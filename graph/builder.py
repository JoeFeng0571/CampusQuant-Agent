"""
graph/builder.py — LangGraph StateGraph 装配与编译

图拓扑（执行流程）:
  ┌─────────────────────────────────────────────────────────┐
  │  START → data_node                                      │
  │          │                                              │
  │     ┌────┼────────────────┬──────────────┐             │
  │     ▼    ▼                ▼              ▼             │
  │  fund_  tech_         sentiment_       rag_           │
  │  node   node          node             node           │
  │  (并)   (并)          (并)             (并)           │
  │     └────┴────────────────┴──────────────┘             │
  │                    ▼                                    │
  │              portfolio_node ◄──────────┐               │
  │           ┌────────┴────────┐          │               │
  │           ▼ [冲突]          ▼ [无冲突] │               │
  │       debate_node       risk_node      │               │
  │           │           ┌────┴────┐      │               │
  │           └──────────►│[拒绝]   │[通过]│               │
  │                       │    └────┘      │               │
  │                       │ portfolio_node─┘               │
  │                       ▼                                 │
  │               trade_executor → END                      │
  └─────────────────────────────────────────────────────────┘

特性:
  - 四路并行执行（fundamental/technical/sentiment/rag）
  - 辩论循环（最多 MAX_DEBATE_ROUNDS=2 轮）
  - 风控重试循环（最多 MAX_RISK_RETRIES=2 次）
  - 支持 LangGraph Checkpointer（可选，用于持久化中间状态）
"""
from __future__ import annotations

from typing import Optional

from langgraph.graph import END, START, StateGraph
from loguru import logger

from graph.nodes import (
    data_node,
    debate_node,
    fundamental_node,
    health_node,
    portfolio_node,
    rag_node,
    risk_node,
    route_after_portfolio,
    route_after_risk,
    sentiment_node,
    technical_node,
    trade_executor,
)
from graph.state import TradingGraphState


def build_graph(checkpointer=None):
    """
    装配并编译 LangGraph StateGraph。

    Args:
        checkpointer: 可选的 LangGraph Checkpointer 实例，
                      用于持久化中间状态（用于 .astream_events() 断点续传）
                      示例：MemorySaver() 或 SqliteSaver.from_conn_string(...)

    Returns:
        已编译的 CompiledStateGraph 实例，支持 .invoke() / .ainvoke() / .astream() / .astream_events()
    """
    logger.info("🔧 构建 LangGraph StateGraph...")

    # ── 创建状态图 ────────────────────────────────────────────
    graph = StateGraph(TradingGraphState)

    # ── 注册所有节点 ──────────────────────────────────────────
    graph.add_node("data_node",        data_node)
    graph.add_node("fundamental_node", fundamental_node)
    graph.add_node("technical_node",   technical_node)
    graph.add_node("sentiment_node",   sentiment_node)
    graph.add_node("rag_node",         rag_node)
    graph.add_node("portfolio_node",   portfolio_node)
    graph.add_node("debate_node",      debate_node)
    graph.add_node("risk_node",        risk_node)
    graph.add_node("trade_executor",   trade_executor)
    # 持仓体检独立节点（health_node），可通过独立图实例触发
    graph.add_node("health_node",      health_node)

    # ── 起点：START → data_node ───────────────────────────────
    graph.add_edge(START, "data_node")

    # ── 并行扇出：data_node → 四个分析节点（同时执行）────────
    # LangGraph 会在 data_node 完成后，并发调度以下四个节点
    graph.add_edge("data_node", "fundamental_node")
    graph.add_edge("data_node", "technical_node")
    graph.add_edge("data_node", "sentiment_node")
    graph.add_edge("data_node", "rag_node")

    # ── 并行汇聚：四个分析节点 → portfolio_node（等待全部完成）
    # LangGraph 会等待所有指向 portfolio_node 的边完成后才执行它
    graph.add_edge("fundamental_node", "portfolio_node")
    graph.add_edge("technical_node",   "portfolio_node")
    graph.add_edge("sentiment_node",   "portfolio_node")
    graph.add_edge("rag_node",         "portfolio_node")

    # ── 条件边 1：portfolio_node → debate_node 或 risk_node ──
    graph.add_conditional_edges(
        "portfolio_node",
        route_after_portfolio,
        {
            "debate_node": "debate_node",
            "risk_node":   "risk_node",
        },
    )

    # ── 辩论循环：debate_node → portfolio_node（重新决策）──
    graph.add_edge("debate_node", "portfolio_node")

    # ── 条件边 2：risk_node → portfolio_node 或 trade_executor
    graph.add_conditional_edges(
        "risk_node",
        route_after_risk,
        {
            "portfolio_node": "portfolio_node",
            "trade_executor": "trade_executor",
        },
    )

    # ── 终点：trade_executor → END ────────────────────────────
    graph.add_edge("trade_executor", END)

    # ── 编译 ──────────────────────────────────────────────────
    compile_kwargs = {}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer

    compiled = graph.compile(**compile_kwargs)

    logger.info("✅ StateGraph 编译完成")
    logger.info(f"   节点: {list(compiled.nodes.keys())}")
    return compiled


