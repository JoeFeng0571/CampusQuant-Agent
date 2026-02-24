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
                   └─ [通过] trade_executor ← 生成交易指令
                       └─ END

所有节点均为 async 函数，接收 TradingGraphState，返回 dict (部分状态更新)。
LLM 输出全部通过 with_structured_output(PydanticModel) 产生，
彻底消除正则/JSON 手动解析。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from loguru import logger

from config import config
from graph.state import (
    MAX_DEBATE_ROUNDS,
    MAX_RISK_RETRIES,
    AnalystReport,
    DebateOutcome,
    RiskDecision,
    TradeOrder,
    TradingGraphState,
)
from tools.market_data import calculate_technical_indicators, get_market_data
from tools.knowledge_base import search_knowledge_base


# ════════════════════════════════════════════════════════════════
# 内部工具：LLM 工厂函数
# ════════════════════════════════════════════════════════════════

def _build_llm(temperature: float = 0.3):
    """
    根据 config.PRIMARY_LLM_PROVIDER 构建 LangChain ChatModel。
    支持 Anthropic Claude 和 OpenAI GPT，自动切换。
    """
    provider = config.PRIMARY_LLM_PROVIDER.lower()

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=config.ANTHROPIC_MODEL,
            api_key=config.ANTHROPIC_API_KEY,
            temperature=temperature,
            max_tokens=2048,
        )
    else:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=config.OPENAI_MODEL,
            api_key=config.OPENAI_API_KEY,
            temperature=temperature,
            max_tokens=2048,
        )


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _log_entry(node: str, msg: str) -> str:
    return f"[{_ts()}] [{node}] {msg}"


# ════════════════════════════════════════════════════════════════
# NODE 1 — data_node
# ════════════════════════════════════════════════════════════════

async def data_node(state: TradingGraphState) -> dict:
    """
    数据情报员节点:
      - 调用 get_market_data @tool 获取 OHLCV 行情
      - 调用 calculate_technical_indicators @tool 预计算所有技术指标
      - 将结果写入 state.market_data，供后续并行节点使用
    """
    symbol = state["symbol"]
    logger.info(f"[data_node] 开始获取市场数据: {symbol}")

    try:
        # 调用工具（在节点内直接 invoke，不通过 ToolNode，简化异步链路）
        raw_json  = get_market_data.invoke({"symbol": symbol, "days": 180})
        tech_json = calculate_technical_indicators.invoke({"market_data_json": raw_json})

        raw_data  = json.loads(raw_json)
        tech_data = json.loads(tech_json)

        market_data = {**raw_data, **tech_data}
        market_data.pop("_ohlcv_json", None)  # 移除大块原始数据节省状态空间

        log_msg = _log_entry(
            "data_node",
            f"数据获取成功 | {symbol} | 最新价: {raw_data.get('latest_price')} "
            f"| 技术信号: {tech_data.get('indicators', {}).get('tech_signal', 'N/A')}"
        )

        return {
            "market_data":   market_data,
            "market_type":   raw_data.get("market_type", "UNKNOWN"),
            "current_node":  "data_node",
            "execution_log": [log_msg],
            "messages": [AIMessage(
                content=f"市场数据已获取: {symbol} | 价格 {raw_data.get('latest_price')} | "
                        f"信号 {tech_data.get('indicators', {}).get('tech_signal')}",
                name="data_node",
            )],
        }

    except Exception as e:
        logger.error(f"[data_node] 失败: {e}")
        return {
            "market_data":   {"status": "error", "error": str(e)},
            "current_node":  "data_node",
            "execution_log": [_log_entry("data_node", f"❌ 数据获取失败: {e}")],
            "status":        "error",
            "error_message": str(e),
            "messages": [AIMessage(content=f"数据获取失败: {e}", name="data_node")],
        }


# ════════════════════════════════════════════════════════════════
# NODE 2 — rag_node（与分析师节点并行）
# ════════════════════════════════════════════════════════════════

