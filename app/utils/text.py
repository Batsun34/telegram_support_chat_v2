from __future__ import annotations

import re
from html import escape, unescape

TELEGRAM_TEXT_LIMIT = 4096
TELEGRAM_CAPTION_LIMIT = 1024
_TAG_RE = re.compile(r"<[^>]+>")



def split_for_html(text: str | None, max_escaped_chars: int) -> list[str]:
    """Compatibility helper for conservative notification/caption paths.

    History rendering no longer uses this function; it works with Telegram's
    post-entity-parsing visible limit instead.
    """
    value = text or ""
    if not value:
        return [""]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for char in value:
        escaped_len = len(escape(char, quote=False))
        if current and current_len + escaped_len > max_escaped_chars:
            chunks.append("".join(current))
            current = []
            current_len = 0
        current.append(char)
        current_len += escaped_len
    if current:
        chunks.append("".join(current))
    return chunks

def split_plain_text(text: str | None, max_chars: int) -> list[str]:
    """Split plain text only when the final Telegram message requires it.

    The input is plain text, so HTML escaping does not reduce the amount of
    user-visible content that Telegram accepts: Bot API's text limit is applied
    after entity parsing. We therefore split by visible characters, not by the
    length of escaped HTML source.
    """
    value = text or ""
    if not value:
        return [""]
    return [value[i : i + max_chars] for i in range(0, len(value), max_chars)]


def telegram_visible_length(html_text: str) -> int:
    """Approximate Bot API's post-entity-parsing character count for our HTML.

    Rendering code only emits simple Telegram-supported tags, while all user
    text is escaped first, so stripping tags and unescaping entities yields the
    visible message text used for the 4096-character limit.
    """
    return len(unescape(_TAG_RE.sub("", html_text)))


def pack_html_sections(sections: list[str], limit: int = TELEGRAM_TEXT_LIMIT) -> list[str]:
    """Pack rendered HTML sections up to Telegram's real visible-text limit.

    Different authors may share one Telegram message because every section has
    its own visible 👤/🛡 header. A section is kept intact when it fits; callers
    split an individual oversized section before handing it here.
    """
    packed: list[str] = []
    current = ""
    current_visible = 0
    for section in sections:
        if not section:
            continue
        section_visible = telegram_visible_length(section)
        separator_visible = 2 if current else 0
        if current and current_visible + separator_visible + section_visible > limit:
            packed.append(current)
            current = section
            current_visible = section_visible
            continue
        current = section if not current else f"{current}\n\n{section}"
        current_visible += separator_visible + section_visible
    if current:
        packed.append(current)
    return packed
