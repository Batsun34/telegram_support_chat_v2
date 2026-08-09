from aiogram import Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import MessageKind
from app.filters import IsRegularUser
from app.services.chats import ChatService
from app.services.notifier import NotificationDebouncer

router = Router(name="user")


@router.message(IsRegularUser())
async def user_message(
    message: Message,
    db: AsyncSession,
    chat_service: ChatService,
    notifier: NotificationDebouncer,
) -> None:
    if message.from_user is None:
        return

    user = await chat_service.upsert_user(
        db,
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name,
    )
    if user.is_banned:
        await message.answer("Доступ к поддержке ограничен.")
        return

    if message.photo:
        photo = message.photo[-1]
        stored = await chat_service.record_user_message(
            db,
            user=user,
            kind=MessageKind.PHOTO.value,
            text=message.caption,
            photo_file_id=photo.file_id,
            telegram_message_id=message.message_id,
        )
    elif message.text is not None:
        stored = await chat_service.record_user_message(
            db,
            user=user,
            kind=MessageKind.TEXT.value,
            text=message.text,
            photo_file_id=None,
            telegram_message_id=message.message_id,
        )
    else:
        await message.answer("Этот тип сообщения не поддерживается. Отправьте текст или фотографию.")
        return

    # Persist before scheduling: this is safe even if DEBOUNCE_SECONDS is
    # configured to zero later. The middleware's final commit is then a no-op.
    await db.commit()
    await notifier.deliver_live(user, stored)
    await notifier.enqueue(user.telegram_id)