async def rag_node(state: TradingGraphState) -> dict:
    """
    RAG 知识检索节点:
      - 根据 symbol + market_type 构建检索 query
      - 调用 FAISS search_knowledge_base @tool
      - 将检索结果写入 state.rag_context，作为分析师的 RAG 上下文
    """
    symbol      = state["symbol"]
    market_type = state.get("market_type", "ALL")
    market_data = state.get("market_data", {})

    indicators  = market_data.get("indicators", {})
    tech_signal = indicators.get("tech_signal", "HOLD")

    # 构建语义查询（结合当前技术信号）
    query = (
        f"{symbol} {market_type} 市场政策 行业景气度 宏观经济"
        f" 技术信号{tech_signal} 投资分析"
    )

    logger.info(f"[rag_node] 检索知识库: {query[:60]}...")
    rag_text = search_knowledge_base.invoke({"query": query, "market_type": market_type})

    return {
        "rag_context":   rag_text,
        "current_node":  "rag_node",
        "execution_log": [_log_entry("rag_node", f"RAG 检索完成，返回 {len(rag_text)} 字符")],
        "messages": [AIMessage(
            content=f"RAG 知识检索完成: {len(rag_text)} 字符上下文已准备",
            name="rag_node",
        )],
    }


# ════════════════════════════════════════════════════════════════
# NODE 3 — fundamental_node（与其他分析师并行）
# ════════════════════════════════════════════════════════════════

_FUNDAMENTAL_PROMPTS = {
    "A_STOCK": """你是专注A股市场的景气度与政策驱动分析专家。
核心框架：行业景气度（30%）+ EPS增速/PEG（30%）+ 政策催化剂（25%）+ 资金热度（15%）
原则：不以低静态PE/PB作为主要买入理由；重视"业绩高增+政策利好+资金介入"三重共振。

【CampusQuant 大学生用户特别规则】
- 本金安全第一：优先推荐主板大盘蓝筹或宽基ETF，规避中小盘投机标的
- 不建议高频盯盘：投资周期以中长期（3个月以上）为宜，拒绝追涨杀跌
- 置信度低于60%时直接建议 HOLD，宁可错过机会也不在不确定时下注
- 定投宽基ETF（如沪深300ETF）是大学生首选入门工具，可作为备选推荐""",

    "HK_STOCK": """你是专注港股市场的价值投资分析专家，融合香港市场特色与全球视野。
核心框架：合理估值PE/PB（35%）+ 自由现金流FCF（25%）+ 分红/回购（20%）+ 宏观因素（20%）
原则：港股需更高安全边际；关注A/H溢价与南向资金；美联储降息是重要催化剂。

【CampusQuant 大学生用户特别规则】
- 本金安全第一：港股流动性弱于A股，需更保守的安全边际（至少30%折价保护）
- 不建议高频盯盘：港股受外资影响波动较大，建议长线持有优质标的
- 置信度低于60%时直接建议 HOLD
- 严禁使用杠杆或融资融券（Margin Trading）""",

    "US_STOCK": """你是专注美股市场的成长价值双轨分析专家。
核心框架：EPS增速/PEG（30%）+ 自由现金流（25%）+ AI/科技主题（25%）+ 宏观Beta（20%）
原则：关注美联储降息周期对成长股估值扩张；AI算力主题享有估值溢价。

【CampusQuant 大学生用户特别规则】
- 本金安全第一：美股科技股波动大，仓位须更保守（单标的≤10%总资金）
- 不建议高频盯盘：持仓周期建议3个月以上，关注季度财报而非日内波动
- 置信度低于60%时直接建议 HOLD
- 严禁任何形式的杠杆交易、期权投机（Options Trading）""",
}


