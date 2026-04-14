"""
utils/report_cache.py — 研报磁盘缓存

同一股票 24 小时内复用上次分析结果，避免重复调用 LLM。
缓存存储在 data/report_cache/ 目录，JSON 格式，不占常驻 RAM。

【v2.2 修复 — 降级报告不缓存】
现实问题: 上一次分析因 LLM 欠费/超时/解析失败走到降级路径,整份报告退化为
HOLD/0.30 + reasoning="结构化输出解析三层全失败",这份垃圾结果被写入缓存后,
后续 24 小时内所有用户分析同一只股票都会拿到同样的错误报告。

修复: `set()` 在写盘前通过 `_is_degraded_report()` 检测几种失败模式,
只要命中任一就拒绝写入(打 warning + 返回 False 让调用方感知)。
调用方无需改动,set() 签名保持向后兼容。

用法:
    from utils.report_cache import report_cache

    cached = report_cache.get("600519.SH")
    if cached:
        return cached

    # 写入失败会被 set() 内部拦截,不会污染缓存
    report_cache.set("600519.SH", final_state_dict)
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from loguru import logger

_CACHE_DIR = Path(__file__).parent.parent / "data" / "report_cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 默认缓存 24 小时
DEFAULT_TTL = 24 * 3600


# ════════════════════════════════════════════════════════════════
# 【v2.2 修复】降级报告检测 — 决定哪些结果不配进缓存
# ════════════════════════════════════════════════════════════════

# 典型降级 rationale 片段 (来自各节点的 fallback 和 LLM 错误消息)
_DEGRADED_RATIONALE_MARKERS = (
    "系统异常，降级输出",
    "系统异常,降级输出",
    "结构化输出解析三层全失败",
    "Error code: 400",
    "Error code: 401",
    "Error code: 402",
    "Error code: 403",
    "Error code: 429",
    "Error code: 500",
    "Error code: 502",
    "Access denied",
    "Arrearage",
    "overdue-payment",
    "FreeTierOnly",
    "三层解析均失败",
    "降级处理",
)


def _is_degraded_report(report: dict[str, Any]) -> tuple[bool, str]:
    """
    检测一份报告是否是降级/失败产物,不应进缓存。

    返回 (is_degraded, reason)。

    判定规则 (任一命中即降级):
      1. status 字段 == "error" 或包含 "error"/"failed"
      2. trade_order.rationale 含 _DEGRADED_RATIONALE_MARKERS 任一片段
      3. final_markdown_report 含 "系统异常,降级输出" 或 "解析三层全失败"
      4. trade_order.action == "HOLD" 且 confidence <= 0.31 且 rationale 含错误标记
         (不会误伤"真的应该 HOLD"的正常情况: 那种情况下 rationale 是正常分析文本)
    """
    if not isinstance(report, dict):
        return True, "report 不是 dict"

    # 规则 1: status 字段
    status = str(report.get("status", "")).lower()
    if status in ("error", "failed", "degraded"):
        return True, f"status={status!r}"

    # 规则 2: trade_order.rationale 含降级标记
    order = report.get("trade_order") or {}
    if isinstance(order, dict):
        rationale = str(order.get("rationale") or "")
        for marker in _DEGRADED_RATIONALE_MARKERS:
            if marker in rationale:
                return True, f"trade_order.rationale 含 '{marker}'"

        # 规则 4: HOLD + conf≤0.31 + 含错误关键字
        action = str(order.get("action") or "").upper()
        try:
            conf = float(order.get("confidence") or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        if action == "HOLD" and conf <= 0.31:
            err_kws = ("Error", "error", "失败", "异常", "降级")
            if any(k in rationale for k in err_kws):
                return True, f"HOLD+conf={conf:.2f}+rationale 含错误关键字"

    # 规则 3: final_markdown_report 含降级标记
    md = str(report.get("final_markdown_report") or "")
    if md:
        for marker in (
            "系统异常，降级输出",
            "系统异常,降级输出",
            "解析三层全失败",
            "fundamental_node 结构化输出解析",
            "technical_node 结构化输出解析",
            "sentiment_node 结构化输出解析",
        ):
            if marker in md:
                return True, f"final_markdown_report 含 '{marker}'"

    return False, ""


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

            # 【v2.2 防御】读出来再查一次 — 避免历史上写入的坏缓存继续服务
            # (修复发布前已经存了一批降级报告,这里做一次清洗兜底)
            report = data.get("report")
            is_bad, reason = _is_degraded_report(report or {})
            if is_bad:
                logger.warning(
                    f"[Cache] {symbol} 缓存命中但检测到是降级报告 ({reason}),丢弃并重新分析"
                )
                path.unlink(missing_ok=True)
                return None

            logger.info(f"[Cache] {symbol} 命中缓存 (剩余 {self.ttl - (time.time() - cached_at):.0f}s)")
            return report
        except Exception as e:
            logger.warning(f"[Cache] 读取失败 {symbol}: {e}")
            return None

    def set(self, symbol: str, report: dict) -> bool:
        """
        写入缓存。

        返回 True = 写入成功,False = 被拒绝或失败。
        调用方无需关心返回值(保持向后兼容),但可用于日志/metrics。

        【v2.2 修复】降级报告会被拒绝写入,避免污染后续 24 小时的缓存。
        """
        # 【v2.2】降级报告不配进缓存
        is_bad, reason = _is_degraded_report(report or {})
        if is_bad:
            logger.warning(
                f"[Cache] {symbol} 拒绝写入降级报告: {reason}"
            )
            try:
                from observability.metrics import metrics
                metrics.counter(
                    "report_cache_rejected_degraded_total",
                    symbol=symbol,
                )
            except Exception:
                pass
            return False

        path = self._key_path(symbol)
        try:
            data = {
                "_cached_at": time.time(),
                "_symbol": symbol,
                "report": report,
            }
            path.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
            logger.info(f"[Cache] {symbol} 缓存已写入 ({path.stat().st_size / 1024:.1f}KB)")
            return True
        except Exception as e:
            logger.warning(f"[Cache] 写入失败 {symbol}: {e}")
            return False

    def invalidate(self, symbol: str):
        """手动清除单个 symbol 的缓存"""
        path = self._key_path(symbol)
        path.unlink(missing_ok=True)

    def clear_all(self):
        """清除所有缓存"""
        count = 0
        for f in self.cache_dir.glob("*.json"):
            f.unlink(missing_ok=True)
            count += 1
        logger.info(f"[Cache] 已清除 {count} 个缓存文件")

    def clear_degraded(self) -> int:
        """
        【v2.2 新增】扫描所有现存缓存,清除检测到是降级报告的那些。

        返回清除数量。用于修复发布后,把历史上写坏的一批缓存一次性清掉。
        """
        removed = 0
        for f in self.cache_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                report = data.get("report") or {}
                is_bad, reason = _is_degraded_report(report)
                if is_bad:
                    logger.info(f"[Cache] clear_degraded 清除 {f.name}: {reason}")
                    f.unlink(missing_ok=True)
                    removed += 1
            except Exception as e:
                logger.warning(f"[Cache] clear_degraded 跳过 {f.name}(无法解析): {e}")
        logger.info(f"[Cache] clear_degraded 共清除 {removed} 个降级缓存")
        return removed

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
