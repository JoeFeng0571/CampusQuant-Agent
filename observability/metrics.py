"""
observability/metrics.py — 轻量级 metrics 采集 (SQLite 后端)

用法:
    from observability.metrics import metrics

    metrics.counter("analyze_request_total", market="A_STOCK")
    with metrics.timer("analyze_duration_seconds", node="fundamental"):
        await run_analysis()
    metrics.histogram("llm_tokens_used", 1234, model="qwen-plus")
    metrics.gauge("active_users", 42)

查询:
    metrics.query_counters("analyze_request_total", since_hours=24)
    metrics.query_histogram_percentiles("analyze_duration_seconds", [50, 95, 99])
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from loguru import logger


_DB_PATH = Path(__file__).parent.parent / "data" / "metrics.db"
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)


class MetricsStore:
    """Thread-safe SQLite metrics store"""

    def __init__(self, db_path: Path = _DB_PATH):
        self._db_path = db_path
        self._local = threading.local()
        self._init_done = False
        self._lock = threading.Lock()

    def _get_conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self._db_path), timeout=5)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        if not self._init_done:
            with self._lock:
                if not self._init_done:
                    self._init_tables(conn)
                    self._init_done = True
        return conn

    def _init_tables(self, conn: sqlite3.Connection):
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS counters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                value REAL NOT NULL DEFAULT 1,
                labels TEXT NOT NULL DEFAULT '{}',
                ts REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS histograms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                value REAL NOT NULL,
                labels TEXT NOT NULL DEFAULT '{}',
                ts REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS gauges (
                name TEXT NOT NULL,
                value REAL NOT NULL,
                labels TEXT NOT NULL DEFAULT '{}',
                ts REAL NOT NULL,
                PRIMARY KEY (name, labels)
            );
            CREATE INDEX IF NOT EXISTS idx_counters_name_ts ON counters(name, ts);
            CREATE INDEX IF NOT EXISTS idx_histograms_name_ts ON histograms(name, ts);
        """)
        conn.commit()

    # ── 采集 API ──

    def counter(self, name: str, value: float = 1, **labels):
        """递增计数器"""
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO counters (name, value, labels, ts) VALUES (?, ?, ?, ?)",
            (name, value, json.dumps(labels, ensure_ascii=False), time.time()),
        )
        conn.commit()

    def histogram(self, name: str, value: float, **labels):
        """记录一个观测值（延迟/token 数等）"""
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO histograms (name, value, labels, ts) VALUES (?, ?, ?, ?)",
            (name, value, json.dumps(labels, ensure_ascii=False), time.time()),
        )
        conn.commit()

    def gauge(self, name: str, value: float, **labels):
        """设置一个当前值（替换旧值）"""
        conn = self._get_conn()
        labels_json = json.dumps(labels, ensure_ascii=False)
        conn.execute(
            "INSERT OR REPLACE INTO gauges (name, value, labels, ts) VALUES (?, ?, ?, ?)",
            (name, value, labels_json, time.time()),
        )
        conn.commit()

    @contextmanager
    def timer(self, name: str, **labels):
        """Context manager 计时,自动写入 histogram"""
        t0 = time.perf_counter()
        yield
        elapsed = time.perf_counter() - t0
        self.histogram(name, elapsed, **labels)

    # ── 查询 API ──

    def query_counter_sum(self, name: str, since_hours: float = 24) -> float:
        """查询计数器在时间窗口内的总和"""
        conn = self._get_conn()
        cutoff = time.time() - since_hours * 3600
        row = conn.execute(
            "SELECT COALESCE(SUM(value), 0) FROM counters WHERE name=? AND ts>?",
            (name, cutoff),
        ).fetchone()
        return row[0] if row else 0

    def query_counter_by_label(self, name: str, label_key: str, since_hours: float = 24) -> dict[str, float]:
        """按 label 分组的计数器"""
        conn = self._get_conn()
        cutoff = time.time() - since_hours * 3600
        rows = conn.execute(
            "SELECT labels, SUM(value) FROM counters WHERE name=? AND ts>? GROUP BY labels",
            (name, cutoff),
        ).fetchall()
        result = {}
        for labels_json, total in rows:
            labels = json.loads(labels_json)
            key = labels.get(label_key, "unknown")
            result[key] = result.get(key, 0) + total
        return result

    def query_histogram_percentiles(
        self, name: str, percentiles: list[int] = None, since_hours: float = 24
    ) -> dict[str, float]:
        """查询直方图的百分位"""
        if percentiles is None:
            percentiles = [50, 95, 99]
        conn = self._get_conn()
        cutoff = time.time() - since_hours * 3600
        rows = conn.execute(
            "SELECT value FROM histograms WHERE name=? AND ts>? ORDER BY value",
            (name, cutoff),
        ).fetchall()
        if not rows:
            return {f"p{p}": 0 for p in percentiles}
        values = [r[0] for r in rows]
        n = len(values)
        result = {"count": n, "avg": sum(values) / n}
        for p in percentiles:
            idx = min(int(n * p / 100), n - 1)
            result[f"p{p}"] = round(values[idx], 4)
        return result

    def query_gauge(self, name: str) -> dict[str, float]:
        """查询所有 gauge 的当前值"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT labels, value, ts FROM gauges WHERE name=?", (name,)
        ).fetchall()
        return {r[0]: {"value": r[1], "ts": r[2]} for r in rows}

    def query_recent_events(self, name: str, limit: int = 50) -> list[dict]:
        """查询最近 N 条事件"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT value, labels, ts FROM counters WHERE name=? ORDER BY ts DESC LIMIT ?",
            (name, limit),
        ).fetchall()
        return [{"value": r[0], "labels": json.loads(r[1]), "ts": r[2]} for r in rows]

    def summary(self, since_hours: float = 24) -> dict[str, Any]:
        """全局摘要"""
        conn = self._get_conn()
        cutoff = time.time() - since_hours * 3600

        counter_names = [r[0] for r in conn.execute(
            "SELECT DISTINCT name FROM counters WHERE ts>?", (cutoff,)
        ).fetchall()]
        hist_names = [r[0] for r in conn.execute(
            "SELECT DISTINCT name FROM histograms WHERE ts>?", (cutoff,)
        ).fetchall()]

        result = {"period_hours": since_hours, "counters": {}, "histograms": {}}
        for name in counter_names:
            result["counters"][name] = self.query_counter_sum(name, since_hours)
        for name in hist_names:
            result["histograms"][name] = self.query_histogram_percentiles(name, [50, 95, 99], since_hours)
        return result


# 全局单例
metrics = MetricsStore()
