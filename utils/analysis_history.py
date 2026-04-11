"""
utils/analysis_history.py — 分析历史记录存储

每次分析完成后自动保存摘要到 SQLite，用户可回看。
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from loguru import logger

_DB_PATH = Path(__file__).parent.parent / "data" / "analysis_history.db"
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def _get_conn():
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("""CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        action TEXT,
        confidence REAL,
        risk_level TEXT,
        reasoning TEXT,
        markdown_report TEXT,
        user_id TEXT DEFAULT 'anonymous',
        created_at REAL DEFAULT (strftime('%s','now')),
        metadata TEXT
    )""")
    return conn


def save_analysis(symbol: str, result: dict, user_id: str = "anonymous"):
    """分析完成后保存摘要"""
    try:
        conn = _get_conn()
        trade_order = result.get("trade_order", {}) or {}
        conn.execute(
            "INSERT INTO history (symbol, action, confidence, risk_level, reasoning, markdown_report, user_id, metadata) VALUES (?,?,?,?,?,?,?,?)",
            (
                symbol,
                trade_order.get("action", "HOLD"),
                trade_order.get("confidence", 0),
                trade_order.get("risk_level", ""),
                trade_order.get("rationale", "")[:500],
                result.get("final_markdown_report", "")[:10000],
                user_id,
                json.dumps({"status": result.get("status")}, ensure_ascii=False),
            ),
        )
        conn.commit()
        conn.close()
        logger.info(f"[History] 保存分析记录: {symbol} → {trade_order.get('action', '?')}")
    except Exception as e:
        logger.warning(f"[History] 保存失败: {e}")


def get_history(user_id: str = None, limit: int = 20, offset: int = 0) -> list[dict]:
    """获取历史记录"""
    try:
        conn = _get_conn()
        if user_id:
            rows = conn.execute(
                "SELECT id, symbol, action, confidence, risk_level, reasoning, created_at FROM history WHERE user_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (user_id, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, symbol, action, confidence, risk_level, reasoning, created_at FROM history ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        conn.close()
        return [
            {"id": r[0], "symbol": r[1], "action": r[2], "confidence": r[3],
             "risk_level": r[4], "reasoning": r[5][:100], "created_at": r[6]}
            for r in rows
        ]
    except Exception as e:
        logger.warning(f"[History] 查询失败: {e}")
        return []


def get_report(record_id: int) -> dict | None:
    """获取单条完整研报"""
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT id, symbol, action, confidence, risk_level, reasoning, markdown_report, created_at FROM history WHERE id=?",
            (record_id,),
        ).fetchone()
        conn.close()
        if not row:
            return None
        return {
            "id": row[0], "symbol": row[1], "action": row[2], "confidence": row[3],
            "risk_level": row[4], "reasoning": row[5], "markdown_report": row[6], "created_at": row[7],
        }
    except Exception as e:
        logger.warning(f"[History] 查询失败: {e}")
        return None
