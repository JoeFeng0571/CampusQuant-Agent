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
