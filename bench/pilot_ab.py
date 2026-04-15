"""
bench/pilot_ab.py — Phase 1 全量预计算之前的最小 pilot

跑 1 支股票 × 2 个月 × 2 个 version = 4 次 analyse,实测:
  1. 真实单位成本 (token 数 × 单价)
  2. 真实单次耗时 (portfolio_node 后 reasoning 有多长)
  3. v1_baseline 和 v2_esc 的 signals 确实不一样
  4. CostTracker 统计准确性
  5. 整条时点驱动链路跑通

成本估算: ~¥0.26,耗时 ~8-10 分钟
"""
from __future__ import annotations

import asyncio
import io
import sys
import time
from datetime import date

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from loguru import logger

from graph.builder import build_graph, make_initial_state
from observability.llm_tracker import CostTracker, set_current_tracker


# 降低 loguru 噪音,只看 WARNING+
logger.remove()
logger.add(sys.stderr, level="WARNING")


async def run_one(symbol: str, rebalance_date: date, version: str, graph) -> dict:
    """跑一次 graph.ainvoke 并返回关键字段"""
    state = make_initial_state(symbol)
    state["rebalance_date"] = rebalance_date.isoformat()
    state["prompt_version"] = version

    config = {
        "configurable": {"thread_id": f"pilot_{version}_{symbol}_{rebalance_date}"},
        "recursion_limit": 50,
    }

    t0 = time.time()
    result = await graph.ainvoke(state, config=config)
    elapsed = time.time() - t0

    order = result.get("trade_order") or {}
    fund = result.get("fundamental_report") or {}
    tech = result.get("technical_report") or {}
    sent = result.get("sentiment_report") or {}

    return {
        "symbol":       symbol,
        "date":         rebalance_date.isoformat(),
        "version":      version,
        "action":       order.get("action", "HOLD"),
        "confidence":   float(order.get("confidence") or 0.5),
        "quantity_pct": float(order.get("quantity_pct") or 0.0),
        "fund_rec":     fund.get("recommendation"),
        "fund_conf":    fund.get("confidence"),
        "tech_rec":     tech.get("recommendation"),
        "tech_conf":    tech.get("confidence"),
        "sent_rec":     sent.get("recommendation"),
        "sent_conf":    sent.get("confidence"),
        "fund_cites_n": len(fund.get("evidence_citations") or []),
        "tech_cites_n": len(tech.get("evidence_citations") or []),
        "sent_cites_n": len(sent.get("evidence_citations") or []),
        "rationale":    (order.get("rationale") or "")[:160],
        "reasoning_preview": (
            (fund.get("_portfolio_decision") or {}).get("reasoning") or ""
        )[:300] if fund.get("_portfolio_decision") else "(no portfolio reasoning)",
        "has_conflict": bool(result.get("has_conflict", False)),
        "elapsed_s":    round(elapsed, 1),
    }


async def main() -> None:
    PILOT_SYMBOL = "600519"
    PILOT_DATES = [
        date(2024, 1, 2),   # 第一个月
        date(2024, 6, 3),   # 第六个月
    ]

    graph = build_graph()
    print(f"{'=' * 70}")
    print(f"v2.2 Phase 1 Pilot: {PILOT_SYMBOL} × {len(PILOT_DATES)} months × 2 versions")
    print(f"{'=' * 70}")

    all_results: list[dict] = []

    for version in ("v1_baseline", "v2_esc"):
        tracker = CostTracker(run_id=f"pilot_{version}", hard_stop_cny=5.0)
        set_current_tracker(tracker)
        print(f"\n--- Running {version} ---")
        for d in PILOT_DATES:
            row = await run_one(PILOT_SYMBOL, d, version, graph)
            all_results.append(row)
            print(
                f"  {d}: {row['action']:<5} conf={row['confidence']:.2f} "
                f"qty={row['quantity_pct']:.0f}% "
                f"fund={row['fund_rec']}/{row['fund_conf']:.2f} "
                f"tech={row['tech_rec']}/{row['tech_conf']:.2f} "
                f"sent={row['sent_rec']}/{row['sent_conf']:.2f} "
                f"| cost=¥{tracker.total_cny:.4f} n={tracker.n_calls} "
                f"| t={row['elapsed_s']}s"
            )

        print(f"  {version} TOTAL: ¥{tracker.total_cny:.4f}, {tracker.n_calls} llm calls")
        set_current_tracker(None)

    # ── A/B 对比表 ──
    print(f"\n{'=' * 70}")
    print("A/B COMPARISON TABLE")
    print(f"{'=' * 70}")
    print(f"{'date':<12} {'version':<12} {'action':<6} {'conf':<6} {'qty':<5} {'fund':<4} {'tech':<4} {'sent':<4} {'cites(f/t/s)':<12}")
    for r in all_results:
        cites = f"{r['fund_cites_n']}/{r['tech_cites_n']}/{r['sent_cites_n']}"
        print(
            f"{r['date']:<12} {r['version']:<12} "
            f"{r['action']:<6} {r['confidence']:<6.2f} "
            f"{r['quantity_pct']:<5.0f} "
            f"{r['fund_rec']:<4} {r['tech_rec']:<4} {r['sent_rec']:<4} "
            f"{cites:<12}"
        )

    # 对比 v1 vs v2 差异 (按日期配对)
    print(f"\n{'-' * 70}")
    print("v1_baseline vs v2_esc DIFFS")
    print(f"{'-' * 70}")
    for d in PILOT_DATES:
        v1 = next(r for r in all_results if r["date"] == d.isoformat() and r["version"] == "v1_baseline")
        v2 = next(r for r in all_results if r["date"] == d.isoformat() and r["version"] == "v2_esc")
        print(f"\n{d}:")
        print(f"  v1_baseline: {v1['action']}/{v1['confidence']:.2f}/{v1['quantity_pct']:.0f}% | t={v1['elapsed_s']}s")
        print(f"  v2_esc     : {v2['action']}/{v2['confidence']:.2f}/{v2['quantity_pct']:.0f}% | t={v2['elapsed_s']}s")
        same_action = v1["action"] == v2["action"]
        print(f"  {'SAME' if same_action else 'DIFFERENT'} action, conf diff: {v2['confidence'] - v1['confidence']:+.2f}")

    # 总耗时/成本估算
    total_elapsed = sum(r["elapsed_s"] for r in all_results)
    print(f"\n{'-' * 70}")
    print(f"TOTAL ELAPSED: {total_elapsed:.1f}s ({total_elapsed / 60:.1f} min)")
    print(f"AVG PER ANALYSE: {total_elapsed / len(all_results):.1f}s")
    print(f"{'-' * 70}")

    # Phase 1 全量估算
    full_count = 20 * 36 * 2  # 1440
    full_elapsed = full_count * (total_elapsed / len(all_results))
    print(f"\nFULL Phase 1 projection:")
    print(f"  N = {full_count} analyses")
    print(f"  串行总耗时 = {full_elapsed:.0f}s = {full_elapsed / 60:.0f} min = {full_elapsed / 3600:.1f} hr")
    print(f"  Semaphore(10) 并行 ≈ {full_elapsed / 10 / 60:.0f} min = {full_elapsed / 10 / 3600:.1f} hr")


if __name__ == "__main__":
    asyncio.run(main())
