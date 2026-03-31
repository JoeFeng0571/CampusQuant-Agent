"""
inland_relay/server.py — 内地数据中继服务

部署在阿里云内地服务器（47.108.191.110:8001），为香港主站提供：
  1. akshare 全量 A 股 / 港股 / 美股数据接口
  2. Chroma + BM25 混合 RAG 知识库检索
  3. 财联社 / 新浪 / 澎湃等国内新闻源

所有接口均需 Bearer token 鉴权。
"""
from __future__ import annotations

import json
import os
import pickle
import re
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import akshare as ak
import pandas as pd
import requests
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

# ════════════════════════════════════════════════════════════════
# 配置
# ════════════════════════════════════════════════════════════════

RELAY_TOKEN = os.getenv("INLAND_RELAY_TOKEN", "CQ_Relay_Secure_2026_YQ")

# RAG 数据目录（内地服务器上的路径，部署时按需修改）
_BASE_DIR = Path(__file__).parent
_DATA_DIR = _BASE_DIR / "data"
_CHROMA_DIR = _DATA_DIR / "chroma_db"
_BM25_PKL = _DATA_DIR / "bm25_index.pkl"
_COLLECTION = "trading_knowledge"

# DashScope Embedding（RAG 查询时需要）
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DASHSCOPE_EMBEDDING_MODEL = os.getenv("DASHSCOPE_EMBEDDING_MODEL", "text-embedding-v3")

# ════════════════════════════════════════════════════════════════
# 缓存
# ════════════════════════════════════════════════════════════════

_CACHE: dict[str, tuple[float, Any]] = {}
_TTL = {"spot": 60, "kline": 300, "fundamental": 3600, "news": 900, "overview": 120}


def _cache_get(ns: str, key: str) -> Any:
    item = _CACHE.get(f"{ns}:{key}")
    if not item:
        return None
    if time.time() > item[0]:
        _CACHE.pop(f"{ns}:{key}", None)
        return None
    return item[1]


def _cache_set(ns: str, key: str, value: Any, ttl: int | None = None) -> Any:
    _CACHE[f"{ns}:{key}"] = (time.time() + (ttl or _TTL.get(ns, 300)), value)
    return value


# ════════════════════════════════════════════════════════════════
# 工具函数
# ════════════════════════════════════════════════════════════════

def _safe_float(value: Any) -> float | None:
    if value in (None, "", "-", "--"):
        return None
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


def _akshare_with_retry(fn, retries: int = 2, delay: float = 0.8) -> Any:
    last_error = None
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


def _pick_column(df: pd.DataFrame, aliases: list[str]) -> str | None:
    cols = {str(col).strip().lower(): str(col) for col in df.columns}
    for alias in aliases:
        if alias.strip().lower() in cols:
            return cols[alias.strip().lower()]
    return None


def _json_serial(obj: Any) -> str:
    """JSON 序列化辅助，处理 pandas Timestamp 等特殊类型"""
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    return str(obj)


# ════════════════════════════════════════════════════════════════
# 鉴权
# ════════════════════════════════════════════════════════════════

def verify_token(request: Request) -> None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    if auth[7:] != RELAY_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")


# ════════════════════════════════════════════════════════════════
# RAG 单例
# ════════════════════════════════════════════════════════════════

_ensemble_retriever = None
_bm25_retriever = None
_chroma_retriever = None