async def fundamental_node(state: TradingGraphState) -> dict:
    """
    基本面分析师节点:
      - 调用 LLM + with_structured_output(AnalystReport)
      - 基于市场类型差异化 System Prompt
      - 结合 RAG 上下文（state.rag_context）提升分析深度
    """
    symbol      = state["symbol"]
    market_type = state.get("market_type", "US_STOCK")
    market_data = state.get("market_data", {})
    rag_context = state.get("rag_context", "")

    logger.info(f"[fundamental_node] 开始基本面分析: {symbol}")

    system_prompt = _FUNDAMENTAL_PROMPTS.get(
        market_type,
        _FUNDAMENTAL_PROMPTS["US_STOCK"]
    )

    user_prompt = f"""
请对标的 **{symbol}** ({market_type}) 进行基本面研判，输出结构化报告。

【市场数据摘要】
- 最新价格: {market_data.get('latest_price', 'N/A')}
- 区间最高/最低: {market_data.get('period_high', 'N/A')} / {market_data.get('period_low', 'N/A')}
- 价格变动: {market_data.get('price_change_pct', 'N/A')}%
- 成交量比（10日均）: {market_data.get('indicators', {}).get('volume_ratio', 'N/A')}

【RAG 知识库参考】
{rag_context[:1200] if rag_context else '暂无'}

请基于以上信息，以你的专业框架分析该标的的基本面状况，给出 BUY/SELL/HOLD 建议。
注意：price_target 使用绝对价格数值。
"""

    try:
        llm = _build_llm(temperature=0.3)
        structured_llm = llm.with_structured_output(AnalystReport)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        report: AnalystReport = await structured_llm.ainvoke(messages)

        report_dict = report.model_dump()
        log_msg = _log_entry(
            "fundamental_node",
            f"基本面分析: {report.recommendation} | 置信度: {report.confidence:.2f} | "
            f"信号强度: {report.signal_strength}"
        )
        logger.info(log_msg)

        return {
            "fundamental_report": report_dict,
            "current_node":       "fundamental_node",
            "execution_log":      [log_msg],
            "messages": [AIMessage(
                content=f"基本面分析完成: {report.recommendation} "
                        f"(置信度 {report.confidence:.0%}) — {report.reasoning[:80]}...",
                name="fundamental_node",
            )],
        }

    except Exception as e:
        logger.error(f"[fundamental_node] 失败: {e}")
        fallback = {
            "recommendation": "HOLD",
            "confidence": 0.3,
            "reasoning": f"基本面分析异常: {str(e)}",
            "key_factors": [], "risk_factors": [],
            "price_target": None, "signal_strength": "WEAK",
        }
        return {
            "fundamental_report": fallback,
            "execution_log":      [_log_entry("fundamental_node", f"⚠️ 降级处理: {e}")],
            "messages": [AIMessage(content=f"基本面分析异常: {e}", name="fundamental_node")],
        }


# ════════════════════════════════════════════════════════════════
# NODE 4 — technical_node（与其他分析师并行）
# ════════════════════════════════════════════════════════════════

async def technical_node(state: TradingGraphState) -> dict:
    """
    技术分析师节点:
      - 基于预计算的技术指标（MACD/RSI/BOLL/MA 等）进行信号解读
      - 使用 with_structured_output(AnalystReport) 输出结构化报告
    """
    symbol      = state["symbol"]
    market_type = state.get("market_type", "US_STOCK")
    market_data = state.get("market_data", {})
    indicators  = market_data.get("indicators", {})

    logger.info(f"[technical_node] 开始技术分析: {symbol}")

    system_prompt = """你是拥有20年经验的量化技术分析专家，擅长多周期信号融合与量价关系分析。
核心框架: 趋势（MA系统 30%）+ 动量（MACD 30%）+ 超买超卖（RSI/BOLL 25%）+ 量价（量比 15%）
分析原则:
- 多重信号共振时才发出强信号；单一信号不足以支撑高置信度结论
- 量价背离（放量阴线、缩量阳线）是重要预警信号
- 技术面形态服从于大趋势方向（顺势交易）"""

    # 格式化技术指标为可读形式
    ind_summary = "\n".join([
        f"  MA系统: MA5={indicators.get('MA5','N/A')} | MA20={indicators.get('MA20','N/A')} | MA60={indicators.get('MA60','N/A')}",
        f"  趋势: 上方MA20={indicators.get('above_ma20','N/A')} | 上方MA60={indicators.get('above_ma60','N/A')} | 多头排列={indicators.get('ma_bullish_alignment','N/A')}",
        f"  MACD: DIF={indicators.get('MACD','N/A')} | DEA={indicators.get('MACD_signal','N/A')} | 柱={indicators.get('MACD_hist','N/A')} | 金叉={indicators.get('MACD_golden_cross','N/A')}",
        f"  RSI14: {indicators.get('RSI14','N/A')} | 超买={indicators.get('RSI_overbought','N/A')} | 超卖={indicators.get('RSI_oversold','N/A')}",
        f"  BOLL %B: {indicators.get('BOLL_pct_B','N/A')} | 近上轨={indicators.get('near_boll_upper','N/A')} | 近下轨={indicators.get('near_boll_lower','N/A')}",
        f"  量比: {indicators.get('volume_ratio','N/A')} | 高量能={indicators.get('high_volume','N/A')}",
        f"  ATR%: {indicators.get('ATR_pct','N/A')}%",
        f"  系统信号: {indicators.get('tech_signal','N/A')} (多头信号数={indicators.get('bull_signal_count',0)}, 空头信号数={indicators.get('bear_signal_count',0)})",
    ])

    user_prompt = f"""
请对标的 **{symbol}** ({market_type}) 进行技术面研判。

【当前价格】{market_data.get('latest_price', 'N/A')}

【技术指标详情】
{ind_summary}

基于上述多维度技术信号，综合判断当前价格所处的趋势位置与动量状态，
给出 BUY/SELL/HOLD 建议，并量化置信度。
"""

    try:
        llm = _build_llm(temperature=0.2)
        structured_llm = llm.with_structured_output(AnalystReport)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        report: AnalystReport = await structured_llm.ainvoke(messages)

        report_dict = report.model_dump()
        log_msg = _log_entry(
            "technical_node",
            f"技术分析: {report.recommendation} | 置信度: {report.confidence:.2f} | "
            f"系统信号: {indicators.get('tech_signal')}"
        )
        logger.info(log_msg)

        return {
            "technical_report": report_dict,
            "current_node":     "technical_node",
            "execution_log":    [log_msg],
            "messages": [AIMessage(
                content=f"技术分析完成: {report.recommendation} "
                        f"(置信度 {report.confidence:.0%}) — {report.reasoning[:80]}...",
                name="technical_node",
            )],
        }

    except Exception as e:
        logger.error(f"[technical_node] 失败: {e}")
        # 降级：直接使用技术指标系统信号
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

