"""
tests/test_matching_engine.py — Matching Engine 单元测试

覆盖:
  - 空簿下单
  - Price-time priority
  - Partial fill
  - Market order walks the book
  - Cancel
  - Maker-taker fees
  - Depth snapshot
"""
import pytest
from api.matching_engine import MatchingEngine, Side, OrderStatus


@pytest.fixture
def engine():
    return MatchingEngine()


class TestBasicOrders:
    def test_empty_book_limit(self, engine):
        """空簿下限价单,应挂单不成交"""
        r = engine.place_order("alice", "TEST", Side.BUY, 100.0, 10)
        assert r.filled == 0
        assert r.remaining == 10
        assert len(r.trades) == 0
        assert r.status == OrderStatus.OPEN

    def test_empty_book_market_rejected(self, engine):
        """空簿下市价单,应拒绝(无流动性)"""
        r = engine.place_order("alice", "TEST", Side.BUY, None, 10)
        assert r.rejected == "no_liquidity"

    def test_exact_match(self, engine):
        """买卖数量和价格完全匹配"""
        engine.place_order("alice", "TEST", Side.SELL, 100.0, 10)
        r = engine.place_order("bob", "TEST", Side.BUY, 100.0, 10)
        assert r.filled == 10
        assert r.remaining == 0
        assert r.status == OrderStatus.FILLED
        assert len(r.trades) == 1
        assert r.trades[0].price == 100.0
        assert r.trades[0].quantity == 10


class TestPriceTimePriority:
    def test_price_priority(self, engine):
        """价格优先: 更好的价格先成交"""
        engine.place_order("a", "T", Side.SELL, 102.0, 5)
        engine.place_order("b", "T", Side.SELL, 100.0, 5)  # 更低,先成交
        r = engine.place_order("buyer", "T", Side.BUY, 102.0, 5)
        assert r.trades[0].price == 100.0  # 先吃便宜的
        assert r.trades[0].sell_user == "b"

    def test_time_priority(self, engine):
        """时间优先: 同价格先挂的先成交"""
        engine.place_order("a", "T", Side.SELL, 100.0, 10)  # 先挂
        engine.place_order("b", "T", Side.SELL, 100.0, 10)  # 后挂
        r = engine.place_order("buyer", "T", Side.BUY, 100.0, 15)
        assert r.trades[0].sell_user == "a"  # a 全部成交(10)
        assert r.trades[0].quantity == 10
        assert r.trades[1].sell_user == "b"  # b 部分成交(5)
        assert r.trades[1].quantity == 5


class TestPartialFill:
    def test_partial_fill_incoming(self, engine):
        """incoming 订单部分成交"""
        engine.place_order("a", "T", Side.SELL, 100.0, 5)
        r = engine.place_order("buyer", "T", Side.BUY, 100.0, 10)
        assert r.filled == 5
        assert r.remaining == 5
        assert r.status == OrderStatus.PARTIAL

    def test_partial_fill_resting(self, engine):
        """挂单被部分成交"""
        engine.place_order("a", "T", Side.SELL, 100.0, 10)
        r = engine.place_order("buyer", "T", Side.BUY, 100.0, 3)
        assert r.filled == 3
        # 确认挂单还剩 7
        depth = engine.get_depth("T")
        assert depth["asks"][0]["quantity"] == 7


class TestMarketOrder:
    def test_market_walks_book(self, engine):
        """市价单 walks the book"""
        engine.place_order("a", "T", Side.SELL, 100.0, 5)
        engine.place_order("b", "T", Side.SELL, 101.0, 5)
        engine.place_order("c", "T", Side.SELL, 102.0, 5)
        # 市价买 12
        r = engine.place_order("buyer", "T", Side.BUY, None, 12)
        assert r.filled == 12
        assert len(r.trades) == 3
        total_cost = sum(t.price * t.quantity for t in r.trades)
        assert total_cost == 100 * 5 + 101 * 5 + 102 * 2  # 滑点


class TestCancel:
    def test_cancel_own_order(self, engine):
        r = engine.place_order("alice", "T", Side.SELL, 100.0, 10)
        ok = engine.cancel_order("T", r.order_id, "alice")
        assert ok
        depth = engine.get_depth("T")
        assert len(depth["asks"]) == 0

    def test_cancel_other_user_fails(self, engine):
        r = engine.place_order("alice", "T", Side.SELL, 100.0, 10)
        ok = engine.cancel_order("T", r.order_id, "bob")  # bob 不能撤 alice 的
        assert not ok


class TestFees:
    def test_maker_taker_fee(self, engine):
        """maker (挂单方) 费率低于 taker (吃单方)"""
        engine.place_order("maker", "600519.SH", Side.SELL, 100.0, 10)
        r = engine.place_order("taker", "600519.SH", Side.BUY, 100.0, 10)
        # A股 taker fee = 0.0003
        expected_fee = 100 * 10 * 0.0003  # = 0.3
        assert abs(r.total_fee - expected_fee) < 0.001


class TestDepth:
    def test_depth_aggregation(self, engine):
        """同价位的多个订单应聚合"""
        engine.place_order("a", "T", Side.SELL, 100.0, 5)
        engine.place_order("b", "T", Side.SELL, 100.0, 3)
        engine.place_order("c", "T", Side.SELL, 101.0, 10)
        depth = engine.get_depth("T")
        assert len(depth["asks"]) == 2
        assert depth["asks"][0]["price"] == 100.0
        assert depth["asks"][0]["quantity"] == 8  # 5+3 聚合
        assert depth["asks"][0]["orders"] == 2
        assert depth["asks"][1]["price"] == 101.0

    def test_depth_limit(self, engine):
        for i in range(20):
            engine.place_order("a", "T", Side.SELL, 100.0 + i, 1)
        depth = engine.get_depth("T", depth=5)
        assert len(depth["asks"]) == 5


class TestMultiSymbol:
    def test_separate_books(self, engine):
        """不同标的互不影响"""
        engine.place_order("a", "AAPL", Side.SELL, 150.0, 10)
        engine.place_order("b", "MSFT", Side.SELL, 300.0, 5)
        r = engine.place_order("c", "AAPL", Side.BUY, 150.0, 10)
        assert r.filled == 10
        depth_msft = engine.get_depth("MSFT")
        assert depth_msft["asks"][0]["quantity"] == 5  # MSFT 不受影响
