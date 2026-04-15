"""
bench/evidence_sharing_ab.py — Phase 2 同步重放 + A/B 报告生成

输入: bench/data/signals_v1_baseline.parquet + signals_v2_esc.parquet
      (由 bench/precompute_signals.py Phase 1 产出)

流程:
  1. 读两组 signals parquet 构造 SignalReplayStrategy
  2. 用 backtest/engine.BacktestEngine 分别跑:
     - in-sample (2023-01 → 2024-12)
     - holdout (2025-01 → 2025-12)
  3. 计算 Sharpe/Sortino/Calmar/MDD/胜率
  4. 月度 block bootstrap 计算 95% CI (10000 resamples)
  5. Leave-One-Market-Out 稳健性检查 (A/HK/US 各切片一次)
  6. 输出 bench/results/ab_esc_vs_baseline.md

重要: 本脚本 **零 LLM 成本**,可多次重跑调参数
"""
from __future__ import annotations

import io
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from loguru import logger

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from backtest.engine import BacktestEngine, StopRule
from backtest.metrics import compute_all, sharpe_ratio, max_drawdown, cagr
from bench.backtest.signal_replay_strategy import SignalReplayStrategy


_BASE_DIR     = Path(__file__).parent.parent
_DATA_DIR     = _BASE_DIR / "bench" / "data"
_OHLCV_DIR    = _DATA_DIR / "ohlcv"
_RESULTS_DIR  = _BASE_DIR / "bench" / "results"
_UNIVERSE_YML = _BASE_DIR / "bench" / "backtest" / "universe.yaml"

IN_SAMPLE_START = "2023-01-01"
IN_SAMPLE_END   = "2024-12-31"
HOLDOUT_START   = "2025-01-01"
HOLDOUT_END     = "2025-12-31"


# ════════════════════════════════════════════════════════════════
# 工具函数
# ════════════════════════════════════════════════════════════════

def _load_ohlcv_into_price_data() -> dict[str, pd.DataFrame]:
    """
    把 bench/data/ohlcv/{market}/{symbol}.parquet 读成
    {symbol: DataFrame[date, open, high, low, close, volume]} 字典,
    喂给 BacktestEngine(price_data=...)

    BacktestEngine 期待 symbol key 跟 signals parquet 里的 symbol 对齐。
    """
    price_data: dict[str, pd.DataFrame] = {}
    for market_dir in _OHLCV_DIR.iterdir():
        if not market_dir.is_dir():
            continue
        market = market_dir.name  # 'a' | 'hk' | 'us'
        for pq in market_dir.glob("*.parquet"):
            df = pd.read_parquet(pq)
            df["date"] = pd.to_datetime(df["date"]).dt.date
            df = df.sort_values("date").reset_index(drop=True)
            # 反解文件名 → symbol
            # a/600519.parquet → 600519
            # hk/00700_HK.parquet → 00700.HK
            # us/AAPL.parquet → AAPL
            stem = pq.stem
            if market == "hk":
                symbol = stem.replace("_HK", ".HK")
            else:
                symbol = stem
            price_data[symbol] = df
    return price_data


def _load_universe_markets() -> dict[str, str]:
    """返回 {symbol: market_name}"""
    with open(_UNIVERSE_YML, encoding="utf-8") as f:
        u = yaml.safe_load(f)
    out = {}
    for group_name, group in u["groups"].items():
        market = {"a_stock": "A", "hk_stock": "HK", "us_stock": "US"}[group_name]
        for s in group["stocks"]:
            out[s["symbol"]] = market
    return out


