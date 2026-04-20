"""
bench/backtest/walk_forward.py — 时间序列 Walk-forward 回测

核心抽象：
    Split(train_start, train_end, test_start, test_end)
        └─ 训练窗用于拟合参数（本模块不假设任何拟合逻辑，预留接口）
        └─ 测试窗用于基于信号重放评估绩效，**测试窗不重叠**

切分模式：
    - rolling:   训练窗长度固定，往后滚动
    - expanding: 训练窗从起点累积，测试窗长度固定

重放规则：
    - 每个 rebalance 日按信号调整目标权重（target weight = quantity_pct / 100）
    - 每只股票按市场规则（A/HK/US）计费：T+N 约束 + 佣金 + 印花税 + 滑点
    - NAV 按日复利更新；基准（等权组合）同步计算用于对比

**零 API 消耗**：输入信号来自 bench/data/signals_*.parquet（已预计算）或
因子合成的输出，本框架纯数值运算。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal, Optional

import numpy as np
import pandas as pd

from bench.backtest.market_rules import (
    CostModel,
    MarketType,
    can_sell_today,
    classify_market,
    get_cost_model,
)


# ══════════════════════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Split:
    """单次训练/测试切分。"""
    train_start: pd.Timestamp
    train_end:   pd.Timestamp
    test_start:  pd.Timestamp
    test_end:    pd.Timestamp

    def __repr__(self) -> str:
        return (f"Split(train=[{self.train_start.date()}..{self.train_end.date()}], "
                f"test=[{self.test_start.date()}..{self.test_end.date()}])")


@dataclass
class WalkForwardResult:
    """单次测试窗的回测结果。"""
    split: Split
    nav:       pd.Series   # 策略净值
    benchmark: pd.Series   # 基准净值（等权）
    metrics:   dict        # 策略指标
    bench_metrics: dict    # 基准指标
    trades:    pd.DataFrame  # 逐笔成交明细


# ══════════════════════════════════════════════════════════════
# 切分器
# ══════════════════════════════════════════════════════════════

def generate_splits(
    dates: pd.DatetimeIndex,
    train_months: int = 12,
    test_months: int = 3,
    mode: Literal["rolling", "expanding"] = "rolling",
    min_train_months: int = 6,
) -> list[Split]:
    """生成 walk-forward 切分序列。

    Args:
        dates: 交易日索引（会转为 DatetimeIndex 并去重）
        train_months: 训练窗长度（月）
        test_months: 测试窗长度（月），**不重叠**
        mode: rolling = 固定长度滑动; expanding = 起点固定终点滑动
        min_train_months: expanding 模式下首窗最小长度

    Returns:
        list[Split]
    """
    dates = pd.DatetimeIndex(dates).unique().sort_values()
    if len(dates) == 0:
        return []

    splits: list[Split] = []
    start = dates[0]
    first_train_end = start + pd.DateOffset(months=train_months if mode == "rolling"
                                             else min_train_months)
    cursor_test_start = first_train_end

    while True:
        test_start = cursor_test_start
        test_end = test_start + pd.DateOffset(months=test_months)
        if test_end > dates[-1] + pd.Timedelta(days=1):
            break

        if mode == "rolling":
            train_end = test_start
            train_start = max(start, train_end - pd.DateOffset(months=train_months))
        else:  # expanding
            train_start = start
            train_end = test_start

        # 只保留至少有交易日的窗
        train_mask = (dates >= train_start) & (dates < train_end)
        test_mask  = (dates >= test_start)  & (dates < test_end)
        if train_mask.sum() == 0 or test_mask.sum() == 0:
            cursor_test_start = test_end
            continue

        splits.append(Split(
            train_start=pd.Timestamp(train_start),
            train_end=pd.Timestamp(train_end),
            test_start=pd.Timestamp(test_start),
            test_end=pd.Timestamp(test_end),
        ))
        cursor_test_start = test_end

    return splits


# ══════════════════════════════════════════════════════════════
# 信号重放 + 多市场成本
# ══════════════════════════════════════════════════════════════

@dataclass
class PortfolioState:
    """简单的账户状态：现金 + 持仓（按 symbol 记录数量和买入日）。"""
    cash: float
    holdings: dict[str, dict] = field(default_factory=dict)
    # holdings[symbol] = {"qty": float, "buy_date_idx": int}

    def market_value(self, prices: dict[str, float]) -> float:
        mv = self.cash
        for sym, pos in self.holdings.items():
            price = prices.get(sym, 0.0)
            mv += pos["qty"] * price
        return mv


def _rebalance_one_day(
    state: PortfolioState,
    target_weights: dict[str, float],
    prices: dict[str, float],
    cost_models: dict[str, CostModel],
    date_idx: int,
    trade_log: list[dict],
    date: pd.Timestamp,
) -> None:
    """把当前持仓调向目标权重。

    约束：
        - 目标仓位之和不得超过 1（不加杠杆）
        - A 股 T+1：刚买入的不能当日卖
        - 小于最小手数的忽略
    """
    total_mv = state.market_value(prices)
    if total_mv <= 0:
        return

    # 先卖再买，保持现金正
    # ── 卖出 ────────────────────────────
    for sym in list(state.holdings.keys()):
        pos = state.holdings[sym]
        price = prices.get(sym)
        if price is None or price <= 0:
            continue

        cm = cost_models[sym]
        # T+N 约束
        if not can_sell_today(pos["buy_date_idx"], date_idx, cm.t_plus):
            continue

        target_w = target_weights.get(sym, 0.0)
        current_val = pos["qty"] * price
        target_val = target_w * total_mv

        if current_val > target_val + 1e-6:
            sell_notional = current_val - target_val
            sell_qty_raw = sell_notional / price
            sell_qty = cm.round_quantity(sell_qty_raw)
            if sell_qty <= 0:
                continue
            sell_qty = min(sell_qty, pos["qty"])
            gross = sell_qty * price
            cost = cm.compute_cost(gross, "sell")
            state.cash += gross - cost
            pos["qty"] -= sell_qty
            trade_log.append({
                "date": date, "symbol": sym, "side": "sell",
                "qty": sell_qty, "price": price,
                "notional": gross, "cost": cost,
            })
            if pos["qty"] <= 0:
                del state.holdings[sym]

    # ── 买入 ────────────────────────────
    for sym, target_w in target_weights.items():
        if target_w <= 0:
            continue
        price = prices.get(sym)
        if price is None or price <= 0:
            continue

        cm = cost_models[sym]
        current_val = state.holdings.get(sym, {"qty": 0})["qty"] * price
        target_val = target_w * total_mv

        if target_val > current_val + 1e-6:
            buy_notional = target_val - current_val
            # 预留成本
            buy_notional = min(buy_notional, state.cash * 0.995)
            buy_qty_raw = buy_notional / price
            buy_qty = cm.round_quantity(buy_qty_raw)
            if buy_qty <= 0:
                continue
            gross = buy_qty * price
            cost = cm.compute_cost(gross, "buy")
            if gross + cost > state.cash:
                continue   # 现金不够
            state.cash -= gross + cost
            if sym in state.holdings:
                old = state.holdings[sym]
                new_qty = old["qty"] + buy_qty
                state.holdings[sym] = {"qty": new_qty, "buy_date_idx": date_idx}
            else:
                state.holdings[sym] = {"qty": buy_qty, "buy_date_idx": date_idx}
            trade_log.append({
                "date": date, "symbol": sym, "side": "buy",
                "qty": buy_qty, "price": price,
                "notional": gross, "cost": cost,
            })


def run_signal_replay(
    signals: pd.DataFrame,
    prices: pd.DataFrame,
    initial_cash: float = 1_000_000.0,
    cost_overrides: Optional[dict[str, CostModel]] = None,
) -> tuple[pd.Series, pd.DataFrame]:
    """在给定时间范围重放信号，返回 (NAV 曲线, 成交记录)。

    Args:
        signals: DataFrame 必须含 date / symbol / action / confidence / quantity_pct
                 (与现有 bench/data/signals_*.parquet 格式一致)
        prices: DataFrame, index=date, columns=symbols, values=close price
        initial_cash: 初始现金
        cost_overrides: 可选按 symbol 指定不同 CostModel（否则按 classify_market 自动）

    Returns:
        nav: pd.Series, index=prices.index, values=账户总资产
        trades: DataFrame, 逐笔成交
    """
    signals = signals.copy()
    signals["date"] = pd.to_datetime(signals["date"])

    # 归一化 prices 索引
    prices = prices.copy()
    prices.index = pd.to_datetime(prices.index)
    prices = prices.sort_index()

    # 每个标的的 cost model
    cost_models: dict[str, CostModel] = {}
    for sym in prices.columns:
        if cost_overrides and sym in cost_overrides:
            cost_models[sym] = cost_overrides[sym]
        else:
            cost_models[sym] = get_cost_model(sym)

    # 信号按 date 分组（每次 rebalance 的目标仓位）
    rebalance_map: dict[pd.Timestamp, dict[str, float]] = {}
    for rb_date, group in signals.groupby("date"):
        # 过滤 HOLD / 非方向性，转为目标权重
        buy_rows = group[group["action"].str.upper() == "BUY"]
        target: dict[str, float] = {}
        for _, row in buy_rows.iterrows():
            sym = row["symbol"]
            weight = float(row["quantity_pct"]) / 100.0
            # 同 date 同 symbol 重复则覆盖
            target[sym] = weight
        # 归一化到 sum <= 1（若超 1，按比例缩放）
        total = sum(target.values())
        if total > 1.0:
            target = {k: v / total for k, v in target.items()}
        rebalance_map[rb_date] = target

    # 重放
    state = PortfolioState(cash=initial_cash)
    nav_values: list[float] = []
    trade_log: list[dict] = []

    for date_idx, dt in enumerate(prices.index):
        # 当日价格 snapshot
        day_prices = {sym: float(prices.at[dt, sym])
                      for sym in prices.columns
                      if not pd.isna(prices.at[dt, sym])}

        # 若当日是 rebalance 日，执行调仓
        rb_target = rebalance_map.get(dt)
        if rb_target is None:
            # 找 ≤ dt 的最近 rebalance 日还未触发的
            for rb_date in sorted(rebalance_map.keys()):
                if rb_date <= dt and rb_date not in getattr(state, "_applied", set()):
                    rb_target = rebalance_map[rb_date]
                    if not hasattr(state, "_applied"):
                        state._applied = set()
                    state._applied.add(rb_date)
                    break
        else:
            if not hasattr(state, "_applied"):
                state._applied = set()
            state._applied.add(dt)

        if rb_target is not None:
            _rebalance_one_day(
                state, rb_target, day_prices, cost_models,
                date_idx, trade_log, dt,
            )

        nav_values.append(state.market_value(day_prices))

    nav = pd.Series(nav_values, index=prices.index, name="strategy_nav")
    trades_df = pd.DataFrame(trade_log) if trade_log else pd.DataFrame(
        columns=["date", "symbol", "side", "qty", "price", "notional", "cost"],
    )
    return nav, trades_df


# ══════════════════════════════════════════════════════════════
# 基准（等权买入持有）
# ══════════════════════════════════════════════════════════════

def equal_weight_buy_and_hold(
    prices: pd.DataFrame,
    initial_cash: float = 1_000_000.0,
) -> pd.Series:
    """等权买入持有：首日均分买入所有标的后不动。

    成本按各自市场扣一次 buy 费用。后续随价格波动。
    """
    prices = prices.sort_index()
    if prices.empty:
        return pd.Series(dtype=float)

    first_day = prices.index[0]
    n = len([c for c in prices.columns if not pd.isna(prices.at[first_day, c])])
    if n == 0:
        return pd.Series([initial_cash] * len(prices), index=prices.index)

    per_symbol_cash = initial_cash / n
    holdings: dict[str, float] = {}
    total_cost = 0.0

    for sym in prices.columns:
        p0 = prices.at[first_day, sym]
        if pd.isna(p0) or p0 <= 0:
            continue
        cm = get_cost_model(sym)
        qty = cm.round_quantity(per_symbol_cash / p0)
        if qty <= 0:
            continue
        gross = qty * p0
        cost = cm.compute_cost(gross, "buy")
        holdings[sym] = qty
        total_cost += cost

    cash_remaining = initial_cash - sum(
        holdings[s] * prices.at[first_day, s] for s in holdings
    ) - total_cost

    nav = []
    for dt in prices.index:
        mv = cash_remaining
        for sym, qty in holdings.items():
            p = prices.at[dt, sym]
            if not pd.isna(p):
                mv += qty * p
        nav.append(mv)
    return pd.Series(nav, index=prices.index, name="benchmark_nav")


# ══════════════════════════════════════════════════════════════
# 指标扩展（交易级 win rate / 盈亏比）
# ══════════════════════════════════════════════════════════════

def trade_level_stats(trades: pd.DataFrame, prices: pd.DataFrame) -> dict:
    """按"配对"的买卖计算交易级胜率和盈亏比。

    简化配对：同 symbol 按时间顺序，先进先出配对（FIFO）。
    """
    if trades.empty:
        return {"trade_count": 0, "win_rate": 0.0, "profit_loss_ratio": 0.0}

    pnl_list: list[float] = []
    # 按 symbol 分组做 FIFO
    for sym, group in trades.groupby("symbol"):
        group = group.sort_values("date")
        buy_queue: list[tuple[float, float]] = []   # (qty, price)
        for _, r in group.iterrows():
            if r["side"] == "buy":
                buy_queue.append((r["qty"], r["price"]))
            else:  # sell
                remaining = r["qty"]
                while remaining > 0 and buy_queue:
                    b_qty, b_price = buy_queue[0]
                    matched = min(remaining, b_qty)
                    pnl_list.append(matched * (r["price"] - b_price))
                    remaining -= matched
                    if matched >= b_qty:
                        buy_queue.pop(0)
                    else:
                        buy_queue[0] = (b_qty - matched, b_price)

    if not pnl_list:
        return {"trade_count": 0, "win_rate": 0.0, "profit_loss_ratio": 0.0}

    wins = [p for p in pnl_list if p > 0]
    losses = [p for p in pnl_list if p < 0]
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(abs(np.mean(losses))) if losses else 0.0

    return {
        "trade_count": len(pnl_list),
        "win_rate": float(len(wins) / len(pnl_list)),
        "profit_loss_ratio": float(avg_win / avg_loss) if avg_loss > 0 else float("inf"),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
    }


# ══════════════════════════════════════════════════════════════
# 完整 walk-forward 入口
# ══════════════════════════════════════════════════════════════

def run_walk_forward(
    signals: pd.DataFrame,
    prices: pd.DataFrame,
    train_months: int = 12,
    test_months: int = 3,
    mode: Literal["rolling", "expanding"] = "rolling",
    initial_cash: float = 1_000_000.0,
) -> tuple[list[WalkForwardResult], pd.Series, pd.Series]:
    """完整的 walk-forward 回测。

    当前版本**不在训练窗拟合任何参数**（信号已是外生输入），仅做测试窗重放。
    训练窗在框架里预留，供后续加入"训练期内做因子权重拟合/Platt 校准等"。

    Returns:
        - per-split results
        - 拼接后的策略 NAV（测试窗串联）
        - 拼接后的基准 NAV（测试窗串联）
    """
    from backtest.metrics import compute_all

    splits = generate_splits(prices.index, train_months, test_months, mode)

    results: list[WalkForwardResult] = []
    concat_strategy: list[pd.Series] = []
    concat_bench:    list[pd.Series] = []
    cash = initial_cash
    bench_cash = initial_cash

    for sp in splits:
        test_mask = (prices.index >= sp.test_start) & (prices.index < sp.test_end)
        test_prices = prices.loc[test_mask]
        if test_prices.empty:
            continue
        test_signals = signals[
            (pd.to_datetime(signals["date"]) >= sp.test_start) &
            (pd.to_datetime(signals["date"]) <  sp.test_end)
        ]

        nav, trades = run_signal_replay(
            test_signals, test_prices, initial_cash=cash,
        )
        bench = equal_weight_buy_and_hold(test_prices, initial_cash=bench_cash)

        strat_metrics = compute_all(nav)
        bench_metrics = compute_all(bench)

        results.append(WalkForwardResult(
            split=sp, nav=nav, benchmark=bench,
            metrics=strat_metrics, bench_metrics=bench_metrics,
            trades=trades,
        ))

        # 复利到下一窗
        cash       = float(nav.iloc[-1])
        bench_cash = float(bench.iloc[-1])

        concat_strategy.append(nav)
        concat_bench.append(bench)

    if concat_strategy:
        full_nav = pd.concat(concat_strategy).sort_index()
        full_nav = full_nav[~full_nav.index.duplicated(keep="last")]
    else:
        full_nav = pd.Series(dtype=float)
    if concat_bench:
        full_bench = pd.concat(concat_bench).sort_index()
        full_bench = full_bench[~full_bench.index.duplicated(keep="last")]
    else:
        full_bench = pd.Series(dtype=float)

    return results, full_nav, full_bench
