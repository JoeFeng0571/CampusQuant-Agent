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
_FETCH_TIMEOUT  = 12
_BATCH_TIMEOUT  = 20   # 批量行情超时（美股并发拉取留更多余量）


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
                    # 切换至同花顺财务摘要（替代已遭 IP 防火墙封锁的东方财富个股信息接口）
                    # stock_financial_abstract_ths 返回: 报告期, 营业总收入, 归母净利润,
                    #   基本每股收益, 加权净资产收益率, 每股净资产, 资产负债率, 每股经营现金流量
                    df = ak.stock_financial_abstract_ths(symbol=code, indicator="按年度")

                    if df is None or df.empty:
                        _result[0] = {
                            "status": "partial", "symbol": symbol,
                            "source": "akshare/ths", "market": "A_STOCK", "data": {},
                        }
                        return

                    cols = list(df.columns)
                    year_col   = cols[0]   # 报告期（首列）
                    rev_col    = next((c for c in cols if "营业" in c and "收入" in c), None)
                    profit_col = next((c for c in cols if "净利润" in c), None)
                    roe_col    = next((c for c in cols if "净资产收益率" in c or "ROE" in c), None)
                    eps_col    = next((c for c in cols if "每股收益" in c or "EPS" in c.upper()), None)

                    def _to_yi(val) -> float:
                        """解析 THS 财务数值（已为亿元单位，带'亿'后缀）"""
                        try:
                            s = str(val).replace(",", "").strip()
                            if "亿" in s:
                                # 值已是亿元，去掉单位直接解析
                                s = s.replace("亿", "").replace("--", "").strip()
                            else:
                                # 假设为元，转亿
                                s = s.replace("--", "").strip()
                                if s:
                                    return round(float(s) / 1e8, 2)
                                return 0.0
                            return round(float(s or "0"), 2)
                        except Exception:
                            return 0.0

                    def _to_float(val):
                        try:
                            return float(str(val).replace("%", "").replace(",", "").replace("--", ""))
                        except Exception:
                            return None

                    # 数据为升序（最旧在前），tail(5) 取最近5年，已是时间正序
                    rows = df.tail(5)
                    rev_hist, pft_hist, yrs, roe_list = [], [], [], []
                    for _, row in rows.iterrows():
                        yrs.append(str(row[year_col])[:4])
                        rev_hist.append(_to_yi(row[rev_col])    if rev_col    else 0.0)
                        pft_hist.append(_to_yi(row[profit_col]) if profit_col else 0.0)
                        if roe_col:
                            roe_list.append(_to_float(row[roe_col]))

                    latest_eps = _to_float(rows.iloc[-1][eps_col]) if (eps_col and not rows.empty) else None

                    _result[0] = {
                        "status": "success",
                        "symbol": symbol,
                        "source": "akshare/ths",
                        "market": "A_STOCK",
                        "data": {
                            "revenue_history": rev_hist,
                            "profit_history":  pft_hist,
                            "years":           yrs,
                            "revenue_label":   "营业总收入（亿元）",
                            "profit_label":    "归母净利润（亿元）",
                            "ROE":             roe_list[-1] if roe_list else None,
                            "EPS(TTM)":        latest_eps,
                        },
                    }
                except Exception as _e:
                    _exc[0] = _e
                finally:
                    _done.set()

        elif market_type == MarketType.US_STOCK:
            def _fetch():
                try:
                    import yfinance as yf
                    import numpy as _np
                    ticker = yf.Ticker(symbol)
                    info   = ticker.info

                    # ── 近5年财务历史（年度收益表）──────────────────────
                    rev_hist, pft_hist, yrs = [], [], []
                    try:
                        fin_df = ticker.financials  # rows=指标, cols=日期(近→远)
                        if fin_df is not None and not fin_df.empty:
                            rev_row = None
                            pft_row = None
                            for idx in fin_df.index:
                                idx_s = str(idx).lower()
                                if "total revenue" in idx_s:
                                    rev_row = idx
                                if "net income" in idx_s and "minority" not in idx_s and "common" not in idx_s:
                                    pft_row = idx
                            cols = list(fin_df.columns)[:5]   # 最近5年（列为近→远）
                            for col in cols:
                                yrs.append(str(col.year))
                                rv = fin_df.loc[rev_row, col] if (rev_row is not None) else None
                                nt = fin_df.loc[pft_row, col] if (pft_row is not None) else None
                                def _safe(v):
                                    try:
                                        f = float(v)
                                        return 0.0 if _np.isnan(f) else round(f / 1e8, 2)
                                    except Exception:
                                        return 0.0
                                rev_hist.append(_safe(rv))
                                pft_hist.append(_safe(nt))
                            # 反转为时间正序（旧→新）
                            yrs      = yrs[::-1]
                            rev_hist = rev_hist[::-1]
                            pft_hist = pft_hist[::-1]
                    except Exception as _fe:
                        logger.warning(f"[get_fundamental_data] yfinance financials 获取失败: {_fe}")

                    _result[0] = {
                        "status": "success",
                        "symbol": symbol,
                        "source": "yfinance",
                        "market": "US_STOCK",
                        "data": {
                            "PE(TTM)":        info.get("trailingPE"),
                            "PE(Forward)":    info.get("forwardPE"),
                            "PB":             info.get("priceToBook"),
                            "PS(TTM)":        info.get("priceToSalesTrailing12Months"),
                            "ROE":            info.get("returnOnEquity"),
                            "ROA":            info.get("returnOnAssets"),
                            "EPS(TTM)":       info.get("trailingEps"),
                            "EPS(Forward)":   info.get("forwardEps"),
                            "营收增速YoY":     info.get("revenueGrowth"),
                            "净利润率":        info.get("profitMargins"),
                            "毛利率":          info.get("grossMargins"),
                            "市值(亿USD)":     round(info.get("marketCap", 0) / 1e8, 2) if info.get("marketCap") else None,
                            "所属行业":        info.get("sector"),
                            "细分板块":        info.get("industry"),
                            "员工人数":        info.get("fullTimeEmployees"),
                            "52周最高":        info.get("fiftyTwoWeekHigh"),
                            "52周最低":        info.get("fiftyTwoWeekLow"),
                            # 财务历史（用于 ECharts 图表）
                            "revenue_history": rev_hist,
                            "profit_history":  pft_hist,
                            "years":           yrs,
                            "revenue_label":   "营业收入（亿美元）",
                            "profit_label":    "净利润（亿美元）",
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


# 常用标的名称静态映射（API 不返回名称时的兜底）
_SYMBOL_NAMES: dict = {
    "600519.SH": "贵州茅台", "000858.SZ": "五粮液",   "601318.SH": "中国平安",
    "002594.SZ": "比亚迪",   "300750.SZ": "宁德时代", "600036.SH": "招商银行",
    "601899.SH": "紫金矿业", "000001.SZ": "平安银行",
    "00700.HK":  "腾讯控股", "09988.HK":  "阿里巴巴", "03690.HK":  "美团",
    "02318.HK":  "中国平安", "01398.HK":  "工商银行", "09999.HK":  "网易",
    "AAPL": "苹果",  "MSFT": "微软",  "NVDA": "英伟达",
    "GOOGL": "谷歌", "AMZN": "亚马逊", "TSLA": "特斯拉", "META": "Meta",
}


# ════════════════════════════════════════════════════════════════
# 实时现价引擎（非 @tool，供节点与 API 端点直接调用）
#
# 设计目标：
#   1. 优先使用实时接口（交易时段）
#   2. 超时或接口失败时，自动降级到最近日线收盘价（非交易时段兜底）
#   3. 全程 Thread + Event 熔断，绝不阻塞主流程
# ════════════════════════════════════════════════════════════════

def get_spot_price_raw(symbol: str) -> dict:
    """
    获取单个标的实时现价（非 @tool，供 trade_executor 和 API 端点调用）。

    优先级：
      A/港股 → akshare 实时行情表（stock_zh_a_spot_em / stock_hk_spot_em）
      美股   → yfinance Ticker.fast_info
      任何失败 → 降级到 DataLoader 日线最新收盘价（is_fallback=True）

    Returns:
        {
          "symbol":      str,
          "price":       float,   # 0.0 表示完全失败
          "change_pct":  float,   # 涨跌幅 (%)
          "is_fallback": bool,    # True = 已降级到日线收盘价
          "source":      str,     # 数据来源描述
        }
    """
    market_type, _ = MarketClassifier.classify(symbol)
    code = symbol.split(".")[0]   # "600519.SH" → "600519"

    _result: list = [None]
    _exc:    list = [None]
    _done = threading.Event()

    if market_type == MarketType.A_STOCK:
        def _fetch():
            try:
                import akshare as ak
                import re as _re

                price, chg, name_str = 0.0, 0.0, code

                # ── 主力接口：东财逐只买卖盘 ────────────────────────────
                try:
                    df = ak.stock_bid_ask_em(symbol=code)
                    kv = dict(zip(df.iloc[:, 0].astype(str), df.iloc[:, 1].astype(str)))
                    price_str = kv.get("最新") or kv.get("最新价") or "0"
                    chg_str   = kv.get("涨跌幅") or "0%"
                    name_str  = kv.get("名称") or kv.get("股票名称") or code
                    price = float(_re.sub(r"[^\d.\-]", "", price_str) or 0)
                    chg   = float(_re.sub(r"[^\d.\-]", "", chg_str) or 0)
                    if price <= 0:
                        raise ValueError("stock_bid_ask_em 返回价格为0，触发备用接口")
                except Exception as _e1:
                    # 常见原因：接口返回 HTML（限流/IP封锁/维护）
                    logger.warning(
                        f"[get_spot_price_raw] stock_bid_ask_em 失败 ({type(_e1).__name__}: {_e1})，"
                        f"切换备用接口 stock_zh_a_spot_em"
                    )
                    # ── 备用接口：东财全市场实时行情表（过滤单只）────────
                    try:
                        df2 = ak.stock_zh_a_spot_em()
                        row = df2[df2["代码"] == code]
                        if not row.empty:
                            r = row.iloc[0]
                            price     = float(r.get("最新价", 0) or 0)
                            chg       = float(r.get("涨跌幅", 0) or 0)
                            name_str  = str(r.get("名称", "") or code)
                        else:
                            raise ValueError(f"stock_zh_a_spot_em 中未找到 {code}")
                    except Exception as _e2:
                        logger.warning(f"[get_spot_price_raw] 备用接口也失败 ({_e2})，将触发日线降级")
                        raise  # 让上层 except 捕获并走日线降级

                if price > 0:
                    _result[0] = {
                        "symbol":      symbol,
                        "name":        name_str,
                        "price":       price,
                        "change_pct":  chg,
                        "is_fallback": False,
                        "source":      "akshare/em-realtime",
                    }
            except Exception as _e:
                _exc[0] = _e
            finally:
                _done.set()

    elif market_type == MarketType.HK_STOCK:
        def _fetch():
            try:
                import akshare as ak
                df = ak.stock_hk_spot_em()
                row = df[df["代码"] == code]
                if not row.empty:
                    r = row.iloc[0]
                    _result[0] = {
                        "symbol":     symbol,
                        "name":       str(r.get("名称", "") or r.get("股票名称", "") or code),
                        "price":      float(r.get("最新价", 0) or 0),
                        "change_pct": float(r.get("涨跌幅", 0) or 0),
                        "is_fallback": False,
                        "source":     "akshare/eastmoney-hk-realtime",
                    }
            except Exception as _e:
                _exc[0] = _e
            finally:
                _done.set()

    elif market_type == MarketType.US_STOCK:
        def _fetch():
            try:
                import yfinance as yf
                fi = yf.Ticker(symbol).fast_info
                price = float(fi.last_price or 0)
                prev  = float(fi.previous_close or fi.regular_market_previous_close or 0)
                chg_pct = round((price - prev) / prev * 100, 2) if prev else 0.0
                _result[0] = {
                    "symbol":     symbol,
                    "name":       _SYMBOL_NAMES.get(symbol, symbol),
                    "price":      price,
                    "change_pct": chg_pct,
                    "is_fallback": False,
                    "source":     "yfinance/fast_info",
                }
            except Exception as _e:
                _exc[0] = _e
            finally:
                _done.set()

    else:
        # UNKNOWN market — 直接返回失败占位
        return {"symbol": symbol, "price": 0.0, "change_pct": 0.0, "is_fallback": True, "source": "unsupported"}

    t = threading.Thread(target=_fetch, daemon=True, name=f"spot-{symbol}")
    t.start()

    if not _done.wait(timeout=_FETCH_TIMEOUT):
        logger.error(f"[get_spot_price_raw] 超时 (>{_FETCH_TIMEOUT}s): {symbol}，降级到日线")
    elif _result[0] and _result[0]["price"] > 0:
        logger.info(f"[get_spot_price_raw] 实时价格: {symbol} = {_result[0]['price']}")
        return _result[0]
    elif _exc[0]:
        logger.error(f"[get_spot_price_raw] 实时接口异常: {_exc[0]}")

    # ── Fallback：降级到日线最新收盘价 ──────────────────────────
    logger.warning(f"[get_spot_price_raw] 实时价格不可用，降级到日线收盘价: {symbol}")
    try:
        loader = _get_loader()
        df = loader.get_historical_data(symbol, days=5)
        if not df.empty:
            last  = float(df.iloc[-1]["close"])
            prev  = float(df.iloc[-2]["close"]) if len(df) >= 2 else last
            chg   = round((last - prev) / prev * 100, 2) if prev else 0.0
            return {"symbol": symbol, "price": last, "change_pct": chg,
                    "is_fallback": True, "source": "daily-close-fallback"}
    except Exception as fe:
        logger.error(f"[get_spot_price_raw] 日线降级也失败: {fe}")

    return {"symbol": symbol, "price": 0.0, "change_pct": 0.0, "is_fallback": True, "source": "none"}


def get_batch_quotes_raw(symbols: list, market: str) -> list:
    """
    批量获取热门标的实时行情（供 /api/v1/market/quotes 端点调用）。

    策略：
      A股  → stock_zh_a_spot_em 一次拉取全表过滤（比逐只调用快 8 倍）
      港股  → stock_hk_spot_em  一次拉取全表过滤
      美股  → yfinance.Tickers 批量并行拉取

    Returns:
        list of {symbol, name, price, change, change_pct, is_fallback}
    """
    if market == "a":
        # ── A 股：并发线程池，每只使用 get_spot_price_raw（内含熔断）──
        import concurrent.futures

        def _fetch_one_a(sym: str) -> dict:
            code = sym.split(".")[0]
            spot = get_spot_price_raw(sym)
            return {
                "symbol":      sym,
                "name":        spot.get("name") or _SYMBOL_NAMES.get(sym) or code,
                "price":       spot["price"],
                "change":      0.0,
                "change_pct":  spot["change_pct"],
                "is_fallback": spot["is_fallback"],
            }

        results_a: list[dict] = []
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(symbols), 10),
            thread_name_prefix="batch-a",
        ) as executor:
            futures_a = {executor.submit(_fetch_one_a, sym): sym for sym in symbols}
            done, _ = concurrent.futures.wait(futures_a, timeout=_BATCH_TIMEOUT)
            for future in done:
                try:
                    results_a.append(future.result())
                except Exception as _e:
                    sym = futures_a[future]
                    logger.error(f"[get_batch_quotes_raw] A股 {sym} 失败: {_e}")
                    results_a.append({
                        "symbol": sym, "name": _SYMBOL_NAMES.get(sym, sym.split(".")[0]),
                        "price": 0.0, "change": 0.0, "change_pct": 0.0, "is_fallback": True,
                    })
            # 超时未完成的标的填兜底
            for future in futures_a:
                if future not in done:
                    sym = futures_a[future]
                    results_a.append({
                        "symbol": sym, "name": _SYMBOL_NAMES.get(sym, sym.split(".")[0]),
                        "price": 0.0, "change": 0.0, "change_pct": 0.0, "is_fallback": True,
                    })
        sym_order_a = {s: i for i, s in enumerate(symbols)}
        results_a.sort(key=lambda r: sym_order_a.get(r["symbol"], 999))
        return results_a

    elif market == "hk":
        # ── 港股：一次拉取 stock_hk_spot_em 全港股表，过滤目标标的 ──
        # 比并发分别下载节省 N 倍网络开销（每次 get_spot_price_raw 都下全表）
        _hk_items: list = [None]
        _hk_done = threading.Event()

        def _fetch_hk_batch():
            try:
                import akshare as ak
                df = ak.stock_hk_spot_em()
                code_map = {sym.split(".")[0]: sym for sym in symbols}
                items = []
                for code, sym in code_map.items():
                    row = df[df["代码"] == code]
                    if not row.empty:
                        r = row.iloc[0]
                        items.append({
                            "symbol":      sym,
                            "name":        str(r.get("名称", "") or _SYMBOL_NAMES.get(sym) or code),
                            "price":       float(r.get("最新价", 0) or 0),
                            "change":      float(r.get("涨跌额", 0) or 0),
                            "change_pct":  float(r.get("涨跌幅", 0) or 0),
                            "is_fallback": False,
                        })
                    else:
                        items.append({
                            "symbol": sym, "name": _SYMBOL_NAMES.get(sym, code),
                            "price": 0.0, "change": 0.0, "change_pct": 0.0,
                            "is_fallback": True,
                        })
                _hk_items[0] = items
            except Exception as _e:
                logger.error(f"[get_batch_quotes_raw] 港股全表失败: {_e}")
            finally:
                _hk_done.set()

        t_hk = threading.Thread(target=_fetch_hk_batch, daemon=True, name="batch-hk")
        t_hk.start()
        # HK全表下载最多给 35 秒（港交所接口较慢）
        _hk_done.wait(timeout=35)

        if _hk_items[0]:
            sym_order_hk = {s: i for i, s in enumerate(symbols)}
            _hk_items[0].sort(key=lambda r: sym_order_hk.get(r["symbol"], 999))
            return _hk_items[0]

        # 超时兜底：立即返回静态名称+零价，is_fallback=True
        # 不再调用任何网络API，避免级联阻塞
        logger.warning("[get_batch_quotes_raw] 港股全表超时，返回静态降级数据")
        return [
            {"symbol": s, "name": _SYMBOL_NAMES.get(s, s.split(".")[0]),
             "price": 0.0, "change": 0.0, "change_pct": 0.0, "is_fallback": True}
            for s in symbols
        ]

    elif market == "us":
        _items: list = [None]
        _done = threading.Event()

        def _fetch_us():
            try:
                import yfinance as yf
                tickers = yf.Tickers(" ".join(symbols))
                items = []
                for sym in symbols:
                    try:
                        fi   = tickers.tickers[sym].fast_info
                        price = float(fi.last_price or 0)
                        prev  = float(fi.previous_close or 0)
                        chg   = round(price - prev, 4)
                        chg_p = round((chg / prev * 100), 2) if prev else 0.0
                        items.append({
                            "symbol": sym, "name": sym,
                            "price": price, "change": chg, "change_pct": chg_p,
                            "is_fallback": False,
                        })
                    except Exception:
                        items.append({
                            "symbol": sym, "name": sym,
                            "price": 0.0, "change": 0.0, "change_pct": 0.0,
                            "is_fallback": True,
                        })
                _items[0] = items
            except Exception as _e:
                logger.error(f"[get_batch_quotes_raw] yfinance 批量失败: {_e}")
            finally:
                _done.set()

        t = threading.Thread(target=_fetch_us, daemon=True, name="batch-us")
        t.start()
        _done.wait(timeout=_BATCH_TIMEOUT)

        if _items[0]:
            return _items[0]

    # 全部降级
    return [{"symbol": s, "name": s.split(".")[0], "price": 0.0,
             "change": 0.0, "change_pct": 0.0, "is_fallback": True}
            for s in symbols]


