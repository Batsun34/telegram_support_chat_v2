from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.services.chats import ChatService
from app.services.views import ViewService
from app.keyboards.moderator import main_menu_keyboard

router = Router(name="common")


@router.message(CommandStart())
async def start(
    message: Message,
    settings: Settings,
    db: AsyncSession,
    chat_service: ChatService,
    view_service: ViewService,
) -> None:
    if message.from_user is None:
        return
    telegram_id = message.from_user.id
    if telegram_id in settings.moderators:
        await view_service.close_chat(telegram_id)
        await message.answer("Панель модератора.", reply_markup=ReplyKeyboardRemove())
        await message.answer(
            "Откройте любой диалог; закреплений нет — несколько модераторов "
            "могут отвечать одновременно.",
            reply_markup=main_menu_keyboard(),
        )
        return

    user = await chat_service.upsert_user(
        db,
        telegram_id=telegram_id,
        username=message.from_user.username,
        full_name=message.from_user.full_name,
    )
    if user.is_banned:
        await message.answer("Доступ к поддержке ограничен.")
        return
    await message.answer("Здравствуйте! Напишите, чем можем помочь. Можно отправить текст или фото.")
