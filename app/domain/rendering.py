from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Protocol

from app.domain.enums import MessageKind, SenderType


class MessageLike(Protocol):
    id: int
    sender_type: str
    sender_telegram_id: int
    sender_alias: str | None
    kind: str
    text: str | None
    photo_file_id: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RenderBlock:
    sender_type: str
    sender_telegram_id: int
    sender_alias: str | None
    kind: str
    text: str | None
    photo_file_id: str | None
    first_created_at: datetime
    last_created_at: datetime
    source_message_ids: tuple[int, ...]


def group_history(messages: Iterable[MessageLike]) -> list[RenderBlock]:
    """Group consecutive text messages from the same logical author.

    We deliberately do not split by an artificial internal character limit.
    Telegram-sized splitting happens later, after the visible header is known,
    so a long source message remains whole whenever it actually fits Bot API's
    text limit. Photos are always standalone and break a text group.
    """
    result: list[RenderBlock] = []
    pending: list[MessageLike] = []

    def flush_pending() -> None:
        nonlocal pending
        if not pending:
            return
        result.append(
            RenderBlock(
                sender_type=pending[0].sender_type,
                sender_telegram_id=pending[0].sender_telegram_id,
                sender_alias=pending[0].sender_alias,
                kind=MessageKind.TEXT.value,
                text="\n".join((m.text or "") for m in pending),
                photo_file_id=None,
                first_created_at=pending[0].created_at,
                last_created_at=pending[-1].created_at,
                source_message_ids=tuple(m.id for m in pending),
            )
        )
        pending = []

    for message in messages:
        if message.kind == MessageKind.PHOTO.value:
            flush_pending()
            result.append(
                RenderBlock(
                    sender_type=message.sender_type,
                    sender_telegram_id=message.sender_telegram_id,
                    sender_alias=message.sender_alias,
                    kind=MessageKind.PHOTO.value,
                    text=message.text,
                    photo_file_id=message.photo_file_id,
                    first_created_at=message.created_at,
                    last_created_at=message.created_at,
                    source_message_ids=(message.id,),
                )
            )
            continue

        if not pending:
            pending = [message]
            continue

        previous = pending[-1]
        same_author = (
            previous.sender_type == message.sender_type
            and previous.sender_telegram_id == message.sender_telegram_id
            and previous.sender_alias == message.sender_alias
            and previous.kind == MessageKind.TEXT.value
        )
        if same_author:
            pending.append(message)
        else:
            flush_pending()
            pending = [message]

    flush_pending()
    return result


def sender_label(block: RenderBlock, user_name: str) -> str:
    if block.sender_type == SenderType.USER.value:
        return f"👤 {user_name}"
    return f"🛡 {block.sender_alias or 'Поддержка'}"
