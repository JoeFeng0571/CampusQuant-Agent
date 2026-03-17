"""
db/engine.py — 异步 SQLAlchemy 引擎 & Session 工厂

数据库: SQLite（开发）/ PostgreSQL（生产）
驱动:   aiosqlite（异步 SQLite）

切换到 PostgreSQL 只需修改 DATABASE_URL：
  DATABASE_URL = "postgresql+asyncpg://user:pass@host/dbname"
"""
from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from typing import Optional

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from db.models import Base

# ── 连接字符串 ─────────────────────────────────────────────────
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "sqlite+aiosqlite:///./campusquant.db",
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


# ── 应用启动时建表 ─────────────────────────────────────────────
async def init_db() -> None:
    """在 startup_event 中调用一次，自动创建所有表（幂等）"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
