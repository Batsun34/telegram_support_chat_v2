import pytest

pytest.importorskip("aiogram")

from app.keyboards.moderator import BTN_BACK, BTN_INFO, BTN_OLDER, chat_controls_keyboard


def test_chat_controls_are_reply_keyboard() -> None:
    markup = chat_controls_keyboard(page=0, pages=3, banned=False)
    texts = [button.text for row in markup.keyboard for button in row]
    assert BTN_OLDER in texts
    assert BTN_INFO in texts
    assert BTN_BACK in texts
    assert "📄 1/3" in texts
    assert not hasattr(markup, "inline_keyboard")
