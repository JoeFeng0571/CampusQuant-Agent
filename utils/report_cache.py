"""
utils/report_cache.py — 研报磁盘缓存

同一股票 24 小时内复用上次分析结果，避免重复调用 LLM。
缓存存储在 data/report_cache/ 目录，JSON 格式，不占常驻 RAM。

用法:
    from utils.report_cache import ReportCache
    cache = ReportCache()

    # 检查缓存
    cached = cache.get("600519.SH")
    if cached:
        return cached  # 直接返回

    # 分析完成后写入
    cache.set("600519.SH", final_state_dict)
"""
from __future__ import annotations

import json
import hashlib
import time
from pathlib import Path
from loguru import logger

_CACHE_DIR = Path(__file__).parent.parent / "data" / "report_cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 默认缓存 24 小时
DEFAULT_TTL = 24 * 3600


class ReportCache:
    def __init__(self, cache_dir: Path = _CACHE_DIR, ttl: int = DEFAULT_TTL):
        self.cache_dir = cache_dir
        self.ttl = ttl

    def _key_path(self, symbol: str) -> Path:
        """symbol → 缓存文件路径"""
        safe = symbol.upper().replace("/", "_").replace("\\", "_")
        return self.cache_dir / f"{safe}.json"

    def get(self, symbol: str) -> dict | None:
        """读取缓存，过期返回 None"""
        path = self._key_path(symbol)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            cached_at = data.get("_cached_at", 0)
            if time.time() - cached_at > self.ttl:
                logger.info(f"[Cache] {symbol} 缓存已过期 ({self.ttl}s)")
                path.unlink(missing_ok=True)
                return None
            logger.info(f"[Cache] {symbol} 命中缓存 (剩余 {self.ttl - (time.time() - cached_at):.0f}s)")
            return data.get("report")
        except Exception as e:
            logger.warning(f"[Cache] 读取失败 {symbol}: {e}")
            return None

    def set(self, symbol: str, report: dict):
        """写入缓存"""
        path = self._key_path(symbol)
        try:
            data = {
                "_cached_at": time.time(),
                "_symbol": symbol,
                "report": report,
            }
            path.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
            logger.info(f"[Cache] {symbol} 缓存已写入 ({path.stat().st_size / 1024:.1f}KB)")
        except Exception as e:
            logger.warning(f"[Cache] 写入失败 {symbol}: {e}")

    def invalidate(self, symbol: str):
        """手动清除缓存"""
        path = self._key_path(symbol)
        path.unlink(missing_ok=True)

    def clear_all(self):
        """清除所有缓存"""
        count = 0
        for f in self.cache_dir.glob("*.json"):
            f.unlink(missing_ok=True)
            count += 1
        logger.info(f"[Cache] 已清除 {count} 个缓存文件")

    def stats(self) -> dict:
        """缓存统计"""
        files = list(self.cache_dir.glob("*.json"))
        total_size = sum(f.stat().st_size for f in files)
        return {
            "count": len(files),
            "total_size_kb": round(total_size / 1024, 1),
            "cache_dir": str(self.cache_dir),
            "ttl_hours": self.ttl / 3600,
        }


# 全局单例
report_cache = ReportCache()