async def sentiment_node(state: TradingGraphState) -> dict:
    """
    舆情分析师节点:
      - 基于市场数据量价特征与 RAG 宏观知识推断市场情绪
      - 分析板块轮动、资金流向、宏观情绪三维度
    """
    symbol      = state["symbol"]
    market_type = state.get("market_type", "US_STOCK")
    market_data = state.get("market_data", {})
    rag_context = state.get("rag_context", "")
    indicators  = market_data.get("indicators", {})

    logger.info(f"[sentiment_node] 开始舆情分析: {symbol}")

    system_prompt = """你是专业的金融市场舆情与资金面分析师，擅长从量价数据与宏观环境中读取市场情绪。
分析维度:
1. 资金热度（量比/换手率）: 判断主力资金行为
2. 市场情绪（宏观政策面）: 当前市场整体风险偏好
3. 板块轮动: 资金是否正在轮入/轮出本标的所在板块
4. 极端情绪信号: 是否存在恐慌性卖出或疯狂追涨
分析原则:
- 结合量能与价格形态识别"主力资金意图"
- 极端情绪（RSI>80 或 RSI<20）往往是反转信号
- 宏观政策利好是A股情绪的最强催化剂"""

    user_prompt = f"""
请对标的 **{symbol}** ({market_type}) 进行市场情绪与资金面研判。

【量价数据】
- 价格变动: {market_data.get('price_change_pct', 'N/A')}%
- 量比（近10日均）: {indicators.get('volume_ratio', 'N/A')}
- 高量能信号: {indicators.get('high_volume', 'N/A')}
- RSI14: {indicators.get('RSI14', 'N/A')}（>70超买, <30超卖）
- BOLL %B: {indicators.get('BOLL_pct_B', 'N/A')}（>0.85接近上轨，<0.15接近下轨）

【宏观情绪参考（RAG）】
{rag_context[:800] if rag_context else '暂无宏观背景信息'}

基于以上信息，判断当前市场情绪（资金热度、风险偏好、板块轮动方向），
给出 BUY/SELL/HOLD 建议。
"""

    try:
        llm = _build_llm(temperature=0.4)
        structured_llm = llm.with_structured_output(AnalystReport)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        report: AnalystReport = await structured_llm.ainvoke(messages)

        report_dict = report.model_dump()
        log_msg = _log_entry(
            "sentiment_node",
            f"舆情分析: {report.recommendation} | 置信度: {report.confidence:.2f}"
        )
        logger.info(log_msg)

        return {
            "sentiment_report": report_dict,
            "current_node":     "sentiment_node",
            "execution_log":    [log_msg],
            "messages": [AIMessage(
                content=f"舆情分析完成: {report.recommendation} "
                        f"(置信度 {report.confidence:.0%}) — {report.reasoning[:80]}...",
                name="sentiment_node",
            )],
        }

    except Exception as e:
        logger.error(f"[sentiment_node] 失败: {e}")
        fallback = {
            "recommendation": "HOLD", "confidence": 0.3,
            "reasoning": f"舆情分析异常: {str(e)}",
            "key_factors": [], "risk_factors": [],
            "price_target": None, "signal_strength": "WEAK",
        }
        return {
            "sentiment_report": fallback,
            "execution_log":    [_log_entry("sentiment_node", f"⚠️ 降级处理: {e}")],
            "messages": [AIMessage(content=f"舆情分析异常: {e}", name="sentiment_node")],
        }


