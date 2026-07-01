"""Inline keyboard factories and callback payload helpers.

Callback payloads use a compact ``action:token[:extra]`` scheme.
"""

from __future__ import annotations

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# Callback action constants.
ACT_START = "dl"
ACT_CANCEL = "cxl"
ACT_MUX_MP4 = "mmp4"
ACT_MUX_MKV = "mmkv"
ACT_AUTO = "auto"
ACT_DECRYPT = "dcrp"
ACT_LIVE = "live"
ACT_SUBS = "subs"
ACT_NOOP = "noop"


def download_menu(token: str) -> InlineKeyboardMarkup:
    """Menu shown after user submits a URL."""

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "\U0001f4e5 Download (raw)",
                    callback_data=f"{ACT_START}:{token}",
                ),
                InlineKeyboardButton(
                    "\u2699\ufe0f Auto-select + MP4",
                    callback_data=f"{ACT_AUTO}:{token}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "\U0001f3ac Mux MP4",
                    callback_data=f"{ACT_MUX_MP4}:{token}",
                ),
                InlineKeyboardButton(
                    "\U0001f4c0 Mux MKV",
                    callback_data=f"{ACT_MUX_MKV}:{token}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "\U0001f510 With Decryption",
                    callback_data=f"{ACT_DECRYPT}:{token}",
                ),
                InlineKeyboardButton(
                    "\U0001f4fa Live Record",
                    callback_data=f"{ACT_LIVE}:{token}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "\U0001f4dd Subtitles Only",
                    callback_data=f"{ACT_SUBS}:{token}",
                ),
                InlineKeyboardButton(
                    "\u274c Cancel",
                    callback_data=f"{ACT_CANCEL}:{token}",
                ),
            ],
        ]
    )


def cancel_only(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("\u274c Cancel", callback_data=f"{ACT_CANCEL}:{token}")]]
    )


def parse_callback(data: str) -> tuple[str, list[str]]:
    parts = data.split(":")
    return parts[0], parts[1:]