# ════════════════════════════════════════════════════════════════
# 辅助函数：大盘指数实时数据
# 供 /api/v1/market/indices 端点调用
# ════════════════════════════════════════════════════════════════

# 已知指数代码 → 中文名称映射（避免 Windows 终端编码导致的乱码问题）
_A_INDEX_NAMES: dict[str, str] = {
    "000001": "上证指数",
    "000688": "科创50",
    # 399001/399006 (深证/创业板) 不在 stock_zh_index_spot_em，改由 index_global_spot_em 获取
}
_GLOBAL_INDEX_NAMES: dict[str, str] = {
    "399001": "深证成指",   # stock_zh_index_spot_em 不含399xxx，改从 index_global_spot_em 取
    "399006": "创业板指",
    "HSI":    "恒生指数",
    "NDX":    "纳斯达克100",
    "SPX":    "标普500",
    "DJIA":   "道琼斯",
}

_INDEX_TIMEOUT = 15   # 大盘指数获取总超时（s）


def get_market_indices_raw() -> list[dict]:
    """
    获取主要大盘指数实时数据：A股4只 + 港股（恒生）+ 美股（纳指/标普/道指）。

    数据来源：
      - A股指数: akshare.stock_zh_index_spot_em（2页，约3s）
      - 全球指数: akshare.index_global_spot_em（1次，约1s）

    Returns:
        list[dict]  每项含 {name, code, price, change_pct, change, is_fallback}
        price=0 且 is_fallback=True 表示该指数数据获取失败。
    """
    result: list[dict] = []
    errors: list[str] = []

    # ── A股指数 ───────────────────────────────────────────────
    _a_done  = threading.Event()
    _a_data: list = [None]

    def _fetch_a():
        try:
            import akshare as ak
            df = ak.stock_zh_index_spot_em()
            # 列顺序: 序(0), 代码(1), 名称(2), 最新价(3), 涨跌幅%(4), 涨跌额(5)
            items = []
            for code, name in _A_INDEX_NAMES.items():
                row = df[df.iloc[:, 1] == code]   # col[1] = 代码
                if not row.empty:
                    items.append({
                        "code":       code,
                        "name":       name,
                        "price":      float(row.iloc[0, 3] or 0),   # 最新价
                        "change_pct": float(row.iloc[0, 4] or 0),   # 涨跌幅%
                        "change":     float(row.iloc[0, 5] or 0),   # 涨跌额
                        "is_fallback": False,
                    })
                else:
                    items.append({"code": code, "name": name,
                                  "price": 0.0, "change_pct": 0.0, "change": 0.0,
                                  "is_fallback": True})
            _a_data[0] = items
        except Exception as _e:
            logger.error(f"[get_market_indices_raw] A股指数失败: {_e}")
        finally:
            _a_done.set()

    # ── 全球指数 ──────────────────────────────────────────────
    _g_done  = threading.Event()
    _g_data: list = [None]

    def _fetch_global():
        try:
            import akshare as ak
            df = ak.index_global_spot_em()
            # 列顺序: 序(0), 代码(1), 名称(2), 最新价(3), 涨跌额(4), 涨跌幅%(5)
            # 注意: col[4]=涨跌额(points), col[5]=涨跌幅(%)，与A股列顺序不同
            items = []
            for code, name in _GLOBAL_INDEX_NAMES.items():
                row = df[df.iloc[:, 1] == code]
                if not row.empty:
                    items.append({
                        "code":       code,
                        "name":       name,
                        "price":      float(row.iloc[0, 3] or 0),   # 最新价
                        "change_pct": float(row.iloc[0, 5] or 0),   # 涨跌幅%
                        "change":     float(row.iloc[0, 4] or 0),   # 涨跌额(points)
                        "is_fallback": False,
                    })
                else:
                    items.append({"code": code, "name": name,
                                  "price": 0.0, "change_pct": 0.0, "change": 0.0,
                                  "is_fallback": True})
            _g_data[0] = items
        except Exception as _e:
            logger.error(f"[get_market_indices_raw] 全球指数失败: {_e}")
        finally:
            _g_done.set()

    # 并发发起两个请求
    threading.Thread(target=_fetch_a,      daemon=True, name="idx-a").start()
    threading.Thread(target=_fetch_global, daemon=True, name="idx-global").start()

    _a_done.wait(timeout=_INDEX_TIMEOUT)
    _g_done.wait(timeout=_INDEX_TIMEOUT)

    for items in (_a_data[0], _g_data[0]):
        if items:
            result.extend(items)

    # 如果任一来源完全失败，补充静态占位
    if not result:
        fallback_names = {**_A_INDEX_NAMES, **_GLOBAL_INDEX_NAMES}
        result = [{"code": c, "name": n, "price": 0.0, "change_pct": 0.0,
                   "change": 0.0, "is_fallback": True}
                  for c, n in fallback_names.items()]

    logger.info(f"[get_market_indices_raw] 返回 {len(result)} 个指数，"
                f"fallback数={sum(1 for r in result if r['is_fallback'])}")
    return result


