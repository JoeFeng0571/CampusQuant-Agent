"""
api/mock_exchange.py — 虚拟撮合引擎

维护一个全局内存账户，提供：
  - place_order(symbol, action, quantity) → OrderResult
  - get_account_snapshot()                → AccountSnapshot

设计原则：
  - 纯内存，无持久化（重启即重置）
  - action=BUY  → 扣减可用资金，增加持仓
  - action=SELL → 扣减持仓，增加可用资金
  - 价格来源：get_spot_price_raw()，失败时抛 RuntimeError
  - TradeOrder.simulated 始终为 True
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

# ════════════════════════════════════════════════════════════════
# 数据模型
# ════════════════════════════════════════════════════════════════

@dataclass
class Position:
    symbol:     str
    name:       str
    quantity:   float          # 持仓股数/份
    avg_cost:   float          # 平均持仓成本
    market_type: str = "UNKNOWN"


@dataclass
class OrderResult:
    success:       bool
    symbol:        str
    action:        str           # BUY / SELL
    quantity:      float
    exec_price:    float         # 实际成交价
    is_spot_price: bool          # True=实时 False=日线收盘降级
    amount:        float         # 成交金额（正值）
    fee:           float         # 手续费（0.03% 模拟）
    cash_before:   float
    cash_after:    float
    timestamp:     str
    error:         Optional[str] = None


# ════════════════════════════════════════════════════════════════
# 全局虚拟账户
# ════════════════════════════════════════════════════════════════

_INITIAL_CASH = 100_000.0       # 初始资金 10 万元

class VirtualAccount:
    """线程安全的虚拟账户"""

    def __init__(self, initial_cash: float = _INITIAL_CASH):
        self._lock      = threading.Lock()
        self.cash       = initial_cash          # 可用资金
        self.initial    = initial_cash
        self.positions: dict[str, Position] = {}  # symbol → Position
        self.orders:    list[OrderResult]    = []  # 历史成交记录

    # ── 下单撮合 ───────────────────────────────────────────────
    def place_order(
        self,
        symbol:    str,
        action:    str,      # "BUY" | "SELL"
        quantity:  float,
        name:      str = "",
        market_type: str = "UNKNOWN",
    ) -> OrderResult:
        """
        撮合一笔模拟订单。
        价格由外部注入（已经查询好），保证线程安全。
        """
        action = action.upper()
        if action not in ("BUY", "SELL"):
            raise ValueError(f"action 必须是 BUY 或 SELL，收到: {action}")
        if quantity <= 0:
            raise ValueError("quantity 必须 > 0")

        # 获取实时价格（在锁外调用，避免长时间持锁）
        from tools.market_data import get_spot_price_raw
        spot = get_spot_price_raw(symbol)
        exec_price    = spot.get("price") or 0.0
        is_spot_price = not spot.get("is_fallback", True)

        if not exec_price or exec_price <= 0:
            return OrderResult(
                success=False, symbol=symbol, action=action,
                quantity=quantity, exec_price=0.0, is_spot_price=False,
                amount=0.0, fee=0.0,
                cash_before=self.cash, cash_after=self.cash,
                timestamp=datetime.now(timezone.utc).isoformat(),
                error="行情获取失败，无法撮合",
            )

        amount = round(exec_price * quantity, 4)
        fee    = round(amount * 0.0003, 4)   # 万三手续费

        with self._lock:
            cash_before = self.cash
            ts = datetime.now(timezone.utc).isoformat()

            if action == "BUY":
                total_cost = amount + fee
                if total_cost > self.cash:
                    return OrderResult(
                        success=False, symbol=symbol, action=action,
                        quantity=quantity, exec_price=exec_price,
                        is_spot_price=is_spot_price,
                        amount=amount, fee=fee,
                        cash_before=cash_before, cash_after=self.cash,
                        timestamp=ts,
                        error=f"可用资金不足（需 {total_cost:.2f}，可用 {self.cash:.2f}）",
                    )
                self.cash -= total_cost
                # 更新持仓（加权平均成本）
                pos = self.positions.get(symbol)
                if pos:
                    total_qty  = pos.quantity + quantity
                    pos.avg_cost = (pos.avg_cost * pos.quantity + exec_price * quantity) / total_qty
                    pos.quantity = total_qty
                else:
                    self.positions[symbol] = Position(
                        symbol=symbol, name=name or symbol,
                        quantity=quantity, avg_cost=exec_price,
                        market_type=market_type,
                    )

            else:  # SELL
                pos = self.positions.get(symbol)
                if not pos or pos.quantity < quantity:
                    held = pos.quantity if pos else 0
                    return OrderResult(
                        success=False, symbol=symbol, action=action,
                        quantity=quantity, exec_price=exec_price,
                        is_spot_price=is_spot_price,
                        amount=amount, fee=fee,
                        cash_before=cash_before, cash_after=self.cash,
                        timestamp=ts,
                        error=f"持仓不足（需 {quantity}，持有 {held:.2f}）",
                    )
                pos.quantity -= quantity
                if pos.quantity < 1e-6:
                    del self.positions[symbol]
                self.cash += (amount - fee)

            result = OrderResult(
                success=True, symbol=symbol, action=action,
                quantity=quantity, exec_price=exec_price,
                is_spot_price=is_spot_price,
                amount=amount, fee=fee,
                cash_before=cash_before, cash_after=self.cash,
                timestamp=ts,
            )
            self.orders.append(result)
            logger.info(
                f"[MockExchange] {action} {quantity}×{symbol} @{exec_price} "
                f"amount={amount:.2f} fee={fee:.4f} cash={self.cash:.2f}"
            )
            return result

    # ── 账户快照 ───────────────────────────────────────────────
    def snapshot(self) -> dict:
        """
        返回账户快照：持仓 + 实时估值 + 资金汇总。
        注意：此方法不获取实时价格（调用方负责注入），
        返回使用 avg_cost 作为 current_price 的静态快照，
        由 server.py 端点再并发注入实时价格。
        """
        with self._lock:
            positions = [
                {
                    "symbol":    p.symbol,
                    "name":      p.name,
                    "quantity":  p.quantity,
                    "avg_cost":  p.avg_cost,
                    "market_type": p.market_type,
                }
                for p in self.positions.values()
            ]
            return {
                "cash":       round(self.cash, 2),
                "initial":    round(self.initial, 2),
                "positions":  positions,
                "order_count": len(self.orders),
            }


# ── 模块级单例 ────────────────────────────────────────────────
_ACCOUNT = VirtualAccount()


def get_account() -> VirtualAccount:
    """返回全局虚拟账户单例"""
    return _ACCOUNT
