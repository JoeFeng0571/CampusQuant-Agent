"""
db/models.py — SQLAlchemy 2.x 声明式 ORM 模型

表结构:
  users              — 用户账号
  virtual_accounts   — 每用户一个虚拟账户（可用资金）
  positions          — 持仓明细（唯一约束: account_id + symbol）
  orders             — 成交记录（只追加，不修改）
  chat_sessions      — 财商学长对话 Session（支持匿名 UUID）
  chat_messages      — 对话消息（按 session 分组）
  community_posts    — 社区帖子
  community_comments — 帖子评论
  post_likes         — 点赞（防重复复合主键）
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey,
    Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ════════════════════════════════════════════════════════════════
# 用户 & 账户
# ════════════════════════════════════════════════════════════════

class User(Base):
    __tablename__ = "users"

    id:              Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    username:        Mapped[str]           = mapped_column(String(50), unique=True, nullable=False)
    email:           Mapped[str]           = mapped_column(String(120), unique=True, nullable=False)
    hashed_password: Mapped[str]           = mapped_column(String(255), nullable=False)
    avatar_url:      Mapped[Optional[str]] = mapped_column(String(500), default=None)
    bio:             Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at:      Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=_now)
    is_active:       Mapped[bool]          = mapped_column(Boolean, default=True)

    # relationships
    account:   Mapped[Optional["VirtualAccount"]] = relationship("VirtualAccount", back_populates="user", uselist=False)
    sessions:  Mapped[list["ChatSession"]]         = relationship("ChatSession", back_populates="user")
    posts:     Mapped[list["CommunityPost"]]       = relationship("CommunityPost", back_populates="user")
    comments:  Mapped[list["CommunityComment"]]    = relationship("CommunityComment", back_populates="user")


class VirtualAccount(Base):
    __tablename__ = "virtual_accounts"

    id:           Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:      Mapped[int]      = mapped_column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    cash:         Mapped[float]    = mapped_column(Float, default=100_000.0)
    initial_cash: Mapped[float]    = mapped_column(Float, default=100_000.0)
    created_at:   Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at:   Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    user:      Mapped["User"]          = relationship("User", back_populates="account")
    positions: Mapped[list["Position"]] = relationship("Position", back_populates="account", cascade="all, delete-orphan")
    orders:    Mapped[list["Order"]]    = relationship("Order",    back_populates="account", cascade="all, delete-orphan")


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("account_id", "symbol", name="uq_account_symbol"),)

    id:          Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id:  Mapped[int]      = mapped_column(Integer, ForeignKey("virtual_accounts.id"), nullable=False)
    symbol:      Mapped[str]      = mapped_column(String(30), nullable=False)
    name:        Mapped[str]      = mapped_column(String(100), default="")
    quantity:    Mapped[float]    = mapped_column(Float, default=0.0)
    avg_cost:    Mapped[float]    = mapped_column(Float, default=0.0)
    market_type: Mapped[str]      = mapped_column(String(20), default="UNKNOWN")
    updated_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    account: Mapped["VirtualAccount"] = relationship("VirtualAccount", back_populates="positions")


class Order(Base):
    __tablename__ = "orders"

    id:            Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id:    Mapped[int]      = mapped_column(Integer, ForeignKey("virtual_accounts.id"), nullable=False)
    symbol:        Mapped[str]      = mapped_column(String(30), nullable=False)
    name:          Mapped[str]      = mapped_column(String(100), default="")
    action:        Mapped[str]      = mapped_column(String(10), nullable=False)   # BUY | SELL
    quantity:      Mapped[float]    = mapped_column(Float, nullable=False)
    exec_price:    Mapped[float]    = mapped_column(Float, nullable=False)
    amount:        Mapped[float]    = mapped_column(Float, nullable=False)
    fee:           Mapped[float]    = mapped_column(Float, nullable=False)
    cash_before:   Mapped[float]    = mapped_column(Float, nullable=False)
    cash_after:    Mapped[float]    = mapped_column(Float, nullable=False)
    is_spot_price: Mapped[bool]     = mapped_column(Boolean, default=True)
    market_type:   Mapped[str]      = mapped_column(String(20), default="UNKNOWN")
    simulated:     Mapped[bool]     = mapped_column(Boolean, default=True)   # 始终为 True
    created_at:    Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    account: Mapped["VirtualAccount"] = relationship("VirtualAccount", back_populates="orders")


# ════════════════════════════════════════════════════════════════
# 财商学长对话记忆
# ════════════════════════════════════════════════════════════════

class ChatSession(Base):
    """一个 session_key 对应一段连续对话（匿名或已登录均可使用）"""
    __tablename__ = "chat_sessions"

    id:              Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:         Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    session_key:     Mapped[str]           = mapped_column(String(64), unique=True, nullable=False)
    context_summary: Mapped[Optional[str]] = mapped_column(Text, default=None)   # 消息超50条后压缩存储
    created_at:      Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=_now)
    updated_at:      Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    user:     Mapped[Optional["User"]]      = relationship("User", back_populates="sessions")
    messages: Mapped[list["ChatMessage"]]   = relationship("ChatMessage", back_populates="session",
                                                            cascade="all, delete-orphan",
                                                            order_by="ChatMessage.created_at")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id:         Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int]      = mapped_column(Integer, ForeignKey("chat_sessions.id"), nullable=False)
    role:       Mapped[str]      = mapped_column(String(20), nullable=False)   # user | assistant
    content:    Mapped[str]      = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    session: Mapped["ChatSession"] = relationship("ChatSession", back_populates="messages")


# ════════════════════════════════════════════════════════════════
# 投教社区
# ════════════════════════════════════════════════════════════════

class CommunityPost(Base):
    __tablename__ = "community_posts"

    id:         Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:    Mapped[int]      = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    title:      Mapped[str]      = mapped_column(String(200), nullable=False)
    content:    Mapped[str]      = mapped_column(Text, nullable=False)
    tag:        Mapped[str]      = mapped_column(String(20), default="learn")  # learn|analysis|risk|exp
    like_count: Mapped[int]      = mapped_column(Integer, default=0)
    view_count: Mapped[int]      = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    user:     Mapped["User"]                  = relationship("User", back_populates="posts")
    comments: Mapped[list["CommunityComment"]] = relationship("CommunityComment", back_populates="post",
                                                               cascade="all, delete-orphan")
    likes:    Mapped[list["PostLike"]]         = relationship("PostLike", back_populates="post",
                                                               cascade="all, delete-orphan")


class CommunityComment(Base):
    __tablename__ = "community_comments"

    id:         Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id:    Mapped[int]      = mapped_column(Integer, ForeignKey("community_posts.id"), nullable=False)
    user_id:    Mapped[int]      = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    content:    Mapped[str]      = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    post: Mapped["CommunityPost"] = relationship("CommunityPost", back_populates="comments")
    user: Mapped["User"]          = relationship("User", back_populates="comments")


class PostLike(Base):
    """防重复点赞复合主键"""
    __tablename__ = "post_likes"
    __table_args__ = (UniqueConstraint("user_id", "post_id", name="uq_user_post_like"),)

    id:      Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    post_id: Mapped[int] = mapped_column(Integer, ForeignKey("community_posts.id"), nullable=False)

    post: Mapped["CommunityPost"] = relationship("CommunityPost", back_populates="likes")
