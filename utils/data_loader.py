"""
utils/data_loader.py — 多市场历史行情加载器

数据源路由:
  A股  → akshare.stock_zh_a_hist()   (前复权日线)
  港股  → akshare.stock_hk_hist()     (前复权日线)
  美股  → yfinance.Ticker.history()   (日线)

严格红线:
  - 不引入任何加密货币相关库（无 CCXT / Binance / ccxt）
  - 不连接任何真实交易所 API
  - 仅支持 A_STOCK / HK_STOCK / US_STOCK，其余返回空 DataFrame

统一输出格式 (DataFrame):
  timestamp | open | high | low | close | volume
  ──────────┼──────┼──────┼─────┼───────┼────────
  datetime  | float| float|float| float | float

内置能力:
  - 简单 TTL 内存缓存（默认 5 分钟），同一 symbol+days 不重复请求 API
  - 指数退避重试（最多 3 次），应对网络抖动
  - 对 akshare / yfinance 接口返回的列名做健壮映射
"""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd
from loguru import logger

from config import config
from .market_classifier import MarketClassifier, MarketType


# ── 简单 TTL 缓存（避免同一请求短时间内重复调用 API）────────────
_CACHE: Dict[str, Tuple[float, pd.DataFrame]] = {}
_CACHE_TTL_SECONDS = 300   # 5 分钟


# ── 代理隔离上下文管理器 ─────────────────────────────────────────
# 在 TUN/系统代理环境下，国内数据源（akshare 请求新浪/东方财富）的流量若被
# 代理路由到海外出口，国内服务器会丢弃该连接，造成无限期挂起。
# 通过临时设置 NO_PROXY=* 强制绕过代理直连，执行完毕后恢复原值。
@contextmanager
def _bypass_proxy():
    """临时强制所有连接绕过代理直连（用于国内数据源请求）。"""
    proxy_keys = ("NO_PROXY", "no_proxy", "HTTP_PROXY", "http_proxy",
                  "HTTPS_PROXY", "https_proxy")
    saved = {k: os.environ.get(k) for k in proxy_keys}
    try:
        os.environ["NO_PROXY"]    = "*"
        os.environ["no_proxy"]    = "*"
        os.environ.pop("HTTP_PROXY",  None)
        os.environ.pop("http_proxy",  None)
        os.environ.pop("HTTPS_PROXY", None)
        os.environ.pop("https_proxy", None)
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _cache_key(symbol: str, days: int) -> str:
    return f"{symbol}:{days}"


def _cache_get(key: str) -> Optional[pd.DataFrame]:
    if key in _CACHE:
        ts, df = _CACHE[key]
        if time.time() - ts < _CACHE_TTL_SECONDS:
            return df
        del _CACHE[key]
    return None


def _cache_set(key: str, df: pd.DataFrame) -> None:
    _CACHE[key] = (time.time(), df)


