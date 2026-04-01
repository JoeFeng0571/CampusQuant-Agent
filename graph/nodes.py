"""
graph/nodes.py — LangGraph 节点函数集合

图拓扑（执行顺序）:
  START
   └─ data_node                      ← 数据获取节点
       ├─ fundamental_node (并行)     ← 基本面分析师
       ├─ technical_node   (并行)     ← 技术分析师
       ├─ sentiment_node   (并行)     ← 舆情分析师
       └─ rag_node         (并行)     ← RAG 知识检索
           └─ portfolio_node          ← 综合决策 (有条件循环)
               ├─ [冲突] debate_node  ← 多空辩论
               │   └─ portfolio_node  ← 辩论后重新决策
               └─ [无冲突] risk_node  ← 风控审核 (有条件循环)
                   ├─ [拒绝] portfolio_node ← 修订决策
                   └─ [通过] trade_executor ← 生成模拟交易指令
                       └─ END

  持仓体检独立分支（可从 START 单独触发）:
  START → health_node → END

架构改进（来自 TradingAgents-CN-main 精华提取）:
  A. 工具调用防死循环（Anti-Loop）
     借鉴: agents/utils/agent_states.py 的 market_tool_call_count 模式
     实现: _check_tool_limit() 在每次工具调用前检查 tool_call_counts[node]，
           超过 MAX_TOOL_CALLS 后抛出 ToolLimitExceeded，触发降级路径。
  B. Prompt 字典外化管理
     借鉴: TradingAgents-CN 将各 analyst 的 system_prompt 集中管理
     实现: 模块级 _PROMPTS 字典统一存放所有 System Prompt，
           节点函数从 dict 中按 market_type 取值，避免代码中散布长字符串。
  C. 持仓体检节点（health_node）
     新增: 基于 PortfolioPosition 列表输入，输出 PortfolioHealthReport
     特点: 支持大学生场景的严格风控上限（单仓 ≤ 15%），不依赖任何真实交易所 API
  D. 错误分类
     所有节点 except 块中写入 error_type 字段，便于前端 SSE 精准提示

所有节点均为 async 函数，接收 TradingGraphState，返回 dict (部分状态更新)。
LLM 输出全部通过 with_structured_output(PydanticModel) 产生，
彻底消除正则/JSON 手动解析。

严格红线:
  - 绝不引入任何真实交易所 API
  - TradeOrder.simulated 始终为 True，执行指向本地模拟撮合引擎
"""
from __future__ import annotations

import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

import asyncio
import functools
import json
import os
import re as _re_top
from datetime import datetime
from typing import Any, Dict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from loguru import logger

from config import config
from graph.state import (
    MAX_DEBATE_ROUNDS,
    MAX_RISK_RETRIES,
    MAX_TOOL_CALLS,
    AnalystReport,
    DebateOutcome,
    PortfolioHealthReport,
    PortfolioPosition,
    RiskDecision,
    TradeOrder,
    TradingGraphState,
)
from tools.market_data import (
    calculate_technical_indicators,
    get_deep_financial_data,
    get_deep_financial_data_via_relay,
    get_fundamental_data,
    get_market_data,
    get_stock_news,
)
from tools.knowledge_base import search_knowledge_base


# ════════════════════════════════════════════════════════════════
# 内部工具：LLM 工厂函数
# ════════════════════════════════════════════════════════════════

def _build_llm(temperature: float = 0.3):
    """
    根据 config.PRIMARY_LLM_PROVIDER 构建 LangChain ChatModel。
    默认使用阿里云百炼（DashScope/Qwen），备选 OpenAI / Anthropic。

    架构说明: 与 TradingAgents-CN create_llm_by_provider() 对齐，
    保持"单一工厂函数、环境变量驱动"的模式，方便切换 LLM 供应商。
    """
    provider = config.PRIMARY_LLM_PROVIDER.lower()
    # 启动时打印实际使用的模型名称，便于排查环境变量未正确加载的问题
    logger.info(
        f"[_build_llm] provider={provider} | model={config.DASHSCOPE_MODEL!r} "
        f"| QWEN_MODEL_NAME env={os.getenv('QWEN_MODEL_NAME', '<未设置>')!r}"
    )

    # 确保 DashScope 域名绕过本地 TUN 全局代理（防止 RemoteProtocolError 长连接被切断）
    _dashscope_no_proxy = "dashscope.aliyuncs.com,aliyuncs.com"
    _cur_no_proxy = os.environ.get("NO_PROXY", os.environ.get("no_proxy", ""))
    if _dashscope_no_proxy not in _cur_no_proxy:
        os.environ["NO_PROXY"] = (
            _cur_no_proxy + "," + _dashscope_no_proxy if _cur_no_proxy else _dashscope_no_proxy
        )
        os.environ["no_proxy"] = os.environ["NO_PROXY"]

    # 硬超时：200s 适配高峰期大模型并发延迟，防止并行节点永久挂死
    _LLM_TIMEOUT = 200

    if provider == "dashscope":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=config.DASHSCOPE_MODEL,
            api_key=config.DASHSCOPE_API_KEY,
            base_url=config.DASHSCOPE_BASE_URL,
            temperature=temperature,
            max_tokens=4096,          # 防止长 JSON 被提前截断导致 ValidationError
            timeout=_LLM_TIMEOUT,
            request_timeout=_LLM_TIMEOUT,
        )
    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=config.ANTHROPIC_MODEL,
            api_key=config.ANTHROPIC_API_KEY,
            temperature=temperature,
            max_tokens=4096,
            timeout=_LLM_TIMEOUT,
        )
    else:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=config.OPENAI_MODEL,
            api_key=config.OPENAI_API_KEY,
            temperature=temperature,
            max_tokens=4096,
            timeout=_LLM_TIMEOUT,
            request_timeout=_LLM_TIMEOUT,
        )


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _log_entry(node: str, msg: str) -> str:
    return f"[{_ts()}] [{node}] {msg}"


def _sanitize_symbol(s: str) -> str:
    """
    Sanitize user-supplied stock symbol to prevent prompt injection.
    Only allow alphanumeric, dots, hyphens, and carets; max 20 chars.
    """
    if not s:
        return "UNKNOWN"
    cleaned = _re_top.sub(r"[^A-Za-z0-9.\-\^]", "", str(s))
    return cleaned[:20] if cleaned else "UNKNOWN"


# ════════════════════════════════════════════════════════════════
# Anti-Loop 工具调用计数器（借鉴 TradingAgents-CN-main）
# ════════════════════════════════════════════════════════════════

class _ToolLimitExceeded(Exception):
    """工具调用次数超过上限，触发降级路径"""
    pass


def _check_tool_limit(state: TradingGraphState, node_name: str) -> int:
    """
    检查并返回当前节点的工具调用次数。
    超过 MAX_TOOL_CALLS 时抛出 _ToolLimitExceeded。

    借鉴来源: TradingAgents-CN agents/utils/agent_states.py
      market_tool_call_count、news_tool_call_count 等字段 +
      market_analyst.py 中的 max 3 tool calls 防死循环逻辑。

    用法（在节点内调用工具前）:
        count = _check_tool_limit(state, "data_node")
    """
    counts = state.get("tool_call_counts") or {}
    count  = counts.get(node_name, 0)
    if count >= MAX_TOOL_CALLS:
        raise _ToolLimitExceeded(
            f"[{node_name}] 工具调用次数已达上限 {MAX_TOOL_CALLS}，强制降级"
        )
    return count


def _log_node_error(node_name: str, e: Exception) -> None:
    """
    统一节点错误日志：即使 str(e) 为空（如裸 asyncio.TimeoutError），
    也能打印异常类型名称和完整 traceback，便于追踪死因。
    注意：使用 {} 位置占位符传参，避免 loguru 对含花括号的异常消息二次格式化
    导致 KeyError（如 LangChain 抛出含 {field} 的错误消息时）。
    """
    type_name = type(e).__name__
    err_str   = str(e) or repr(e)
    logger.error("[{}] 失败: {} - {}", node_name, type_name, err_str, exc_info=True)


def _safe_fallback_report(node_name: str, key: str, err: BaseException) -> dict:
    """
    极简安全兜底函数——绝对不会抛出任何异常。
    规则：
      1. 不访问任何外部对象的属性或键（无 e['x']、无 obj.attr）
      2. 只使用字符串字面量和内置函数
      3. 双层 try/except 保证次生崩溃也有出路
    """
    # ── 第一层：尽力记录日志 ──────────────────────────────────
    try:
        _node  = str(node_name)[:50]   if node_name  else "unknown_node"
        _key   = str(key)[:100]        if key        else "unknown_report"
        _etype = type(err).__name__
        _emsg  = ""
        try:
            _emsg = str(err)[:150]
        except Exception:
            try:
                _emsg = repr(err)[:150]
            except Exception:
                _emsg = "unserializable_error"
        logger.critical(
            f"[{_node}] 💀 安全降级触发 | {_etype}: {_emsg}",
            exc_info=True,
        )
    except Exception:
        _node  = "unknown_node"
        _key   = "unknown_report"
        _etype = "UnknownError"
        _emsg  = ""

    # ── 第二层：构建并返回硬编码安全字典 ──────────────────────
    try:
        _reasoning = f"{_node} 节点异常降级 [{_etype}]: {_emsg}" if _emsg else f"{_node} 节点异常降级"
        return {
            _key: {
                "recommendation":  "HOLD",
                "confidence":      0.1,
                "reasoning":       _reasoning,
                "key_factors":     [],
                "risk_factors":    [],
                "price_target":    None,
                "signal_strength": "WEAK",
                "key_metrics":     {},
            },
            "execution_log": [],
            "messages":      [],
        }
    except Exception:
        # 极端情况：连 dict 都构建不了，返回绝对最小结构
        return {"execution_log": [], "messages": []}


def _guard_node(state_key: str):
    """
    装饰器：为 LangGraph 节点添加顶层 try/except 安全兜底。
    任何未被内层 except 捕获的异常（包括 asyncio.TimeoutError）都将被拦截，
    返回符合 State Schema 的降级字典，避免并发节点崩溃导致整图死锁。

    Usage:
        @_guard_node("technical_report")
        async def technical_node(state): ...
    """
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(state):
            try:
                return await fn(state)
            except BaseException as _top_err:
                return _safe_fallback_report(fn.__name__, state_key, _top_err)
        return wrapper
    return decorator


def _increment_tool_count(state_counts: dict, node_name: str) -> dict:
    """返回更新后的 tool_call_counts 字典（不直接修改 state）"""
    new_counts = dict(state_counts or {})
    new_counts[node_name] = new_counts.get(node_name, 0) + 1
    return new_counts


# ════════════════════════════════════════════════════════════════
# 置信度惩罚函数（P0 修复：原文档描述的函数在代码中缺失）
# ════════════════════════════════════════════════════════════════

_CONF_FLOOR     = 0.40   # 低于此值强制 HOLD，仓位归零
_CONF_THRESHOLD = 0.55   # 低于此值线性缩仓（惩罚带）


def _apply_confidence_penalty(
    action: str, confidence: float, base_pct: float
) -> tuple:
    """
    置信度惩罚函数：将 LLM 综合置信度映射为仓位约束。

    三阶段线性规则:
      阶段1: confidence < _CONF_FLOOR (0.40)
             → 强制 HOLD，仓位归零（模型自己都不确定，任何仓位都是噪声）
      阶段2: _CONF_FLOOR <= confidence < _CONF_THRESHOLD (0.40-0.55)
             → 线性缩仓: scale = (conf - 0.40) / (0.55 - 0.40)
             → 实际仓位 = base_pct × scale
             （避免阈值处悬崖效应）
      阶段3: confidence >= _CONF_THRESHOLD (0.55)
             → 正常执行，仓位不被惩罚

    Args:
        action:     原始动作 "BUY" / "SELL" / "HOLD"
        confidence: 综合置信度 [0.0, 1.0]
        base_pct:   风控已审核的建议仓位百分比

    Returns:
        (final_action, final_pct, penalty_note)
        - final_action: 最终动作（可能被强制改为 "HOLD"）
        - final_pct:    最终仓位百分比
        - penalty_note: 惩罚说明字符串，None 表示无惩罚

    数字示例:
        confidence=0.35 → HOLD, 0.0%  (强制HOLD)
        confidence=0.47 → BUY,  7.0%  (base=10%, scale=(0.47-0.40)/(0.55-0.40)=0.467)
        confidence=0.60 → BUY, 10.0%  (无惩罚)
    """
    if confidence < _CONF_FLOOR:
        return "HOLD", 0.0, f"置信度 {confidence:.2f} < {_CONF_FLOOR}，强制HOLD，仓位归零"

    if confidence < _CONF_THRESHOLD:
        scale = (confidence - _CONF_FLOOR) / (_CONF_THRESHOLD - _CONF_FLOOR)
        penalized_pct = round(base_pct * scale, 2)
        return (
            action,
            penalized_pct,
            f"置信度惩罚带 [{_CONF_FLOOR},{_CONF_THRESHOLD}): {base_pct}×{scale:.3f}={penalized_pct:.2f}%",
        )

    return action, base_pct, None


# ════════════════════════════════════════════════════════════════
# ATR 硬阻断函数（P1 修复：ATR 风控原为 Prompt 约束，现改为代码强制执行）
# ════════════════════════════════════════════════════════════════

_ATR_HARD_REJECT    = 8.0   # ATR% 超过此值：强制 REJECTED，仓位归零
_ATR_CONDITIONAL    = 5.0   # ATR% 超过此值：CONDITIONAL，仓位减半


