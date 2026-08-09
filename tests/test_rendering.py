from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.domain.enums import MessageKind, SenderType
from app.domain.rendering import group_history
from app.utils.text import (
    TELEGRAM_TEXT_LIMIT,
    pack_html_sections,
    split_for_html,
    split_plain_text,
    telegram_visible_length,
)


@dataclass
class M:
    id: int
    sender_type: str
    sender_telegram_id: int
    sender_alias: str | None
    kind: str
    text: str | None
    photo_file_id: str | None
    created_at: datetime


def msg(
    mid: int,
    sender: str,
    sender_id: int,
    text: str | None,
    *,
    kind: str = MessageKind.TEXT.value,
    alias: str | None = None,
    photo: str | None = None,
) -> M:
    return M(
        id=mid,
        sender_type=sender,
        sender_telegram_id=sender_id,
        sender_alias=alias,
        kind=kind,
        text=text,
        photo_file_id=photo,
        created_at=datetime(2026, 8, 8, 12, mid, tzinfo=timezone.utc),
    )


def test_consecutive_user_text_is_grouped() -> None:
    blocks = group_history(
        [
            msg(1, SenderType.USER.value, 100, "привет"),
            msg(2, SenderType.USER.value, 100, "есть вопрос"),
        ]
    )
    assert len(blocks) == 1
    assert blocks[0].text == "привет\nесть вопрос"
    assert blocks[0].source_message_ids == (1, 2)


def test_different_moderators_are_not_grouped() -> None:
    blocks = group_history(
        [
            msg(1, SenderType.MODERATOR.value, 10, "ответ 1", alias="Алекс"),
            msg(2, SenderType.MODERATOR.value, 11, "ответ 2", alias="Мария"),
        ]
    )
    assert len(blocks) == 2


def test_photo_breaks_text_group_and_is_standalone() -> None:
    blocks = group_history(
        [
            msg(1, SenderType.USER.value, 100, "до"),
            msg(
                2,
                SenderType.USER.value,
                100,
                "подпись",
                kind=MessageKind.PHOTO.value,
                photo="file-id",
            ),
            msg(3, SenderType.USER.value, 100, "после"),
        ]
    )
    assert [b.kind for b in blocks] == ["text", "photo", "text"]
    assert blocks[1].source_message_ids == (2,)


def test_long_source_is_not_split_by_internal_rendering_limit() -> None:
    huge = "Здравствуйте " * 300
    assert len(huge) > 3000
    blocks = group_history([msg(1, SenderType.USER.value, 100, huge)])
    assert len(blocks) == 1
    assert blocks[0].text == huge


def test_plain_splitter_uses_real_telegram_text_capacity() -> None:
    text = "Я" * 4050
    assert split_plain_text(text, 4050) == [text]
    assert len(split_plain_text(text + "ещё", 4050)) == 2


def test_html_heavy_compat_splitter_still_round_trips() -> None:
    from html import escape

    chunks = split_for_html("&" * 1000, 3300)
    assert len(chunks) == 2
    assert all(len(escape(chunk, quote=False)) <= 3300 for chunk in chunks)
    assert "".join(chunks) == "&" * 1000


def test_history_sections_from_different_authors_fit_one_telegram_message() -> None:
    sections = [
        "<b>👤 Zzzler</b> · <i>09.08 09:05 UTC</i>\n"
        "<blockquote>Здравствуйте, у меня есть 2 уха и 2 глаза.\nКак вы могли бы мне помочь?</blockquote>",
        "<b>🛡 Igor</b> · <i>09.08 09:05 UTC</i>\n"
        "<blockquote>Привет, а рот один?</blockquote>",
        "<b>👤 Zzzler</b> · <i>09.08 09:05 UTC</i>\n"
        "<blockquote>Да, один</blockquote>",
    ]
    packed = pack_html_sections(sections)
    assert len(packed) == 1
    assert "👤 Zzzler" in packed[0]
    assert "🛡 Igor" in packed[0]
    assert "Да, один" in packed[0]
    assert telegram_visible_length(packed[0]) <= TELEGRAM_TEXT_LIMIT


def test_packer_counts_visible_text_not_html_source_length() -> None:
    section = "<blockquote>" + ("&amp;" * 1000) + "</blockquote>"
    assert len(section) > TELEGRAM_TEXT_LIMIT
    assert telegram_visible_length(section) == 1000
    assert pack_html_sections([section]) == [section]


def test_delivery_proxy_marker_is_removed_from_view_code() -> None:
    source = (Path(__file__).parents[1] / "app/services/views.py").read_text()
    assert "после этого пользователь ответил" not in source
    assert "✓ отправлено" not in source


def test_history_controls_are_no_longer_inline_in_view_code() -> None:
    source = (Path(__file__).parents[1] / "app/services/views.py").read_text()
    assert "history_controls" not in source
    assert "chat_controls_keyboard" in source


def test_default_history_page_size_is_ten() -> None:
    from app.config import Settings

    settings = Settings(
        BOT_TOKEN="test-token",
        MODERATORS_JSON='{"1":"Igor"}',
        _env_file=None,
    )
    assert settings.history_page_size == 10
