"""
api/server.py — FastAPI SSE 流式分析后端

端点列表:
  POST /api/v1/analyze      → Server-Sent Events (SSE) 流式分析
  POST /api/v1/health-check → 持仓体检（JSON 请求/响应）
  GET  /api/v1/health       → 健康检查
  GET  /api/v1/graph/mermaid → 图拓扑 Mermaid 字符串

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
        seq += 1
        yield _make_sse_event(
            event="error",
            node="system",
            message=f"分析过程异常: {str(e)}",
            data={"error": str(e)},
            seq=seq,
        )
        return

    # ── 发送完成事件（附最终 trade_order）────────────────────
    seq += 1
    final_order = last_state.get("trade_order", {})
    yield _make_sse_event(
        event="complete",
        node="system",
        message=f"✅ 分析完成: {symbol} → {final_order.get('action', 'N/A')} "
                f"(仓位 {final_order.get('quantity_pct', 0):.0f}%)",
        data={
            "symbol":     symbol,
            "trade_order": final_order,
            "status":     "completed",
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

    # 运行持仓体检图
    try:
        health_graph = build_health_graph()
        initial_state = make_health_initial_state(positions)
        result_state = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: health_graph.invoke(initial_state),
        )
    except Exception as e:
        logger.error(f"[health-check] 体检图执行失败: {e}")
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
