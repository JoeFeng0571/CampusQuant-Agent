"""
api/server.py — FastAPI SSE 流式分析后端

端点列表:
  POST /api/v1/analyze          → Server-Sent Events (SSE) 流式分析
  POST /api/v1/health-check     → 持仓体检（JSON 请求/响应）
  POST /api/v1/chat             → 财商学长 AI 对话（Qwen）
  POST /api/v1/trade/order      → 模拟撮合下单
  GET  /api/v1/market/quotes    → 实时行情列表
  GET  /api/v1/portfolio/summary → 虚拟账户持仓摘要
  GET  /api/v1/health           → 健康检查
  GET  /api/v1/graph/mermaid    → 图拓扑 Mermaid 字符串

SSE 事件格式:
  每个事件结构为 JSON:
  {
    "event":     "<event_type>",    // 见下方事件类型说明
    "node":      "<node_name>",     // 产生此事件的节点名称
    "message":   "<human_msg>",     // 人类可读摘要
    "data":      { ... },           // 节点输出的结构化数据
    "timestamp": "<ISO8601>",       // 事件时间戳
    "seq":       <int>              // 事件序号（从1开始）
  }

事件类型 (event):
  node_start   — 节点开始执行（含 node 名称）
  node_complete— 节点执行完成（含 data 输出）
  conflict     — 检测到基本面/技术面冲突，触发辩论
  debate       — 辩论完成
  risk_check   — 风控审批结果
  risk_retry   — 风控拒绝，要求修订
  trade_order  — 最终交易指令生成
  complete     — 全流程完成
  error        — 发生错误

启动命令:
  uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field
from utils.market_classifier import MarketClassifier
from config import config as _cfg

# ════════════════════════════════════════════════════════════════
# Proxy Monkey Patch — 国内金融域名强制绕过 TUN/全局代理
# 问题背景: 开发机开启 TUN 全局代理（访问 yfinance 美股数据），
#   导致 akshare 访问国内东方财富等接口时 ProxyError。
#   NO_PROXY 环境变量在 TUN 模式下失效，必须在 requests 层劫持。
# ════════════════════════════════════════════════════════════════
import requests as _requests
from urllib.parse import urlparse as _urlparse

_original_session_request = _requests.Session.request

_CN_FINANCIAL_DOMAINS = [
    "eastmoney.com",
    "10jqka.com.cn",
    "sina.com.cn",
    "emoney.cn",
    "xueqiu.com",
    "hexun.com",
    "gtimg.com",
    "sse.com.cn",
    "szse.cn",
]


def _proxy_bypass_request(self, method, url, **kwargs):
    """
    对国内金融域名强制禁用代理（proxies=None），其余请求保持原有代理配置。
    这样 yfinance/OpenAI 等境外请求仍走 TUN 代理，akshare 走直连。
    """
    try:
        hostname = _urlparse(url).hostname or ""
        if any(domain in hostname for domain in _CN_FINANCIAL_DOMAINS):
            kwargs["proxies"] = {"http": None, "https": None}
            logger.debug(f"[proxy_patch] 直连(绕过代理): {hostname}")
    except Exception:
        pass  # 解析失败不影响正常请求
    return _original_session_request(self, method, url, **kwargs)


_requests.Session.request = _proxy_bypass_request
logger.info("✅ Proxy Monkey Patch 已激活：国内金融域名将绕过全局代理")

# ════════════════════════════════════════════════════════════════
# 应用初始化
# ════════════════════════════════════════════════════════════════

app = FastAPI(
    title="Multi-Agent Trading System API",
    description="LangGraph + FAISS RAG 驱动的量化交易多智能体分析服务",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS（允许 Streamlit / Vue / React 前端跨域调用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ════════════════════════════════════════════════════════════════
# 启动时初始化（FAISS 知识库 + LangGraph 图）
# ════════════════════════════════════════════════════════════════

_compiled_graph = None


@app.on_event("startup")
async def startup_event():
    """应用启动时预热 FAISS 知识库和 LangGraph 图"""
    global _compiled_graph
    logger.info("🚀 Trading System API 启动中...")

    # 1. 初始化 FAISS 知识库
    try:
        from tools.knowledge_base import init_knowledge_base
        ok = init_knowledge_base()
        logger.info(f"{'✅' if ok else '⚠️'} FAISS 知识库初始化: {'成功' if ok else '降级模式'}")
    except Exception as e:
        logger.error(f"❌ 知识库初始化失败: {e}")

    # 2. 构建 LangGraph 图（带 MemorySaver）
    try:
        from graph.builder import build_graph_with_memory
        _compiled_graph = build_graph_with_memory()
        logger.info("✅ LangGraph 图构建完成")
    except Exception as e:
        logger.error(f"❌ 图构建失败: {e}")

    logger.info("✅ API 服务启动完成，监听请求...")


# ════════════════════════════════════════════════════════════════
# 请求/响应模型
# ════════════════════════════════════════════════════════════════

class AnalyzeRequest(BaseModel):
    symbol: str = Field(..., description="交易标的代码 (如 AAPL / 600519.SH)")
    days:   int = Field(default=180, ge=30, le=365, description="历史数据天数")


class HealthResponse(BaseModel):
    status:      str
    version:     str
    graph_ready: bool
    kb_ready:    bool
    timestamp:   str


class PositionItem(BaseModel):
    """持仓体检单条持仓（供 /api/v1/health-check 请求使用）"""
    symbol:   str   = Field(..., description="标的代码，如 600519.SH / AAPL")
    quantity: float = Field(..., ge=0, description="持仓数量（股/份）")
    avg_cost: float = Field(..., ge=0, description="平均持仓成本价")


class PortfolioCheckRequest(BaseModel):
    """POST /api/v1/health-check 请求体"""
    positions: list[PositionItem] = Field(..., min_length=1, description="持仓列表")


class ChatRequest(BaseModel):
    """POST /api/v1/chat 请求体"""
    message:  str = Field(..., min_length=1, description="用户消息")
    history:  list[dict] = Field(default_factory=list, description="历史对话（可选）")


class TradeOrderRequest(BaseModel):
    """POST /api/v1/trade/order 请求体"""
    symbol:   str   = Field(..., description="标的代码，如 600519.SH / AAPL")
    action:   str   = Field(..., pattern="^(BUY|SELL)$", description="BUY 或 SELL")
    quantity: float = Field(..., gt=0, description="数量（股/份）")


# ════════════════════════════════════════════════════════════════
# SSE 事件构建工具
# ════════════════════════════════════════════════════════════════

def _make_sse_event(
    event:    str,
    node:     str,
    message:  str,
    data:     Optional[dict] = None,
    seq:      int = 0,
) -> str:
    """
    将事件信息序列化为 SSE 格式字符串。

    SSE 协议格式:
      event: <event_type>\\n
      data: <JSON>\\n
      \\n
    """
    payload = {
        "event":     event,
        "node":      node,
        "message":   message,
        "data":      data or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "seq":       seq,
    }
    json_str = json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {json_str}\n\n"


# ════════════════════════════════════════════════════════════════
# 核心：LangGraph astream_events → SSE 生成器
# ════════════════════════════════════════════════════════════════

# 节点名称 → 人类可读标签映射
_NODE_LABELS = {
    "data_node":        "数据情报员",
    "rag_node":         "RAG 知识检索",
    "fundamental_node": "基本面分析师",
    "technical_node":   "技术分析师",
    "sentiment_node":   "舆情分析师",
    "portfolio_node":   "基金经理",
    "debate_node":      "多空辩论裁决",
    "risk_node":        "风险控制官",
    "trade_executor":   "交易指令生成",
}


async def _stream_graph_events(
    symbol:    str,
    thread_id: str,
) -> AsyncGenerator[str, None]:
    """
    调用 LangGraph .astream_events()，将图节点事件转译为 SSE 数据流。

    LangGraph astream_events API 返回的事件类型:
      - on_chain_start  : 图/节点开始
      - on_chain_end    : 图/节点结束（含输出）
      - on_chain_stream : 流式输出中间值

    我们只关注各节点（Node）的 start / end 事件。
    """
    from graph.builder import make_initial_state

    initial_state = make_initial_state(symbol)
    config        = {"configurable": {"thread_id": thread_id}}
    seq           = 0

    # ── 发送开始事件 ──────────────────────────────────────────
    seq += 1
    yield _make_sse_event(
        event="start",
        node="system",
        message=f"开始分析 {symbol}，LangGraph 多智能体引擎启动...",
        data={"symbol": symbol, "thread_id": thread_id},
        seq=seq,
    )
    await asyncio.sleep(0)   # 让事件循环有机会 flush

    if _compiled_graph is None:
        seq += 1
        yield _make_sse_event(
            event="error",
            node="system",
            message="LangGraph 图尚未初始化，请稍后重试",
            seq=seq,
        )
        return

    # ── 追踪已通知的节点（避免重复 node_start）────────────────
    notified_start: set[str] = set()
    last_state:     dict     = {}
    _graph_error:   str | None = None  # 记录图执行异常，用于降级研报

    try:
        async for event in _compiled_graph.astream_events(
            initial_state,
            config=config,
            version="v2",            # 使用 LangGraph astream_events v2
        ):
            kind      = event.get("event", "")
            node_name = event.get("name", "")
            run_id    = event.get("run_id", "")

            # ── 节点开始 ──────────────────────────────────────
            if kind == "on_chain_start" and node_name in _NODE_LABELS:
                if node_name not in notified_start:
                    notified_start.add(node_name)
                    label = _NODE_LABELS[node_name]
                    seq += 1
                    yield _make_sse_event(
                        event="node_start",
                        node=node_name,
                        message=f"⚙️ {label} 开始工作...",
                        data={"label": label},
                        seq=seq,
                    )
                    await asyncio.sleep(0)

            # ── 节点完成 ──────────────────────────────────────
            elif kind == "on_chain_end" and node_name in _NODE_LABELS:
                output    = event.get("data", {}).get("output", {})
                label     = _NODE_LABELS[node_name]

                # 更新最新 state 快照（合并节点输出）
                if isinstance(output, dict):
                    last_state.update(output)

                # 根据节点类型构建特定消息与数据
                sse_event_type = "node_complete"
                extra_data     = {}
                human_msg      = f"✅ {label} 完成"

                if node_name == "data_node":
                    md = output.get("market_data", {})
                    human_msg  = (
                        f"数据获取完成: {symbol} | 最新价 {md.get('latest_price', 'N/A')} "
                        f"| 信号 {md.get('indicators', {}).get('tech_signal', 'N/A')}"
                    )
                    extra_data = {
                        "latest_price":    md.get("latest_price"),
                        "price_change_pct": md.get("price_change_pct"),
                        "tech_signal":      md.get("indicators", {}).get("tech_signal"),
                    }

                elif node_name == "rag_node":
                    rag = output.get("rag_context", "")
                    human_msg  = f"RAG 知识检索完成，获取 {len(rag)} 字符上下文"
                    extra_data = {"context_length": len(rag)}

                elif node_name == "fundamental_node":
                    report = output.get("fundamental_report", {}) or {}
                    human_msg  = (
                        f"基本面分析: {report.get('recommendation', 'N/A')} "
                        f"(置信度 {report.get('confidence', 0):.0%})"
                    )
                    extra_data = {
                        "recommendation": report.get("recommendation"),
                        "confidence":     report.get("confidence"),
                        "signal_strength": report.get("signal_strength"),
                        "reasoning_preview": (report.get("reasoning", "")[:100] + "..."),
                    }

                elif node_name == "technical_node":
                    report = output.get("technical_report", {}) or {}
                    human_msg  = (
                        f"技术分析: {report.get('recommendation', 'N/A')} "
                        f"(置信度 {report.get('confidence', 0):.0%})"
                    )
                    extra_data = {
                        "recommendation": report.get("recommendation"),
                        "confidence":     report.get("confidence"),
                        "signal_strength": report.get("signal_strength"),
                    }

                elif node_name == "sentiment_node":
                    report = output.get("sentiment_report", {}) or {}
                    human_msg  = (
                        f"舆情分析: {report.get('recommendation', 'N/A')} "
                        f"(置信度 {report.get('confidence', 0):.0%})"
                    )
                    extra_data = {
                        "recommendation": report.get("recommendation"),
                        "confidence":     report.get("confidence"),
                    }

                elif node_name == "portfolio_node":
                    has_conflict = output.get("has_conflict", False)
                    if has_conflict:
                        sse_event_type = "conflict"
                        human_msg = "⚡ 检测到基本面与技术面意见冲突，启动多空辩论机制..."
                        extra_data = {"conflict": True}
                    else:
                        human_msg = "基金经理综合决策完成，提交风控审核..."
                        extra_data = {"conflict": False}

                elif node_name == "debate_node":
                    outcome    = output.get("debate_outcome", {}) or {}
                    rounds     = output.get("debate_rounds", 1)
                    sse_event_type = "debate"
                    human_msg  = (
                        f"⚖️ 辩论第{rounds}轮裁决: {outcome.get('resolved_recommendation', 'N/A')} "
                        f"(置信度 {outcome.get('confidence_after_debate', 0):.0%}) "
                        f"— {outcome.get('deciding_factor', '')[:60]}"
                    )
                    extra_data = {
                        "resolved_recommendation": outcome.get("resolved_recommendation"),
                        "confidence_after_debate":  outcome.get("confidence_after_debate"),
                        "deciding_factor":          outcome.get("deciding_factor"),
                        "debate_rounds":            rounds,
                    }

                elif node_name == "risk_node":
                    rd         = output.get("risk_decision", {}) or {}
                    retries    = output.get("risk_rejection_count", 0)
                    approval   = rd.get("approval_status", "N/A")
                    status_map = {"APPROVED": "✅", "CONDITIONAL": "⚠️", "REJECTED": "❌"}
                    sse_event_type = "risk_check"

                    if approval == "REJECTED":
                        sse_event_type = "risk_retry"
                        human_msg = (
                            f"❌ 风控拒绝（第{retries}次）: {rd.get('rejection_reason', '')} "
                            f"→ 要求基金经理修订方案"
                        )
                    else:
                        human_msg = (
                            f"{status_map.get(approval, '?')} 风控审批: {approval} "
                            f"| 风险 {rd.get('risk_level')} "
                            f"| 仓位 {rd.get('position_pct', 0):.0f}%"
                        )
                    extra_data = {
                        "approval_status": approval,
                        "risk_level":      rd.get("risk_level"),
                        "position_pct":    rd.get("position_pct"),
                        "stop_loss_pct":   rd.get("stop_loss_pct"),
                        "take_profit_pct": rd.get("take_profit_pct"),
                        "rejection_reason": rd.get("rejection_reason"),
                    }

                elif node_name == "trade_executor":
                    order          = output.get("trade_order", {}) or {}
                    sse_event_type = "trade_order"
                    human_msg      = (
                        f"🎯 交易指令: {order.get('action', 'N/A')} {symbol} "
                        f"| 仓位 {order.get('quantity_pct', 0):.0f}% "
                        f"| 止损 {order.get('stop_loss')} "
                        f"| 止盈 {order.get('take_profit')}"
                    )
                    extra_data = order

                seq += 1
                yield _make_sse_event(
                    event=sse_event_type,
                    node=node_name,
                    message=human_msg,
                    data=extra_data,
                    seq=seq,
                )
                await asyncio.sleep(0)

    except Exception as e:
        logger.error(f"[stream] 图执行异常: {e}", exc_info=True)
        _graph_error = str(e)
        seq += 1
        yield _make_sse_event(
            event="error",
            node="system",
            message=f"分析过程异常: {str(e)}",
            data={"error": str(e)},
            seq=seq,
        )
        # 不 return：继续构建降级完成事件，确保前端能渲染出部分结果

    # ── 发送完成事件（附最终 trade_order + 研报 + 图表数据）──────
    # Phase 3 兜底：无论图执行是否成功，final_order 永远为 dict（不为 None）
    seq += 1
    final_order = last_state.get("trade_order") or {}

    # 编译 Markdown 深度研报
    fundamental = last_state.get("fundamental_report") or {}
    technical   = last_state.get("technical_report")   or {}
    sentiment   = last_state.get("sentiment_report")   or {}
    debate      = last_state.get("debate_outcome")      or {}
    risk        = last_state.get("risk_decision")       or {}

    def _pct(v):
        try: return f"{float(v):.1%}"
        except: return str(v)

    _error_banner = (
        f"\n> ⚠ **分析流程异常中断**（{_graph_error}）。以下为各节点已完成的部分结果，供参考。\n\n---\n\n"
        if _graph_error else ""
    )
    markdown_report = f"""# {symbol} · 多智能体深度研报

