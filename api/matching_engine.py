"""
api/matching_engine.py — Price-Time Priority Matching Engine

升级计划 §5.4 W4: 替换玩具级 mock_exchange.py

支持:
  - Limit order (限价单)
  - Market order (市价单,吃对手盘 best price)
  - Partial fill (部分成交)
  - Cancel (撤单)
  - Price-time priority (FIFO at same price)
  - Maker-taker 费率差异
  - Order book snapshot query (depth)
  - 持久化(SQLite)

不做(避免 scope creep):
  - Stop-loss / trailing stop
  - Iceberg / hidden orders
  - Real-time market data feed

线程安全: 所有操作加 threading.Lock

面试 talking point:
  "我自己实现了 price-time priority order book,支持
   partial fill、maker-taker 费率、盘口查询,
   并用 property-based test 验证了不变式"
"""
from __future__ import annotations

import itertools
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from loguru import logger


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELED = "CANCELED"


# ════════════════════════════════════════════════════════════════
# Data classes
# ════════════════════════════════════════════════════════════════


@dataclass
class Order:
    order_id: int
    user_id: str
    symbol: str
    side: Side
    price: float          # 限价;市价单用 0 表示
    quantity: int          # 原始下单量
    filled: int = 0        # 已成交量
    status: OrderStatus = OrderStatus.OPEN
    timestamp: float = field(default_factory=time.monotonic)
    is_market: bool = False

    @property
    def remaining(self) -> int:
        return self.quantity - self.filled


@dataclass
class Trade:
    trade_id: int
    symbol: str
    price: float
    quantity: int
    buy_order_id: int
    sell_order_id: int
    buy_user: str
    sell_user: str
    maker_order_id: int    # 挂单方
    taker_order_id: int    # 吃单方
    timestamp: float = field(default_factory=time.monotonic)


@dataclass
class OrderResult:
    order_id: int
    status: OrderStatus
    filled: int = 0
    remaining: int = 0
    trades: list[Trade] = field(default_factory=list)
    avg_price: float = 0.0
    total_fee: float = 0.0
    rejected: Optional[str] = None  # 拒绝原因


# ════════════════════════════════════════════════════════════════
# Fee model
# ════════════════════════════════════════════════════════════════

FEE_TIERS = {
    "A":  {"maker": 0.0001, "taker": 0.0003},
    "HK": {"maker": 0.00005, "taker": 0.0002},
    "US": {"maker": 0.0, "taker": 0.0001},
}


def _get_fee_tier(symbol: str) -> dict:
    if symbol.endswith((".SH", ".SZ")):
        return FEE_TIERS["A"]
    elif symbol.endswith(".HK"):
        return FEE_TIERS["HK"]
    else:
        return FEE_TIERS["US"]


# ════════════════════════════════════════════════════════════════
# Order Book (per symbol)
# ════════════════════════════════════════════════════════════════