# ════════════════════════════════════════════════════════════════
# 辅助函数：市场财经快讯
# 供 /api/v1/market/news 端点调用
# ════════════════════════════════════════════════════════════════

_NEWS_TIMEOUT = 10   # 新闻获取超时（s）


def get_market_news_raw(limit: int = 20) -> list[dict]:
    """
    获取财联社全球财经快讯（7x24），用于 market.html 右侧资讯面板。

    数据来源: akshare.stock_info_global_cls（财联社实时快讯，约20条/次）

    Returns:
        list[dict]  每项含 {title, date, time, is_fallback}
    """
    _done  = threading.Event()
    _data: list = [None]

    def _fetch():
        try:
            import akshare as ak
            df = ak.stock_info_global_cls()
            if df is None or df.empty:
                return
            # 列顺序: 标题(0), 内容(1), 更新时间(2), 发布时间(3)
            # 注意：某些版本的列顺序为: 标题, 内容, 发布日期, 时间
            items = []
            for _, row in df.head(limit).iterrows():
                title = str(row.iloc[0])
                # 取时间：优先用 col[3]（具体时分秒），若为日期则用 col[2]
                try:
                    time_str = str(row.iloc[3]).strip()
                    date_str = str(row.iloc[2]).strip()
                except Exception:
                    time_str = ""
                    date_str = ""
                # 跳过空标题（财联社偶发无标题条目）
                if not title or title.strip() in ('', 'nan', 'None'):
                    continue
                # 截断过长标题（快讯有时把全文放到标题列）
                if len(title) > 80:
                    title = title[:77] + "…"
                items.append({
                    "title":       title,
                    "date":        date_str,
                    "time":        time_str,
                    "is_fallback": False,
                })
            _data[0] = items
        except Exception as _e:
            logger.error(f"[get_market_news_raw] 财联社快讯获取失败: {_e}")
        finally:
            _done.set()

    threading.Thread(target=_fetch, daemon=True, name="news-cls").start()
    _done.wait(timeout=_NEWS_TIMEOUT)

    if _data[0]:
        logger.info(f"[get_market_news_raw] 返回 {len(_data[0])} 条快讯")
        return _data[0]

    # 超时或失败时返回空列表，前端显示占位提示
    logger.warning("[get_market_news_raw] 快讯获取超时/失败，返回空列表")
    return []
