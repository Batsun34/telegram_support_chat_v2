from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import SupportMessage, User
from app.domain.enums import MessageKind
from app.keyboards.moderator import open_chat_keyboard
from app.services.chats import ChatService
from app.services.views import ViewService, display_user_name
from app.utils.html import h, short
from app.utils.text import split_for_html

logger = logging.getLogger(__name__)


class NotificationDebouncer:
    """Debounce user bursts without losing the raw messages in the database.

    Each incoming message is committed before enqueue(). The worker waits until
    DEBOUNCE_SECONDS have passed since the most recent message from that user.
    On restart, recover_pending() schedules any rows that were saved but never
    dispatched.
    """

    def __init__(
        self,
        bot: Bot,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        chat_service: ChatService,
        view_service: ViewService,
    ) -> None:
        self.bot = bot
        self.settings = settings
        self.session_factory = session_factory
        self.chat_service = chat_service
        self.view_service = view_service
        self._deadlines: dict[int, float] = {}
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    async def deliver_live(self, user: User, message: SupportMessage) -> None:
        """Deliver immediately to moderators who currently have this chat open."""
        try:
            await self.view_service.broadcast_user_message(user, message)
        except Exception:
            logger.exception("Immediate live delivery failed for user %s", user.telegram_id)

    async def enqueue(self, user_id: int, *, delay: float | None = None) -> None:
        loop = asyncio.get_running_loop()
        wait = self.settings.debounce_seconds if delay is None else delay
        async with self._lock:
            self._deadlines[user_id] = loop.time() + max(0.0, wait)
            task = self._tasks.get(user_id)
            if task is None or task.done():
                self._tasks[user_id] = asyncio.create_task(
                    self._worker(user_id), name=f"notify-user-{user_id}"
                )

    async def _worker(self, user_id: int) -> None:
        loop = asyncio.get_running_loop()
        try:
            while True:
                async with self._lock:
                    target = self._deadlines.get(user_id)
                if target is None:
                    return
                remaining = target - loop.time()
                if remaining > 0:
                    await asyncio.sleep(remaining)

                async with self._lock:
                    current = self._deadlines.get(user_id)
                if current != target:
                    continue

                await self.flush(user_id)

                async with self._lock:
                    if self._deadlines.get(user_id) == target:
                        self._deadlines.pop(user_id, None)
                        self._tasks.pop(user_id, None)
                        return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Debounce worker failed for user %s", user_id)
            async with self._lock:
                self._tasks.pop(user_id, None)

    @staticmethod
    def _digest_text(messages: Iterable[SupportMessage]) -> tuple[str, int]:
        text_parts: list[str] = []
        photos = 0
        for message in messages:
            if message.kind == MessageKind.PHOTO.value:
                photos += 1
                if message.text:
                    text_parts.append(message.text)
            elif message.text:
                text_parts.append(message.text)
        return "\n".join(text_parts), photos

    async def _send_compact_notification(
        self,
        moderator_id: int,
        user: User,
        messages: list[SupportMessage],
    ) -> None:
        text, photos = self._digest_text(messages)
        pieces = [f"🔔 <b>{h(short(display_user_name(user), 80))}</b>"]
        if text:
            text_chunks = split_for_html(text, 1800)
            preview = text_chunks[0]
            if len(text_chunks) > 1:
                preview += "…"
            pieces.append(f"<blockquote>{h(preview)}</blockquote>")
        if photos:
            pieces.append(f"📷 Фото: <b>{photos}</b>")
        pieces.append(f"Новых исходных сообщений: <b>{len(messages)}</b>")
        await self.bot.send_message(
            chat_id=moderator_id,
            text="\n".join(pieces),
            reply_markup=open_chat_keyboard(user.telegram_id),
        )

    async def flush(self, user_id: int) -> None:
        async with self.session_factory() as db:
            user = await db.get(User, user_id)
            if user is None:
                return
            messages = await self.chat_service.pending_user_messages(db, user_id=user_id)
            if not messages:
                return

        for moderator_id in self.settings.moderators:
            try:
                active_user_id, _, _ = await self.view_service.get_active(moderator_id)
                if active_user_id == user_id:
                    # Normally already delivered immediately. This is also a
                    # 10-second recovery attempt if the immediate send failed.
                    await self.view_service.render_live_user_batch(
                        moderator_id, user, messages
                    )
                else:
                    await self._send_compact_notification(moderator_id, user, messages)
            except TelegramAPIError:
                logger.warning(
                    "Could not notify moderator %s about user %s. "
                    "Moderator probably has not started the bot or blocked it.",
                    moderator_id,
                    user_id,
                )
            except Exception:
                logger.exception(
                    "Unexpected notification error moderator=%s user=%s",
                    moderator_id,
                    user_id,
                )

        async with self.session_factory() as db:
            fresh = await self.chat_service.pending_user_messages(db, user_id=user_id)
            selected_ids = {message.id for message in messages}
            selected = [message for message in fresh if message.id in selected_ids]
            await self.chat_service.mark_notified(db, selected)
            await db.commit()

    async def recover_pending(self) -> None:
        async with self.session_factory() as db:
            user_ids = await self.chat_service.pending_user_ids(db)
        for user_id in user_ids:
            await self.enqueue(user_id, delay=0.5)

    async def shutdown(self) -> None:
        async with self._lock:
            tasks = list(self._tasks.values())
            self._tasks.clear()
            self._deadlines.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
