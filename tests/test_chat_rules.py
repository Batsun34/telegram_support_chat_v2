from datetime import datetime, timedelta, timezone

from app.domain.chat_rules import classify_conversation


def test_new_active_chat() -> None:
    now = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    flags = classify_conversation(
        last_user_message_at=now - timedelta(minutes=2),
        last_support_message_at=now - timedelta(hours=1),
        moderator_participated=False,
        now=now,
    )
    assert flags.is_new
    assert flags.is_active
    assert not flags.is_old
    assert not flags.is_mine


def test_mine_requires_active_and_participation() -> None:
    now = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    flags = classify_conversation(
        last_user_message_at=now - timedelta(hours=2),
        last_support_message_at=now - timedelta(hours=1),
        moderator_participated=True,
        now=now,
    )
    assert flags.is_active
    assert flags.is_mine
    assert not flags.is_new


def test_old_chat_is_not_mine_even_if_participated() -> None:
    now = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    flags = classify_conversation(
        last_user_message_at=now - timedelta(hours=25),
        last_support_message_at=now - timedelta(hours=24),
        moderator_participated=True,
        now=now,
    )
    assert flags.is_old
    assert not flags.is_active
    assert not flags.is_mine
