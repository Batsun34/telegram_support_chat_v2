import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings


class DbSessionMiddleware(BaseMiddleware):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self.session_factory() as db:
            data["db"] = db
            try:
                result = await handler(event, data)
                await db.commit()
                return result
            except Exception:
                await db.rollback()
                raise


class ModeratorSerialMiddleware(BaseMiddleware):
    """Serialize updates from the same moderator inside one bot process.

    Different moderators still run concurrently. This preserves reply/UI order
    when Telegram delivers several moderator updates almost simultaneously.
    """

    def __init__(self, settings: Settings) -> None:
        self.moderator_ids = set(settings.moderators)
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock_for(self, moderator_id: int) -> asyncio.Lock:
        lock = self._locks.get(moderator_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[moderator_id] = lock
        return lock

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        from_user = getattr(event, "from_user", None)
        if from_user is None or from_user.id not in self.moderator_ids:
            return await handler(event, data)
        async with self._lock_for(from_user.id):
            return await handler(event, data)
