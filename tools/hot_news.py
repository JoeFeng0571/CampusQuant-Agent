"""
tools/hot_news.py

多平台市场快讯聚合。

设计目标：
1. 单个来源失败时不清空该来源原有缓存。
2. 所有来源都失败时也要返回可展示的兜底数据，避免前端大片空白。
3. 保持现有接口不变：get_hot_news(force_refresh=False)、refresh_in_background()。
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

import requests
from loguru import logger

_CACHE_TTL = 15 * 60
_cache_lock = threading.Lock()
_cache_data: dict[str, list[dict]] = {}
_cache_ts: float = 0.0

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}

_SOURCE_META = {
    "cailian": {"label": "财联社", "color": "#e74c3c", "icon": "📰"},
    "wallstreetcn": {"label": "华尔街见闻", "color": "#f5a623", "icon": "📣"},
    "sina_live": {"label": "新浪财经", "color": "#e8312f", "icon": "🛰"},
    "thepaper": {"label": "澎湃新闻", "color": "#2ecc71", "icon": "🗞"},
}

_SOURCE_FALLBACKS: dict[str, list[dict]] = {
    "cailian": [
        {"title": "市场波动加大，关注成交量与风险偏好变化", "url": "https://www.cls.cn/telegraph", "rank": 1},
        {"title": "多家机构继续关注科技与高股息板块轮动", "url": "https://www.cls.cn/telegraph", "rank": 2},
        {"title": "宏观数据披露窗口临近，市场等待进一步指引", "url": "https://www.cls.cn/telegraph", "rank": 3},
    ],
    "wallstreetcn": [
        {"title": "海外市场关注利率路径与企业盈利预期变化", "url": "https://wallstreetcn.com/", "rank": 1},
        {"title": "资金重新评估成长与防御板块的配置节奏", "url": "https://wallstreetcn.com/", "rank": 2},
        {"title": "主要指数震荡整理，板块分化继续扩大", "url": "https://wallstreetcn.com/", "rank": 3},
    ],
    "sina_live": [
        {"title": "沪深两市热点轮动加快，短线情绪保持活跃", "url": "https://finance.sina.com.cn/", "rank": 1},
        {"title": "市场聚焦业绩与估值匹配度，资金偏好更均衡", "url": "https://finance.sina.com.cn/", "rank": 2},
        {"title": "权重与题材交替发力，指数整体延续震荡格局", "url": "https://finance.sina.com.cn/", "rank": 3},
    ],
    "thepaper": [
        {"title": "宏观政策与产业景气度仍是市场关注焦点", "url": "https://www.thepaper.cn/", "rank": 1},
        {"title": "资金面总体平稳，防御与成长风格继续拉锯", "url": "https://www.thepaper.cn/", "rank": 2},
        {"title": "投资者继续跟踪外部市场扰动与汇率走势", "url": "https://www.thepaper.cn/", "rank": 3},
    ],
}


def _normalize_items(items: list[dict], default_url: str) -> list[dict]:
    normalized: list[dict] = []
    for idx, item in enumerate(items[:3], start=1):
        title = str(item.get("title") or "").strip()[:200]
        if not title:
            continue
        normalized.append(
            {
                "title": title,
                "url": str(item.get("url") or default_url),
                "rank": idx,
            }
        )
    return normalized


def _fetch_cailian() -> list[dict]:
    try:
        import akshare as ak

        df = ak.stock_info_global_cls(symbol="全部")
        if df is None or df.empty:
            return []

        items: list[dict] = []
        for row in df.head(3).itertuples():
            title = str(getattr(row, "内容", getattr(row, "标题", ""))).strip()
            if title:
                items.append({"title": title, "url": "https://www.cls.cn/telegraph"})
        return _normalize_items(items, "https://www.cls.cn/telegraph")
    except Exception as exc:
        logger.warning(f"[hot_news] 财联社抓取失败: {exc}")
        return []


def _fetch_wallstreetcn() -> list[dict]:
    try:
        resp = requests.get(
            "https://api.wallstreetcn.com/apiv1/content/articles?channel=a-stock&limit=5&accept=json",
            headers={**_HEADERS, "Referer": "https://wallstreetcn.com/"},
            timeout=8,
        )
        resp.raise_for_status()
        payload = resp.json()
        items = payload.get("data", {}).get("items", [])[:3]
        return _normalize_items(
            [{"title": item.get("title", ""), "url": item.get("uri", "https://wallstreetcn.com/")} for item in items],
            "https://wallstreetcn.com/",
        )
    except Exception as exc:
        logger.warning(f"[hot_news] 华尔街见闻抓取失败: {exc}")
        return []


def _fetch_sina_live() -> list[dict]:
    import re

    try:
        resp = requests.get(
            "https://zhibo.sina.com.cn/api/zhibo/feed?zhibo_id=152&tag_id=0&dire=f&dtime=&pagesize=10&otype=json",
            headers={**_HEADERS, "Referer": "https://finance.sina.com.cn/"},
            timeout=8,
            proxies={"http": "", "https": ""},
        )
        resp.raise_for_status()
        payload = resp.json()
        feed = payload.get("result", {}).get("data", {}).get("feed", {}).get("list", [])
        items: list[dict] = []
        for item in feed:
            title = re.sub(r"<[^>]+>", "", str(item.get("rich_text", ""))).strip()
            if title:
                items.append({"title": title, "url": "https://finance.sina.com.cn/"})
            if len(items) >= 3:
                break
        return _normalize_items(items, "https://finance.sina.com.cn/")
    except Exception as exc:
        logger.warning(f"[hot_news] 新浪快讯抓取失败: {exc}")
        return []


def _fetch_thepaper() -> list[dict]:
    try:
        resp = requests.get(
            "https://cache.thepaper.cn/contentapi/wwwIndex/rightSidebar",
            headers=_HEADERS,
            timeout=8,
            proxies={"http": "", "https": ""},
        )
        resp.raise_for_status()
        payload = resp.json()
        hot_list = payload.get("data", {}).get("hotNews", [])[:3]
        items = []
        for item in hot_list:
            cont_id = item.get("contId", "")
            url = f"https://www.thepaper.cn/newsDetail_forward_{cont_id}" if cont_id else "https://www.thepaper.cn/"
            items.append({"title": item.get("name", ""), "url": url})
        return _normalize_items(items, "https://www.thepaper.cn/")
    except Exception as exc:
        logger.warning(f"[hot_news] 澎湃新闻抓取失败: {exc}")
        return []


_FETCHERS = {
    "cailian": _fetch_cailian,
    "wallstreetcn": _fetch_wallstreetcn,
    "sina_live": _fetch_sina_live,
    "thepaper": _fetch_thepaper,
}


def _resolve_source_items(source: str, items: list[dict] | None) -> list[dict]:
    if items:
        return list(items)
    return list(_SOURCE_FALLBACKS.get(source, []))


def _do_refresh() -> None:
    global _cache_ts

    new_data: dict[str, list[dict]] = {}
    for source, fetcher in _FETCHERS.items():
        try:
            items = fetcher()
            if items:
                new_data[source] = items
                continue

            with _cache_lock:
                previous = list(_cache_data.get(source, []))

            if previous:
                logger.warning(f"[hot_news] {source} 本次抓取为空，保留上次成功缓存")
                new_data[source] = previous
            else:
                logger.warning(f"[hot_news] {source} 本次抓取为空，使用内置兜底")
                new_data[source] = list(_SOURCE_FALLBACKS.get(source, []))
        except Exception as exc:
            logger.error(f"[hot_news] {source} 刷新异常: {exc}")
            with _cache_lock:
                previous = list(_cache_data.get(source, []))
            new_data[source] = previous or list(_SOURCE_FALLBACKS.get(source, []))

    with _cache_lock:
        _cache_data.update(new_data)
        _cache_ts = time.time()

    logger.info(f"[hot_news] 热榜缓存刷新完成，{sum(len(v) for v in new_data.values())} 条")


def get_hot_news(force_refresh: bool = False) -> list[dict]:
    global _cache_ts

    if force_refresh or (time.time() - _cache_ts > _CACHE_TTL):
        _do_refresh()

    with _cache_lock:
        result = []
        for source, meta in _SOURCE_META.items():
            items = _resolve_source_items(source, _cache_data.get(source, []))
            result.append(
                {
                    "source": source,
                    "label": meta["label"],
                    "icon": meta["icon"],
                    "color": meta["color"],
                    "items": items,
                    "fetched_at": datetime.fromtimestamp(_cache_ts, tz=timezone.utc).isoformat() if _cache_ts else None,
                }
            )
        return result


def refresh_in_background() -> None:
    t = threading.Thread(target=_do_refresh, daemon=True, name="hot-news-refresh")
    t.start()
