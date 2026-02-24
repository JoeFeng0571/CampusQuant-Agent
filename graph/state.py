"""
graph/state.py — LangGraph 全局状态定义

设计原则:
  1. TradingGraphState 是一个 TypedDict，所有节点共享同一个状态对象
  2. `messages` 字段使用 LangGraph 内置的 add_messages reducer，
     自动追加而非覆盖，完整记录节点间的消息流转历史
  3. `execution_log` 字段使用自定义 append_log reducer，支持并行节点安全追加
  4. 其余字段使用 "最后写入者胜" 策略（LangGraph 默认行为）
  5. Pydantic 模型作为 with_structured_output() 的 Schema，
     彻底取代原系统中的正则/JSON 手动解析
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, List, Literal, Optional
from typing_extensions import TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════════════
# 一、Pydantic 结构化输出模型
#    用于 llm.with_structured_output(Model) 调用
# ══════════════════════════════════════════════════════════════

class AnalystReport(BaseModel):
    """分析师结构化输出报告（Fundamental / Technical / Sentiment 共用）"""

    recommendation: Literal["BUY", "SELL", "HOLD"] = Field(
        description="交易建议: BUY/SELL/HOLD"
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="置信度，范围 [0.0, 1.0]"
    )
    reasoning: str = Field(
        description="详细的分析推理，不少于50字"
    )
    key_factors: List[str] = Field(
        default_factory=list,
        description="支撑该建议的3~5个关键因素"
    )
    price_target: Optional[float] = Field(
        default=None,
        description="目标价格（可选，None 表示不设定）"
    )
    risk_factors: List[str] = Field(
        default_factory=list,
        description="主要风险因素（1~3个）"
    )
    signal_strength: Literal["STRONG", "MODERATE", "WEAK"] = Field(
        default="MODERATE",
        description="信号强度"
    )


class RiskDecision(BaseModel):
    """风控官结构化决策输出"""

    approval_status: Literal["APPROVED", "CONDITIONAL", "REJECTED"] = Field(
        description="审批状态: APPROVED/CONDITIONAL/REJECTED"
    )
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "EXTREME"] = Field(
        description="综合风险等级"
    )
    position_pct: float = Field(
        ge=0.0, le=100.0,
        description="建议仓位占总资金的百分比"
    )
    stop_loss_pct: float = Field(
        ge=0.0, le=50.0,
        description="止损比例（相对入场价的百分比）"
    )
    take_profit_pct: float = Field(
        ge=0.0, le=200.0,
        description="止盈比例（相对入场价的百分比）"
    )
    rejection_reason: Optional[str] = Field(
        default=None,
        description="拒绝原因（REJECTED 时必填）"
    )
    conditions: List[str] = Field(
        default_factory=list,
        description="条件审批时的附加执行条件"
    )
    max_loss_amount: Optional[float] = Field(
        default=None,
        description="最大可承受亏损金额（USD）"
    )


class TradeOrder(BaseModel):
    """最终交易指令结构化输出"""

    symbol: str = Field(description="交易标的代码，如 AAPL / 600519.SH / 00700.HK")
    action: Literal["BUY", "SELL", "HOLD"] = Field(description="交易动作")
    quantity_pct: float = Field(
        ge=0.0, le=100.0,
        description="建议使用总资金的百分比"
    )
    order_type: Literal["MARKET", "LIMIT"] = Field(
        default="LIMIT",
        description="订单类型: 市价/限价"
    )
    limit_price: Optional[float] = Field(
        default=None,
        description="限价单价格（order_type=LIMIT 时有效）"
    )
    stop_loss: Optional[float] = Field(
        default=None,
        description="止损触发价格"
    )
    take_profit: Optional[float] = Field(
        default=None,
        description="止盈触发价格"
    )
    rationale: str = Field(description="核心决策依据摘要（不少于30字）")
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="综合置信度"
    )
    market_type: str = Field(description="市场类型: A_STOCK/HK_STOCK/US_STOCK")
    valid_until: Optional[str] = Field(
        default=None,
        description="指令有效期（ISO 8601 日期字符串）"
    )


class DebateOutcome(BaseModel):
    """多空辩论结构化输出（由 Debate 节点产出）"""

    resolved_recommendation: Literal["BUY", "SELL", "HOLD"] = Field(
        description="辩论后形成的共识建议"
    )
    confidence_after_debate: float = Field(
        ge=0.0, le=1.0,
        description="辩论后调整的置信度"
    )
    bull_core_argument: str = Field(
        description="多头方核心论点摘要"
    )
    bear_core_argument: str = Field(
        description="空头方核心论点摘要"
    )
    deciding_factor: str = Field(
        description="最终拍板的决定性因素"
    )
    debate_summary: str = Field(
        description="辩论全程摘要，不少于80字"
    )


# ══════════════════════════════════════════════════════════════
# 二、自定义 Reducer
# ══════════════════════════════════════════════════════════════

def _append_log(left: List[str], right: List[str]) -> List[str]:
    """
    执行日志追加 Reducer — 多个并行节点同时写入时安全合并
    """
    if left is None:
        left = []
    if right is None:
        right = []
    return left + right


# ══════════════════════════════════════════════════════════════
# 三、LangGraph 全局状态 TypedDict
# ══════════════════════════════════════════════════════════════

class TradingGraphState(TypedDict, total=False):
    """
    LangGraph 状态机全局状态

    并行执行说明:
      - fundamental_report / technical_report / sentiment_report / rag_context
        分别由四个并行节点写入不同字段，无写冲突
      - messages 使用 add_messages reducer，并行 AIMessage 均被追加
      - execution_log 使用 _append_log reducer，并行日志条目安全合并

    循环保护:
      - debate_rounds      : Debate 节点已执行次数，≥ MAX_DEBATE_ROUNDS 时跳过
      - risk_rejection_count: Risk 节点拒绝次数，≥ MAX_RISK_RETRIES 时强制放行/降级
    """

    # ── 基础标的信息 ─────────────────────────────────────────
    symbol: str
    market_type: str          # "A_STOCK" | "HK_STOCK" | "US_STOCK"（已移除 CRYPTO）

    # ── 原始市场数据（由 data_node 填充）─────────────────────
    market_data: Dict[str, Any]

    # ── RAG 检索到的外部知识（由 rag_node 并行填充）──────────
    rag_context: str           # 宏观政策 / 财报片段的检索结果

    # ── 三大分析师独立研判报告（并行填充，各写不同字段）──────
    fundamental_report: Optional[Dict[str, Any]]
    technical_report:   Optional[Dict[str, Any]]
    sentiment_report:   Optional[Dict[str, Any]]

    # ── 辩论与冲突消解 ──────────────────────────────────────
    has_conflict: bool                      # 基本面 vs 技术面意见截然相反
    debate_outcome: Optional[Dict[str, Any]]  # DebateOutcome.model_dump()
    debate_rounds: int                      # 已辩论轮次（循环保护上限: 2）

    # ── 风控状态 ────────────────────────────────────────────
    risk_decision: Optional[Dict[str, Any]]   # RiskDecision.model_dump()
    risk_rejection_count: int               # 风控拒绝次数（循环保护上限: 2）

    # ── 最终交易指令 ─────────────────────────────────────────
    trade_order: Optional[Dict[str, Any]]     # TradeOrder.model_dump()

    # ── 消息流转历史（LangGraph add_messages reducer）────────
    messages: Annotated[List[BaseMessage], add_messages]

    # ── 执行追踪 ─────────────────────────────────────────────
    current_node: str
    execution_log: Annotated[List[str], _append_log]
    status: str               # "running" | "completed" | "error"
    error_message: Optional[str]


# ── 全局常量 ────────────────────────────────────────────────
MAX_DEBATE_ROUNDS = 2    # 最多辩论2轮
MAX_RISK_RETRIES  = 2    # 风控拒绝后最多重试2次
