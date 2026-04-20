"""
bench/backtest/market_rules.py — 三市场费用与交易规则

每个市场独立封装：
    - 佣金 / 印花税 / 规费 / 过户费
    - T+N 约束（A 股 T+1，港/美 T+0）
    - 最小交易单位
    - 涨跌幅限制（回测时用作撮合失败判断，非必须）

**不涉及** 撮合层面的细节（盘口、连续竞价等），仅覆盖"单笔订单净成本 + 能否交割"。

引用：
    - 上交所/深交所规则（2023 费率）：佣金普遍 0.025%、印花税卖方 0.1%、
      过户费双边 0.001%（上交所）
    - 港交所（2023）：佣金约 0.025%、印花税双边 0.1%、交易征费 0.0027%
    - 美股主流券商零佣金，仅 SEC fee（卖方 0.00278%）+ FINRA TAF
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MarketType = Literal["A_STOCK", "HK_STOCK", "US_STOCK"]


# ══════════════════════════════════════════════════════════════
# 符号 → 市场分类
# ══════════════════════════════════════════════════════════════

def classify_market(symbol: str) -> MarketType:
    """根据 symbol 推断市场类型。

    规则：
        - 结尾 .HK / .hk             → HK_STOCK
        - 全数字 6 位（含 0/3/6 开头）→ A_STOCK
        - 其他（字母为主）            → US_STOCK
    """
    s = symbol.strip().upper()
    if s.endswith(".HK"):
        return "HK_STOCK"
    # 去掉 .SH / .SZ 后缀也视为 A 股
    core = s.split(".")[0]
    if core.isdigit() and len(core) == 6:
        return "A_STOCK"
    return "US_STOCK"


# ══════════════════════════════════════════════════════════════
# 费用模型
# ══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class CostModel:
    """单市场费用模型。

    Attributes:
        commission_rate: 佣金比例（双边）
        stamp_duty_rate: 印花税（卖方或双边，由 stamp_duty_both_sides 决定）
        stamp_duty_both_sides: True = 买卖都收（港股），False = 仅卖方（A 股）
        transfer_fee_rate: 过户费（双边），0 表示无
        regulatory_fee_rate: 规费/SEC/交易征费（按 side_rule 决定仅卖或双边）
        regulatory_fee_sell_only: True = 仅卖方收 (美 SEC)，False = 双边 (港交所征费)
        min_commission: 最低单笔佣金（人民币/港币/美元）
        slippage_rate: 滑点（双边），按成交金额百分比
        min_lot_size: 最小交易手数（如 A 股 100 股，美股 1 股）
        t_plus: T+N 交割约束，A 股=1，港/美=0
    """
    market: MarketType
    commission_rate: float
    stamp_duty_rate: float = 0.0
    stamp_duty_both_sides: bool = False
    transfer_fee_rate: float = 0.0
    regulatory_fee_rate: float = 0.0
    regulatory_fee_sell_only: bool = False
    min_commission: float = 0.0
    slippage_rate: float = 0.0005
    min_lot_size: int = 1
    t_plus: int = 0

    def compute_cost(self, notional: float, side: Literal["buy", "sell"]) -> float:
        """计算单笔订单的总成本（不含买入金额本身，仅摩擦）。

        Args:
            notional: 成交金额（数量 × 价格）
            side: buy / sell

        Returns:
            总成本（人民币 / 港币 / 美元，与 notional 同币种）
        """
        if notional <= 0:
            return 0.0

        cost = 0.0
        # 佣金（双边）
        cost += max(notional * self.commission_rate, self.min_commission)
        # 印花税
        if self.stamp_duty_both_sides or side == "sell":
            cost += notional * self.stamp_duty_rate
        # 过户费（双边）
        cost += notional * self.transfer_fee_rate
        # 规费
        if (not self.regulatory_fee_sell_only) or side == "sell":
            cost += notional * self.regulatory_fee_rate
        # 滑点
        cost += notional * self.slippage_rate
        return cost

    def round_quantity(self, quantity: float) -> int:
        """把数量向下取整到最小单位。"""
        if self.min_lot_size <= 1:
            return int(quantity)
        return int(quantity // self.min_lot_size) * self.min_lot_size


# ══════════════════════════════════════════════════════════════
# 默认参数（可覆盖）
# ══════════════════════════════════════════════════════════════

A_STOCK_COSTS = CostModel(
    market="A_STOCK",
    commission_rate=0.00025,      # 0.025%
    stamp_duty_rate=0.001,        # 0.1%，仅卖方
    stamp_duty_both_sides=False,
    transfer_fee_rate=0.00001,    # 0.001%（上交所双边，深交所近零，取折中）
    min_commission=5.0,           # 主流券商最低 5 元
    slippage_rate=0.0005,
    min_lot_size=100,             # A 股一手 100 股
    t_plus=1,                     # T+1
)

HK_STOCK_COSTS = CostModel(
    market="HK_STOCK",
    commission_rate=0.00025,                # 0.025%
    stamp_duty_rate=0.001,                   # 0.1%，双边
    stamp_duty_both_sides=True,
    regulatory_fee_rate=0.000027,            # 交易征费 0.0027%，双边
    regulatory_fee_sell_only=False,
    min_commission=3.0,                      # 港币 3 元（常见券商）
    slippage_rate=0.0005,
    min_lot_size=100,                        # 简化：各股不同，此处取常见默认
    t_plus=0,
)

US_STOCK_COSTS = CostModel(
    market="US_STOCK",
    commission_rate=0.0,                     # 零佣金
    regulatory_fee_rate=0.0000278,           # SEC fee 0.00278%，仅卖方
    regulatory_fee_sell_only=True,
    min_commission=0.0,
    slippage_rate=0.0003,                    # 美股流动性更好，滑点更低
    min_lot_size=1,                          # 1 股起
    t_plus=0,
)

DEFAULT_COST_MODELS: dict[MarketType, CostModel] = {
    "A_STOCK":  A_STOCK_COSTS,
    "HK_STOCK": HK_STOCK_COSTS,
    "US_STOCK": US_STOCK_COSTS,
}


def get_cost_model(symbol: str) -> CostModel:
    """根据 symbol 自动返回对应的费用模型。"""
    market = classify_market(symbol)
    return DEFAULT_COST_MODELS[market]


# ══════════════════════════════════════════════════════════════
# T+N 约束 helpers
# ══════════════════════════════════════════════════════════════

def can_sell_today(
    buy_date_idx: int,
    today_idx: int,
    t_plus: int,
) -> bool:
    """给定 buy 与 today 的交易日索引，判断是否可卖出。

    A 股 t_plus=1：buy_idx=5 买入，today_idx >= 6 才能卖。
    """
    return today_idx - buy_date_idx >= t_plus