class OrderBook:
    """
    单个标的的 order book。

    内部数据结构:
      bids: list of Order, 按 (price DESC, timestamp ASC) 排序
      asks: list of Order, 按 (price ASC, timestamp ASC) 排序
    """

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.bids: list[Order] = []   # 买盘: 价格降序
        self.asks: list[Order] = []   # 卖盘: 价格升序
        self.last_trade_price: Optional[float] = None
        self._lock = threading.Lock()

    def place(self, order: Order) -> OrderResult:
        """下单 + 撮合"""
        with self._lock:
            trades = self._match(order)

            # 未完全成交的部分挂到簿上
            if order.remaining > 0 and not order.is_market:
                if order.side == Side.BUY:
                    self._insert_bid(order)
                else:
                    self._insert_ask(order)
                if order.filled > 0:
                    order.status = OrderStatus.PARTIAL

            elif order.remaining == 0:
                order.status = OrderStatus.FILLED

            # 计算费用
            fee_tier = _get_fee_tier(order.symbol)
            total_fee = 0.0
            total_amount = 0.0
            for t in trades:
                is_maker = t.maker_order_id == order.order_id
                fee_rate = fee_tier["maker"] if is_maker else fee_tier["taker"]
                total_fee += t.price * t.quantity * fee_rate
                total_amount += t.price * t.quantity

            avg_price = total_amount / order.filled if order.filled > 0 else 0

            return OrderResult(
                order_id=order.order_id,
                status=order.status,
                filled=order.filled,
                remaining=order.remaining,
                trades=trades,
                avg_price=round(avg_price, 6),
                total_fee=round(total_fee, 6),
            )

    def cancel(self, order_id: int, user_id: str) -> bool:
        """撤单"""
        with self._lock:
            for book in (self.bids, self.asks):
                for i, o in enumerate(book):
                    if o.order_id == order_id and o.user_id == user_id:
                        o.status = OrderStatus.CANCELED
                        del book[i]
                        return True
            return False

    def snapshot(self, depth: int = 5) -> dict:
        """返回 N 档盘口"""
        with self._lock:
            # 聚合同价位
            bid_levels = self._aggregate(self.bids, depth)
            ask_levels = self._aggregate(self.asks, depth)
            return {
                "symbol": self.symbol,
                "bids": bid_levels,
                "asks": ask_levels,
                "last": self.last_trade_price,
                "bid_count": len(self.bids),
                "ask_count": len(self.asks),
            }

    # ── 内部方法 ──

    def _match(self, incoming: Order) -> list[Trade]:
        """核心撮合逻辑: price-time priority"""
        opposite = self.asks if incoming.side == Side.BUY else self.bids
        trades: list[Trade] = []

        while incoming.remaining > 0 and opposite:
            best = opposite[0]

            # 价格不匹配,退出
            if not incoming.is_market:
                if incoming.side == Side.BUY and incoming.price < best.price:
                    break
                if incoming.side == Side.SELL and incoming.price > best.price:
                    break

            # 撮合量 = min(双方剩余)
            qty = min(incoming.remaining, best.remaining)
            trade_price = best.price  # 按挂单价成交

            trade = Trade(
                trade_id=0,  # 由 MatchingEngine 分配
                symbol=self.symbol,
                price=trade_price,
                quantity=qty,
                buy_order_id=incoming.order_id if incoming.side == Side.BUY else best.order_id,
                sell_order_id=best.order_id if incoming.side == Side.BUY else incoming.order_id,
                buy_user=incoming.user_id if incoming.side == Side.BUY else best.user_id,
                sell_user=best.user_id if incoming.side == Side.BUY else incoming.user_id,
                maker_order_id=best.order_id,
                taker_order_id=incoming.order_id,
            )
            trades.append(trade)

            incoming.filled += qty
            best.filled += qty
            self.last_trade_price = trade_price

            if best.remaining == 0:
                best.status = OrderStatus.FILLED
                opposite.pop(0)
            else:
                best.status = OrderStatus.PARTIAL

        return trades

    def _insert_bid(self, order: Order):
        """按 price DESC, time ASC 插入"""
        pos = 0
        for i, o in enumerate(self.bids):
            if order.price > o.price:
                break
            elif order.price == o.price and order.timestamp < o.timestamp:
                break
            pos = i + 1
        self.bids.insert(pos, order)

    def _insert_ask(self, order: Order):
        """按 price ASC, time ASC 插入"""
        pos = 0
        for i, o in enumerate(self.asks):
            if order.price < o.price:
                break
            elif order.price == o.price and order.timestamp < o.timestamp:
                break
            pos = i + 1
        self.asks.insert(pos, order)

    def _aggregate(self, book: list[Order], depth: int) -> list[dict]:
        """聚合同价位的 quantity"""
        levels: list[dict] = []
        prev_price = None
        for o in book:
            if prev_price == o.price and levels:
                levels[-1]["quantity"] += o.remaining
                levels[-1]["orders"] += 1
            else:
                levels.append({"price": o.price, "quantity": o.remaining, "orders": 1})
                prev_price = o.price
            if len(levels) >= depth:
                break
        return levels


# ════════════════════════════════════════════════════════════════
# Matching Engine (管理多个 symbol 的 order book)
# ════════════════════════════════════════════════════════════════