def _apply_atr_hard_block(
    approval_status: str, position_pct: float, atr_pct: float
) -> tuple:
    """
    ATR 硬阻断函数：基于波动率对风控决策做代码层强制覆盖。

    规则（优先级高于 LLM 风控输出）:
      ATR% > 8.0%  → 强制 REJECTED，仓位归零（超出大学生风险承受能力）
      ATR% > 5.0%  → 强制 CONDITIONAL，仓位减半（高波动预警）
      ATR% <= 5.0% → 不干预，保持 LLM 输出

    Args:
        approval_status: LLM 风控输出的审批状态
        position_pct:    LLM 建议仓位百分比
        atr_pct:         14日 ATR 波动率百分比

    Returns:
        (new_status, new_position_pct, block_reason)
        - block_reason: None 表示未触发阻断
    """
    if atr_pct > _ATR_HARD_REJECT:
        return (
            "REJECTED",
            0.0,
            f"ATR% {atr_pct:.1f}% > {_ATR_HARD_REJECT}%（代码硬阻断：超出大学生风险承受能力）",
        )

    if atr_pct > _ATR_CONDITIONAL:
        new_pct = round(position_pct / 2.0, 2)
        return (
            "CONDITIONAL",
            new_pct,
            f"ATR% {atr_pct:.1f}% > {_ATR_CONDITIONAL}%（高波动警报：仓位减半至 {new_pct:.1f}%）",
        )

    return approval_status, position_pct, None


# ════════════════════════════════════════════════════════════════
# 单次亏损上限反算函数（P1 修复：3000元上限原为 Prompt 约束，现改为代码强制执行）
# ════════════════════════════════════════════════════════════════

_MAX_SINGLE_LOSS_CNY = 3000.0   # 单次最大亏损金额（人民币）
_ASSUMED_CAPITAL_CNY = 50000.0  # 假设大学生总本金（人民币）


def _apply_max_loss_cap(
    position_pct: float, stop_loss_pct: float, current_price: float = 0.0
) -> tuple:
    """
    单次亏损硬上限反算函数：基于 3000 元亏损上限反算最大安全仓位。

    公式：
        max_safe_pct = (_MAX_SINGLE_LOSS_CNY / _ASSUMED_CAPITAL_CNY) / (stop_loss_pct / 100)
        实际仓位 = min(position_pct, max_safe_pct × 100)

    例：stop_loss=7%, max_safe = (3000/50000) / 0.07 = 0.06 / 0.07 ≈ 0.857 → 85.7%（不触发）
        stop_loss=20%, max_safe = 0.06 / 0.20 = 0.30 → 30%（若仓位>30%则截断）

    Args:
        position_pct:  当前建议仓位百分比
        stop_loss_pct: 止损比例百分比
        current_price: 当前价格（预留参数，当前基于总资金百分比计算）

    Returns:
        (final_pct, cap_reason)
        - cap_reason: None 表示未触发上限截断
    """
    if stop_loss_pct <= 0:
        return position_pct, None

    # 反算最大安全仓位（百分比形式）
    max_safe_pct = (_MAX_SINGLE_LOSS_CNY / _ASSUMED_CAPITAL_CNY) / (stop_loss_pct / 100.0) * 100.0

    if position_pct > max_safe_pct:
        capped_pct = round(max_safe_pct, 2)
        return (
            capped_pct,
            f"单次亏损上限反算：止损{stop_loss_pct}%下最大安全仓位={capped_pct:.1f}%"
            f"（3000元/{_ASSUMED_CAPITAL_CNY:.0f}元本金）",
        )

    return position_pct, None


# ════════════════════════════════════════════════════════════════
# Prompt 字典外化管理（借鉴 TradingAgents-CN 集中管理模式）
# ════════════════════════════════════════════════════════════════

# ── AnalystReport JSON 答题卡（所有输出此模型的节点共用）──────────────
# 与 graph/state.py 中 AnalystReport 字段严格对齐
_ANALYST_REPORT_SKELETON = """
【强制置信度计算规则 — 必须像计算器一样输出精准小数】
1. confidence 必须是 0.00~1.00 之间的两位小数，严禁输出 0.60 / 0.65 等敷衍默认值。
2. 基础分 0.50（完全中性信号）。
3. 动态加减规则（可叠加）：
   - 多项核心指标高度一致且强烈看涨/看跌：+0.25 ~ +0.35
   - 单一利好/利空信号明确：+0.10 ~ +0.20
   - 信号轻微矛盾或噪音：-0.05 ~ -0.10
   - 核心数据极度恶化或极强反转信号：+0.30 ~ +0.40
   - 信号严重矛盾或数据不足：-0.15 ~ -0.25
4. 示例：基础 0.50 + 技术金叉 +0.15 + 业绩超预期 +0.12 = 0.77；你必须给出类似 0.42、0.78、0.88 的叠加结果。

【强制 JSON 输出结构 — 必须完整填写，绝不遗漏任何字段】
你必须且只能输出以下 JSON 对象，不加任何 Markdown 包裹或额外说明：
{
  "recommendation": "BUY或SELL或HOLD（三选一，必填）",
  "confidence": 0.73,
  "reasoning": "你的完整分析推导过程，不少于200字，需包含具体数据佐证和逻辑链条（必填）",
  "key_factors": ["支撑建议的关键因素1", "因素2", "因素3"],
  "price_target": null,
  "risk_factors": ["主要风险1", "风险2"],
  "signal_strength": "STRONG或MODERATE或WEAK（三选一，默认MODERATE）",
  "investment_thesis": "2-3句话概括投资论点（基本面分析必填，技术/情绪分析留空）",
  "business_model": "商业模式与收入驱动分析（基本面分析必填，技术/情绪分析留空）",
  "moat_assessment": "护城河与竞争优势评估（基本面分析必填，技术/情绪分析留空）",
  "catalysts": ["催化剂1", "催化剂2"],
  "peer_comparison": "同行估值对比（基本面分析必填，技术/情绪分析留空）",
  "bull_case": "乐观情景描述（基本面分析必填，技术/情绪分析留空）",
  "bear_case": "悲观情景描述（基本面分析必填，技术/情绪分析留空）"
}
规则：recommendation 只能是 BUY/SELL/HOLD；confidence 必须是经过上述加减法计算的精准小数；reasoning 不得为空。
注意：
- investment_thesis/business_model/moat_assessment/catalysts/peer_comparison/bull_case/bear_case 仅基本面分析师必须填写，技术面和情绪面分析师可留空字符串。
- 基本面分析师：reasoning 不少于 200 字，business_model/moat_assessment/peer_comparison 每项不少于 100 字，bull_case/bear_case 每项不少于 50 字。
- 技术面/情绪面分析师：reasoning 不少于 200 字。
"""

# 【CampusQuant 不可豁免规则】写在基础 Prompt 后，所有分析师节点共用
_CAMPUS_RULES = """
【CampusQuant 大学生用户特别规则 — 全部不可豁免】
- 本金安全第一：优先推荐主板大盘蓝筹或宽基ETF，规避中小盘投机标的
- 不建议高频盯盘：投资周期建议3个月以上，拒绝追涨杀跌
- 置信度低于60%时直接建议 HOLD，宁可错过机会也不在不确定时下注
- 严禁推荐杠杆交易、融资融券（Margin Trading）、期权投机
- 定投宽基ETF（如沪深300ETF）是大学生首选入门工具，可作备选推荐
""" + _ANALYST_REPORT_SKELETON

_PROMPTS: Dict[str, Dict[str, str]] = {

    # ── 基本面分析师 System Prompt（按市场类型区分）────────
    "fundamental": {
        "A_STOCK": (
            "你是专注A股市场的景气度与政策驱动分析专家。\n"
            "核心框架：行业景气度（30%）+ EPS增速/PEG（30%）+ 政策催化剂（25%）+ 资金热度（15%）\n"
            "原则：不以低静态PE/PB作为主要买入理由；重视【业绩高增+政策利好+资金介入】三重共振。\n\n"
            "【必须覆盖的分析维度 — 缺一不可】\n"
            "1. 商业模式 & 收入驱动：公司主营业务是什么？靠什么赚钱？收入结构如何？\n"
            "2. 护城河 & 竞争优势：品牌认知度、技术壁垒、规模效应、政策牌照、行业地位如何？\n"
            "3. 催化剂：未来1-2个季度可能推动股价的事件（业绩发布、政策落地、新产品、行业变化）\n"
            "4. 同行对比：相比同行业龙头，PE/PB/增速是偏高还是偏低？\n"
            "5. 情景分析：乐观情景（什么条件下大涨）和悲观情景（什么风险导致下跌）\n"
            "6. 投资论点：用2-3句话概括为什么推荐/不推荐这只股票"
            + _CAMPUS_RULES
        ),
        "HK_STOCK": (
            "你是专注港股市场的价值投资分析专家，融合香港市场特色与全球视野。\n"
            "核心框架：合理估值PE/PB（35%）+ 自由现金流FCF（25%）+ 分红/回购（20%）+ 宏观因素（20%）\n"
            "原则：港股需更高安全边际；关注A/H溢价与南向资金；美联储降息是重要催化剂。\n\n"
            "【必须覆盖的分析维度 — 缺一不可】\n"
            "1. 商业模式 & 收入驱动：公司主营业务是什么？靠什么赚钱？收入结构如何？\n"
            "2. 护城河 & 竞争优势：品牌、技术、网络效应、生态壁垒、市场份额如何？\n"
            "3. 催化剂：未来1-2个季度可能推动股价的事件（业绩、回购、南向资金、政策）\n"
            "4. 同行对比：相比同行业公司，估值水平和增长前景如何？\n"
            "5. 情景分析：乐观情景和悲观情景\n"
            "6. 投资论点：用2-3句话概括为什么推荐/不推荐这只股票"
            + _CAMPUS_RULES
        ),
        "US_STOCK": (
            "你是专注美股市场的成长价值双轨分析专家。\n"
            "核心框架：EPS增速/PEG（30%）+ 自由现金流（25%）+ AI/科技主题（25%）+ 宏观Beta（20%）\n"
            "原则：关注美联储降息周期对成长股估值扩张；AI算力主题享有估值溢价。\n\n"
            "【必须覆盖的分析维度 — 缺一不可】\n"
            "1. 商业模式 & 收入驱动：公司靠什么赚钱？各业务线收入占比如何？\n"
            "2. 护城河 & 竞争优势：技术领先性、生态锁定、品牌、专利、网络效应如何？\n"
            "3. 催化剂：未来1-2个季度可能推动股价的事件（财报、产品发布、AI进展、并购）\n"
            "4. 同行对比：相比行业 peers，P/E、P/S、增速是偏高还是偏低？\n"
            "5. 情景分析：乐观情景和悲观情景\n"
            "6. 投资论点：用2-3句话概括为什么推荐/不推荐这只股票"
            + _CAMPUS_RULES
        ),
    },

    # ── 技术分析师 System Prompt ─────────────────────────────
    "technical": {
        "DEFAULT": (
            "你是拥有20年经验的量化技术分析专家，擅长多周期信号融合与量价关系分析。\n"
            "核心框架: 趋势（MA系统 30%）+ 动量（MACD 30%）+ 超买超卖（RSI/BOLL 25%）+ 量价（量比 15%）\n"
            "分析原则:\n"
            "- 多重信号共振时才发出强信号；单一信号不足以支撑高置信度结论\n"
            "- 量价背离（放量阴线、缩量阳线）是重要预警信号\n"
            "- 技术面形态服从于大趋势方向（顺势交易）\n"
            + _ANALYST_REPORT_SKELETON
        ),
    },

    # ── 舆情分析师 System Prompt ─────────────────────────────
    "sentiment": {
        "DEFAULT": (
            "你是专业的金融市场舆情与资金面分析师，擅长从量价数据与宏观环境中读取市场情绪。\n"
            "分析维度:\n"
            "1. 资金热度（量比/换手率）: 判断主力资金行为\n"
            "2. 市场情绪（宏观政策面）: 当前市场整体风险偏好\n"
            "3. 板块轮动: 资金是否正在轮入/轮出本标的所在板块\n"
            "4. 极端情绪信号: 是否存在恐慌性卖出或疯狂追涨\n"
            "分析原则:\n"
            "- 结合量能与价格形态识别'主力资金意图'\n"
            "- 极端情绪（RSI>80 或 RSI<20）往往是反转信号\n"
            "- 宏观政策利好是A股情绪的最强催化剂\n"
            + _ANALYST_REPORT_SKELETON
        ),
    },

    # ── 持仓体检 System Prompt ──────────────────────────────
    "health": {
        "DEFAULT": (
            "你是专为大学生服务的持仓健康度分析专家，擅长识别集中度风险、回撤风险与流动性风险。\n"
            "评估框架:\n"
            "1. 集中度风险: 单标的占比 > 15%（A股）或 > 10%（港/美股）即为超权重\n"
            "2. 回撤风险: 各持仓浮亏情况 + ATR波动率评估最大可能亏损\n"
            "3. 流动性: 中小盘流动性差，大学生优先选择流动性强的主板蓝筹\n"
            "4. 市场分散: 单一市场集中度 > 70% 需提示分散风险\n"
            "大学生专属评分规则:\n"
            "- 全部持仓均为大盘蓝筹/宽基ETF + 合理分散 → 满分 100 分\n"
            "- 含超权重标的每项扣 15 分\n"
            "- 含高波动标的（ATR%>5%）每项扣 10 分\n"
            "- 含中小盘投机股每项扣 20 分\n"
            "- 严禁杠杆，发现直接输出健康分 0 分\n"
            "【输出格式】必须严格按照给定的 JSON 格式输出结果，不得输出任何 Markdown 包裹或额外说明文字。"
        ),
    },

    # ── 风控官 System Prompt（在 risk_node 中直接构建，此处存基础前缀）──
    "risk": {
        "BASE": (
            "你是严格的风险控制官，专为在校大学生用户把关交易风险。\n"
            "你有一票否决权，若方案对大学生风险不可接受，直接拒绝并给出教育性说明。\n"
            "【输出格式】必须严格按照给定的 JSON 格式输出结果，不得输出任何 Markdown 包裹或额外说明文字。"
        ),
    },
}


