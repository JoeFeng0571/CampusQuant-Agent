"""
tests/test_walk_forward.py — Walk-forward 回测单元测试

覆盖：
  - 市场分类与费用模型（A 股 / 港股 / 美股）
  - T+1 约束（A 股买入当日不能卖）
  - Walk-forward 切分（rolling / expanding）
  - 信号重放（目标权重、最小手数、现金约束）
  - 等权买入持有基准
  - 交易级 FIFO 配对胜率
"""
import numpy as np
import pandas as pd
import pytest

from bench.backtest.market_rules import (
    A_STOCK_COSTS,
    HK_STOCK_COSTS,
    US_STOCK_COSTS,
    can_sell_today,
    classify_market,
    get_cost_model,
)
from bench.backtest.walk_forward import (
    Split,
    equal_weight_buy_and_hold,
    generate_splits,
    run_signal_replay,
    run_walk_forward,
    trade_level_stats,
)


# ══════════════════════════════════════════════════════════════
# 市场规则
# ══════════════════════════════════════════════════════════════

class TestMarketClassification:
    def test_a_stock_codes(self):
        assert classify_market("600519") == "A_STOCK"
        assert classify_market("000001") == "A_STOCK"
        assert classify_market("300750") == "A_STOCK"
        assert classify_market("688981") == "A_STOCK"
        assert classify_market("600519.SH") == "A_STOCK"
        assert classify_market("000001.SZ") == "A_STOCK"

    def test_hk_stock_codes(self):
        assert classify_market("00700.HK") == "HK_STOCK"
        assert classify_market("09988.HK") == "HK_STOCK"
        assert classify_market("00005.hk") == "HK_STOCK"

    def test_us_stock_codes(self):
        assert classify_market("AAPL") == "US_STOCK"
        assert classify_market("NVDA") == "US_STOCK"
        assert classify_market("JPM") == "US_STOCK"


class TestCostModel:
    def test_a_stock_buy_no_stamp_duty(self):
        # 买入 100k 元：佣金 25 + 过户 1 + 滑点 50 = 76
        cost = A_STOCK_COSTS.compute_cost(100_000, "buy")
        # 印花税应为 0 (仅卖方)
        assert abs(cost - 76.0) < 1e-6

    def test_a_stock_sell_includes_stamp_duty(self):
        # 卖出 100k 元：上面 + 印花税 100 = 176
        cost = A_STOCK_COSTS.compute_cost(100_000, "sell")
        assert abs(cost - 176.0) < 1e-6

    def test_hk_stamp_duty_both_sides(self):
        buy_cost  = HK_STOCK_COSTS.compute_cost(100_000, "buy")
        sell_cost = HK_STOCK_COSTS.compute_cost(100_000, "sell")
        # 港股印花税双边，买卖应相同
        assert abs(buy_cost - sell_cost) < 1e-6

    def test_us_zero_commission_but_sec_on_sell(self):
        buy_cost = US_STOCK_COSTS.compute_cost(10_000, "buy")
        sell_cost = US_STOCK_COSTS.compute_cost(10_000, "sell")
        # 卖方多 SEC fee
        assert sell_cost > buy_cost
        assert buy_cost == pytest.approx(10_000 * US_STOCK_COSTS.slippage_rate)

    def test_min_commission_floor(self):
        """成交额极小时，佣金不低于 min_commission。"""
        cost = A_STOCK_COSTS.compute_cost(1_000, "buy")
        # 佣金 0.25 < 5 最低 → 用 5
        # 过户 0.01，滑点 0.5，合计 5.51
        assert cost > 5.0

    def test_a_stock_min_lot_100(self):
        assert A_STOCK_COSTS.round_quantity(250) == 200
        assert A_STOCK_COSTS.round_quantity(99) == 0
        assert A_STOCK_COSTS.round_quantity(1000) == 1000

    def test_us_min_lot_1(self):
        assert US_STOCK_COSTS.round_quantity(250.7) == 250
        assert US_STOCK_COSTS.round_quantity(0.5) == 0


class TestTPlus:
    def test_a_stock_cannot_sell_same_day(self):
        # A 股 T+1，当天买当天不能卖
        assert can_sell_today(buy_date_idx=5, today_idx=5, t_plus=1) is False
        assert can_sell_today(buy_date_idx=5, today_idx=6, t_plus=1) is True

    def test_hk_us_can_sell_same_day(self):
        # T+0 市场，当日即可卖
        assert can_sell_today(buy_date_idx=5, today_idx=5, t_plus=0) is True


# ══════════════════════════════════════════════════════════════
# Walk-forward 切分
# ══════════════════════════════════════════════════════════════

class TestSplits:
    @pytest.fixture
    def three_years_daily(self):
        return pd.date_range("2023-01-01", "2025-12-31", freq="B")

    def test_rolling_non_overlapping_tests(self, three_years_daily):
        splits = generate_splits(
            three_years_daily, train_months=12, test_months=3, mode="rolling",
        )
        assert len(splits) > 0
        # 测试窗不重叠
        for i in range(1, len(splits)):
            assert splits[i].test_start >= splits[i - 1].test_end

    def test_expanding_train_grows(self, three_years_daily):
        splits = generate_splits(
            three_years_daily, train_months=12, test_months=3, mode="expanding",
        )
        # expanding: 训练窗起点固定
        for sp in splits:
            assert sp.train_start == pd.Timestamp(three_years_daily[0])
        # 训练窗长度递增
        lengths = [sp.train_end - sp.train_start for sp in splits]
        for i in range(1, len(lengths)):
            assert lengths[i] > lengths[i - 1]

    def test_rolling_train_length_constant(self, three_years_daily):
        splits = generate_splits(
            three_years_daily, train_months=12, test_months=3, mode="rolling",
        )
        lengths = [sp.train_end - sp.train_start for sp in splits]
        # rolling: 训练窗长度应稳定在约 12 个月（±几日，因月份长短）
        for lg in lengths:
            days = lg.days
            assert 350 < days < 370

    def test_empty_dates(self):
        assert generate_splits(pd.DatetimeIndex([])) == []


