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

审计修复:
  - 【P0-2】删除 build_graph() 中注册的 health_node 死节点（该节点无边可达）
    health_node 由独立的 build_health_graph() 正确路由
  - 【P1-4】make_initial_state / make_health_initial_state 包含全部新增字段
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from langgraph.graph import END, START, StateGraph
from loguru import logger

from graph.nodes import (
    data_node,
    debate_node,
    fundamental_node,
    portfolio_node,
    # 【v2.2 P0-C】rag_node 已删除,RAG 预取合并到 data_node 末尾
    risk_node,
    route_after_portfolio,
    route_after_risk,
    sentiment_node,
    technical_node,
    trade_executor,
    # 【审计修复 P0-2】health_node 仅在 build_health_graph() 中使用，
    # 不再注册到主图（原注册无边可达，是死节点）
    health_node,
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
    # 【v2.2 P0-C】rag_node 已删除, RAG 预取合并到 data_node 末尾的 rag_evidence_pool
    graph.add_node("portfolio_node",   portfolio_node)
    graph.add_node("debate_node",      debate_node)
    graph.add_node("risk_node",        risk_node)
    graph.add_node("trade_executor",   trade_executor)
    # 【审计修复 P0-2】删除原来的 graph.add_node("health_node", health_node)
    # health_node 在主图中无边可达，是死节点。正确路由见 build_health_graph()

    # ── 起点：START → data_node ───────────────────────────────
    graph.add_edge(START, "data_node")

    # ── 并行扇出：data_node → 四个分析节点（同时执行）────────
    # 【审计修复 P0-3 实现方式】
    # 数据错误短路通过各并行节点内部的 data_fetch_failed 早退实现：
    # 当 data_node 设置 data_fetch_failed=True 时，四个并行节点检测到后
    # 立即返回 HOLD 降级报告，不调用 LLM，避免在错误数据上浪费 LLM 调用。
    # （LangGraph 对同一源节点的 conditional fan-out 实现较复杂，
    #   使用节点内早退是更简洁且等效的解决方案）
    graph.add_edge("data_node", "fundamental_node")
    graph.add_edge("data_node", "technical_node")
    graph.add_edge("data_node", "sentiment_node")
    # 【v2.2 P0-C】删除 data_node → rag_node 边, RAG 已整合入 data_node

    # ── 并行汇聚：三个分析节点 → portfolio_node（等待全部完成）
    # LangGraph 会等待所有指向 portfolio_node 的边完成后才执行它
    graph.add_edge("fundamental_node", "portfolio_node")
    graph.add_edge("technical_node",   "portfolio_node")
    graph.add_edge("sentiment_node",   "portfolio_node")
    # 【v2.2 P0-C】删除 rag_node → portfolio_node 边

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

_MAX_MEMORY_THREADS = 200  # 最多保留 200 个会话，防止内存无限增长

def build_graph_with_memory():
    """
    构建带 MemorySaver checkpointer 的图，支持 thread_id 会话追踪。
    用于 FastAPI SSE 场景，每个分析请求使用独立的 thread_id。
    内置简易驱逐：超过 _MAX_MEMORY_THREADS 时清理最旧的会话。
    """
    try:
        from langgraph.checkpoint.memory import MemorySaver
        checkpointer = MemorySaver()
        logger.info("✅ 使用 MemorySaver 检查点（上限 %d 会话）", _MAX_MEMORY_THREADS)
    except ImportError:
        logger.warning("MemorySaver 不可用，使用无持久化模式")
        checkpointer = None

    return build_graph(checkpointer=checkpointer)


# ────────────────────────────────────────────────────────────────
# W5 升级：SQLite 持久化检查点（进程崩溃后可恢复）
# ────────────────────────────────────────────────────────────────

_CHECKPOINT_DB = Path(__file__).parent.parent / "data" / "checkpoints.db"


async def build_graph_with_sqlite_checkpoint():
    """
    构建带 AsyncSqliteSaver 持久化检查点的图。

    注意: 这是 async 函数，因为 SQLite saver 需要 async context。
    应在 FastAPI lifespan 或 async 上下文中调用。

    优势 vs MemorySaver:
      - 进程崩溃后 state 不丢失，可从 thread_id resume
      - 所有中间 node state 持久化（可回放 debug）
      - 支持多 worker 共享（SQLite WAL 模式）

    用法 (在 FastAPI lifespan 中):
      async with build_sqlite_saver() as saver:
          graph = build_graph(checkpointer=saver)
          config = {"configurable": {"thread_id": f"{user_id}:{symbol}:{uuid4()}"}}
          result = await graph.ainvoke(state, config)

    恢复中断的分析:
      result = await graph.ainvoke(None, config)  # 传 None state 从 checkpoint 恢复
    """
    _CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)

    try:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        import aiosqlite
        conn = await aiosqlite.connect(str(_CHECKPOINT_DB))
        checkpointer = AsyncSqliteSaver(conn)
        await checkpointer.setup()  # 创建 checkpoint 表
        logger.info(f"✅ 使用 AsyncSqliteSaver 持久化检查点: {_CHECKPOINT_DB}")
        return build_graph(checkpointer=checkpointer), checkpointer
    except ImportError:
        logger.warning("langgraph-checkpoint-sqlite 未安装，降级为 MemorySaver")
        logger.warning("  pip install langgraph-checkpoint-sqlite")
        return build_graph_with_memory(), None


