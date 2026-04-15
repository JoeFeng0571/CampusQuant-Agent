"""
bench/smoke_time_travel.py — 验证 rebalance_date 透传到 data_node,time travel 生效

用法:
    .venv/Scripts/python.exe -m bench.smoke_time_travel
"""
from __future__ import annotations

import asyncio
import io
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from graph.builder import build_graph, make_initial_state


async def main() -> None:
    graph = build_graph()
    state = make_initial_state("600519")
    state["rebalance_date"] = "2024-06-03"
    print(f"[INPUT] state.rebalance_date = {state['rebalance_date']!r}")

    config = {
        "configurable": {"thread_id": "smoke_tt_600519_2024-06-03"},
        "recursion_limit": 50,
    }
    result = await graph.ainvoke(state, config=config)

    md = result.get("market_data") or {}
    print()
    print("=" * 60)
    print("[MARKET DATA]")
    print(f"  latest_price: {md.get('latest_price')}")
    print(f"  source:       {md.get('source')}")
    ind = md.get("indicators", {}) or {}
    print(f"  tech_signal:  {ind.get('tech_signal')}")
    print(f"  MA5/MA20/MA60: {ind.get('MA5')}/{ind.get('MA20')}/{ind.get('MA60')}")
    print(f"  BOLL_pct_B:   {ind.get('BOLL_pct_B')}")

    print()
    print("[ANALYSTS]")
    for key, label in [
        ("fundamental_report", "fund"),
        ("technical_report", "tech"),
        ("sentiment_report", "sent"),
    ]:
        r = result.get(key) or {}
        print(f"  {label}: {r.get('recommendation')} conf={r.get('confidence')}")
        for c in (r.get("evidence_citations") or [])[:3]:
            print(f"    - {c}")

    order = result.get("trade_order") or {}
    print()
    print("[TRADE ORDER]")
    print(f"  action:       {order.get('action')}")
    print(f"  confidence:   {order.get('confidence')}")
    print(f"  quantity_pct: {order.get('quantity_pct')}%")
    print(f"  rationale:    {(order.get('rationale') or '')[:200]}")

    print()
    print("=" * 60)
    # 关键断言
    lp = md.get("latest_price")
    src = md.get("source")
    if lp == 1525.03 and src == "bench_parquet_at":
        print("[OK] latest_price = 1525.03 (2024-06-03 历史价) + source = bench_parquet_at")
        print("[OK] time travel 生效!")
    else:
        print(f"[FAIL] expected 1525.03 / bench_parquet_at, got {lp} / {src}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
