"""Telegram command and callback routing for the N_m3u8DL-RE bot.

Commands:
    /start, /help  - Show welcome card with usage instructions.
    /dl <url> [flags] - Download a DASH/HLS/MSS stream.
    /flags         - List all supported N_m3u8DL-RE flags.
    /cancel        - Cancel the current running task.
    /status        - Show status of the current task.
"""

from __future__ import annotations

import shlex

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery, Message

from ..config import Config
from ..core import downloader
from ..core.manager import TaskManager
from ..core.status import StatusReporter
from ..ui import fmt as md
from ..ui import keyboards as kb
from ..ui import progress as pg

_START_CARD = pg.render_status(
    "N_m3u8DL-RE Bot",
    [
        "DASH / HLS / MSS stream downloader.",
        "",
        "Usage:",
        "/dl <url> [flags]  - Download a stream",
        "/flags  - List all supported flags",
        "/cancel - Cancel running task",
        "/status - Current task status",
        "",
        "Example:",
        '/dl https://example.com/master.m3u8 -sv best -sa best -M format=mp4',
        '/dl https://example.com/stream.mpd --thread-count 16',
        '/dl <url> -H "Cookie: foo" -M format=mkv',
    ],
    emoji="\U0001f4e1",
)


def _build_flags_text() -> str:
    """Build the /flags help text from the downloader's flag registry."""

    lines = [md.bold("\U0001f527 Supported N_m3u8DL-RE Flags")]
    for flag, desc in downloader.ALL_FLAGS.items():
        lines.append(f"{md.code(flag)} - {md.escape(desc)}")
    # Split into chunks if too long for one message (Telegram 4096 char limit).
    return md.quote_block(lines)


def _split_long_text(text: str, limit: int = 4000) -> list[str]:
    """Split a long HTML text into chunks that fit Telegram's message limit."""

    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    lines = text.split("\n")
    current: list[str] = []
    current_len = 0
    in_block = False

    for line in lines:
        if "<blockquote>" in line:
            in_block = True
        line_len = len(line) + 1

        if current_len + line_len > limit and current:
            joined = "\n".join(current)
            if in_block and "</blockquote>" not in joined:
                joined += "</blockquote>"
            chunks.append(joined)
            current = []
            current_len = 0
            if in_block:
                current.append("<blockquote>")
                current_len = len("<blockquote>") + 1

        current.append(line)
        current_len += line_len

        if "</blockquote>" in line:
            in_block = False

    if current:
        chunks.append("\n".join(current))
    return chunks


def _parse_dl_args(text: str) -> tuple[str, list[str]]:
    """Parse ``/dl <url> [flags...]`` into (url, [flag_tokens]).

    Returns ("", []) if the command is malformed.
    """

    # Strip /dl prefix.
    body = text.strip()
    if body.lower().startswith("/dl"):
        body = body[3:].strip()
        # Handle @botname suffix.
        if body.startswith("@"):
            idx = body.find(" ")
            body = body[idx:].strip() if idx != -1 else ""

    if not body:
        return "", []

    try:
        tokens = shlex.split(body)
    except ValueError:
        tokens = body.split()

    if not tokens:
        return "", []

    url = tokens[0]
    flags = tokens[1:]
    return url, flags


