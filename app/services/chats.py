from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import AuditLog, ModeratorParticipant, SupportMessage, User
from app.domain.enums import ChatBucket, MessageKind, SenderType
from app.utils.time import utcnow


@dataclass(frozen=True, slots=True)
class ChatListPage:
    users: list[User]
    page: int
    pages: int
    total: int


@dataclass(frozen=True, slots=True)
class HistoryPage:
    user: User
    messages: list[SupportMessage]
    page: int
    pages: int
    total: int


@dataclass(frozen=True, slots=True)
class UserInfo:
    user: User
    message_count: int
    user_message_count: int
    support_message_count: int
    moderator_ids: tuple[int, ...]


class ChatService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def upsert_user(
        self,
        db: AsyncSession,
        *,
        telegram_id: int,
        username: str | None,
        full_name: str,
    ) -> User:
        user = await db.get(User, telegram_id)
        now = utcnow()
        if user is None:
            user = User(
                telegram_id=telegram_id,
                username=username,
                full_name=full_name,
                created_at=now,
                updated_at=now,
            )
            db.add(user)
            await db.flush()
            return user
        user.username = username
        user.full_name = full_name
        user.updated_at = now
        return user

    async def record_user_message(
        self,
        db: AsyncSession,
        *,
        user: User,
        kind: str,
        text: str | None,
        photo_file_id: str | None,
        telegram_message_id: int,
    ) -> SupportMessage:
        now = utcnow()
        message = SupportMessage(
            user_id=user.telegram_id,
            sender_type=SenderType.USER.value,
            sender_telegram_id=user.telegram_id,
            sender_alias=None,
            kind=kind,
            text=text,
            photo_file_id=photo_file_id,
            telegram_message_id=telegram_message_id,
            created_at=now,
        )
        db.add(message)
        user.last_user_message_at = now
        user.updated_at = now
        await db.flush()
        return message

    async def record_moderator_message(
        self,
        db: AsyncSession,
        *,
        user: User,
        moderator_id: int,
        moderator_alias: str,
        kind: str,
        text: str | None,
        photo_file_id: str | None,
        telegram_message_id: int,
    ) -> SupportMessage:
        now = utcnow()
        message = SupportMessage(
            user_id=user.telegram_id,
            sender_type=SenderType.MODERATOR.value,
            sender_telegram_id=moderator_id,
            sender_alias=moderator_alias,
            kind=kind,
            text=text,
            photo_file_id=photo_file_id,
            telegram_message_id=telegram_message_id,
            notification_dispatched_at=now,
            created_at=now,
        )
        db.add(message)
        user.last_support_message_at = now
        user.updated_at = now

        participant = await db.scalar(
            select(ModeratorParticipant).where(
                ModeratorParticipant.user_id == user.telegram_id,
                ModeratorParticipant.moderator_id == moderator_id,
            )
        )
        if participant is None:
            db.add(
                ModeratorParticipant(
                    user_id=user.telegram_id,
                    moderator_id=moderator_id,
                    first_replied_at=now,
                    last_replied_at=now,
                    reply_count=1,
                )
            )
        else:
            participant.last_replied_at = now
            participant.reply_count += 1

        # A real moderator reply resolves the currently pending user burst.
        # Messages sent after this reply will form a new 10-second burst.
        await db.execute(
            update(SupportMessage)
            .where(
                SupportMessage.user_id == user.telegram_id,
                SupportMessage.sender_type == SenderType.USER.value,
                SupportMessage.notification_dispatched_at.is_(None),
            )
            .values(notification_dispatched_at=now)
        )

        db.add(
            AuditLog(
                actor_id=moderator_id,
                action="moderator_reply",
                target_user_id=user.telegram_id,
                created_at=now,
            )
        )
        await db.flush()
        return message

    def _bucket_condition(self, bucket: ChatBucket, moderator_id: int):
        cutoff = utcnow() - timedelta(hours=self.settings.active_hours)
        has_user_message = User.last_user_message_at.is_not(None)
        if bucket == ChatBucket.NEW:
            return and_(
                has_user_message,
                or_(
                    User.last_support_message_at.is_(None),
                    User.last_user_message_at > User.last_support_message_at,
                ),
            )
        if bucket == ChatBucket.ACTIVE:
            return and_(has_user_message, User.last_user_message_at >= cutoff)
        if bucket == ChatBucket.OLD:
            return and_(has_user_message, User.last_user_message_at < cutoff)
        if bucket == ChatBucket.MINE:
            participated = exists(
                select(ModeratorParticipant.id).where(
                    ModeratorParticipant.user_id == User.telegram_id,
                    ModeratorParticipant.moderator_id == moderator_id,
                )
            )
            return and_(has_user_message, User.last_user_message_at >= cutoff, participated)
        raise ValueError(f"Unknown bucket: {bucket}")

    async def list_chats(
        self,
        db: AsyncSession,
        *,
        bucket: ChatBucket,
        moderator_id: int,
        page: int,
    ) -> ChatListPage:
        page = max(0, page)
        page_size = self.settings.chat_list_page_size
        condition = self._bucket_condition(bucket, moderator_id)
        total = int(
            await db.scalar(select(func.count()).select_from(User).where(condition)) or 0
        )
        pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, pages - 1)
        users = list(
            (
                await db.scalars(
                    select(User)
                    .where(condition)
                    .order_by(User.last_user_message_at.desc(), User.telegram_id.desc())
                    .offset(page * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return ChatListPage(users=users, page=page, pages=pages, total=total)

    async def history(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        page: int,
    ) -> HistoryPage | None:
        user = await db.get(User, user_id)
        if user is None:
            return None
        page_size = self.settings.history_page_size
        total = int(
            await db.scalar(
                select(func.count()).select_from(SupportMessage).where(
                    SupportMessage.user_id == user_id
                )
            )
            or 0
        )
        pages = max(1, (total + page_size - 1) // page_size)
        page = min(max(0, page), pages - 1)
        rows = list(
            (
                await db.scalars(
                    select(SupportMessage)
                    .where(SupportMessage.user_id == user_id)
                    .order_by(SupportMessage.id.desc())
                    .offset(page * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        rows.reverse()
        return HistoryPage(user=user, messages=rows, page=page, pages=pages, total=total)

    async def pending_user_messages(
        self, db: AsyncSession, *, user_id: int
    ) -> list[SupportMessage]:
        return list(
            (
                await db.scalars(
                    select(SupportMessage)
                    .where(
                        SupportMessage.user_id == user_id,
                        SupportMessage.sender_type == SenderType.USER.value,
                        SupportMessage.notification_dispatched_at.is_(None),
                    )
                    .order_by(SupportMessage.id.asc())
                )
            ).all()
        )

    async def mark_notified(self, db: AsyncSession, messages: list[SupportMessage]) -> None:
        now = utcnow()
        for message in messages:
            message.notification_dispatched_at = now

    async def pending_user_ids(self, db: AsyncSession) -> list[int]:
        return list(
            (
                await db.scalars(
                    select(SupportMessage.user_id)
                    .where(
                        SupportMessage.sender_type == SenderType.USER.value,
                        SupportMessage.notification_dispatched_at.is_(None),
                    )
                    .distinct()
                )
            ).all()
        )

    async def user_info(self, db: AsyncSession, *, user_id: int) -> UserInfo | None:
        user = await db.get(User, user_id)
        if user is None:
            return None
        total = int(
            await db.scalar(
                select(func.count()).select_from(SupportMessage).where(
                    SupportMessage.user_id == user_id
                )
            )
            or 0
        )
        user_count = int(
            await db.scalar(
                select(func.count()).select_from(SupportMessage).where(
                    SupportMessage.user_id == user_id,
                    SupportMessage.sender_type == SenderType.USER.value,
                )
            )
            or 0
        )
        support_count = total - user_count
        moderator_ids = tuple(
            (
                await db.scalars(
                    select(ModeratorParticipant.moderator_id)
                    .where(ModeratorParticipant.user_id == user_id)
                    .order_by(ModeratorParticipant.first_replied_at.asc())
                )
            ).all()
        )
        return UserInfo(
            user=user,
            message_count=total,
            user_message_count=user_count,
            support_message_count=support_count,
            moderator_ids=moderator_ids,
        )

    async def set_ban(
        self,
        db: AsyncSession,
        *,
        actor_id: int,
        user_id: int,
        banned: bool,
    ) -> bool:
        user = await db.get(User, user_id)
        if user is None:
            return False
        user.is_banned = banned
        user.updated_at = utcnow()
        db.add(
            AuditLog(
                actor_id=actor_id,
                action="ban_user" if banned else "unban_user",
                target_user_id=user_id,
                created_at=utcnow(),
            )
        )
        return True
