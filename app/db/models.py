from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_last_user_message", "last_user_message_at"),
        Index("ix_users_last_support_message", "last_support_message_at"),
    )

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    last_user_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_support_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    messages: Mapped[list[SupportMessage]] = relationship(
        back_populates="user", cascade="all, delete-orphan", order_by="SupportMessage.id"
    )


class SupportMessage(Base):
    __tablename__ = "support_messages"
    __table_args__ = (
        Index("ix_support_messages_user_created", "user_id", "created_at"),
        Index("ix_support_messages_pending_notify", "sender_type", "notification_dispatched_at", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False
    )
    sender_type: Mapped[str] = mapped_column(String(16), nullable=False)
    sender_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sender_alias: Mapped[str | None] = mapped_column(String(80), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_file_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notification_dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    user: Mapped[User] = relationship(back_populates="messages")


class ModeratorParticipant(Base):
    __tablename__ = "moderator_participants"
    __table_args__ = (
        UniqueConstraint("user_id", "moderator_id", name="uq_participant_user_mod"),
        Index("ix_participant_mod_last", "moderator_id", "last_replied_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False
    )
    moderator_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    first_replied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_replied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    reply_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class ModeratorSession(Base):
    __tablename__ = "moderator_sessions"

    moderator_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    active_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.telegram_id", ondelete="SET NULL"), nullable=True
    )
    active_page: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_rendered_message_id: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ModeratorViewMessage(Base):
    __tablename__ = "moderator_view_messages"
    __table_args__ = (
        UniqueConstraint("moderator_id", "telegram_message_id", name="uq_view_mod_message"),
        Index("ix_view_mod_created", "moderator_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    moderator_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_actor_created", "actor_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
