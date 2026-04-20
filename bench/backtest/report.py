"""
bench/backtest/report.py — Walk-forward 回测报告生成

产出 markdown 报告（默认）+ 可选 CSV 明细，支持跨多次 walk-forward 比较。
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from bench.backtest.walk_forward import (
    WalkForwardResult,
    trade_level_stats,
)
from backtest.metrics import compute_all


def render_walk_forward_report(
    results: list[WalkForwardResult],
    full_nav: pd.Series,
    full_bench: pd.Series,
    prices: pd.DataFrame,
    title: str = "Walk-Forward Backtest Report",
    notes: str | None = None,
) -> str:
    """把 walk-forward 结果渲染为 markdown 字符串。"""
    lines: list[str] = [f"# {title}", ""]
    if notes:
        lines += [notes, ""]

    # ── 总览 ─────────────────────────────────────
    if not full_nav.empty:
        total_metrics = compute_all(full_nav)
        bench_metrics = compute_all(full_bench) if not full_bench.empty else {}
        lines += [
            "## 一、总体指标（拼接所有测试窗）",
            "",
            "| 指标 | 策略 | 基准（等权 buy-and-hold）|",
            "|---|---|---|",
            f"| 总收益 | {total_metrics.get('total_return', 0):+.2%} | {bench_metrics.get('total_return', 0):+.2%} |",
            f"| 年化收益 (CAGR) | {total_metrics.get('cagr', 0):+.2%} | {bench_metrics.get('cagr', 0):+.2%} |",
            f"| 年化波动 | {total_metrics.get('volatility', 0):.2%} | {bench_metrics.get('volatility', 0):.2%} |",
            f"| 夏普比 | {total_metrics.get('sharpe', 0):+.3f} | {bench_metrics.get('sharpe', 0):+.3f} |",
            f"| Sortino | {total_metrics.get('sortino', 0):+.3f} | {bench_metrics.get('sortino', 0):+.3f} |",
            f"| 最大回撤 | {total_metrics.get('max_drawdown', 0):+.2%} | {bench_metrics.get('max_drawdown', 0):+.2%} |",
            f"| Calmar | {total_metrics.get('calmar', 0):+.3f} | {bench_metrics.get('calmar', 0):+.3f} |",
            f"| 胜率（日级）| {total_metrics.get('win_rate', 0):.2%} | {bench_metrics.get('win_rate', 0):.2%} |",
            f"| 交易日数 | {total_metrics.get('trading_days', 0)} | {bench_metrics.get('trading_days', 0)} |",
            "",
        ]

    # ── 交易级统计（所有测试窗合并）──────────────
    all_trades = pd.concat([r.trades for r in results], ignore_index=True) \
                 if results and any(not r.trades.empty for r in results) else pd.DataFrame()
    if not all_trades.empty:
        tstats = trade_level_stats(all_trades, prices)
        lines += [
            "## 二、交易级统计（FIFO 配对）",
            "",
            f"- 成交笔数（配对）: **{tstats['trade_count']}**",
            f"- 胜率（交易级）: **{tstats['win_rate']:.2%}**",
            f"- 盈亏比 (avg_win / avg_loss): **{tstats['profit_loss_ratio']:.3f}**",
            f"- 平均盈利: {tstats.get('avg_win', 0):.2f}",
            f"- 平均亏损: {tstats.get('avg_loss', 0):.2f}",
            "",
        ]

    # ── 逐窗指标 ─────────────────────────────────
    lines += [
        "## 三、逐窗绩效",
        "",
        "| 训练窗 | 测试窗 | 策略收益 | 基准收益 | 超额 | 策略夏普 | 最大回撤 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        s = r.metrics
        b = r.bench_metrics
        excess = s.get("total_return", 0) - b.get("total_return", 0)
        lines.append(
            f"| {r.split.train_start.date()}~{r.split.train_end.date()} "
            f"| {r.split.test_start.date()}~{r.split.test_end.date()} "
            f"| {s.get('total_return', 0):+.2%} "
            f"| {b.get('total_return', 0):+.2%} "
            f"| {excess:+.2%} "
            f"| {s.get('sharpe', 0):+.3f} "
            f"| {s.get('max_drawdown', 0):+.2%} |"
        )
    lines.append("")

    # ── 成本明细 ─────────────────────────────────
    if not all_trades.empty:
        total_cost = float(all_trades["cost"].sum())
        total_notional = float(all_trades["notional"].sum())
        cost_pct = total_cost / total_notional if total_notional > 0 else 0
        lines += [
            "## 四、摩擦成本",
            "",
            f"- 总成交金额: {total_notional:,.2f}",
            f"- 总摩擦成本: {total_cost:,.2f}（{cost_pct:.3%} 双边合计）",
            "- 包含：佣金 + 印花税（A 股卖/港股双边）+ SEC（美股卖）+ 滑点 0.03-0.05%",
            "",
        ]

    return "\n".join(lines)


def save_report(
    results: list[WalkForwardResult],
    full_nav: pd.Series,
    full_bench: pd.Series,
    prices: pd.DataFrame,
    output_dir: str | Path,
    *,
    title: str = "Walk-Forward Backtest Report",
    notes: str | None = None,
) -> dict[str, Path]:
    """渲染 markdown + 保存 NAV / 交易明细 CSV，返回文件路径字典。"""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    md = render_walk_forward_report(
        results, full_nav, full_bench, prices,
        title=title, notes=notes,
    )
    md_path = out / "walk_forward_report.md"
    md_path.write_text(md, encoding="utf-8")

    nav_path = out / "walk_forward_nav.csv"
    nav_df = pd.DataFrame({"strategy": full_nav, "benchmark": full_bench})
    nav_df.to_csv(nav_path)

    all_trades = pd.concat([r.trades for r in results], ignore_index=True) \
                 if results and any(not r.trades.empty for r in results) else pd.DataFrame()
    trades_path = out / "walk_forward_trades.csv"
    all_trades.to_csv(trades_path, index=False)

    return {
        "markdown": md_path,
        "nav_csv":  nav_path,
        "trades_csv": trades_path,
    }