class MatchingEngine:
    """
    多标的撮合引擎。

    用法:
        engine = MatchingEngine()
        result = engine.place_order("user1", "600519.SH", Side.BUY, 100.0, 10)
        depth = engine.get_depth("600519.SH")
        engine.cancel_order("600519.SH", order_id, "user1")
    """

    def __init__(self, db_path: Optional[Path] = None):
        self._books: dict[str, OrderBook] = {}
        self._order_id_gen = itertools.count(1)
        self._trade_id_gen = itertools.count(1)
        self._lock = threading.Lock()
        self._all_orders: dict[int, Order] = {}
        self._all_trades: list[Trade] = []

        # 可选: SQLite 持久化
        self._db_path = db_path
        if db_path:
            self._init_db()

    def _get_book(self, symbol: str) -> OrderBook:
        if symbol not in self._books:
            with self._lock:
                if symbol not in self._books:
                    self._books[symbol] = OrderBook(symbol)
        return self._books[symbol]

    def place_order(
        self,
        user_id: str,
        symbol: str,
        side: Side,
        price: Optional[float],
        quantity: int,
    ) -> OrderResult:
        """
        下单。

        Args:
            user_id: 用户 ID
            symbol: 标的代码
            side: BUY / SELL
            price: 限价。None = 市价单
            quantity: 数量(正整数)

        Returns:
            OrderResult 含成交信息
        """
        if quantity <= 0:
            return OrderResult(
                order_id=0, status=OrderStatus.CANCELED,
                rejected="quantity must be positive",
            )

        book = self._get_book(symbol)
        is_market = price is None

        # 市价单: 用对手盘 best price
        if is_market:
            opposite = book.asks if side == Side.BUY else book.bids
            if not opposite:
                return OrderResult(
                    order_id=0, status=OrderStatus.CANCELED,
                    rejected="no_liquidity",
                )
            price = 0.0  # 市价标记

        order_id = next(self._order_id_gen)
        order = Order(
            order_id=order_id,
            user_id=user_id,
            symbol=symbol,
            side=side,
            price=price,
            quantity=quantity,
            is_market=is_market,
        )
        self._all_orders[order_id] = order

        result = book.place(order)

        # 分配 trade_id
        for t in result.trades:
            t.trade_id = next(self._trade_id_gen)
            self._all_trades.append(t)

        # 持久化
        if self._db_path:
            self._persist_order(order)
            for t in result.trades:
                self._persist_trade(t)

        logger.info(
            f"[MatchingEngine] {side.value} {symbol} qty={quantity} "
            f"price={price} → filled={result.filled} trades={len(result.trades)} "
            f"avg={result.avg_price} fee={result.total_fee}"
        )
        return result

    def cancel_order(self, symbol: str, order_id: int, user_id: str) -> bool:
        book = self._get_book(symbol)
        return book.cancel(order_id, user_id)

    def get_depth(self, symbol: str, depth: int = 5) -> dict:
        return self._get_book(symbol).snapshot(depth)

    def get_trades(self, symbol: str = "", limit: int = 50) -> list[dict]:
        trades = self._all_trades
        if symbol:
            trades = [t for t in trades if t.symbol == symbol]
        return [
            {
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "price": t.price,
                "quantity": t.quantity,
                "buy_user": t.buy_user,
                "sell_user": t.sell_user,
                "timestamp": t.timestamp,
            }
            for t in trades[-limit:]
        ]

    # ── SQLite 持久化 ──

    def _init_db(self):
        conn = sqlite3.connect(str(self._db_path))
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id INTEGER PRIMARY KEY,
                user_id TEXT, symbol TEXT, side TEXT,
                price REAL, quantity INTEGER, filled INTEGER,
                status TEXT, timestamp REAL, is_market INTEGER
            );
            CREATE TABLE IF NOT EXISTS trades (
                trade_id INTEGER PRIMARY KEY,
                symbol TEXT, price REAL, quantity INTEGER,
                buy_order_id INTEGER, sell_order_id INTEGER,
                buy_user TEXT, sell_user TEXT,
                maker_order_id INTEGER, taker_order_id INTEGER,
                timestamp REAL
            );
        """)
        conn.commit()
        conn.close()

    def _persist_order(self, o: Order):
        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.execute(
                "INSERT OR REPLACE INTO orders VALUES (?,?,?,?,?,?,?,?,?,?)",
                (o.order_id, o.user_id, o.symbol, o.side.value,
                 o.price, o.quantity, o.filled, o.status.value,
                 o.timestamp, int(o.is_market)),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Order persist failed: {e}")

    def _persist_trade(self, t: Trade):
        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.execute(
                "INSERT OR REPLACE INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (t.trade_id, t.symbol, t.price, t.quantity,
                 t.buy_order_id, t.sell_order_id,
                 t.buy_user, t.sell_user,
                 t.maker_order_id, t.taker_order_id, t.timestamp),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Trade persist failed: {e}")
