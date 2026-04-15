"""
bench/precompute_signals.py — v2.2 A/B 回测的 Phase 1 异步预计算

对 universe × 每月第一个交易日 × version 跑 graph.ainvoke,把每次产出的
TradeOrder 写到 signals_{version}.parquet,供 Phase 2 的 SignalReplayStrategy
同步回放使用。

用法:
    .venv/Scripts/python.exe -m bench.precompute_signals v1_baseline 2023-01-01 2025-12-31
    .venv/Scripts/python.exe -m bench.precompute_signals v2_esc 2023-01-01 2025-12-31

成本(方案 A):
    20 股 × 36 月 × ¥0.065 = ~¥47 / version
    A+B 两组合计 ~¥94 (留 ¥6 余量)
    CostTracker 硬停 ¥47 / version 保底不超

关键设计:
    1. 用 make_initial_state(symbol) + inject rebalance_date 参数让 data_node 拉当时点的数据
    2. asyncio.Semaphore(10) 限制并发避免 DashScope QPS 撞墙(20 RPS 额度)
    3. CostTracker 透过 contextvars 下发到节点的 _invoke_structured_with_fallback
    4. 单 symbol × 单日期失败不阻断,记 error log 继续下一个
    5. 中途抛 CostExceeded 直接中断保护预算

注意: 当前 data_node 会拉"最新"市场数据而不是历史时点,本脚本仅提供
signals parquet 的骨架接口。真实的时点回测需要 data_node 支持
`state["rebalance_date"]` 参数才能正确,这是一个 TODO(留给 §5.4 升级)。
"""
from __future__ import annotations

import argparse
import asyncio
import io
import os
import sys
import time
import traceback
from datetime import date, datetime
from pathlib import Path
from typing import Any

# 禁用 Windows 系统代理(akshare 反爬 workaround)
os.environ["NO_PROXY"] = "*"
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
import urllib.request
urllib.request.getproxies = lambda: {}

import pandas as pd
import yaml
from loguru import logger

# UTF-8 stdout on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from graph.builder import build_graph, make_initial_state
from observability.llm_tracker import (
    CostTracker,
    CostExceeded,
    set_current_tracker,
    get_current_tracker,
)


_BASE_DIR = Path(__file__).parent.parent
_UNIVERSE_YAML = _BASE_DIR / "bench" / "backtest" / "universe.yaml"
_SIGNALS_DIR = _BASE_DIR / "bench" / "data"
_ERROR_LOG_DIR = _BASE_DIR / "bench" / "data"

CONCURRENCY = 10
COST_HARD_STOP_CNY = 47.0  # 单 version 硬停,A+B 两组共 ¥94


# ════════════════════════════════════════════════════════════════
# Universe & rebalance dates
# ════════════════════════════════════════════════════════════════

def _load_universe() -> list[dict[str, Any]]:
    with open(_UNIVERSE_YAML, encoding="utf-8") as f:
        u = yaml.safe_load(f)
    stocks = []
    for group_name, group in u["groups"].items():
        market = {"a_stock": "A", "hk_stock": "HK", "us_stock": "US"}[group_name]
        for s in group["stocks"]:
            stocks.append({
                "symbol": s["symbol"],
                "name": s["name"],
                "market": market,
            })
    return stocks


def _monthly_first_trading_days(start: str, end: str) -> list[date]:
    """
    返回区间内每月第一个交易日(近似: 用每月第一个工作日代替)。
    真实交易日会随节假日偏移,但对月频回测精度足够。
    """
    start_d = datetime.strptime(start, "%Y-%m-%d").date()
    end_d = datetime.strptime(end, "%Y-%m-%d").date()
    result = []
    # 每月 1 号开始找第一个非周末日
    cur = date(start_d.year, start_d.month, 1)
    if cur < start_d:
        cur = _next_month(cur)
    while cur <= end_d:
        candidate = cur
        # 跳过周末 (Mon=0 ... Sun=6)
        while candidate.weekday() >= 5:
            candidate = date.fromordinal(candidate.toordinal() + 1)
        if start_d <= candidate <= end_d:
            result.append(candidate)
        cur = _next_month(cur)
    return result


def _next_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


# ════════════════════════════════════════════════════════════════
# Precompute core
# ════════════════════════════════════════════════════════════════

