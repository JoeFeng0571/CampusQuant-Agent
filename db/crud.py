"""
db/crud.py — 全部异步 CRUD 操作

函数命名规范:
  get_*    — 查询，不修改数据
  create_* — 新建记录
  upsert_* — 插入或更新
  delete_* — 删除记录
  toggle_* — 切换布尔状态（如点赞/取消赞）
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from passlib.context import CryptContext
from sqlalchemy import delete, desc, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    ChatMessage, ChatSession,
    CommunityComment, CommunityPost, PostLike,
    Order, Position, User, VirtualAccount,
)

# ── 密码哈希 ───────────────────────────────────────────────────
_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_ctx.verify(plain, hashed)


# ════════════════════════════════════════════════════════════════
# 用户
# ════════════════════════════════════════════════════════════════

async def create_user(
    db: AsyncSession,
    username: str,
    email: str,
    password: str,
) -> User:
    user = User(
        username=username,
        email=email.lower(),
        hashed_password=hash_password(password),
    )
    db.add(user)
    await db.flush()   # 获取自增 id，不 commit（由 get_db 统一 commit）
    return user


async def get_user_by_id(db: AsyncSession, user_id: int) -> Optional[User]:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.email == email.lower()))
    return result.scalar_one_or_none()


async def get_user_by_username(db: AsyncSession, username: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


# ════════════════════════════════════════════════════════════════
# 虚拟账户 & 持仓
# ════════════════════════════════════════════════════════════════

async def get_or_create_virtual_account(db: AsyncSession, user_id: int) -> VirtualAccount:
    result = await db.execute(
        select(VirtualAccount).where(VirtualAccount.user_id == user_id)
    )
    account = result.scalar_one_or_none()
    if account is None:
        account = VirtualAccount(user_id=user_id)
        db.add(account)
        await db.flush()
    return account


async def get_positions(db: AsyncSession, account_id: int) -> list[Position]:
    result = await db.execute(
        select(Position).where(Position.account_id == account_id)
    )
    return list(result.scalars().all())


async def upsert_position(
    db: AsyncSession,
    account_id: int,
    symbol: str,
    name: str,
    quantity: float,
    avg_cost: float,
    market_type: str,
) -> Position:
    """插入或更新持仓（加权平均成本由调用方传入已计算好的值）"""
    result = await db.execute(
        select(Position).where(
            Position.account_id == account_id,
            Position.symbol == symbol,
        )
    )
    pos = result.scalar_one_or_none()
    if pos is None:
        pos = Position(
            account_id=account_id,
            symbol=symbol,
            name=name,
            quantity=quantity,
            avg_cost=avg_cost,
            market_type=market_type,
        )
        db.add(pos)
    else:
        pos.name        = name or pos.name
        pos.quantity    = quantity
        pos.avg_cost    = avg_cost
        pos.market_type = market_type
        pos.updated_at  = datetime.now(timezone.utc)
    await db.flush()
    return pos


async def delete_position(db: AsyncSession, account_id: int, symbol: str) -> None:
    await db.execute(
        delete(Position).where(
            Position.account_id == account_id,
            Position.symbol == symbol,
        )
    )


async def create_order(
    db: AsyncSession,
    account_id: int,
    symbol: str,
    name: str,
    action: str,
    quantity: float,
    exec_price: float,
    amount: float,
    fee: float,
    cash_before: float,
    cash_after: float,
    is_spot_price: bool,
    market_type: str,
) -> Order:
    order = Order(
        account_id=account_id,
        symbol=symbol,
        name=name,
        action=action,
        quantity=quantity,
        exec_price=exec_price,
        amount=amount,
        fee=fee,
        cash_before=cash_before,
        cash_after=cash_after,
        is_spot_price=is_spot_price,
        market_type=market_type,
        simulated=True,   # 永远为 True
    )
    db.add(order)
    await db.flush()
    return order


async def update_account_cash(db: AsyncSession, account_id: int, cash: float) -> None:
    result = await db.execute(
        select(VirtualAccount).where(VirtualAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if account:
        account.cash       = cash
        account.updated_at = datetime.now(timezone.utc)


async def get_orders(
    db: AsyncSession,
    account_id: int,
    limit: int = 50,
) -> list[Order]:
    result = await db.execute(
        select(Order)
        .where(Order.account_id == account_id)
        .order_by(desc(Order.created_at))
        .limit(limit)
    )
    return list(result.scalars().all())


# ════════════════════════════════════════════════════════════════
# 财商学长对话记忆
# ════════════════════════════════════════════════════════════════

async def get_or_create_chat_session(
    db: AsyncSession,
    session_key: str,
    user_id: Optional[int] = None,
) -> ChatSession:
    result = await db.execute(
        select(ChatSession).where(ChatSession.session_key == session_key)
    )
    session = result.scalar_one_or_none()
    if session is None:
        session = ChatSession(
            session_key=session_key,
            user_id=user_id,
        )
        db.add(session)
        await db.flush()
    elif user_id and session.user_id is None:
        # 匿名 session 登录后关联用户
        session.user_id = user_id
    return session


async def get_chat_history(
    db: AsyncSession,
    session_id: int,
    limit: int = 20,
) -> list[ChatMessage]:
    """返回最近 limit 条消息，按时间正序（最早在前）"""
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(desc(ChatMessage.created_at))
        .limit(limit)
    )
    messages = list(result.scalars().all())
    return list(reversed(messages))   # 翻转为正序


async def append_chat_message(
    db: AsyncSession,
    session_id: int,
    role: str,
    content: str,
) -> ChatMessage:
    msg = ChatMessage(session_id=session_id, role=role, content=content)
    db.add(msg)
    await db.flush()
    # 更新 session.updated_at
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    s = result.scalar_one_or_none()
    if s:
        s.updated_at = datetime.now(timezone.utc)
    return msg


async def count_chat_messages(db: AsyncSession, session_id: int) -> int:
    result = await db.execute(
        select(func.count()).where(ChatMessage.session_id == session_id)
    )
    return result.scalar_one() or 0


async def save_context_summary(db: AsyncSession, session_id: int, summary: str) -> None:
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    s = result.scalar_one_or_none()
    if s:
        s.context_summary = summary


# ════════════════════════════════════════════════════════════════
# 投教社区
# ════════════════════════════════════════════════════════════════

async def create_post(
    db: AsyncSession,
    user_id: int,
    title: str,
    content: str,
    tag: str = "learn",
) -> CommunityPost:
    post = CommunityPost(user_id=user_id, title=title, content=content, tag=tag)
    db.add(post)
    await db.flush()
    return post


async def get_posts(
    db: AsyncSession,
    tag_filter: Optional[str] = None,
    sort: str = "latest",         # latest | featured | qa
    limit: int = 20,
    offset: int = 0,
) -> list[CommunityPost]:
    q = select(CommunityPost)
    if tag_filter:
        q = q.where(CommunityPost.tag == tag_filter)
    if sort == "featured":
        q = q.order_by(desc(CommunityPost.like_count))
    elif sort == "qa":
        q = q.where(CommunityPost.tag == "learn").order_by(desc(CommunityPost.created_at))
    else:
        q = q.order_by(desc(CommunityPost.created_at))
    q = q.limit(limit).offset(offset)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_post(db: AsyncSession, post_id: int) -> Optional[CommunityPost]:
    result = await db.execute(select(CommunityPost).where(CommunityPost.id == post_id))
    return result.scalar_one_or_none()


async def create_comment(
    db: AsyncSession,
    post_id: int,
    user_id: int,
    content: str,
) -> CommunityComment:
    comment = CommunityComment(post_id=post_id, user_id=user_id, content=content)
    db.add(comment)
    await db.flush()
    return comment


async def get_comments(db: AsyncSession, post_id: int) -> list[CommunityComment]:
    result = await db.execute(
        select(CommunityComment)
        .where(CommunityComment.post_id == post_id)
        .order_by(CommunityComment.created_at)
    )
    return list(result.scalars().all())


async def toggle_like(db: AsyncSession, user_id: int, post_id: int) -> bool:
    """点赞/取消赞。返回 True=已点赞 False=已取消"""
    result = await db.execute(
        select(PostLike).where(
            PostLike.user_id == user_id,
            PostLike.post_id == post_id,
        )
    )
    like = result.scalar_one_or_none()

    post_result = await db.execute(select(CommunityPost).where(CommunityPost.id == post_id))
    post = post_result.scalar_one_or_none()

    if like:
        await db.delete(like)
        if post and post.like_count > 0:
            post.like_count -= 1
        return False
    else:
        db.add(PostLike(user_id=user_id, post_id=post_id))
        if post:
            post.like_count += 1
        return True


async def has_liked(db: AsyncSession, user_id: int, post_id: int) -> bool:
    result = await db.execute(
        select(PostLike).where(
            PostLike.user_id == user_id,
            PostLike.post_id == post_id,
        )
    )
    return result.scalar_one_or_none() is not None
