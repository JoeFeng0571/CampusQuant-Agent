"""
tools/hot_news.py — 多平台热榜聚合（后端缓存，15 分钟 TTL）

数据源：
  1. cailian   — 财联社 7x24 快讯（akshare，最新 3 条）
  2. xueqiu    — 雪球财经热搜（雪球公开 API，Top 3）
  3. zhihu     — 知乎热榜（知乎公开 API，Top 3）
  4. phoenix   — 凤凰财经新闻（凤凰网公开 API，Top 3）
  5. thepaper  — 澎湃新闻热榜（澎湃公开接口，Top 3）

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


def _fetch_xueqiu() -> list[dict]:
    """雪球财经热搜 Top 3（Session 携带 cookie，公开接口）"""
    try:
        sess = requests.Session()
        # 先访问首页触发 cookie 下发（xq_a_token 等），再请求热搜接口
        sess.get(
            "https://xueqiu.com/",
            headers=_HEADERS,
            timeout=8,
            proxies={"http": "", "https": ""},
        )
        resp = sess.get(
            "https://xueqiu.com/statuses/hot_search_list.json?size=3",
            headers={**_HEADERS, "Referer": "https://xueqiu.com/"},
            timeout=8,
            proxies={"http": "", "https": ""},
        )
        data  = resp.json()
        # 响应结构: {"stocks": [{"symbol":"SH600519","name":"贵州茅台",...}, ...]}
        items = data.get("stocks", data.get("list", []))[:3]
        results = []
        for i, item in enumerate(items, start=1):
            name   = item.get("name", item.get("title", ""))[:200]
            symbol = item.get("symbol", "")
            url    = f"https://xueqiu.com/S/{symbol}" if symbol else "https://xueqiu.com/hq"
            results.append({"title": name, "url": url, "rank": i})
        return results
    except Exception as e:
        logger.warning(f"[hot_news] 雪球抓取失败: {e}")
        return []


def _fetch_zhihu() -> list[dict]:
    """知乎热榜 Top 3"""
    try:
        url = "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total?limit=3"
        headers = {**_HEADERS, "x-api-version": "3.0.91"}
        resp = requests.get(url, headers=headers, timeout=8, proxies={"http": "", "https": ""})
        data = resp.json()
        items = data.get("data", [])[:3]
        results = []
        for i, item in enumerate(items, start=1):
            target = item.get("target", {})
            title  = target.get("title", "")[:200]
            qid    = target.get("id", "")
            results.append({
                "title": title,
                "url":   f"https://www.zhihu.com/question/{qid}" if qid else "https://www.zhihu.com/hot",
                "rank":  i,
            })
        return results
    except Exception as e:
        logger.warning(f"[hot_news] 知乎抓取失败: {e}")
        return []


def _fetch_phoenix() -> list[dict]:
    """凤凰财经热点新闻 Top 3（ifengNews API）"""
    try:
        url = "https://openapi.inews.qq.com/getQQNewsIndexAndItems?base_id=hot_channel_finance&num=3&callback="
        # 凤凰财经使用腾讯新闻开放接口作兜底
        resp = requests.get(
            "https://i.ifeng.com/api/ifeng/channel/newslist?channelId=finance&num=3",
            headers=_HEADERS, timeout=8, proxies={"http": "", "https": ""},
        )
        data = resp.json()
        news_list = data.get("newslist", [])[:3]
        results = []
        for i, item in enumerate(news_list, start=1):
            title = item.get("title", "")[:200]
            link  = item.get("url", item.get("link", "https://finance.ifeng.com/"))
            results.append({"title": title, "url": link, "rank": i})
        return results
    except Exception as e:
        logger.warning(f"[hot_news] 凤凰财经抓取失败: {e}")
        return _fetch_phoenix_fallback()


def _fetch_phoenix_fallback() -> list[dict]:
    """凤凰财经主接口失败时用腾讯新闻财经作备用"""
    try:
        url = "https://r.inews.qq.com/gw/event/hot_ranking_list?page_size=3"
        resp = requests.get(url, headers=_HEADERS, timeout=8, proxies={"http": "", "https": ""})
        data = resp.json()
        items = data.get("idlist", [{}])[0].get("newslist", [])[:3]
        results = []
        for i, item in enumerate(items, start=1):
            title = item.get("title", "")[:200]
            link  = item.get("url", "https://news.qq.com/")
            results.append({"title": title, "url": link, "rank": i})
        return results
    except Exception as e:
        logger.warning(f"[hot_news] 凤凰备用也失败: {e}")
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

_FETCHERS = {
    "cailian":  _fetch_cailian,
    "xueqiu":   _fetch_xueqiu,
    "zhihu":    _fetch_zhihu,
    "phoenix":  _fetch_phoenix,
    "thepaper": _fetch_thepaper,
}

_SOURCE_META = {
    "cailian":  {"label": "财联社",   "color": "#e74c3c", "icon": "📰"},
    "xueqiu":   {"label": "雪球热搜", "color": "#1db954", "icon": "❄️"},
    "zhihu":    {"label": "知乎热榜", "color": "#0084ff", "icon": "💬"},
    "phoenix":  {"label": "凤凰财经", "color": "#f39c12", "icon": "🔥"},
    "thepaper": {"label": "澎湃新闻", "color": "#2ecc71", "icon": "📌"},
}


def _do_refresh() -> None:
    global _cache_ts
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
    logger.info(f"[hot_news] 热榜缓存刷新完成，{sum(len(v) for v in new_data.values())} 条")


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
    """
    global _cache_ts

    need_refresh = force_refresh or (time.time() - _cache_ts > _CACHE_TTL)

    if need_refresh:
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
