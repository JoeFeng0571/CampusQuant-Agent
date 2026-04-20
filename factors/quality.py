"""
factors/quality.py — 质量因子

衡量公司的"盈利质量"与"经营稳健性"。相比价值因子（便宜与否），质量因子关注
"这家公司是不是值得拥有"。

参考：
    - Novy-Marx (2013), "The Other Side of Value: The Gross Profitability Premium"
    - Asness-Frazzini-Pedersen (2019), "Quality Minus Junk"
"""
from __future__ import annotations

import pandas as pd


def _safe_divide(num: pd.DataFrame, den: pd.DataFrame) -> pd.DataFrame:
    return num.where(den.abs() > 1e-12, other=float("nan")) / den.where(
        den.abs() > 1e-12, other=float("nan")
    )


def compute_roe(
    net_income: pd.DataFrame,
    equity: pd.DataFrame,
) -> pd.DataFrame:
    """ROE = 净利润 / 净资产。

    巴菲特长期偏爱 ROE 连续 10 年 > 15% 的公司。可拆解为：
        ROE = 净利率 × 资产周转率 × 权益乘数 (杜邦分析)
    """
    return _safe_divide(net_income, equity)


def compute_roic(
    nopat: pd.DataFrame,
    invested_capital: pd.DataFrame,
) -> pd.DataFrame:
    """ROIC = NOPAT / 投入资本。

    比 ROE 更严格——排除财务杠杆的影响，衡量运营资本的真实回报。
    NOPAT = EBIT × (1 - 税率)
    投入资本 = 股东权益 + 有息负债 - 超额现金
    """
    return _safe_divide(nopat, invested_capital)


def compute_gross_margin_stability(
    revenue_quarterly: pd.DataFrame,
    cost_quarterly: pd.DataFrame,
    lookback_quarters: int = 8,
) -> pd.DataFrame:
    """毛利率稳定性 = -1 × rolling std(毛利率, 过去 N 季度)。

    取负号让"稳定性高 → 因子值高"，方向与其他质量因子一致。
    覆盖 8 个季度 ≈ 2 年，能识别"周期平滑"vs"业绩暴涨暴跌"。
    """
    gross_margin = _safe_divide(revenue_quarterly - cost_quarterly, revenue_quarterly)
    # rolling std on each column
    vol = gross_margin.rolling(window=lookback_quarters, min_periods=4).std()
    return -vol


def compute_cashflow_coverage(
    operating_cashflow: pd.DataFrame,
    net_income: pd.DataFrame,
) -> pd.DataFrame:
    """经营现金流/净利润 (CFO/NI)。

    > 1 表示利润真金白银落袋；< 0.8 需警惕"应收账款堆积的纸面利润"。
    """
    return _safe_divide(operating_cashflow, net_income)
