"""Inline keyboard factories for task control.

Callback payloads use a compact ``action:token`` scheme.
"""

from __future__ import annotations

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

ACT_START = "dl"
ACT_CANCEL = "cxl"
ACT_NOOP = "noop"


def confirm_menu(token: str) -> InlineKeyboardMarkup:
    """Menu shown after user submits a download request."""

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("\U0001f4e5 Start Download", callback_data=f"{ACT_START}:{token}")],
            [InlineKeyboardButton("\u274c Cancel", callback_data=f"{ACT_CANCEL}:{token}")],
        ]
    )


def cancel_only(token: str) -> InlineKeyboardMarkup:
    """Single cancel button shown while a task is running."""

    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("\u274c Cancel Task", callback_data=f"{ACT_CANCEL}:{token}")]]
    )


def parse_callback(data: str) -> tuple[str, list[str]]:
    """Split callback data into ``(action, [args...])``."""

    parts = data.split(":")
    return parts[0], parts[1:]