# ════════════════════════════════════════════════════════════════
# NODE 6 — portfolio_node（汇聚分析、检测冲突）
# ════════════════════════════════════════════════════════════════

# 市场差异化权重配置（CampusQuant 版：加密货币已移除）
# A股：政策/情绪驱动为主；港股/美股：基本面价值为主
_MARKET_WEIGHTS = {
    "A_STOCK":  {"fundamental": 0.20, "technical": 0.35, "sentiment": 0.35, "risk": 0.10},
    "HK_STOCK": {"fundamental": 0.45, "technical": 0.20, "sentiment": 0.25, "risk": 0.10},
    "US_STOCK": {"fundamental": 0.35, "technical": 0.30, "sentiment": 0.25, "risk": 0.10},
}


async def portfolio_node(state: TradingGraphState) -> dict:
    """
    基金经理综合决策节点:
      - 汇聚三大分析师报告 + RAG 上下文 + 风控反馈
      - 检测基本面 vs 技术面冲突（has_conflict）
      - 若 risk_rejection_count > 0，进入风控修订模式（降仓/调仓）
      - 输出最终投资建议（供后续辩论或风控使用）
    """
    symbol               = state["symbol"]
    market_type          = state.get("market_type", "US_STOCK")
    fundamental          = state.get("fundamental_report", {}) or {}
    technical            = state.get("technical_report", {})   or {}
    sentiment            = state.get("sentiment_report", {})   or {}
    debate_outcome       = state.get("debate_outcome")
    risk_decision        = state.get("risk_decision")
    risk_rejection_count = state.get("risk_rejection_count", 0)
    rag_context          = state.get("rag_context", "")

    logger.info(f"[portfolio_node] 开始综合决策: {symbol} | 风控拒绝次数={risk_rejection_count}")

    # ── 冲突检测 ──────────────────────────────────────────────
    # 仅在首次执行（无辩论结果、无风控拒绝）时检测冲突
    is_revision = risk_rejection_count > 0 and risk_decision is not None
    fund_rec    = fundamental.get("recommendation", "HOLD")
    tech_rec    = technical.get("recommendation", "HOLD")

    has_conflict = (
        not is_revision
        and debate_outcome is None          # 辩论后不再检测
        and fund_rec in ("BUY", "SELL")
        and tech_rec in ("BUY", "SELL")
        and fund_rec != tech_rec
    )

    # ── 权重配置 ──────────────────────────────────────────────
    weights = _MARKET_WEIGHTS.get(market_type, _MARKET_WEIGHTS["US_STOCK"])

    # ── 构建 System Prompt ─────────────────────────────────────
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
- 基本面权重: {weights['fundamental']:.0%}
- 技术面权重: {weights['technical']:.0%}
- 情绪面权重: {weights['sentiment']:.0%}
{revision_instruction}{debate_instruction}
决策原则:
1. 综合加权评分时，不同方向信号视置信度折扣
2. 三方向高度一致 → 强信号；两方向一致一方向中性 → 中等信号
3. 任何一方向极高置信度反向信号 → 须认真对待
4. 存在辩论结果时，以辩论共识为重要参考

