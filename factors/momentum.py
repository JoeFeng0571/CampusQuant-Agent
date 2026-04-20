"""
factors/momentum.py — 动量与反转因子

仅依赖日频价格序列，是最容易实现的一类因子。

参考：
    - Jegadeesh-Titman (1993), 动量效应的开创性论文
    - Asness, "Value and Momentum Everywhere" (2013)
"""
from __future__ import annotations

import pandas as pd


def compute_momentum(
    prices: pd.DataFrame,
    window: int = 252,
    skip: int = 21,
) -> pd.DataFrame:
    """动量因子 = 过去 `window` 日到 `skip` 日前的累计收益。

    Args:
        prices: 日频收盘价，index=date, columns=symbols
        window: 回看窗口（日），默认 252（≈ 1 年）
        skip: 跳过最近 N 日（避开反转效应），默认 21（≈ 1 月）

    经典形式:
        J-K 动量: J=12 月, K=1 月 → window=252, skip=21
        短动量: J=6 月, K=1 月 → window=126, skip=21
    """
    if window <= skip:
        raise ValueError(f"window ({window}) must be > skip ({skip})")

    # 今日为 t，过去窗口的起点为 t - window，终点为 t - skip
    # 因子值 = P_{t-skip} / P_{t-window} - 1
    mom = prices.shift(skip) / prices.shift(window) - 1.0
    return mom


def compute_reversal(
    prices: pd.DataFrame,
    window: int = 21,
) -> pd.DataFrame:
    """短期反转因子 = -1 × 过去 `window` 日累计收益。

    取负号使"跌得多 → 因子值高 → 预期未来回升"，便于与动量因子合成时符号统一。
    """
    ret = prices.pct_change(fill_method=None, periods=window)
    return -ret


def compute_multi_horizon_momentum(
    prices: pd.DataFrame,
    horizons: tuple[int, ...] = (21, 63, 252),
) -> dict[str, pd.DataFrame]:
    """同时计算多个时间窗的动量，返回 {horizon_name: factor_panel}。

    常用 1 月 (21) / 3 月 (63) / 12 月 (252) 三种尺度。
    """
    out = {}
    for h in horizons:
        if h <= 21:
            # 短尺度走反转（跳过 skip，否则样本不足）
            out[f"mom_{h}d"] = prices.pct_change(fill_method=None, periods=h)
        else:
            out[f"mom_{h}d"] = prices.shift(21) / prices.shift(h) - 1.0
    return out
