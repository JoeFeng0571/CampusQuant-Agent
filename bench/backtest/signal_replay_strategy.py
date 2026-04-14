"""
bench/backtest/signal_replay_strategy.py — v2.2 同步回测策略

Phase 2b(§5.4.3): 从 bench/precompute_signals.py 写的 signals parquet 读取,
喂给现有 sync BacktestEngine,零引擎改动。

用法:
    from bench.backtest.signal_replay_strategy import SignalReplayStrategy
    from backtest.engine import BacktestEngine

    strat = SignalReplayStrategy(
        signals_parquet="bench/data/signals_v2_esc.parquet",
        version="v2_esc",
    )
    engine = BacktestEngine(strategy=strat, start="2024-01-01", end="2025-12-31")
    result = engine.run()
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from loguru import logger

from backtest.engine import Signal, Strategy


class SignalReplayStrategy(Strategy):
    """
    从预计算的 signals parquet 读取信号,sync generate() 直接返回。

    signals parquet 的必需列:
      - date (YYYY-MM-DD 或 datetime): rebalance 日期
      - symbol (str): 股票代码
      - action (str): BUY / SELL / HOLD
      - confidence (float): 0.0 ~ 1.0
      - quantity_pct (float): 0 ~ 100 建议仓位百分比

    可选列(仅供审阅/报告):
      - stop_loss / take_profit / reasoning / evidence_citations / version
    """

    def __init__(
        self,
        signals_parquet: str | Path,
        version: str,
        max_positions: int = 10,
        min_confidence: float = 0.60,
        max_weight_per_stock: float = 0.10,
    ):
        self.name = f"signal_replay_{version}"
        self.version = version
        self.max_positions = max_positions
        self.min_confidence = min_confidence
        self.max_weight_per_stock = max_weight_per_stock

        path = Path(signals_parquet)
        if not path.exists():
            raise FileNotFoundError(f"signals parquet not found: {path}")
        self.df = pd.read_parquet(path)

        # 标准化 date 列到 date 类型
        if "date" in self.df.columns:
            self.df["date"] = pd.to_datetime(self.df["date"]).dt.date
        else:
            raise ValueError(f"signals parquet missing 'date' column: {path}")

        # 必需列检查
        required = {"date", "symbol", "action", "confidence", "quantity_pct"}
        missing = required - set(self.df.columns)
        if missing:
            raise ValueError(f"signals parquet missing required columns: {missing}")

        # 预索引月份 → 行,加速重放
        self._month_index: dict[tuple[int, int], pd.DataFrame] = {}
        for (y, m), group in self.df.groupby(
            [self.df["date"].apply(lambda d: d.year),
             self.df["date"].apply(lambda d: d.month)]
        ):
            self._month_index[(y, m)] = group.reset_index(drop=True)

        # 每月只触发一次(first trading day encountered)
        self._fired_months: set[tuple[int, int]] = set()

        logger.info(
            f"[SignalReplayStrategy:{version}] loaded {len(self.df)} signals, "
            f"{len(self._month_index)} months covered"
        )

    def generate(self, t: date, prices: dict[str, float]) -> list[Signal]:
        """
        每月第一个交易日返回当月 signals,其他日子返回空列表。

        t: 当前回测日期 (backtest/engine.py 主循环每日调用)
        prices: 当日收盘价 dict (本策略不依赖,只看 parquet)
        """
        month_key = (t.year, t.month)

        # 跨月边界:当月尚未 fire 过 → 返回信号
        if month_key in self._fired_months:
            return []

        if month_key not in self._month_index:
            # 当月完全没有预计算信号 (可能是 universe 里这些股票都没被选中)
            self._fired_months.add(month_key)
            return []

        monthly_df = self._month_index[month_key]
        self._fired_months.add(month_key)

        signals: list[Signal] = []

        # 把当月所有 action 转成 Signal
        # BUY + conf >= min_confidence → 按 quantity_pct 建仓(上限 max_weight_per_stock)
        # SELL → 清仓
        # HOLD → 不动(不生成 Signal)
        buy_candidates: list[tuple[float, str, float]] = []  # (confidence, symbol, weight)
        sells: list[str] = []

        for row in monthly_df.itertuples():
            action = str(row.action).upper()
            conf = float(row.confidence or 0.0)
            qpct = float(row.quantity_pct or 0.0) / 100.0

            if action == "BUY" and conf >= self.min_confidence and qpct > 0:
                weight = min(qpct, self.max_weight_per_stock)
                buy_candidates.append((conf, str(row.symbol), weight))
            elif action == "SELL":
                sells.append(str(row.symbol))

        # 按 confidence 降序,最多留 max_positions 个 BUY
        buy_candidates.sort(reverse=True, key=lambda x: x[0])
        for _, sym, w in buy_candidates[: self.max_positions]:
            signals.append(Signal(symbol=sym, weight=w))
        for sym in sells:
            signals.append(Signal(symbol=sym, weight=0.0))

        logger.debug(
            f"[SignalReplayStrategy:{self.version}] {t}: "
            f"BUY={len([s for s in signals if s.weight > 0])} "
            f"SELL={len([s for s in signals if s.weight == 0])}"
        )
        return signals
