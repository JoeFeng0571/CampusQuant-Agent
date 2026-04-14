"""
scripts/download_universe_history.py

一次性下载 bench/backtest/universe.yaml 里的 20 支股票 2023-01-01 → 2025-12-31
三年 OHLCV 数据,存为 bench/data/ohlcv/{market}/{symbol}.parquet

用法:
    .venv/Scripts/python.exe -m scripts.download_universe_history

零成本: akshare(A股/港股) + yfinance(美股)都是免费数据源。
预计耗时: ~7 分钟 (20 支 × 2-5 秒/支 + 重试).

相关文档: BACKEND_ALGO_OPTIMIZATION.md §5.3.2 (v2.2)
"""
from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path
from typing import Any

# ── 禁用 Windows 系统代理(否则 requests 会自动从系统注册表读 127.0.0.1:2080 之类)───
# akshare 的东财接口对代理敏感,本地 clash/v2ray 代理没开时会报 ProxyError。
# yfinance 走 Yahoo 接口不受影响。必须在 import pandas/akshare/yfinance 前设置。
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)

# Windows 下 requests 会从系统注册表读代理,NO_PROXY=* 不一定被尊重。
# 直接 monkey-patch urllib.request.getproxies 返回空 dict。
import urllib.request
urllib.request.getproxies = lambda: {}
urllib.request.getproxies_environment = lambda: {}

import pandas as pd
import yaml
from loguru import logger

# Force UTF-8 stdout on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_BASE_DIR = Path(__file__).parent.parent
_UNIVERSE_YAML = _BASE_DIR / "bench" / "backtest" / "universe.yaml"
_OHLCV_DIR = _BASE_DIR / "bench" / "data" / "ohlcv"
_ERROR_LOG = _BASE_DIR / "bench" / "data" / "universe_errors.log"

START_DATE = "2023-01-01"
END_DATE = "2025-12-31"

# 从 config 拿 inland relay 地址(A 股走 relay 绕过本地反爬)
try:
    from config import config as _cfg
    _INLAND_RELAY_URL = (_cfg.INLAND_RELAY_BASE_URL or "").rstrip("/")
    _INLAND_RELAY_TOKEN = (_cfg.INLAND_RELAY_TOKEN or "").strip()
except Exception:
    _INLAND_RELAY_URL = ""
    _INLAND_RELAY_TOKEN = ""


# ════════════════════════════════════════════════════════════════
# 数据源适配器
# ════════════════════════════════════════════════════════════════

