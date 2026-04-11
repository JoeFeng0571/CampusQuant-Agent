"""tests/test_backtest_stops.py — 回测止损/止盈测试"""
import sys
from pathlib import Path
from datetime import date
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
from backtest.engine import BacktestEngine, Strategy, Signal, StopRule


class BuyAndHoldStrategy(Strategy):
    name = "buy_and_hold"
    def __init__(self, symbol):
        self.symbol = symbol
        self._bought = False
    def generate(self, t, prices):
        if not self._bought and self.symbol in prices:
            self._bought = True
            return [Signal(self.symbol, 0.95)]
        return []


def make_price_data(symbol, prices_list, start="2024-01-01"):
    dates = pd.bdate_range(start, periods=len(prices_list))
    df = pd.DataFrame({"close": prices_list}, index=dates)
    return {symbol: df}


def test_stop_loss_triggers():
    # Price drops 10% → should trigger 5% stop loss
    prices = [100] * 5 + [95, 93, 91, 90, 88]
    data = make_price_data("TEST", prices)
    engine = BacktestEngine(
        strategy=BuyAndHoldStrategy("TEST"),
        start="2024-01-01", end="2024-01-15",
        initial_cash=100000, price_data=data,
        stop_rule=StopRule(stop_loss_pct=0.05),
    )
    result = engine.run()
    # Should have a STOP trade
    stop_trades = [t for t in result.trades if t.side == "STOP"]
    assert len(stop_trades) >= 1


def test_take_profit_triggers():
    # Price rises 20% → should trigger 15% take profit
    prices = [100, 105, 110, 115, 120, 125]
    data = make_price_data("TEST", prices)
    engine = BacktestEngine(
        strategy=BuyAndHoldStrategy("TEST"),
        start="2024-01-01", end="2024-01-10",
        initial_cash=100000, price_data=data,
        stop_rule=StopRule(take_profit_pct=0.15),
    )
    result = engine.run()
    stop_trades = [t for t in result.trades if t.side == "STOP"]
    assert len(stop_trades) >= 1


def test_no_same_day_reentry():
    # After stop-loss, should not re-enter same day
    prices = [100, 94, 93, 95, 96]  # drops then recovers
    data = make_price_data("TEST", prices)

    class AlwaysBuyStrategy(Strategy):
        name = "always_buy"
        def generate(self, t, prices):
            if "TEST" in prices:
                return [Signal("TEST", 0.95)]
            return []

    engine = BacktestEngine(
        strategy=AlwaysBuyStrategy(),
        start="2024-01-01", end="2024-01-08",
        initial_cash=100000, price_data=data,
        stop_rule=StopRule(stop_loss_pct=0.05),
    )
    result = engine.run()
    # Count BUY trades — should only have initial buy, not re-entry on stop day
    buy_trades = [t for t in result.trades if t.side == "BUY"]
    stop_trades = [t for t in result.trades if t.side == "STOP"]
    for st in stop_trades:
        same_day_buys = [b for b in buy_trades if b.date == st.date]
        assert len(same_day_buys) == 0, f"Re-entered on stop day {st.date}"


def test_no_stop_rule():
    prices = [100, 90, 80, 70]  # 30% drop, no stop
    data = make_price_data("TEST", prices)
    engine = BacktestEngine(
        strategy=BuyAndHoldStrategy("TEST"),
        start="2024-01-01", end="2024-01-06",
        initial_cash=100000, price_data=data,
        stop_rule=None,
    )
    result = engine.run()
    stop_trades = [t for t in result.trades if t.side == "STOP"]
    assert len(stop_trades) == 0
