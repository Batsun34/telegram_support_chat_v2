from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.domain.enums import ChatBucket


BUCKET_TITLES = {
    ChatBucket.NEW: "🆕 Новые",
    ChatBucket.ACTIVE: "🟢 Активные",
    ChatBucket.MINE: "👤 Мои",
    ChatBucket.OLD: "🗄 Старые",
}

BTN_OLDER = "⬅️ Старее"
BTN_NEWER = "Новее ➡️"
BTN_INFO = "ℹ️ Инфо"
BTN_BAN = "🚫 Бан"
BTN_UNBAN = "✅ Разбанить"
BTN_BACK = "◀️ К спискам"
BTN_CONFIRM_BAN = "⚠️ Подтвердить бан"
BTN_CANCEL = "Отмена"
PAGE_PREFIX = "📄 "


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🆕 Новые", callback_data="bucket:new:0"),
                InlineKeyboardButton(text="🟢 Активные", callback_data="bucket:active:0"),
            ],
            [
                InlineKeyboardButton(text="👤 Мои", callback_data="bucket:mine:0"),
                InlineKeyboardButton(text="🗄 Старые", callback_data="bucket:old:0"),
            ],
        ]
    )


def chat_list_keyboard(
    users: list[tuple[int, str]],
    *,
    bucket: ChatBucket,
    page: int,
    pages: int,
) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"chat:open:{user_id}:0")]
        for user_id, label in users
    ]
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"bucket:{bucket.value}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="noop"))
    if page + 1 < pages:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"bucket:{bucket.value}:{page + 1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton(text="🏠 Меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def chat_controls_keyboard(*, page: int, pages: int, banned: bool) -> ReplyKeyboardMarkup:
    nav: list[KeyboardButton] = []
    if page + 1 < pages:
        nav.append(KeyboardButton(text=BTN_OLDER))
    nav.append(KeyboardButton(text=f"{PAGE_PREFIX}{page + 1}/{pages}"))
    if page > 0:
        nav.append(KeyboardButton(text=BTN_NEWER))

    return ReplyKeyboardMarkup(
        keyboard=[
            nav,
            [
                KeyboardButton(text=BTN_INFO),
                KeyboardButton(text=BTN_UNBAN if banned else BTN_BAN),
            ],
            [KeyboardButton(text=BTN_BACK)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Сообщение пользователю…",
    )


def confirm_ban_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_CONFIRM_BAN), KeyboardButton(text=BTN_CANCEL)],
            [KeyboardButton(text=BTN_BACK)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Подтвердите действие",
    )


def open_chat_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть диалог", callback_data=f"chat:open:{user_id}:0")]
        ]
    )
