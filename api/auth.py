"""
api/auth.py — JWT 认证模块

提供:
  create_access_token(data)     → JWT 字符串
  get_current_user(token, db)   → User（FastAPI Depends，强制登录）
  get_optional_user(token, db)  → User | None（可选认证，兼容游客模式）
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud import get_user_by_id
from db.engine import get_db
from db.models import User

# ── 配置 ───────────────────────────────────────────────────────
SECRET_KEY:  str = os.getenv("JWT_SECRET_KEY", "")
if not SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET_KEY 环境变量未设置。请在 .env 中配置一个强随机密钥。"
    )
ALGORITHM:   str = "HS256"
EXPIRE_DAYS: int = 7    # Token 有效期 7 天（学生频繁使用，减少重新登录摩擦）

# ── HTTP Bearer 解析（不强制必须存在）──────────────────────────
_bearer = HTTPBearer(auto_error=False)


# ── Token 生成 ─────────────────────────────────────────────────

def create_access_token(user_id: int, username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=EXPIRE_DAYS)
    payload = {
        "sub":      str(user_id),
        "username": username,
        "exp":      expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


# ── 内部解码 ───────────────────────────────────────────────────

def _decode_token(token: str) -> dict:
    """解码 JWT，失败抛 HTTPException 401"""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 无效或已过期，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── FastAPI 依赖：强制认证 ─────────────────────────────────────

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """需要登录的端点使用此依赖，未携带 Token 直接返回 401"""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload  = _decode_token(credentials.credentials)
    user_id  = int(payload.get("sub", 0))
    user     = await get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已被禁用")
    return user


# ── FastAPI 依赖：可选认证（兼容游客）─────────────────────────

async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """
    不强制登录。
    - 携带有效 Token → 返回 User
    - 未携带 / Token 无效 → 返回 None（游客模式）
    """
    if not credentials:
        return None
    try:
        payload = _decode_token(credentials.credentials)
        user_id = int(payload.get("sub", 0))
        return await get_user_by_id(db, user_id)
    except HTTPException:
        return None
