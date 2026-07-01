"""Rich-text formatting helpers.

All renderers emit HTML strings for Telegram's HTML parse mode, producing
native blockquote cards.
"""

from __future__ import annotations

from typing import Iterable

PARSE_MODE = "html"


def escape(text: object) -> str:
    """Escape text for safe inclusion in HTML-parsed messages."""

    if text is None:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def code(text: object) -> str:
    return f"<code>{escape(text)}</code>"


def bold(text: str) -> str:
    return f"<b>{text}</b>"


def italic(text: str) -> str:
    return f"<i>{text}</i>"


def pre(text: str) -> str:
    return f"<pre>{escape(text)}</pre>"


def quote_block(lines: Iterable[str]) -> str:
    return "<blockquote>" + "\n".join(lines) + "</blockquote>"
