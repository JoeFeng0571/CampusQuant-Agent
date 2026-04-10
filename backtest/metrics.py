"""
backtest/metrics.py — 回测指标计算

所有输入是 pandas Series (daily returns 或 NAV)。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sharpe_ratio(returns: pd.Series, rf: float = 0.03, periods: int = 252) -> float:
    """年化 Sharpe ratio"""
    if returns.empty or returns.std() == 0:
        return 0.0
    excess = returns - rf / periods
    return float(np.sqrt(periods) * excess.mean() / excess.std())


def sortino_ratio(returns: pd.Series, rf: float = 0.03, periods: int = 252) -> float:
    """年化 Sortino ratio (只看下行波动)"""
    if returns.empty:
        return 0.0
    excess = returns - rf / periods
    downside = excess[excess < 0]
    if downside.empty or downside.std() == 0:
        return float("inf") if excess.mean() > 0 else 0.0
    return float(np.sqrt(periods) * excess.mean() / downside.std())


def max_drawdown(nav: pd.Series) -> float:
    """最大回撤 (负数)"""
    if nav.empty:
        return 0.0
    peak = nav.cummax()
    dd = (nav - peak) / peak
    return float(dd.min())


def cagr(nav: pd.Series, periods: int = 252) -> float:
    """年化复合增长率"""
    if len(nav) < 2 or nav.iloc[0] <= 0:
        return 0.0
    total_return = nav.iloc[-1] / nav.iloc[0]
    years = len(nav) / periods
    if years <= 0:
        return 0.0
    return float(total_return ** (1 / years) - 1)


def calmar_ratio(nav: pd.Series, periods: int = 252) -> float:
    """Calmar ratio = CAGR / |max drawdown|"""
    dd = max_drawdown(nav)
    if dd == 0:
        return 0.0
    return cagr(nav, periods) / abs(dd)


def compute_all(nav: pd.Series, rf: float = 0.03) -> dict[str, float]:
    """一次性计算所有指标"""
    returns = nav.pct_change().dropna()
    return {
        "total_return": float((nav.iloc[-1] / nav.iloc[0] - 1) if len(nav) >= 2 else 0),
        "cagr": cagr(nav),
        "sharpe": sharpe_ratio(returns, rf),
        "sortino": sortino_ratio(returns, rf),
        "max_drawdown": max_drawdown(nav),
        "calmar": calmar_ratio(nav),
        "volatility": float(returns.std() * np.sqrt(252)) if not returns.empty else 0,
        "win_rate": float((returns > 0).mean()) if not returns.empty else 0,
        "trading_days": len(nav),
    }