def _init_rag() -> None:
    """启动时加载 RAG 索引"""
    global _ensemble_retriever, _bm25_retriever, _chroma_retriever

    # BM25
    if _BM25_PKL.exists():
        try:
            with open(_BM25_PKL, "rb") as f:
                _bm25_retriever = pickle.load(f)
            logger.info(f"BM25 加载完成: {_BM25_PKL}")
        except Exception as e:
            logger.error(f"BM25 加载失败: {e}")

    # Chroma
    embedding_model = None
    if DASHSCOPE_API_KEY and len(DASHSCOPE_API_KEY) > 20:
        try:
            from langchain_openai import OpenAIEmbeddings
            embedding_model = OpenAIEmbeddings(
                model=DASHSCOPE_EMBEDDING_MODEL,
                api_key=DASHSCOPE_API_KEY,
                base_url=DASHSCOPE_BASE_URL,
                check_embedding_ctx_length=False,
            )
            logger.info(f"Embedding 模型: DashScope {DASHSCOPE_EMBEDDING_MODEL}")
        except Exception as e:
            logger.warning(f"DashScope Embedding 初始化失败: {e}")

    if embedding_model and _CHROMA_DIR.exists():
        try:
            import chromadb
            try:
                from langchain_chroma import Chroma
            except ImportError:
                from langchain_community.vectorstores import Chroma

            client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
            names = [c.name for c in client.list_collections()]
            if _COLLECTION in names:
                vs = Chroma(
                    client=client,
                    collection_name=_COLLECTION,
                    embedding_function=embedding_model,
                )
                _chroma_retriever = vs.as_retriever(search_type="similarity", search_kwargs={"k": 5})
                logger.info("Chroma 向量检索器加载完成")
            else:
                logger.warning(f"Chroma 集合 '{_COLLECTION}' 不存在")
        except Exception as e:
            logger.error(f"Chroma 加载失败: {e}")

    # Ensemble
    if _bm25_retriever and _chroma_retriever:
        try:
            try:
                from langchain_classic.retrievers.ensemble import EnsembleRetriever
            except ImportError:
                from langchain.retrievers import EnsembleRetriever
            _ensemble_retriever = EnsembleRetriever(
                retrievers=[_bm25_retriever, _chroma_retriever],
                weights=[0.5, 0.5],
            )
            logger.info("EnsembleRetriever (BM25 50% + Chroma 50%) 就绪")
        except Exception as e:
            logger.warning(f"EnsembleRetriever 组装失败: {e}")
            _ensemble_retriever = _chroma_retriever or _bm25_retriever
    else:
        _ensemble_retriever = _chroma_retriever or _bm25_retriever
        if _ensemble_retriever:
            logger.warning("RAG 降级: 仅单路检索器可用")


# ════════════════════════════════════════════════════════════════
# akshare 数据函数
# ════════════════════════════════════════════════════════════════

def _normalize_ohlcv_df(df: pd.DataFrame) -> pd.DataFrame:
    aliases = {
        "date": ["日期", "date", "时间", "trade_date"],
        "open": ["开盘", "open", "今开", "开盘价"],
        "high": ["最高", "high", "最高价"],
        "low": ["最低", "low", "最低价"],
        "close": ["收盘", "close", "最新价", "close_price"],
        "volume": ["成交量", "volume", "vol"],
    }
    mapped = {}
    for target, options in aliases.items():
        col = _pick_column(df, options)
        if not col:
            raise ValueError(f"缺少列: {target}")
        mapped[target] = col

    out = pd.DataFrame({
        "date": pd.to_datetime(df[mapped["date"]], errors="coerce"),
        "open": pd.to_numeric(df[mapped["open"]], errors="coerce"),
        "high": pd.to_numeric(df[mapped["high"]], errors="coerce"),
        "low": pd.to_numeric(df[mapped["low"]], errors="coerce"),
        "close": pd.to_numeric(df[mapped["close"]], errors="coerce"),
        "volume": pd.to_numeric(df[mapped["volume"]], errors="coerce"),
    })
    out["volume"] = out["volume"].fillna(0.0)
    out = out.dropna(subset=["date", "open", "high", "low", "close"])
    out = out.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    return out.reset_index(drop=True)


