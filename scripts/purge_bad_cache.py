"""
scripts/purge_bad_cache.py — 扫 data/report_cache/*.json, 删除 trade_order.action
不是 BUY/SELL/HOLD 或 confidence 为 None 的"降级缓存"。

场景: 早期 BaseHTTPMiddleware bug 导致部分研报 trade_order={}, 被 24h TTL 缓存
     后续用户命中这份空结果, 前端渲染出 N/A / 0% / --。本脚本一次性清理。
"""
from __future__ import annotations

import glob
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "data" / "report_cache"


def main() -> int:
    files = sorted(glob.glob(str(ROOT / "*.json")))
    if not files:
        print(f"[purge] no cache files in {ROOT}")
        return 0

    bad = []
    for path in files:
        try:
            data = json.load(open(path, encoding="utf-8"))
            trade_order = (data.get("report", {}) or {}).get("trade_order", {}) or {}
            action = trade_order.get("action")
            confidence = trade_order.get("confidence")
            if action not in ("BUY", "SELL", "HOLD") or confidence is None:
                bad.append((path, action, confidence))
        except Exception as e:
            bad.append((path, "PARSE_ERR", str(e)[:50]))

    print(f"[purge] total caches: {len(files)}")
    print(f"[purge] bad (to remove): {len(bad)}")
    for path, action, confidence in bad:
        print(f"  {os.path.basename(path)}: action={action} confidence={confidence}")
        try:
            os.remove(path)
        except OSError as e:
            print(f"    REMOVE FAILED: {e}")
    print(f"[purge] done, {len(files) - len(bad)} good caches kept")
    return 0


if __name__ == "__main__":
    sys.exit(main())
