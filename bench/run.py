"""
bench/run.py — CLI entry point

Usage:
    python -m bench.run                           # 默认跑 POC 10 case
    python -m bench.run --runner cq --n 3         # 只跑前 3 个
    python -m bench.run --dataset cq_bench_poc    # 指定数据集
    python -m bench.run --judge qwen-max          # 指定 judge 模型
    python -m bench.run --no-judge                # 仅 runner,不评分(用于 debug)
    python -m bench.run --case BENCH-001          # 只跑单条
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from loguru import logger

# 把项目根加到 sys.path
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.judges import LLMJudge
from bench.runners import RUNNERS
from bench.schema import BenchCase, BenchOutput, BenchRun, BenchScore


def load_dataset(path: Path) -> list[BenchCase]:
    cases = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            cases.append(BenchCase.model_validate(d))
    return cases


async def run_bench(
    runner_name: str,
    dataset_path: Path,
    n: int | None = None,
    judge_model: str | None = None,
    case_filter: str | None = None,
    output_dir: Path | None = None,
) -> BenchRun:
    # 1. Load dataset
    cases = load_dataset(dataset_path)
    if case_filter:
        cases = [c for c in cases if c.id == case_filter]
        if not cases:
            raise ValueError(f"Case {case_filter} not found")
    if n is not None:
        cases = cases[:n]

    logger.info(f"📋 加载 {len(cases)} 个 case (from {dataset_path.name})")

    # 2. Setup output dir
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    if output_dir is None:
        output_dir = ROOT / "bench" / "results" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_state_dir = output_dir / "raw_states"

    # 3. Build runner
    runner_cls = RUNNERS.get(runner_name)
    if runner_cls is None:
        raise ValueError(f"Unknown runner: {runner_name}. Available: {list(RUNNERS)}")
    # CampusQuantRunner 接受 raw_state_dir
    if runner_name in ("campusquant", "cq"):
        runner = runner_cls(raw_state_dir=raw_state_dir)
    else:
        runner = runner_cls()

    await runner.setup()

    # 4. Build judge
    judge: LLMJudge | None = None
    if judge_model:
        judge = LLMJudge(model=judge_model)

    # 5. Init run container
    run = BenchRun(
        run_id=run_id,
        runner_name=runner_name,
        judge_name=judge.name if judge else "none",
        started_at=datetime.now(),
        case_count=len(cases),
        cases=cases,
        outputs=[],
        scores=[],
    )

    # 6. Execute
    for i, case in enumerate(cases, 1):
        logger.info(f"🎯 [{i}/{len(cases)}] 运行 {case.id} ({case.symbol} {case.name})...")
        output = await runner.run_case(case)
        run.outputs.append(output)

        if output.failed:
            logger.error(f"   ❌ {case.id} 崩溃: {output.error}")
        else:
            logger.info(
                f"   ✅ {case.id} · {output.direction} · "
                f"confidence={output.confidence:.2f} · "
                f"latency={output.latency_seconds:.1f}s"
            )

        if judge:
            logger.info(f"   ⚖️  Judge 评分中...")
            score = await judge.score(case, output)
            run.scores.append(score)
            logger.info(
                f"   📊 overall={score.overall_score} "
                f"grounding={score.grounding_score} "
                f"coverage={score.coverage_score} "
                f"reasoning={score.reasoning_score} "
                f"risk={score.risk_awareness_score} "
                f"direction_match={score.direction_match}"
            )

    await runner.teardown()

    # 7. Finalize + save
    run.finalize()

    # 保存原始 run JSON
    run_json_path = output_dir / "run.json"
    run_json_path.write_text(
        run.model_dump_json(indent=2, exclude_none=False),
        encoding="utf-8",
    )
    logger.info(f"💾 保存结果: {run_json_path}")

    # 生成 HTML 报告
    try:
        from bench.report import render_html_report
        html_path = output_dir / "report.html"
        html_path.write_text(render_html_report(run), encoding="utf-8")
        logger.info(f"📄 HTML 报告: {html_path}")
    except Exception as e:
        logger.warning(f"HTML 报告生成失败: {e}")

    # 汇总打印
    print()
    print("=" * 60)
    print(f"  Run ID: {run.run_id}")
    print(f"  Runner: {run.runner_name}")
    print(f"  Judge:  {run.judge_name}")
    print(f"  Cases:  {run.case_count}")
    if run.scores:
        print(f"  ────────────────────────────────────────")
        print(f"  Direction accuracy: {run.direction_accuracy:.1%}")
        print(f"  Avg grounding:      {run.avg_grounding:.2f} / 5")
        print(f"  Avg coverage:       {run.avg_coverage:.2f} / 5")
        print(f"  Avg reasoning:      {run.avg_reasoning:.2f} / 5")
        print(f"  Avg risk aware:     {run.avg_risk:.2f} / 5")
        print(f"  Avg overall:        {run.avg_overall:.2f} / 5")
        print(f"  Fail rate:          {run.fail_rate:.1%}")
        print(f"  Total latency:      {run.total_latency_seconds:.1f}s")
    print("=" * 60)

    return run


def main():
    parser = argparse.ArgumentParser(description="CQ-Bench · Agent 评测框架")
    parser.add_argument("--runner", default="campusquant", help="Runner name (campusquant/cq)")
    parser.add_argument(
        "--dataset",
        default="cq_bench_poc",
        help="数据集名 (不带 .jsonl),默认 cq_bench_poc",
    )
    parser.add_argument("--n", type=int, default=None, help="只跑前 N 个 case")
    parser.add_argument("--case", default=None, help="只跑指定 case ID")
    parser.add_argument(
        "--judge",
        default="qwen-plus",
        help="Judge 模型,默认 qwen-plus。传 'none' 跳过评分",
    )
    parser.add_argument("--no-judge", action="store_true", help="跳过评分 (debug 用)")
    args = parser.parse_args()

    dataset_path = ROOT / "bench" / "datasets" / f"{args.dataset}.jsonl"
    if not dataset_path.exists():
        print(f"❌ 数据集不存在: {dataset_path}")
        sys.exit(1)

    judge_model = None if (args.no_judge or args.judge == "none") else args.judge

    asyncio.run(
        run_bench(
            runner_name=args.runner,
            dataset_path=dataset_path,
            n=args.n,
            judge_model=judge_model,
            case_filter=args.case,
        )
    )


if __name__ == "__main__":
    main()
