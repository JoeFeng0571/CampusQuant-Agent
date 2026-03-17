"""
api/mock_exchange.py — 虚拟撮合引擎 (V1.2 三币种版)

三个独立货币账户（互不干扰）：
  - A股  → cash_cnh  初始 100,000 CNH
  - 港股 → cash_hkd  初始 100,000 HKD
  - 美股 → cash_usd  初始  10,000 USD

成交价格策略：最新收盘价（EOD）——
  get_spot_price_raw() 返回最新可用价格，对应已收盘日收盘价。

TradeOrder.simulated 始终为 True，不接入任何真实券商 API。
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
    symbol:      str
    name:        str
    quantity:    float
    avg_cost:    float
    market_type: str = "UNKNOWN"


@dataclass
class OrderResult:
    success:       bool
    symbol:        str
    action:        str           # BUY / SELL
    quantity:      float
    exec_price:    float
    is_spot_price: bool
    amount:        float
    fee:           float
    cash_before:   float
    cash_after:    float
    market_type:   str
    timestamp:     str
    error:         Optional[str] = None


# ════════════════════════════════════════════════════════════════
# 市场 → 币种映射
# ════════════════════════════════════════════════════════════════

_MARKET_CURRENCY: dict[str, str] = {
    "A":       "CNH",
    "HK":      "HKD",
    "US":      "USD",
    "UNKNOWN": "CNH",
}

_INIT_CASH: dict[str, float] = {
    "CNH": 100_000.0,
    "HKD": 100_000.0,
    "USD":  10_000.0,
}

_CURRENCY_LABEL: dict[str, str] = {
    "CNH": "人民币",
    "HKD": "港币",
    "USD": "美元",
}


# ════════════════════════════════════════════════════════════════
# 全局虚拟账户（线程安全）
# ════════════════════════════════════════════════════════════════

class VirtualAccount:
    """
    三货币虚拟账户。
    每个市场独立维护资金池，持仓按 symbol 统一存储（market_type 字段区分）。
    """

    def __init__(self):
        self._lock = threading.Lock()

        # 三币种资金池 { "CNH": float, "HKD": float, "USD": float }
        self.cash:    dict[str, float] = {c: v for c, v in _INIT_CASH.items()}
        self.initial: dict[str, float] = {c: v for c, v in _INIT_CASH.items()}

        self.positions: dict[str, Position] = {}   # symbol → Position
        self.orders:    list[OrderResult]   = []

    # ── 内部：从市场类型解析币种 ──────────────────────────────
    @staticmethod
    def _currency(market_type: str) -> str:
        return _MARKET_CURRENCY.get(market_type.upper(), "CNH")

    # ── 下单撮合 ───────────────────────────────────────────────
    def place_order(
        self,
        symbol:      str,
        action:      str,
        quantity:    float,
        name:        str = "",
        market_type: str = "UNKNOWN",
    ) -> OrderResult:
        action = action.upper()
        if action not in ("BUY", "SELL"):
            raise ValueError(f"action 须为 BUY/SELL，收到: {action}")
        if quantity <= 0:
            raise ValueError("quantity 须 > 0")

        currency = self._currency(market_type)

        # 获取最新收盘价（在锁外，避免长时间持锁）
        from tools.market_data import get_spot_price_raw
        spot = get_spot_price_raw(symbol)
        exec_price    = spot.get("price") or 0.0
        is_spot_price = not spot.get("is_fallback", True)

        if not exec_price or exec_price <= 0:
            return OrderResult(
                success=False, symbol=symbol, action=action,
                quantity=quantity, exec_price=0.0, is_spot_price=False,
                amount=0.0, fee=0.0,
                cash_before=self.cash[currency], cash_after=self.cash[currency],
                market_type=market_type,
                timestamp=datetime.now(timezone.utc).isoformat(),
                error="行情获取失败，无法撮合",
            )

        amount = round(exec_price * quantity, 4)
        fee    = round(amount * 0.0003, 4)   # 万三手续费

        with self._lock:
            cash_before = self.cash[currency]
            ts = datetime.now(timezone.utc).isoformat()

            if action == "BUY":
                total_cost = amount + fee
                if total_cost > self.cash[currency]:
                    return OrderResult(
                        success=False, symbol=symbol, action=action,
                        quantity=quantity, exec_price=exec_price,
                        is_spot_price=is_spot_price,
                        amount=amount, fee=fee,
                        cash_before=cash_before, cash_after=self.cash[currency],
                        market_type=market_type, timestamp=ts,
                        error=(
                            f"[{currency}] 可用资金不足"
                            f"（需 {total_cost:.2f}，可用 {self.cash[currency]:.2f}）"
                        ),
                    )
                self.cash[currency] -= total_cost
                pos = self.positions.get(symbol)
                if pos:
                    total_qty    = pos.quantity + quantity
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
                        cash_before=cash_before, cash_after=self.cash[currency],
                        market_type=market_type, timestamp=ts,
                        error=f"持仓不足（需 {quantity}，持有 {held:.2f}）",
                    )
                pos.quantity -= quantity
                if pos.quantity < 1e-6:
                    del self.positions[symbol]
                self.cash[currency] += (amount - fee)

            result = OrderResult(
                success=True, symbol=symbol, action=action,
                quantity=quantity, exec_price=exec_price,
                is_spot_price=is_spot_price,
                amount=amount, fee=fee,
                cash_before=cash_before, cash_after=self.cash[currency],
                market_type=market_type, timestamp=ts,
            )
            self.orders.append(result)
            logger.info(
                f"[MockExchange] {action} {quantity}×{symbol}@{exec_price} "
                f"[{currency}] amount={amount:.2f} fee={fee:.4f} "
                f"cash={self.cash[currency]:.2f}"
            )
            return result

    # ── 账户快照 ───────────────────────────────────────────────
    def snapshot(self, market_type: Optional[str] = None) -> dict:
        """
        返回账户快照。
        market_type=None → 返回全市场汇总（含三个货币账户余额）
        market_type=A/HK/US → 只返回该市场持仓
        """
        with self._lock:
            all_positions = [
                {
                    "symbol":      p.symbol,
                    "name":        p.name,
                    "quantity":    p.quantity,
                    "avg_cost":    p.avg_cost,
                    "market_type": p.market_type,
                }
                for p in self.positions.values()
            ]

            if market_type:
                mt = market_type.upper()
                filtered = [p for p in all_positions if p["market_type"] == mt]
            else:
                filtered = all_positions

            currency = self._currency(market_type or "UNKNOWN") if market_type else None

            return {
                # 三币种余额（全量）
                "cash_cnh":    round(self.cash["CNH"], 2),
                "cash_hkd":    round(self.cash["HKD"], 2),
                "cash_usd":    round(self.cash["USD"], 2),
                "init_cnh":    round(self.initial["CNH"], 2),
                "init_hkd":    round(self.initial["HKD"], 2),
                "init_usd":    round(self.initial["USD"], 2),
                # 当前市场余额（单市场查询时）
                "cash":        round(self.cash[currency], 2) if currency else None,
                "initial":     round(self.initial[currency], 2) if currency else None,
                "currency":    currency,
                # 持仓
                "positions":   filtered,
                "order_count": len(self.orders),
            }


# ── 模块级单例 ────────────────────────────────────────────────
_ACCOUNT = VirtualAccount()


def get_account() -> VirtualAccount:
    return _ACCOUNT
