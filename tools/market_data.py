"""
tools/market_data.py

市场数据工具：
1. A 股优先使用本地 akshare
2. 港股 / 美股行情与 K 线优先使用 akshare 国内接口
3. 港股 / 美股基本面与新闻优先使用 Relay/FC
4. 所有 @tool 都返回 JSON 字符串
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

_CACHE: dict[str, tuple[float, Any]] = {}
_TTL = {"spot": 60, "kline": 300, "fundamental": 3600, "news": 900}


def _json_dumps(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _cache_get(namespace: str, key: str) -> Any:
    item = _CACHE.get(f"{namespace}:{key}")
    if not item:
        return None
    expire_at, value = item
    if time.time() > expire_at:
        _CACHE.pop(f"{namespace}:{key}", None)
        return None
    return value


def _cache_set(namespace: str, key: str, value: Any, ttl: int | None = None) -> Any:
    _CACHE[f"{namespace}:{key}"] = (time.time() + (ttl or _TTL.get(namespace, 300)), value)
    return value


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


def _to_relay_symbol(symbol: str, market_type: MarketType) -> str:
    """将内部代码转换为更适合 Yahoo/Relay 的代码格式。"""
    if market_type == MarketType.HK_STOCK and symbol.upper().endswith(".HK"):
        code = symbol.split(".")[0].lstrip("0") or "0"
        return f"{code}.HK"
    return symbol


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
    """通过 Relay 或未来 FC 中转请求港股/美股数据。"""
    base_url = (config.MARKET_RELAY_BASE_URL or "").rstrip("/")
    token = (config.MARKET_RELAY_TOKEN or "").strip()
    if not base_url or not token:
        logger.warning(f"[market_data] Relay 未配置，无法请求 {endpoint} {symbol}")
        return None

    url = f"{base_url}/relay/market/{endpoint.lstrip('/')}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    market_type, normalized = _normalize_symbol(symbol)
    relay_symbol = _to_relay_symbol(normalized, market_type)
    query = {"symbol": relay_symbol, **(params or {})}
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
    df = df.drop(columns=["timestamp"]).dropna(subset=["open", "high", "low", "close"])
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
    return df.tail(max(int(days), 2)).reset_index(drop=True)[["date", "open", "high", "low", "close", "volume"]]


def _source_days_for_period(period: str, count: int) -> int:
    count = max(int(count), 2)
    if period == "weekly":
        return min(max(count * 7 + 30, 180), 5000)
    if period == "monthly":
        return min(max(count * 31 + 90, 365), 5000)
    return count


def _resample_ohlcv(ohlcv: pd.DataFrame, period: str, count: int) -> pd.DataFrame:
    if period == "daily":
        return ohlcv.tail(max(int(count), 2)).reset_index(drop=True)

    rule = {"weekly": "W-FRI", "monthly": "ME"}.get(period)
    if not rule:
        return ohlcv.tail(max(int(count), 2)).reset_index(drop=True)

    df = ohlcv.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    agg = (
        df.resample(rule)
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna(subset=["open", "high", "low", "close"])
        .reset_index()
    )
    agg["date"] = agg["date"].dt.strftime("%Y-%m-%d")
    return agg.tail(max(int(count), 2)).reset_index(drop=True)


def _get_a_stock_hist(symbol: str, days: int) -> pd.DataFrame:
    pure = symbol.split(".")[0]
    df = _akshare_with_retry(lambda: ak.stock_zh_a_hist(symbol=pure, period="daily", adjust="qfq"))
    if df.empty:
        raise ValueError(f"A 股行情为空: {symbol}")
    df = df.rename(columns={"日期": "date", "开盘": "open", "最高": "high", "最低": "low", "收盘": "close", "成交量": "volume"})
    df = df[["date", "open", "high", "low", "close", "volume"]].copy()
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["volume"] = df["volume"].fillna(0.0)
    return df.dropna(subset=["open", "high", "low", "close"]).tail(max(int(days), 2)).reset_index(drop=True)


def _get_hk_stock_hist(symbol: str, days: int) -> pd.DataFrame:
    pure = symbol.split(".")[0].zfill(5)
    df = _akshare_with_retry(lambda: ak.stock_hk_daily(symbol=pure, adjust="qfq"))
    if df.empty:
        raise ValueError(f"港股行情为空: {symbol}")
    df = df.rename(columns={"date": "date", "open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"})
    df = df[["date", "open", "high", "low", "close", "volume"]].copy()
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["volume"] = df["volume"].fillna(0.0)
    return df.dropna(subset=["open", "high", "low", "close"]).tail(max(int(days), 2)).reset_index(drop=True)


def _get_us_stock_hist(symbol: str, days: int) -> pd.DataFrame:
    pure = symbol.replace(".", "-").upper()
    df = _akshare_with_retry(lambda: ak.stock_us_daily(symbol=pure, adjust="qfq"))
    if df.empty:
        raise ValueError(f"美股行情为空: {symbol}")
    df = df.rename(columns={"date": "date", "open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"})
    df = df[["date", "open", "high", "low", "close", "volume"]].copy()
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["volume"] = df["volume"].fillna(0.0)
    return df.dropna(subset=["open", "high", "low", "close"]).tail(max(int(days), 2)).reset_index(drop=True)


def _get_hist_df(symbol: str, market_type: MarketType, days: int) -> tuple[pd.DataFrame, str]:
    cache_key = f"{market_type.name}:{symbol}:{days}"
    cached = _cache_get("kline", cache_key)
    if cached is not None:
        return cached, "cache"

    if market_type == MarketType.A_STOCK:
        df = _get_a_stock_hist(symbol, days)
        _cache_set("kline", cache_key, df)
        return df, "akshare"

    relay_data = _relay_request("kline", symbol, {"period": "1d", "count": days})
    if relay_data:
        try:
            df = _parse_relay_kline(symbol, relay_data, days)
            min_required = min(days, max(60, int(days * 0.6)))
            if len(df) < min_required:
                raise ValueError(f"Relay 历史长度不足: got={len(df)} need>={min_required}")
            _cache_set("kline", cache_key, df)
            return df, "relay"
        except Exception as relay_exc:
            logger.warning(f"[market_data] Relay K 线解析失败，回退 akshare: {symbol} {relay_exc}")

    try:
        if market_type == MarketType.HK_STOCK:
            df = _get_hk_stock_hist(symbol, days)
        else:
            df = _get_us_stock_hist(symbol, days)
        _cache_set("kline", cache_key, df)
        return df, "akshare"
    except Exception as ak_exc:
        logger.warning(f"[market_data] akshare K 线失败: {symbol} {ak_exc}")
        raise ak_exc


def _get_non_a_spot(symbol: str, market_type: MarketType) -> dict[str, Any] | None:
    cache_key = f"{market_type.name}:{symbol}"
    cached = _cache_get("spot", cache_key)
    if cached is not None:
        return cached

    try:
        # 复用 2 根日线，避免 Yahoo quote 接口 401，同时可命中 K 线缓存。
        ohlcv, source = _get_hist_df(symbol, market_type, 2)
        latest = ohlcv.iloc[-1]
        prev_close = float(ohlcv.iloc[-2]["close"]) if len(ohlcv) >= 2 else float(latest["close"])
        price = float(latest["close"])
        change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0.0
        parsed = {
            "symbol": symbol,
            "name": symbol,
            "price": price,
            "change_pct": change_pct,
            "source": source,
        }
        return _cache_set("spot", cache_key, parsed)
    except Exception as relay_exc:
        logger.warning(f"[market_data] relay/kline spot 回退到 akshare: {symbol} {relay_exc}")

    try:
        if market_type == MarketType.HK_STOCK:
            df = _akshare_with_retry(lambda: ak.stock_hk_spot_em())
            key = symbol.split(".")[0].zfill(5)
            row_df = df[df["代码"].astype(str).str.zfill(5) == key]
            if row_df.empty:
                return None
            row = row_df.iloc[0].to_dict()
            result = {
                "symbol": symbol,
                "name": row.get("名称") or symbol,
                "price": _safe_float(row.get("最新价")),
                "change_pct": _safe_float(row.get("涨跌幅")) or 0.0,
                "source": "akshare",
            }
        else:
            df = _akshare_with_retry(lambda: ak.stock_us_spot_em())
            key = symbol.replace(".", "-").upper()
            row_df = df[df["代码"].astype(str).str.upper() == key]
            if row_df.empty:
                return None
            row = row_df.iloc[0].to_dict()
            result = {
                "symbol": symbol,
                "name": row.get("名称") or symbol,
                "price": _safe_float(row.get("最新价")),
                "change_pct": _safe_float(row.get("涨跌幅")) or 0.0,
                "source": "akshare",
            }
        if result.get("price") is None:
            return None
        return _cache_set("spot", cache_key, result)
    except Exception as exc:
        logger.warning(f"[market_data] akshare 实时行情失败: {symbol} {exc}")
        return None


def _build_market_payload(symbol: str, market_type: MarketType, ohlcv: pd.DataFrame, source: str) -> dict[str, Any]:
    latest = ohlcv.iloc[-1]
    prev_close = float(ohlcv.iloc[-2]["close"]) if len(ohlcv) >= 2 else float(latest["close"])
    latest_close = float(latest["close"])
    change_pct = ((latest_close - prev_close) / prev_close * 100) if prev_close else 0.0
    return {
        "status": "success",
        "symbol": symbol,
        "market_type": market_type.name,
        "source": source,
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
        cur_rsi = rsi14.iloc[-1] if pd.notna(rsi14.iloc[-1]) else 50
        if macd.iloc[-1] > macd_signal.iloc[-1] and cur_rsi < 70:
            tech_signal = "BUY"
        elif macd.iloc[-1] < macd_signal.iloc[-1] and cur_rsi > 30:
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


def _get_relay_fundamental(symbol: str) -> dict[str, Any]:
    cached = _cache_get("fundamental", symbol)
    if cached is not None:
        return cached
    payload = _relay_request("fundamental", symbol)
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
    return _cache_set("fundamental", symbol, data)


def _get_relay_news(symbol: str, limit: int) -> list[dict[str, Any]]:
    cache_key = f"{symbol}:{limit}"
    cached = _cache_get("news", cache_key)
    if cached is not None:
        return cached
    payload = _relay_request("news", symbol)
    items = (payload or {}).get("news") or []
    news = []
    for item in items[: max(int(limit), 1)]:
        news.append(
            {
                "title": str(item.get("title") or "")[:200],
                "source": str((item.get("publisher") or item.get("source") or {}).get("name") if isinstance(item.get("publisher"), dict) else item.get("publisher") or item.get("source") or "Yahoo Finance"),
                "time": datetime.fromtimestamp(int(item.get("providerPublishTime", 0))).isoformat() if item.get("providerPublishTime") else "",
            }
        )
    return _cache_set("news", cache_key, news)


@tool
def get_market_data(symbol: str, days: int = 180) -> str:
    """获取股票行情数据，返回统一的 OHLCV JSON 字符串。"""
    try:
        market_type, normalized = _normalize_symbol(symbol)
        if market_type == MarketType.UNKNOWN:
            return _json_dumps({"status": "error", "symbol": symbol, "error": "无法识别市场"})
        ohlcv, source = _get_hist_df(normalized, market_type, days)
        return _json_dumps(_build_market_payload(normalized, market_type, ohlcv, source))
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
            return _json_dumps({"status": "success", "symbol": normalized, "market_type": market_type.name, "source": "akshare", "data": data})

        data = _get_relay_fundamental(normalized)
        if not any(v is not None and v != "" for v in data.values()):
            return _json_dumps({"status": "partial", "symbol": normalized, "market_type": market_type.name, "source": "relay", "data": {}, "message": "Relay 基本面数据不可用"})
        return _json_dumps({"status": "success", "symbol": normalized, "market_type": market_type.name, "source": "relay", "data": data})
    except Exception as exc:
        logger.exception(f"[market_data] get_fundamental_data 失败: {symbol}")
        return _json_dumps({"status": "error", "symbol": symbol, "error": str(exc), "data": {}})


@tool
def get_stock_news(symbol: str, limit: int = 5) -> str:
    """获取股票相关新闻，返回统一 JSON 字符串。"""
    try:
        market_type, normalized = _normalize_symbol(symbol)
        news: list[dict[str, Any]] = []
        source = "akshare"
        if market_type == MarketType.A_STOCK:
            pure = normalized.split(".")[0]
            df = _akshare_with_retry(lambda: ak.stock_news_em(symbol=pure))
            if not df.empty:
                df = df.head(max(int(limit), 1))
                for _, row in df.iterrows():
                    news.append(
                        {
                            "title": str(_pick_value(row.to_dict(), ["标题", "新闻标题", "title"]) or "")[:200],
                            "source": str(_pick_value(row.to_dict(), ["文章来源", "来源", "source"]) or "东方财富"),
                            "time": str(_pick_value(row.to_dict(), ["发布时间", "日期", "时间", "publish_time"]) or ""),
                        }
                    )
        else:
            source = "relay"
            news = _get_relay_news(normalized, limit)

        status = "success" if news else "partial"
        return _json_dumps({"status": status, "symbol": normalized, "market_type": market_type.name, "source": source, "news": news, "message": "" if news else "暂无新闻数据"})
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
    market_type, normalized = _normalize_symbol(symbol)
    try:
        if market_type == MarketType.UNKNOWN:
            return []
        source_days = _source_days_for_period(period, count)
        daily_ohlcv, _ = _get_hist_df(normalized, market_type, source_days)
        ohlcv = _resample_ohlcv(daily_ohlcv, period, count)
        return [
            {
                "time": row["date"],
                "open": round(float(row["open"]), 4),
                "high": round(float(row["high"]), 4),
                "low": round(float(row["low"]), 4),
                "close": round(float(row["close"]), 4),
                "volume": round(float(row["volume"]), 4),
            }
            for row in ohlcv.to_dict(orient="records")
        ]
    except Exception as exc:
        logger.warning(f"[market_data] get_kline_data_raw 失败: {symbol} {exc}")
        return []


def get_spot_price_raw(symbol: str) -> dict[str, Any]:
    market_type, normalized = _normalize_symbol(symbol)
    if market_type in (MarketType.HK_STOCK, MarketType.US_STOCK):
        spot = _get_non_a_spot(normalized, market_type)
        if spot:
            return {
                "symbol": normalized,
                "name": spot.get("name", normalized),
                "market_type": market_type.name,
                "price": spot.get("price"),
                "change_pct": round(float(spot.get("change_pct") or 0.0), 4),
                "is_fallback": False,
                "source": spot.get("source", "akshare"),
            }

    bars = get_kline_data_raw(normalized, period="daily", count=2)
    if not bars:
        return {"symbol": normalized, "name": normalized, "price": None, "change_pct": 0.0, "is_fallback": True, "source": "none"}
    latest = bars[-1]
    prev_close = bars[-2]["close"] if len(bars) >= 2 else latest["close"]
    change_pct = ((latest["close"] - prev_close) / prev_close * 100) if prev_close else 0.0
    return {
        "symbol": normalized,
        "name": normalized,
        "market_type": market_type.name,
        "price": latest["close"],
        "change_pct": round(change_pct, 4),
        "is_fallback": False,
        "source": "akshare" if market_type != MarketType.UNKNOWN else "fallback",
    }


def get_batch_quotes_raw(symbols: list[str], market: str | None = None) -> list[dict[str, Any]]:
    return [get_spot_price_raw(sym) for sym in symbols]


def get_market_indices_raw() -> list[dict[str, Any]]:
    fallback = [
        {"symbol": "000001.SH", "name": "上证指数", "price": 0.0, "change_pct": 0.0, "is_fallback": True},
        {"symbol": "399001.SZ", "name": "深证成指", "price": 0.0, "change_pct": 0.0, "is_fallback": True},
        {"symbol": "^IXIC", "name": "纳斯达克", "price": 0.0, "change_pct": 0.0, "is_fallback": True},
    ]
    try:
        return [
            get_spot_price_raw("000001.SH") | {"name": "上证指数"},
            get_spot_price_raw("399001.SZ") | {"name": "深证成指"},
            get_spot_price_raw("AAPL") | {"symbol": "^IXIC", "name": "纳斯达克观察"},
        ]
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
