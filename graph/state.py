"""
graph/state.py — LangGraph 全局状态定义

设计原则（对标 TradingAgents-CN-main 架构精华）:
  1. TradingGraphState 是 TypedDict，所有节点共享同一个状态对象
  2. `messages` 字段使用 LangGraph 内置 add_messages reducer，
     自动追加而非覆盖，完整记录节点间消息流转
  3. `execution_log` 字段使用自定义 _append_log reducer，并行安全追加
  4. `tool_call_counts` 字段使用 _merge_counts reducer，并行节点各自写入
     自己的 key，reducer 以 dict.update 语义合并，修复原有 last-write-wins 丢失问题
  5. 其余字段使用"最后写入者胜"策略（LangGraph 默认行为）
  6. Pydantic 模型作为 with_structured_output() 的 Schema，
     彻底取代原系统中的正则/JSON 手动解析

架构借鉴（TradingAgents-CN-main）:
  A. 工具调用计数器（Anti-Loop 防死循环）
     参考: agents/utils/agent_states.py / market_tool_call_count
     将各节点的工具调用次数以 Dict 形式集中存储于 tool_call_counts，
     节点内每次工具调用前先检查，超过 MAX_TOOL_CALLS 强制终止。
     【修复】原 tool_call_counts 无 Reducer，并行节点写入时最后写入者胜，
     导致其他节点计数丢失。现改用 _merge_counts Reducer（dict.update 语义），
     保证并行安全。
  B. 分角色独立辩论状态（InvestDebateState / RiskDebateState 模式）
     参考: agents/utils/agent_states.py
     DebateOutcome 新增 bull_argument_summary / bear_argument_summary 论点摘要，
     让辩论可溯源、可审计。（原名 bull_history/bear_history 已重命名，消除
     "可追溯对话历史"的误导——实为 LLM 生成的论点摘要，非真实多轮日志）
  C. 持仓体检状态域（Portfolio Health Check）
     新增 PortfolioPosition 与 PortfolioHealthReport Pydantic 模型，
     以及对应的 portfolio_positions / health_report 字段，
     支撑"持仓体检"业务流。
  D. 错误分类
     error_type 字段支持细粒度错误归因（数据/LLM/限速/超时），
     便于前端 SSE 展示具体错误提示。
  E. 真实数据字段（新增）
     fundamental_data: 真实基本面数据（PE/PB/ROE/EPS，由 get_fundamental_data 工具填充）
     news_data:        最新新闻资讯 JSON 字符串（由 get_stock_news 工具填充）
     data_fetch_failed: 数据获取失败标志，供并行节点早退判断
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, List, Literal, Optional
from typing_extensions import TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field, model_validator


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
        description="详细的分析推理，不少于400字，需包含具体数据（PE/PB/ROE等）和完整逻辑推导链"
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

    # ── 研报增强字段（v2.0）──────────────────────────────────────
    # 主要由 fundamental_node 填充；technical/sentiment 节点保持默认空值
    investment_thesis: str = Field(
        default="",
        description="2-3 句投资论点摘要，需概括核心买入/持有/卖出理由"
    )
    business_model: str = Field(
        default="",
        description="商业模式 & 收入驱动分析，不少于100字，需覆盖主营业务、收入结构、毛利率和增长引擎"
    )
    moat_assessment: str = Field(
        default="",
        description="护城河 / 竞争优势评估，不少于100字，需分析品牌、技术、规模效应、行业地位"
    )
    catalysts: List[str] = Field(
        default_factory=list,
        description="未来 1-2 季度的 3 个以上潜在催化剂，每个需说明预期影响"
    )
    peer_comparison: str = Field(
        default="",
        description="同行估值对比，不少于100字，需列出2-3家同行公司及PE/PB/增速对比，明确估值水平判断"
    )
    bull_case: str = Field(
        default="",
        description="乐观情景描述，需包含目标估值倍数和对应股价估算"
    )
    bear_case: str = Field(
        default="",
        description="悲观情景描述，需量化下跌空间和具体触发条件"
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
        ge=0.0, le=20.0,  # 【审计修复 P1-1】上限 20%，避免大学生超额集中仓位
        description="建议仓位占总资金的百分比（上限20%）"
    )
    stop_loss_pct: float = Field(
        ge=0.0, le=50.0,  # 允许 0（HOLD 场景），上限 50%
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
        description="最大可承受亏损金额（人民币/USD）"
    )


class TradeOrder(BaseModel):
    """最终交易指令结构化输出（指向本地模拟撮合引擎，非真实交易所）"""

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
    # 模拟撮合引擎专属字段 — 绝不指向真实交易所 API
    simulated: bool = Field(
        default=True,
        description="是否为模拟交易（始终为 True，本系统不接入真实交易所）"
    )

    # 【安全校验】强制 simulated=True，即使 LLM 输出 false 也会被覆盖
    @model_validator(mode="after")
    def force_simulated_true(self) -> "TradeOrder":
        self.simulated = True
        return self

    # 【审计修复 P1-2】跨字段校验：LIMIT 订单若无 limit_price 则降级为 MARKET
    @model_validator(mode="after")
    def ensure_limit_price(self) -> "TradeOrder":
        if self.order_type == "LIMIT" and self.limit_price is None:
            self.order_type = "MARKET"
        return self


class DebateOutcome(BaseModel):
    """
    多空辩论结构化输出（由 Debate 节点产出）

    架构借鉴 TradingAgents-CN-main InvestDebateState:
      【审计修复 P2-2】原 bull_history / bear_history 重命名为
      bull_argument_summary / bear_argument_summary，消除"可追溯对话历史"的
      误导——这是 LLM 生成的论点摘要，非真实多轮对话日志。
    """

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
    # 【审计修复 P2-2】重命名：论点摘要，非"完整对话历史"
    bull_argument_summary: str = Field(
        default="",
        description="多头方论点展开记录（LLM 生成的论点摘要，非真实对话日志）"
    )
    bear_argument_summary: str = Field(
        default="",
        description="空头方论点展开记录（LLM 生成的论点摘要，非真实对话日志）"
    )
    deciding_factor: str = Field(
        description="最终拍板的决定性因素"
    )
    debate_summary: str = Field(
        description="辩论全程摘要，不少于80字"
    )


# ── 持仓体检专属 Pydantic 模型（新增，支撑"持仓体检"业务流）────
class PortfolioPosition(BaseModel):
    """单条持仓记录"""

    symbol: str        = Field(description="标的代码")
    market_type: str   = Field(description="市场类型: A_STOCK/HK_STOCK/US_STOCK")
    quantity: float    = Field(ge=0.0, description="持仓数量（股/份）")
    avg_cost: float    = Field(ge=0.0, description="平均持仓成本价")
    current_price: Optional[float] = Field(default=None, description="当前市价（health_node 填充）")
    weight_pct: Optional[float]    = Field(default=None, ge=0.0, le=100.0,
                                           description="占总持仓市值的百分比（health_node 计算后填充）")


class PortfolioHealthReport(BaseModel):
    """
    持仓体检输出报告（由 health_node 产出）

    诊断维度:
      - 集中度风险: 单标的权重是否超过大学生风控上限
      - 回撤风险: 各持仓浮亏情况与最大回撤估算
      - 流动性: 持仓市场流动性评估
      - 综合健康评分
    """

    health_score: float = Field(
        ge=0.0, le=100.0,
        description="综合持仓健康评分 [0, 100]，越高越健康"
    )
    concentration_risk: Literal["LOW", "MEDIUM", "HIGH", "EXTREME"] = Field(
        description="集中度风险等级"
    )
    max_drawdown_est: float = Field(
        ge=0.0, le=100.0,
        description="最大回撤估算（百分比）"
    )
    # 【审计修复 P2-3】统一量纲为 0-100，与 health_score 一致
    liquidity_score: float = Field(
        ge=0.0, le=100.0,
        description="流动性评分 [0, 100]，越高流动性越好"
    )
    overweight_positions: List[str] = Field(
        default_factory=list,
        description="超权重持仓列表（需要减仓的标的）"
    )
    high_risk_positions: List[str] = Field(
        default_factory=list,
        description="高风险持仓列表（ATR% > 5% 或浮亏超15%）"
    )
    recommendations: List[str] = Field(
        default_factory=list,
        description="持仓优化建议（3~5条）"
    )
    overall_diagnosis: str = Field(
        description="综合诊断摘要（不少于60字）"
    )


# ══════════════════════════════════════════════════════════════
# 二、自定义 Reducer
# ══════════════════════════════════════════════════════════════

def _append_log(left: List[str], right: List[str]) -> List[str]:
    """
    执行日志追加 Reducer — 多个并行节点同时写入时安全合并

    TradingAgents-CN 参考: 并行节点各自持有独立的 execution_log list，
    通过此 reducer 在 StateGraph 内部无锁合并，无需显式加锁。
    """
    if left is None:
        left = []
    if right is None:
        right = []
    return left + right


def _merge_counts(left: Dict[str, int], right: Dict[str, int]) -> Dict[str, int]:
    """
    工具调用计数器合并 Reducer — dict.update 语义，并行安全。

    【审计修复 P0-1】原 tool_call_counts 无 Reducer，4 个并行节点（fundamental /
    technical / sentiment / rag）各自返回完整的 counts 字典，LangGraph 以
    "最后写入者胜"合并，导致 3 个节点的计数静默丢失，Anti-Loop 机制完全失效。

    修复方案：dict.update 语义（后者覆盖/补充前者），保证：
      - 并行节点各写自己的 key，reducer 将所有 key 合并
      - 串行节点复写自己的 key，覆盖旧值（计数累加在节点内部完成）
    """
    merged = dict(left or {})
    merged.update(right or {})
    return merged


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
      - tool_call_counts 使用 _merge_counts reducer（dict.update 语义），
        修复了原有 last-write-wins 导致并行计数丢失的问题

    循环保护:
      - debate_rounds       : Debate 节点已执行次数，≥ MAX_DEBATE_ROUNDS 时跳过
      - risk_rejection_count: Risk 节点拒绝次数，≥ MAX_RISK_RETRIES 时强制放行/降级

    工具调用防死循环（TradingAgents-CN Anti-Loop 模式）:
      - tool_call_counts: Dict[node_name → call_count]，每个节点独立计数
        超过 MAX_TOOL_CALLS 后，节点直接降级输出，不再调用工具

    数据层新增字段:
      - fundamental_data  : 真实基本面数据（PE/PB/ROE，由 fundamental_node 填充）
      - news_data         : 最新新闻资讯 JSON（由 sentiment_node 填充）
      - data_fetch_failed : True 时各并行节点早退，不调用 LLM
    """

    # ── 基础标的信息 ─────────────────────────────────────────
    symbol: str
    market_type: str          # "A_STOCK" | "HK_STOCK" | "US_STOCK"

    # ── 原始市场数据（由 data_node 填充）─────────────────────
    market_data: Dict[str, Any]

    # ── 数据获取失败标志（data_node 失败时设为 True，并行节点据此早退）
    data_fetch_failed: bool

    # ── 真实基本面数据（由 fundamental_node 调用 get_fundamental_data 填充）
    fundamental_data: Optional[Dict[str, Any]]   # PE/PB/ROE/EPS/市值/行业等

    # ── 最新新闻资讯（由 sentiment_node 调用 get_stock_news 填充）
    news_data: Optional[str]   # JSON 字符串，含新闻标题列表

    # ── RAG 检索到的外部知识（由 rag_node 并行填充）──────────
    rag_context: str           # 宏观政策 / 财报片段的检索结果

    # ── 三大分析师独立研判报告（并行填充，各写不同字段）──────
    fundamental_report: Optional[Dict[str, Any]]
    technical_report:   Optional[Dict[str, Any]]
    sentiment_report:   Optional[Dict[str, Any]]

    # ── 辩论与冲突消解 ──────────────────────────────────────
    has_conflict: bool                        # 基本面 vs 技术面意见截然相反
    debate_outcome: Optional[Dict[str, Any]]  # DebateOutcome.model_dump()
    debate_rounds: int                        # 已辩论轮次（循环保护上限: MAX_DEBATE_ROUNDS）

    # ── 风控状态 ────────────────────────────────────────────
    risk_decision: Optional[Dict[str, Any]]   # RiskDecision.model_dump()
    risk_rejection_count: int                 # 风控拒绝次数（循环保护上限: MAX_RISK_RETRIES）

    # ── 最终交易指令（指向本地模拟撮合引擎）─────────────────
    trade_order: Optional[Dict[str, Any]]     # TradeOrder.model_dump()

    # ── 工具调用计数器（Anti-Loop，TradingAgents-CN 模式）────
    # 【审计修复 P0-1】改用 _merge_counts Reducer，修复并行写入丢失
    tool_call_counts: Annotated[Dict[str, int], _merge_counts]

    # ── 持仓体检状态域（持仓体检业务流专用）────────────────
    portfolio_positions: Optional[List[Dict[str, Any]]]  # PortfolioPosition.model_dump() 列表
    health_report: Optional[Dict[str, Any]]              # PortfolioHealthReport.model_dump()

    # ── 消息流转历史（LangGraph add_messages reducer）────────
    messages: Annotated[List[BaseMessage], add_messages]

    # ── 执行追踪 ─────────────────────────────────────────────
    current_node: str
    execution_log: Annotated[List[str], _append_log]
    status: str               # "running" | "completed" | "error"
    error_message: Optional[str]
    # ── 错误分类（细粒度归因，便于前端 SSE 展示具体提示）──────
    error_type: Optional[str] # "data_error"|"llm_error"|"rate_limit"|"timeout"|None


# ── 全局常量 ────────────────────────────────────────────────
MAX_DEBATE_ROUNDS = 2    # 最多辩论2轮
MAX_RISK_RETRIES  = 2    # 风控拒绝后最多重试2次

# ── 工具调用防死循环上限（借鉴 TradingAgents-CN anti-loop 机制）──
MAX_TOOL_CALLS    = 3    # 单节点最多调用工具3次，超出强制降级
