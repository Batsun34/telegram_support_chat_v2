from __future__ import annotations

from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import User
from app.domain.enums import ChatBucket, MessageKind
from app.filters import IsModerator
from app.keyboards.moderator import (
    BTN_BACK,
    BTN_BAN,
    BTN_CANCEL,
    BTN_CONFIRM_BAN,
    BTN_INFO,
    BTN_NEWER,
    BTN_OLDER,
    BTN_UNBAN,
    BUCKET_TITLES,
    PAGE_PREFIX,
    chat_list_keyboard,
    confirm_ban_keyboard,
    main_menu_keyboard,
)
from app.services.chats import ChatService
from app.services.views import ViewService, display_user_name
from app.utils.html import h, short
from app.utils.text import TELEGRAM_CAPTION_LIMIT, TELEGRAM_TEXT_LIMIT, split_plain_text
from app.utils.time import aware_utc

router = Router(name="moderator")


def _fmt_dt(value: datetime | None) -> str:
    value = aware_utc(value)
    return value.strftime("%d.%m.%Y %H:%M UTC") if value else "—"


async def _delete_input(message: Message) -> None:
    try:
        await message.delete()
    except TelegramAPIError:
        pass


async def _workspace_notice(
    message: Message,
    view_service: ViewService,
    *,
    moderator_id: int,
    user_id: int,
    text: str,
) -> None:
    await view_service.track_existing_message(moderator_id, user_id, message.message_id)
    sent = await message.answer(text)
    await view_service.track_existing_message(moderator_id, user_id, sent.message_id)


async def _show_main_menu_message(message: Message, view_service: ViewService) -> None:
    if message.from_user is None:
        return
    moderator_id = message.from_user.id
    await _delete_input(message)
    await view_service.close_chat(moderator_id)
    # A reply keyboard and an inline keyboard cannot be attached to the same
    # Telegram message, so remove the chat controls first, then show lists.
    await message.answer("Диалог скрыт.", reply_markup=ReplyKeyboardRemove())
    await message.answer(
        "Панель поддержки. Выберите список диалогов.",
        reply_markup=main_menu_keyboard(),
    )


async def _send_active_info(
    *,
    moderator_id: int,
    bot: Bot,
    db: AsyncSession,
    settings: Settings,
    chat_service: ChatService,
    view_service: ViewService,
) -> None:
    user_id, _, _ = await view_service.get_active(moderator_id)
    if user_id is None:
        await bot.send_message(moderator_id, "Сначала откройте диалог через /menu.")
        return
    info = await chat_service.user_info(db, user_id=user_id)
    if info is None:
        return
    user = info.user
    participants = [settings.moderators.get(mid, str(mid)) for mid in info.moderator_ids]
    participants_text = short(", ".join(participants), 300) if participants else ""
    text = (
        f"ℹ️ <b>{h(short(display_user_name(user), 80))}</b>\n"
        f"ID: <code>{user.telegram_id}</code>\n"
        f"Username: {h('@' + user.username) if user.username else '—'}\n"
        f"Первое обращение: {_fmt_dt(user.created_at)}\n"
        f"Последнее сообщение пользователя: {_fmt_dt(user.last_user_message_at)}\n"
        f"Последний ответ поддержки: {_fmt_dt(user.last_support_message_at)}\n"
        f"Сообщений: <b>{info.message_count}</b> "
        f"(пользователь {info.user_message_count}, поддержка {info.support_message_count})\n"
        f"Отвечали: {h(participants_text) if participants_text else 'никто'}\n"
        f"Бан: <b>{'да' if user.is_banned else 'нет'}</b>"
    )
    sent = await bot.send_message(moderator_id, text)
    await view_service.track_existing_message(moderator_id, user_id, sent.message_id)


@router.message(IsModerator(), Command("menu"))
@router.message(IsModerator(), Command("back"))
async def moderator_menu_command(message: Message, view_service: ViewService) -> None:
    await _show_main_menu_message(message, view_service)