# ────────────────────────────────────────────────────────────────
# 工厂函数：带内存检查点的图（适合单次分析 + 流式传输场景）
# ────────────────────────────────────────────────────────────────

def build_graph_with_memory():
    """
    构建带 MemorySaver checkpointer 的图，支持 thread_id 会话追踪。

    用于 FastAPI SSE 场景，每个分析请求使用独立的 thread_id。
    """
    try:
        from langgraph.checkpoint.memory import MemorySaver
        checkpointer = MemorySaver()
        logger.info("✅ 使用 MemorySaver 检查点")
    except ImportError:
        logger.warning("MemorySaver 不可用，使用无持久化模式")
        checkpointer = None

    return build_graph(checkpointer=checkpointer)


# ────────────────────────────────────────────────────────────────
# 初始状态构造工具
# ────────────────────────────────────────────────────────────────

def make_initial_state(symbol: str) -> TradingGraphState:
    """
    构造 LangGraph 初始状态，所有可选字段填充默认值。

    Args:
        symbol: 交易标的代码

    Returns:
        完整的初始 TradingGraphState 字典
    """
    from utils.market_classifier import MarketClassifier
    market_type, _ = MarketClassifier.classify(symbol)

    return TradingGraphState(
        symbol=symbol,
        market_type=market_type.value,
        market_data={},
        rag_context="",
        fundamental_report=None,
        technical_report=None,
        sentiment_report=None,
        has_conflict=False,
        debate_outcome=None,
        debate_rounds=0,
        risk_decision=None,
        risk_rejection_count=0,
        trade_order=None,
        # Anti-Loop 工具调用计数器（TradingAgents-CN 模式）
        tool_call_counts={},
        # 持仓体检状态域
        portfolio_positions=None,
        health_report=None,
        messages=[],
        current_node="START",
        execution_log=[],
        status="running",
        error_message=None,
        error_type=None,
    )


# ────────────────────────────────────────────────────────────────
# 持仓体检专用图（独立分支，START → health_node → END）
# ────────────────────────────────────────────────────────────────

def build_health_graph(checkpointer=None):
    """
    构建持仓体检专用 StateGraph。
    拓扑: START → health_node → END
    可通过 FastAPI /api/v1/health-check 端点触发。
    """
    logger.info("🔧 构建持仓体检 StateGraph...")
    graph = StateGraph(TradingGraphState)
    graph.add_node("health_node", health_node)
    graph.add_edge(START, "health_node")
    graph.add_edge("health_node", END)

    compile_kwargs = {}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer

    compiled = graph.compile(**compile_kwargs)
    logger.info("✅ 持仓体检 StateGraph 编译完成")
    return compiled


def make_health_initial_state(
    positions: list,
) -> TradingGraphState:
    """
    构造持仓体检初始状态。

    Args:
        positions: PortfolioPosition.model_dump() 列表

    Returns:
        TradingGraphState 字典（仅 portfolio_positions 有效）
    """
    return TradingGraphState(
        symbol="PORTFOLIO",
        market_type="MIXED",
        market_data={},
        rag_context="",
        fundamental_report=None,
        technical_report=None,
        sentiment_report=None,
        has_conflict=False,
        debate_outcome=None,
        debate_rounds=0,
        risk_decision=None,
        risk_rejection_count=0,
        trade_order=None,
        tool_call_counts={},
        portfolio_positions=positions,
        health_report=None,
        messages=[],
        current_node="START",
        execution_log=[],
        status="running",
        error_message=None,
        error_type=None,
    )
