"""
bench/schema.py — CQ-Bench data models

所有 case / output / score 都是 pydantic BaseModel,方便序列化和验证。
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ════════════════════════════════════════════════════════════════
# INPUT · Case 定义
# ════════════════════════════════════════════════════════════════

Direction = Literal["BUY", "HOLD", "SELL"]
Market = Literal["A_STOCK", "HK_STOCK", "US_STOCK"]


class BenchCase(BaseModel):
    """一条评测 case"""

    id: str = Field(description="Case ID, 如 BENCH-001")
    symbol: str = Field(description="股票代码, 如 600519.SH / 00700.HK / AAPL")
    market: Market
    name: str = Field(description="公司简称, 便于 LLM 理解")

    # Ground truth —— 人工标注的"合理建议"
    expected_direction: Direction = Field(
        description="该情境下的预期方向 (BUY/HOLD/SELL)"
    )
    key_points: list[str] = Field(
        description="AI 输出应该覆盖的关键论点 (人工列出)",
        min_length=1,
    )
    risk_points: list[str] = Field(
        default_factory=list,
        description="AI 输出应该提及的风险点",
    )
    analyst_notes: str = Field(
        description="人工 50-100 字概述, 说明为什么这个方向合理"
    )

    # 可选的 context 提示, runner 可以用
    extra_context: Optional[str] = Field(
        default=None,
        description="额外 context 提示 (如: 刚发布财报/产品重大变更)",
    )


# ════════════════════════════════════════════════════════════════
# OUTPUT · Runner 的输出
# ════════════════════════════════════════════════════════════════


class BenchOutput(BaseModel):
    """Runner 跑完一个 case 的输出"""

    case_id: str
    runner_name: str  # "campusquant" / "gpt4_baseline" / etc.

    # 核心字段 —— 从 graph 的 trade_order 提取
    direction: Direction
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(description="Agent 给出的决策理由")

    # 分析师报告摘要 (用于 grounding 评估)
    fundamental_summary: Optional[str] = None
    technical_summary: Optional[str] = None
    sentiment_summary: Optional[str] = None
    rag_context_preview: Optional[str] = Field(
        default=None,
        description="RAG 召回的前 500 字, 用于判断是否 grounded",
    )

    # 运行元数据
    latency_seconds: float = Field(description="端到端耗时")
    error: Optional[str] = Field(default=None, description="错误信息 (如有)")
    raw_state_path: Optional[str] = Field(
        default=None,
        description="原始 state dump 的文件路径, 便于 debug",
    )

    @property
    def failed(self) -> bool:
        return self.error is not None


# ════════════════════════════════════════════════════════════════
# JUDGE · 评分结果
# ════════════════════════════════════════════════════════════════


class BenchScore(BaseModel):
    """LLM judge 对一条 output 的评分"""

    case_id: str
    runner_name: str
    judge_name: str  # "gpt-4o" / "qwen-plus" / "claude-3.5"

    # 二元指标
    direction_match: bool = Field(description="方向是否与 expected 完全一致")

    # 5 级评分 (1-5)
    grounding_score: int = Field(
        ge=1, le=5,
        description="是否引用具体数字/数据 (1=空泛, 5=高度具体)",
    )
    coverage_score: int = Field(
        ge=1, le=5,
        description="是否覆盖 key_points (1=未覆盖, 5=全部覆盖)",
    )
    reasoning_score: int = Field(
        ge=1, le=5,
        description="论据逻辑合理性 (1=错误, 5=严谨)",
    )
    risk_awareness_score: int = Field(
        ge=1, le=5,
        description="是否提及 risk_points (1=未提及, 5=全部提及)",
    )

    # Judge 的解释
    judge_comment: str = Field(description="judge 的总体评语")
    failure_modes: list[str] = Field(
        default_factory=list,
        description="AI 输出的具体问题 tag, 如 ['空泛', '数字编造']",
    )

    @property
    def overall_score(self) -> float:
        """4 个维度的简单平均, 方向不匹配给 0.5x 惩罚"""
        avg = (
            self.grounding_score
            + self.coverage_score
            + self.reasoning_score
            + self.risk_awareness_score
        ) / 4.0
        if not self.direction_match:
            avg *= 0.5
        return round(avg, 2)


# ════════════════════════════════════════════════════════════════
# RUN · 单次 benchmark 运行的结果
# ════════════════════════════════════════════════════════════════


class BenchRun(BaseModel):
    """一次完整 benchmark 跑的结果"""

    run_id: str = Field(description="时间戳 ID, 如 20260410_1830")
    runner_name: str
    judge_name: str
    started_at: datetime
    finished_at: Optional[datetime] = None

    case_count: int
    cases: list[BenchCase]
    outputs: list[BenchOutput]
    scores: list[BenchScore]

    # 聚合指标 (finalize 时填充)
    direction_accuracy: Optional[float] = None
    avg_grounding: Optional[float] = None
    avg_coverage: Optional[float] = None
    avg_reasoning: Optional[float] = None
    avg_risk: Optional[float] = None
    avg_overall: Optional[float] = None
    fail_rate: Optional[float] = None  # runner 崩溃 / judge 评不了 的比例
    total_latency_seconds: Optional[float] = None

    def finalize(self) -> None:
        """聚合指标计算"""
        self.finished_at = datetime.now()
        n = len(self.scores)
        if n == 0:
            return
        self.direction_accuracy = sum(1 for s in self.scores if s.direction_match) / n
        self.avg_grounding = sum(s.grounding_score for s in self.scores) / n
        self.avg_coverage = sum(s.coverage_score for s in self.scores) / n
        self.avg_reasoning = sum(s.reasoning_score for s in self.scores) / n
        self.avg_risk = sum(s.risk_awareness_score for s in self.scores) / n
        self.avg_overall = sum(s.overall_score for s in self.scores) / n
        self.fail_rate = sum(1 for o in self.outputs if o.failed) / self.case_count
        self.total_latency_seconds = sum(o.latency_seconds for o in self.outputs)
