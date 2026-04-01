"""
tools/hot_news.py — 多平台热榜聚合（后端缓存，15 分钟 TTL）

数据源：
  1. cailian      — 财联社 7x24 快讯（akshare，最新 3 条）
  2. wallstreetcn — 华尔街见闻热门文章（公开 API，Top 3）
  3. sina_live    — 新浪财经实时快讯（新浪直播接口，Top 3）
  4. thepaper     — 澎湃新闻热榜（澎湃公开接口，Top 3）

缓存策略：
  - 内存字典 + fetched_at 时间戳，TTL = 15 分钟
  - 首次请求触发同步刷新，此后后台线程异步刷新
  - 单源失败不影响其他源，返回 [] 并记录 warning
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Optional

import requests
from loguru import logger

# ════════════════════════════════════════════════════════════════
# 缓存
# ════════════════════════════════════════════════════════════════

_CACHE_TTL   = 15 * 60   # 15 分钟
_cache_lock  = threading.Lock()
_cache_data: dict[str, list[dict]] = {}  # source → [{"title","url","rank"}]
_cache_ts:   float = 0.0                 # 上次刷新时间戳


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}


# ════════════════════════════════════════════════════════════════
# 各平台抓取函数
# ════════════════════════════════════════════════════════════════

def _fetch_cailian() -> list[dict]:
    """财联社 7x24 最新 3 条快讯（akshare）"""
    try:
        import akshare as ak
        df = ak.stock_info_global_cls(symbol="全部")
        if df is None or df.empty:
            return []
        df = df.head(3)
        results = []
        for i, row in enumerate(df.itertuples(), start=1):
            title = str(getattr(row, "内容", getattr(row, "标题", "")))[:200]
            results.append({
                "title": title,
                "url":   "https://www.cls.cn/telegraph",
                "rank":  i,
            })
        return results
    except Exception as e:
        logger.warning(f"[hot_news] 财联社抓取失败: {e}")
        return []


def _fetch_wallstreetcn() -> list[dict]:
    """华尔街见闻热门财经文章 Top 3（公开 API，无需登录）"""
    try:
        resp = requests.get(
            "https://api.wallstreetcn.com/apiv1/content/articles?channel=a-stock&limit=5&accept=json",
            headers={**_HEADERS, "Referer": "https://wallstreetcn.com/"},
            timeout=8,
        )
        data  = resp.json()
        items = data.get("data", {}).get("items", [])[:3]
        results = []
        for i, item in enumerate(items, start=1):
            title = item.get("title", "")[:200]
            uri   = item.get("uri", "https://wallstreetcn.com")
            if title:
                results.append({"title": title, "url": uri, "rank": i})
        return results
    except Exception as e:
        logger.warning(f"[hot_news] 华尔街见闻抓取失败: {e}")
        return []


def _fetch_sina_live() -> list[dict]:
    """新浪财经实时快讯 Top 3（直播接口，proxies='' 直连）"""
    import re as _re
    try:
        resp = requests.get(
            "https://zhibo.sina.com.cn/api/zhibo/feed"
            "?zhibo_id=152&tag_id=0&dire=f&dtime=&pagesize=10&otype=json",
            headers={**_HEADERS, "Referer": "https://finance.sina.com.cn/"},
            timeout=8,
            proxies={"http": "", "https": ""},
        )
        data  = resp.json()
        items = data.get("result", {}).get("data", {}).get("feed", {}).get("list", [])
        results = []
        for item in items:
            text = _re.sub(r"<[^>]+>", "", item.get("rich_text", "")).strip()[:200]
            if text and len(results) < 3:
                results.append({
                    "title": text,
                    "url":   "https://finance.sina.com.cn/",
                    "rank":  len(results) + 1,
                })
        return results
    except Exception as e:
        logger.warning(f"[hot_news] 新浪快讯抓取失败: {e}")
        return []


def _fetch_thepaper() -> list[dict]:
    """澎湃新闻热榜 Top 3"""
    try:
        url = "https://cache.thepaper.cn/contentapi/wwwIndex/rightSidebar"
        resp = requests.get(url, headers=_HEADERS, timeout=8, proxies={"http": "", "https": ""})
        data = resp.json()
        hot_list = data.get("data", {}).get("hotNews", [])[:3]
        results = []
        for i, item in enumerate(hot_list, start=1):
            title = item.get("name", "")[:200]
            cont_id = item.get("contId", "")
            link    = f"https://www.thepaper.cn/newsDetail_forward_{cont_id}" if cont_id else "https://www.thepaper.cn/"
            results.append({"title": title, "url": link, "rank": i})
        return results
    except Exception as e:
        logger.warning(f"[hot_news] 澎湃新闻抓取失败: {e}")
        return []


# ════════════════════════════════════════════════════════════════
# 刷新与获取
# ════════════════════════════════════════════════════════════════

def _fetch_jin10() -> list[dict]:
    """金十数据快讯 Top 3"""
    import re as _re
    try:
        resp = requests.get(
            "https://www.jin10.com/flash_newest.js",
            headers={**_HEADERS, "Referer": "https://www.jin10.com/"},
            timeout=8,
        )
        # 格式: var newest = [{...}, ...];
        text = resp.text.strip()
        if text.startswith("var newest = "):
            text = text[len("var newest = "):]
        text = text.rstrip(";").strip()
        import json
        items = json.loads(text)
        results = []
        for item in items:
            content = (item.get("data", {}).get("content") or "").strip()
            content = _re.sub(r"<[^>]+>", "", content).strip()[:200]
            pub_time = item.get("time", "")
            if content and len(results) < 3:
                results.append({
                    "title": content,
                    "url": "https://www.jin10.com/",
                    "rank": len(results) + 1,
                    "time": pub_time,
                })
        return results
    except Exception as e:
        logger.warning(f"[hot_news] 金十数据抓取失败: {e}")
        return []


_FETCHERS = {
    "jin10":        _fetch_jin10,
    "cailian":      _fetch_cailian,
    "wallstreetcn": _fetch_wallstreetcn,
    "sina_live":    _fetch_sina_live,
    "thepaper":     _fetch_thepaper,
}

_SOURCE_META = {
    "jin10":        {"label": "金十数据",   "color": "#ff6600", "icon": "🔔"},
    "cailian":      {"label": "财联社",    "color": "#e74c3c", "icon": "📰"},
    "wallstreetcn": {"label": "华尔街见闻", "color": "#f5a623", "icon": "📊"},
    "sina_live":    {"label": "新浪财经",   "color": "#e8312f", "icon": "⚡"},
    "thepaper":     {"label": "澎湃新闻",   "color": "#2ecc71", "icon": "📌"},
}


def _do_refresh() -> None:
    global _cache_ts

    # 优先走内地 relay 获取国内新闻源
    inland_data = _try_inland_relay_hot_news()
    if inland_data:
        with _cache_lock:
            for item in inland_data:
                src = item.get("source")
                if src:
                    _cache_data[src] = item.get("items", [])
            # 华尔街见闻走本地
            try:
                _cache_data["wallstreetcn"] = _fetch_wallstreetcn()
            except Exception as e:
                logger.warning(f"[hot_news] 华尔街见闻抓取失败: {e}")
                _cache_data.setdefault("wallstreetcn", [])
            _cache_ts = time.time()
        total = sum(len(v) for v in _cache_data.values())
        logger.info(f"[hot_news] 热榜缓存刷新完成（relay），{total} 条")
        return

    # relay 不可用时回退本地抓取
    new_data: dict[str, list] = {}
    for source, fetcher in _FETCHERS.items():
        try:
            new_data[source] = fetcher()
        except Exception as e:
            logger.error(f"[hot_news] {source} 刷新异常: {e}")
            new_data[source] = []

    with _cache_lock:
        _cache_data.update(new_data)
        _cache_ts = time.time()
    logger.info(f"[hot_news] 热榜缓存刷新完成（本地），{sum(len(v) for v in new_data.values())} 条")


def _try_inland_relay_hot_news() -> Optional[list[dict]]:
    """尝试从内地 relay 获取国内新闻源（财联社+新浪+澎湃），失败返回 None"""
    try:
        from config import config
        base_url = (getattr(config, "INLAND_RELAY_BASE_URL", "") or "").rstrip("/")
        token = (getattr(config, "INLAND_RELAY_TOKEN", "") or "").strip()
        if not base_url or not token:
            return None
        resp = requests.get(
            f"{base_url}/relay/hot-news",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "success" and data.get("data"):
            return data["data"]
        return None
    except Exception as exc:
        logger.warning(f"[hot_news] 内地 relay 热榜获取失败，回退本地: {exc}")
        return None


def get_hot_news(force_refresh: bool = False) -> list[dict]:
    """
    返回全部热榜数据，格式：
    [
      {
        "source": "xueqiu",
        "label":  "雪球热搜",
        "icon":   "❄️",
        "color":  "#1db954",
        "items":  [{"title": "...", "url": "...", "rank": 1}, ...]
      },
      ...
    ]
    TTL 超时或 force_refresh=True 时触发同步刷新。
    优先走内地 relay 获取国内新闻源，华尔街见闻仍走本地（国际接口）。
    """
    global _cache_ts

    need_refresh = force_refresh or (time.time() - _cache_ts > _CACHE_TTL)

    if need_refresh:
        # 尝试内地 relay（财联社+新浪+澎湃）
        inland_data = _try_inland_relay_hot_news()
        if inland_data:
            with _cache_lock:
                # 用 relay 返回的国内源数据更新缓存
                for item in inland_data:
                    src = item.get("source")
                    if src:
                        _cache_data[src] = item.get("items", [])
                # 华尔街见闻仍走本地抓取
                try:
                    _cache_data["wallstreetcn"] = _fetch_wallstreetcn()
                except Exception as e:
                    logger.warning(f"[hot_news] 华尔街见闻抓取失败: {e}")
                    _cache_data.setdefault("wallstreetcn", [])
                _cache_ts = time.time()
        else:
            _do_refresh()

    with _cache_lock:
        result = []
        for source, meta in _SOURCE_META.items():
            result.append({
                "source":     source,
                "label":      meta["label"],
                "icon":       meta["icon"],
                "color":      meta["color"],
                "items":      list(_cache_data.get(source, [])),
                "fetched_at": datetime.fromtimestamp(_cache_ts, tz=timezone.utc).isoformat()
                              if _cache_ts else None,
            })
        return result


def refresh_in_background() -> None:
    """在后台线程中刷新缓存（供定时任务调用，不阻塞主线程）"""
    t = threading.Thread(target=_do_refresh, daemon=True, name="hot-news-refresh")
    t.start()
