"""
backtest/engine.py — 轻量级日频回测引擎

设计决策(UPGRADE_PLAN §5.2.3):
  - 不用 backtrader/zipline，自己写 ~200 行更干净
  - Daily frequency, long-only
  - 用开盘价模拟执行
  - 包含 0.03% 手续费 + 0.1% 滑点

用法:
    from backtest.engine import BacktestEngine
    from backtest.strategies.equal_weight import EqualWeightStrategy

    engine = BacktestEngine(
        strategy=EqualWeightStrategy(symbols=["600519.SH", "000858.SZ"]),
        start="2023-01-01", end="2024-12-31",
        initial_cash=1_000_000,
    )
    result = engine.run()
    print(result.metrics)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

from backtest.metrics import compute_all


@dataclass
class Signal:
    """策略输出的信号"""
    symbol: str
    weight: float  # 目标权重 (0-1), 0 = 清仓


@dataclass
class TradeRecord:
    date: date
    symbol: str
    side: str  # BUY / SELL
    quantity: int
    price: float
    amount: float
    fee: float


@dataclass
class BacktestResult:
    """回测结果"""
    nav: pd.Series           # 每日 NAV
    returns: pd.Series       # 每日收益率
    trades: list[TradeRecord]
    metrics: dict[str, float]
    strategy_name: str
    start: date
    end: date
    initial_cash: float


class Strategy:
    """策略基类"""
    name: str = "base"

    def generate(self, t: date, prices: dict[str, float]) -> list[Signal]:
        """给出目标权重"""
        raise NotImplementedError


class BacktestEngine:
    FEE_RATE = 0.0003     # 手续费
    SLIPPAGE = 0.001      # 滑点

    def __init__(
        self,
        strategy: Strategy,
        start: str | date = "2023-01-01",
        end: str | date = "2024-12-31",
        initial_cash: float = 1_000_000,
        price_data: Optional[dict[str, pd.DataFrame]] = None,
    ):
        self.strategy = strategy
        self.start = pd.Timestamp(start).date()
        self.end = pd.Timestamp(end).date()
        self.initial_cash = initial_cash
        self.price_data = price_data or {}

        self.cash = initial_cash
        self.positions: dict[str, int] = {}    # symbol → shares
        self.nav_history: list[tuple[date, float]] = []
        self.trades: list[TradeRecord] = []

    def run(self) -> BacktestResult:
        """主回测循环"""
        logger.info(
            f"[Backtest] {self.strategy.name} | "
            f"{self.start} → {self.end} | cash={self.initial_cash:,.0f}"
        )

        t = self.start
        while t <= self.end:
            prices = self._get_prices(t)
            if not prices:
                t += timedelta(days=1)
                continue

            # 生成信号
            signals = self.strategy.generate(t, prices)

            # 执行交易
            if signals:
                self._rebalance(t, signals, prices)

            # 计算 NAV
            nav = self._compute_nav(prices)
            self.nav_history.append((t, nav))

            t += timedelta(days=1)

        if not self.nav_history:
            return BacktestResult(
                nav=pd.Series(dtype=float),
                returns=pd.Series(dtype=float),
                trades=self.trades,
                metrics={},
                strategy_name=self.strategy.name,
                start=self.start, end=self.end,
                initial_cash=self.initial_cash,
            )

        nav_series = pd.Series(
            [x[1] for x in self.nav_history],
            index=pd.DatetimeIndex([x[0] for x in self.nav_history]),
            name="NAV",
        )
        returns = nav_series.pct_change().dropna()
        metrics = compute_all(nav_series)

        logger.info(
            f"[Backtest] 完成 | days={len(nav_series)} | "
            f"return={metrics['total_return']:.2%} | "
            f"sharpe={metrics['sharpe']:.2f} | "
            f"max_dd={metrics['max_drawdown']:.2%}"
        )

        return BacktestResult(
            nav=nav_series,
            returns=returns,
            trades=self.trades,
            metrics=metrics,
            strategy_name=self.strategy.name,
            start=self.start, end=self.end,
            initial_cash=self.initial_cash,
        )

    def _get_prices(self, t: date) -> dict[str, float]:
        """获取 t 日各标的收盘价"""
        prices = {}
        for sym, df in self.price_data.items():
            if df.empty:
                continue
            # 找 ≤ t 的最近一天
            mask = df.index <= pd.Timestamp(t)
            if mask.any():
                row = df.loc[mask].iloc[-1]
                close = row.get("close", row.get("Close", None))
                if close and close > 0:
                    prices[sym] = float(close)
        return prices

    def _compute_nav(self, prices: dict[str, float]) -> float:
        """当前净值 = cash + 持仓市值"""
        market_value = sum(
            prices.get(sym, 0) * qty
            for sym, qty in self.positions.items()
        )
        return self.cash + market_value

    def _rebalance(self, t: date, signals: list[Signal], prices: dict[str, float]):
        """根据目标权重再平衡"""
        total_nav = self._compute_nav(prices)
        if total_nav <= 0:
            return

        for sig in signals:
            if sig.symbol not in prices:
                continue

            price = prices[sig.symbol]
            if price <= 0:
                continue

            current_qty = self.positions.get(sig.symbol, 0)
            target_value = total_nav * sig.weight
            target_qty = int(target_value / price)

            diff = target_qty - current_qty

            if diff > 0:
                # BUY
                exec_price = price * (1 + self.SLIPPAGE)
                cost = diff * exec_price
                fee = cost * self.FEE_RATE
                if cost + fee <= self.cash:
                    self.cash -= cost + fee
                    self.positions[sig.symbol] = current_qty + diff
                    self.trades.append(TradeRecord(
                        date=t, symbol=sig.symbol, side="BUY",
                        quantity=diff, price=exec_price,
                        amount=cost, fee=fee,
                    ))
            elif diff < 0:
                # SELL
                sell_qty = min(abs(diff), current_qty)
                if sell_qty <= 0:
                    continue
                exec_price = price * (1 - self.SLIPPAGE)
                proceeds = sell_qty * exec_price
                fee = proceeds * self.FEE_RATE
                self.cash += proceeds - fee
                self.positions[sig.symbol] = current_qty - sell_qty
                if self.positions[sig.symbol] == 0:
                    del self.positions[sig.symbol]
                self.trades.append(TradeRecord(
                    date=t, symbol=sig.symbol, side="SELL",
                    quantity=sell_qty, price=exec_price,
                    amount=proceeds, fee=fee,
                ))