def _run_single_backtest(
    signals_path: Path,
    version: str,
    start: str,
    end: str,
    price_data: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    """
    跑一次回测,返回 metrics + nav Series
    """
    strat = SignalReplayStrategy(signals_parquet=str(signals_path), version=version)
    engine = BacktestEngine(
        strategy=strat,
        start=start,
        end=end,
        initial_cash=1_000_000,
        price_data=price_data,
        stop_rule=StopRule(stop_loss_pct=0.05, take_profit_pct=0.15),
    )
    result = engine.run()
    return {
        "version":   version,
        "window":    f"{start} → {end}",
        "nav":       result.nav,
        "returns":   result.returns,
        "trades":    result.trades,
        "metrics":   result.metrics,
    }


# ════════════════════════════════════════════════════════════════
# 月度 Block Bootstrap — 保留截面相关,打破时间相关
# ════════════════════════════════════════════════════════════════

def monthly_block_bootstrap_sharpe_diff(
    returns_a: pd.Series,
    returns_b: pd.Series,
    n_resamples: int = 10000,
    rf: float = 0.03,
) -> dict[str, float]:
    """
    以月为 block 重抽样, 计算 Sharpe(b) - Sharpe(a) 的 95% CI。

    返回:
      point_estimate: 点估计
      ci_95_low:      95% CI 下界
      ci_95_high:     95% CI 上界
      crosses_zero:   CI 是否跨零 (True = 差异不显著)
      n_months:       月数
    """
    if returns_a.empty or returns_b.empty:
        return {"point_estimate": 0, "ci_95_low": 0, "ci_95_high": 0, "crosses_zero": True, "n_months": 0}

    # 按月分组
    df_a = pd.DataFrame({"date": returns_a.index, "ret": returns_a.values})
    df_b = pd.DataFrame({"date": returns_b.index, "ret": returns_b.values})
    df_a["month"] = pd.to_datetime(df_a["date"]).dt.to_period("M")
    df_b["month"] = pd.to_datetime(df_b["date"]).dt.to_period("M")

    months = sorted(set(df_a["month"].unique()) & set(df_b["month"].unique()))
    n_months = len(months)
    if n_months < 6:
        return {"point_estimate": 0, "ci_95_low": 0, "ci_95_high": 0, "crosses_zero": True, "n_months": n_months}

    month_idx = {m: i for i, m in enumerate(months)}
    # 每月 block 存 {月 → daily returns array}
    blocks_a: list[np.ndarray] = [df_a[df_a["month"] == m]["ret"].values for m in months]
    blocks_b: list[np.ndarray] = [df_b[df_b["month"] == m]["ret"].values for m in months]

    point = sharpe_ratio(returns_b, rf) - sharpe_ratio(returns_a, rf)

    rng = np.random.default_rng(42)
    deltas = np.zeros(n_resamples)
    for i in range(n_resamples):
        sample_months = rng.integers(0, n_months, size=n_months)
        sampled_a = np.concatenate([blocks_a[j] for j in sample_months])
        sampled_b = np.concatenate([blocks_b[j] for j in sample_months])
        sa = sharpe_ratio(pd.Series(sampled_a), rf)
        sb = sharpe_ratio(pd.Series(sampled_b), rf)
        deltas[i] = sb - sa

    ci_low  = float(np.percentile(deltas, 2.5))
    ci_high = float(np.percentile(deltas, 97.5))
    crosses_zero = ci_low <= 0 <= ci_high

    return {
        "point_estimate": float(point),
        "ci_95_low":      ci_low,
        "ci_95_high":     ci_high,
        "crosses_zero":   crosses_zero,
        "n_months":       n_months,
    }


# ════════════════════════════════════════════════════════════════
# LOMO — Leave-One-Market-Out
# ════════════════════════════════════════════════════════════════

def leave_one_market_out(
    signals_a_path: Path,
    signals_b_path: Path,
    start: str,
    end: str,
    price_data: dict[str, pd.DataFrame],
    universe_markets: dict[str, str],
) -> dict[str, dict]:
    """
    分别去掉 A/HK/US 各 1 次,跑 A/B,看方向是否一致。
    """
    result: dict[str, dict] = {}
    markets = ["A", "HK", "US"]
    for excluded in markets:
        # 过滤 signals, 只保留非 excluded 市场的 symbol
        for version, path in [("v1_baseline", signals_a_path), ("v2_esc", signals_b_path)]:
            df = pd.read_parquet(path)
            keep = df["symbol"].apply(lambda s: universe_markets.get(s, "?") != excluded)
            df_lomo = df[keep].reset_index(drop=True)
            tmp_path = _DATA_DIR / f"_lomo_{version}_no_{excluded}.parquet"
            df_lomo.to_parquet(tmp_path, index=False)

            br = _run_single_backtest(tmp_path, version, start, end, price_data)
            key = f"no_{excluded}_{version}"
            result[key] = br["metrics"]
            tmp_path.unlink(missing_ok=True)

    # 对比每种切片下 A/B 的 Sharpe 差
    summary = {}
    for excluded in markets:
        m_a = result[f"no_{excluded}_v1_baseline"]
        m_b = result[f"no_{excluded}_v2_esc"]
        summary[f"去掉 {excluded}"] = {
            "sharpe_a":   m_a.get("sharpe", 0),
            "sharpe_b":   m_b.get("sharpe", 0),
            "delta":      m_b.get("sharpe", 0) - m_a.get("sharpe", 0),
            "b_wins":     m_b.get("sharpe", 0) > m_a.get("sharpe", 0),
        }
    return summary


# ════════════════════════════════════════════════════════════════
# 报告生成
# ════════════════════════════════════════════════════════════════

def _fmt_metric(v: float, kind: str = "num") -> str:
    if v is None:
        return "—"
    if kind == "pct":
        return f"{v * 100:+.2f}%"
    if kind == "ratio":
        return f"{v:.3f}"
    return f"{v:,.2f}"


def generate_report(
    in_a: dict, in_b: dict,
    ho_a: dict, ho_b: dict,
    bootstrap_in: dict, bootstrap_ho: dict,
    lomo_in: dict,
    output_path: Path,
) -> None:
    lines = [
        "# v2.2 EMNLP Evidence-Sharing A/B 回测报告",
        "",
        f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 实验设定",
        "",
        "- **Universe**: 20 支股票 (A10 + HK5 + US5)",
        "- **时间分层**: In-sample 2023-01 → 2024-12 / Holdout 2025-01 → 2025-12",
        "- **频率**: 每月首个交易日 rebalance",
        "- **主 LLM**: Qwen3.5-Plus",
        "- **A 组 (v1_baseline)**: portfolio_node 结论优先 (policyHypothesis+Rationale 混合)",
        "- **B 组 (v2_esc)**: portfolio_node 证据优先 (policyEvidence, EMNLP 2025 论文方法)",
        "- **所有其他改动**: 两组一致 (evidence_citations 字段生成 / RAG 共享池 / _compute_weighted_score / _conflict_score / ATR 动态止损)",
        "- **回测定位**: 探索性 A/B,不做统计显著性声明,用月度 block bootstrap + LOMO 做稳健性检查",
        "",
        "## In-Sample (2023-01 → 2024-12)",
        "",
        "| 指标 | A 组 (baseline) | B 组 (ESC) | Δ (B - A) |",
        "|---|---|---|---|",
        f"| 总收益率 | {_fmt_metric(in_a.get('total_return'), 'pct')} | {_fmt_metric(in_b.get('total_return'), 'pct')} | {_fmt_metric(in_b.get('total_return', 0) - in_a.get('total_return', 0), 'pct')} |",
        f"| 年化收益 (CAGR) | {_fmt_metric(in_a.get('cagr'), 'pct')} | {_fmt_metric(in_b.get('cagr'), 'pct')} | {_fmt_metric(in_b.get('cagr', 0) - in_a.get('cagr', 0), 'pct')} |",
        f"| Sharpe | {_fmt_metric(in_a.get('sharpe'), 'ratio')} | {_fmt_metric(in_b.get('sharpe'), 'ratio')} | {_fmt_metric(in_b.get('sharpe', 0) - in_a.get('sharpe', 0), 'ratio')} |",
        f"| Sortino | {_fmt_metric(in_a.get('sortino'), 'ratio')} | {_fmt_metric(in_b.get('sortino'), 'ratio')} | {_fmt_metric(in_b.get('sortino', 0) - in_a.get('sortino', 0), 'ratio')} |",
        f"| Calmar | {_fmt_metric(in_a.get('calmar'), 'ratio')} | {_fmt_metric(in_b.get('calmar'), 'ratio')} | {_fmt_metric(in_b.get('calmar', 0) - in_a.get('calmar', 0), 'ratio')} |",
        f"| 最大回撤 | {_fmt_metric(in_a.get('max_drawdown'), 'pct')} | {_fmt_metric(in_b.get('max_drawdown'), 'pct')} | {_fmt_metric(in_b.get('max_drawdown', 0) - in_a.get('max_drawdown', 0), 'pct')} |",
        f"| 胜率 | {_fmt_metric(in_a.get('win_rate'), 'pct')} | {_fmt_metric(in_b.get('win_rate'), 'pct')} | {_fmt_metric(in_b.get('win_rate', 0) - in_a.get('win_rate', 0), 'pct')} |",
        "",
        "### In-Sample 月度 Block Bootstrap (Sharpe 差 95% CI, 10000 resamples)",
        "",
        f"- **Point estimate** (Δ Sharpe): **{bootstrap_in.get('point_estimate', 0):+.3f}**",
        f"- **95% CI**: [{bootstrap_in.get('ci_95_low', 0):+.3f}, {bootstrap_in.get('ci_95_high', 0):+.3f}]",
        f"- **CI 跨零?**: {'是 (效果不显著)' if bootstrap_in.get('crosses_zero') else '否 (方向一致)'}",
        f"- n_months = {bootstrap_in.get('n_months', 0)}",
        "",
        "## Holdout (2025-01 → 2025-12) — 冻结对比",
        "",
        "| 指标 | A 组 | B 组 | Δ |",
        "|---|---|---|---|",
        f"| 总收益率 | {_fmt_metric(ho_a.get('total_return'), 'pct')} | {_fmt_metric(ho_b.get('total_return'), 'pct')} | {_fmt_metric(ho_b.get('total_return', 0) - ho_a.get('total_return', 0), 'pct')} |",
        f"| Sharpe | {_fmt_metric(ho_a.get('sharpe'), 'ratio')} | {_fmt_metric(ho_b.get('sharpe'), 'ratio')} | {_fmt_metric(ho_b.get('sharpe', 0) - ho_a.get('sharpe', 0), 'ratio')} |",
        f"| 最大回撤 | {_fmt_metric(ho_a.get('max_drawdown'), 'pct')} | {_fmt_metric(ho_b.get('max_drawdown'), 'pct')} | {_fmt_metric(ho_b.get('max_drawdown', 0) - ho_a.get('max_drawdown', 0), 'pct')} |",
        f"| 胜率 | {_fmt_metric(ho_a.get('win_rate'), 'pct')} | {_fmt_metric(ho_b.get('win_rate'), 'pct')} | {_fmt_metric(ho_b.get('win_rate', 0) - ho_a.get('win_rate', 0), 'pct')} |",
        "",
        "### Holdout 月度 Block Bootstrap",
        "",
        f"- **Δ Sharpe**: **{bootstrap_ho.get('point_estimate', 0):+.3f}** (95% CI: [{bootstrap_ho.get('ci_95_low', 0):+.3f}, {bootstrap_ho.get('ci_95_high', 0):+.3f}])",
        f"- **方向一致性**: {'In-sample 和 Holdout 同向' if (bootstrap_in.get('point_estimate', 0) * bootstrap_ho.get('point_estimate', 0)) > 0 else '方向不一致 (疑似 in-sample 过拟合)'}",
        "",
        "## Leave-One-Market-Out 稳健性 (In-Sample)",
        "",
        "| 切片 | A Sharpe | B Sharpe | Δ | B 胜? |",
        "|---|---|---|---|---|",
    ]
    for k, v in lomo_in.items():
        lines.append(
            f"| {k} | {v['sharpe_a']:.3f} | {v['sharpe_b']:.3f} | {v['delta']:+.3f} | {'✓' if v['b_wins'] else '✗'} |"
        )
    all_b_wins = all(v["b_wins"] for v in lomo_in.values())
    lines.append("")
    lines.append(f"**三市场切片一致性**: {'✅ B 组在所有切片下均优于 A' if all_b_wins else '⚠️ 非全部切片 B 胜,效果可能被某单一市场主导'}")
    lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n✅ 报告已写入 {output_path}")


# ════════════════════════════════════════════════════════════════
# 主入口
# ════════════════════════════════════════════════════════════════

def main() -> None:
    signals_a = _DATA_DIR / "signals_v1_baseline.parquet"
    signals_b = _DATA_DIR / "signals_v2_esc.parquet"
    if not signals_a.exists() or not signals_b.exists():
        print(f"❌ 缺少 signals parquet:")
        print(f"   A: {signals_a} {'OK' if signals_a.exists() else 'MISSING'}")
        print(f"   B: {signals_b} {'OK' if signals_b.exists() else 'MISSING'}")
        print("\n请先运行 Phase 1 预计算:")
        print("  python -m bench.precompute_signals v1_baseline 2023-01-01 2025-12-31")
        print("  python -m bench.precompute_signals v2_esc 2023-01-01 2025-12-31")
        sys.exit(1)

    print("=" * 60)
    print("v2.2 EMNLP Evidence-Sharing A/B Phase 2 重放")
    print("=" * 60)

    price_data = _load_ohlcv_into_price_data()
    print(f"loaded OHLCV: {len(price_data)} symbols")

    universe_markets = _load_universe_markets()

    # In-sample
    print(f"\n--- In-sample ({IN_SAMPLE_START} → {IN_SAMPLE_END}) ---")
    in_a = _run_single_backtest(signals_a, "v1_baseline", IN_SAMPLE_START, IN_SAMPLE_END, price_data)
    in_b = _run_single_backtest(signals_b, "v2_esc",      IN_SAMPLE_START, IN_SAMPLE_END, price_data)
    print(f"  A Sharpe={in_a['metrics'].get('sharpe', 0):.3f}, B Sharpe={in_b['metrics'].get('sharpe', 0):.3f}")

    # Holdout
    print(f"\n--- Holdout ({HOLDOUT_START} → {HOLDOUT_END}) ---")
    ho_a = _run_single_backtest(signals_a, "v1_baseline", HOLDOUT_START, HOLDOUT_END, price_data)
    ho_b = _run_single_backtest(signals_b, "v2_esc",      HOLDOUT_START, HOLDOUT_END, price_data)
    print(f"  A Sharpe={ho_a['metrics'].get('sharpe', 0):.3f}, B Sharpe={ho_b['metrics'].get('sharpe', 0):.3f}")

    # Block bootstrap
    print("\n--- Block bootstrap (Sharpe diff 95% CI) ---")
    bootstrap_in = monthly_block_bootstrap_sharpe_diff(in_a["returns"], in_b["returns"])
    bootstrap_ho = monthly_block_bootstrap_sharpe_diff(ho_a["returns"], ho_b["returns"])
    print(f"  in-sample: ΔSharpe = {bootstrap_in['point_estimate']:+.3f} "
          f"CI=[{bootstrap_in['ci_95_low']:+.3f}, {bootstrap_in['ci_95_high']:+.3f}] "
          f"crosses_zero={bootstrap_in['crosses_zero']}")
    print(f"  holdout:   ΔSharpe = {bootstrap_ho['point_estimate']:+.3f} "
          f"CI=[{bootstrap_ho['ci_95_low']:+.3f}, {bootstrap_ho['ci_95_high']:+.3f}] "
          f"crosses_zero={bootstrap_ho['crosses_zero']}")

    # LOMO
    print("\n--- Leave-One-Market-Out (in-sample) ---")
    lomo_in = leave_one_market_out(
        signals_a, signals_b, IN_SAMPLE_START, IN_SAMPLE_END, price_data, universe_markets,
    )
    for k, v in lomo_in.items():
        print(f"  {k}: A={v['sharpe_a']:.3f}, B={v['sharpe_b']:.3f}, Δ={v['delta']:+.3f}")

    # 报告
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _RESULTS_DIR / "ab_esc_vs_baseline.md"
    generate_report(
        in_a["metrics"], in_b["metrics"],
        ho_a["metrics"], ho_b["metrics"],
        bootstrap_in, bootstrap_ho,
        lomo_in,
        out_path,
    )


if __name__ == "__main__":
    main()