@router.callback_query(IsModerator(), F.data == "menu")
async def moderator_menu_callback(
    callback: CallbackQuery, bot: Bot, view_service: ViewService
) -> None:
    await callback.answer()
    if callback.from_user is None:
        return
    await view_service.close_chat(callback.from_user.id)
    if callback.message:
        try:
            await callback.message.edit_text(
                "Панель поддержки. Выберите список диалогов.",
                reply_markup=main_menu_keyboard(),
            )
            return
        except TelegramAPIError:
            pass
    await bot.send_message(
        callback.from_user.id,
        "Панель поддержки. Выберите список диалогов.",
        reply_markup=main_menu_keyboard(),
    )


@router.callback_query(IsModerator(), F.data.startswith("bucket:"))
async def moderator_bucket(
    callback: CallbackQuery,
    bot: Bot,
    db: AsyncSession,
    chat_service: ChatService,
) -> None:
    await callback.answer()
    if callback.from_user is None or callback.data is None:
        return
    _, bucket_raw, page_raw = callback.data.split(":", 2)
    try:
        bucket = ChatBucket(bucket_raw)
        page = int(page_raw)
    except (ValueError, TypeError):
        return
    result = await chat_service.list_chats(
        db,
        bucket=bucket,
        moderator_id=callback.from_user.id,
        page=page,
    )
    rows: list[tuple[int, str]] = []
    for user in result.users:
        label = display_user_name(user)
        if user.is_banned:
            label = f"🚫 {label}"
        rows.append((user.telegram_id, short(label, 48)))

    text = (
        f"<b>{BUCKET_TITLES[bucket]}</b>\n"
        f"Диалогов: <b>{result.total}</b> · страница {result.page + 1}/{result.pages}"
    )
    markup = chat_list_keyboard(
        rows,
        bucket=bucket,
        page=result.page,
        pages=result.pages,
    )
    if callback.message:
        try:
            await callback.message.edit_text(text, reply_markup=markup)
            return
        except TelegramAPIError:
            pass
    await bot.send_message(callback.from_user.id, text, reply_markup=markup)


@router.callback_query(IsModerator(), F.data.startswith("chat:open:"))
async def open_chat(
    callback: CallbackQuery, bot: Bot, view_service: ViewService
) -> None:
    await callback.answer()
    if callback.from_user is None or callback.data is None:
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        return
    try:
        user_id = int(parts[2])
        page = int(parts[3])
    except ValueError:
        return

    if callback.message:
        try:
            await callback.message.delete()
        except TelegramAPIError:
            pass
    ok = await view_service.open_chat(callback.from_user.id, user_id, page)
    if not ok:
        await bot.send_message(callback.from_user.id, "Диалог не найден.")


# Legacy callbacks are intentionally kept for already-rendered v2.1 workspaces.
# v2.2 no longer creates inline chat controls.
@router.callback_query(IsModerator(), F.data.startswith("chat:page:"))
async def legacy_change_history_page(
    callback: CallbackQuery, view_service: ViewService
) -> None:
    await callback.answer()
    if callback.from_user is None or callback.data is None:
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        return
    try:
        user_id = int(parts[2])
        page = int(parts[3])
    except ValueError:
        return
    await view_service.open_chat(callback.from_user.id, user_id, page)


@router.callback_query(IsModerator(), F.data == "chat:back")
async def legacy_leave_chat(
    callback: CallbackQuery, bot: Bot, view_service: ViewService
) -> None:
    await callback.answer()
    if callback.from_user is None:
        return
    await view_service.close_chat(callback.from_user.id)
    await bot.send_message(
        callback.from_user.id,
        "Панель поддержки. Выберите список диалогов.",
        reply_markup=main_menu_keyboard(),
    )


@router.callback_query(IsModerator(), F.data.startswith("chat:info:"))
async def legacy_chat_info(
    callback: CallbackQuery,
    bot: Bot,
    db: AsyncSession,
    settings: Settings,
    chat_service: ChatService,
    view_service: ViewService,
) -> None:
    await callback.answer()
    if callback.from_user is None:
        return
    await _send_active_info(
        moderator_id=callback.from_user.id,
        bot=bot,
        db=db,
        settings=settings,
        chat_service=chat_service,
        view_service=view_service,
    )