# ════════════════════════════════════════════════════════════════
# NODE 1 — data_node
# ════════════════════════════════════════════════════════════════

async def data_node(state: TradingGraphState) -> dict:
    """
    数据情报员节点:
      - 调用 get_market_data @tool 获取 OHLCV 行情
      - 调用 calculate_technical_indicators @tool 预计算所有技术指标
      - 将结果写入 state.market_data，供后续并行节点使用

    Anti-Loop: 使用 _check_tool_limit() 防止工具调用死循环
    """
    symbol = _sanitize_symbol(state.get("symbol") or state.get("stock_code", "UNKNOWN"))
    logger.info(f"[data_node] 开始获取市场数据: {symbol}")

    # 工具调用计数器初始化（首次进入此节点）
    counts = state.get("tool_call_counts") or {}

    try:
        # ── Anti-Loop 检查（借鉴 TradingAgents-CN market_analyst.py max 3 calls）
        _check_tool_limit(state, "data_node")
        counts = _increment_tool_count(counts, "data_node")

        raw_json  = get_market_data.invoke({"symbol": symbol, "days": 180})

        _check_tool_limit({**state, "tool_call_counts": counts}, "data_node")
        counts = _increment_tool_count(counts, "data_node")

        tech_json = calculate_technical_indicators.invoke({"market_data_json": raw_json})

        raw_data  = json.loads(raw_json)
        tech_data = json.loads(tech_json)

        market_data = {**raw_data, **tech_data}

        # 提取最近15行OHLCV数据供 technical_node 构建精简提示词（指标基于全量180天计算）
        _ohlcv_raw = market_data.pop("_ohlcv_json", None)  # 移除大块原始数据节省状态空间
        if _ohlcv_raw:
            try:
                import pandas as _pd
                _df_full = _pd.DataFrame(json.loads(_ohlcv_raw))
                _df_full.columns = [c.lower() for c in _df_full.columns]
                _recent = _df_full.tail(15)[["open", "high", "low", "close", "volume"]]
                market_data["recent_ohlcv"] = _recent.round(4).to_dict(orient="records")
            except Exception as _oe:
                logger.warning(f"[data_node] recent_ohlcv 提取失败（非致命）: {_oe}")

        log_msg = _log_entry(
            "data_node",
            f"数据获取成功 | {symbol} | 最新价: {raw_data.get('latest_price')} "
            f"| 技术信号: {tech_data.get('indicators', {}).get('tech_signal', 'N/A')}"
        )

        return {
            "market_data":        market_data,
            "market_type":        raw_data.get("market_type", "UNKNOWN"),
            "data_fetch_failed":  False,   # 【审计修复 P0-3】明确标记数据正常
            "tool_call_counts":   {"data_node": counts.get("data_node", 0)},
            "current_node":       "data_node",
            "execution_log":      [log_msg],
            "messages": [AIMessage(
                content=f"市场数据已获取: {symbol} | 价格 {raw_data.get('latest_price')} | "
                        f"信号 {tech_data.get('indicators', {}).get('tech_signal')}",
                name="data_node",
            )],
        }

    except _ToolLimitExceeded as e:
        logger.warning(f"[data_node] {e}")
        return {
            "market_data":        {"status": "tool_limit", "error": str(e)},
            "data_fetch_failed":  True,    # 【审计修复 P0-3】标记失败，触发并行节点早退
            "tool_call_counts":   {"data_node": counts.get("data_node", 0)},
            "current_node":       "data_node",
            "execution_log":      [_log_entry("data_node", f"⚠️ 工具调用上限: {e}")],
            "status":             "error",
            "error_type":         "tool_limit",
            "error_message":      str(e),
            "messages": [AIMessage(content=f"工具调用上限: {e}", name="data_node")],
        }

    except Exception as e:
        _log_node_error("data_node", e)
        return {
            "market_data":        {"status": "error", "error": str(e)},
            "data_fetch_failed":  True,    # 【审计修复 P0-3】标记失败，触发并行节点早退
            "tool_call_counts":   {"data_node": counts.get("data_node", 0)},
            "current_node":       "data_node",
            "execution_log":      [_log_entry("data_node", f"❌ 数据获取失败: {e}")],
            "status":             "error",
            "error_type":         "data_error",
            "error_message":      str(e),
            "messages": [AIMessage(content=f"数据获取失败: {e}", name="data_node")],
        }


# ════════════════════════════════════════════════════════════════
# NODE 2 — rag_node（与分析师节点并行）
# ════════════════════════════════════════════════════════════════

async def rag_node(state: TradingGraphState) -> dict:
    """
    RAG 知识检索节点:
      - 根据 symbol + market_type 构建检索 query
      - 调用 search_knowledge_base @tool
      - 将检索结果写入 state.rag_context，作为分析师的 RAG 上下文
    """
    symbol      = state.get("symbol") or state.get("stock_code", "UNKNOWN")
    market_type = state.get("market_type", "ALL")
    market_data = state.get("market_data", {})
    indicators  = market_data.get("indicators", {})
    tech_signal = indicators.get("tech_signal", "HOLD")

    # 【审计修复 P0-3】数据获取失败时早退，不调用工具
    if state.get("data_fetch_failed"):
        logger.warning(f"[rag_node] 数据获取失败，跳过 RAG 检索")
        return {
            "rag_context":   "",
            "execution_log": [_log_entry("rag_node", "⏭️ 数据失败，RAG 跳过")],
            "messages": [AIMessage(content="数据获取失败，RAG 检索已跳过", name="rag_node")],
        }

    query = (
        f"{symbol} {market_type} 市场政策 行业景气度 宏观经济"
        f" 技术信号{tech_signal} 投资分析"
    )

    logger.info(f"[rag_node] 检索知识库: {query[:60]}...")

    try:
        rag_text = search_knowledge_base.invoke({"query": query, "market_type": market_type})
        return {
            "rag_context":   rag_text,
            "execution_log": [_log_entry("rag_node", f"RAG 检索完成，返回 {len(rag_text)} 字符")],
            "messages": [AIMessage(
                content=f"RAG 知识检索完成: {len(rag_text)} 字符上下文已准备",
                name="rag_node",
            )],
        }
    except Exception as e:
        _log_node_error("rag_node", e)
        return {
            "rag_context":   "",
            "execution_log": [_log_entry("rag_node", f"⚠️ RAG 检索失败（降级为空）: {e}")],
            "messages": [AIMessage(content=f"RAG 检索失败: {e}", name="rag_node")],
        }


# ════════════════════════════════════════════════════════════════
# NODE 3 — fundamental_node（与其他分析师并行）
# ════════════════════════════════════════════════════════════════

@_guard_node("fundamental_report")
async def fundamental_node(state: TradingGraphState) -> dict:
    """
    基本面分析师节点（审计修复版）:
      【审计修复 P0-1】调用 get_fundamental_data @tool 获取真实 PE/PB/ROE 数据，
        不再纯靠 OHLCV 价格数据推断基本面。
      【审计修复 P0-3】data_fetch_failed=True 时早退，不调用 LLM，避免幻觉报告。
      - Prompt 从 _PROMPTS["fundamental"] 字典按 market_type 取值（外化管理）
      - 调用 LLM + with_structured_output(AnalystReport)
      - 结合 RAG 上下文（state.rag_context）提升分析深度
    """
    symbol      = _sanitize_symbol(state.get("symbol") or state.get("stock_code", "UNKNOWN"))
    market_type = state.get("market_type", "US_STOCK")
    market_data = state.get("market_data", {})
    counts      = state.get("tool_call_counts") or {}

    # 【审计修复 P0-3】数据获取失败时早退
    if state.get("data_fetch_failed"):
        logger.warning(f"[fundamental_node] 数据获取失败，返回 HOLD 降级报告")
        return {
            "fundamental_report": {
                "recommendation": "HOLD", "confidence": 0.1,
                "reasoning": "上游数据获取失败，无法进行基本面分析",
                "key_factors": ["数据缺失"], "risk_factors": ["数据不可用"],
                "price_target": None, "signal_strength": "WEAK",
            },
            "execution_log": [_log_entry("fundamental_node", "⏭️ 数据失败，基本面跳过")],
            "messages": [AIMessage(content="数据获取失败，基本面分析已跳过", name="fundamental_node")],
        }

    logger.info(f"[fundamental_node] 开始基本面分析: {symbol}")

    # 【审计修复 P0-1】获取真实基本面数据
    fund_data_text = "（基本面数据获取失败，仅凭价格与教育资料分析）"
    fundamental_data_dict = {}
    try:
        _check_tool_limit(state, "fundamental_node")
        counts = _increment_tool_count(counts, "fundamental_node")

        fund_json = get_fundamental_data.invoke({"symbol": symbol})
        fund_parsed = json.loads(fund_json)

        if fund_parsed.get("status") == "success":
            data = fund_parsed.get("data", {})
            fundamental_data_dict = data
            # 格式化为可读文本注入 Prompt（最多 10 个字段，单值截 80 字符）
            fund_lines = [
                f"  {k}: {str(v)[:80]}" for k, v in data.items()
                if v is not None
            ]
            fund_data_text = "\n".join(fund_lines[:10]) if fund_lines else "（无有效字段）"
            # 极严厉截断：800 字符上限，确保 LLM 快速处理
            fund_data_text = fund_data_text[:800]
            logger.info(f"[fundamental_node] 基本面数据获取成功: {len(fund_lines)} 字段")
        elif fund_parsed.get("status") == "partial":
            fund_data_text = f"（{fund_parsed.get('message', '部分数据')}）"
        else:
            fund_data_text = f"（获取失败: {fund_parsed.get('error', '未知错误')[:60]}）"
    except _ToolLimitExceeded:
        logger.warning("[fundamental_node] 工具调用上限，跳过基本面数据获取")
    except Exception as _e:
        logger.warning(f"[fundamental_node] 基本面数据获取异常: {_e}")

    # 【深度财务数据】获取主营构成 + 多维业绩趋势，注入 key_metrics 供前端 ECharts 渲染
    # 深度财务数据仅供前端图表，不注入 LLM prompt，故不受截断约束
    try:
        deep = await asyncio.get_event_loop().run_in_executor(
            None, get_deep_financial_data_via_relay, symbol
        )
        fundamental_data_dict["revenue_composition"] = deep.get("revenue_composition", {})
        fundamental_data_dict["performance_trend"]   = deep.get("performance_trend", {})
        # 历年营收/净利润（供前端 ECharts 柱状图）
        if deep.get("years"):
            fundamental_data_dict["years"] = deep["years"]
            fundamental_data_dict["revenue_history"] = deep.get("revenue_history", [])
            fundamental_data_dict["profit_history"] = deep.get("profit_history", [])
            fundamental_data_dict["revenue_label"] = deep.get("revenue_label", "营业收入（亿元）")
            fundamental_data_dict["profit_label"] = deep.get("profit_label", "净利润（亿元）")
        logger.info(
            f"[fundamental_node] 深度财务注入完成: "
            f"历年数据={len(deep.get('years', []))}年 "
            f"构成产品={len(deep.get('revenue_composition', {}).get('product', []))}项"
        )
    except Exception as _de:
        logger.warning(f"[fundamental_node] 深度财务数据获取失败（非致命）: {_de}")
        fundamental_data_dict.setdefault("revenue_composition", {})
        fundamental_data_dict.setdefault("performance_trend", {})

    # 【Per-Node RAG】基本面专项检索：财报数据、盈利质量、机构评级
    fund_rag_context = ""
    try:
        fund_rag_context = search_knowledge_base.invoke({
            "query":       f"{symbol} 财务报表 基本面 盈利 机构评级",
            "market_type": market_type,
            "max_length":  1200,
        })
        logger.info(f"[fundamental_node] 专项 RAG 检索完成: {len(fund_rag_context)} 字符")
    except Exception as _re:
        logger.warning(f"[fundamental_node] 专项 RAG 检索失败（降级为空）: {_re}")

    # 从 Prompt 字典取 System Prompt（外化管理）
    system_prompt = _PROMPTS["fundamental"].get(
        market_type,
        _PROMPTS["fundamental"]["US_STOCK"]
    )

    user_prompt = f"""
请对标的 **{symbol}** ({market_type}) 进行基本面研判，输出结构化报告。

【真实基本面数据（优先参考）】
{fund_data_text}

【价格与量能数据（辅助参考）】
- 最新价格: {market_data.get('latest_price', 'N/A')}
- 区间最高/最低: {market_data.get('period_high', 'N/A')} / {market_data.get('period_low', 'N/A')}
- 价格变动: {market_data.get('price_change_pct', 'N/A')}%
- 成交量比（10日均）: {market_data.get('indicators', {}).get('volume_ratio', 'N/A')}
- ATR%(波动率): {market_data.get('indicators', {}).get('ATR_pct', 'N/A')}%

【研报知识库 — 基本面专项检索】
{fund_rag_context if fund_rag_context else '暂无'}

请优先基于真实基本面数据（PE/PB/ROE 等），结合量价辅助，以你的专业框架分析
该标的的基本面状况，给出 BUY/SELL/HOLD 建议。
注意：若基本面数据缺失，请明确在 reasoning 中说明分析局限性，并降低置信度。
price_target 使用绝对价格数值。
"""

    try:
        llm = _build_llm(temperature=0.1)
        structured_llm = llm.with_structured_output(AnalystReport)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        report: AnalystReport = await asyncio.wait_for(structured_llm.ainvoke(messages), timeout=300.0)

        report_dict = report.model_dump(mode='json')
        log_msg = _log_entry(
            "fundamental_node",
            f"基本面分析: {report.recommendation} | 置信度: {report.confidence:.2f} | "
            f"信号强度: {report.signal_strength} | 真实数据字段数: {len(fundamental_data_dict)}"
        )
        logger.info(log_msg)

        # 将 key_metrics 注入 fundamental_report，确保 server.py 能提取 financial_chart_data
        # （无论成功还是降级路径，前端 ECharts 都能获得 revenue_history / profit_history）
        report_dict["key_metrics"] = fundamental_data_dict if fundamental_data_dict else {}
        return {
            "fundamental_report": report_dict,
            "fundamental_data":   fundamental_data_dict if fundamental_data_dict else None,
            "tool_call_counts":   {"fundamental_node": counts.get("fundamental_node", 0)},
            "execution_log":      [log_msg],
            "messages": [AIMessage(
                content=f"基本面分析完成: {report.recommendation} "
                        f"(置信度 {report.confidence:.0%}) — {report.reasoning[:80]}...",
                name="fundamental_node",
            )],
        }

    except Exception as e:
        logger.exception("[fundamental_node] 节点执行遭遇致命异常，完整堆栈如下：")
        _log_node_error("fundamental_node", e)
        fallback = {
            "recommendation": "HOLD", "confidence": 0.3,
            "reasoning": f"基本面分析异常（LLM 超时或解析失败）: {str(e)}",
            "key_factors": [], "risk_factors": [],
            "price_target": None, "signal_strength": "WEAK",
            # 抢救已获取的财务数据，确保 server.py 能提取 financial_chart_data
            "key_metrics": fundamental_data_dict if fundamental_data_dict else {},
        }
        return {
            "fundamental_report": fallback,
            "tool_call_counts":   {"fundamental_node": counts.get("fundamental_node", 0)},
            "execution_log":      [_log_entry("fundamental_node", f"⚠️ 降级处理: {e}")],
            "messages": [AIMessage(content=f"基本面分析异常: {e}", name="fundamental_node")],
        }


