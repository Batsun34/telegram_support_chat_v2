from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import ModeratorSession, ModeratorViewMessage, SupportMessage, User
from app.domain.enums import MessageKind
from app.domain.rendering import RenderBlock, group_history, sender_label
from app.keyboards.moderator import chat_controls_keyboard
from app.services.chats import ChatService, HistoryPage
from app.utils.html import h, short
from app.utils.text import (
    TELEGRAM_CAPTION_LIMIT,
    TELEGRAM_TEXT_LIMIT,
    pack_html_sections,
    split_plain_text,
)
from app.utils.time import aware_utc, utcnow

logger = logging.getLogger(__name__)

def display_user_name(user: User) -> str:
    if user.full_name.strip():
        return user.full_name.strip()
    if user.username:
        return f"@{user.username}"
    return str(user.telegram_id)


def _time_label(block: RenderBlock) -> str:
    value = aware_utc(block.last_created_at)
    if value is None:
        return ""
    return value.strftime("%d.%m %H:%M UTC")


class ViewService:
    def __init__(
        self,
        bot: Bot,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        chat_service: ChatService,
    ) -> None:
        self.bot = bot
        self.settings = settings
        self.session_factory = session_factory
        self.chat_service = chat_service
        self._moderator_locks: dict[int, asyncio.Lock] = {}

    def _lock_for(self, moderator_id: int) -> asyncio.Lock:
        lock = self._moderator_locks.get(moderator_id)
        if lock is None:
            lock = asyncio.Lock()
            self._moderator_locks[moderator_id] = lock
        return lock

    async def _track(
        self, moderator_id: int, user_id: int | None, telegram_message_id: int
    ) -> None:
        async with self.session_factory() as db:
            db.add(
                ModeratorViewMessage(
                    moderator_id=moderator_id,
                    user_id=user_id,
                    telegram_message_id=telegram_message_id,
                    created_at=utcnow(),
                )
            )
            await db.commit()

    async def track_existing_message(
        self, moderator_id: int, user_id: int | None, telegram_message_id: int
    ) -> None:
        try:
            await self._track(moderator_id, user_id, telegram_message_id)
        except Exception:
            logger.exception("Could not track moderator-side message %s", telegram_message_id)

    async def _delete_ids(self, moderator_id: int, ids: list[int]) -> None:
        for start in range(0, len(ids), 100):
            chunk = ids[start : start + 100]
            try:
                await self.bot.delete_messages(chat_id=moderator_id, message_ids=chunk)
            except TelegramAPIError:
                # A stale >48h message or another Telegram limitation should not
                # prevent the moderator from switching chats. Try individually.
                for message_id in chunk:
                    try:
                        await self.bot.delete_message(chat_id=moderator_id, message_id=message_id)
                    except TelegramAPIError:
                        logger.debug(
                            "Could not delete workspace message moderator=%s message=%s",
                            moderator_id,
                            message_id,
                        )

    async def cleanup_workspace(self, moderator_id: int) -> None:
        async with self.session_factory() as db:
            ids = list(
                (
                    await db.scalars(
                        select(ModeratorViewMessage.telegram_message_id)
                        .where(ModeratorViewMessage.moderator_id == moderator_id)
                        .order_by(ModeratorViewMessage.id.asc())
                    )
                ).all()
            )
        if ids:
            await self._delete_ids(moderator_id, ids)
        async with self.session_factory() as db:
            await db.execute(
                delete(ModeratorViewMessage).where(
                    ModeratorViewMessage.moderator_id == moderator_id
                )
            )
            await db.commit()

    async def set_active(
        self,
        moderator_id: int,
        user_id: int | None,
        page: int = 0,
        last_rendered_message_id: int = 0,
    ) -> None:
        async with self.session_factory() as db:
            session = await db.get(ModeratorSession, moderator_id)
            now = utcnow()
            if session is None:
                session = ModeratorSession(
                    moderator_id=moderator_id,
                    active_user_id=user_id,
                    active_page=page,
                    last_rendered_message_id=last_rendered_message_id,
                    opened_at=now if user_id is not None else None,
                    last_activity_at=now,
                )
                db.add(session)
            else:
                session.active_user_id = user_id
                session.active_page = page
                session.last_rendered_message_id = last_rendered_message_id
                session.opened_at = now if user_id is not None else None
                session.last_activity_at = now
            await db.commit()

    async def get_active(self, moderator_id: int) -> tuple[int | None, int, int]:
        async with self.session_factory() as db:
            session = await db.get(ModeratorSession, moderator_id)
            if session is None:
                return None, 0, 0
            return (
                session.active_user_id,
                session.active_page,
                session.last_rendered_message_id,
            )

    async def touch(self, moderator_id: int) -> None:
        async with self.session_factory() as db:
            session = await db.get(ModeratorSession, moderator_id)
            if session is not None:
                session.last_activity_at = utcnow()
                await db.commit()

    def _text_sections(self, user: User, block: RenderBlock) -> list[str]:
        label = short(sender_label(block, display_user_name(user)), 80)
        time_part = _time_label(block)
        header = f"<b>{h(label)}</b> · <i>{time_part}</i>"
        visible_header = f"{label} · {time_part}\n"
        max_content = max(1, TELEGRAM_TEXT_LIMIT - len(visible_header))
        chunks = split_plain_text(block.text, max_content)
        return [f"{header}\n<blockquote>{h(chunk)}</blockquote>" for chunk in chunks]

    async def _send_text_run(
        self, moderator_id: int, user: User, blocks: list[RenderBlock]
    ) -> list[int]:
        sections: list[str] = []
        for block in blocks:
            sections.extend(self._text_sections(user, block))
        ids: list[int] = []
        for packed in pack_html_sections(sections):
            sent = await self.bot.send_message(chat_id=moderator_id, text=packed)
            ids.append(sent.message_id)
        return ids

    async def _send_block(
        self, moderator_id: int, user: User, block: RenderBlock
    ) -> list[int]:
        if block.kind == MessageKind.TEXT.value:
            return await self._send_text_run(moderator_id, user, [block])

        label = short(sender_label(block, display_user_name(user)), 80)
        time_part = _time_label(block)
        header = f"<b>{h(label)}</b> · <i>{time_part}</i>"
        visible_header = f"{label} · {time_part}"
        caption_room = max(1, TELEGRAM_CAPTION_LIMIT - len(visible_header) - 1)
        full_caption = block.text or ""
        first_caption = full_caption[:caption_room]
        remaining = full_caption[caption_room:]
        caption = header + (f"\n{h(first_caption)}" if first_caption else "")
        sent_photo = await self.bot.send_photo(
            chat_id=moderator_id,
            photo=block.photo_file_id,
            caption=caption,
        )
        ids = [sent_photo.message_id]
        if remaining:
            continuation_header = f"{header} · <i>подпись</i>"
            visible_continuation_header = f"{label} · {time_part} · подпись\n"
            continuation_room = max(
                1, TELEGRAM_TEXT_LIMIT - len(visible_continuation_header)
            )
            for chunk in split_plain_text(remaining, continuation_room):
                sent = await self.bot.send_message(
                    chat_id=moderator_id,
                    text=(
                        f"{continuation_header}\n"
                        f"<blockquote>{h(chunk)}</blockquote>"
                    ),
                )
                ids.append(sent.message_id)
        return ids

    async def _render_page(self, moderator_id: int, history: HistoryPage) -> None:
        user = history.user
        user_name = display_user_name(user)
        username = f"@{user.username}" if user.username else "без username"
        state = "🚫 заблокирован" if user.is_banned else "доступ разрешён"
        header = await self.bot.send_message(
            chat_id=moderator_id,
            text=(
                f"💬 <b>{h(user_name)}</b>\n"
                f"<code>{user.telegram_id}</code> · {h(username)} · {state}\n"
                "Любой обычный текст или фото сейчас уйдёт этому пользователю."
            ),
            reply_markup=chat_controls_keyboard(
                page=history.page,
                pages=history.pages,
                banned=user.is_banned,
            ),
        )
        await self._track(moderator_id, user.telegram_id, header.message_id)

        blocks = group_history(history.messages)
        text_run: list[RenderBlock] = []

        async def flush_text_run() -> None:
            nonlocal text_run
            if not text_run:
                return
            message_ids = await self._send_text_run(moderator_id, user, text_run)
            for message_id in message_ids:
                await self._track(moderator_id, user.telegram_id, message_id)
            text_run = []

        for block in blocks:
            if block.kind == MessageKind.TEXT.value:
                text_run.append(block)
                continue
            await flush_text_run()
            message_ids = await self._send_block(moderator_id, user, block)
            for message_id in message_ids:
                await self._track(moderator_id, user.telegram_id, message_id)
        await flush_text_run()


    async def open_chat(self, moderator_id: int, user_id: int, page: int = 0) -> bool:
        async with self._lock_for(moderator_id):
            await self.cleanup_workspace(moderator_id)
            async with self.session_factory() as db:
                history = await self.chat_service.history(db, user_id=user_id, page=page)
            if history is None:
                await self.set_active(moderator_id, None)
                return False
            last_rendered = (
                max((message.id for message in history.messages), default=0)
                if history.page == 0
                else 0
            )
            await self.set_active(
                moderator_id, user_id, history.page, last_rendered_message_id=last_rendered
            )
            await self._render_page(moderator_id, history)
            return True

    async def close_chat(self, moderator_id: int) -> None:
        async with self._lock_for(moderator_id):
            await self.cleanup_workspace(moderator_id)
            await self.set_active(moderator_id, None, 0)

    async def render_live_user_batch(
        self,
        moderator_id: int,
        user: User,
        messages: list[SupportMessage],
    ) -> None:
        async with self._lock_for(moderator_id):
            async with self.session_factory() as db:
                session = await db.get(ModeratorSession, moderator_id)
                if (
                    session is None
                    or session.active_user_id != user.telegram_id
                ):
                    return
                fresh = [m for m in messages if m.id > session.last_rendered_message_id]
            if not fresh:
                return
            blocks = group_history(fresh)
            for block in blocks:
                message_ids = await self._send_block(moderator_id, user, block)
                for message_id in message_ids:
                    await self._track(moderator_id, user.telegram_id, message_id)
            async with self.session_factory() as db:
                session = await db.get(ModeratorSession, moderator_id)
                if session is not None and session.active_user_id == user.telegram_id:
                    session.last_rendered_message_id = max(m.id for m in fresh)
                    session.last_activity_at = utcnow()
                    await db.commit()

    async def broadcast_user_message(
        self,
        user: User,
        message: SupportMessage,
    ) -> None:
        """Immediately append a new user message to every open moderator chat.

        Unlike debounced notifications, this applies to any currently open
        history page. It never reopens/rerenders the workspace.
        """
        async with self.session_factory() as db:
            sessions = list(
                (
                    await db.scalars(
                        select(ModeratorSession).where(
                            ModeratorSession.active_user_id == user.telegram_id,
                            ModeratorSession.last_rendered_message_id < message.id,
                        )
                    )
                ).all()
            )
        block = group_history([message])[0]
        for session in sessions:
            async with self._lock_for(session.moderator_id):
                async with self.session_factory() as db:
                    current = await db.get(ModeratorSession, session.moderator_id)
                    if (
                        current is None
                        or current.active_user_id != user.telegram_id
                        or current.last_rendered_message_id >= message.id
                    ):
                        continue
                message_ids = await self._send_block(session.moderator_id, user, block)
                for message_id in message_ids:
                    await self._track(session.moderator_id, user.telegram_id, message_id)
                async with self.session_factory() as db:
                    current = await db.get(ModeratorSession, session.moderator_id)
                    if current is not None and current.active_user_id == user.telegram_id:
                        current.last_rendered_message_id = message.id
                        current.last_activity_at = utcnow()
                        await db.commit()

    async def broadcast_moderator_message(
        self,
        user: User,
        message: SupportMessage,
    ) -> None:
        async with self.session_factory() as db:
            sessions = list(
                (
                    await db.scalars(
                        select(ModeratorSession).where(
                            ModeratorSession.active_user_id == user.telegram_id,
                            ModeratorSession.active_page == 0,
                            ModeratorSession.last_rendered_message_id < message.id,
                        )
                    )
                ).all()
            )
        block = group_history([message])[0]
        for session in sessions:
            async with self._lock_for(session.moderator_id):
                async with self.session_factory() as db:
                    current = await db.get(ModeratorSession, session.moderator_id)
                    if (
                        current is None
                        or current.active_user_id != user.telegram_id
                        or current.active_page != 0
                        or current.last_rendered_message_id >= message.id
                    ):
                        continue
                message_ids = await self._send_block(session.moderator_id, user, block)
                for message_id in message_ids:
                    await self._track(session.moderator_id, user.telegram_id, message_id)
                async with self.session_factory() as db:
                    current = await db.get(ModeratorSession, session.moderator_id)
                    if current is not None and current.active_user_id == user.telegram_id:
                        current.last_rendered_message_id = message.id
                        current.last_activity_at = utcnow()
                        await db.commit()

    async def cleanup_expired_sessions(self) -> int:
        cutoff = utcnow() - timedelta(hours=self.settings.view_ttl_hours)
        async with self.session_factory() as db:
            moderator_ids = list(
                (
                    await db.scalars(
                        select(ModeratorSession.moderator_id).where(
                            ModeratorSession.active_user_id.is_not(None),
                            ModeratorSession.last_activity_at < cutoff,
                        )
                    )
                ).all()
            )
        for moderator_id in moderator_ids:
            await self.close_chat(moderator_id)
        return len(moderator_ids)
