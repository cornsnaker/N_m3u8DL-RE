"""Rich-text formatting helpers (HTML mode for Telegram blockquote cards)."""

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
    """Inline monospace span."""

    return f"<code>{escape(text)}</code>"


def bold(text: str) -> str:
    """Bold an already-escaped fragment."""

    return f"<b>{text}</b>"


def pre(text: object) -> str:
    """Preformatted block."""

    return f"<pre>{escape(text)}</pre>"


def quote_block(lines: Iterable[str]) -> str:
    """Wrap pre-rendered (already escaped) lines in a single blockquote card."""

    return "<blockquote>" + "\n".join(lines) + "</blockquote>"