# ════════════════════════════════════════════════════════════════
# NODE 4 — technical_node（与其他分析师并行）
# ════════════════════════════════════════════════════════════════

@_guard_node("technical_report")
async def technical_node(state: TradingGraphState) -> dict:
    """
    技术分析师节点:
      - 基于预计算的技术指标（MACD/RSI/BOLL/MA 等）进行信号解读
      - Prompt 从 _PROMPTS["technical"] 字典取值（外化管理）
      - 使用 with_structured_output(AnalystReport) 输出结构化报告
    """
    symbol      = _sanitize_symbol(state.get("symbol") or state.get("stock_code", "UNKNOWN"))
    market_type = state.get("market_type", "US_STOCK")
    market_data = state.get("market_data", {})
    indicators  = market_data.get("indicators", {})

    # 【审计修复 P0-3】数据获取失败时早退
    if state.get("data_fetch_failed"):
        logger.warning(f"[technical_node] 数据获取失败，返回 HOLD 降级报告")
        return {
            "technical_report": {
                "recommendation": "HOLD", "confidence": 0.1,
                "reasoning": "上游数据获取失败，无法进行技术分析",
                "key_factors": ["数据缺失"], "risk_factors": ["数据不可用"],
                "price_target": None, "signal_strength": "WEAK",
            },
            "execution_log": [_log_entry("technical_node", "⏭️ 数据失败，技术分析跳过")],
            "messages": [AIMessage(content="数据获取失败，技术分析已跳过", name="technical_node")],
        }

    logger.info(f"[technical_node] 开始技术分析: {symbol}")

    # 【Per-Node RAG】技术面专项检索：资金面、行业技术利好利空
    tech_rag_context = ""
    try:
        tech_rag_context = search_knowledge_base.invoke({
            "query":       f"{symbol} 近期资金面 行业技术利好利空",
            "market_type": market_type,
            "max_length":  1000,
        })
        logger.info(f"[technical_node] 专项 RAG 检索完成: {len(tech_rag_context)} 字符")
    except Exception as _re:
        logger.warning(f"[technical_node] 专项 RAG 检索失败（降级为空）: {_re}")

    system_prompt = _PROMPTS["technical"]["DEFAULT"]

    # 格式化技术指标为可读形式
    ind_summary = "\n".join([
        f"  MA系统: MA5={indicators.get('MA5','N/A')} | MA20={indicators.get('MA20','N/A')} | MA60={indicators.get('MA60','N/A')}",
        f"  趋势: 上方MA20={indicators.get('above_ma20','N/A')} | 上方MA60={indicators.get('above_ma60','N/A')} | 多头排列={indicators.get('ma_bullish_alignment','N/A')}",
        f"  MACD: DIF={indicators.get('MACD','N/A')} | DEA={indicators.get('MACD_signal','N/A')} | 柱={indicators.get('MACD_hist','N/A')} | 金叉={indicators.get('MACD_golden_cross','N/A')}",
        f"  RSI14: {indicators.get('RSI14','N/A')} | 超买={indicators.get('RSI_overbought','N/A')} | 超卖={indicators.get('RSI_oversold','N/A')}",
        f"  BOLL %B: {indicators.get('BOLL_pct_B','N/A')} | 近上轨={indicators.get('near_boll_upper','N/A')} | 近下轨={indicators.get('near_boll_lower','N/A')}",
        f"  量比: {indicators.get('volume_ratio','N/A')} | 高量能={indicators.get('high_volume','N/A')}",
        f"  ATR%: {indicators.get('ATR_pct','N/A')}%",
        f"  系统信号: {indicators.get('tech_signal','N/A')} (多={indicators.get('bull_signal_count',0)}, 空={indicators.get('bear_signal_count',0)})",
    ])

    # 最近10日量价数据（指标基于180天计算）——仅展示给LLM，不用于指标计算
    # 严格截断至 10 行，防止 prompt 过长导致超时
    import pandas as _pd_tech
    recent_rows = market_data.get("recent_ohlcv", [])
    if recent_rows:
        recent_rows = _pd_tech.DataFrame(recent_rows).tail(10).to_dict(orient="records")
    if recent_rows:
        header = "  日期序号 |  开盘   |  最高   |  最低   |  收盘   |   成交量"
        rows_txt = "\n".join(
            f"  [{i+1:>2}]     | {r.get('open','N/A'):>7} | {r.get('high','N/A'):>7} | "
            f"{r.get('low','N/A'):>7} | {r.get('close','N/A'):>7} | {r.get('volume','N/A'):>10}"
            for i, r in enumerate(recent_rows)
        )
        recent_price_section = f"\n【最近10日量价数据（指标基于180天计算）】\n{header}\n{rows_txt}"
    else:
        recent_price_section = ""

    user_prompt = f"""
请对标的 **{symbol}** ({market_type}) 进行技术面研判。

【当前价格】{market_data.get('latest_price', 'N/A')}

【技术指标详情（基于180日数据计算）】
{ind_summary}
{recent_price_section}

【研报知识库 — 资金面与行业技术专项检索】
{tech_rag_context if tech_rag_context else '暂无'}

基于上述多维度技术信号，综合判断当前价格所处的趋势位置与动量状态，
给出 BUY/SELL/HOLD 建议，并量化置信度。
"""

    try:
        llm = _build_llm(temperature=0.1)
        structured_llm = llm.with_structured_output(AnalystReport)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        report: AnalystReport = await asyncio.wait_for(structured_llm.ainvoke(messages), timeout=300.0)

        report_dict = report.model_dump(mode='json')
        log_msg = _log_entry(
            "technical_node",
            f"技术分析: {report.recommendation} | 置信度: {report.confidence:.2f} | "
            f"系统信号: {indicators.get('tech_signal')}"
        )
        logger.info(log_msg)

        return {
            "technical_report": report_dict,
            "execution_log":    [log_msg],
            "messages": [AIMessage(
                content=f"技术分析完成: {report.recommendation} "
                        f"(置信度 {report.confidence:.0%}) — {report.reasoning[:80]}...",
                name="technical_node",
            )],
        }

    except Exception as e:
        logger.exception("[technical_node] 节点执行遭遇致命异常，完整堆栈如下：")
        _log_node_error("technical_node", e)
        sig = indicators.get("tech_signal", "HOLD")
        rec = "BUY" if "BUY" in sig else ("SELL" if "SELL" in sig else "HOLD")
        fallback = {
            "recommendation": rec, "confidence": 0.4,
            "reasoning": f"技术分析异常降级，系统信号={sig}: {str(e)}",
            "key_factors": [f"系统信号: {sig}"], "risk_factors": [],
            "price_target": None, "signal_strength": "WEAK",
        }
        return {
            "technical_report": fallback,
            "execution_log":    [_log_entry("technical_node", f"⚠️ 降级处理: {e}")],
            "messages": [AIMessage(content=f"技术分析异常: {e}", name="technical_node")],
        }


# ════════════════════════════════════════════════════════════════
# NODE 5 — sentiment_node（与其他分析师并行）
# ════════════════════════════════════════════════════════════════

@_guard_node("sentiment_report")
async def sentiment_node(state: TradingGraphState) -> dict:
    """
    舆情与资金面分析师节点（审计修复版）:
      【审计修复 P0-2】调用 get_stock_news @tool 获取真实新闻资讯，
        不再仅凭量价指标推断"情绪"（原来是技术面的二次包装）。
      【审计修复 P0-3】data_fetch_failed=True 时早退，不调用 LLM。
      - 仍保留量价动量特征作为辅助输入
      - Prompt 从 _PROMPTS["sentiment"] 字典取值（外化管理）
    """
    symbol      = _sanitize_symbol(state.get("symbol") or state.get("stock_code", "UNKNOWN"))
    market_type = state.get("market_type", "US_STOCK")
    market_data = state.get("market_data", {})
    indicators  = market_data.get("indicators", {})
    counts      = state.get("tool_call_counts") or {}

    # 【审计修复 P0-3】数据获取失败时早退
    if state.get("data_fetch_failed"):
        logger.warning(f"[sentiment_node] 数据获取失败，返回 HOLD 降级报告")
        return {
            "sentiment_report": {
                "recommendation": "HOLD", "confidence": 0.1,
                "reasoning": "上游数据获取失败，无法进行舆情分析",
                "key_factors": ["数据缺失"], "risk_factors": ["数据不可用"],
                "price_target": None, "signal_strength": "WEAK",
            },
            "execution_log": [_log_entry("sentiment_node", "⏭️ 数据失败，舆情分析跳过")],
            "messages": [AIMessage(content="数据获取失败，舆情分析已跳过", name="sentiment_node")],
        }

    logger.info(f"[sentiment_node] 开始舆情分析: {symbol}")

    # 【审计修复 P0-2】获取真实新闻资讯
    news_text = "（新闻数据获取失败，仅凭量价指标分析动量）"
    news_data_str = None
    try:
        _check_tool_limit(state, "sentiment_node")
        counts = _increment_tool_count(counts, "sentiment_node")

        news_json   = get_stock_news.invoke({"symbol": symbol, "limit": 5})
        news_parsed = json.loads(news_json)

        if news_parsed.get("status") == "success" and news_parsed.get("news"):
            news_items = news_parsed["news"][:3]   # 最多 3 条，进一步减负
            lines = [f"  [{i+1}] {n.get('time','')[:10]} {n.get('title','')[:80]}"
                     for i, n in enumerate(news_items)]
            news_text     = "\n".join(lines)[:600]  # 强制截断 600 字符
            news_data_str = news_json
            logger.info(f"[sentiment_node] 新闻获取成功: {len(news_items)} 条")
        elif news_parsed.get("status") == "partial":
            news_text = f"（{news_parsed.get('message', '暂无新闻数据')}）"
        else:
            news_text = f"（新闻获取失败: {news_parsed.get('error', '')[:60]}）"
    except _ToolLimitExceeded:
        logger.warning("[sentiment_node] 工具调用上限，跳过新闻获取")
    except Exception as _e:
        logger.warning(f"[sentiment_node] 新闻获取异常: {_e}")

    # 【Per-Node RAG】舆情专项检索：最新宏观政策、行业动态、突发新闻
    sent_rag_context = ""
    try:
        sent_rag_context = search_knowledge_base.invoke({
            "query":       f"{symbol} 最新宏观政策 行业动态 突发新闻",
            "market_type": market_type,
            "max_length":  1000,
        })
        logger.info(f"[sentiment_node] 专项 RAG 检索完成: {len(sent_rag_context)} 字符")
    except Exception as _re:
        logger.warning(f"[sentiment_node] 专项 RAG 检索失败（降级为空）: {_re}")

    system_prompt = _PROMPTS["sentiment"]["DEFAULT"]

    user_prompt = f"""
请对标的 **{symbol}** ({market_type}) 进行市场情绪与资金面研判。

【最新新闻资讯（真实舆情，优先参考）】
{news_text}

【量价动量数据（辅助参考）】
- 价格变动: {market_data.get('price_change_pct', 'N/A')}%
- 量比（近10日均）: {indicators.get('volume_ratio', 'N/A')}
- 高量能信号: {indicators.get('high_volume', 'N/A')}
- RSI14: {indicators.get('RSI14', 'N/A')}（>70超买, <30超卖）
- BOLL %B: {indicators.get('BOLL_pct_B', 'N/A')}（>0.85接近上轨，<0.15接近下轨）

【研报知识库 — 宏观政策与行业动态专项检索】
{sent_rag_context if sent_rag_context else '暂无宏观背景信息'}

请优先基于真实新闻事件分析市场情绪，结合量价动量特征，给出 BUY/SELL/HOLD 建议。
若无新闻数据，请明确说明分析仅基于量价推断，并相应降低置信度（≤0.50）。
"""

    try:
        llm = _build_llm(temperature=0.1)
        structured_llm = llm.with_structured_output(AnalystReport)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        report: AnalystReport = await asyncio.wait_for(structured_llm.ainvoke(messages), timeout=300.0)

        report_dict = report.model_dump(mode='json')
        has_real_news = "新闻获取失败" not in news_text and "获取失败" not in news_text and "暂无" not in news_text
        log_msg = _log_entry(
            "sentiment_node",
            f"舆情分析: {report.recommendation} | 置信度: {report.confidence:.2f} | "
            f"真实新闻: {'有' if has_real_news else '无'}"
        )
        logger.info(log_msg)

        return {
            "sentiment_report": report_dict,
            "news_data":        news_data_str,
            "tool_call_counts": {"sentiment_node": counts.get("sentiment_node", 0)},
            "execution_log":    [log_msg],
            "messages": [AIMessage(
                content=f"舆情分析完成: {report.recommendation} "
                        f"(置信度 {report.confidence:.0%}) — {report.reasoning[:80]}...",
                name="sentiment_node",
            )],
        }

    except Exception as e:
        logger.exception("[sentiment_node] 节点执行遭遇致命异常，完整堆栈如下：")
        _log_node_error("sentiment_node", e)
        fallback = {
            "recommendation": "HOLD", "confidence": 0.3,
            "reasoning": f"舆情分析异常: {str(e)}",
            "key_factors": [], "risk_factors": [],
            "price_target": None, "signal_strength": "WEAK",
        }
        return {
            "sentiment_report": fallback,
            "tool_call_counts": {"sentiment_node": counts.get("sentiment_node", 0)},
            "execution_log":    [_log_entry("sentiment_node", f"⚠️ 降级处理: {e}")],
            "messages": [AIMessage(content=f"舆情分析异常: {e}", name="sentiment_node")],
        }