> 生成时间：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}　｜　分析引擎：LangGraph Multi-Agent
{_error_banner}
---

## 一、基本面分析

| 指标 | 结论 |
|------|------|
| 综合建议 | **{fundamental.get('recommendation', 'N/A')}** |
| 置信度   | {_pct(fundamental.get('confidence', 0))} |
| 信号强度 | {fundamental.get('signal_strength', 'N/A')} |

{fundamental.get('reasoning', '暂无详细推理') or '暂无详细推理'}

---

## 二、技术面分析

| 指标 | 结论 |
|------|------|
| 综合建议 | **{technical.get('recommendation', 'N/A')}** |
| 置信度   | {_pct(technical.get('confidence', 0))} |
| 信号强度 | {technical.get('signal_strength', 'N/A')} |

{technical.get('reasoning', '暂无详细推理') or '暂无详细推理'}

---

## 三、市场情绪分析

| 指标 | 结论 |
|------|------|
| 综合建议 | **{sentiment.get('recommendation', 'N/A')}** |
| 置信度   | {_pct(sentiment.get('confidence', 0))} |

{sentiment.get('reasoning', '暂无详细推理') or '暂无详细推理'}

---

## 四、风控决策

| 指标 | 数值 |
|------|------|
| 审批状态 | **{risk.get('approval_status', 'N/A')}** |
| 建议仓位 | {risk.get('position_pct', 0):.1f}% |
| 止损线   | {risk.get('stop_loss_pct', 0):.1f}% |
| 止盈线   | {risk.get('take_profit_pct', 0):.1f}% |
| 风险等级 | {risk.get('risk_level', 'N/A')} |