def _download_a_stock_via_relay(symbol: str, start: str, end: str) -> pd.DataFrame:
    """
    A 股: 走内地 relay (47.108.191.110) 绕过本地反爬。
    relay 接口 /relay/a-stock/kline 只支持 days 参数,拿 2000 天后按日期过滤。
    """
    import requests
    if not _INLAND_RELAY_URL or not _INLAND_RELAY_TOKEN:
        raise RuntimeError("INLAND_RELAY_BASE_URL/TOKEN not configured, can't fetch A-stock")

    url = f"{_INLAND_RELAY_URL}/relay/a-stock/kline"
    # 1200 个交易日 ≈ 5 年自然日,用 1200 参数让 relay 拉足够久的历史
    params = {"symbol": symbol, "days": 1200}
    headers = {"Authorization": f"Bearer {_INLAND_RELAY_TOKEN}"}
    resp = requests.get(url, params=params, headers=headers, timeout=30, proxies={})
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("status") != "success":
        raise RuntimeError(f"relay error: {payload}")
    rows = payload.get("data") or []
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    # 标准化列
    rename = {"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "volume"}
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    # 按日期过滤
    if "date" not in df.columns:
        raise RuntimeError(f"relay payload missing 'date' column, got columns: {list(df.columns)}")
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df[(df["date"] >= start) & (df["date"] <= end)].copy()
    keep = ["date", "open", "high", "low", "close", "volume"]
    df = df[[c for c in keep if c in df.columns]].reset_index(drop=True)
    return df


def _download_a_stock_direct(symbol: str, start: str, end: str) -> pd.DataFrame:
    """A 股: akshare stock_zh_a_hist 直连(本地反爬时失效,留做兜底)"""
    import akshare as ak
    pure = symbol.lstrip("sh").lstrip("sz").split(".")[0]
    start_clean = start.replace("-", "")
    end_clean = end.replace("-", "")
    df = ak.stock_zh_a_hist(
        symbol=pure, period="daily", adjust="qfq",
        start_date=start_clean, end_date=end_clean,
    )
    return _normalize_akshare_df(df)


def _download_a_stock(symbol: str, start: str, end: str) -> pd.DataFrame:
    """A 股: 优先走 relay (绕过本地反爬),失败再兜底 akshare 直连"""
    if _INLAND_RELAY_URL and _INLAND_RELAY_TOKEN:
        try:
            return _download_a_stock_via_relay(symbol, start, end)
        except Exception as exc:
            logger.warning(f"    relay 失败,兜底 akshare 直连: {exc}")
    return _download_a_stock_direct(symbol, start, end)


def _download_hk_stock(symbol: str, start: str, end: str) -> pd.DataFrame:
    """港股: akshare stock_hk_daily (前复权)"""
    import akshare as ak
    # "00700.HK" → "00700"
    pure = symbol.split(".")[0]
    df = ak.stock_hk_daily(symbol=pure, adjust="qfq")
    if df is not None and not df.empty:
        df = _normalize_akshare_df(df)
        # akshare 港股接口不支持日期过滤,手动截取
        df["date"] = pd.to_datetime(df["date"])
        df = df[(df["date"] >= start) & (df["date"] <= end)]
    return df


def _download_us_stock(symbol: str, start: str, end: str) -> pd.DataFrame:
    """美股: yfinance (调整后价格)"""
    import yfinance as yf
    ticker = yf.Ticker(symbol)
    # auto_adjust=True 返回调整后 OHLC
    df = ticker.history(start=start, end=end, auto_adjust=True)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.reset_index()
    # 标准化列名 (Date → date, etc.)
    df.columns = [c.lower() for c in df.columns]
    if "date" not in df.columns and "index" in df.columns:
        df = df.rename(columns={"index": "date"})
    # 只保留标准 OHLCV 列
    keep = ["date", "open", "high", "low", "close", "volume"]
    df = df[[c for c in keep if c in df.columns]].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df


def _normalize_akshare_df(df: pd.DataFrame) -> pd.DataFrame:
    """akshare 返回的 df 中文列名 → 英文标准"""
    if df is None or df.empty:
        return pd.DataFrame()
    alias_map = {
        "日期": "date", "date": "date",
        "开盘": "open", "open": "open",
        "最高": "high", "high": "high",
        "最低": "low", "low": "low",
        "收盘": "close", "close": "close",
        "成交量": "volume", "volume": "volume",
    }
    rename = {}
    for col in df.columns:
        key = str(col).lower()
        if key in alias_map:
            rename[col] = alias_map[key]
    df = df.rename(columns=rename)
    keep = ["date", "open", "high", "low", "close", "volume"]
    df = df[[c for c in keep if c in df.columns]].copy()
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df


# ════════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════════

def _load_universe() -> list[dict[str, Any]]:
    with open(_UNIVERSE_YAML, encoding="utf-8") as f:
        u = yaml.safe_load(f)
    universe = []
    for group_name, group in u["groups"].items():
        market = {"a_stock": "A", "hk_stock": "HK", "us_stock": "US"}[group_name]
        for stock in group["stocks"]:
            universe.append({
                "symbol": stock["symbol"],
                "name": stock["name"],
                "market": market,
                "sector": stock.get("sector", ""),
            })
    return universe


def _retry(fn, retries: int = 3, delay: float = 1.0) -> Any:
    last_exc = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            wait = delay * (1.5 ** attempt)
            logger.warning(f"    retry {attempt + 1}/{retries} failed: {exc}, sleeping {wait:.1f}s")
            time.sleep(wait)
    raise last_exc


def _download_one(item: dict[str, Any]) -> tuple[bool, str]:
    """
    下载单个股票,返回 (success, message)
    """
    symbol = item["symbol"]
    name = item["name"]
    market = item["market"]

    out_dir = _OHLCV_DIR / market.lower()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{symbol.replace('.', '_')}.parquet"

    if out_path.exists():
        try:
            existing = pd.read_parquet(out_path)
            if len(existing) > 100:
                return True, f"SKIP (already have {len(existing)} rows)"
        except Exception:
            pass  # 损坏就重下

    try:
        if market == "A":
            df = _retry(lambda: _download_a_stock(symbol, START_DATE, END_DATE))
        elif market == "HK":
            df = _retry(lambda: _download_hk_stock(symbol, START_DATE, END_DATE))
        elif market == "US":
            df = _retry(lambda: _download_us_stock(symbol, START_DATE, END_DATE))
        else:
            return False, f"unknown market: {market}"

        if df is None or df.empty:
            return False, "empty dataframe"

        df.to_parquet(out_path, index=False, compression="snappy")
        return True, f"OK ({len(df)} rows, {out_path.stat().st_size // 1024} KB)"
    except Exception as exc:
        return False, f"FAIL: {exc}"


def main() -> None:
    logger.info(f"[universe download] start={START_DATE} end={END_DATE}")
    logger.info(f"  universe yaml: {_UNIVERSE_YAML}")
    logger.info(f"  output dir: {_OHLCV_DIR}")
    print()

    _OHLCV_DIR.mkdir(parents=True, exist_ok=True)
    _ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)

    universe = _load_universe()
    logger.info(f"loaded {len(universe)} stocks")

    results: list[tuple[str, str, bool, str]] = []
    errors: list[str] = []
    t0 = time.time()

    for i, item in enumerate(universe, 1):
        symbol = item["symbol"]
        name = item["name"]
        market = item["market"]
        print(f"[{i:>2}/{len(universe)}] {market} {symbol:<10} {name} ...", end=" ", flush=True)
        ok, msg = _download_one(item)
        print(msg)
        results.append((symbol, market, ok, msg))
        if not ok:
            errors.append(f"{market} {symbol} ({name}): {msg}")

    # 汇总
    elapsed = time.time() - t0
    n_ok = sum(1 for _, _, ok, _ in results if ok)
    n_fail = len(results) - n_ok

    print()
    print("=" * 70)
    print(f"  Summary: {n_ok} OK / {n_fail} FAIL  ({elapsed:.1f}s)")
    if errors:
        print()
        print("Errors:")
        for e in errors:
            print(f"  - {e}")
        # 落盘
        with open(_ERROR_LOG, "w", encoding="utf-8") as f:
            f.write(f"# download errors {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            for e in errors:
                f.write(f"{e}\n")
        print(f"\n  Errors logged to: {_ERROR_LOG}")

    # 总 parquet 大小
    total_bytes = 0
    for p in _OHLCV_DIR.rglob("*.parquet"):
        total_bytes += p.stat().st_size
    print(f"  Total parquet size: {total_bytes / 1024:.1f} KB ({total_bytes / 1024 / 1024:.2f} MB)")

    if n_fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