# ════════════════════════════════════════════════════════════════
# NODE 6 — portfolio_node（汇聚分析、检测冲突）
# ════════════════════════════════════════════════════════════════

# 市场差异化权重配置（审计修复版）
# 【审计修复 P1-2】fundamental 权重提升（因已有真实 PE/PB 数据支撑），
# sentiment 权重适当下调（仍可能受限于新闻数据可用性）
_MARKET_WEIGHTS = {
    # A股：基本面权重提升（商业模式+护城河分析），投资周期≥3个月不宜过度偏技术面
    # sentiment 含 0.10 宏观/政策上下文权重（A股政策驱动特性）
    "A_STOCK":  {"fundamental": 0.40, "technical": 0.25, "sentiment": 0.35},
    # 港股：价值投资导向，基本面最重要
    "HK_STOCK": {"fundamental": 0.55, "technical": 0.20, "sentiment": 0.25},
    # 美股：基本面主导（EPS+FCF），技术面辅助
    "US_STOCK": {"fundamental": 0.50, "technical": 0.25, "sentiment": 0.25},
}

# 信号评分映射（用于数学预加权）
_REC_SCORE = {"BUY": 1.0, "HOLD": 0.5, "SELL": 0.0}


def _compute_weighted_score(
    fundamental: dict, technical: dict, sentiment: dict,
    weights: dict, market_type: str,
) -> dict:
    """
    【审计修复 P1-2】在 LLM 调用前完成数学预加权计算。
    将三份报告的建议和置信度转化为数值评分，计算加权结果。
    此结果作为"锚点"注入 portfolio_node 的 Prompt，
    防止 LLM 主观加权偏离预定权重。
    """
    fw = weights.get("fundamental", 0.35)
    tw = weights.get("technical",   0.40)
    sw = weights.get("sentiment",   0.25)

    f_rec  = fundamental.get("recommendation", "HOLD")
    t_rec  = technical.get("recommendation", "HOLD")
    s_rec  = sentiment.get("recommendation", "HOLD")
    f_conf = float(fundamental.get("confidence", 0.5))
    t_conf = float(technical.get("confidence", 0.5))
    s_conf = float(sentiment.get("confidence", 0.5))

    # 加权信号评分（1.0=买，0.5=持，0.0=卖）× 置信度
    f_score = _REC_SCORE.get(f_rec, 0.5) * f_conf
    t_score = _REC_SCORE.get(t_rec, 0.5) * t_conf
    s_score = _REC_SCORE.get(s_rec, 0.5) * s_conf

    weighted_score = fw * f_score + tw * t_score + sw * s_score
    avg_confidence = fw * f_conf + tw * t_conf + sw * s_conf

    if weighted_score >= 0.60:
        pre_signal = "BUY"
    elif weighted_score <= 0.35:
        pre_signal = "SELL"
    else:
        pre_signal = "HOLD"

    return {
        "weighted_score":  round(weighted_score, 3),
        "avg_confidence":  round(avg_confidence, 3),
        "pre_signal":      pre_signal,
        "breakdown": {
            f"基本面({fw:.0%})": f"{f_rec}×{f_conf:.2f}={fw*f_score:.3f}",
            f"技术面({tw:.0%})": f"{t_rec}×{t_conf:.2f}={tw*t_score:.3f}",
            f"舆情({sw:.0%})":   f"{s_rec}×{s_conf:.2f}={sw*s_score:.3f}",
        },
    }


@_guard_node("_portfolio_guard")
async def portfolio_node(state: TradingGraphState) -> dict:
    """
    基金经理综合决策节点:
      - 汇聚三大分析师报告 + RAG 上下文 + 风控反馈
      - 检测基本面 vs 技术面冲突（has_conflict）
      - 若 risk_rejection_count > 0，进入风控修订模式（降仓/调仓）
      - 输出最终投资建议（供后续辩论或风控使用）
    """
    symbol               = _sanitize_symbol(state.get("symbol") or state.get("stock_code", "UNKNOWN"))
    market_type          = state.get("market_type", "US_STOCK")
    fundamental          = state.get("fundamental_report", {}) or {}
    technical            = state.get("technical_report", {})   or {}
    sentiment            = state.get("sentiment_report", {})   or {}
    debate_outcome       = state.get("debate_outcome")
    risk_decision        = state.get("risk_decision")
    risk_rejection_count = state.get("risk_rejection_count", 0)
    rag_context          = state.get("rag_context", "")

    logger.info(f"[portfolio_node] 综合决策: {symbol} | 风控拒绝次数={risk_rejection_count}")

    is_revision = risk_rejection_count > 0 and risk_decision is not None
    fund_rec    = fundamental.get("recommendation", "HOLD")
    tech_rec    = technical.get("recommendation", "HOLD")
    sent_rec    = sentiment.get("recommendation", "HOLD")
    sent_conf   = sentiment.get("confidence", 0.0)

    # 冲突检测：基本面 vs 技术面直接矛盾
    fund_tech_conflict = (
        fund_rec in ("BUY", "SELL")
        and tech_rec in ("BUY", "SELL")
        and fund_rec != tech_rec
    )

    # 冲突检测：基本面+技术面一致，但舆情以高置信度强烈反对
    sentiment_dissent = False
    if (
        fund_rec == tech_rec
        and fund_rec in ("BUY", "SELL")
        and sent_rec in ("BUY", "SELL")
        and sent_rec != fund_rec
        and sent_conf >= 0.8
    ):
        sentiment_dissent = True

    has_conflict = (
        not is_revision
        and debate_outcome is None
        and (fund_tech_conflict or sentiment_dissent)
    )

    weights = _MARKET_WEIGHTS.get(market_type, _MARKET_WEIGHTS["US_STOCK"])

    # 【审计修复 P1-2】数学预加权计算（作为 LLM 决策锚点）
    pre_weight = _compute_weighted_score(fundamental, technical, sentiment, weights, market_type)
    pre_signal_text = (
        f"数学预加权结果: {pre_weight['pre_signal']} "
        f"(加权分={pre_weight['weighted_score']:.3f}, "
        f"平均置信度={pre_weight['avg_confidence']:.2f})\n"
        f"分项: {' | '.join(pre_weight['breakdown'].values())}"
    )

    revision_instruction = ""
    if is_revision:
        rejection_reason = risk_decision.get("rejection_reason", "风险过高")
        revision_instruction = f"""
【重要】本次为风控修订模式（第 {risk_rejection_count} 次）：
风控官拒绝原因：{rejection_reason}
请重新评估并提出更为保守、仓位更低、风控合规的方案。
"""

    debate_instruction = ""
    if debate_outcome:
        debate_instruction = f"""
【辩论结果参考】
辩论共识建议: {debate_outcome.get('resolved_recommendation')}
决定性因素: {debate_outcome.get('deciding_factor')}
辩论摘要: {debate_outcome.get('debate_summary', '')[:200]}
"""

    system_prompt = f"""你是拥有20年经验的基金经理，负责整合多路研究报告，做出最终投资决策。

当前市场策略 ({market_type}):
- 基本面权重: {weights['fundamental']:.0%}（已有真实PE/PB/ROE数据支撑）
- 技术面权重: {weights['technical']:.0%}
- 舆情权重:   {weights['sentiment']:.0%}

【量化预加权参考锚点】（请以此为基础，结合定性分析调整）
{pre_signal_text}
{revision_instruction}{debate_instruction}
决策原则:
1. 以上方数学预加权结果为锚点，除非定性分析发现明显错误，否则最终建议应与锚点方向一致
2. 三方向高度一致 → 强信号；两方向一致一方向中性 → 中等信号
3. 任何一方向极高置信度反向信号 → 须认真对待
4. 存在辩论结果时，以辩论共识为重要参考

【CampusQuant 目标用户：在校大学生 — 不可豁免的决策原则】
1. 本金安全优先于一切：宁可错过机会，绝不承担超额风险
2. HOLD 是最佳朋友：信号不够清晰（综合置信度<0.60）时，果断选 HOLD
3. 严禁推荐任何形式的杠杆操作、融资融券（Margin Trading）
4. 投资周期建议≥3个月，不推荐短线高频操作
5. 单标的建议仓位：A股≤15%，港股/美股≤10%（大学生本金有限）
6. 若综合置信度<0.60，recommendation 必须输出 HOLD，不强行找入场理由

【强制置信度计算规则 — 必须像计算器一样输出精准小数】
1. confidence 必须是 0.00~1.00 之间的两位小数，严禁输出 0.60 / 0.65 等敷衍默认值。
2. 基础分 0.50（完全中性信号）。
3. 动态加减规则（可叠加）：多项核心指标高度一致 +0.25~+0.35；单一明确信号 +0.10~+0.20；信号轻微矛盾 -0.05~-0.10；核心数据极度恶化 +0.30~+0.40；信号严重矛盾或数据不足 -0.15~-0.25。
4. 示例：基础 0.50 + 三方向一致看涨 +0.20 + 辩论共识强 +0.10 = 0.80；你必须给出类似 0.42、0.78、0.88 的叠加结果。

【强制 JSON 输出结构 — 必须完整填写所有字段，不得遗漏】
你必须且只能输出以下 JSON 对象，不加任何 Markdown 包裹或额外说明：
{{
  "recommendation": "BUY或SELL或HOLD（三选一，必填）",
  "confidence": 0.73,
  "reasoning": "综合分析推理过程（必填，不少于50字）",
  "key_factors": ["因素1", "因素2", "因素3"]
}}
规则：recommendation 只能是 BUY/SELL/HOLD；confidence 为0~1之间的浮点数；reasoning 不得为空。"""

    user_prompt = f"""
请综合以下研究报告，对 **{symbol}** 做出投资决策。

【基本面报告】
- 建议: {fund_rec} | 置信度: {fundamental.get('confidence', 0):.2f}
- 核心逻辑: {fundamental.get('reasoning', 'N/A')[:200]}
- 关键因素: {', '.join(fundamental.get('key_factors', [])[:3])}

【技术面报告】
- 建议: {tech_rec} | 置信度: {technical.get('confidence', 0):.2f}
- 核心逻辑: {technical.get('reasoning', 'N/A')[:200]}

【舆情报告】
- 建议: {sentiment.get('recommendation', 'HOLD')} | 置信度: {sentiment.get('confidence', 0):.2f}
- 核心逻辑: {sentiment.get('reasoning', 'N/A')[:200]}

【宏观知识参考】
{rag_context[:600] if rag_context else '暂无'}

请给出最终的综合投资建议（BUY/SELL/HOLD），包含详细推理。
"""

    try:
        llm = _build_llm(temperature=0.1)
        structured_llm = llm.with_structured_output(AnalystReport)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        decision: AnalystReport = await structured_llm.ainvoke(messages)

        conflict_msg = "⚡ 检测到基本面与技术面冲突！" if has_conflict else ""
        log_msg = _log_entry(
            "portfolio_node",
            f"综合决策: {decision.recommendation} | 置信度: {decision.confidence:.2f} | "
            f"冲突: {has_conflict} {conflict_msg}"
        )
        logger.info(log_msg)

        portfolio_decision = decision.model_dump(mode='json')

        return {
            "fundamental_report": {**fundamental, "_portfolio_decision": portfolio_decision},
            "has_conflict":       has_conflict,
            "current_node":       "portfolio_node",
            "execution_log":      [log_msg],
            "messages": [AIMessage(
                content=f"基金经理决策: {decision.recommendation} "
                        f"(置信度 {decision.confidence:.0%})"
                        + (f" ⚡ 冲突检测触发辩论" if has_conflict else ""),
                name="portfolio_node",
            )],
        }

    except Exception as e:
        _log_node_error("portfolio_node", e)
        return {
            "has_conflict":  False,
            "execution_log": [_log_entry("portfolio_node", f"❌ 失败: {e}")],
            "error_type":    "llm_error",
            "messages":      [AIMessage(content=f"基金经理异常: {e}", name="portfolio_node")],
        }