{f"> 辩论裁决：{debate.get('resolved_recommendation','N/A')} | 决定因素：{debate.get('deciding_factor','')}" if debate else ""}

---

## 五、最终交易指令

| 字段 | 值 |
|------|----|
| 操作方向 | **{final_order.get('action', 'N/A')}** |
| 建议仓位 | {final_order.get('quantity_pct', 0):.1f}% |
| 止损价   | {final_order.get('stop_loss', 'N/A')} |
| 止盈价   | {final_order.get('take_profit', 'N/A')} |
| 置信度   | {_pct(final_order.get('confidence', 0))} |

> **核心逻辑**：{final_order.get('rationale', '暂无')}

---

⚠ *本研报由 AI 多智能体自动生成，仅供学习参考，不构成投资建议。请遵守大学生守则：单股仓位 ≤ 15%，务必设置止损，切勿加杠杆。*
"""

    # 图表数据：从基本面 key_metrics 中提取实际历年数据
    key_metrics  = fundamental.get("key_metrics") or {}
    revenue_data = key_metrics.get("revenue_history") or []
    profit_data  = key_metrics.get("profit_history")  or []
    data_years   = key_metrics.get("years") or []
    # 优先使用真实历史年份；无数据时回退到近5年占位
    if data_years and revenue_data:
        chart_years  = [str(y) for y in data_years[-5:]]
        revenue_vals = [(v or 0) for v in revenue_data[-5:]]
        profit_vals  = [(v or 0) for v in profit_data[-5:]] if profit_data else [0] * len(chart_years)
        # 长度对齐
        n = len(chart_years)
        revenue_vals = (revenue_vals + [0] * n)[:n]
        profit_vals  = (profit_vals  + [0] * n)[:n]
    else:
        current_year = datetime.now(timezone.utc).year
        # 使用上一年往前推 4 年（当年财报通常未出齐）
        chart_years  = [str(current_year - 5 + i) for i in range(5)]
        revenue_vals = [0, 0, 0, 0, 0]
        profit_vals  = [0, 0, 0, 0, 0]
    # 若全为 0，提示前端"数据不足"
    has_chart_data = any(v != 0 for v in revenue_vals + profit_vals)

    # Phase 3 兜底：financial_chart_data / final_markdown_report 始终下发，前端无需防 undefined
    _chart_payload = {
        "years":         chart_years,
        "revenue":       revenue_vals,
        "profit":        profit_vals,
        "has_data":      has_chart_data,
        "revenue_label": key_metrics.get("revenue_label", "营业收入（亿元）"),
        "profit_label":  key_metrics.get("profit_label",  "净利润（亿元）"),
        "revenue_composition": key_metrics.get("revenue_composition", {}),
        "performance_trend":   key_metrics.get("performance_trend", {}),
    }
    yield _make_sse_event(
        event="complete",
        node="system",
        message=f"✅ 分析完成: {symbol} → {final_order.get('action', 'N/A')} "
                f"(仓位 {final_order.get('quantity_pct', 0):.0f}%)",
        data={
            "symbol":                symbol,
            "trade_order":           final_order,
            "status":                "completed",
            "final_markdown_report": markdown_report or "> 研报生成失败，请重试。",
            "financial_chart_data":  _chart_payload,
        },
        seq=seq,
    )


# ════════════════════════════════════════════════════════════════
# API 端点
# ════════════════════════════════════════════════════════════════

@app.post(
    "/api/v1/analyze",
    summary="流式分析交易标的",
    description=(
        "接收交易标的代码，启动 LangGraph 多智能体分析流程。\n"
        "通过 Server-Sent Events (SSE) 实时推送每个节点的分析进度与结果。\n\n"
        "客户端需使用 EventSource 或 httpx streaming 解析 SSE 事件流。"
    ),
    response_description="SSE 事件流（Content-Type: text/event-stream）",
)
async def analyze_symbol(request: AnalyzeRequest):
    """POST /api/v1/analyze — SSE 流式分析"""
    raw_symbol = request.symbol.strip()
    if not raw_symbol:
        raise HTTPException(status_code=400, detail="symbol 不能为空")

    # 模糊搜索拦截：中文/英文名称 → 标准交易代码
    symbol    = MarketClassifier.fuzzy_match(raw_symbol)
    thread_id = str(uuid.uuid4())

    logger.info(f"[API] 收到分析请求: 原始='{raw_symbol}' → 标准='{symbol}' | thread_id={thread_id}")

    return StreamingResponse(
        _stream_graph_events(symbol, thread_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",    # Nginx 禁用缓冲
            "X-Thread-Id":       thread_id,
        },
    )


@app.get("/api/v1/health", response_model=HealthResponse)
async def health_check():
    """GET /api/v1/health — 健康检查"""
    from tools.knowledge_base import _ensemble_retriever

    return HealthResponse(
        status      = "ok",
        version     = "2.0.0",
        graph_ready = _compiled_graph is not None,
        kb_ready    = _ensemble_retriever is not None,
        timestamp   = datetime.now(timezone.utc).isoformat(),
    )


@app.get("/api/v1/graph/mermaid", summary="获取图拓扑 Mermaid 字符串")
async def get_graph_mermaid():
    """GET /api/v1/graph/mermaid — 返回 LangGraph 拓扑的 Mermaid 图字符串"""
    mermaid = """flowchart TD
    START([START]) --> data_node[数据情报员\\ndata_node]
    data_node --> fundamental_node[基本面分析师\\nfundamental_node]
    data_node --> technical_node[技术分析师\\ntechnical_node]
    data_node --> sentiment_node[舆情分析师\\nsentiment_node]
    data_node --> rag_node[RAG知识检索\\nrag_node]
    fundamental_node --> portfolio_node
    technical_node --> portfolio_node
    sentiment_node --> portfolio_node
    rag_node --> portfolio_node[基金经理\\nportfolio_node]
    portfolio_node -->|冲突检测| debate_node[多空辩论\\ndebate_node]
    portfolio_node -->|无冲突| risk_node[风控官\\nrisk_node]
    debate_node --> portfolio_node
    risk_node -->|REJECTED| portfolio_node
    risk_node -->|APPROVED| trade_executor[交易指令\\ntrade_executor]
    trade_executor --> END([END])"""

    if _compiled_graph:
        try:
            mermaid = _compiled_graph.get_graph().draw_mermaid()
        except Exception:
            pass  # 使用静态版本

    return {"mermaid": mermaid}


# ════════════════════════════════════════════════════════════════
# 持仓体检端点
# ════════════════════════════════════════════════════════════════

@app.post(
    "/api/v1/health-check",
    summary="持仓体检",
    description=(
        "接收持仓列表，启动 health_node 独立分支（START→health_node→END），\n"
        "返回持仓健康评分、集中度/回撤/流动性指标与 AI 优化建议。"
    ),
)
async def portfolio_health_check(request: PortfolioCheckRequest):
    """POST /api/v1/health-check — 持仓健康诊断（JSON 请求/响应）"""
    from graph.builder import build_health_graph, make_health_initial_state
    from graph.state import PortfolioPosition
    from utils.market_classifier import MarketClassifier

    # 构建 PortfolioPosition 列表
    positions = []
    for item in request.positions:
        market_type, _ = MarketClassifier.classify(item.symbol)
        positions.append(
            PortfolioPosition(
                symbol=item.symbol,
                market_type=market_type.value,
                quantity=item.quantity,
                avg_cost=item.avg_cost,
            ).model_dump()
        )

    if not positions:
        raise HTTPException(status_code=400, detail="持仓列表不能为空")

    # 运行持仓体检图（health_node 是 async def，必须用 ainvoke 而非 invoke）
    try:
        health_graph = build_health_graph()
        initial_state = make_health_initial_state(positions)
        result_state = await health_graph.ainvoke(initial_state)
    except Exception as e:
        logger.error(f"[health-check] 体检图执行失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"持仓体检执行失败: {str(e)}")

    health_report = result_state.get("health_report")
    if not health_report:
        raise HTTPException(status_code=500, detail="health_node 未返回体检报告，请检查 LLM 配置")

    return {
        "status": "ok",
        "health_report": health_report,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ════════════════════════════════════════════════════════════════
# 行情快讯 & 持仓摘要端点
# ════════════════════════════════════════════════════════════════

# 各市场默认观察股票列表
_MARKET_WATCHLISTS: dict[str, list[str]] = {
    "a":  ["600519.SH", "000858.SZ", "601318.SH", "002594.SZ",
           "300750.SZ", "600036.SH", "601899.SH", "000001.SZ"],
    "hk": ["00700.HK", "09988.HK", "03690.HK", "02318.HK", "01398.HK", "09999.HK"],
    "us": ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA", "META"],
}

# 后端内存模拟持仓（成本价基于某日收盘，演示用）
_MOCK_PORTFOLIO: list[dict] = [
    {"symbol": "600519.SH", "name": "贵州茅台", "quantity": 10,  "avg_cost": 1680.00},
    {"symbol": "000858.SZ", "name": "五粮液",   "quantity": 50,  "avg_cost":  148.00},
    {"symbol": "AAPL",      "name": "苹果",     "quantity": 20,  "avg_cost":  185.00},
    {"symbol": "00700.HK",  "name": "腾讯控股",  "quantity": 100, "avg_cost":  370.00},
]


# ════════════════════════════════════════════════════════════════
# 财商学长 AI 对话
# ════════════════════════════════════════════════════════════════

_CAISHANG_SYSTEM_PROMPT = (
    "你叫财财学长，是 CampusQuant 的 AI 财商导师，专门服务中国在校大学生。\n"
    "请用亲切、通俗的语言，结合大学生的实际情况（资金有限、没有收入、需要学费生活费），"
    "认真解答他们关于理财、基金、股票、债券、风险管理、经济常识等泛金融问题。\n\n"
    "回答要求：\n"
    "1. 直接给出实质性回答，不要说'我无法给出建议'——要像一个懂行的学长一样帮人分析利弊。\n"
    "2. 用大学生听得懂的语言，结合具体场景举例，避免纯理论堆砌。\n"
    "3. 强调风险教育：提醒止损、仓位控制、不用生活费炒股等大学生守则。\n"
    "4. 如涉及具体标的（如沪深300ETF、主动基金），可客观对比优缺点，但不做最终买卖决定。\n"
    "5. 禁止推荐任何具体真实券商或第三方平台。\n"
    "6. 非金融无关话题礼貌拒绝，说明只专注投资教育。\n"
    "7. 【严格边界】严禁强行分析实时行情或最新财报！"
    "当用户要求分析某只具体股票（如腾讯、茅台、苹果）、解读最新财报或预测近期走势时，"
    "必须明确告知：你作为答疑学长不具备实时联网看盘的能力，你的知识存在截止日期，无法保证数据准确。"
    "然后亲切引导用户：'你可以在本平台的【个股分析】页面，输入股票代码（如 00700.HK / 600519.SH / AAPL），"
    "召唤多智能体引擎获取基于实时数据的深度研报，那比我靠谱多了！'"
)


@app.post("/api/v1/chat", summary="财商学长 AI 对话（Qwen）")
async def chat_with_advisor(request: ChatRequest):
    """
    POST /api/v1/chat

    调用 LLMClient（DashScope/Qwen）生成财商教育回复。
    强制注入 System Prompt，确保回答聚焦于投资理财教育。
    """
    try:
        from utils.llm_client import LLMClient
        loop = asyncio.get_event_loop()

        def _call_llm():
            client = LLMClient(provider="dashscope")
            # 将 history 拼到 prompt 前
            history_text = ""
            for turn in request.history[-6:]:   # 最多保留 6 轮上下文
                role = "用户" if turn.get("role") == "user" else "学长"
                history_text += f"{role}：{turn.get('content', '')}\n"
            prompt = history_text + f"用户：{request.message}"
            return client.generate(
                prompt=prompt,
                system_prompt=_CAISHANG_SYSTEM_PROMPT,
                temperature=0.6,
                max_tokens=800,
            )

        reply = await loop.run_in_executor(None, _call_llm)
        return {"reply": reply, "model": _cfg.DASHSCOPE_MODEL, "timestamp": datetime.now(timezone.utc).isoformat()}

    except Exception as e:
        logger.error(f"[chat] LLM 调用失败: {e}")
        raise HTTPException(status_code=502, detail=f"AI 对话服务暂时不可用: {str(e)}")


# ════════════════════════════════════════════════════════════════
# 模拟撮合下单
# ════════════════════════════════════════════════════════════════

@app.post("/api/v1/trade/order", summary="模拟撮合下单")
async def place_trade_order(request: TradeOrderRequest):
    """
    POST /api/v1/trade/order

    从虚拟账户买入或卖出指定标的。
    后端调用 get_spot_price_raw() 获取实时现价作为成交价。
    Phase 4 兜底：价格获取失败时返回明确错误，不崩溃。
    """
    from api.mock_exchange import get_account
    from utils.market_classifier import MarketClassifier

    symbol = request.symbol.strip().upper()
    symbol = MarketClassifier.fuzzy_match(symbol)
    market_type, _ = MarketClassifier.classify(symbol)

    account = get_account()
    loop    = asyncio.get_event_loop()

    try:
        result = await loop.run_in_executor(
            None,
            lambda: account.place_order(
                symbol=symbol,
                action=request.action,
                quantity=request.quantity,
                market_type=market_type.value,
            )
        )
    except Exception as e:
        logger.error(f"[trade/order] 撮合异常: {e}")
        raise HTTPException(status_code=502, detail=f"撮合引擎异常: {str(e)}")

    if not result.success:
        # Phase 4: 明确错误提示，HTTP 200 + success=False（前端可展示）
        return {
            "success":   False,
            "error":     result.error,
            "symbol":    symbol,
            "action":    request.action,
            "timestamp": result.timestamp,
        }

    return {
        "success":       True,
        "symbol":        result.symbol,
        "action":        result.action,
        "quantity":      result.quantity,
        "exec_price":    result.exec_price,
        "is_spot_price": result.is_spot_price,
        "amount":        result.amount,
        "fee":           result.fee,
        "cash_before":   result.cash_before,
        "cash_after":    result.cash_after,
        "simulated":     True,
        "timestamp":     result.timestamp,
    }


@app.get("/api/v1/market/search", summary="股票搜索联想（输入中英文/拼音/代码）")
async def search_stocks(q: str = ""):
    """
    GET /api/v1/market/search?q={query}

    对用户输入做多路模糊匹配，返回联想股票列表。
    优先查本地字典，再调新浪 Suggest API，总超时 3s。
    返回格式: { "suggestions": [{"symbol", "name", "type"}, ...] }
    """
    if not q or not q.strip():
        return {"suggestions": [], "query": q}

    try:
        loop = asyncio.get_event_loop()
        suggestions = await loop.run_in_executor(
            None,
            lambda: MarketClassifier.search_stock_suggestions(q.strip(), limit=8),
        )
    except Exception as e:
        logger.warning(f"[market/search] 搜索失败: {e}")
        suggestions = []

    return {"suggestions": suggestions, "query": q}


@app.get("/api/v1/market/quotes", summary="获取市场实时行情列表")
async def get_market_quotes(market: str = "a"):
    """
    GET /api/v1/market/quotes?market=a|hk|us

    调用 get_batch_quotes_raw() 获取指定市场的观察股票实时价格。
    返回标准化的报价列表，前端 market.html 使用。
    """
    market = market.lower()
    if market not in _MARKET_WATCHLISTS:
        raise HTTPException(status_code=400, detail=f"market 参数无效，可选: a / hk / us，收到: {market}")

    symbols = _MARKET_WATCHLISTS[market]

    try:
        from tools.market_data import get_batch_quotes_raw
        loop = asyncio.get_event_loop()
        quotes = await loop.run_in_executor(None, get_batch_quotes_raw, symbols, market)
    except Exception as e:
        logger.error(f"[market/quotes] 批量行情获取失败: {e}")
        raise HTTPException(status_code=502, detail=f"行情获取失败: {str(e)}")

    return {
        "market":    market,
        "quotes":    quotes,
        "count":     len(quotes),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/portfolio/summary", summary="获取虚拟账户持仓摘要（含实时估值）")
async def get_portfolio_summary():
    """
    GET /api/v1/portfolio/summary

    读取 mock_exchange 虚拟账户的真实持仓，并发调用 get_spot_price_raw()
    获取实时现价，计算每个持仓的市值、浮动盈亏，以及账户汇总指标。
    """
    from api.mock_exchange import get_account
    from tools.market_data import get_spot_price_raw

    account  = get_account()
    snapshot = account.snapshot()
    raw_positions = snapshot["positions"]   # list[dict] with symbol/name/quantity/avg_cost

    async def enrich_position(pos: dict) -> dict:
        loop = asyncio.get_event_loop()
        try:
            spot = await loop.run_in_executor(None, get_spot_price_raw, pos["symbol"])
        except Exception:
            spot = {"price": pos["avg_cost"], "change_pct": 0.0, "is_fallback": True}

        current_price  = spot.get("price") or pos["avg_cost"]
        change_pct     = spot.get("change_pct") or 0.0
        cost_value     = pos["quantity"] * pos["avg_cost"]
        market_value   = pos["quantity"] * current_price
        unrealized_pnl = market_value - cost_value
        pnl_pct        = (unrealized_pnl / cost_value * 100) if cost_value else 0.0

        return {
            **pos,
            "current_price":  round(current_price, 3),
            "change_pct":     round(change_pct, 2),
            "cost_value":     round(cost_value, 2),
            "market_value":   round(market_value, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "pnl_pct":        round(pnl_pct, 2),
            "is_fallback":    spot.get("is_fallback", False),
        }

    try:
        enriched = await asyncio.gather(*[enrich_position(p) for p in raw_positions])
    except Exception as e:
        logger.error(f"[portfolio/summary] 持仓摘要计算失败: {e}")
        raise HTTPException(status_code=502, detail=f"持仓摘要获取失败: {str(e)}")

    total_cost   = sum(p["cost_value"]     for p in enriched)
    total_market = sum(p["market_value"]   for p in enriched)
    total_pnl    = sum(p["unrealized_pnl"] for p in enriched)
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else 0.0
    today_pnl    = sum(p["market_value"] * p["change_pct"] / 100 for p in enriched)
    cash         = snapshot["cash"]
    total_assets = round(cash + total_market, 2)

    return {
        "cash":          round(cash, 2),
        "total_assets":  total_assets,
        "positions":     list(enriched),
        "total_cost":    round(total_cost, 2),
        "total_market":  round(total_market, 2),
        "total_pnl":     round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "today_pnl":     round(today_pnl, 2),
        "order_count":   snapshot["order_count"],
        "timestamp":     datetime.now(timezone.utc).isoformat(),
    }


# ════════════════════════════════════════════════════════════════
# 大盘指数 & 市场快讯端点
# ════════════════════════════════════════════════════════════════

@app.get("/api/v1/market/indices", summary="获取主要大盘指数实时行情")
async def get_market_indices():
    """
    GET /api/v1/market/indices

    返回 A股（上证/深证/创业板/科创50）、恒生指数、纳斯达克100、标普500、道琼斯
    的实时点位与涨跌幅。

    使用 akshare:
      - A股指数: stock_zh_index_spot_em（东方财富实时指数）
      - 全球指数: index_global_spot_em（东方财富全球指数）
    """
    try:
        from tools.market_data import get_market_indices_raw
        loop = asyncio.get_event_loop()
        indices = await loop.run_in_executor(None, get_market_indices_raw)
    except Exception as e:
        logger.error(f"[market/indices] 获取失败: {e}")
        raise HTTPException(status_code=502, detail=f"大盘指数获取失败: {str(e)}")

    return {
        "indices":   indices,
        "count":     len(indices),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/market/news", summary="获取财联社全球财经快讯")
async def get_market_news(limit: int = 20):
    """
    GET /api/v1/market/news?limit=20

    调用 akshare.stock_info_global_cls() 获取财联社 7x24 全球财经快讯。
    返回最新 limit 条资讯（标题 + 时间），用于 market.html 右侧资讯面板。
    """
    limit = max(1, min(limit, 50))   # 限制 1-50 条
    try:
        from tools.market_data import get_market_news_raw
        loop = asyncio.get_event_loop()
        news = await loop.run_in_executor(None, get_market_news_raw, limit)
    except Exception as e:
        logger.error(f"[market/news] 快讯获取失败: {e}")
        raise HTTPException(status_code=502, detail=f"快讯获取失败: {str(e)}")

    return {
        "news":      news,
        "count":     len(news),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ════════════════════════════════════════════════════════════════
# 开发模式入口
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