【CampusQuant 目标用户：在校大学生 — 不可豁免的决策原则】
1. 本金安全优先于一切：宁可错过机会，绝不承担超额风险
2. HOLD 是最佳朋友：信号不够清晰（综合置信度<0.60）时，果断选 HOLD
3. 严禁推荐任何形式的杠杆操作、融资融券（Margin Trading）
4. 投资周期建议≥3个月，不推荐短线高频操作
5. 单标的建议仓位：A股≤15%，港股/美股≤10%（大学生本金有限）
6. 若综合置信度<0.60，recommendation 必须输出 HOLD，不强行找入场理由"""

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
        llm = _build_llm(temperature=0.3)
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

        # 将 portfolio 决策暂存为 fundamental_report 的 override
        # （debate_node 和 risk_node 会读取 fundamental_report 作为当前决策）
        portfolio_decision = decision.model_dump()

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
        logger.error(f"[portfolio_node] 失败: {e}")
        return {
            "has_conflict":  False,
            "execution_log": [_log_entry("portfolio_node", f"❌ 失败: {e}")],
            "messages":      [AIMessage(content=f"基金经理异常: {e}", name="portfolio_node")],
        }


# ════════════════════════════════════════════════════════════════
# NODE 7 — debate_node（条件触发：基本面 vs 技术面冲突时）
# ════════════════════════════════════════════════════════════════

async def debate_node(state: TradingGraphState) -> dict:
    """
    多空辩论节点（Debate Node）:
      - 仅在 portfolio_node 检测到 has_conflict=True 时被路由触发
      - 模拟"多头方（基本面）vs 空头方（技术面）"的结构化辩论
      - 由 LLM 担任裁判，输出辩论共识（DebateOutcome）
      - debate_rounds 自增 1，防止无限循环
    """
    symbol           = state["symbol"]
    fundamental      = state.get("fundamental_report", {}) or {}
    technical        = state.get("technical_report", {})   or {}
    debate_rounds    = state.get("debate_rounds", 0)

    logger.info(f"[debate_node] 启动辩论第 {debate_rounds + 1} 轮: {symbol}")

    fund_rec    = fundamental.get("recommendation", "HOLD")
    fund_logic  = fundamental.get("reasoning", "")[:300]
    tech_rec    = technical.get("recommendation", "HOLD")
    tech_logic  = technical.get("reasoning", "")[:300]

    system_prompt = """你是一位权威的投资决策委员会主席，负责主持并裁决多空方的投资辩论。
你的职责:
1. 客观总结多方（基本面）和空方（技术面）的核心论点
2. 识别双方论点的根本分歧所在
3. 基于证据和逻辑权重，裁决出合理的投资方向
4. 裁决后降低置信度以体现不确定性（通常降低0.1-0.2）
裁决原则: 趋势性基本面 > 短期技术波动；但若技术信号极强（金叉+高量能），可优先技术面"""

    user_prompt = f"""
【辩论议题】{symbol} 当前应该 BUY 还是 SELL？

【多头方（基本面）论点】
立场: {fund_rec}
论据: {fund_logic}
置信度: {fundamental.get('confidence', 0.5):.2f}
关键支撑因素: {', '.join(fundamental.get('key_factors', [])[:3])}

【空头方（技术面）论点】
立场: {tech_rec}
论据: {tech_logic}
置信度: {technical.get('confidence', 0.5):.2f}
关键支撑因素: {', '.join(technical.get('key_factors', [])[:3])}

请主持本次辩论，总结双方核心论点，分析根本分歧，并给出裁决。
"""

    try:
        llm = _build_llm(temperature=0.5)
        structured_llm = llm.with_structured_output(DebateOutcome)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        outcome: DebateOutcome = await structured_llm.ainvoke(messages)

        outcome_dict  = outcome.model_dump()
        new_rounds    = debate_rounds + 1
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
            "has_conflict":   False,   # 辩论已消解冲突
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
        logger.error(f"[debate_node] 失败: {e}")
        return {
            "debate_outcome": {
                "resolved_recommendation": "HOLD",
                "confidence_after_debate": 0.3,
                "bull_core_argument": fund_logic[:100],
                "bear_core_argument": tech_logic[:100],
                "deciding_factor": "辩论异常，保守 HOLD",
                "debate_summary": str(e),
            },
            "debate_rounds":  state.get("debate_rounds", 0) + 1,
            "has_conflict":   False,
            "execution_log":  [_log_entry("debate_node", f"⚠️ 降级处理: {e}")],
            "messages":       [AIMessage(content=f"辩论异常: {e}", name="debate_node")],
        }


# ════════════════════════════════════════════════════════════════
# NODE 8 — risk_node（风控审核）
# ════════════════════════════════════════════════════════════════

async def risk_node(state: TradingGraphState) -> dict:
    """
    风控官审核节点:
      - 综合价格风险（ATR%）、仓位合规性、市场类型风控规则
      - 使用 with_structured_output(RiskDecision) 输出结构化风控决策
      - 若 REJECTED，risk_rejection_count += 1，触发 portfolio_node 修订
    """
    symbol               = state["symbol"]
    market_type          = state.get("market_type", "US_STOCK")
    market_data          = state.get("market_data", {})
    indicators           = market_data.get("indicators", {})
    fundamental          = state.get("fundamental_report", {}) or {}
    portfolio_decision   = fundamental.get("_portfolio_decision", {})
    risk_rejection_count = state.get("risk_rejection_count", 0)

    # 读取当前综合建议
    current_rec  = portfolio_decision.get("recommendation", "HOLD")
    current_conf = portfolio_decision.get("confidence", 0.5)
    atr_pct      = indicators.get("ATR_pct", 2.0)
    vol_ratio    = indicators.get("volume_ratio", 1.0)

    logger.info(f"[risk_node] 风控审核: {symbol} | 建议={current_rec} | ATR%={atr_pct}")

    system_prompt = f"""你是严格的风险控制官，专为在校大学生用户把关交易风险。

