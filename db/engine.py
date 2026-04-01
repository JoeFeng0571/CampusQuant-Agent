"""
db/engine.py — 异步 SQLAlchemy 引擎 & Session 工厂

当前约束：
  - 默认强制使用外部数据库，不再回落本地 SQLite
  - 生产默认指向宝塔 MySQL
"""
from __future__ import annotations

import os
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from db.models import Base

# ── 连接字符串 ─────────────────────────────────────────────────
# 香港服务器: 远程连接内地 MySQL → DATABASE_URL=mysql+asyncmy://...@47.108.191.110/...
# 内地服务器: 本机连接 → DATABASE_URL=mysql+asyncmy://...@127.0.0.1/...
# 本地开发:   按需指向任一服务器
DATABASE_URL: str = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL 环境变量未设置。请在 .env 中配置数据库连接字符串。"
    )

# ── 引擎 & Session 工厂 ────────────────────────────────────────
engine = create_async_engine(
    DATABASE_URL,
    echo=False,           # 生产设 False；调试设 True 可看 SQL
    future=True,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


# ── FastAPI 依赖注入：每请求一个 Session ───────────────────────
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Depends — 每次请求自动创建 / 关闭 Session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── 应用启动时建表 + 迁移 ──────────────────────────────────────
async def init_db() -> None:
    """在 startup_event 中调用一次，自动创建所有表（幂等），并迁移新列。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if DATABASE_URL.startswith("sqlite"):
            await _sqlite_migrate_virtual_accounts(conn)


async def _sqlite_migrate_virtual_accounts(conn) -> None:
    """
    SQLite 不支持 IF NOT EXISTS 加列，通过 PRAGMA table_info 判断后再 ALTER。
    幂等：列已存在时直接跳过。
    """
    result = await conn.execute(text("PRAGMA table_info(virtual_accounts)"))
    existing = {row[1] for row in result.fetchall()}  # row[1] = column name

    new_cols = [
        ("cash_cnh", "FLOAT", 100000.0),
        ("cash_hkd", "FLOAT", 100000.0),
        ("cash_usd", "FLOAT", 10000.0),
        ("init_cnh", "FLOAT", 100000.0),
        ("init_hkd", "FLOAT", 100000.0),
        ("init_usd", "FLOAT", 10000.0),
    ]
    for col, typ, default in new_cols:
        if col not in existing:
            await conn.execute(
                text(f"ALTER TABLE virtual_accounts ADD COLUMN {col} {typ} DEFAULT {default}")
            )