# ════════════════════════════════════════════════════════════════
# NODE 7 — debate_node（条件触发：基本面 vs 技术面冲突时）
# ════════════════════════════════════════════════════════════════

# ── DebateOutcome 字段别名映射表 ────────────────────────────────
# Qwen 等模型在 with_structured_output 降级时常用同义词替代标准字段名。
# 此表将常见别名规范化为 DebateOutcome 的确切字段名，作为解析兜底。
_DEBATE_KEY_MAP: dict[str, str] = {
    # resolved_recommendation
    "final_recommendation":    "resolved_recommendation",
    "recommendation":          "resolved_recommendation",
    "decision":                "resolved_recommendation",
    "final_decision":          "resolved_recommendation",
    "trade_recommendation":    "resolved_recommendation",
    "action":                  "resolved_recommendation",
    "final_action":            "resolved_recommendation",
    # confidence_after_debate
    "final_confidence":        "confidence_after_debate",
    "confidence":              "confidence_after_debate",
    "confidence_score":        "confidence_after_debate",
    "debate_confidence":       "confidence_after_debate",
    "confidence_level":        "confidence_after_debate",
    "final_confidence_score":  "confidence_after_debate",
    # bull_core_argument
    "bull_argument":           "bull_core_argument",
    "bull_argument_core":      "bull_core_argument",
    "bullish_argument":        "bull_core_argument",
    "bull_main_argument":      "bull_core_argument",
    "bull_key_argument":       "bull_core_argument",
    "long_core_argument":      "bull_core_argument",
    # bear_core_argument
    "bear_argument":           "bear_core_argument",
    "bear_argument_core":      "bear_core_argument",
    "bearish_argument":        "bear_core_argument",
    "bear_main_argument":      "bear_core_argument",
    "bear_key_argument":       "bear_core_argument",
    "short_core_argument":     "bear_core_argument",
    # bull_argument_summary
    "bull_summary":            "bull_argument_summary",
    "bull_detail":             "bull_argument_summary",
    "bullish_summary":         "bull_argument_summary",
    "long_argument_summary":   "bull_argument_summary",
    # bear_argument_summary
    "bear_summary":            "bear_argument_summary",
    "bear_detail":             "bear_argument_summary",
    "bearish_summary":         "bear_argument_summary",
    "short_argument_summary":  "bear_argument_summary",
    # deciding_factor
    "key_factor":              "deciding_factor",
    "decisive_factor":         "deciding_factor",
    "key_deciding_factor":     "deciding_factor",
    "resolution_factor":       "deciding_factor",
    "tipping_point":           "deciding_factor",
    "key_decision_factor":     "deciding_factor",
    # debate_summary
    "summary":                 "debate_summary",
    "overall_summary":         "debate_summary",
    "conclusion":              "debate_summary",
    "debate_conclusion":       "debate_summary",
    "analysis_summary":        "debate_summary",
    "final_summary":           "debate_summary",
}


def _normalize_debate_json(raw: dict) -> dict:
    """将 LLM 输出的 JSON 键名归一化为 DebateOutcome 的确切字段名。"""
    return {_DEBATE_KEY_MAP.get(k, k): v for k, v in raw.items()}


async def debate_node(state: TradingGraphState) -> dict:
    """
    多空辩论节点:
      - 仅在 portfolio_node 检测到 has_conflict=True 时被路由触发
      - 模拟"多头方（基本面）vs 空头方（技术面）"的结构化辩论
      - 三层解析兜底：① with_structured_output → ② 原始JSON+键名归一化 → ③ 纠错重试
      - debate_rounds 自增 1，防止无限循环
    """
    import re as _re

    symbol        = _sanitize_symbol(state.get("symbol") or state.get("stock_code", "UNKNOWN"))
    fundamental   = state.get("fundamental_report", {}) or {}
    technical     = state.get("technical_report", {})   or {}
    debate_rounds = state.get("debate_rounds", 0)

    logger.info(f"[debate_node] 启动辩论第 {debate_rounds + 1} 轮: {symbol}")

    fund_rec   = fundamental.get("recommendation", "HOLD")
    fund_logic = fundamental.get("reasoning", "")[:300]
    tech_rec   = technical.get("recommendation", "HOLD")
    tech_logic = technical.get("reasoning", "")[:300]

    market_type = state.get("market_type", "ALL")

    # 【Per-Node RAG】辩论专项检索：行业核心风险点、前景、护城河
    debate_rag_context = ""
    try:
        debate_rag_context = search_knowledge_base.invoke({
            "query":       f"{symbol} 行业核心风险点 前景 护城河",
            "market_type": market_type,
            "max_length":  1200,
        })
        logger.info(f"[debate_node] 专项 RAG 检索完成: {len(debate_rag_context)} 字符")
    except Exception as _re:
        logger.warning(f"[debate_node] 专项 RAG 检索失败（降级为空）: {_re}")

    # ── Task 1: 在 Prompt 中显式列出全部 8 个字段名，杜绝 LLM 自造键名 ──
    system_prompt = """你是一位权威的投资决策委员会主席，负责主持并裁决多空方的投资辩论。
你的职责:
1. 客观总结多方（基本面）和空方（技术面）的核心论点
2. 识别双方论点的根本分歧所在
3. 基于证据和逻辑权重，裁决出合理的投资方向
4. 裁决后降低置信度以体现不确定性（通常降低0.1-0.2）
裁决原则: 趋势性基本面 > 短期技术波动；但若技术信号极强（金叉+高量能），可优先技术面

【极其严格的格式要求】
你必须仅输出合法的 JSON 对象，绝对禁止包含任何 markdown 标记（如 ```json）或分析过程的废话。
你的 JSON 的键名（Keys）必须一字不差地完全等于以下 8 个字段名，严禁自定义字段，严禁改名或翻译：
{
  "resolved_recommendation": "最终建议，只能是 BUY、SELL、HOLD 三个英文大写值之一",
  "confidence_after_debate": 0.65,
  "bull_core_argument": "多头方一句话核心论点（字符串，必填，不得为空）",
  "bear_core_argument": "空头方一句话核心论点（字符串，必填，不得为空）",
  "bull_argument_summary": "多头方论点的完整展开（字符串）",
  "bear_argument_summary": "空头方论点的完整展开（字符串）",
  "deciding_factor": "最终裁决的决定性因素，一句话说明（字符串，必填）",
  "debate_summary": "辩论全程摘要，至少80个汉字，覆盖双方主要论点和裁决依据（字符串，必填）"
}

注意: confidence_after_debate 是 0.0~1.0 的数字，不是字符串。resolved_recommendation 只能是 BUY、SELL 或 HOLD。"""

    # 论点摘要（LLM 生成，非真实多轮对话日志）
    bull_argument = (
        f"【第{debate_rounds + 1}轮多头论点】\n"
        f"立场: {fund_rec} | 置信度: {fundamental.get('confidence', 0.5):.2f}\n"
        f"论据: {fund_logic}\n"
        f"关键因素: {', '.join(fundamental.get('key_factors', [])[:3])}"
    )
    bear_argument = (
        f"【第{debate_rounds + 1}轮空头论点】\n"
        f"立场: {tech_rec} | 置信度: {technical.get('confidence', 0.5):.2f}\n"
        f"论据: {tech_logic}\n"
        f"关键因素: {', '.join(technical.get('key_factors', [])[:3])}"
    )

    user_prompt = f"""【辩论议题】{symbol} 当前应该 BUY 还是 SELL？

{bull_argument}

{bear_argument}

【外部研报与宏观事实（作为裁判裁决依据）】
{debate_rag_context if debate_rag_context else '暂无外部研报参考'}

请主持本次辩论，总结双方核心论点，分析根本分歧，并给出裁决。
严格按照 system prompt 中规定的 8 个字段名输出 JSON，不得添加、删除或重命名任何字段。"""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]

    def _extract_outcome_from_text(text: str) -> DebateOutcome:
        """从原始文本中提取 JSON 并构建 DebateOutcome（兜底解析）。"""
        # 去除 markdown 代码块
        clean = _re.sub(r"```(?:json|JSON)?", "", text).strip().strip("`").strip()
        m = _re.search(r"\{[\s\S]*\}", clean)
        if not m:
            raise ValueError(f"LLM 响应中未找到 JSON 对象: {clean[:300]}")
        raw_dict = json.loads(m.group())
        normalized = _normalize_debate_json(raw_dict)
        return DebateOutcome(**normalized)

    try:
        llm = _build_llm(temperature=0.1)
        outcome: DebateOutcome | None = None

        # ── Task 2 层1: with_structured_output（Function Calling / JSON Schema 路径）──
        try:
            structured_llm = llm.with_structured_output(DebateOutcome)
            outcome = await asyncio.wait_for(
                structured_llm.ainvoke(messages), timeout=180.0
            )
            logger.info("[debate_node] ✅ 层1 with_structured_output 解析成功")
        except Exception as e1:
            logger.warning(
                f"[debate_node] 层1 with_structured_output 失败 ({type(e1).__name__}: {e1})，"
                f"降级至层2 原始JSON解析"
            )

            # ── Task 2 层2: 原始调用 + 键名归一化兜底解析 ──────────────────
            try:
                raw_resp = await asyncio.wait_for(llm.ainvoke(messages), timeout=180.0)
                raw_text = raw_resp.content if hasattr(raw_resp, "content") else str(raw_resp)
                outcome = _extract_outcome_from_text(raw_text)
                logger.info("[debate_node] ✅ 层2 原始JSON+键名归一化解析成功")
            except Exception as e2:
                logger.warning(
                    f"[debate_node] 层2 解析失败 ({type(e2).__name__}: {e2})，"
                    f"降级至层3 纠错重试"
                )

                # ── Task 2 层3: 带纠错指令的一次重试 ──────────────────────
                correction_prompt = HumanMessage(content=(
                    f"你上一次输出的 JSON 键名有误，导致以下解析错误: {e2}\n\n"
                    f"请严格按照以下模板重新输出，只输出纯 JSON，不要任何其他内容:\n"
                    f'{{\n'
                    f'  "resolved_recommendation": "BUY 或 SELL 或 HOLD",\n'
                    f'  "confidence_after_debate": 0.5,\n'
                    f'  "bull_core_argument": "多头方核心论点",\n'
                    f'  "bear_core_argument": "空头方核心论点",\n'
                    f'  "bull_argument_summary": "多头方详细论点",\n'
                    f'  "bear_argument_summary": "空头方详细论点",\n'
                    f'  "deciding_factor": "决定性因素",\n'
                    f'  "debate_summary": "辩论摘要，至少80字"\n'
                    f'}}'
                ))
                retry_resp = await asyncio.wait_for(
                    llm.ainvoke(messages + [correction_prompt]), timeout=120.0
                )
                retry_text = retry_resp.content if hasattr(retry_resp, "content") else str(retry_resp)
                outcome = _extract_outcome_from_text(retry_text)
                logger.info("[debate_node] ✅ 层3 纠错重试解析成功")

        outcome_dict = outcome.model_dump(mode='json')
        new_rounds   = debate_rounds + 1
        log_msg = _log_entry(
            "debate_node",
            f"辩论第{new_rounds}轮完成 | 裁决: {outcome.resolved_recommendation} "
            f"| 置信度: {outcome.confidence_after_debate:.2f} "
            f"| 决定因素: {outcome.deciding_factor[:50]}"
        )
        logger.info(log_msg)

        return {
            "debate_outcome": outcome_dict,
            "debate_rounds":  new_rounds,
            "has_conflict":   False,
            "current_node":   "debate_node",
            "execution_log":  [log_msg],
            "messages": [AIMessage(
                content=f"⚖️ 辩论裁决（第{new_rounds}轮）: {outcome.resolved_recommendation} "
                        f"(置信度 {outcome.confidence_after_debate:.0%}) — "
                        f"决定因素: {outcome.deciding_factor}",
                name="debate_node",
            )],
        }

    except Exception as e:
        _log_node_error("debate_node", e)
        return {
            "debate_outcome": {
                "resolved_recommendation": "HOLD",
                "confidence_after_debate": 0.3,
                "bull_core_argument": fund_logic[:100],
                "bear_core_argument": tech_logic[:100],
                "bull_argument_summary": bull_argument,
                "bear_argument_summary": bear_argument,
                "deciding_factor": "三层解析均失败，保守降级 HOLD",
                "debate_summary": f"解析异常: {e}",
            },
            "debate_rounds":  state.get("debate_rounds", 0) + 1,
            "has_conflict":   False,
            "execution_log":  [_log_entry("debate_node", f"⚠️ 三层兜底均失败，降级处理: {e}")],
            "error_type":     "llm_error",
            "messages":       [AIMessage(content=f"辩论异常: {e}", name="debate_node")],
        }


