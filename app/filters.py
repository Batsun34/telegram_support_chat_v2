from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from app.config import Settings


class IsModerator(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery, settings: Settings) -> bool:
        return bool(event.from_user and event.from_user.id in settings.moderators)


class IsRegularUser(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery, settings: Settings) -> bool:
        return bool(event.from_user and event.from_user.id not in settings.moderators)
