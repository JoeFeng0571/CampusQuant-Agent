"""
tools/market_data.py — 市场数据与技术指标工具

将原有 DataLoader / DataAgent 逻辑封装为 LangChain @tool，
供 LangGraph 节点直接调用，支持工具调用追踪与日志记录。

工具列表:
  - get_market_data(symbol)             : 获取多市场行情数据（OHLCV）
  - calculate_technical_indicators(data): 计算 MACD/RSI/KDJ/BOLL 等指标
  - get_fundamental_data(symbol)        : 获取真实基本面数据（PE/PB/ROE/EPS 等）
  - get_stock_news(symbol)              : 获取标的最新新闻资讯（东方财富/yfinance）
"""
from __future__ import annotations

import json
import threading
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
from langchain_core.tools import tool
from loguru import logger

# 复用已有的数据加载与市场分类逻辑
from config import config
from utils.market_classifier import MarketClassifier, MarketType

# 数据获取超时上限（秒）
# 超过此时间直接放弃，返回兜底 JSON，LangGraph 继续流转
_FETCH_TIMEOUT = 12


# ════════════════════════════════════════════════════════════════
# 内部辅助：延迟初始化 DataLoader
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
    获取指定交易标的的历史行情数据（支持 A股/港股/美股）。

    Args:
        symbol: 交易标的代码。示例:
                - A股:  "600519.SH"（贵州茅台）
                - 港股: "00700.HK"（腾讯）
                - 美股: "AAPL"
        days:   获取最近 N 天的历史数据，默认 180 天

    Returns:
        JSON 字符串，包含行情摘要 + 最新价格数据；
        超时或网络阻塞时返回 {"status":"error","error":"数据获取超时或网络阻塞"}
    """
    logger.info(f"[Tool] get_market_data: {symbol}, days={days}")

    try:
        loader = _get_loader()
        market_type, _ = MarketClassifier.classify(symbol)

        # ── 带熔断的数据获取 ──────────────────────────────────────────
        # 问题根因：akshare/yfinance 均为同步阻塞调用，在 TUN/代理网络下
        # 可能因 socket 死锁或代理握手失败导致无限期挂起，阻塞整个事件循环。
        # 方案：Daemon Thread + threading.Event 超时控制：
        #   - daemon=True 保证超时后不阻塞进程退出
        #   - event.wait(timeout) 非阻塞等待，超时后立即返回兜底数据
        #   - 放弃的后台线程待 OS TCP 超时后自然结束，不产生资源泄漏
        _result:    list = [None]   # [DataFrame]
        _exc:       list = [None]   # [Exception]
        _done = threading.Event()

        def _fetch():
            try:
                _result[0] = loader.get_historical_data(symbol, days=days)
            except Exception as _e:
                _exc[0] = _e
            finally:
                _done.set()

        _t = threading.Thread(target=_fetch, daemon=True, name=f"data-fetch-{symbol}")
        _t.start()

        if not _done.wait(timeout=_FETCH_TIMEOUT):
            # ── 熔断：超时，立即放弃等待 ─────────────────────────────
            logger.error(
                f"[Tool] get_market_data 超时 (>{_FETCH_TIMEOUT}s): {symbol} — "
                f"疑似网络阻塞（akshare/yfinance 无响应），已触发熔断"
            )
            return json.dumps({
                "status": "error",
                "error":  "数据获取超时或网络阻塞",
                "symbol": symbol,
            }, ensure_ascii=False)

        if _exc[0] is not None:
            raise _exc[0]

        df = _result[0]

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


# ════════════════════════════════════════════════════════════════
# @tool  3 — get_fundamental_data
# 【审计修复 Agent-P0-1】为 fundamental_node 提供真实基本面数据
# ════════════════════════════════════════════════════════════════

@tool
def get_fundamental_data(symbol: str) -> str:
    """
    获取标的真实基本面财务数据（PE/PB/ROE/EPS/市值/行业等）。

    Args:
        symbol: 交易标的代码。示例:
                - A股:  "600519.SH"（贵州茅台）
                - 港股: "00700.HK"（腾讯，返回 partial 状态）
                - 美股: "AAPL"

    Returns:
        JSON 字符串，包含基本面指标；无法获取时返回 partial/error 状态。

    数据来源:
        - A股: akshare stock_individual_info_em（东方财富个股信息）
        - 美股: yfinance Ticker.info（含 PE/PB/ROE/EPS/sector 等）
        - 港股: 暂无自动获取，返回 partial 状态提示
    """
    logger.info(f"[Tool] get_fundamental_data: {symbol}")

    try:
        market_type, _ = MarketClassifier.classify(symbol)
        code = symbol.split(".")[0]   # "600519.SH" → "600519"

        _result: list = [None]
        _exc:    list = [None]
        _done = threading.Event()

        if market_type == MarketType.A_STOCK:
            def _fetch():
                try:
                    import akshare as ak
                    df = ak.stock_individual_info_em(symbol=code)
                    # 转为 {字段名: 值} 字典
                    info = {str(row.iloc[0]): row.iloc[1] for _, row in df.iterrows()}
                    _result[0] = {
                        "status":  "success",
                        "symbol":  symbol,
                        "source":  "akshare/eastmoney",
                        "market":  "A_STOCK",
                        "data":    info,
                    }
                except Exception as _e:
                    _exc[0] = _e
                finally:
                    _done.set()

        elif market_type == MarketType.US_STOCK:
            def _fetch():
                try:
                    import yfinance as yf
                    info = yf.Ticker(symbol).info
                    _result[0] = {
                        "status": "success",
                        "symbol": symbol,
                        "source": "yfinance",
                        "market": "US_STOCK",
                        "data": {
                            "PE(TTM)":       info.get("trailingPE"),
                            "PE(Forward)":   info.get("forwardPE"),
                            "PB":            info.get("priceToBook"),
                            "PS(TTM)":       info.get("priceToSalesTrailing12Months"),
                            "ROE":           info.get("returnOnEquity"),
                            "ROA":           info.get("returnOnAssets"),
                            "EPS(TTM)":      info.get("trailingEps"),
                            "EPS(Forward)":  info.get("forwardEps"),
                            "营收增速YoY":    info.get("revenueGrowth"),
                            "净利润率":       info.get("profitMargins"),
                            "毛利率":         info.get("grossMargins"),
                            "市值(亿USD)":    round(info.get("marketCap", 0) / 1e8, 2) if info.get("marketCap") else None,
                            "所属行业":       info.get("sector"),
                            "细分板块":       info.get("industry"),
                            "员工人数":       info.get("fullTimeEmployees"),
                            "52周最高":       info.get("fiftyTwoWeekHigh"),
                            "52周最低":       info.get("fiftyTwoWeekLow"),
                        },
                    }
                except Exception as _e:
                    _exc[0] = _e
                finally:
                    _done.set()

        else:
            # HK_STOCK — 暂无可靠自动获取方式
            logger.info(f"[Tool] get_fundamental_data: 港股 {symbol} 暂不支持")
            return json.dumps({
                "status":  "partial",
                "symbol":  symbol,
                "market":  "HK_STOCK",
                "message": "港股基本面数据暂不支持自动获取，请参考港交所披露或 hkex.com.hk",
                "data":    {},
            }, ensure_ascii=False)

        _t = threading.Thread(target=_fetch, daemon=True, name=f"fund-fetch-{symbol}")
        _t.start()

        if not _done.wait(timeout=_FETCH_TIMEOUT):
            logger.error(f"[Tool] get_fundamental_data 超时 (>{_FETCH_TIMEOUT}s): {symbol}")
            return json.dumps({
                "status": "error",
                "error":  "基本面数据获取超时",
                "symbol": symbol,
            }, ensure_ascii=False)

        if _exc[0] is not None:
            raise _exc[0]

        result = _result[0]
        logger.info(f"[Tool] get_fundamental_data 成功: {symbol} 字段数={len(result.get('data', {}))}")
        return json.dumps(result, ensure_ascii=False, default=str)

    except Exception as e:
        logger.error(f"[Tool] get_fundamental_data 失败: {e}")
        return json.dumps({"status": "error", "error": str(e), "symbol": symbol}, ensure_ascii=False)


# ════════════════════════════════════════════════════════════════
# @tool  4 — get_stock_news
# 【审计修复 Agent-P0-2】为 sentiment_node 提供真实新闻资讯
# ════════════════════════════════════════════════════════════════

@tool
def get_stock_news(symbol: str, limit: int = 8) -> str:
    """
    获取标的最新新闻资讯（真实舆情数据，替代纯量价推断）。

    Args:
        symbol: 交易标的代码
        limit:  返回新闻条数，默认 8 条

    Returns:
        JSON 字符串，包含新闻标题列表；超时或无数据时返回 partial/error 状态。

    数据来源:
        - A股: akshare stock_news_em（东方财富个股新闻）
        - 美股: yfinance Ticker.news
        - 港股: 降级返回 partial 状态
    """
    logger.info(f"[Tool] get_stock_news: {symbol}, limit={limit}")

    try:
        market_type, _ = MarketClassifier.classify(symbol)
        code = symbol.split(".")[0]   # "600519.SH" → "600519"

        _result: list = [None]
        _exc:    list = [None]
        _done = threading.Event()

        if market_type == MarketType.A_STOCK:
            def _fetch():
                try:
                    import akshare as ak
                    df = ak.stock_news_em(symbol=code)
                    if df is None or df.empty:
                        _result[0] = {"status": "partial", "symbol": symbol, "news": [], "count": 0}
                        return
                    # 取标题/时间/来源列（列名可能因 akshare 版本不同）
                    cols = list(df.columns)
                    title_col  = next((c for c in cols if "标题" in c or "title" in c.lower()), cols[0])
                    time_col   = next((c for c in cols if "时间" in c or "date" in c.lower()), None)
                    source_col = next((c for c in cols if "来源" in c or "source" in c.lower()), None)

                    news_list = []
                    for _, row in df.head(limit).iterrows():
                        item = {"title": str(row[title_col])}
                        if time_col:   item["time"]   = str(row[time_col])
                        if source_col: item["source"] = str(row[source_col])
                        news_list.append(item)

                    _result[0] = {
                        "status": "success",
                        "symbol": symbol,
                        "source": "akshare/eastmoney",
                        "news":   news_list,
                        "count":  len(news_list),
                    }
                except Exception as _e:
                    _exc[0] = _e
                finally:
                    _done.set()

        elif market_type == MarketType.US_STOCK:
            def _fetch():
                try:
                    import yfinance as yf
                    raw_news = yf.Ticker(symbol).news or []
                    news_list = [
                        {
                            "title":  n.get("title", ""),
                            "time":   str(n.get("providerPublishTime", "")),
                            "source": n.get("publisher", ""),
                        }
                        for n in raw_news[:limit]
                    ]
                    _result[0] = {
                        "status": "success",
                        "symbol": symbol,
                        "source": "yfinance",
                        "news":   news_list,
                        "count":  len(news_list),
                    }
                except Exception as _e:
                    _exc[0] = _e
                finally:
                    _done.set()

        else:
            # HK_STOCK
            logger.info(f"[Tool] get_stock_news: 港股 {symbol} 暂不支持")
            return json.dumps({
                "status":  "partial",
                "symbol":  symbol,
                "message": "港股新闻暂不支持自动获取，请参考 hkex.com.hk 或东方财富港股频道",
                "news":    [],
                "count":   0,
            }, ensure_ascii=False)

        _t = threading.Thread(target=_fetch, daemon=True, name=f"news-fetch-{symbol}")
        _t.start()

        if not _done.wait(timeout=_FETCH_TIMEOUT):
            logger.error(f"[Tool] get_stock_news 超时 (>{_FETCH_TIMEOUT}s): {symbol}")
            return json.dumps({
                "status": "error",
                "error":  "新闻数据获取超时",
                "symbol": symbol,
                "news":   [],
            }, ensure_ascii=False)

        if _exc[0] is not None:
            raise _exc[0]

        result = _result[0]
        logger.info(f"[Tool] get_stock_news 成功: {symbol} 新闻数={result.get('count', 0)}")
        return json.dumps(result, ensure_ascii=False, default=str)

    except Exception as e:
        logger.error(f"[Tool] get_stock_news 失败: {e}")
        return json.dumps({"status": "error", "error": str(e), "news": [], "symbol": symbol}, ensure_ascii=False)