# ════════════════════════════════════════════════════════════════
# NODE 8 — risk_node（风控审核）
# ════════════════════════════════════════════════════════════════

@_guard_node("risk_decision")
async def risk_node(state: TradingGraphState) -> dict:
    """
    风控官审核节点:
      - 综合价格风险（ATR%）、仓位合规性、市场类型风控规则
      - 使用 with_structured_output(RiskDecision) 输出结构化风控决策
      - Prompt 从 _PROMPTS["risk"] 取基础前缀，动态拼装市场规则
      - 若 REJECTED，risk_rejection_count += 1，触发 portfolio_node 修订
    """
    symbol               = _sanitize_symbol(state.get("symbol") or state.get("stock_code", "UNKNOWN"))
    market_type          = state.get("market_type", "US_STOCK")
    market_data          = state.get("market_data", {})
    indicators           = market_data.get("indicators", {})
    fundamental          = state.get("fundamental_report", {}) or {}
    portfolio_decision   = fundamental.get("_portfolio_decision", {})
    risk_rejection_count = state.get("risk_rejection_count", 0)

    current_rec  = portfolio_decision.get("recommendation", "HOLD")
    current_conf = portfolio_decision.get("confidence", 0.5)
    atr_pct      = indicators.get("ATR_pct", 2.0)
    vol_ratio    = indicators.get("volume_ratio", 1.0)

    logger.info(f"[risk_node] 风控审核: {symbol} | 建议={current_rec} | ATR%={atr_pct}")

    # 从 Prompt 字典取基础前缀，再动态拼装市场规则
    base_prompt  = _PROMPTS["risk"]["BASE"]
    system_prompt = f"""{base_prompt}

【CampusQuant 大学生专属风控规则 — 全部不可豁免】
1. 严禁任何形式的杠杆交易、融资融券（Margin Trading）、期权投机 — 发现立即拒绝
2. 单笔最大仓位上限（{market_type}）:
   - A股: ≤ 15%（比通常标准更保守）
   - 港股: ≤ 10%（流动性弱，需更高安全边际）
   - 美股: ≤ 10%（汇率风险 + 信息不对称）
4. 综合置信度 < 0.60 → 自动将仓位压至 ≤ 5%，或直接拒绝
5. ATR% > 5% 为高波动警报，> 8% 直接拒绝（超出大学生风险承受能力）
6. 止损：必须严格设置（A股≥5%，港股/美股≥7%），保护有限本金
7. 大学生假设总本金 ≤ 5万元，单次最大亏损金额不超过 3000 元

审核维度: 波动率合规 | 仓位合规 | 止损设置 | 置信度合规

【强制 JSON 输出结构 — 必须完整填写，绝不遗漏任何字段】
你必须且只能输出以下 JSON 对象，不加任何 Markdown 包裹或额外说明：
{{
  "approval_status": "APPROVED或CONDITIONAL或REJECTED（三选一，必填）",
  "risk_level": "LOW或MEDIUM或HIGH或EXTREME（四选一，必填）",
  "position_pct": 10.0,
  "stop_loss_pct": 7.0,
  "take_profit_pct": 15.0,
  "rejection_reason": null,
  "conditions": [],
  "max_loss_amount": null
}}
规则：approval_status 只能是 APPROVED/CONDITIONAL/REJECTED；position_pct 单位为百分比（如10.0表示10%）。"""

    user_prompt = f"""
请审核以下交易方案的风险合规性（模拟交易，非真实交易所）。

【标的基本信息】
- 标的: {symbol} | 市场: {market_type}
- 当前价格: {market_data.get('latest_price', 'N/A')}
- ATR%(14日波动率): {atr_pct}%
- 量比: {vol_ratio}
- RSI14: {indicators.get('RSI14', 'N/A')}

【综合决策方案】
- 建议方向: {current_rec}
- 综合置信度: {current_conf:.2f}
- 推理: {portfolio_decision.get('reasoning', 'N/A')[:200]}

【风控修订次数】{risk_rejection_count}（若已多次拒绝，说明风险确实不可接受，维持拒绝或给出更严格的条件）

请给出 APPROVED / CONDITIONAL / REJECTED 决策，并设定仓位、止损、止盈比例。
"""

    try:
        llm = _build_llm(temperature=0.1)
        structured_llm = llm.with_structured_output(RiskDecision)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        decision: RiskDecision = await asyncio.wait_for(structured_llm.ainvoke(messages), timeout=180.0)

        decision_dict = decision.model_dump(mode='json')

        # ── 量纲规范化：position_pct 统一为百分比（0-20），不允许小数形式 ──
        # Pydantic 上限 le=20.0，LLM 若输出 0.10（本意 10%）会通过校验但量纲错误
        raw_pos = decision_dict["position_pct"]
        max_pos = 15.0 if market_type == "A_STOCK" else 10.0
        if raw_pos < 1.0 and raw_pos > 0:
            corrected_pos = round(raw_pos * 100, 1)
            logger.warning(
                f"[risk_node] position_pct 量纲修正(小数→百分比): {raw_pos} → {corrected_pos}%"
            )
            decision_dict["position_pct"] = min(corrected_pos, max_pos)

        # 【审计修复 P1-3】代码层强制校验——LLM 输出可能仍不满足学生风控红线
        if decision_dict["position_pct"] > max_pos:
            logger.warning(
                f"[risk_node] 仓位超限 {decision_dict['position_pct']:.1f}% > {max_pos:.0f}%，强制截断"
            )
            decision_dict["position_pct"] = max_pos
            if decision_dict["approval_status"] == "APPROVED":
                decision_dict["approval_status"] = "CONDITIONAL"
                decision_dict.setdefault("conditions", []).append(
                    f"仓位已由系统截断至{max_pos:.0f}%（学生风控上限）"
                )
        if decision_dict["stop_loss_pct"] < 0.5:
            logger.warning(
                f"[risk_node] 止损比例过小 {decision_dict['stop_loss_pct']:.2f}%，强制设为5%"
            )
            decision_dict["stop_loss_pct"] = 5.0
            decision_dict.setdefault("conditions", []).append("止损比例已由系统修正为5%（最低有效止损）")

        # ── ATR 硬阻断（P1 修复：代码层强制执行，非 Prompt 约束）────────
        new_status, new_pct, atr_block_reason = _apply_atr_hard_block(
            decision_dict["approval_status"],
            decision_dict["position_pct"],
            float(atr_pct),
        )
        if atr_block_reason:
            logger.warning(f"[risk_node] ATR 硬阻断触发: {atr_block_reason}")
            decision_dict["approval_status"] = new_status
            decision_dict["position_pct"]    = new_pct
            decision_dict.setdefault("conditions", []).append(atr_block_reason)
            if new_status == "REJECTED":
                decision_dict["rejection_reason"] = atr_block_reason

        # ── 单次亏损上限反算（P1 修复：代码层强制执行）────────────────────
        final_pct, loss_cap_reason = _apply_max_loss_cap(
            decision_dict["position_pct"],
            decision_dict["stop_loss_pct"],
        )
        if loss_cap_reason:
            logger.warning(f"[risk_node] 亏损上限截断: {loss_cap_reason}")
            decision_dict["position_pct"] = final_pct
            decision_dict.setdefault("conditions", []).append(loss_cap_reason)

        new_rejection_count = risk_rejection_count
        if decision_dict["approval_status"] == "REJECTED":
            new_rejection_count += 1

        status_emoji = {"APPROVED": "✅", "CONDITIONAL": "⚠️", "REJECTED": "❌"}
        log_msg = _log_entry(
            "risk_node",
            f"{status_emoji.get(decision_dict['approval_status'], '?')} 风控审批: "
            f"{decision_dict['approval_status']} | 风险级别: {decision_dict['risk_level']} "
            f"| 仓位: {decision_dict['position_pct']:.1f}% "
            f"| 止损: {decision_dict['stop_loss_pct']:.1f}%（代码层校验后）"
        )
        logger.info(log_msg)

        return {
            "risk_decision":        decision_dict,
            "risk_rejection_count": new_rejection_count,
            "current_node":         "risk_node",
            "execution_log":        [log_msg],
            "messages": [AIMessage(
                content=f"风控审批: {decision_dict['approval_status']} "
                        f"({decision_dict['risk_level']} 风险) | 仓位 {decision_dict['position_pct']:.0f}% "
                        + (f"| 拒绝原因: {decision_dict['rejection_reason']}" if decision_dict.get("rejection_reason") else ""),
                name="risk_node",
            )],
        }

    except Exception as e:
        _log_node_error("risk_node", e)
        fallback_decision = {
            "approval_status": "REJECTED", "risk_level": "HIGH",
            "position_pct": 5.0, "stop_loss_pct": 7.0, "take_profit_pct": 15.0,
            "rejection_reason": f"风控评估异常，安全降级拒绝: {str(e)[:100]}",
            "conditions": ["风控评估异常，安全降级拒绝"],
            "max_loss_amount": None,
        }
        return {
            "risk_decision":        fallback_decision,
            "risk_rejection_count": risk_rejection_count + 1,
            "execution_log":        [_log_entry("risk_node", f"⚠️ 降级处理（REJECTED）: {e}")],
            "error_type":           "llm_error",
            "messages":             [AIMessage(content=f"风控异常: {e}", name="risk_node")],
        }


# ════════════════════════════════════════════════════════════════
# NODE 9 — trade_executor（生成最终模拟交易指令）
# ════════════════════════════════════════════════════════════════