def register(client: Client, manager: TaskManager, config: Config) -> None:
    """Attach all handlers to ``client``."""

    def _authorized(user_id: int | None) -> bool:
        return config.is_user_allowed(user_id)

    @client.on_message(filters.command(["start", "help"]) & filters.private)
    async def _on_start(_: Client, message: Message) -> None:
        if not _authorized(message.from_user.id if message.from_user else None):
            await message.reply_text(
                pg.render_error("You are not authorized to use this bot."),
                parse_mode=ParseMode.HTML,
            )
            return
        await message.reply_text(_START_CARD, parse_mode=ParseMode.HTML)

    @client.on_message(filters.command("flags") & filters.private)
    async def _on_flags(_: Client, message: Message) -> None:
        if not _authorized(message.from_user.id if message.from_user else None):
            return
        text = _build_flags_text()
        chunks = _split_long_text(text)
        for chunk in chunks:
            await message.reply_text(chunk, parse_mode=ParseMode.HTML)

    @client.on_message(filters.command("dl") & filters.private)
    async def _on_dl(_: Client, message: Message) -> None:
        if not _authorized(message.from_user.id if message.from_user else None):
            return

        url, flags = _parse_dl_args(message.text or "")
        if not url:
            await message.reply_text(
                pg.render_error(
                    "Missing URL",
                    'Usage: /dl <url> [flags]\nExample: /dl https://example.com/master.m3u8 -sv best',
                ),
                parse_mode=ParseMode.HTML,
            )
            return

        task = manager.create_task(
            chat_id=message.chat.id,
            user_id=message.from_user.id if message.from_user else 0,
            trigger_message_id=message.id,
            url=url,
            flags=flags,
        )

        flag_display = " ".join(flags) if flags else "(default settings)"
        await message.reply_text(
            pg.render_status(
                "Download Queued",
                [
                    f"URL: {url[:80]}{'...' if len(url) > 80 else ''}",
                    f"Flags: {flag_display}",
                    "",
                    "Tap Start to begin downloading.",
                ],
                emoji="\U0001f4e1",
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=kb.confirm_menu(task.token),
        )

    @client.on_message(filters.command("cancel") & filters.private)
    async def _on_cancel(_: Client, message: Message) -> None:
        if not _authorized(message.from_user.id if message.from_user else None):
            return
        # Cancel the most recent non-terminal task for this user.
        user_id = message.from_user.id if message.from_user else 0
        cancelled = False
        for task in reversed(list(manager._tasks.values())):
            if task.user_id == user_id and task.state.value in (
                "pending", "queued", "downloading", "uploading"
            ):
                manager.cancel(task.token)
                cancelled = True
                await message.reply_text(
                    pg.render_status("Cancelling", [f"Task {task.token}"], emoji="\U0001f6d1"),
                    parse_mode=ParseMode.HTML,
                )
                break
        if not cancelled:
            await message.reply_text(
                pg.render_status("No Active Task", ["Nothing to cancel."], emoji="\U0001f937"),
                parse_mode=ParseMode.HTML,
            )

    @client.on_message(filters.command("status") & filters.private)
    async def _on_status(_: Client, message: Message) -> None:
        if not _authorized(message.from_user.id if message.from_user else None):
            return
        user_id = message.from_user.id if message.from_user else 0
        active = [
            t
            for t in manager._tasks.values()
            if t.user_id == user_id
            and t.state.value in ("pending", "queued", "downloading", "uploading")
        ]
        if not active:
            await message.reply_text(
                pg.render_status("No Active Tasks", ["All clear."], emoji="\u2705"),
                parse_mode=ParseMode.HTML,
            )
            return
        lines: list[str] = []
        for t in active:
            lines.append(f"[{t.token}] {t.state.value} - {t.url[:50]}")
        await message.reply_text(
            pg.render_status("Active Tasks", lines, emoji="\U0001f4cb"),
            parse_mode=ParseMode.HTML,
        )

    @client.on_message(filters.text & filters.private & ~filters.command(
        ["start", "help", "dl", "flags", "cancel", "status"]
    ))
    async def _on_text(_: Client, message: Message) -> None:
        """Treat bare URLs (no /dl prefix) as download requests."""

        if not _authorized(message.from_user.id if message.from_user else None):
            return
        text = (message.text or "").strip()
        if not text.startswith(("http://", "https://")):
            return

        task = manager.create_task(
            chat_id=message.chat.id,
            user_id=message.from_user.id if message.from_user else 0,
            trigger_message_id=message.id,
            url=text,
            flags=[],
        )
        await message.reply_text(
            pg.render_status(
                "Download Queued",
                [
                    f"URL: {text[:80]}{'...' if len(text) > 80 else ''}",
                    "Flags: (default settings)",
                    "",
                    "Tap Start to begin downloading.",
                ],
                emoji="\U0001f4e1",
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=kb.confirm_menu(task.token),
        )

    @client.on_callback_query()
    async def _on_callback(_: Client, query: CallbackQuery) -> None:
        if not _authorized(query.from_user.id if query.from_user else None):
            await query.answer("Not authorized.", show_alert=True)
            return
        action, args = kb.parse_callback(query.data or "")
        token = args[0] if args else ""
        task = manager.get(token)

        if action == kb.ACT_CANCEL:
            manager.cancel(token)
            await query.answer("Cancelling task...")
            return

        if task is None:
            await query.answer("This task has expired. Send the link again.", show_alert=True)
            return

        if action == kb.ACT_START:
            reporter = StatusReporter(
                client, query.message, min_interval=config.progress_update_interval
            )
            manager.attach_reporter(task, reporter)
            if manager.launch(task):
                await query.answer("Starting download...")
            else:
                await query.answer("Task already started.", show_alert=True)
            return

        await query.answer()