def _get_a_stock_hist(symbol: str, days: int) -> pd.DataFrame:
    pure = symbol.split(".")[0]
    sina_symbol = ("sh" if pure.startswith(("6", "9")) else "sz") + pure
    try:
        df = _akshare_with_retry(lambda: ak.stock_zh_a_hist(symbol=pure, period="daily", adjust="qfq"))
        if df.empty:
            raise ValueError(f"A 股 K 线为空: {symbol}")
        df = df.rename(columns={"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "volume"})
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
    pure = symbol.split(".")[0].zfill(5)
    df = _akshare_with_retry(lambda: ak.stock_hk_daily(symbol=pure, adjust="qfq"))
    if df.empty:
        raise ValueError(f"港股 K 线为空: {symbol}")
    return _normalize_ohlcv_df(df.reset_index(drop=True)).tail(max(int(days), 2)).reset_index(drop=True)


def _get_us_stock_hist(symbol: str, days: int) -> pd.DataFrame:
    df = _akshare_with_retry(lambda: ak.stock_us_daily(symbol=symbol.upper(), adjust="qfq"))
    if df.empty:
        raise ValueError(f"美股 K 线为空: {symbol}")
    return _normalize_ohlcv_df(df.reset_index(drop=True)).tail(max(int(days), 2)).reset_index(drop=True)


# ════════════════════════════════════════════════════════════════
# 新闻抓取
# ════════════════════════════════════════════════════════════════

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

_hot_news_cache: dict[str, list[dict]] = {}
_hot_news_ts: float = 0.0
_hot_news_lock = threading.Lock()
_HOT_NEWS_TTL = 15 * 60


def _fetch_cailian() -> list[dict]:
    try:
        df = ak.stock_info_global_cls(symbol="全部")
        if df is None or df.empty:
            return []
        results = []
        for i, row in enumerate(df.head(3).itertuples(), start=1):
            title = str(getattr(row, "内容", getattr(row, "标题", "")))[:200]
            results.append({"title": title, "url": "https://www.cls.cn/telegraph", "rank": i})
        return results
    except Exception as e:
        logger.warning(f"财联社抓取失败: {e}")
        return []


def _fetch_sina_live() -> list[dict]:
    try:
        resp = requests.get(
            "https://zhibo.sina.com.cn/api/zhibo/feed?zhibo_id=152&tag_id=0&dire=f&dtime=&pagesize=10&otype=json",
            headers={**_HEADERS, "Referer": "https://finance.sina.com.cn/"},
            timeout=8,
        )
        items = resp.json().get("result", {}).get("data", {}).get("feed", {}).get("list", [])
        results = []
        for item in items:
            text = re.sub(r"<[^>]+>", "", item.get("rich_text", "")).strip()[:200]
            if text and len(results) < 3:
                results.append({"title": text, "url": "https://finance.sina.com.cn/", "rank": len(results) + 1})
        return results
    except Exception as e:
        logger.warning(f"新浪快讯抓取失败: {e}")
        return []


def _fetch_thepaper() -> list[dict]:
    try:
        resp = requests.get(
            "https://cache.thepaper.cn/contentapi/wwwIndex/rightSidebar",
            headers=_HEADERS, timeout=8,
        )
        hot_list = resp.json().get("data", {}).get("hotNews", [])[:3]
        results = []
        for i, item in enumerate(hot_list, start=1):
            title = item.get("name", "")[:200]
            cont_id = item.get("contId", "")
            link = f"https://www.thepaper.cn/newsDetail_forward_{cont_id}" if cont_id else "https://www.thepaper.cn/"
            results.append({"title": title, "url": link, "rank": i})
        return results
    except Exception as e:
        logger.warning(f"澎湃新闻抓取失败: {e}")
        return []


_NEWS_FETCHERS = {
    "cailian": (_fetch_cailian, {"label": "财联社", "color": "#e74c3c", "icon": "news"}),
    "sina_live": (_fetch_sina_live, {"label": "新浪财经", "color": "#e8312f", "icon": "bolt"}),
    "thepaper": (_fetch_thepaper, {"label": "澎湃新闻", "color": "#2ecc71", "icon": "pin"}),
}


def _refresh_hot_news() -> None:
    global _hot_news_ts
    new_data = {}
    for source, (fetcher, _) in _NEWS_FETCHERS.items():
        try:
            new_data[source] = fetcher()
        except Exception as e:
            logger.error(f"热榜 {source} 刷新异常: {e}")
            new_data[source] = []
    with _hot_news_lock:
        _hot_news_cache.update(new_data)
        _hot_news_ts = time.time()


# ════════════════════════════════════════════════════════════════
# FastAPI 应用
# ════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("内地 Relay 服务启动，初始化 RAG 索引...")
    _init_rag()
    yield
    logger.info("内地 Relay 服务关闭")


app = FastAPI(title="CampusQuant Inland Relay", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ════════════════════════════════════════════════════════════════
# 健康检查（无需鉴权）
# ════════════════════════════════════════════════════════════════

@app.get("/health")
def health():
    return {
        "status": "ok",
        "rag_available": _ensemble_retriever is not None,
        "bm25_available": _bm25_retriever is not None,
        "chroma_available": _chroma_retriever is not None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ════════════════════════════════════════════════════════════════
# A 股 K 线
# ════════════════════════════════════════════════════════════════

@app.get("/relay/a-stock/kline", dependencies=[Depends(verify_token)])
def a_stock_kline(symbol: str, days: int = 180):
    cache_key = f"a:{symbol}:{days}"
    cached = _cache_get("kline", cache_key)
    if cached is not None:
        return cached
    try:
        df = _get_a_stock_hist(symbol, days)
        data = {"status": "success", "symbol": symbol, "count": len(df), "data": df.to_dict(orient="records")}
        return _cache_set("kline", cache_key, data)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ════════════════════════════════════════════════════════════════
# 港股 K 线（akshare 回退源，香港主站优先用 relay/yfinance）
# ════════════════════════════════════════════════════════════════

@app.get("/relay/hk-stock/kline", dependencies=[Depends(verify_token)])
def hk_stock_kline(symbol: str, days: int = 180):
    cache_key = f"hk:{symbol}:{days}"
    cached = _cache_get("kline", cache_key)
    if cached is not None:
        return cached
    try:
        df = _get_hk_stock_hist(symbol, days)
        data = {"status": "success", "symbol": symbol, "count": len(df), "data": df.to_dict(orient="records")}
        return _cache_set("kline", cache_key, data)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ════════════════════════════════════════════════════════════════
# 美股 K 线（akshare 回退源）
# ════════════════════════════════════════════════════════════════

@app.get("/relay/us-stock/kline", dependencies=[Depends(verify_token)])
def us_stock_kline(symbol: str, days: int = 180):
    cache_key = f"us:{symbol}:{days}"
    cached = _cache_get("kline", cache_key)
    if cached is not None:
        return cached
    try:
        df = _get_us_stock_hist(symbol, days)
        data = {"status": "success", "symbol": symbol, "count": len(df), "data": df.to_dict(orient="records")}
        return _cache_set("kline", cache_key, data)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ════════════════════════════════════════════════════════════════
# A 股实时行情表（批量）
# ════════════════════════════════════════════════════════════════

@app.get("/relay/a-stock/spot-table", dependencies=[Depends(verify_token)])
def a_stock_spot_table():
    cached = _cache_get("overview", "a_spot_table")
    if cached is not None:
        if isinstance(cached, str) and cached == "__FAILED__":
            raise HTTPException(status_code=502, detail="A 股行情表暂时不可用")
        return {"status": "success", "count": len(cached), "data": cached.to_dict(orient="records")}
    try:
        df = _akshare_with_retry(ak.stock_zh_a_spot_em)
        _cache_set("overview", "a_spot_table", df)
        return {"status": "success", "count": len(df), "data": df.to_dict(orient="records")}
    except Exception as e:
        _cache_set("overview", "a_spot_table", "__FAILED__", ttl=30)
        raise HTTPException(status_code=502, detail=str(e))


# ════════════════════════════════════════════════════════════════
# 港股 / 美股实时行情表
# ════════════════════════════════════════════════════════════════

@app.get("/relay/hk-stock/spot-table", dependencies=[Depends(verify_token)])
def hk_stock_spot_table():
    cached = _cache_get("overview", "hk_spot_table")
    if cached is not None:
        return {"status": "success", "count": len(cached), "data": cached.to_dict(orient="records")}
    try:
        df = _akshare_with_retry(ak.stock_hk_spot_em)
        _cache_set("overview", "hk_spot_table", df)
        return {"status": "success", "count": len(df), "data": df.to_dict(orient="records")}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/relay/us-stock/spot-table", dependencies=[Depends(verify_token)])
def us_stock_spot_table():
    cached = _cache_get("overview", "us_spot_table")
    if cached is not None:
        return {"status": "success", "count": len(cached), "data": cached.to_dict(orient="records")}
    try:
        df = _akshare_with_retry(ak.stock_us_spot_em)
        _cache_set("overview", "us_spot_table", df)
        return {"status": "success", "count": len(df), "data": df.to_dict(orient="records")}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ════════════════════════════════════════════════════════════════
# A 股指数
# ════════════════════════════════════════════════════════════════

@app.get("/relay/indices", dependencies=[Depends(verify_token)])
def market_indices():
    cached = _cache_get("overview", "cn_indices")
    if cached is not None:
        return {"status": "success", "data": cached}

    results = []
    try:
        cn_df = _akshare_with_retry(lambda: ak.stock_zh_index_spot_em(symbol="沪深重要指数"))
        for code, name in [("000001", "上证指数"), ("399001", "深证成指"), ("399006", "创业板指"), ("000300", "沪深300")]:
            row = cn_df[cn_df["代码"].astype(str) == code]
            if row.empty:
                continue
            item = row.iloc[0]
            results.append({
                "symbol": code, "name": name,
                "price": _safe_float(item.get("最新价")),
                "change": _safe_float(item.get("涨跌额")),
                "change_pct": _safe_float(item.get("涨跌幅")),
                "source": "akshare",
            })
    except Exception as exc:
        logger.warning(f"A 股指数获取失败: {exc}")
        try:
            cn_df = _akshare_with_retry(ak.stock_zh_index_spot_sina)
            for code, name in [("sh000001", "上证指数"), ("sz399001", "深证成指"), ("sz399006", "创业板指"), ("sh000300", "沪深300")]:
                row = cn_df[cn_df["代码"].astype(str) == code]
                if row.empty:
                    continue
                item = row.iloc[0]
                results.append({
                    "symbol": code[-6:], "name": name,
                    "price": _safe_float(item.get("最新价")),
                    "change": _safe_float(item.get("涨跌额")),
                    "change_pct": _safe_float(item.get("涨跌幅")),
                    "source": "akshare",
                })
        except Exception as sina_exc:
            logger.warning(f"A 股指数新浪回退失败: {sina_exc}")

    _cache_set("overview", "cn_indices", results)
    return {"status": "success", "data": results}


# ════════════════════════════════════════════════════════════════
# A 股财务摘要
# ════════════════════════════════════════════════════════════════

@app.get("/relay/a-stock/fundamental", dependencies=[Depends(verify_token)])
def a_stock_fundamental(symbol: str):
    cached = _cache_get("fundamental", symbol)
    if cached is not None:
        return {"status": "success", "symbol": symbol, "data": cached}
    try:
        pure = symbol.split(".")[0]
        df = _akshare_with_retry(lambda: ak.stock_financial_abstract_ths(symbol=pure))
        if df.empty:
            raise ValueError("财务摘要为空")
        row = df.iloc[-1].to_dict()
        data = {
            "report_date": _safe_str(row.get("报告期") or row.get("报告日期") or row.get("日期")),
            "pe": _safe_float(row.get("市盈率")) or _safe_float(row.get("市盈率ttm")) or _safe_float(row.get("滚动市盈率")),
            "pb": _safe_float(row.get("市净率")),
            "roe": _safe_float(row.get("净资产收益率")) or _safe_float(row.get("ROE")),
            "eps": _safe_float(row.get("每股收益")) or _safe_float(row.get("基本每股收益")) or _safe_float(row.get("EPS")),
        }
        _cache_set("fundamental", symbol, data)
        return {"status": "success", "symbol": symbol, "data": data}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ════════════════════════════════════════════════════════════════
# A 股个股新闻
# ════════════════════════════════════════════════════════════════

@app.get("/relay/a-stock/news", dependencies=[Depends(verify_token)])
def a_stock_news(symbol: str, limit: int = 5):
    try:
        pure = symbol.split(".")[0]
        df = _akshare_with_retry(lambda: ak.stock_news_em(symbol=pure))
        if df.empty:
            return {"status": "partial", "symbol": symbol, "news": []}
        title_col = _pick_column(df, ["标题", "新闻标题", "title"]) or df.columns[0]
        source_col = _pick_column(df, ["文章来源", "来源", "source"])
        time_col = _pick_column(df, ["发布时间", "日期", "时间", "publish_time"])
        news = []
        for _, row in df.head(max(int(limit), 1)).iterrows():
            news.append({
                "title": _safe_str(row.get(title_col))[:200],
                "source": _safe_str(row.get(source_col), "东方财富") if source_col else "东方财富",
                "time": _safe_str(row.get(time_col)) if time_col else "",
            })
        return {"status": "success", "symbol": symbol, "news": news}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ════════════════════════════════════════════════════════════════
# 财联社快讯（市场页用）
# ════════════════════════════════════════════════════════════════

@app.get("/relay/market-news", dependencies=[Depends(verify_token)])
def market_news(limit: int = 20):
    try:
        df = _akshare_with_retry(lambda: ak.stock_info_global_cls(symbol="全部"))
        result = []
        sorted_df = df.sort_values(["发布日期", "发布时间"], ascending=False)
        for _, row in sorted_df.head(max(int(limit), 1)).iterrows():
            publish_at = f"{row.get('发布日期', '')} {row.get('发布时间', '')}".strip()
            result.append({
                "title": _safe_str(row.get("标题"))[:200],
                "source": "财联社",
                "time": publish_at,
                "url": "https://www.cls.cn/telegraph",
            })
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ════════════════════════════════════════════════════════════════
# 板块数据
# ════════════════════════════════════════════════════════════════

@app.get("/relay/sectors", dependencies=[Depends(verify_token)])
def sector_data():
    cached = _cache_get("overview", "sectors")
    if cached is not None:
        return {"status": "success", "data": cached}
    try:
        df = _akshare_with_retry(ak.stock_board_industry_name_em)
    except Exception:
        try:
            df = _akshare_with_retry(ak.stock_board_concept_name_em)
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e))

    result = []
    for _, row in df.sort_values("涨跌幅", ascending=False).head(12).iterrows():
        result.append({
            "name": _safe_str(row.get("板块名称")),
            "sector": _safe_str(row.get("板块名称")),
            "change_pct": float(_safe_float(row.get("涨跌幅")) or 0.0),
            "leader": _safe_str(row.get("领涨股票")),
            "up_count": int(_safe_float(row.get("上涨家数")) or 0),
            "down_count": int(_safe_float(row.get("下跌家数")) or 0),
        })
    _cache_set("overview", "sectors", result)
    return {"status": "success", "data": result}


# ════════════════════════════════════════════════════════════════
# 市场情绪（涨停/跌停/成交量/北向资金）
# ════════════════════════════════════════════════════════════════

@app.get("/relay/sentiment", dependencies=[Depends(verify_token)])
def market_sentiment():
    cached = _cache_get("overview", "sentiment")
    if cached is not None:
        return {"status": "success", "data": cached}

    limit_up = "--"
    limit_down = "--"
    volume = "--"
    north_flow = "--"
    north_flow_raw = None

    try:
        df = _akshare_with_retry(ak.stock_zh_a_spot_em)
        pct = pd.to_numeric(df["涨跌幅"], errors="coerce")
        limit_up = str(int((pct >= 9.8).sum()))
        limit_down = str(int((pct <= -9.8).sum()))
        total_amount = pd.to_numeric(df["成交额"], errors="coerce").fillna(0).sum()
        volume = f"{total_amount / 1e8:.2f}亿"
    except Exception as exc:
        logger.warning(f"市场情绪-A股统计失败: {exc}")

    try:
        north_df = _akshare_with_retry(ak.stock_hsgt_fund_flow_summary_em)
        if not north_df.empty:
            latest_date = north_df["交易日"].max()
            latest_df = north_df[north_df["交易日"] == latest_date]
            value = pd.to_numeric(latest_df["成交净买额"], errors="coerce").sum()
            north_flow_raw = float(value)
            north_flow = f"{value:+.2f}亿"
    except Exception as exc:
        logger.warning(f"市场情绪-北向资金失败: {exc}")

    result = {
        "limit_up": limit_up, "limit_down": limit_down,
        "volume": volume, "north_flow": north_flow, "north_flow_raw": north_flow_raw,
    }
    _cache_set("overview", "sentiment", result)
    return {"status": "success", "data": result}


# ════════════════════════════════════════════════════════════════
# 热榜新闻（财联社 + 新浪 + 澎湃）
# ════════════════════════════════════════════════════════════════

@app.get("/relay/hot-news", dependencies=[Depends(verify_token)])
def hot_news(force_refresh: bool = False):
    global _hot_news_ts
    need_refresh = force_refresh or (time.time() - _hot_news_ts > _HOT_NEWS_TTL)
    if need_refresh:
        _refresh_hot_news()

    with _hot_news_lock:
        result = []
        for source, (_, meta) in _NEWS_FETCHERS.items():
            result.append({
                "source": source,
                "label": meta["label"],
                "icon": meta["icon"],
                "color": meta["color"],
                "items": list(_hot_news_cache.get(source, [])),
                "fetched_at": datetime.fromtimestamp(_hot_news_ts, tz=timezone.utc).isoformat() if _hot_news_ts else None,
            })
    return {"status": "success", "data": result}


# ════════════════════════════════════════════════════════════════
# RAG 知识库检索
# ════════════════════════════════════════════════════════════════

_MARKET_HINTS = {
    "A_STOCK": "A股 中国 上证 深证 政策 行业景气度 ETF定投",
    "HK_STOCK": "港股 香港 恒生 南向资金 估值折价 安全边际",
    "US_STOCK": "美股 纳斯达克 标普500 美联储 EPS FCF 盈利",
}


@app.get("/relay/rag/search", dependencies=[Depends(verify_token)])
def rag_search(query: str, market_type: str = "ALL", max_length: int = 1500):
    if _ensemble_retriever is None:
        return {
            "status": "partial",
            "local_results": "暂不可用（检索器未初始化）",
            "doc_count": 0,
        }

    market_hint = _MARKET_HINTS.get(market_type, "")
    enhanced_query = f"{query} {market_hint}".strip()

    try:
        raw_docs = _ensemble_retriever.invoke(enhanced_query)
        if not raw_docs:
            return {"status": "partial", "local_results": "未检索到相关内容", "doc_count": 0}

        # 去重
        seen: set[str] = set()
        unique_docs = []
        for doc in raw_docs:
            fp = doc.page_content[:80]
            if fp not in seen:
                seen.add(fp)
                unique_docs.append(doc)

        snippets = []
        for i, doc in enumerate(unique_docs[:5], 1):
            source = doc.metadata.get("source", "内置知识库")
            page = doc.metadata.get("page", "")
            src_str = source + (f"  p.{page}" if page != "" else "")
            snippets.append({
                "index": i,
                "source": src_str,
                "content": doc.page_content.strip(),
            })

        # 组装格式化文本（与原 knowledge_base.py 输出格式兼容）
        text_parts = []
        for s in snippets:
            text_parts.append(f"  [{s['index']}] 来源: {s['source']}\n      {s['content']}")
        local_text = f"【本地知识库 — 混合检索结果（BM25 + 向量语义）】\n" + "\n\n".join(text_parts)

        if max_length > 0:
            local_text = local_text[:max_length]

        return {"status": "success", "local_results": local_text, "doc_count": len(snippets)}
    except Exception as e:
        logger.error(f"RAG 检索异常: {e}")
        return {"status": "error", "local_results": f"检索异常: {e}", "doc_count": 0}


# ════════════════════════════════════════════════════════════════
# 入口
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