【CampusQuant 大学生专属风控规则 — 全部不可豁免】
1. 严禁任何形式的杠杆交易、融资融券（Margin Trading）、期权投机 — 发现立即拒绝
2. 严禁加密货币交易（已从系统移除）— 若出现直接拒绝
3. 单笔最大仓位上限（{market_type}）:
   - A股: ≤ 15%（比通常标准更保守）
   - 港股: ≤ 10%（流动性弱，需更高安全边际）
   - 美股: ≤ 10%（汇率风险 + 信息不对称）
4. 综合置信度 < 0.60 → 自动将仓位压至 ≤ 5%，或直接拒绝
5. ATR% > 5% 为高波动警报，> 8% 直接拒绝（超出大学生风险承受能力）
6. 止损：必须严格设置（A股≥5%，港股/美股≥7%），保护有限本金
7. 大学生假设总本金 ≤ 5万元，单次最大亏损金额不超过 3000 元

审核维度:
1. 波动率合规: ATR% 是否超标
2. 仓位合规: 是否超过市场上限
3. 止损设置: 是否包含合理止损
4. 置信度合规: 低置信度必须降仓或拒绝

你有一票否决权，若方案对大学生风险不可接受，直接拒绝并给出教育性说明。"""

    user_prompt = f"""
请审核以下交易方案的风险合规性。

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

【风控修订次数】{risk_rejection_count}（若已多次拒绝请放宽标准，给出条件审批）

请给出 APPROVED / CONDITIONAL / REJECTED 决策，并设定仓位、止损、止盈比例。
"""

    try:
        llm = _build_llm(temperature=0.1)
        structured_llm = llm.with_structured_output(RiskDecision)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        decision: RiskDecision = await structured_llm.ainvoke(messages)

        decision_dict = decision.model_dump()
        new_rejection_count = risk_rejection_count
        if decision.approval_status == "REJECTED":
            new_rejection_count += 1

        status_emoji = {"APPROVED": "✅", "CONDITIONAL": "⚠️", "REJECTED": "❌"}
        log_msg = _log_entry(
            "risk_node",
            f"{status_emoji.get(decision.approval_status, '?')} 风控审批: "
            f"{decision.approval_status} | 风险级别: {decision.risk_level} "
            f"| 仓位: {decision.position_pct:.1f}% "
            f"| 止损: {decision.stop_loss_pct:.1f}%"
        )
        logger.info(log_msg)

        return {
            "risk_decision":        decision_dict,
            "risk_rejection_count": new_rejection_count,
            "current_node":         "risk_node",
            "execution_log":        [log_msg],
            "messages": [AIMessage(
                content=f"风控审批: {decision.approval_status} "
                        f"({decision.risk_level} 风险) | 仓位 {decision.position_pct:.0f}% "
                        + (f"| 拒绝原因: {decision.rejection_reason}" if decision.rejection_reason else ""),
                name="risk_node",
            )],
        }

    except Exception as e:
        logger.error(f"[risk_node] 失败: {e}")
        fallback_decision = {
            "approval_status": "CONDITIONAL", "risk_level": "MEDIUM",
            "position_pct": 10.0, "stop_loss_pct": 7.0, "take_profit_pct": 15.0,
            "rejection_reason": None, "conditions": ["风控评估异常，降级使用保守仓位"],
            "max_loss_amount": None,
        }
        return {
            "risk_decision":        fallback_decision,
            "risk_rejection_count": risk_rejection_count,
            "execution_log":        [_log_entry("risk_node", f"⚠️ 降级处理: {e}")],
            "messages":             [AIMessage(content=f"风控异常: {e}", name="risk_node")],
        }


# ════════════════════════════════════════════════════════════════
# NODE 9 — trade_executor（生成最终交易指令）
# ════════════════════════════════════════════════════════════════

async def trade_executor(state: TradingGraphState) -> dict:
    """
    交易指令生成节点:
      - 整合风控决策（仓位、止损、止盈）与基金经理决策
      - 使用 with_structured_output(TradeOrder) 生成精确的结构化交易指令
      - 填充 state.trade_order，标记 status = "completed"
    """
    symbol         = state["symbol"]
    market_type    = state.get("market_type", "US_STOCK")
    market_data    = state.get("market_data", {})
    fundamental    = state.get("fundamental_report", {}) or {}
    portfolio_dec  = fundamental.get("_portfolio_decision", {})
    risk_decision  = state.get("risk_decision", {}) or {}
    debate_outcome = state.get("debate_outcome")

    current_price    = market_data.get("latest_price", 0.0)
    action           = portfolio_dec.get("recommendation", "HOLD")
    confidence       = portfolio_dec.get("confidence", 0.5)
    position_pct     = risk_decision.get("position_pct", 10.0)
    stop_loss_pct    = risk_decision.get("stop_loss_pct", 7.0)
    take_profit_pct  = risk_decision.get("take_profit_pct", 15.0)

    logger.info(f"[trade_executor] 生成交易指令: {symbol} | {action} | 仓位={position_pct:.1f}%")

    # 计算绝对价格
    if current_price and action == "BUY":
        stop_loss   = round(current_price * (1 - stop_loss_pct / 100), 4)
        take_profit = round(current_price * (1 + take_profit_pct / 100), 4)
        limit_price = round(current_price * 1.002, 4)   # 略高于当前价的限价单
    elif current_price and action == "SELL":
        stop_loss   = round(current_price * (1 + stop_loss_pct / 100), 4)   # 卖空止损
        take_profit = round(current_price * (1 - take_profit_pct / 100), 4)
        limit_price = round(current_price * 0.998, 4)
    else:
        stop_loss = take_profit = limit_price = None

    system_prompt = "你是执行层交易员，负责将研究决策转化为精确的交易指令。"
    user_prompt = f"""
