"""
市场数据工具。

职责：
1. A 股优先使用 akshare 本地接口。
2. 港股、美股优先使用香港 relay 获取 K 线，失败时回退到 akshare。
3. 提供市场页依赖的批量行情、指数、快讯、板块和情绪数据。
4. 所有 @tool 工具都返回 JSON 字符串。
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Callable

import pandas as pd

try:
    import akshare as ak
except ImportError:
    ak = None  # 香港服务器不装 akshare，数据走内地 relay
import requests
from langchain_core.tools import tool
from loguru import logger

from config import config
from utils.market_classifier import MarketClassifier, MarketType

_CACHE: dict[str, tuple[float, Any]] = {}
_TTL = {
    "spot": 60,
    "kline": 300,
    "fundamental": 3600,
    "news": 900,
    "overview": 120,
}


def _json_dumps(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _cache_key(namespace: str, key: str) -> str:
    return f"{namespace}:{key}"


def _cache_get(namespace: str, key: str) -> Any:
    item = _CACHE.get(_cache_key(namespace, key))
    if not item:
        return None
    expire_at, value = item
    if time.time() > expire_at:
        _CACHE.pop(_cache_key(namespace, key), None)
        return None
    return value


def _cache_set(namespace: str, key: str, value: Any, ttl: int | None = None) -> Any:
    _CACHE[_cache_key(namespace, key)] = (time.time() + (ttl or _TTL.get(namespace, 300)), value)
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


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip() or default


def _pick_column(df: pd.DataFrame, aliases: list[str]) -> str | None:
    cols = {str(col).strip().lower(): str(col) for col in df.columns}
    for alias in aliases:
        key = alias.strip().lower()
        if key in cols:
            return cols[key]
    return None


def _normalize_symbol(symbol: str) -> tuple[MarketType, str]:
    matched = MarketClassifier.fuzzy_match((symbol or "").strip())
    return MarketClassifier.classify(matched)


def _to_relay_symbol(symbol: str, market_type: MarketType) -> str:
    if market_type == MarketType.HK_STOCK and symbol.upper().endswith(".HK"):
        code = symbol.split(".")[0].lstrip("0") or "0"
        return f"{code}.HK"
    return symbol


def _akshare_with_retry(fn: Callable[[], Any], retries: int = 2, delay: float = 0.8) -> Any:
    if ak is None:
        raise RuntimeError("akshare 未安装，数据应走内地 relay")
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            result = fn()
            if result is None:
                raise ValueError("akshare 返回空结果")
            return result
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(delay * (attempt + 1))
    raise last_error or RuntimeError("akshare 调用失败")


def _relay_request(endpoint: str, symbol: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    base_url = (config.MARKET_RELAY_BASE_URL or "").rstrip("/")
    token = (config.MARKET_RELAY_TOKEN or "").strip()
    if not base_url or not token:
        return None

    # 指数符号（^GSPC, ^HSI, ^IXIC 等）直接透传给 relay，不做模糊匹配
    if symbol.startswith("^"):
        relay_symbol = symbol
    else:
        market_type, normalized = _normalize_symbol(symbol)
        relay_symbol = _to_relay_symbol(normalized, market_type)
    url = f"{base_url}/relay/market/{endpoint.lstrip('/')}"
    query = {"symbol": relay_symbol, **(params or {})}
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    try:
        resp = requests.get(url, params=query, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.warning(f"[market_data] relay 请求失败 endpoint={endpoint} symbol={symbol}: {exc}")
        return None


def _inland_relay_request(endpoint: str, params: dict[str, Any] | None = None, timeout: int = 45) -> dict[str, Any] | None:
    """请求内地数据中继服务（akshare A股/港美股 + RAG + 新闻）"""
    base_url = (config.INLAND_RELAY_BASE_URL or "").rstrip("/")
    token = (config.INLAND_RELAY_TOKEN or "").strip()
    if not base_url or not token:
        return None
    url = f"{base_url}/relay/{endpoint.lstrip('/')}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        resp = requests.get(url, params=params or {}, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.warning(f"[market_data] inland relay 请求失败 endpoint={endpoint}: {exc}")
        return None


def _normalize_ohlcv_df(df: pd.DataFrame) -> pd.DataFrame:
    aliases = {
        "date": ["日期", "date", "时间", "trade_date"],
        "open": ["开盘", "open", "今开", "开盘价"],
        "high": ["最高", "high", "最高价"],
        "low": ["最低", "low", "最低价"],
        "close": ["收盘", "close", "最新价", "close_price"],
        "volume": ["成交量", "volume", "vol"],
    }

    mapped: dict[str, str] = {}
    for target, options in aliases.items():
        col = _pick_column(df, options)
        if not col:
            raise ValueError(f"缺少列: {target}")
        mapped[target] = col

    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df[mapped["date"]], errors="coerce"),
            "open": pd.to_numeric(df[mapped["open"]], errors="coerce"),
            "high": pd.to_numeric(df[mapped["high"]], errors="coerce"),
            "low": pd.to_numeric(df[mapped["low"]], errors="coerce"),
            "close": pd.to_numeric(df[mapped["close"]], errors="coerce"),
            "volume": pd.to_numeric(df[mapped["volume"]], errors="coerce"),
        }
    )
    out["volume"] = out["volume"].fillna(0.0)
    out = out.dropna(subset=["date", "open", "high", "low", "close"])
    out = out.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    return out.reset_index(drop=True)


def _parse_relay_kline(symbol: str, payload: dict[str, Any]) -> pd.DataFrame:
    result = ((payload or {}).get("chart") or {}).get("result") or []
    if not result:
        raise ValueError(f"relay K 线为空: {symbol}")
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
        raise ValueError(f"relay K 线解析失败: {symbol}")
    df["date"] = (
        pd.to_datetime(df["timestamp"], unit="s", utc=True)
        .dt.tz_convert("Asia/Shanghai")
        .dt.strftime("%Y-%m-%d")
    )
    out = df[["date", "open", "high", "low", "close", "volume"]].copy()
    out["open"] = pd.to_numeric(out["open"], errors="coerce")
    out["high"] = pd.to_numeric(out["high"], errors="coerce")
    out["low"] = pd.to_numeric(out["low"], errors="coerce")
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out["volume"] = pd.to_numeric(out["volume"], errors="coerce").fillna(0.0)
    return out.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)


def _source_days_for_period(period: str, count: int) -> int:
    count = max(int(count), 2)
    if period == "weekly":
        return min(max(count * 7 + 30, 260), 3000)
    if period == "monthly":
        return min(max(count * 31 + 90, 600), 4000)
    return min(max(count, 2), 3000)


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
    # 优先走内地 relay
    inland = _inland_relay_request("a-stock/kline", {"symbol": symbol, "days": days})
    if inland and inland.get("status") == "success" and inland.get("data"):
        df = pd.DataFrame(inland["data"])
        if not df.empty:
            logger.debug(f"[market_data] A 股 K 线走内地 relay: {symbol}")
            return df.tail(max(int(days), 2)).reset_index(drop=True)

    # 回退本地 akshare
    pure = symbol.split(".")[0]
    sina_symbol = ("sh" if pure.startswith(("6", "9")) else "sz") + pure
    try:
        df = _akshare_with_retry(lambda: ak.stock_zh_a_hist(symbol=pure, period="daily", adjust="qfq"))
        if df.empty:
            raise ValueError(f"A 股 K 线为空: {symbol}")
        df = df.rename(
            columns={
                "日期": "date",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
            }
        )
        return _normalize_ohlcv_df(df).tail(max(int(days), 2)).reset_index(drop=True)
    except Exception:
        try:
            df = _akshare_with_retry(lambda: ak.stock_zh_a_hist_tx(symbol=sina_symbol, adjust="qfq"))
            if df.empty:
                raise ValueError(f"A 股 K 线为空: {symbol}")
            return _normalize_ohlcv_df(df).tail(max(int(days), 2)).reset_index(drop=True)
        except Exception:
            df = _akshare_with_retry(lambda: ak.stock_zh_a_daily(symbol=sina_symbol, adjust="qfq"))
            if df.empty:
                raise ValueError(f"A 股 K 线为空: {symbol}")
            return _normalize_ohlcv_df(df).tail(max(int(days), 2)).reset_index(drop=True)


def _get_hk_stock_hist(symbol: str, days: int) -> pd.DataFrame:
    # 优先走内地 relay（akshare 港股数据）
    inland = _inland_relay_request("hk-stock/kline", {"symbol": symbol, "days": days})
    if inland and inland.get("status") == "success" and inland.get("data"):
        df = pd.DataFrame(inland["data"])
        if not df.empty:
            logger.debug(f"[market_data] 港股 K 线走内地 relay: {symbol}")
            return df.tail(max(int(days), 2)).reset_index(drop=True)

    pure = symbol.split(".")[0].zfill(5)
    df = _akshare_with_retry(lambda: ak.stock_hk_daily(symbol=pure, adjust="qfq"))
    if df.empty:
        raise ValueError(f"港股 K 线为空: {symbol}")
    return _normalize_ohlcv_df(df.reset_index(drop=True)).tail(max(int(days), 2)).reset_index(drop=True)


def _get_us_stock_hist(symbol: str, days: int) -> pd.DataFrame:
    # 优先走内地 relay（akshare 美股数据）
    inland = _inland_relay_request("us-stock/kline", {"symbol": symbol, "days": days})
    if inland and inland.get("status") == "success" and inland.get("data"):
        df = pd.DataFrame(inland["data"])
        if not df.empty:
            logger.debug(f"[market_data] 美股 K 线走内地 relay: {symbol}")
            return df.tail(max(int(days), 2)).reset_index(drop=True)

    df = _akshare_with_retry(lambda: ak.stock_us_daily(symbol=symbol.upper(), adjust="qfq"))
    if df.empty:
        raise ValueError(f"美股 K 线为空: {symbol}")
    return _normalize_ohlcv_df(df.reset_index(drop=True)).tail(max(int(days), 2)).reset_index(drop=True)


def _get_hist_df(symbol: str, market_type: MarketType, days: int) -> tuple[pd.DataFrame, str]:
    cache_key = f"{market_type.name}:{symbol}:{days}"
    cached = _cache_get("kline", cache_key)
    if cached is not None:
        return cached, "cache"

    if market_type == MarketType.A_STOCK:
        df = _get_a_stock_hist(symbol, days)
        _cache_set("kline", cache_key, df)
        return df, "akshare"

    relay = _relay_request("kline", symbol, {"period": "1d", "count": days})
    if relay:
        try:
            df = _parse_relay_kline(symbol, relay)
            if len(df) >= min(max(int(days * 0.5), 60), days):
                _cache_set("kline", cache_key, df)
                return df.tail(max(int(days), 2)).reset_index(drop=True), "relay"
        except Exception as exc:
            logger.warning(f"[market_data] relay K 线解析失败，回退 akshare: {symbol} {exc}")

    if market_type == MarketType.HK_STOCK:
        df = _get_hk_stock_hist(symbol, days)
    else:
        df = _get_us_stock_hist(symbol, days)
    _cache_set("kline", cache_key, df)
    return df, "akshare"


def _calc_change(price: float | None, prev_close: float | None) -> tuple[float | None, float | None]:
    if price is None or prev_close in (None, 0):
        return None, None
    change = price - prev_close
    change_pct = change / prev_close * 100
    return change, change_pct


_STOCK_NAME_MAP = {
    "600519": "贵州茅台", "000858": "五粮液", "601318": "中国平安",
    "002594": "比亚迪", "300750": "宁德时代", "600036": "招商银行",
    "601899": "紫金矿业", "000001": "平安银行",
    "00700": "腾讯控股", "09988": "阿里巴巴", "03690": "美团",
    "02318": "中国平安", "01398": "工商银行", "09999": "网易",
    "09618": "京东集团", "01810": "小米集团",
    "AAPL": "苹果", "MSFT": "微软", "NVDA": "英伟达",
    "GOOGL": "谷歌", "AMZN": "亚马逊", "TSLA": "特斯拉", "META": "Meta",
}


def _get_display_name(symbol: str) -> str:
    pure = symbol.split(".")[0]
    return _STOCK_NAME_MAP.get(pure, symbol)


def _bars_to_spot(symbol: str, market_type: MarketType) -> dict[str, Any]:
    bars = get_kline_data_raw(symbol, period="daily", count=2)
    if not bars:
        return {
            "symbol": symbol,
            "name": _get_display_name(symbol),
            "market_type": market_type.name,
            "price": None,
            "change": None,
            "change_pct": None,
            "is_fallback": True,
            "source": "none",
        }
    latest = bars[-1]
    prev_close = bars[-2]["close"] if len(bars) >= 2 else latest["close"]
    change, change_pct = _calc_change(latest["close"], prev_close)
    return {
        "symbol": symbol,
        "name": _get_display_name(symbol),
        "market_type": market_type.name,
        "price": latest["close"],
        "change": round(change, 4) if change is not None else None,
        "change_pct": round(change_pct, 4) if change_pct is not None else None,
        "is_fallback": True,
        "source": "kline",
    }


def _get_a_spot_table() -> pd.DataFrame:
    cached = _cache_get("overview", "a_spot_table")
    if cached is not None:
        if isinstance(cached, str) and cached == "__FAILED__":
            raise ValueError("A 股行情表暂时不可用（短期负缓存）")
        return cached
    # 优先走内地 relay
    inland = _inland_relay_request("a-stock/spot-table")
    if inland and inland.get("status") == "success" and inland.get("data"):
        df = pd.DataFrame(inland["data"])
        if not df.empty:
            return _cache_set("overview", "a_spot_table", df)
    try:
        df = _akshare_with_retry(ak.stock_zh_a_spot_em)
        return _cache_set("overview", "a_spot_table", df)
    except Exception:
        _cache_set("overview", "a_spot_table", "__FAILED__", ttl=30)
        raise


def _get_hk_spot_table() -> pd.DataFrame:
    cached = _cache_get("overview", "hk_spot_table")
    if cached is not None:
        return cached
    inland = _inland_relay_request("hk-stock/spot-table")
    if inland and inland.get("status") == "success" and inland.get("data"):
        df = pd.DataFrame(inland["data"])
        if not df.empty:
            return _cache_set("overview", "hk_spot_table", df)
    df = _akshare_with_retry(ak.stock_hk_spot_em)
    return _cache_set("overview", "hk_spot_table", df)


def _get_us_spot_table() -> pd.DataFrame:
    cached = _cache_get("overview", "us_spot_table")
    if cached is not None:
        return cached
    inland = _inland_relay_request("us-stock/spot-table")
    if inland and inland.get("status") == "success" and inland.get("data"):
        df = pd.DataFrame(inland["data"])
        if not df.empty:
            return _cache_set("overview", "us_spot_table", df)
    df = _akshare_with_retry(ak.stock_us_spot_em)
    return _cache_set("overview", "us_spot_table", df)


def _spot_from_a_share(symbol: str) -> dict[str, Any]:
    pure = symbol.split(".")[0]
    try:
        df = _get_a_spot_table()
        row = df[df["代码"].astype(str) == pure]
        if row.empty:
            raise ValueError(f"A 股实时行情未命中: {symbol}")
        item = row.iloc[0]
    except Exception:
        df = _akshare_with_retry(ak.stock_zh_a_spot)
        code_series = df["代码"].astype(str)
        row = df[(code_series == pure) | (code_series == f"sh{pure}") | (code_series == f"sz{pure}")]
        if row.empty:
            raise ValueError(f"A 股实时行情未命中: {symbol}")
        item = row.iloc[0]
    return {
        "symbol": symbol,
        "name": _safe_str(item.get("名称"), symbol),
        "market_type": MarketType.A_STOCK.name,
        "price": _safe_float(item.get("最新价")),
        "change": _safe_float(item.get("涨跌额")),
        "change_pct": _safe_float(item.get("涨跌幅")),
        "is_fallback": False,
        "source": "akshare",
    }


def _spot_from_hk_share(symbol: str) -> dict[str, Any]:
    df = _get_hk_spot_table()
    pure = symbol.split(".")[0].zfill(5)
    row = df[df["代码"].astype(str).str.zfill(5) == pure]
    if row.empty:
        raise ValueError(f"港股实时行情未命中: {symbol}")
    item = row.iloc[0]
    return {
        "symbol": symbol,
        "name": _safe_str(item.get("名称"), symbol),
        "market_type": MarketType.HK_STOCK.name,
        "price": _safe_float(item.get("最新价")),
        "change": _safe_float(item.get("涨跌额")),
        "change_pct": _safe_float(item.get("涨跌幅")),
        "is_fallback": False,
        "source": "akshare",
    }


def _spot_from_us_share(symbol: str) -> dict[str, Any]:
    df = _get_us_spot_table()
    code_series = df["代码"].astype(str).str.upper()
    matched = df[code_series == symbol.upper()]
    if matched.empty:
        matched = df[code_series.str.startswith(symbol.upper() + ".")]
    if matched.empty:
        raise ValueError(f"美股实时行情未命中: {symbol}")
    item = matched.iloc[0]
    return {
        "symbol": symbol,
        "name": _safe_str(item.get("名称"), symbol),
        "market_type": MarketType.US_STOCK.name,
        "price": _safe_float(item.get("最新价")),
        "change": _safe_float(item.get("涨跌额")),
        "change_pct": _safe_float(item.get("涨跌幅")),
        "is_fallback": False,
        "source": "akshare",
    }


def _build_market_payload(symbol: str, market_type: MarketType, ohlcv: pd.DataFrame, source: str) -> dict[str, Any]:
    records = ohlcv.to_dict(orient="records")
    latest = records[-1]
    prev_close = records[-2]["close"] if len(records) >= 2 else latest["close"]
    change, change_pct = _calc_change(float(latest["close"]), float(prev_close))
    return {
        "status": "success",
        "symbol": symbol,
        "market_type": market_type.name,
        "source": source,
        "count": len(records),
        "data": records,
        "latest_price": round(float(latest["close"]), 4),
        "change": round(change, 4) if change is not None else None,
        "change_pct": round(change_pct, 4) if change_pct is not None else None,
        "_ohlcv_json": ohlcv.to_json(orient="records", force_ascii=False),
    }


def _calc_indicators_from_ohlcv(ohlcv: pd.DataFrame) -> dict[str, Any]:
    df = ohlcv.copy()
    close = pd.to_numeric(df["close"], errors="coerce")
    high = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    volume = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)

    ma5 = close.rolling(5).mean()
    ma10 = close.rolling(10).mean()
    ma20 = close.rolling(20).mean()

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, pd.NA)
    rsi14 = 100 - (100 / (1 + rs))

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal

    mid = close.rolling(20).mean()
    std = close.rolling(20).std()
    upper = mid + 2 * std
    lower = mid - 2 * std

    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean()

    last_close = float(close.iloc[-1])
    avg_volume_20 = volume.tail(20).mean()
    volume_ratio = float(volume.iloc[-1] / avg_volume_20) if avg_volume_20 else None

    tech_signal = "neutral"
    if pd.notna(ma5.iloc[-1]) and pd.notna(ma20.iloc[-1]):
        if ma5.iloc[-1] > ma20.iloc[-1] and pd.notna(rsi14.iloc[-1]) and rsi14.iloc[-1] < 70:
            tech_signal = "bullish"
        elif ma5.iloc[-1] < ma20.iloc[-1] and pd.notna(rsi14.iloc[-1]) and rsi14.iloc[-1] > 30:
            tech_signal = "bearish"

    return {
        "status": "success",
        "indicators": {
            "MA5": round(float(ma5.iloc[-1]), 4) if pd.notna(ma5.iloc[-1]) else None,
            "MA10": round(float(ma10.iloc[-1]), 4) if pd.notna(ma10.iloc[-1]) else None,
            "MA20": round(float(ma20.iloc[-1]), 4) if pd.notna(ma20.iloc[-1]) else None,
            "RSI14": round(float(rsi14.iloc[-1]), 4) if pd.notna(rsi14.iloc[-1]) else None,
            "MACD": round(float(macd.iloc[-1]), 4) if pd.notna(macd.iloc[-1]) else None,
            "MACD_signal": round(float(signal.iloc[-1]), 4) if pd.notna(signal.iloc[-1]) else None,
            "MACD_hist": round(float(hist.iloc[-1]), 4) if pd.notna(hist.iloc[-1]) else None,
            "BOLL_mid": round(float(mid.iloc[-1]), 4) if pd.notna(mid.iloc[-1]) else None,
            "BOLL_upper": round(float(upper.iloc[-1]), 4) if pd.notna(upper.iloc[-1]) else None,
            "BOLL_lower": round(float(lower.iloc[-1]), 4) if pd.notna(lower.iloc[-1]) else None,
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
    result: list[dict[str, Any]] = []
    for item in items[: max(int(limit), 1)]:
        publisher = item.get("publisher")
        source = publisher.get("name") if isinstance(publisher, dict) else (publisher or item.get("source") or "Yahoo Finance")
        publish_time = item.get("providerPublishTime")
        result.append(
            {
                "title": _safe_str(item.get("title"))[:200],
                "source": _safe_str(source, "Yahoo Finance"),
                "time": datetime.fromtimestamp(int(publish_time)).isoformat() if publish_time else "",
            }
        )
    return _cache_set("news", cache_key, result)


@tool
def get_market_data(symbol: str, days: int = 180) -> str:
    """获取股票行情数据，返回统一的 OHLCV JSON。"""
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
    """获取股票基本面数据，返回统一 JSON。"""
    try:
        market_type, normalized = _normalize_symbol(symbol)
        if market_type == MarketType.A_STOCK:
            # 优先走内地 relay
            inland = _inland_relay_request("a-stock/fundamental", {"symbol": normalized})
            if inland and inland.get("status") == "success" and inland.get("data"):
                return _json_dumps({"status": "success", "symbol": normalized, "market_type": market_type.name, "source": "inland_relay", "data": inland["data"]})
            # 回退本地 akshare
            pure = normalized.split(".")[0]
            df = _akshare_with_retry(lambda: ak.stock_financial_abstract_ths(symbol=pure))
            if df.empty:
                raise ValueError("财务摘要为空")
            row = df.iloc[-1].to_dict()
            data = {
                "report_date": row.get("报告期") or row.get("报告日期") or row.get("日期"),
                "pe": _safe_float(row.get("市盈率")) or _safe_float(row.get("市盈率ttm")) or _safe_float(row.get("滚动市盈率")),
                "pb": _safe_float(row.get("市净率")),
                "roe": _safe_float(row.get("净资产收益率")) or _safe_float(row.get("ROE")),
                "eps": _safe_float(row.get("每股收益")) or _safe_float(row.get("基本每股收益")) or _safe_float(row.get("EPS")),
            }
            return _json_dumps({"status": "success", "symbol": normalized, "market_type": market_type.name, "source": "akshare", "data": data})

        data = _get_relay_fundamental(normalized)
        status = "success" if any(v is not None and v != "" for v in data.values()) else "partial"
        return _json_dumps({"status": status, "symbol": normalized, "market_type": market_type.name, "source": "relay", "data": data})
    except Exception as exc:
        logger.exception(f"[market_data] get_fundamental_data 失败: {symbol}")
        return _json_dumps({"status": "error", "symbol": symbol, "error": str(exc), "data": {}})


@tool
def get_stock_news(symbol: str, limit: int = 5) -> str:
    """获取个股相关新闻，返回统一 JSON。"""
    try:
        market_type, normalized = _normalize_symbol(symbol)
        news: list[dict[str, Any]] = []
        source = "akshare"
        if market_type == MarketType.A_STOCK:
            # 优先走内地 relay
            inland = _inland_relay_request("a-stock/news", {"symbol": normalized, "limit": limit})
            if inland and inland.get("news"):
                news = inland["news"]
                source = "inland_relay"
            else:
                pure = normalized.split(".")[0]
                df = _akshare_with_retry(lambda: ak.stock_news_em(symbol=pure))
                if not df.empty:
                    title_col = _pick_column(df, ["标题", "新闻标题", "title"]) or df.columns[0]
                    source_col = _pick_column(df, ["文章来源", "来源", "source"])
                    time_col = _pick_column(df, ["发布时间", "日期", "时间", "publish_time"])
                    for _, row in df.head(max(int(limit), 1)).iterrows():
                        news.append(
                            {
                                "title": _safe_str(row.get(title_col))[:200],
                                "source": _safe_str(row.get(source_col), "东方财富") if source_col else "东方财富",
                                "time": _safe_str(row.get(time_col)) if time_col else "",
                            }
                        )
        else:
            source = "relay"
            news = _get_relay_news(normalized, limit)

        status = "success" if news else "partial"
        return _json_dumps({"status": status, "symbol": normalized, "market_type": market_type.name, "source": source, "news": news})
    except Exception as exc:
        logger.exception(f"[market_data] get_stock_news 失败: {symbol}")
        return _json_dumps({"status": "error", "symbol": symbol, "error": str(exc), "news": []})


@tool
def calculate_technical_indicators(market_data_json: str) -> str:
    """根据行情 JSON 计算技术指标。"""
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
    if market_type == MarketType.UNKNOWN:
        return []
    try:
        source_days = _source_days_for_period(period, count)
        daily_ohlcv, _ = _get_hist_df(normalized, market_type, source_days)
        ohlcv = _resample_ohlcv(daily_ohlcv, period.lower(), count)
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
    if market_type == MarketType.UNKNOWN:
        return _bars_to_spot(symbol, MarketType.UNKNOWN)

    cache_key = f"{market_type.name}:{normalized}"
    cached = _cache_get("spot", cache_key)
    if cached is not None:
        return cached

    try:
        if market_type == MarketType.A_STOCK:
            result = _spot_from_a_share(normalized)
        elif market_type == MarketType.HK_STOCK:
            result = _spot_from_hk_share(normalized)
        else:
            result = _spot_from_us_share(normalized)
        return _cache_set("spot", cache_key, result)
    except Exception as exc:
        logger.warning(f"[market_data] 实时行情回退日线: {normalized} {exc}")
        result = _bars_to_spot(normalized, market_type)
        return _cache_set("spot", cache_key, result)


def get_batch_quotes_raw(symbols: list[str], market: str | None = None) -> list[dict[str, Any]]:
    """批量获取行情，优先走内地 relay 批量接口（一次请求），回退逐只 K 线"""
    # 优先走内地 relay 批量 K 线接口
    symbols_str = ",".join(symbols)
    inland = _inland_relay_request("batch-kline", {"symbols": symbols_str, "days": 2}, timeout=120)
    if inland and inland.get("status") == "success" and inland.get("data"):
        results = []
        for item in inland["data"]:
            market_type, _ = _normalize_symbol(item.get("symbol", ""))
            results.append({
                "symbol": item.get("symbol", ""),
                "name": item.get("name", item.get("symbol", "")),
                "market_type": market_type.name,
                "price": item.get("price"),
                "change": item.get("change"),
                "change_pct": item.get("change_pct"),
                "is_fallback": True,
                "source": item.get("source", "kline"),
            })
        return results

    # 回退：逐只用 K 线收盘价
    return [_bars_to_spot(sym, _normalize_symbol(sym)[0]) for sym in symbols]


def _index_from_cn_table(df: pd.DataFrame, code: str, name: str) -> dict[str, Any] | None:
    row = df[df["代码"].astype(str) == code]
    if row.empty:
        return None
    item = row.iloc[0]
    return {
        "symbol": code,
        "name": name,
        "price": _safe_float(item.get("最新价")),
        "change": _safe_float(item.get("涨跌额")),
        "change_pct": _safe_float(item.get("涨跌幅")),
        "is_fallback": False,
        "source": "akshare",
    }


def _index_from_relay(symbol: str, name: str) -> dict[str, Any]:
    payload = _relay_request("kline", symbol, {"period": "1d", "count": 2})
    if not payload:
        raise ValueError(f"relay 指数为空: {symbol}")
    bars = _parse_relay_kline(symbol, payload)
    if bars.empty:
        raise ValueError(f"relay 指数解析失败: {symbol}")
    latest = bars.iloc[-1]
    prev_close = bars.iloc[-2]["close"] if len(bars) >= 2 else latest["close"]
    change, change_pct = _calc_change(float(latest["close"]), float(prev_close))
    return {
        "symbol": symbol,
        "name": name,
        "price": round(float(latest["close"]), 4),
        "change": round(change, 4) if change is not None else None,
        "change_pct": round(change_pct, 4) if change_pct is not None else None,
        "is_fallback": False,
        "source": "relay",
    }


def get_market_indices_raw() -> list[dict[str, Any]]:
    cache_key = "indices"
    cached = _cache_get("overview", cache_key)
    if cached is not None:
        return cached

    results: list[dict[str, Any]] = []

    # 优先走内地 relay 获取 A 股指数
    inland = _inland_relay_request("indices")
    if inland and inland.get("status") == "success" and inland.get("data"):
        for item in inland["data"]:
            item["is_fallback"] = False
            results.append(item)
    else:
        try:
            cn_df = _akshare_with_retry(lambda: ak.stock_zh_index_spot_em(symbol="沪深重要指数"))
            for code, name in [("000001", "上证指数"), ("399001", "深证成指"), ("399006", "创业板指"), ("000300", "沪深300")]:
                item = _index_from_cn_table(cn_df, code, name)
                if item:
                    results.append(item)
        except Exception as exc:
            logger.warning(f"[market_data] A 股指数获取失败: {exc}")
            try:
                cn_df = _akshare_with_retry(ak.stock_zh_index_spot_sina)
                for code, name in [("sh000001", "上证指数"), ("sz399001", "深证成指"), ("sz399006", "创业板指"), ("sh000300", "沪深300")]:
                    row = cn_df[cn_df["代码"].astype(str) == code]
                    if row.empty:
                        continue
                    item = row.iloc[0]
                    results.append(
                        {
                            "symbol": code[-6:],
                            "name": name,
                            "price": _safe_float(item.get("最新价")),
                            "change": _safe_float(item.get("涨跌额")),
                            "change_pct": _safe_float(item.get("涨跌幅")),
                            "is_fallback": False,
                            "source": "akshare",
                        }
                    )
            except Exception as sina_exc:
                logger.warning(f"[market_data] A 股指数新浪回退失败: {sina_exc}")

    for symbol, name in [("^HSI", "恒生指数"), ("^GSPC", "标普500"), ("^IXIC", "纳斯达克")]:
        try:
            results.append(_index_from_relay(symbol, name))
        except Exception as exc:
            logger.warning(f"[market_data] 全球指数获取失败 {symbol}: {exc}")

    if not results:
        results = [
            {"symbol": "000001", "name": "上证指数", "price": 0.0, "change": 0.0, "change_pct": 0.0, "is_fallback": True, "source": "fallback"},
            {"symbol": "399001", "name": "深证成指", "price": 0.0, "change": 0.0, "change_pct": 0.0, "is_fallback": True, "source": "fallback"},
            {"symbol": "^IXIC", "name": "纳斯达克", "price": 0.0, "change": 0.0, "change_pct": 0.0, "is_fallback": True, "source": "fallback"},
        ]

    return _cache_set("overview", cache_key, results)


def get_market_news_raw(limit: int = 20) -> list[dict[str, Any]]:
    # 优先走内地 relay
    inland = _inland_relay_request("market-news", {"limit": limit})
    if inland and inland.get("status") == "success" and inland.get("data"):
        return inland["data"]

    try:
        df = _akshare_with_retry(lambda: ak.stock_info_global_cls(symbol="全部"))
        result: list[dict[str, Any]] = []
        sorted_df = df.sort_values(["发布日期", "发布时间"], ascending=False)
        for _, row in sorted_df.head(max(int(limit), 1)).iterrows():
            publish_at = f"{row.get('发布日期', '')} {row.get('发布时间', '')}".strip()
            result.append(
                {
                    "title": _safe_str(row.get("标题"))[:200],
                    "source": "财联社",
                    "time": publish_at,
                    "url": "https://www.cls.cn/telegraph",
                }
            )
        return result
    except Exception as exc:
        logger.warning(f"[market_data] get_market_news_raw 失败: {exc}")
        return []


def get_sector_data_raw() -> list[dict[str, Any]]:
    cache_key = "sectors"
    cached = _cache_get("overview", cache_key)
    if cached is not None:
        return cached

    # 走内地 relay（板块数据只能在内地服务器用 akshare 获取）
    inland = _inland_relay_request("sectors")
    if inland and inland.get("status") == "success" and inland.get("data"):
        return _cache_set("overview", cache_key, inland["data"])

    if ak is None:
        return []

    try:
        df = _akshare_with_retry(ak.stock_board_industry_name_em)
    except Exception as exc:
        logger.warning(f"[market_data] 行业板块获取失败，回退概念板块: {exc}")
        try:
            df = _akshare_with_retry(ak.stock_board_concept_name_em)
        except Exception as concept_exc:
            logger.warning(f"[market_data] get_sector_data_raw 失败: {concept_exc}")
            return []

    result = []
    for _, row in df.sort_values("涨跌幅", ascending=False).head(12).iterrows():
        result.append(
            {
                "name": _safe_str(row.get("板块名称")),
                "sector": _safe_str(row.get("板块名称")),
                "change_pct": float(_safe_float(row.get("涨跌幅")) or 0.0),
                "leader": _safe_str(row.get("领涨股票")),
                "up_count": int(_safe_float(row.get("上涨家数")) or 0),
                "down_count": int(_safe_float(row.get("下跌家数")) or 0),
            }
        )
    return _cache_set("overview", cache_key, result)


def get_market_sentiment_raw() -> dict[str, Any]:
    cache_key = "sentiment"
    cached = _cache_get("overview", cache_key)
    if cached is not None:
        return cached

    # 走内地 relay（涨停/跌停统计需要全量 A 股表，只能在内地服务器算）
    inland = _inland_relay_request("sentiment")
    if inland and inland.get("status") == "success" and inland.get("data"):
        return _cache_set("overview", cache_key, inland["data"])

    # 内地 relay 不可用时回退本地 akshare（仅本地开发环境）
    if ak is None:
        return _cache_set("overview", cache_key, {
            "limit_up": "--", "limit_down": "--", "volume": "--",
            "north_flow": "--", "north_flow_raw": None,
        })

    limit_up = "--"
    limit_down = "--"
    volume = "--"
    north_flow = "--"
    north_flow_raw = None

    try:
        df = _get_a_spot_table()
        pct = pd.to_numeric(df["涨跌幅"], errors="coerce")
        limit_up = str(int((pct >= 9.8).sum()))
        limit_down = str(int((pct <= -9.8).sum()))
        total_amount = pd.to_numeric(df["成交额"], errors="coerce").fillna(0).sum()
        volume = f"{total_amount / 1e8:.2f}亿"
    except Exception as exc:
        logger.warning(f"[market_data] 市场情绪-A股统计失败: {exc}")

    try:
        north_df = _akshare_with_retry(ak.stock_hsgt_fund_flow_summary_em)
        if not north_df.empty:
            latest_date = north_df["交易日"].max()
            latest_df = north_df[north_df["交易日"] == latest_date]
            value = pd.to_numeric(latest_df["成交净买额"], errors="coerce").sum()
            north_flow_raw = float(value)
            north_flow = f"{value:+.2f}亿"
    except Exception as exc:
        logger.warning(f"[market_data] 市场情绪-北向资金失败: {exc}")

    result = {
        "limit_up": limit_up,
        "limit_down": limit_down,
        "volume": volume,
        "north_flow": north_flow,
        "north_flow_raw": north_flow_raw,
    }
    return _cache_set("overview", cache_key, result)


def get_deep_financial_data_via_relay(symbol: str) -> dict[str, Any]:
    market_type, normalized = _normalize_symbol(symbol)
    if market_type == MarketType.A_STOCK:
        return get_deep_financial_data(normalized)
    payload = _relay_request("deep", normalized) or {}
    result = (((payload.get("quoteSummary") or {}).get("result")) or [{}])[0]
    return {"symbol": normalized, "raw": result, "revenue_composition": {}, "performance_trend": {}}


def get_deep_financial_data(symbol: str) -> dict[str, Any]:
    return {"symbol": symbol, "revenue_composition": {}, "performance_trend": {}}
