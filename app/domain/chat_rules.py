from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class ConversationFlags:
    is_new: bool
    is_active: bool
    is_old: bool
    is_mine: bool


def classify_conversation(
    *,
    last_user_message_at: datetime | None,
    last_support_message_at: datetime | None,
    moderator_participated: bool,
    now: datetime,
    active_hours: int = 24,
) -> ConversationFlags:
    if last_user_message_at is None:
        return ConversationFlags(False, False, False, False)

    cutoff = now - timedelta(hours=active_hours)
    is_active = last_user_message_at >= cutoff
    is_new = last_support_message_at is None or last_user_message_at > last_support_message_at
    return ConversationFlags(
        is_new=is_new,
        is_active=is_active,
        is_old=not is_active,
        is_mine=is_active and moderator_participated,
    )
