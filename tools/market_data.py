"""
tools/market_data.py — 市场数据与技术指标工具

将原有 DataLoader / DataAgent 逻辑封装为 LangChain @tool，
供 LangGraph 节点直接调用，支持工具调用追踪与日志记录。

工具列表:
  - get_market_data(symbol)             : 获取多市场行情数据
  - calculate_technical_indicators(data): 计算 MACD/RSI/KDJ/BOLL 等指标
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
from langchain_core.tools import tool
from loguru import logger

# 复用已有的数据加载与市场分类逻辑
from config import config
from utils.market_classifier import MarketClassifier, MarketType


# ════════════════════════════════════════════════════════════════
# 内部辅助：延迟初始化 DataLoader（避免 import 时连接 Binance）
# ════════════════════════════════════════════════════════════════
_data_loader: Optional[Any] = None


def _get_loader():
    global _data_loader
    if _data_loader is None:
        from utils.data_loader import DataLoader
        _data_loader = DataLoader()
    return _data_loader


# ════════════════════════════════════════════════════════════════
# @tool  1 — get_market_data
# ════════════════════════════════════════════════════════════════

@tool
def get_market_data(symbol: str, days: int = 180) -> str:
    """
    获取指定交易标的的历史行情数据（支持 A股/港股/美股/加密货币）。

    Args:
        symbol: 交易标的代码。示例:
                - A股:    "600519.SH"（贵州茅台）
                - 港股:   "00700.HK"（腾讯）
                - 美股:   "AAPL"
                - 加密:   "BTC/USDT"
        days:   获取最近 N 天的历史数据，默认 180 天

    Returns:
        JSON 字符串，包含行情摘要 + 最新价格数据
    """
    logger.info(f"[Tool] get_market_data: {symbol}, days={days}")

    try:
        loader = _get_loader()
        market_type, _ = MarketClassifier.classify(symbol)

        # 获取历史 K 线
        df = loader.get_historical_data(symbol, days=days)

        if df is None or df.empty:
            return json.dumps({"status": "error", "error": f"无法获取 {symbol} 的数据"})

        latest = df.iloc[-1]
        prev   = df.iloc[-2] if len(df) > 1 else df.iloc[-1]

        # 统计摘要
        price_change_pct = (
            (latest["close"] - prev["close"]) / prev["close"] * 100
            if prev["close"] != 0 else 0.0
        )
        avg_volume_10d = float(df["volume"].tail(10).mean()) if "volume" in df.columns else 0.0

        result = {
            "status": "success",
            "symbol": symbol,
            "market_type": market_type.value,
            # 最新价格
            "latest_price": float(latest.get("close", 0)),
            "open":   float(latest.get("open",  0)),
            "high":   float(latest.get("high",  0)),
            "low":    float(latest.get("low",   0)),
            "volume": float(latest.get("volume", 0)),
            "price_change_pct": round(price_change_pct, 2),
            # 区间统计
            "period_high": float(df["high"].max()),
            "period_low":  float(df["low"].min()),
            "avg_volume_10d": round(avg_volume_10d, 0),
            "data_points": len(df),
            # 传递原始 DataFrame 序列化数据供技术指标工具使用
            "_ohlcv_json": df[["open","high","low","close","volume"]].tail(300).to_json(
                orient="records", date_format="iso"
            ),
        }

        logger.info(f"[Tool] get_market_data 成功: {symbol} latest={result['latest_price']}")
        return json.dumps(result, ensure_ascii=False)

    except Exception as e:
        logger.error(f"[Tool] get_market_data 失败: {e}")
        return json.dumps({"status": "error", "error": str(e), "symbol": symbol})


# ════════════════════════════════════════════════════════════════
# @tool  2 — calculate_technical_indicators
# ════════════════════════════════════════════════════════════════

@tool
def calculate_technical_indicators(market_data_json: str) -> str:
    """
    根据行情数据计算主流技术指标（MACD / RSI / KDJ / 布林带 / ATR / MA）。

    Args:
        market_data_json: get_market_data 工具返回的 JSON 字符串

    Returns:
        JSON 字符串，包含各技术指标的最新值与信号判断
    """
    logger.info("[Tool] calculate_technical_indicators 开始")

    try:
        data = json.loads(market_data_json)

        if data.get("status") == "error":
            return market_data_json  # 传递错误信息

        ohlcv_raw = data.get("_ohlcv_json")
        if not ohlcv_raw:
            return json.dumps({"status": "error", "error": "缺少 OHLCV 数据"})

        df = pd.DataFrame(json.loads(ohlcv_raw))
        df.columns = [c.lower() for c in df.columns]

        close  = df["close"].astype(float)
        high   = df["high"].astype(float)
        low    = df["low"].astype(float)
        volume = df["volume"].astype(float) if "volume" in df.columns else pd.Series([0.0]*len(df))

        indicators: Dict[str, Any] = {}

        # ── 移动平均线 ────────────────────────────────────────
        for period in [5, 10, 20, 60]:
            if len(close) >= period:
                ma_val = float(close.rolling(period).mean().iloc[-1])
                indicators[f"MA{period}"] = round(ma_val, 4)

        current_price = float(close.iloc[-1])
        ma20 = indicators.get("MA20")
        ma60 = indicators.get("MA60")

        indicators["above_ma20"] = bool(ma20 and current_price > ma20)
        indicators["above_ma60"] = bool(ma60 and current_price > ma60)
        indicators["ma_bullish_alignment"] = bool(
            ma20 and ma60 and ma20 > ma60
        )

        # ── MACD (12, 26, 9) ─────────────────────────────────
        if len(close) >= 35:
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd_line   = ema12 - ema26
            signal_line = macd_line.ewm(span=9, adjust=False).mean()
            histogram   = macd_line - signal_line

            indicators["MACD"]        = round(float(macd_line.iloc[-1]),  4)
            indicators["MACD_signal"] = round(float(signal_line.iloc[-1]), 4)
            indicators["MACD_hist"]   = round(float(histogram.iloc[-1]),   4)
            indicators["MACD_golden_cross"] = bool(
                macd_line.iloc[-1] > signal_line.iloc[-1] and
                macd_line.iloc[-2] <= signal_line.iloc[-2]
            )
            indicators["MACD_bullish"] = bool(macd_line.iloc[-1] > signal_line.iloc[-1])

        # ── RSI (14) ──────────────────────────────────────────
        if len(close) >= 15:
            delta    = close.diff()
            gain     = delta.clip(lower=0).rolling(14).mean()
            loss     = (-delta.clip(upper=0)).rolling(14).mean()
            rs       = gain / loss.replace(0, np.nan)
            rsi_vals = 100 - (100 / (1 + rs))
            rsi      = float(rsi_vals.iloc[-1])
            indicators["RSI14"] = round(rsi, 2)
            indicators["RSI_overbought"] = bool(rsi > 70)
            indicators["RSI_oversold"]   = bool(rsi < 30)

        # ── 布林带 (20, 2σ) ───────────────────────────────────
        if len(close) >= 20:
            sma20 = close.rolling(20).mean()
            std20 = close.rolling(20).std()
            upper = sma20 + 2 * std20
            lower = sma20 - 2 * std20
            indicators["BOLL_upper"]  = round(float(upper.iloc[-1]),  4)
            indicators["BOLL_mid"]    = round(float(sma20.iloc[-1]),  4)
            indicators["BOLL_lower"]  = round(float(lower.iloc[-1]),  4)
            boll_pct = float(
                (current_price - lower.iloc[-1]) /
                (upper.iloc[-1] - lower.iloc[-1] + 1e-9)
            )
            indicators["BOLL_pct_B"] = round(boll_pct, 4)   # 0-1, >0.8 偏贵
            indicators["near_boll_upper"] = bool(boll_pct > 0.85)
            indicators["near_boll_lower"] = bool(boll_pct < 0.15)

        # ── ATR (14) ──────────────────────────────────────────
        if len(close) >= 15:
            tr = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low  - close.shift()).abs(),
            ], axis=1).max(axis=1)
            atr = float(tr.rolling(14).mean().iloc[-1])
            indicators["ATR14"]     = round(atr, 4)
            indicators["ATR_pct"]   = round(atr / current_price * 100, 2)

        # ── 量比（最新成交量 / 10日均量）─────────────────────
        if len(volume) >= 10 and float(volume.tail(10).mean()) > 0:
            vol_ratio = float(volume.iloc[-1]) / float(volume.tail(10).mean())
            indicators["volume_ratio"] = round(vol_ratio, 2)
            indicators["high_volume"]  = bool(vol_ratio > 1.5)

        # ── 综合信号评分 ──────────────────────────────────────
        bull_signals = sum([
            indicators.get("above_ma20", False),
            indicators.get("above_ma60", False),
            indicators.get("ma_bullish_alignment", False),
            indicators.get("MACD_bullish", False),
            indicators.get("MACD_golden_cross", False),
            indicators.get("RSI_oversold", False),
            indicators.get("near_boll_lower", False),
            indicators.get("high_volume", False),
        ])
        bear_signals = sum([
            not indicators.get("above_ma20", True),
            not indicators.get("above_ma60", True),
            indicators.get("RSI_overbought", False),
            indicators.get("near_boll_upper", False),
        ])

        indicators["bull_signal_count"] = bull_signals
        indicators["bear_signal_count"] = bear_signals

        if bull_signals >= 5:
            tech_signal = "STRONG_BUY"
        elif bull_signals >= 3:
            tech_signal = "BUY"
        elif bear_signals >= 3:
            tech_signal = "SELL"
        elif bear_signals >= 2:
            tech_signal = "WEAK_SELL"
        else:
            tech_signal = "HOLD"

        indicators["tech_signal"] = tech_signal

        result = {
            "status":  "success",
            "symbol":  data.get("symbol"),
            "current_price": current_price,
            "indicators": indicators,
        }

        logger.info(f"[Tool] 技术指标计算完成: {data.get('symbol')} signal={tech_signal}")
        return json.dumps(result, ensure_ascii=False)

    except Exception as e:
        logger.error(f"[Tool] calculate_technical_indicators 失败: {e}")
        return json.dumps({"status": "error", "error": str(e)})