async def trade_executor(state: TradingGraphState) -> dict:
    """
    交易指令生成节点:
      - 整合风控决策（仓位、止损、止盈）与基金经理决策
      - 使用 with_structured_output(TradeOrder) 生成精确结构化交易指令
      - TradeOrder.simulated = True，指向本地模拟撮合引擎，不连接任何真实交易所
      - 填充 state.trade_order，标记 status = "completed"
    """
    symbol         = _sanitize_symbol(state.get("symbol") or state.get("stock_code", "UNKNOWN"))
    market_type    = state.get("market_type", "US_STOCK")
    market_data    = state.get("market_data", {})
    fundamental    = state.get("fundamental_report", {}) or {}
    portfolio_dec  = fundamental.get("_portfolio_decision", {})
    risk_decision  = state.get("risk_decision", {}) or {}
    debate_outcome = state.get("debate_outcome")

    action          = portfolio_dec.get("recommendation", "HOLD")
    confidence      = portfolio_dec.get("confidence", 0.5)
    position_pct    = risk_decision.get("position_pct", 10.0)
    stop_loss_pct   = risk_decision.get("stop_loss_pct", 7.0)
    take_profit_pct = risk_decision.get("take_profit_pct", 15.0)

    # ── 实时现价获取（降级至日线收盘价）──────────────────────────
    is_spot_price = False
    try:
        from tools.market_data import get_spot_price_raw
        import asyncio as _asyncio
        loop = _asyncio.get_event_loop()
        spot_data    = await loop.run_in_executor(None, get_spot_price_raw, symbol)
        current_price = spot_data.get("price") or market_data.get("latest_price", 0.0)
        is_spot_price = not spot_data.get("is_fallback", True)
        logger.info(
            f"[trade_executor] 实时现价: {current_price} "
            f"({'实时' if is_spot_price else '日线收盘'})"
        )
    except Exception as _e:
        logger.warning(f"[trade_executor] 实时价格获取失败，使用历史收盘价: {_e}")
        current_price = market_data.get("latest_price", 0.0)

    logger.info(f"[trade_executor] 生成模拟交易指令: {symbol} | {action} | 仓位={position_pct:.1f}%")

    # ── 置信度惩罚（P0 修复：代码层强制执行，非 Prompt 约束）──────────
    action, position_pct, penalty_note = _apply_confidence_penalty(action, confidence, position_pct)
    if penalty_note:
        logger.warning(f"[trade_executor] 置信度惩罚触发: {penalty_note}")

    if current_price and action == "BUY":
        stop_loss   = round(current_price * (1 - stop_loss_pct / 100), 4)
        take_profit = round(current_price * (1 + take_profit_pct / 100), 4)
        limit_price = round(current_price * 1.002, 4)
    elif current_price and action == "SELL":
        stop_loss   = round(current_price * (1 + stop_loss_pct / 100), 4)
        take_profit = round(current_price * (1 - take_profit_pct / 100), 4)
        limit_price = round(current_price * 0.998, 4)
    else:
        stop_loss = take_profit = limit_price = None

    system_prompt = (
        "你是执行层交易员，负责将研究决策转化为精确的模拟交易指令。\n"
        "注意：所有指令仅用于本地模拟撮合引擎，不连接任何真实交易所。\n\n"
        "【强制 JSON 输出结构 — 所有字段必须完整填写，绝不遗漏】\n"
        "你必须且只能输出以下 JSON 对象，不加任何 Markdown 包裹或额外说明：\n"
        "{\n"
        '  "symbol": "交易标的代码，如 600519.SH / AAPL / 00700.HK（必填）",\n'
        '  "action": "BUY或SELL或HOLD（三选一，必填）",\n'
        '  "quantity_pct": 10.0,\n'
        '  "order_type": "LIMIT或MARKET（二选一，默认LIMIT）",\n'
        '  "limit_price": null,\n'
        '  "stop_loss": null,\n'
        '  "take_profit": null,\n'
        '  "rationale": "核心交易逻辑说明，不少于30字（必填）",\n'
        '  "confidence": 0.70,\n'
        '  "market_type": "A_STOCK或HK_STOCK或US_STOCK（三选一，必填）",\n'
        '  "valid_until": null,\n'
        '  "simulated": true\n'
        "}\n"
        "规则：quantity_pct 单位为百分比（如10.0表示10%，HOLD时填0.0）；"
        "market_type 必须从 A_STOCK / HK_STOCK / US_STOCK 三选一；"
        "simulated 必须为 true；confidence 为0~1之间的浮点数。"
    )

    user_prompt = f"""
请将以下投资决策转化为标准化模拟交易指令。

【决策信息】
- 标的: {symbol} | 市场: {market_type}
- 操作方向: {action}
- 综合置信度: {confidence:.2f}
- 建议仓位: {position_pct:.1f}% 总资金
- 当前价格: {current_price}
- 建议止损价: {stop_loss}（{stop_loss_pct:.1f}%）
- 建议止盈价: {take_profit}（{take_profit_pct:.1f}%）
- 基金经理推理: {portfolio_dec.get('reasoning', '')[:200]}
{f"- 辩论共识: {debate_outcome.get('resolved_recommendation')} (决定因素: {debate_outcome.get('deciding_factor', '')[:100]})" if debate_outcome else ""}
- 风控条件: {', '.join(risk_decision.get('conditions', [])[:3])}
- 模拟交易: 是（指向本地撮合引擎）

请生成完整的模拟交易指令，rationale 需包含核心投资逻辑（不少于30字）。
simulated 字段必须为 true。
"""

    try:
        llm = _build_llm(temperature=0.1)
        structured_llm = llm.with_structured_output(TradeOrder)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        order: TradeOrder = await asyncio.wait_for(structured_llm.ainvoke(messages), timeout=180.0)

        order_dict = order.model_dump(mode='json')
        order_dict["simulated"]       = True            # 强制确保 simulated=True
        order_dict["execution_price"] = current_price   # 注入实时/收盘现价
        order_dict["is_spot_price"]   = is_spot_price   # 是否为实时现价

        # ── 量纲规范化：统一以百分比（%）表示仓位，修复 LLM 量纲混乱 ──
        # 风控 position_pct 已经过代码层校验（单位：%，如 10.0 = 10%）
        # LLM 有时将其误输出为小数（0.10）或超大值（100.0），均需修正
        if action in ("BUY", "SELL"):
            raw_qty = order_dict.get("quantity_pct", position_pct)
            if raw_qty < 1.0 and position_pct >= 1.0:
                # 小数形式：0.10 → 10.0%
                logger.warning(
                    f"[trade_executor] quantity_pct 量纲修正(小数→百分比): "
                    f"{raw_qty} → {position_pct}%"
                )
                order_dict["quantity_pct"] = position_pct
            elif raw_qty > position_pct * 2.0 + 1.0:
                # 超出风控给定仓位 2 倍以上：截断到 position_pct
                logger.warning(
                    f"[trade_executor] quantity_pct 量纲修正(超限截断): "
                    f"{raw_qty}% → {position_pct}%"
                )
                order_dict["quantity_pct"] = position_pct
        elif action == "HOLD":
            order_dict["quantity_pct"] = 0.0  # HOLD 仓位统一为 0

        log_msg = _log_entry(
            "trade_executor",
            f"🎯 模拟交易指令: {order.action} {symbol} | 仓位 {order_dict['quantity_pct']:.1f}% "
            f"| 止损 {order.stop_loss} | 止盈 {order.take_profit} "
            f"| 置信度 {order.confidence:.2f} | 模拟={order_dict['simulated']}"
        )
        logger.info(log_msg)

        return {
            "trade_order":   order_dict,
            "current_node":  "trade_executor",
            "status":        "completed",
            "execution_log": [log_msg],
            "messages": [AIMessage(
                content=f"✅ 模拟交易指令已生成: {order.action} {symbol} "
                        f"仓位 {order.quantity_pct:.0f}% | "
                        f"止损 {order.stop_loss} | 止盈 {order.take_profit} | "
                        f"{order.rationale[:100]}",
                name="trade_executor",
            )],
        }

    except Exception as e:
        _log_node_error("trade_executor", e)
        fallback_order = {
            "symbol": symbol, "action": action,
            "quantity_pct": position_pct, "order_type": "MARKET",
            "limit_price": None, "stop_loss": stop_loss,
            "take_profit": take_profit,
            "rationale": f"系统异常，降级输出: {str(e)[:100]}",
            "confidence": confidence, "market_type": market_type,
            "valid_until": None, "simulated": True,
            "execution_price": current_price, "is_spot_price": is_spot_price,
        }
        return {
            "trade_order":   fallback_order,
            "current_node":  "trade_executor",
            "status":        "completed",
            "execution_log": [_log_entry("trade_executor", f"⚠️ 降级处理: {e}")],
            "error_type":    "llm_error",
            "messages": [AIMessage(content=f"交易指令生成异常（降级）: {e}", name="trade_executor")],
        }


# ════════════════════════════════════════════════════════════════
# NODE 10 — health_node（持仓体检，独立分支）
# ════════════════════════════════════════════════════════════════

async def health_node(state: TradingGraphState) -> dict:
    """
    持仓体检节点（新增，完善"持仓体检"业务流）:
      - 读取 state.portfolio_positions（PortfolioPosition 列表）
      - 计算集中度风险、回撤风险、流动性评分
      - 使用 with_structured_output(PortfolioHealthReport) 输出结构化诊断
      - Prompt 从 _PROMPTS["health"] 字典取值（外化管理）
      - 严格执行大学生风控规则：单仓 ≤ 15%，无杠杆

    注意: health_node 是独立业务分支，不依赖 data_node / portfolio_node，
    可由 builder.py 单独路由到 END。
    """
    positions_raw = state.get("portfolio_positions") or []
    symbol        = _sanitize_symbol(state.get("symbol", "PORTFOLIO"))  # 持仓体检时 symbol 为 "PORTFOLIO"

    if not positions_raw:
        logger.warning("[health_node] portfolio_positions 为空，无法执行体检")
        empty_report = {
            "health_score": 0.0, "concentration_risk": "EXTREME",
            "max_drawdown_est": 100.0, "liquidity_score": 0.0,
            "overweight_positions": [], "high_risk_positions": [],
            "recommendations": ["请先输入持仓数据"],
            "overall_diagnosis": "未提供持仓数据，无法执行体检。",
        }
        return {
            "health_report": empty_report,
            "current_node":  "health_node",
            "status":        "completed",
            "execution_log": [_log_entry("health_node", "⚠️ 持仓数据为空")],
            "messages": [AIMessage(content="持仓数据为空，请先输入持仓", name="health_node")],
        }

    logger.info(f"[health_node] 开始持仓体检，持仓数: {len(positions_raw)}")

    # 【审计修复 P0-3/P1-3】获取各持仓的真实当前价格，计算真实市值权重
    enriched_positions = []
    for p in positions_raw:
        pos = dict(p)
        sym = pos.get("symbol", "")
        if sym and pos.get("current_price") is None:
            try:
                raw_json = get_market_data.invoke({"symbol": sym, "days": 5})
                raw_data = json.loads(raw_json)
                if raw_data.get("status") == "success":
                    pos["current_price"] = raw_data.get("latest_price")
                    logger.info(f"[health_node] {sym} 实时价格: {pos['current_price']}")
            except Exception as _pe:
                logger.warning(f"[health_node] {sym} 价格获取失败: {_pe}")
        enriched_positions.append(pos)

    # 计算真实市值权重（需要当前价格）
    total_value = sum(
        (p.get("current_price") or p.get("avg_cost", 0)) * p.get("quantity", 0)
        for p in enriched_positions
    )
    if total_value > 0:
        for p in enriched_positions:
            price = p.get("current_price") or p.get("avg_cost", 0)
            qty   = p.get("quantity", 0)
            p["weight_pct"] = round(price * qty / total_value * 100, 2)
            p["market_value"] = round(price * qty, 2)
            p["pnl_pct"] = round(
                (price - p.get("avg_cost", price)) / max(p.get("avg_cost", price), 1e-9) * 100, 2
            ) if p.get("avg_cost") else None

    # 格式化持仓数据（含真实价格与盈亏）
    positions_text = "\n".join([
        f"  {i+1}. {p.get('symbol','?')} ({p.get('market_type','?')}) "
        f"| 数量: {p.get('quantity','?')} | 成本: {p.get('avg_cost','?')} "
        f"| 市价: {p.get('current_price', '未获取')} "
        f"| 市值: {p.get('market_value', 'N/A')} "
        f"| 盈亏: {p.get('pnl_pct', 'N/A')}% "
        f"| 权重: {p.get('weight_pct', 'N/A')}%"
        for i, p in enumerate(enriched_positions)
    ])

    system_prompt = _PROMPTS["health"]["DEFAULT"]

    user_prompt = f"""
请对以下持仓组合进行全面健康体检，输出 PortfolioHealthReport 格式报告。

【持仓明细（含真实价格与浮盈亏）】
{positions_text}

【持仓总市值】{f'{total_value:.2f} 元' if total_value > 0 else '未获取'}

【大学生风控规则】
- 单标的权重上限: A股≤15%，港股/美股≤10%
- 总本金假设: ≤5万元
- 严禁杠杆（发现则健康分=0）
- 定投宽基ETF视为最健康的持仓选择
- 浮亏超15%的标的列为高风险持仓

请综合评估集中度风险、回撤风险、流动性，给出健康评分（0-100）和优化建议。
注意：liquidity_score 请使用 0-100 分制（100分=极佳流动性）。
"""

    try:
        llm = _build_llm(temperature=0.2)
        structured_llm = llm.with_structured_output(PortfolioHealthReport)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        report: PortfolioHealthReport = await asyncio.wait_for(structured_llm.ainvoke(messages), timeout=180.0)

        report_dict = report.model_dump(mode='json')
        log_msg = _log_entry(
            "health_node",
            f"持仓体检完成 | 健康分: {report.health_score:.1f}/100 "
            f"| 集中度风险: {report.concentration_risk} "
            f"| 最大回撤估算: {report.max_drawdown_est:.1f}%"
        )
        logger.info(log_msg)

        return {
            "health_report":       report_dict,
            "portfolio_positions": enriched_positions,   # 写回含实时价格的持仓数据
            "current_node":        "health_node",
            "status":              "completed",
            "execution_log":       [log_msg],
            "messages": [AIMessage(
                content=f"🩺 持仓体检完成 | 健康分: {report.health_score:.0f}/100 "
                        f"| 集中度: {report.concentration_risk} "
                        f"| {report.overall_diagnosis[:80]}...",
                name="health_node",
            )],
        }

    except Exception as e:
        _log_node_error("health_node", e)
        fallback = {
            "health_score": 50.0, "concentration_risk": "MEDIUM",
            "max_drawdown_est": 30.0, "liquidity_score": 5.0,
            "overweight_positions": [], "high_risk_positions": [],
            "recommendations": ["体检服务暂时异常，请稍后重试"],
            "overall_diagnosis": f"持仓体检异常: {str(e)[:100]}",
        }
        return {
            "health_report": fallback,
            "current_node":  "health_node",
            "status":        "error",
            "execution_log": [_log_entry("health_node", f"⚠️ 降级处理: {e}")],
            "error_type":    "llm_error",
            "error_message": str(e),
            "messages": [AIMessage(content=f"持仓体检异常: {e}", name="health_node")],
        }


# ════════════════════════════════════════════════════════════════
# 条件边函数（由 builder.py 注册）
# ════════════════════════════════════════════════════════════════

def route_after_portfolio(state: TradingGraphState) -> str:
    """
    portfolio_node → 下一节点路由:
      - has_conflict=True 且 debate_rounds < MAX_DEBATE_ROUNDS → debate_node
      - 否则 → risk_node
    """
    if (
        state.get("has_conflict", False)
        and state.get("debate_rounds", 0) < MAX_DEBATE_ROUNDS
    ):
        logger.info(f"[router] portfolio → debate (冲突, 轮次={state.get('debate_rounds', 0)})")
        return "debate_node"
    logger.info("[router] portfolio → risk_node")
    return "risk_node"


def route_after_risk(state: TradingGraphState) -> str:
    """
    risk_node → 下一节点路由:
      - REJECTED 且 risk_rejection_count < MAX_RISK_RETRIES → portfolio_node
      - 否则（APPROVED / CONDITIONAL / 超出重试次数）→ trade_executor
    """
    risk    = state.get("risk_decision", {}) or {}
    status  = risk.get("approval_status", "APPROVED")
    retries = state.get("risk_rejection_count", 0)

    if status == "REJECTED" and retries < MAX_RISK_RETRIES:
        logger.info(f"[router] risk → portfolio (拒绝, 次数={retries})")
        return "portfolio_node"
    logger.info(f"[router] risk → trade_executor ({status})")
    return "trade_executor"
