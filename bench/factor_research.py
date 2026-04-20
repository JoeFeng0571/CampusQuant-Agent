"""
bench/factor_research.py — 在真实 A 股 OHLCV 数据上跑价格类因子

运行方式：
    python bench/factor_research.py

输出：
    bench/results/factor_research_report.md  — 可读的因子 IC/IR 报告
    bench/results/factor_ic_table.csv        — 完整表格数据

覆盖：
    - 动量 (1M / 3M / 12M)
    - 短期反转 (1M)
    - 波动率 (60D realized vol)
    - 最大回撤 (252D)

未覆盖（需要基本面历史面板）：
    - 价值因子 BP / EP / SP / DY
    - 质量因子 ROE / ROIC / 毛利率稳定性 / CFO/NI

实测使用 bench/backtest/universe.yaml 定义的 10 只 A 股。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict

import pandas as pd
import yaml

# 允许直接 `python bench/factor_research.py` 运行
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from factors import (
    compute_momentum,
    compute_reversal,
    compute_multi_horizon_momentum,
    compute_realized_volatility,
    compute_max_drawdown,
    summarize_ic,
    rank_ic,
    ic_ir,
    orthogonalize,
    combine_factors,
    ic_ir_weighted,
)

OHLCV_DIR = REPO_ROOT / "bench" / "data" / "ohlcv" / "a"
UNIVERSE_YAML = REPO_ROOT / "bench" / "backtest" / "universe.yaml"
OUTPUT_DIR = REPO_ROOT / "bench" / "results"


def load_a_share_prices() -> pd.DataFrame:
    """把 universe.yaml 里 10 只 A 股的收盘价加载为 (date × symbol) 面板。"""
    with open(UNIVERSE_YAML, "r", encoding="utf-8") as f:
        uni = yaml.safe_load(f)
    a_symbols = [s["symbol"] for s in uni["groups"]["a_stock"]["stocks"]]

    series_list = []
    for sym in a_symbols:
        fp = OHLCV_DIR / f"{sym}.parquet"
        if not fp.exists():
            print(f"[warn] missing OHLCV for {sym}")
            continue
        df = pd.read_parquet(fp)
        s = df.set_index("date")["close"].rename(sym)
        s.index = pd.to_datetime(s.index)
        series_list.append(s)

    prices = pd.concat(series_list, axis=1).sort_index()
    print(f"loaded prices: shape={prices.shape}, range={prices.index[0].date()} → {prices.index[-1].date()}")
    return prices


def compute_all_factors(prices: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """计算所有价格类因子。"""
    factors: Dict[str, pd.DataFrame] = {}

    # 动量 (三个尺度)
    mh = compute_multi_horizon_momentum(prices, horizons=(21, 63, 252))
    factors.update(mh)   # mom_21d / mom_63d / mom_252d

    # 短期反转（覆盖 1 月，取负号使"跌得多=因子值高"）
    factors["reversal_21d"] = compute_reversal(prices, window=21)

    # 波动率（取负号，让"低波动=高因子值"，与动量合成时符号统一）
    factors["neg_vol_60d"] = -compute_realized_volatility(prices, window=60)

    # 最大回撤（取负号：回撤小=因子值高）
    factors["neg_mdd_252d"] = -compute_max_drawdown(prices, window=252)

    return factors


def build_ic_report(
    factors: Dict[str, pd.DataFrame],
    prices: pd.DataFrame,
) -> pd.DataFrame:
    """逐因子跑 IC 评估，汇总为表格。"""
    rows = []
    for name, fp in factors.items():
        report = summarize_ic(fp, prices, forward_horizon=20,
                               decay_horizons=(1, 5, 10, 20))
        rows.append({
            "factor":    name,
            "ic_mean":   round(report["ic_mean"], 4),
            "ic_std":    round(report["ic_std"], 4),
            "ic_ir":     round(report["ic_ir"], 4),
            "t_stat":    round(report["t_stat"], 3),
            "win_rate":  round(report["win_rate"], 3),
            "ic_1d":     round(report["decay"].loc[1, "ic_mean"], 4),
            "ic_5d":     round(report["decay"].loc[5, "ic_mean"], 4),
            "ic_10d":    round(report["decay"].loc[10, "ic_mean"], 4),
            "ic_20d":    round(report["decay"].loc[20, "ic_mean"], 4),
            "n_periods": report["n_periods"],
        })
    return pd.DataFrame(rows).set_index("factor")


def render_markdown_report(
    ic_table: pd.DataFrame,
    combined_ic_ir: float,
    orthogonal_ir: Dict[str, float],
    prices: pd.DataFrame,
) -> str:
    lines = [
        "# CampusQuant 因子研究报告（A 股池）",
        "",
        f"- 数据范围: {prices.index[0].date()} → {prices.index[-1].date()}",
        f"- 股票数: {prices.shape[1]} (universe.yaml 定义的 A 股 10 只)",
        f"- 前向持有期: 20 日",
        "",
        "## 一、各因子 IC 评估",
        "",
        "| 因子 | IC 均值 | IC std | IC_IR | t 值 | 胜率 | IC(1d) | IC(5d) | IC(10d) | IC(20d) | 观测期 |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, row in ic_table.iterrows():
        lines.append(
            f"| {name} | {row['ic_mean']:+.4f} | {row['ic_std']:.4f} | "
            f"{row['ic_ir']:+.3f} | {row['t_stat']:+.2f} | {row['win_rate']:.2%} | "
            f"{row['ic_1d']:+.4f} | {row['ic_5d']:+.4f} | "
            f"{row['ic_10d']:+.4f} | {row['ic_20d']:+.4f} | {row['n_periods']} |"
        )

    lines += [
        "",
        "## 二、因子衰减解读",
        "",
        "- IC(1d) 到 IC(20d) 递减的因子说明信号随持有期衰减，适合短期调仓",
        "- IC 在 5-20 日保持稳定的因子说明信号持久性好，调仓频率可放低",
        "",
        "## 三、正交化 + IC_IR 加权合成",
        "",
        "对动量类因子做施密特正交后，再用 IC_IR 加权合成综合打分。",
        "",
        "**正交化后各残差因子的 IC_IR**：",
        "",
    ]
    for name, ir in orthogonal_ir.items():
        lines.append(f"- `{name}`: IC_IR = {ir:+.3f}")
    lines += [
        "",
        f"**IC_IR 加权合成因子的 IC_IR**: `{combined_ic_ir:+.3f}`",
        "",
        "## 四、工程约束说明",
        "",
        "- 本报告仅覆盖**价格类因子**（动量、反转、波动率、回撤）",
        "- 价值/质量因子需要基本面历史面板数据，当前 akshare 仅提供最新快照，需后续扩展",
        "- universe 仅 10 只股，横截面样本小，IC 的统计显著性有限；真实研究建议 ≥ 300 股",
        "- 结论仅作为技术框架演示，不作为投资建议",
    ]
    return "\n".join(lines)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    prices = load_a_share_prices()
    factors = compute_all_factors(prices)
    print(f"computed {len(factors)} factors: {list(factors.keys())}")

    ic_table = build_ic_report(factors, prices)
    print("\n=== IC table ===")
    print(ic_table.to_string())

    # 正交化动量类因子 + IC_IR 加权合成
    momentum_factors = {
        k: v for k, v in factors.items()
        if k.startswith("mom_") or k == "reversal_21d"
    }
    ortho = orthogonalize(
        list(momentum_factors.values()),
        names=list(momentum_factors.keys()),
    )
    orthogonal_ir = {}
    for name, panel in ortho.items():
        ic_series = rank_ic(panel, prices.pct_change(fill_method=None, periods=20).shift(-20))
        orthogonal_ir[name] = ic_ir(ic_series)

    combined = ic_ir_weighted(ortho, orthogonal_ir)
    combined_ic_series = rank_ic(combined, prices.pct_change(fill_method=None, periods=20).shift(-20))
    combined_ic_ir = ic_ir(combined_ic_series)

    print(f"\northogonal factor IC_IRs: {orthogonal_ir}")
    print(f"combined (IC_IR-weighted) factor IC_IR: {combined_ic_ir:.3f}")

    # 输出
    ic_table.to_csv(OUTPUT_DIR / "factor_ic_table.csv")
    report_md = render_markdown_report(
        ic_table, combined_ic_ir, orthogonal_ir, prices
    )
    (OUTPUT_DIR / "factor_research_report.md").write_text(
        report_md, encoding="utf-8"
    )
    print(f"\nreports written to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
