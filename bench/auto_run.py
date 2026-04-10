#!/usr/bin/env python3
"""
bench/auto_run.py — 一键跑完 CQ-Bench + 生成报告 + 与历史对比

用法:
    python -m bench.auto_run                    # 跑全部 case + judge + 报告
    python -m bench.auto_run --n 3              # 只跑 3 个 case (快速验证)
    python -m bench.auto_run --no-judge         # 不用 LLM 评分 (省钱)
    python -m bench.auto_run --compare          # 只做历史对比,不跑新 case
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RESULTS_DIR = ROOT / "bench" / "results"


def find_latest_runs(top_n: int = 5) -> list[Path]:
    """找到最近 N 次 run 目录"""
    if not RESULTS_DIR.exists():
        return []
    runs = sorted(
        [d for d in RESULTS_DIR.iterdir() if d.is_dir() and (d / "run.json").exists()],
        key=lambda d: d.name,
        reverse=True,
    )
    return runs[:top_n]


def load_run_summary(run_dir: Path) -> dict:
    """加载一次 run 的摘要（兼容实际 run.json 格式）"""
    run_file = run_dir / "run.json"
    if not run_file.exists():
        return {}
    with run_file.open("r", encoding="utf-8") as f:
        data = json.load(f)

    cases = data.get("cases", [])
    outputs = data.get("outputs", [])
    scores = data.get("scores", [])
    total = data.get("case_count", len(cases))

    if total == 0:
        return {"run_id": run_dir.name, "cases": 0}

    # Build case_id → expected_direction lookup
    expected = {c.get("id", ""): c.get("expected_direction", "HOLD") for c in cases}

    # Direction accuracy
    correct = 0
    hold_count = 0
    for o in outputs:
        d = (o.get("direction") or "HOLD").upper()
        if d == "HOLD":
            hold_count += 1
        case_id = o.get("case_id", "")
        if d == expected.get(case_id, "").upper():
            correct += 1

    # Average judge scores (from scores list)
    avg_grounding = avg_coverage = avg_reasoning = avg_risk = 0
    n_judged = 0
    for s in scores:
        g = s.get("grounding_score", 0)
        c = s.get("coverage_score", 0)
        r = s.get("reasoning_score", 0)
        k = s.get("risk_awareness_score", 0)
        if g or c or r or k:
            avg_grounding += g
            avg_coverage += c
            avg_reasoning += r
            avg_risk += k
            n_judged += 1

    if n_judged > 0:
        avg_grounding /= n_judged
        avg_coverage /= n_judged
        avg_reasoning /= n_judged
        avg_risk /= n_judged

    n_out = len(outputs) or total
    return {
        "run_id": run_dir.name,
        "cases": total,
        "direction_accuracy": f"{correct}/{n_out} ({correct/n_out:.0%})" if n_out > 0 else "N/A",
        "hold_rate": f"{hold_count}/{n_out} ({hold_count/n_out:.0%})" if n_out > 0 else "N/A",
        "avg_grounding": round(avg_grounding, 2),
        "avg_coverage": round(avg_coverage, 2),
        "avg_reasoning": round(avg_reasoning, 2),
        "avg_risk_awareness": round(avg_risk, 2),
        "has_report": (run_dir / "report.html").exists(),
    }


def compare_runs():
    """对比最近几次 run 的指标趋势"""
    runs = find_latest_runs(10)
    if not runs:
        logger.warning("没有找到历史 run 记录。先运行: python -m bench.auto_run")
        return

    logger.info(f"\n{'='*80}")
    logger.info("CQ-Bench 历史趋势对比")
    logger.info(f"{'='*80}")
    logger.info(f"{'Run ID':<20} | {'Cases':>5} | {'Direction':>12} | {'HOLD Rate':>10} | {'Ground':>6} | {'Cover':>5} | {'Reason':>6} | {'Risk':>5}")
    logger.info("-" * 80)

    for run_dir in reversed(runs):  # oldest first
        summary = load_run_summary(run_dir)
        if not summary or summary.get("cases", 0) == 0:
            continue
        logger.info(
            f"{summary['run_id']:<20} | {summary['cases']:>5} | "
            f"{summary['direction_accuracy']:>12} | {summary['hold_rate']:>10} | "
            f"{summary['avg_grounding']:>6.1f} | {summary['avg_coverage']:>5.1f} | "
            f"{summary['avg_reasoning']:>6.1f} | {summary['avg_risk_awareness']:>5.1f}"
        )

    logger.info(f"{'='*80}")


async def auto_run(n: int = None, judge_model: str = "qwen-plus", no_judge: bool = False):
    """一键运行 CQ-Bench"""
    from bench.run import run_bench

    dataset_path = ROOT / "bench" / "datasets" / "cq_bench_poc.jsonl"
    if not dataset_path.exists():
        logger.error(f"数据集不存在: {dataset_path}")
        return

    logger.info("=" * 60)
    logger.info("CQ-Bench 一键自动评估")
    logger.info(f"  数据集: {dataset_path.name}")
    logger.info(f"  Case 数: {n or 'ALL'}")
    logger.info(f"  Judge: {judge_model if not no_judge else '关闭'}")
    logger.info("=" * 60)

    await run_bench(
        runner_name="cq",
        dataset_path=dataset_path,
        n=n,
        judge_model=None if no_judge else judge_model,
    )

    # Show comparison after run
    compare_runs()


def main():
    parser = argparse.ArgumentParser(description="CQ-Bench 一键自动评估")
    parser.add_argument("--n", type=int, default=None, help="只跑前 N 个 case")
    parser.add_argument("--judge", default="qwen-plus", help="Judge 模型")
    parser.add_argument("--no-judge", action="store_true", help="不用 LLM 评分")
    parser.add_argument("--compare", action="store_true", help="只做历史对比")
    args = parser.parse_args()

    if args.compare:
        compare_runs()
    else:
        import asyncio
        asyncio.run(auto_run(n=args.n, judge_model=args.judge, no_judge=args.no_judge))


if __name__ == "__main__":
    main()