# ── 指数退避重试装饰器 ───────────────────────────────────────────
def _retry(func, *args, max_tries: int = 3, base_wait: float = 1.5, **kwargs):
    """以指数退避方式重试 func，最多 max_tries 次。"""
    for attempt in range(1, max_tries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if attempt == max_tries:
                raise
            wait = base_wait ** attempt
            logger.warning(f"[retry {attempt}/{max_tries}] {e}，{wait:.1f}s 后重试...")
            time.sleep(wait)


class DataLoader:
    """
    多市场数据加载器

    支持市场: A股 (akshare) / 港股 (akshare) / 美股 (yfinance)
    不支持: 加密货币（已从系统移除）
    """

    def __init__(self):
        self.classifier = MarketClassifier()
        logger.info("✅ DataLoader 初始化完成（A股/港股: akshare | 美股: yfinance）")

    # ══════════════════════════════════════════════════════════
    # 公共接口
    # ══════════════════════════════════════════════════════════

    def get_historical_data(
        self,
        symbol: str,
        days: int = 180,
    ) -> pd.DataFrame:
        """
        获取历史日线行情（统一接口）

        Args:
            symbol: 标的代码，例如 600519.SH / 00700.HK / AAPL
            days:   向前追溯的自然日数（默认 180 天）

        Returns:
            标准化 DataFrame，列固定为:
            [timestamp, open, high, low, close, volume]
            失败时返回空 DataFrame（不抛出异常）
        """
        market_type, normalized = self.classifier.classify(symbol)

        # UNKNOWN 或不受支持的市场类型（加密货币已从系统移除）
        if market_type not in (MarketType.A_STOCK, MarketType.HK_STOCK, MarketType.US_STOCK):
            logger.error(f"❌ {symbol}: 不支持的市场类型 {market_type.value}（仅支持 A股/港股/美股）")
            return pd.DataFrame()

        # 命中缓存直接返回
        key = _cache_key(normalized, days)
        cached = _cache_get(key)
        if cached is not None:
            logger.debug(f"[cache hit] {normalized} days={days}")
            return cached.copy()

        try:
            if market_type == MarketType.A_STOCK:
                df = self._get_a_stock_data(normalized, days)
            elif market_type == MarketType.HK_STOCK:
                df = self._get_hk_stock_data(normalized, days)
            elif market_type == MarketType.US_STOCK:
                df = self._get_us_stock_data(normalized, days)
            else:
                logger.error(f"❌ 未知市场类型: {market_type}")
                return pd.DataFrame()

            if df is None or df.empty:
                logger.error(f"❌ {symbol} 数据为空")
                return pd.DataFrame()

            df = self._standardize(df, market_type)

            if df.empty:
                logger.error(f"❌ {symbol} 标准化后数据为空，请检查列名映射")
                return pd.DataFrame()

            _cache_set(key, df)
            logger.info(f"✅ {symbol} 获取成功: {len(df)} 条 | "
                        f"{df['timestamp'].iloc[0].date()} → {df['timestamp'].iloc[-1].date()}")
            return df

        except Exception as e:
            logger.error(f"❌ {symbol} 数据获取异常: {e}")
            return pd.DataFrame()

    def get_latest_price(self, symbol: str) -> Optional[float]:
        """
        获取最新收盘价（从历史数据末行取）

        Returns:
            float 价格，失败返回 None
        """
        df = self.get_historical_data(symbol, days=10)
        if df.empty:
            return None
        try:
            return float(df["close"].iloc[-1])
        except Exception as e:
            logger.error(f"get_latest_price 失败: {e}")
            return None

    # ══════════════════════════════════════════════════════════
    # 内部：各市场数据拉取
    # ══════════════════════════════════════════════════════════

    def _get_a_stock_data(self, symbol: str, days: int) -> pd.DataFrame:
        """
        A股日线数据 — akshare.stock_zh_a_daily()  (前复权)

        说明：stock_zh_a_hist 接口已不稳定（RemoteDisconnected），
        改用 stock_zh_a_daily，一次拉全量后本地截断日期范围。

        akshare stock_zh_a_daily 返回列:
          date | open | high | low | close | volume | amount | ...

        symbol 格式：600519.SH → sh600519，002812.SZ → sz002812
        """
        import akshare as ak

        # 去掉后缀并加交易所前缀：600519.SH → sh600519
        parts = symbol.split(".")
        code  = parts[0]
        suffix = parts[1].upper() if len(parts) > 1 else ""
        prefix = "sh" if suffix == "SH" else "sz"
        ak_symbol = f"{prefix}{code}"

        cutoff = datetime.now() - timedelta(days=days)

        logger.debug(f"[akshare A股 daily] ak_symbol={ak_symbol} cutoff={cutoff.date()}")

        with _bypass_proxy():
            logger.info(f"[A股] 👉 开始请求 akshare (stock_zh_a_daily): {ak_symbol}")
            _t0 = time.time()
            df = _retry(ak.stock_zh_a_daily, symbol=ak_symbol, adjust="qfq")
            logger.info(f"[A股] ✅ akshare 请求完成，耗时 {time.time()-_t0:.2f}s，共 {len(df)} 行")

        # 本地按日期截断
        if df is not None and not df.empty:
            date_col = _find_col(df, ["date", "Date", "日期"])
            if date_col:
                df[date_col] = pd.to_datetime(df[date_col])
                df = df[df[date_col] >= cutoff].copy()

        return df

    def _get_hk_stock_data(self, symbol: str, days: int) -> pd.DataFrame:
        """
        港股日线数据 — akshare.stock_hk_daily()  (前复权)

        说明：stock_hk_hist 接口已不稳定（RemoteDisconnected），
        改用 stock_hk_daily，一次拉全量后本地截断日期范围。

        akshare stock_hk_daily 返回列:
          date | open | high | low | close | volume

        symbol 格式示例: 00700.HK → 传入 akshare 为 "00700"
        """
        import akshare as ak

        # 去掉市场后缀：00700.HK → 00700
        code   = symbol.split(".")[0]
        cutoff = datetime.now() - timedelta(days=days)

        logger.debug(f"[akshare 港股 daily] code={code} cutoff={cutoff.date()}")

        with _bypass_proxy():
            logger.info(f"[港股] 👉 开始请求 akshare (stock_hk_daily): {code}")
            _t0 = time.time()
            df = _retry(ak.stock_hk_daily, symbol=code, adjust="qfq")
            logger.info(f"[港股] ✅ akshare 请求完成，耗时 {time.time()-_t0:.2f}s，共 {len(df)} 行")

        # 本地按日期截断
        if df is not None and not df.empty:
            date_col = _find_col(df, ["date", "Date", "日期", "时间"])
            if date_col:
                df[date_col] = pd.to_datetime(df[date_col])
                df = df[df[date_col] >= cutoff].copy()

        return df

    def _get_us_stock_data(self, symbol: str, days: int) -> pd.DataFrame:
        """
        美股日线数据 — yfinance.Ticker.history()

        yfinance 返回 DataFrame:
          - index: DatetimeIndex（名称为 'Date'）
          - columns: Open, High, Low, Close, Volume, Dividends, Stock Splits

        处理要点: 必须先 reset_index() 将日期从 index 变为普通列。
        """
        import yfinance as yf

        end_dt   = datetime.now()
        start_dt = end_dt - timedelta(days=days)

        logger.debug(f"[yfinance 美股] symbol={symbol} {start_dt.date()}~{end_dt.date()}")

        logger.info(f"[美股] 👉 开始请求 yfinance: symbol={symbol}")
        _t0 = time.time()
        ticker = yf.Ticker(symbol)
        df = _retry(
            ticker.history,
            start=start_dt,
            end=end_dt,
            auto_adjust=True,    # 自动复权（等价于前复权）
        )
        logger.info(f"[美股] ✅ yfinance 请求完成，耗时 {time.time()-_t0:.2f}s")

        # yfinance 的日期在 index 里，需要 reset_index 变成列
        if df is not None and not df.empty:
            df = df.reset_index()
            # reset_index 后列名可能是 'Date' 或 'Datetime'（Ticker.history 返回 'Date'）

        return df

    # ══════════════════════════════════════════════════════════
    # 内部：标准化 DataFrame
    # ══════════════════════════════════════════════════════════

    def _standardize(self, df: pd.DataFrame, market_type: MarketType) -> pd.DataFrame:
        """
        将不同来源的 DataFrame 统一为:
          [timestamp, open, high, low, close, volume]

        列名优先级映射（按顺序尝试）:
          timestamp: 日期 / Date / Datetime / date / index
          open:      开盘 / Open / open
          high:      最高 / High / high
          low:       最低 / Low / low
          close:     收盘 / Close / close
          volume:    成交量 / Volume / volume
        """
        if df is None or df.empty:
            return pd.DataFrame()

        df = df.copy()

        # ── 1. 如果索引是日期类型，先 reset 进来（防漏网之鱼）────
        if isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index()

        # ── 2. 列名归一化映射 ────────────────────────────────────
        CANDIDATES = {
            "timestamp": ["日期", "date", "Date", "Datetime", "datetime", "时间", "index"],
            "open":      ["开盘", "open", "Open"],
            "high":      ["最高", "high", "High"],
            "low":       ["最低", "low", "Low"],
            "close":     ["收盘", "close", "Close"],
            "volume":    ["成交量", "volume", "Volume"],
        }

        rename_map: dict = {}
        for target, candidates in CANDIDATES.items():
            if target in df.columns:
                continue   # 已经是标准名
            col = _find_col(df, candidates)
            if col:
                rename_map[col] = target

        df = df.rename(columns=rename_map)

        # ── 3. 检查必要列 ────────────────────────────────────────
        required = ["timestamp", "open", "high", "low", "close", "volume"]
        missing  = [c for c in required if c not in df.columns]
        if missing:
            logger.warning(f"列名映射后仍缺少: {missing}  (现有列: {df.columns.tolist()})")
            return pd.DataFrame()

        df = df[required].copy()

        # ── 4. 类型转换 ──────────────────────────────────────────
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # ── 5. 清理：去掉 NaN 行、按时间升序排列 ─────────────────
        df = df.dropna(subset=["timestamp", "close"])
        df = df.sort_values("timestamp").reset_index(drop=True)

        return df


# ══════════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════════

def _find_col(df: pd.DataFrame, candidates: list) -> Optional[str]:
    """在 df.columns 中找到第一个匹配的候选列名，找不到返回 None。"""
    for c in candidates:
        if c in df.columns:
            return c
    return None


# ══════════════════════════════════════════════════════════════
# 快速功能测试（直接运行此文件）
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    from loguru import logger as _log
    _log.add("logs/data_loader_test.log", rotation="10 MB")

    loader = DataLoader()

    test_cases = [
        ("600519.SH", "A股 · 贵州茅台"),
        ("000858.SZ", "A股 · 五粮液"),
        ("00700.HK",  "港股 · 腾讯"),
        ("09988.HK",  "港股 · 阿里巴巴"),
        ("AAPL",      "美股 · 苹果"),
        ("TSLA",      "美股 · 特斯拉"),
    ]

    for symbol, label in test_cases:
        print(f"\n{'='*55}")
        print(f"  {label}  ({symbol})")
        print("="*55)

        df = loader.get_historical_data(symbol, days=30)
        if df.empty:
            print("  ❌ 数据获取失败")
            continue

        print(f"  行数     : {len(df)}")
        print(f"  日期范围 : {df['timestamp'].iloc[0].date()} → {df['timestamp'].iloc[-1].date()}")
        print(f"  最新收盘 : {df['close'].iloc[-1]:.4f}")
        print(f"  成交量   : {df['volume'].iloc[-1]:,.0f}")
        print(f"  数据预览 :\n{df.tail(3).to_string(index=False)}")

        time.sleep(0.8)   # 礼貌性请求间隔