# ══════════════════════════════════════════════════════════════
# 信号重放
# ══════════════════════════════════════════════════════════════

@pytest.fixture
def toy_market():
    """3 个市场各 1 只股票，252 个交易日，价格平稳上涨 10%。"""
    dates = pd.date_range("2024-01-01", periods=252, freq="B")
    trend = np.linspace(1.0, 1.10, 252)
    prices = pd.DataFrame({
        "600519":   100 * trend,
        "00700.HK": 200 * trend,
        "AAPL":     150 * trend,
    }, index=dates)
    return prices


class TestSignalReplay:
    def test_basic_buy_signals(self, toy_market):
        signals = pd.DataFrame([
            {"date": toy_market.index[0], "symbol": "600519",
             "action": "BUY", "confidence": 0.8, "quantity_pct": 30},
            {"date": toy_market.index[0], "symbol": "AAPL",
             "action": "BUY", "confidence": 0.8, "quantity_pct": 30},
        ])
        nav, trades = run_signal_replay(signals, toy_market, initial_cash=1_000_000)
        # 应该盈利（标的都涨 10%）
        assert nav.iloc[-1] > nav.iloc[0]
        # 至少成交 2 笔买入
        buys = trades[trades["side"] == "buy"]
        assert len(buys) >= 2

    def test_only_hold_signals_no_trades(self, toy_market):
        signals = pd.DataFrame([
            {"date": toy_market.index[0], "symbol": "600519",
             "action": "HOLD", "confidence": 0.5, "quantity_pct": 0},
        ])
        nav, trades = run_signal_replay(signals, toy_market)
        assert trades.empty
        # NAV 应保持初始现金不变
        assert abs(nav.iloc[-1] - 1_000_000) < 1e-6

    def test_weight_normalization_when_exceeds_one(self, toy_market):
        """quantity_pct 合计超过 100 应按比例缩放。"""
        signals = pd.DataFrame([
            {"date": toy_market.index[0], "symbol": s,
             "action": "BUY", "confidence": 0.9, "quantity_pct": 50}
            for s in ["600519", "00700.HK", "AAPL"]
        ])
        # 合计 150% → 归一化到 ~33% 每只
        nav, trades = run_signal_replay(signals, toy_market, initial_cash=1_000_000)
        buys = trades[trades["side"] == "buy"]
        # 单笔成交金额应在账户总资产的 ~33% 附近（允许最小手数误差）
        total_buy = buys["notional"].sum()
        assert 0.90 * 1_000_000 < total_buy <= 1_000_000

    def test_rebalance_triggers_sells(self, toy_market):
        """先满仓 A 股，后切到 AAPL，应有卖单。"""
        signals = pd.DataFrame([
            {"date": toy_market.index[5],  "symbol": "600519",
             "action": "BUY", "confidence": 0.8, "quantity_pct": 90},
            {"date": toy_market.index[50], "symbol": "AAPL",
             "action": "BUY", "confidence": 0.8, "quantity_pct": 90},
        ])
        nav, trades = run_signal_replay(signals, toy_market, initial_cash=1_000_000)
        sells = trades[trades["side"] == "sell"]
        assert len(sells) >= 1


class TestBenchmark:
    def test_equal_weight_positive_on_uptrend(self, toy_market):
        nav = equal_weight_buy_and_hold(toy_market, initial_cash=1_000_000)
        assert nav.iloc[-1] > nav.iloc[0]
        # 涨约 10% - 摩擦，应在 9-10% 附近
        total_return = nav.iloc[-1] / nav.iloc[0] - 1
        assert 0.08 < total_return < 0.11


class TestTradeLevelStats:
    def test_fifo_pairing(self):
        """模拟：买入 3 个 100 元，卖出 3 个 120 元 → 单笔利润 60。"""
        trades = pd.DataFrame([
            {"date": "2024-01-01", "symbol": "X", "side": "buy",
             "qty": 3, "price": 100, "notional": 300, "cost": 0},
            {"date": "2024-02-01", "symbol": "X", "side": "sell",
             "qty": 3, "price": 120, "notional": 360, "cost": 0},
        ])
        trades["date"] = pd.to_datetime(trades["date"])
        stats = trade_level_stats(trades, pd.DataFrame())
        assert stats["trade_count"] == 1
        assert stats["win_rate"] == 1.0

    def test_empty_trades(self):
        stats = trade_level_stats(pd.DataFrame(), pd.DataFrame())
        assert stats == {"trade_count": 0, "win_rate": 0.0, "profit_loss_ratio": 0.0}


# ══════════════════════════════════════════════════════════════
# 完整流程
# ══════════════════════════════════════════════════════════════

def test_full_walk_forward_pipeline(toy_market):
    """测试 run_walk_forward 全链路能跑通。"""
    signals = pd.DataFrame([
        {"date": toy_market.index[30], "symbol": "AAPL",
         "action": "BUY", "confidence": 0.8, "quantity_pct": 50},
    ])
    results, full_nav, full_bench = run_walk_forward(
        signals, toy_market,
        train_months=3, test_months=1, mode="rolling",
        initial_cash=1_000_000,
    )
    # 至少产出 1 个切分
    assert len(results) >= 1
    assert isinstance(full_nav, pd.Series)
    assert isinstance(full_bench, pd.Series)
