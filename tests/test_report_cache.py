"""tests/test_report_cache.py — 研报缓存单元测试"""
import time
import pytest
from pathlib import Path
import tempfile

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.report_cache import ReportCache


@pytest.fixture
def cache(tmp_path):
    return ReportCache(cache_dir=tmp_path, ttl=5)


def test_set_and_get(cache):
    cache.set("600519.SH", {"action": "BUY", "confidence": 0.75})
    result = cache.get("600519.SH")
    assert result is not None
    assert result["action"] == "BUY"


def test_cache_miss(cache):
    assert cache.get("NONEXIST") is None


def test_cache_expiry(cache):
    cache.ttl = 1  # 1 second TTL
    cache.set("AAPL", {"action": "SELL"})
    assert cache.get("AAPL") is not None
    time.sleep(1.5)
    assert cache.get("AAPL") is None


def test_invalidate(cache):
    cache.set("TSLA", {"action": "HOLD"})
    assert cache.get("TSLA") is not None
    cache.invalidate("TSLA")
    assert cache.get("TSLA") is None


def test_clear_all(cache):
    cache.set("A", {"x": 1})
    cache.set("B", {"x": 2})
    cache.set("C", {"x": 3})
    stats = cache.stats()
    assert stats["count"] == 3
    cache.clear_all()
    assert cache.stats()["count"] == 0


def test_stats(cache):
    cache.set("TEST", {"data": "hello"})
    stats = cache.stats()
    assert stats["count"] == 1
    assert stats["total_size_kb"] > 0


def test_case_insensitive(cache):
    cache.set("aapl", {"action": "BUY"})
    result = cache.get("AAPL")
    assert result is not None


# ══════════════════════════════════════════════════════════════════
# 【v2.2 修复】降级报告检测: 不允许进缓存
# ══════════════════════════════════════════════════════════════════

def _build_degraded_report(rationale: str = "系统异常，降级输出: Error code: 400") -> dict:
    """构造一份典型的降级报告(模拟 LLM 欠费时 api/server.py 的 _complete_data)"""
    return {
        "symbol": "09988.HK",
        "status": "completed",
        "trade_order": {
            "symbol": "09988.HK",
            "action": "HOLD",
            "quantity_pct": 0.0,
            "rationale": rationale,
            "confidence": 0.3,
            "simulated": True,
        },
        "final_markdown_report": (
            "# 09988.HK · AI 投资研报\n"
            "## 💡 一句话结论\n"
            f"> **{rationale}**\n\n"
        ),
    }


def _build_normal_report() -> dict:
    """构造一份典型的正常报告"""
    return {
        "symbol": "600519.SH",
        "status": "completed",
        "trade_order": {
            "symbol": "600519.SH",
            "action": "BUY",
            "quantity_pct": 15.0,
            "rationale": "基本面强势,PE 合理,MA 多头排列,建议长期持有",
            "confidence": 0.78,
            "simulated": True,
        },
        "final_markdown_report": (
            "# 600519.SH · AI 投资研报\n"
            "## 💡 一句话结论\n"
            "> 基于 ROE 24.6% 的强劲基本面,建议买入并持有 3 个月以上\n"
        ),
    }


def test_set_rejects_degraded_arrearage(cache):
    """DashScope 欠费导致的降级报告应被拒绝"""
    report = _build_degraded_report("系统异常，降级输出: Error code: 400 - Arrearage")
    ok = cache.set("09988.HK", report)
    assert ok is False, "欠费降级报告应被拒绝"
    assert cache.get("09988.HK") is None, "被拒绝的报告不应留在缓存里"


def test_set_rejects_degraded_parsing_failure(cache):
    """结构化输出三层解析失败的降级报告应被拒绝"""
    report = _build_degraded_report("系统异常，降级输出: 结构化输出解析三层全失败")
    ok = cache.set("TSLA", report)
    assert ok is False
    assert cache.get("TSLA") is None


def test_set_rejects_by_markdown_markers(cache):
    """通过 final_markdown_report 里的降级标记识别"""
    report = {
        "symbol": "NVDA",
        "status": "completed",
        "trade_order": {"action": "BUY", "confidence": 0.7, "rationale": "正常"},
        "final_markdown_report": (
            "## 投资论点\n\nfundamental_node 结构化输出解析三层全失败，降级为 HOLD\n"
        ),
    }
    ok = cache.set("NVDA", report)
    assert ok is False


def test_set_rejects_free_tier_only(cache):
    """FreeTierOnly 错误也是降级"""
    report = _build_degraded_report(
        "系统异常，降级输出: Error code: 403 - AllocationQuota.FreeTierOnly"
    )
    ok = cache.set("AAPL", report)
    assert ok is False


def test_set_accepts_normal_report(cache):
    """正常 BUY 报告应被缓存"""
    report = _build_normal_report()
    ok = cache.set("600519.SH", report)
    assert ok is True, "正常报告应被接受"
    cached = cache.get("600519.SH")
    assert cached is not None
    assert cached["trade_order"]["action"] == "BUY"
    assert cached["trade_order"]["confidence"] == 0.78


def test_set_accepts_normal_hold(cache):
    """正常 HOLD 报告(高置信度 + 非错误 rationale)应被缓存"""
    report = {
        "symbol": "MSFT",
        "status": "completed",
        "trade_order": {
            "action": "HOLD",
            "confidence": 0.65,
            "rationale": "基本面稳健但短期缺乏催化剂,等待右侧信号",
        },
        "final_markdown_report": "# MSFT · AI 投资研报\n> 观望等待催化剂\n",
    }
    ok = cache.set("MSFT", report)
    assert ok is True, "高置信度 HOLD 不应被误杀"
    assert cache.get("MSFT") is not None


def test_get_invalidates_degraded_cache_on_read(cache):
    """
    【兜底】绕过 set() 直接写入磁盘的坏缓存(模拟历史上 v2.2 修复之前留下的脏数据),
    get() 读出来时也应该检测到并丢弃。
    """
    import json as _json
    # 构造一份 degraded report, 手工写到磁盘(绕过 set 的拦截)
    degraded = _build_degraded_report()
    path = cache._key_path("09988.HK")
    path.write_text(_json.dumps({
        "_cached_at": time.time(),
        "_symbol": "09988.HK",
        "report": degraded,
    }, ensure_ascii=False), encoding="utf-8")

    # get 应该检测到并返回 None,同时把文件删掉
    assert cache.get("09988.HK") is None
    assert not path.exists(), "get() 读到降级报告后应删除磁盘文件"


def test_clear_degraded_removes_only_bad(cache):
    """clear_degraded 只清坏的,不动好的"""
    # 一份好的 + 两份坏的
    cache.set("600519.SH", _build_normal_report())  # good
    # 直接写两份坏的绕过拦截
    import json as _json
    for sym in ("BAD1", "BAD2"):
        path = cache._key_path(sym)
        path.write_text(_json.dumps({
            "_cached_at": time.time(),
            "_symbol": sym,
            "report": _build_degraded_report(),
        }, ensure_ascii=False), encoding="utf-8")

    assert cache.stats()["count"] == 3
    removed = cache.clear_degraded()
    assert removed == 2
    assert cache.stats()["count"] == 1

    # 好的仍然可读
    assert cache.get("600519.SH") is not None
