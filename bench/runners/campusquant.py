"""
bench/runners/campusquant.py — 跑我们自己 LangGraph 系统的 runner

直接调 graph.builder.build_graph,注入 case.symbol 作为 initial state,
等整个 graph 跑完(data → fundamental/technical/sentiment/rag 并行 →
portfolio → (debate?) → risk → trade_executor)抽取 trade_order 作为
最终决策。
"""
from __future__ import annotations

import asyncio
import json
import time
import traceback
from pathlib import Path
from typing import Any

from loguru import logger

from bench.runners.base import Runner
from bench.schema import BenchCase, BenchOutput


# 【重要】我们的 graph 需要符号 + 市场 + 初始 state
# build_graph 返回 compiled graph, make_initial_state 构造初始 state


class CampusQuantRunner(Runner):
    """跑本地 LangGraph 多智能体分析"""

    name = "campusquant"

    def __init__(self, raw_state_dir: Path | None = None):
        self.graph = None
        self.raw_state_dir = raw_state_dir
        if raw_state_dir:
            raw_state_dir.mkdir(parents=True, exist_ok=True)

    async def setup(self) -> None:
        from graph.builder import build_graph

        logger.info("[CampusQuantRunner] 构建 StateGraph...")
        self.graph = build_graph()
        logger.info("[CampusQuantRunner] ✅ 就绪")

    async def run_case(self, case: BenchCase) -> BenchOutput:
        from graph.builder import make_initial_state

        t0 = time.perf_counter()
        state = make_initial_state(case.symbol)

        try:
            # ainvoke 走完整图
            final_state: dict[str, Any] = await self.graph.ainvoke(state)
            latency = time.perf_counter() - t0

            # 从 trade_order 提取核心决策
            trade_order = final_state.get("trade_order")
            if trade_order is None:
                return BenchOutput(
                    case_id=case.id,
                    runner_name=self.name,
                    direction="HOLD",
                    confidence=0.0,
                    rationale="",
                    latency_seconds=latency,
                    error="trade_order is None (graph may have failed before trade_executor)",
                )

            # Pydantic BaseModel → dict
            to_dict = trade_order.model_dump() if hasattr(trade_order, "model_dump") else dict(trade_order)

            # 分析师 summary (用于 grounding)
            fund_report = final_state.get("fundamental_report")
            tech_report = final_state.get("technical_report")
            sent_report = final_state.get("sentiment_report")
            rag_ctx = final_state.get("rag_context", "")

            fund_sum = _safe_summary(fund_report)
            tech_sum = _safe_summary(tech_report)
            sent_sum = _safe_summary(sent_report)

            raw_path = None
            if self.raw_state_dir:
                raw_path = self.raw_state_dir / f"{case.id}.json"
                _dump_state(final_state, raw_path)

            return BenchOutput(
                case_id=case.id,
                runner_name=self.name,
                direction=to_dict.get("action", "HOLD"),
                confidence=float(to_dict.get("confidence", 0.0)),
                rationale=str(to_dict.get("rationale", "")),
                fundamental_summary=fund_sum,
                technical_summary=tech_sum,
                sentiment_summary=sent_sum,
                rag_context_preview=rag_ctx[:500] if rag_ctx else None,
                latency_seconds=latency,
                raw_state_path=str(raw_path) if raw_path else None,
            )

        except Exception as e:
            latency = time.perf_counter() - t0
            logger.error(f"[CampusQuantRunner] {case.id} 崩溃: {e}")
            logger.error(traceback.format_exc())
            return BenchOutput(
                case_id=case.id,
                runner_name=self.name,
                direction="HOLD",
                confidence=0.0,
                rationale="",
                latency_seconds=latency,
                error=f"{type(e).__name__}: {e}",
            )


def _safe_summary(report: Any) -> str | None:
    """从 AnalystReport 抽出摘要文本,兼容 pydantic / dict / None"""
    if report is None:
        return None
    if hasattr(report, "model_dump"):
        d = report.model_dump()
    elif isinstance(report, dict):
        d = report
    else:
        return str(report)[:500]

    # 优先使用 executive_summary,其次 raw_content
    summary = d.get("executive_summary") or d.get("summary") or d.get("raw_content", "")
    return str(summary)[:500] if summary else None


def _dump_state(state: dict, path: Path) -> None:
    """把 graph 最终 state 序列化到 json (best-effort)"""
    try:
        serializable = _to_serializable(state)
        path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"state dump 失败: {e}")


def _to_serializable(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, list):
        return [_to_serializable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_serializable(v) for k, v in obj.items() if not k.startswith("_")}
    if hasattr(obj, "model_dump"):
        return _to_serializable(obj.model_dump())
    # LangChain Message 对象
    if hasattr(obj, "content"):
        return {
            "type": type(obj).__name__,
            "content": str(obj.content)[:500],
            "name": getattr(obj, "name", None),
        }
    return str(obj)[:500]
