"""
factors/volatility.py — 波动率因子

低波动异象（low-volatility anomaly）：波动率低的股票反而长期跑赢高波动股票。
一般把波动率作为**负向因子**（取负号使"低波动 = 高因子值"）。

参考：
    - Ang-Hodrick-Xing-Zhang (2006), "The Cross-Section of Volatility and Expected Returns"
    - Frazzini-Pedersen (2014), "Betting Against Beta"
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute_realized_volatility(
    prices: pd.DataFrame,
    window: int = 60,
    annualize: int = 252,
) -> pd.DataFrame:
    """已实现波动率 = 过去 `window` 日日收益的 std，年化。

    返回的因子值保留正波动率（未取负）。在合成阶段可根据方向需求再决定符号。
    """
    rets = prices.pct_change(fill_method=None)
    return rets.rolling(window=window, min_periods=window // 2).std() * np.sqrt(annualize)


def compute_downside_deviation(
    prices: pd.DataFrame,
    window: int = 60,
    threshold: float = 0.0,
    annualize: int = 252,
) -> pd.DataFrame:
    """下行偏差 = 仅对 return < threshold 的样本计算 std，年化。

    比总波动率更能反映"亏损时的风险"，是 Sortino 比率的分母。
    """
    rets = prices.pct_change(fill_method=None)
    negative = rets.where(rets < threshold, other=0.0)

    def _rolling_downside(series: pd.Series) -> pd.Series:
        # 只对 < threshold 的样本求平方和
        def core(arr):
            mask = arr < threshold
            if mask.sum() == 0:
                return 0.0
            diffs = arr[mask] - threshold
            return np.sqrt(np.mean(diffs ** 2))
        return rets[series.name].rolling(window=window, min_periods=window // 2).apply(
            core, raw=True
        )

    # 用更直接的向量化实现
    neg_squared = ((rets - threshold).clip(upper=0.0)) ** 2
    dd = np.sqrt(neg_squared.rolling(window=window, min_periods=window // 2).mean())
    return dd * np.sqrt(annualize)


def compute_max_drawdown(
    prices: pd.DataFrame,
    window: int = 252,
) -> pd.DataFrame:
    """过去 `window` 日的最大回撤（绝对值）。

    回撤定义：(当前价 - 窗口内最高价) / 窗口内最高价，取绝对值。
    """
    rolling_max = prices.rolling(window=window, min_periods=window // 4).max()
    drawdown = (prices - rolling_max) / rolling_max
    return drawdown.abs()
