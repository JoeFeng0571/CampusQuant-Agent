"""
backtest/strategies/equal_weight.py — 等权基准策略

每月初等权配置给定的 universe,用作 baseline。
"""
from __future__ import annotations

from datetime import date

from backtest.engine import Signal, Strategy


class EqualWeightStrategy(Strategy):
    """买入并持有,每月 rebalance"""

    name = "equal_weight"

    def __init__(self, symbols: list[str], rebalance_day: int = 1):
        self.symbols = symbols
        self.rebalance_day = rebalance_day
        self._last_rebalance: date | None = None

    def generate(self, t: date, prices: dict[str, float]) -> list[Signal]:
        # 每月第一个交易日 rebalance
        if self._last_rebalance and self._last_rebalance.month == t.month:
            return []
        self._last_rebalance = t

        available = [s for s in self.symbols if s in prices]
        if not available:
            return []

        w = 1.0 / len(available) * 0.95  # 留 5% cash buffer
        return [Signal(symbol=s, weight=w) for s in available]