async def _run_one(
    graph,
    symbol: str,
    rebalance_date: date,
    version: str,
    sem: asyncio.Semaphore,
) -> dict[str, Any]:
    """
    跑一次 analyze graph,返回 signal dict(失败返回 error 字段的 dict)。
    """
    async with sem:
        try:
            state = make_initial_state(symbol)
            # 【v2.2 回测】时点驱动: data_node 走 get_market_data_at()
            state["rebalance_date"] = rebalance_date.isoformat()
            # 【v2.2 A/B】prompt 版本切换:v1_baseline = 结论优先旧风格,
            # v2_esc = 证据优先新风格(唯一变量,严格对照实验)
            state["prompt_version"] = version

            config = {
                "configurable": {
                    "thread_id": f"precompute_{version}_{symbol}_{rebalance_date.isoformat()}",
                },
                "recursion_limit": 50,
            }
            result = await graph.ainvoke(state, config=config)

            order = result.get("trade_order") or {}
            fund = result.get("fundamental_report") or {}
            tech = result.get("technical_report") or {}
            sent = result.get("sentiment_report") or {}

            return {
                "date":         rebalance_date.isoformat(),
                "symbol":       symbol,
                "version":      version,
                "action":       order.get("action", "HOLD"),
                "confidence":   float(order.get("confidence") or 0.5),
                "quantity_pct": float(order.get("quantity_pct") or 0.0),
                "stop_loss":    order.get("stop_loss"),
                "take_profit":  order.get("take_profit"),
                "fund_rec":     fund.get("recommendation"),
                "tech_rec":     tech.get("recommendation"),
                "sent_rec":     sent.get("recommendation"),
                "fund_cites":   fund.get("evidence_citations", []),
                "tech_cites":   tech.get("evidence_citations", []),
                "sent_cites":   sent.get("evidence_citations", []),
                "rationale":    (order.get("rationale") or "")[:300],
                "has_conflict": bool(result.get("has_conflict", False)),
                "error":        None,
            }
        except CostExceeded:
            # 硬停向上透传
            raise
        except Exception as exc:
            logger.error(
                f"[precompute] {version} {symbol} {rebalance_date}: "
                f"{type(exc).__name__}: {exc}"
            )
            return {
                "date":         rebalance_date.isoformat(),
                "symbol":       symbol,
                "version":      version,
                "action":       "HOLD",
                "confidence":   0.0,
                "quantity_pct": 0.0,
                "stop_loss":    None,
                "take_profit":  None,
                "fund_rec":     None,
                "tech_rec":     None,
                "sent_rec":     None,
                "fund_cites":   [],
                "tech_cites":   [],
                "sent_cites":   [],
                "rationale":    f"ERROR: {type(exc).__name__}: {str(exc)[:200]}",
                "has_conflict": False,
                "error":        f"{type(exc).__name__}: {str(exc)[:200]}",
            }


async def precompute(version: str, start: str, end: str) -> Path:
    """
    主入口: 对 universe × monthly_first_trading_days × version 跑 graph。

    Args:
        version: "v1_baseline" 或 "v2_esc"
        start/end: "YYYY-MM-DD"

    Returns:
        写入的 signals parquet 路径
    """
    universe = _load_universe()
    rebalance_dates = _monthly_first_trading_days(start, end)

    logger.info(
        f"[precompute] version={version} start={start} end={end} "
        f"universe={len(universe)} stocks months={len(rebalance_dates)} "
        f"total analyses={len(universe) * len(rebalance_dates)}"
    )

    # CostTracker 按 version 隔离
    tracker = CostTracker(run_id=f"precompute_{version}", hard_stop_cny=COST_HARD_STOP_CNY)
    set_current_tracker(tracker)

    graph = build_graph()
    sem = asyncio.Semaphore(CONCURRENCY)

    tasks = []
    for stock in universe:
        for d in rebalance_dates:
            tasks.append(_run_one(graph, stock["symbol"], d, version, sem))

    rows: list[dict[str, Any]] = []
    t0 = time.time()

    try:
        for i, coro in enumerate(asyncio.as_completed(tasks), 1):
            row = await coro
            rows.append(row)
            if i % 10 == 0:
                elapsed = time.time() - t0
                rps = i / elapsed if elapsed > 0 else 0
                logger.info(
                    f"[precompute:{version}] {i}/{len(tasks)} done "
                    f"({rps:.1f}/s, cost=¥{tracker.total_cny:.2f})"
                )
    except CostExceeded as ce:
        logger.error(f"[precompute:{version}] 硬停触发: {ce}")
        logger.error(f"  已完成 {len(rows)} 条,部分结果仍会写盘")
    finally:
        set_current_tracker(None)
        elapsed = time.time() - t0
        logger.info(
            f"[precompute:{version}] 结束: {len(rows)} 条, "
            f"耗时 {elapsed:.1f}s, 总成本 ¥{tracker.total_cny:.2f}"
        )

    # 落盘
    _SIGNALS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _SIGNALS_DIR / f"signals_{version}.parquet"
    df = pd.DataFrame(rows)
    # Parquet 不支持 list 列有混合类型,evidence_citations 存 JSON 字符串
    import json as _json
    for col in ("fund_cites", "tech_cites", "sent_cites"):
        if col in df.columns:
            df[col] = df[col].apply(lambda x: _json.dumps(x, ensure_ascii=False) if x else "[]")
    df.to_parquet(out_path, index=False, compression="snappy")
    logger.info(
        f"[precompute:{version}] written {len(df)} rows → {out_path} "
        f"({out_path.stat().st_size // 1024} KB)"
    )

    # 错误汇总
    err_df = df[df["error"].notna()]
    if not err_df.empty:
        err_log = _ERROR_LOG_DIR / f"signals_errors_{version}.log"
        with open(err_log, "w", encoding="utf-8") as f:
            for _, row in err_df.iterrows():
                f.write(f"{row['date']} {row['symbol']}: {row['error']}\n")
        logger.warning(f"[precompute:{version}] {len(err_df)} 条错误 → {err_log}")

    return out_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("version", choices=["v1_baseline", "v2_esc"])
    parser.add_argument("start", help="YYYY-MM-DD")
    parser.add_argument("end", help="YYYY-MM-DD")
    args = parser.parse_args()

    path = asyncio.run(precompute(args.version, args.start, args.end))
    print(f"\n✅ signals parquet: {path}")


if __name__ == "__main__":
    main()