请将以下投资决策转化为标准化交易指令。

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

请生成完整的交易指令，rationale 需包含核心投资逻辑（不少于30字）。
"""

    try:
        llm = _build_llm(temperature=0.1)
        structured_llm = llm.with_structured_output(TradeOrder)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        order: TradeOrder = await structured_llm.ainvoke(messages)

        order_dict = order.model_dump()
        log_msg = _log_entry(
            "trade_executor",
            f"🎯 交易指令生成: {order.action} {symbol} | 仓位 {order.quantity_pct:.1f}% "
            f"| 止损 {order.stop_loss} | 止盈 {order.take_profit} "
            f"| 置信度 {order.confidence:.2f}"
        )
        logger.info(log_msg)

        return {
            "trade_order":   order_dict,
            "current_node":  "trade_executor",
            "status":        "completed",
            "execution_log": [log_msg],
            "messages": [AIMessage(
                content=f"✅ 交易指令已生成: {order.action} {symbol} "
                        f"仓位 {order.quantity_pct:.0f}% | "
                        f"止损 {order.stop_loss} | 止盈 {order.take_profit} | "
                        f"{order.rationale[:100]}",
                name="trade_executor",
            )],
        }

    except Exception as e:
        logger.error(f"[trade_executor] 失败: {e}")
        fallback_order = {
            "symbol": symbol, "action": action,
            "quantity_pct": position_pct, "order_type": "MARKET",
            "limit_price": None, "stop_loss": stop_loss,
            "take_profit": take_profit,
            "rationale": f"系统异常，降级输出: {str(e)[:100]}",
            "confidence": confidence, "market_type": market_type,
            "valid_until": None,
        }
        return {
            "trade_order":   fallback_order,
            "current_node":  "trade_executor",
            "status":        "completed",
            "execution_log": [_log_entry("trade_executor", f"⚠️ 降级处理: {e}")],
            "messages": [AIMessage(content=f"交易指令生成异常（降级）: {e}", name="trade_executor")],
        }


# ════════════════════════════════════════════════════════════════
# 条件边函数（由 builder.py 注册）
# ════════════════════════════════════════════════════════════════

def route_after_portfolio(state: TradingGraphState) -> str:
    """
    portfolio_node → 下一节点路由逻辑:
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
    risk_node → 下一节点路由逻辑:
      - REJECTED 且 risk_rejection_count < MAX_RISK_RETRIES → portfolio_node (修订)
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