@router.callback_query(IsModerator(), F.data == "noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()


# --- Reply-keyboard controls inside an open chat ---


@router.message(IsModerator(), F.text == BTN_BACK)
async def reply_back(message: Message, view_service: ViewService) -> None:
    await _show_main_menu_message(message, view_service)


@router.message(IsModerator(), F.text == BTN_OLDER)
async def reply_older(message: Message, view_service: ViewService) -> None:
    if message.from_user is None:
        return
    moderator_id = message.from_user.id
    user_id, page, _ = await view_service.get_active(moderator_id)
    await _delete_input(message)
    if user_id is not None:
        await view_service.open_chat(moderator_id, user_id, page + 1)


@router.message(IsModerator(), F.text == BTN_NEWER)
async def reply_newer(message: Message, view_service: ViewService) -> None:
    if message.from_user is None:
        return
    moderator_id = message.from_user.id
    user_id, page, _ = await view_service.get_active(moderator_id)
    await _delete_input(message)
    if user_id is not None:
        await view_service.open_chat(moderator_id, user_id, max(0, page - 1))


@router.message(IsModerator(), F.text.startswith(PAGE_PREFIX))
async def reply_page_indicator(message: Message) -> None:
    # Reply keyboards cannot contain a truly inert label. Treat a tap on the
    # visible page counter as a system action and never forward it to the user.
    await _delete_input(message)


@router.message(IsModerator(), F.text == BTN_INFO)
async def reply_info(
    message: Message,
    bot: Bot,
    db: AsyncSession,
    settings: Settings,
    chat_service: ChatService,
    view_service: ViewService,
) -> None:
    if message.from_user is None:
        return
    await _delete_input(message)
    await _send_active_info(
        moderator_id=message.from_user.id,
        bot=bot,
        db=db,
        settings=settings,
        chat_service=chat_service,
        view_service=view_service,
    )


@router.message(IsModerator(), F.text == BTN_BAN)
async def reply_ask_ban(message: Message, view_service: ViewService) -> None:
    if message.from_user is None:
        return
    moderator_id = message.from_user.id
    user_id, _, _ = await view_service.get_active(moderator_id)
    await _delete_input(message)
    if user_id is None:
        return
    sent = await message.answer(
        "Заблокировать пользователю доступ к поддержке бессрочно?",
        reply_markup=confirm_ban_keyboard(),
    )
    await view_service.track_existing_message(moderator_id, user_id, sent.message_id)


@router.message(IsModerator(), F.text == BTN_CONFIRM_BAN)
async def reply_confirm_ban(
    message: Message,
    db: AsyncSession,
    chat_service: ChatService,
    view_service: ViewService,
) -> None:
    if message.from_user is None:
        return
    moderator_id = message.from_user.id
    user_id, page, _ = await view_service.get_active(moderator_id)
    await _delete_input(message)
    if user_id is None:
        return
    await chat_service.set_ban(
        db,
        actor_id=moderator_id,
        user_id=user_id,
        banned=True,
    )
    await db.commit()
    await view_service.open_chat(moderator_id, user_id, page)


@router.message(IsModerator(), F.text == BTN_UNBAN)
async def reply_unban(
    message: Message,
    db: AsyncSession,
    chat_service: ChatService,
    view_service: ViewService,
) -> None:
    if message.from_user is None:
        return
    moderator_id = message.from_user.id
    user_id, page, _ = await view_service.get_active(moderator_id)
    await _delete_input(message)
    if user_id is None:
        return
    await chat_service.set_ban(
        db,
        actor_id=moderator_id,
        user_id=user_id,
        banned=False,
    )
    await db.commit()
    await view_service.open_chat(moderator_id, user_id, page)


@router.message(IsModerator(), F.text == BTN_CANCEL)
async def reply_cancel(message: Message, view_service: ViewService) -> None:
    if message.from_user is None:
        return
    moderator_id = message.from_user.id
    user_id, page, _ = await view_service.get_active(moderator_id)
    await _delete_input(message)
    if user_id is not None:
        await view_service.open_chat(moderator_id, user_id, page)


@router.message(IsModerator(), F.text.startswith("/"))
async def unknown_moderator_command(message: Message) -> None:
    await message.answer("Неизвестная системная команда. Используйте /menu или /back.")


@router.message(IsModerator())
async def moderator_chat_message(
    message: Message,
    bot: Bot,
    db: AsyncSession,
    settings: Settings,
    chat_service: ChatService,
    view_service: ViewService,
) -> None:
    if message.from_user is None:
        return
    moderator_id = message.from_user.id
    user_id, active_page, _ = await view_service.get_active(moderator_id)
    if user_id is None:
        await message.answer("Сначала откройте диалог через /menu.")
        return
    user = await db.get(User, user_id)
    if user is None:
        await _workspace_notice(
            message,
            view_service,
            moderator_id=moderator_id,
            user_id=user_id,
            text="Пользователь больше не найден в базе.",
        )
        return
    if user.is_banned:
        await _workspace_notice(
            message,
            view_service,
            moderator_id=moderator_id,
            user_id=user_id,
            text="Пользователь заблокирован. Сначала разбаньте его кнопкой «Разбанить».",
        )
        return

    if message.photo:
        kind = MessageKind.PHOTO.value
        text = message.caption
        photo_file_id = message.photo[-1].file_id
    elif message.text is not None:
        kind = MessageKind.TEXT.value
        text = message.text
        photo_file_id = None
    else:
        await _workspace_notice(
            message,
            view_service,
            moderator_id=moderator_id,
            user_id=user_id,
            text="В диалоге поддерживаются только текст и фото.",
        )
        return

    alias = settings.moderators[moderator_id]
    try:
        label = f"🛡 {short(alias, 80)}"
        user_header = f"<b>{h(label)}</b>"
        if kind == MessageKind.TEXT.value:
            room = max(1, TELEGRAM_TEXT_LIMIT - len(label) - 1)
            for chunk in split_plain_text(text, room):
                await bot.send_message(
                    chat_id=user_id,
                    text=f"{user_header}\n{h(chunk)}",
                )
        else:
            full_caption = text or ""
            caption_room = max(1, TELEGRAM_CAPTION_LIMIT - len(label) - 1)
            first_caption = full_caption[:caption_room]
            remaining = full_caption[caption_room:]
            caption = user_header + (f"\n{h(first_caption)}" if first_caption else "")
            await bot.send_photo(chat_id=user_id, photo=photo_file_id, caption=caption)
            if remaining:
                continuation_label = f"{label} · подпись к фото"
                continuation_header = f"{user_header} · <i>подпись к фото</i>"
                room = max(1, TELEGRAM_TEXT_LIMIT - len(continuation_label) - 1)
                for chunk in split_plain_text(remaining, room):
                    await bot.send_message(
                        chat_id=user_id,
                        text=f"{continuation_header}\n{h(chunk)}",
                    )
    except TelegramAPIError:
        await _workspace_notice(
            message,
            view_service,
            moderator_id=moderator_id,
            user_id=user_id,
            text="Не удалось доставить сообщение пользователю через Telegram.",
        )
        return

    stored = await chat_service.record_moderator_message(
        db,
        user=user,
        moderator_id=moderator_id,
        moderator_alias=alias,
        kind=kind,
        text=text,
        photo_file_id=photo_file_id,
        telegram_message_id=message.message_id,
    )
    await db.commit()

    try:
        await message.delete()
    except TelegramAPIError:
        await view_service.track_existing_message(moderator_id, user_id, message.message_id)

    await view_service.broadcast_moderator_message(user, stored)
    if active_page != 0:
        await view_service.open_chat(moderator_id, user_id, 0)