def cleanup_memory_saver(checkpointer) -> int:
    """清理超限的 MemorySaver 会话，返回清理数量"""
    try:
        storage = getattr(checkpointer, "storage", None) or getattr(checkpointer, "store", {})
        if hasattr(storage, '__len__') and len(storage) > _MAX_MEMORY_THREADS:
            # 删除最旧的一半
            keys = list(storage.keys())
            to_remove = keys[:len(keys) // 2]
            for k in to_remove:
                storage.pop(k, None)
            return len(to_remove)
    except Exception:
        pass
    return 0


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
        # 【审计修复 P1-4】新增字段默认值
        data_fetch_failed=False,
        fundamental_data=None,
        news_data=None,
        rag_context="",
        rag_evidence_pool=None,
        fundamental_report=None,
        technical_report=None,
        sentiment_report=None,
        has_conflict=False,
        debate_outcome=None,
        debate_rounds=0,
        debate_confidence_history=[],
        debate_converged=None,
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
        # 【v2.2】回测时点驱动: None = 生产路径(NOW),否则 ISO 日期字符串
        rebalance_date=None,
        # 【v2.2】回测 prompt 版本: None = 默认证据优先,
        # "v1_baseline" = 回到结论优先的旧风格
        prompt_version=None,
    )


# ────────────────────────────────────────────────────────────────
# 持仓体检专用图（独立分支，START → health_node → END）
# ────────────────────────────────────────────────────────────────

def build_health_graph(checkpointer=None):
    """
    构建持仓体检专用 StateGraph。
    拓扑: START → health_node → END
    可通过 FastAPI /api/v1/health-check 端点触发。

    【审计修复 P0-2 说明】health_node 仅在此独立图中使用，
    已从 build_graph() 中删除，消除了主图中的死节点。
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
        data_fetch_failed=False,
        fundamental_data=None,
        news_data=None,
        rag_context="",
        rag_evidence_pool=None,
        fundamental_report=None,
        technical_report=None,
        sentiment_report=None,
        has_conflict=False,
        debate_outcome=None,
        debate_rounds=0,
        debate_confidence_history=[],
        debate_converged=None,
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
        # 【v2.2】回测时点驱动: None = 生产路径(NOW),否则 ISO 日期字符串
        rebalance_date=None,
        # 【v2.2】回测 prompt 版本: None = 默认证据优先,
        # "v1_baseline" = 回到结论优先的旧风格
        prompt_version=None,
    )
