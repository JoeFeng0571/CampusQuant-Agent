"""
bench/walk_forward_demo.py — 基于现有 signals parquet 的 Walk-forward 回测 demo

**零 API 消耗**：仅读取本地 parquet + OHLCV，纯计算。

数据源：
    - bench/data/signals_v2_alt.parquet (v2.2 预计算的 Agent 研判信号)
    - bench/data/ohlcv/{a,hk,us}/*.parquet (OHLCV)

运行：
    python bench/walk_forward_demo.py

输出：
    bench/results/walk_forward_report.md    绩效报告
    bench/results/walk_forward_nav.csv      NAV 曲线
    bench/results/walk_forward_trades.csv   成交明细
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from bench.backtest.walk_forward import run_walk_forward
from bench.backtest.report import save_report

SIGNALS_PARQUET = REPO_ROOT / "bench" / "data" / "signals_v2_alt.parquet"
OHLCV_DIR = REPO_ROOT / "bench" / "data" / "ohlcv"
OUTPUT_DIR = REPO_ROOT / "bench" / "results"


def load_ohlcv_for(symbols: list[str]) -> pd.DataFrame:
    """按 symbol 自动定位到 a/hk/us 子目录，汇总为 close price 面板。"""
    series = []
    for sym in symbols:
        if sym.endswith(".HK"):
            # 文件名用下划线代替点（如 00700_HK.parquet）
            fp = OHLCV_DIR / "hk" / f"{sym.replace('.', '_')}.parquet"
            if not fp.exists():
                fp = OHLCV_DIR / "hk" / f"{sym.replace('.HK', '')}.parquet"
        elif sym.isupper() and not any(c.isdigit() for c in sym):
            fp = OHLCV_DIR / "us" / f"{sym}.parquet"
        else:
            fp = OHLCV_DIR / "a" / f"{sym}.parquet"

        if not fp.exists():
            print(f"[warn] OHLCV not found for {sym}: {fp}")
            continue
        df = pd.read_parquet(fp)
        s = df.set_index("date")["close"].rename(sym)
        s.index = pd.to_datetime(s.index)
        series.append(s)

    if not series:
        raise RuntimeError("no OHLCV data loaded")
    prices = pd.concat(series, axis=1).sort_index()
    # 只保留全部标的都有价格的交易日（避免跨市场日历不一致）
    prices = prices.dropna(how="any")
    return prices


def main():
    print(f"loading signals: {SIGNALS_PARQUET}")
    signals = pd.read_parquet(SIGNALS_PARQUET)
    print(f"  rows={len(signals)}, symbols={signals['symbol'].nunique()}, "
          f"actions={signals['action'].value_counts().to_dict()}")

    symbols = sorted(signals["symbol"].unique())
    print(f"\nsymbols: {symbols}")

    prices = load_ohlcv_for(symbols)
    print(f"prices: shape={prices.shape}, "
          f"range={prices.index[0].date()} → {prices.index[-1].date()}")

    # rolling 12/3: 训练窗 12 月 + 测试窗 3 月
    results, full_nav, full_bench = run_walk_forward(
        signals, prices,
        train_months=12, test_months=3, mode="rolling",
        initial_cash=1_000_000.0,
    )
    print(f"\n generated {len(results)} walk-forward splits")

    paths = save_report(
        results, full_nav, full_bench, prices,
        output_dir=OUTPUT_DIR,
        title="CampusQuant Walk-Forward Backtest (signals_v2_alt)",
        notes=(
            f"- 信号: `signals_v2_alt.parquet` ({len(signals)} 条 rebalance 记录)\n"
            f"- 标的: {', '.join(symbols)}\n"
            f"- 期间: {prices.index[0].date()} → {prices.index[-1].date()}\n"
            f"- 切分: rolling，训练窗 12 月 + 测试窗 3 月（非重叠）\n"
            f"- 费用: 按市场自动（A 股 0.025% 佣金 + 0.1% 印花税(卖) + T+1; "
            f"港 0.025% + 0.1% 印花税(双边); 美 0% + SEC 0.00278%(卖)；通用滑点 0.03-0.05%）"
        ),
    )
    print(f"\n outputs:")
    for k, v in paths.items():
        print(f"  {k}: {v.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
