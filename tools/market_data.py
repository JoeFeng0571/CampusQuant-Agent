"""
tools/market_data.py

市场数据工具：
- A 股走本地 akshare
- 港股 / 美股走 Cloudflare Relay
"""

import json
import time
from datetime import datetime
from typing import Any, Callable

import akshare as ak
import pandas as pd
import requests
from langchain_core.tools import tool
from loguru import logger

from config import config
from utils.market_classifier import MarketClassifier, MarketType


def _json_dumps(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _safe_float(value: Any) -> float | None:
    if value in (None, "", "-", "--"):
        return None
    if isinstance(value, dict):
        value = value.get("raw", value.get("fmt"))
    try:
        if isinstance(value, str):
            value = value.replace(",", "").replace("%", "").strip()
        return float(value)
    except (TypeError, ValueError):
        return None


def _pick_value(record: dict[str, Any], candidates: list[str]) -> Any:
    lowered = {str(k).strip().lower(): v for k, v in record.items()}
    for key in candidates:
        if key.lower() in lowered:
            return lowered[key.lower()]
    return None


def _normalize_symbol(symbol: str) -> tuple[MarketType, str]:
    matched = MarketClassifier.fuzzy_match(symbol.strip())
    market_type, normalized = MarketClassifier.classify(matched)
    return market_type, normalized


def _akshare_with_retry(fn: Callable[[], Any], retries: int = 2, delay: float = 0.8) -> Any:
    """带重试的 akshare 调用，禁止静默返回 None。"""
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            result = fn()
            if result is None:
                raise ValueError("akshare 返回 None")
            return result
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(delay * (attempt + 1))
    raise last_error or ValueError("akshare 调用失败")


def _relay_request(endpoint: str, symbol: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """通过 Cloudflare Relay 请求港股/美股数据。"""
    base_url = (config.MARKET_RELAY_BASE_URL or "").rstrip("/")
    token = (config.MARKET_RELAY_TOKEN or "").strip()
    if not base_url or not token:
        logger.warning(f"[market_data] Relay 未配置，无法请求 {endpoint} {symbol}")
        return None

    url = f"{base_url}/relay/market/{endpoint.lstrip('/')}"
    query = {"symbol": symbol, **(params or {})}
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        resp = requests.get(url, params=query, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.warning(f"[market_data] Relay 请求失败 endpoint={endpoint} symbol={symbol}: {exc}")
        return None


def _parse_relay_kline(symbol: str, payload: dict[str, Any], days: int) -> pd.DataFrame:
    result = ((payload or {}).get("chart") or {}).get("result") or []
    if not result:
        raise ValueError(f"Relay K 线为空: {symbol}")
    node = result[0]
    quote = (((node.get("indicators") or {}).get("quote") or [{}])[0]) or {}
    df = pd.DataFrame(
        {
            "timestamp": node.get("timestamp") or [],
            "open": quote.get("open") or [],
            "high": quote.get("high") or [],
            "low": quote.get("low") or [],
            "close": quote.get("close") or [],
            "volume": quote.get("volume") or [],
        }
    )
    if df.empty:
        raise ValueError(f"Relay K 线解析失败: {symbol}")
    df["date"] = pd.to_datetime(df["timestamp"], unit="s", utc=True).dt.tz_convert("Asia/Shanghai").dt.strftime("%Y-%m-%d")
    df = df.drop(columns=["timestamp"]).dropna(subset=["open", "high", "low", "close"]).tail(max(int(days), 2)).reset_index(drop=True)
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
    return df[["date", "open", "high", "low", "close", "volume"]]


def _get_a_stock_hist(symbol: str, days: int) -> pd.DataFrame:
    pure = symbol.split(".")[0]
    df = _akshare_with_retry(lambda: ak.stock_zh_a_hist(symbol=pure, period="daily", adjust="qfq"))
    if df.empty:
        raise ValueError(f"A 股行情为空: {symbol}")
    columns = {"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "volume"}
    df = df.rename(columns=columns)
    df = df[list(columns.values())].copy()
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).tail(max(int(days), 2)).reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["volume"] = df["volume"].fillna(0.0)
    return df


def _build_market_payload(symbol: str, market_type: MarketType, ohlcv: pd.DataFrame) -> dict[str, Any]:
    latest = ohlcv.iloc[-1]
    prev_close = float(ohlcv.iloc[-2]["close"]) if len(ohlcv) >= 2 else float(latest["close"])
    latest_close = float(latest["close"])
    change_pct = ((latest_close - prev_close) / prev_close * 100) if prev_close else 0.0
    return {
        "status": "success",
        "symbol": symbol,
        "market_type": market_type.name,
        "latest_price": round(latest_close, 4),
        "period_high": round(float(ohlcv["high"].max()), 4),
        "period_low": round(float(ohlcv["low"].min()), 4),
        "price_change_pct": round(change_pct, 4),
        "volume_latest": round(float(latest["volume"]), 4),
        "data_count": int(len(ohlcv)),
        "_ohlcv_json": ohlcv.to_json(orient="records", force_ascii=False),
    }


def _calc_indicators_from_ohlcv(ohlcv: pd.DataFrame) -> dict[str, Any]:
    """基于 OHLCV 计算常用技术指标。"""
    df = ohlcv.copy()
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    close, high, low, volume = df["close"], df["high"], df["low"], df["volume"]
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, pd.NA)
    rsi14 = 100 - (100 / (1 + rs))
    ma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    boll_up = ma20 + 2 * std20
    boll_low = ma20 - 2 * std20
    tr = pd.concat([(high - low), (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean()
    vol_ma10 = volume.rolling(10).mean()
    volume_ratio = volume.iloc[-1] / vol_ma10.iloc[-1] if len(df) >= 10 and vol_ma10.iloc[-1] else None
    last_close = float(close.iloc[-1])
    tech_signal = "HOLD"
    if pd.notna(macd.iloc[-1]) and pd.notna(macd_signal.iloc[-1]):
        if macd.iloc[-1] > macd_signal.iloc[-1] and (rsi14.iloc[-1] if pd.notna(rsi14.iloc[-1]) else 50) < 70:
            tech_signal = "BUY"
        elif macd.iloc[-1] < macd_signal.iloc[-1] and (rsi14.iloc[-1] if pd.notna(rsi14.iloc[-1]) else 50) > 30:
            tech_signal = "SELL"
    return {
        "status": "success",
        "indicators": {
            "MACD": round(float(macd.iloc[-1]), 4) if pd.notna(macd.iloc[-1]) else None,
            "MACD_signal": round(float(macd_signal.iloc[-1]), 4) if pd.notna(macd_signal.iloc[-1]) else None,
            "RSI14": round(float(rsi14.iloc[-1]), 4) if pd.notna(rsi14.iloc[-1]) else None,
            "MA20": round(float(ma20.iloc[-1]), 4) if pd.notna(ma20.iloc[-1]) else None,
            "BOLL_upper": round(float(boll_up.iloc[-1]), 4) if pd.notna(boll_up.iloc[-1]) else None,
            "BOLL_lower": round(float(boll_low.iloc[-1]), 4) if pd.notna(boll_low.iloc[-1]) else None,
            "BOLL_pct_B": round(float((last_close - boll_low.iloc[-1]) / (boll_up.iloc[-1] - boll_low.iloc[-1])), 4)
            if pd.notna(boll_up.iloc[-1]) and pd.notna(boll_low.iloc[-1]) and boll_up.iloc[-1] != boll_low.iloc[-1] else None,
            "ATR14": round(float(atr14.iloc[-1]), 4) if pd.notna(atr14.iloc[-1]) else None,
            "ATR_pct": round(float(atr14.iloc[-1] / last_close * 100), 4) if pd.notna(atr14.iloc[-1]) and last_close else None,
            "volume_ratio": round(float(volume_ratio), 4) if volume_ratio is not None else None,
            "high_volume": bool(volume_ratio and volume_ratio >= 1.5),
            "tech_signal": tech_signal,
        },
    }


@tool
def get_market_data(symbol: str, days: int = 180) -> str:
    """获取股票行情数据，返回统一的 OHLCV JSON 字符串。"""
    try:
        market_type, normalized = _normalize_symbol(symbol)
        if market_type == MarketType.UNKNOWN:
            return _json_dumps({"status": "error", "symbol": symbol, "error": "无法识别市场"})
        if market_type == MarketType.A_STOCK:
            ohlcv = _get_a_stock_hist(normalized, days)
        else:
            relay_data = _relay_request("kline", normalized, {"period": "1d", "count": days})
            if not relay_data:
                return _json_dumps({"status": "error", "symbol": normalized, "market_type": market_type.name, "error": "Relay 行情获取失败"})
            ohlcv = _parse_relay_kline(normalized, relay_data, days)
        return _json_dumps(_build_market_payload(normalized, market_type, ohlcv))
    except Exception as exc:
        logger.exception(f"[market_data] get_market_data 失败: {symbol}")
        return _json_dumps({"status": "error", "symbol": symbol, "error": str(exc)})


@tool
def get_fundamental_data(symbol: str) -> str:
    """获取股票基本面数据，返回统一 JSON 字符串。"""
    try:
        market_type, normalized = _normalize_symbol(symbol)
        if market_type == MarketType.A_STOCK:
            pure = normalized.split(".")[0]
            df = _akshare_with_retry(lambda: ak.stock_financial_abstract_ths(symbol=pure))
            if df.empty:
                raise ValueError("财务摘要为空")
            row = df.iloc[-1].to_dict()
            data = {
                "report_date": _pick_value(row, ["报告期", "报告日期", "日期"]),
                "pe": _safe_float(_pick_value(row, ["市盈率", "市盈率ttm", "滚动市盈率"])),
                "pb": _safe_float(_pick_value(row, ["市净率"])),
                "roe": _safe_float(_pick_value(row, ["净资产收益率", "净资产收益率roe", "roe"])),
                "eps": _safe_float(_pick_value(row, ["每股收益", "基本每股收益", "eps"])),
            }
        else:
            payload = _relay_request("fundamental", normalized)
            result = (((payload or {}).get("quoteSummary") or {}).get("result") or [{}])[0]
            stats = result.get("defaultKeyStatistics") or {}
            financial = result.get("financialData") or {}
            profile = result.get("assetProfile") or {}
            data = {
                "industry": profile.get("industry"),
                "sector": profile.get("sector"),
                "pe": _safe_float(financial.get("trailingPE")) or _safe_float(stats.get("trailingPE")) or _safe_float(stats.get("forwardPE")),
                "pb": _safe_float(stats.get("priceToBook")),
                "roe": (_safe_float(financial.get("returnOnEquity")) or 0.0) * 100 if _safe_float(financial.get("returnOnEquity")) is not None else None,
                "eps": _safe_float(stats.get("trailingEps")) or _safe_float(stats.get("forwardEps")),
            }
        return _json_dumps({"status": "success", "symbol": normalized, "market_type": market_type.name, "data": data})
    except Exception as exc:
        logger.exception(f"[market_data] get_fundamental_data 失败: {symbol}")
        return _json_dumps({"status": "error", "symbol": symbol, "error": str(exc), "data": {}})


@tool
def get_stock_news(symbol: str, limit: int = 5) -> str:
    """获取股票相关新闻，返回统一 JSON 字符串。"""
    try:
        market_type, normalized = _normalize_symbol(symbol)
        news: list[dict[str, Any]] = []
        if market_type == MarketType.A_STOCK:
            pure = normalized.split(".")[0]
            df = _akshare_with_retry(lambda: ak.stock_news_em(symbol=pure))
            if not df.empty:
                df = df.head(max(int(limit), 1))
                for _, row in df.iterrows():
                    news.append({
                        "title": str(_pick_value(row.to_dict(), ["标题", "新闻标题", "title"]) or "")[:200],
                        "source": str(_pick_value(row.to_dict(), ["文章来源", "来源", "source"]) or "东方财富"),
                        "time": str(_pick_value(row.to_dict(), ["发布时间", "日期", "时间", "publish_time"]) or ""),
                    })
        else:
            payload = _relay_request("news", normalized)
            items = (payload or {}).get("news") or []
            for item in items[: max(int(limit), 1)]:
                news.append({
                    "title": str(item.get("title") or "")[:200],
                    "source": str((item.get("publisher") or item.get("source") or {}).get("name") if isinstance(item.get("publisher"), dict) else item.get("publisher") or item.get("source") or "Yahoo Finance"),
                    "time": datetime.fromtimestamp(int(item.get("providerPublishTime", 0))).isoformat() if item.get("providerPublishTime") else "",
                })
        status = "success" if news else "partial"
        return _json_dumps({"status": status, "symbol": normalized, "market_type": market_type.name, "news": news, "message": "" if news else "暂无新闻数据"})
    except Exception as exc:
        logger.exception(f"[market_data] get_stock_news 失败: {symbol}")
        return _json_dumps({"status": "error", "symbol": symbol, "error": str(exc), "news": []})


@tool
def calculate_technical_indicators(market_data_json: str) -> str:
    """基于行情 JSON 计算技术指标。"""
    try:
        payload = json.loads(market_data_json)
        ohlcv_json = payload.get("_ohlcv_json")
        if not ohlcv_json:
            return _json_dumps({"status": "error", "error": "缺少 _ohlcv_json"})
        ohlcv = pd.DataFrame(json.loads(ohlcv_json))
        return _json_dumps(_calc_indicators_from_ohlcv(ohlcv))
    except Exception as exc:
        logger.exception("[market_data] calculate_technical_indicators 失败")
        return _json_dumps({"status": "error", "error": str(exc), "indicators": {}})


def get_kline_data_raw(symbol: str, period: str = "daily", count: int = 120) -> list[dict[str, Any]]:
    period_map = {"daily": "1d", "weekly": "1wk", "monthly": "1mo"}
    market_type, normalized = _normalize_symbol(symbol)
    try:
        if market_type == MarketType.A_STOCK and period == "daily":
            ohlcv = _get_a_stock_hist(normalized, count)
        elif market_type != MarketType.UNKNOWN:
            relay_data = _relay_request("kline", normalized, {"period": period_map.get(period, "1d"), "count": count})
            ohlcv = _parse_relay_kline(normalized, relay_data or {}, count)
        else:
            return []
        return [{"time": r["date"], "open": round(float(r["open"]), 4), "high": round(float(r["high"]), 4), "low": round(float(r["low"]), 4), "close": round(float(r["close"]), 4), "volume": round(float(r["volume"]), 4)} for r in ohlcv.to_dict(orient="records")]
    except Exception as exc:
        logger.warning(f"[market_data] get_kline_data_raw 失败: {symbol} {exc}")
        return []


def get_spot_price_raw(symbol: str) -> dict[str, Any]:
    market_type, normalized = _normalize_symbol(symbol)
    bars = get_kline_data_raw(normalized, period="daily", count=2)
    if not bars:
        return {"symbol": normalized, "name": normalized, "price": None, "change_pct": 0.0, "is_fallback": True, "source": "none"}
    latest = bars[-1]
    prev_close = bars[-2]["close"] if len(bars) >= 2 else latest["close"]
    change_pct = ((latest["close"] - prev_close) / prev_close * 100) if prev_close else 0.0
    return {"symbol": normalized, "name": normalized, "market_type": market_type.name, "price": latest["close"], "change_pct": round(change_pct, 4), "is_fallback": False, "source": "akshare" if market_type == MarketType.A_STOCK else "relay"}


def get_batch_quotes_raw(symbols: list[str], market: str | None = None) -> list[dict[str, Any]]:
    return [get_spot_price_raw(sym) for sym in symbols]


def get_market_indices_raw() -> list[dict[str, Any]]:
    fallback = [
        {"symbol": "000001.SH", "name": "上证指数", "price": 0.0, "change_pct": 0.0, "is_fallback": True},
        {"symbol": "399001.SZ", "name": "深证成指", "price": 0.0, "change_pct": 0.0, "is_fallback": True},
        {"symbol": "^IXIC", "name": "纳斯达克", "price": 0.0, "change_pct": 0.0, "is_fallback": True},
    ]
    try:
        return [get_spot_price_raw("000001.SH") | {"name": "上证指数"}, get_spot_price_raw("399001.SZ") | {"name": "深证成指"}, get_spot_price_raw("AAPL") | {"symbol": "^IXIC", "name": "纳斯达克观察"}]
    except Exception:
        return fallback


def get_market_news_raw(limit: int = 20) -> list[dict[str, Any]]:
    try:
        from tools.hot_news import get_hot_news

        flat: list[dict[str, Any]] = []
        for block in get_hot_news(force_refresh=False):
            label = block.get("label", "")
            for item in block.get("items", []):
                flat.append({"title": item.get("title", "")[:200], "source": label, "time": block.get("fetched_at") or "", "url": item.get("url", "")})
        return flat[:limit]
    except Exception as exc:
        logger.warning(f"[market_data] get_market_news_raw 失败: {exc}")
        return []


def get_sector_data_raw() -> list[dict[str, Any]]:
    return [
        {"sector": "消费", "change_pct": 0.0},
        {"sector": "科技", "change_pct": 0.0},
        {"sector": "金融", "change_pct": 0.0},
    ]


def get_market_sentiment_raw() -> dict[str, Any]:
    indices = get_market_indices_raw()
    avg_change = sum(float(item.get("change_pct") or 0.0) for item in indices) / max(len(indices), 1)
    level = "neutral"
    if avg_change > 1:
        level = "bullish"
    elif avg_change < -1:
        level = "bearish"
    return {"sentiment": level, "score": round(avg_change, 4), "indices": indices}


def get_deep_financial_data_via_relay(symbol: str) -> dict[str, Any]:
    market_type, normalized = _normalize_symbol(symbol)
    if market_type != MarketType.A_STOCK:
        payload = _relay_request("deep", normalized) or {}
        result = (((payload.get("quoteSummary") or {}).get("result")) or [{}])[0]
        return {"raw": result, "revenue_composition": {}, "performance_trend": {}}
    return get_deep_financial_data(normalized)


def get_deep_financial_data(symbol: str) -> dict[str, Any]:
    return {"symbol": symbol, "revenue_composition": {}, "performance_trend": {}}
