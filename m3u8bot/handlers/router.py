"""Wires Pyrogram update handlers to the :class:`TaskManager`.

Commands
--------
/start, /help    -- welcome card with usage guide
/dl <url> [flags] -- download HLS/DASH/MSS stream
/live <url> [flags] -- record a live stream
/flags           -- show all N_m3u8DL-RE flags
/cancel          -- cancel the active task
/status          -- show current task status

Users can also just paste a URL directly (no command prefix) to start
an interactive download menu.
"""

from __future__ import annotations

import asyncio
import logging
import shlex
from typing import Optional

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery, Message

from ..config import Config
from ..core.manager import TaskManager
from ..core.task import Task, TaskState
from ..ui import fmt as md
from ..ui import keyboards as kb
from ..ui import progress as pg

log = logging.getLogger("m3u8bot.router")

_URL_PREFIXES = ("http://", "https://", "file://")

_HELP_TEXT = pg.render_status(
    "N_m3u8DL-RE Bot",
    [
        "Cross-platform HLS / DASH / MSS downloader bot.",
        "",
        "Commands:",
        "/dl <url> [flags] - Download stream",
        "/live <url> [flags] - Record live stream",
        "/flags - Show all available flags",
        "/cancel - Cancel active task",
        "/status - Check task status",
        "",
        "Or just paste a URL to get a download menu.",
        "",
        "Examples:",
        '/dl https://example.com/stream.m3u8 --auto-select -M format=mp4',
        '/dl https://example.com/enc.mpd --key KID:KEY',
        '/live https://example.com/live.m3u8 --live-record-limit 01:00:00',
    ],
    emoji="\U0001f3ac",
)

# All N_m3u8DL-RE flags for the /flags command.
_FLAGS_PAGE_1 = """<b>N_m3u8DL-RE Flags (1/3) -- General</b>

<code>--save-name NAME</code> - Set output filename
<code>--save-dir DIR</code> - Set output directory
<code>--save-pattern TPL</code> - Naming template (&lt;SaveName&gt;, &lt;Resolution&gt;, etc.)
<code>--tmp-dir DIR</code> - Temp directory
<code>--base-url URL</code> - Set BaseURL
<code>--thread-count N</code> - Download threads [default: CPU cores]
<code>--download-retry-count N</code> - Retries per segment [default: 3]
<code>--http-request-timeout SEC</code> - HTTP timeout [default: 100]
<code>--auto-select</code> - Auto-pick best tracks
<code>--skip-merge</code> - Skip segment merge
<code>--skip-download</code> - Skip download (parse only)
<code>--binary-merge</code> - Binary merge mode
<code>--use-ffmpeg-concat-demuxer</code> - Use concat demuxer
<code>--del-after-done</code> - Delete temp files [default: True]
<code>--no-date-info</code> - No date in mux
<code>--write-meta-json</code> - Output meta JSON [default: True]
<code>--append-url-params</code> - Append URL params to segments
<code>-mt / --concurrent-download</code> - Parallel A/V/S download
<code>-H "Header: value"</code> - Custom HTTP header(s)
<code>-R / --max-speed 15M</code> - Speed limit (Mbps/Kbps)
<code>--ad-keyword REGEX</code> - Filter ad segments
<code>--custom-proxy URL</code> - HTTP proxy
<code>--custom-range RANGE</code> - Partial download (e.g. 0-10, 05:00-20:00)
<code>--task-start-at yyyyMMddHHmmss</code> - Delayed start"""

_FLAGS_PAGE_2 = """<b>N_m3u8DL-RE Flags (2/3) -- Decryption &amp; Muxing</b>

<code>--key KID:KEY</code> - Decryption key (repeatable)
<code>--key-text-file FILE</code> - Key file (KID:KEY lines)
<code>--decryption-engine ENGINE</code> - MP4DECRYPT | FFMPEG | SHAKA_PACKAGER
<code>--decryption-binary-path PATH</code> - Path to decryption tool
<code>--mp4-real-time-decryption</code> - Decrypt segments in real-time
<code>--custom-hls-method METHOD</code> - AES_128|AES_128_ECB|CENC|CHACHA20|NONE|SAMPLE_AES|SAMPLE_AES_CTR
<code>--custom-hls-key HEX|BASE64|FILE</code> - HLS decryption key
<code>--custom-hls-iv HEX|BASE64|FILE</code> - HLS decryption IV

<code>-M / --mux-after-done OPTIONS</code> - Auto-mux when done
  format=mp4|mkv  muxer=ffmpeg|mkvmerge  skip_sub=true|false  keep=true|false
<code>--mux-import OPTIONS</code> - Import external file during mux
  path=FILE:lang=CODE:name=NAME
<code>--ffmpeg-binary-path PATH</code> - ffmpeg path"""

_FLAGS_PAGE_3 = """<b>N_m3u8DL-RE Flags (3/3) -- Streams &amp; Live</b>

<code>-sv / --select-video OPTIONS</code> - Select video streams
<code>-sa / --select-audio OPTIONS</code> - Select audio streams
<code>-ss / --select-subtitle OPTIONS</code> - Select subtitle streams
<code>-dv / --drop-video OPTIONS</code> - Drop video streams
<code>-da / --drop-audio OPTIONS</code> - Drop audio streams
<code>-ds / --drop-subtitle OPTIONS</code> - Drop subtitle streams

Stream filter format: id=REGEX:lang=REGEX:name=REGEX:codecs=REGEX:res=REGEX
  :frame=REGEX:for=best|worst|all|bestN

<code>--sub-only</code> - Download subtitles only
<code>--sub-format SRT|VTT</code> - Subtitle format [default: SRT]
<code>--auto-subtitle-fix</code> - Auto-fix subtitles [default: True]

<code>--live-perform-as-vod</code> - Download live as VOD
<code>--live-real-time-merge</code> - Merge live segments in real-time
<code>--live-keep-segments</code> - Keep segments during live merge
<code>--live-pipe-mux</code> - Pipe mux via ffmpeg to TS
<code>--live-fix-vtt-by-audio</code> - Fix VTT timing via audio
<code>--live-record-limit HH:mm:ss</code> - Recording duration limit
<code>--live-wait-time SEC</code> - Playlist refresh interval
<code>--live-take-count N</code> - Initial segment count [default: 16]"""


def _parse_dl_command(text: str) -> tuple[Optional[str], list[str]]:
    """Extract URL and CLI flags from a /dl or /live command.

    Returns (url, cli_args) or (None, []) if parsing fails.
    """

    parts = text.strip().split(None, 1)
    if len(parts) < 2:
        return None, []

    remainder = parts[1]

    # Use shlex to properly handle quoted strings.
    try:
        tokens = shlex.split(remainder)
    except ValueError:
        tokens = remainder.split()

    if not tokens:
        return None, []

    url = tokens[0]
    cli_args = tokens[1:]
    return url, cli_args


def _is_url(text: str) -> bool:
    return any(text.strip().startswith(p) for p in _URL_PREFIXES)


def register(client: Client, manager: TaskManager, config: Config) -> None:
    """Attach all handlers to ``client``."""

    def _authorized(user_id: Optional[int]) -> bool:
        return config.is_user_allowed(user_id)

    @client.on_message(filters.command(["start", "help"]) & filters.private)
    async def _on_start(_: Client, message: Message) -> None:
        if not _authorized(message.from_user.id if message.from_user else None):
            await message.reply_text(
                pg.render_error("You are not authorized to use this bot."),
                parse_mode=ParseMode.HTML,
            )
            return
        await message.reply_text(_HELP_TEXT, parse_mode=ParseMode.HTML)

    @client.on_message(filters.command("flags") & filters.private)
    async def _on_flags(_: Client, message: Message) -> None:
        if not _authorized(message.from_user.id if message.from_user else None):
            return
        await message.reply_text(_FLAGS_PAGE_1, parse_mode=ParseMode.HTML)
        await message.reply_text(_FLAGS_PAGE_2, parse_mode=ParseMode.HTML)
        await message.reply_text(_FLAGS_PAGE_3, parse_mode=ParseMode.HTML)

    @client.on_message(filters.command("dl") & filters.private)
    async def _on_dl(_: Client, message: Message) -> None:
        if not _authorized(message.from_user.id if message.from_user else None):
            return
        url, cli_args = _parse_dl_command(message.text or "")
        if not url:
            await message.reply_text(
                pg.render_error("Usage: /dl <url> [flags]", "No URL provided."),
                parse_mode=ParseMode.HTML,
            )
            return
        await _start_download(message, url, cli_args)

    @client.on_message(filters.command("live") & filters.private)
    async def _on_live(_: Client, message: Message) -> None:
        if not _authorized(message.from_user.id if message.from_user else None):
            return
        url, cli_args = _parse_dl_command(message.text or "")
        if not url:
            await message.reply_text(
                pg.render_error("Usage: /live <url> [flags]", "No URL provided."),
                parse_mode=ParseMode.HTML,
            )
            return
        # Inject live-friendly defaults if the user hasn't set them.
        arg_set = set(cli_args)
        if "--live-real-time-merge" not in arg_set:
            cli_args.append("--live-real-time-merge")
        await _start_download(message, url, cli_args)

    @client.on_message(filters.command("cancel") & filters.private)
    async def _on_cancel(_: Client, message: Message) -> None:
        if not _authorized(message.from_user.id if message.from_user else None):
            return
        # Cancel most recent running task for this user.
        uid = message.from_user.id if message.from_user else 0
        cancelled = False
        for task in reversed(list(manager._tasks.values())):
            if task.user_id == uid and task.state in (TaskState.PENDING, TaskState.RUNNING):
                manager.cancel(task.token)
                cancelled = True
                await message.reply_text(
                    pg.render_status("Cancelled", [f"Task {task.token} cancelled."], emoji="\u274c"),
                    parse_mode=ParseMode.HTML,
                )
                break
        if not cancelled:
            await message.reply_text(
                pg.render_status("No Active Task", ["Nothing to cancel."], emoji="\u2139\ufe0f"),
                parse_mode=ParseMode.HTML,
            )

    @client.on_message(filters.command("status") & filters.private)
    async def _on_status(_: Client, message: Message) -> None:
        if not _authorized(message.from_user.id if message.from_user else None):
            return
        uid = message.from_user.id if message.from_user else 0
        active = [
            t for t in manager._tasks.values()
            if t.user_id == uid and t.state in (TaskState.PENDING, TaskState.RUNNING, TaskState.UPLOADING)
        ]
        if not active:
            await message.reply_text(
                pg.render_status("No Active Tasks", emoji="\u2139\ufe0f"),
                parse_mode=ParseMode.HTML,
            )
            return
        for task in active:
            p = task.progress
            await message.reply_text(
                pg.render_progress(p.stage, percent=p.percent, speed=p.speed, eta=p.eta),
                parse_mode=ParseMode.HTML,
            )

    # Bare URL messages (no command prefix) -- show the interactive menu.
    @client.on_message(filters.text & filters.private & ~filters.command(
        ["start", "help", "dl", "live", "flags", "cancel", "status"]
    ))
    async def _on_text(_: Client, message: Message) -> None:
        if not _authorized(message.from_user.id if message.from_user else None):
            return
        text = (message.text or "").strip()
        if not _is_url(text):
            await message.reply_text(
                pg.render_error(
                    "Not a valid URL",
                    "Send an HLS/DASH/MSS URL or use /dl <url> [flags].",
                ),
                parse_mode=ParseMode.HTML,
            )
            return
        task = manager.create_task(
            chat_id=message.chat.id,
            user_id=message.from_user.id if message.from_user else 0,
            trigger_message_id=message.id,
            url=text,
        )
        await message.reply_text(
            pg.render_status(
                "URL Received",
                [f"URL: {text[:80]}{'...' if len(text) > 80 else ''}", "Choose a download mode:"],
                emoji="\U0001f517",
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=kb.download_menu(task.token),
        )

    # Callback query handler.
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
            await query.answer("Cancelling...")
            if query.message:
                await query.message.edit_text(
                    pg.render_status("Cancelled", emoji="\u274c"),
                    parse_mode=ParseMode.HTML,
                )
            return

        if task is None:
            await query.answer("Task expired. Send the URL again.", show_alert=True)
            return

        extra_args: list[str] = []

        if action == kb.ACT_START:
            pass  # raw download, no extra args

        elif action == kb.ACT_AUTO:
            extra_args = ["--auto-select", "-M", "format=mp4"]

        elif action == kb.ACT_MUX_MP4:
            extra_args = ["--auto-select", "-M", "format=mp4", "-mt"]

        elif action == kb.ACT_MUX_MKV:
            extra_args = ["--auto-select", "-M", "format=mkv:muxer=mkvmerge", "-mt"]

        elif action == kb.ACT_DECRYPT:
            await query.answer()
            if query.message:
                await query.message.edit_text(
                    pg.render_status(
                        "Decryption Mode",
                        [
                            "Send the download command with decryption keys:",
                            "",
                            f"/dl {task.url} --key KID:KEY",
                            "",
                            "Or for HLS AES-128:",
                            f"/dl {task.url} --custom-hls-key YOUR_HEX_KEY",
                            "",
                            "Engines: --decryption-engine MP4DECRYPT|FFMPEG|SHAKA_PACKAGER",
                        ],
                        emoji="\U0001f510",
                    ),
                    parse_mode=ParseMode.HTML,
                )
            return

        elif action == kb.ACT_LIVE:
            extra_args = ["--live-real-time-merge", "--auto-select"]

        elif action == kb.ACT_SUBS:
            extra_args = ["--sub-only", "--auto-select"]

        else:
            await query.answer()
            return

        task.cli_args.extend(extra_args)

        if not manager.launch(task):
            await query.answer("Cannot start: at capacity or already running.", show_alert=True)
            return

        await query.answer("Starting download...")

        if query.message:
            await query.message.edit_text(
                pg.render_progress("Starting download..."),
                parse_mode=ParseMode.HTML,
                reply_markup=kb.cancel_only(task.token),
            )
            task.status_message_id = query.message.id

        # Start the progress updater.
        asyncio.create_task(
            _progress_loop(task, query.message.chat.id if query.message else task.chat_id),
            name=f"progress-{task.token}",
        )

    async def _start_download(message: Message, url: str, cli_args: list[str]) -> None:
        """Create task and immediately start downloading (CLI mode)."""

        if manager.active_count() >= config.max_concurrent_tasks:
            await message.reply_text(
                pg.render_error(
                    "Too many active tasks",
                    f"Max {config.max_concurrent_tasks} concurrent downloads.",
                ),
                parse_mode=ParseMode.HTML,
            )
            return

        task = manager.create_task(
            chat_id=message.chat.id,
            user_id=message.from_user.id if message.from_user else 0,
            trigger_message_id=message.id,
            url=url,
            cli_args=cli_args,
        )

        status_msg = await message.reply_text(
            pg.render_progress("Starting download..."),
            parse_mode=ParseMode.HTML,
            reply_markup=kb.cancel_only(task.token),
        )
        task.status_message_id = status_msg.id

        manager.launch(task)
        asyncio.create_task(
            _progress_loop(task, message.chat.id),
            name=f"progress-{task.token}",
        )

    async def _progress_loop(task: Task, chat_id: int) -> None:
        """Periodically update the status message with download progress."""

        evt = manager.get_progress_event(task.token)
        last_text = ""

        while task.state in (TaskState.PENDING, TaskState.RUNNING):
            if evt:
                try:
                    await asyncio.wait_for(
                        _wait_event(evt), timeout=config.progress_update_interval
                    )
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(config.progress_update_interval)

            p = task.progress
            text = pg.render_progress(p.stage, percent=p.percent, speed=p.speed, eta=p.eta)
            if text != last_text and task.status_message_id:
                try:
                    await client.edit_message_text(
                        chat_id, task.status_message_id, text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=kb.cancel_only(task.token),
                    )
                    last_text = text
                except Exception:
                    pass

        # Final state.
        if task.state == TaskState.FAILED:
            if task.status_message_id:
                try:
                    await client.edit_message_text(
                        chat_id, task.status_message_id,
                        pg.render_error("Download failed", task.error),
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    pass
            return

        if task.state == TaskState.CANCELLED:
            return

        # Upload output files.
        task.state = TaskState.UPLOADING
        await _upload_files(task, chat_id)
        task.state = TaskState.DONE

        if task.status_message_id:
            file_list = "\n".join(f.name for f in task.output_files)
            try:
                await client.edit_message_text(
                    chat_id, task.status_message_id,
                    pg.render_status(
                        "Complete",
                        [f"{len(task.output_files)} file(s) uploaded.", file_list],
                        emoji="\u2705",
                    ),
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass

        manager.cleanup_task(task.token)

    async def _upload_files(task: Task, chat_id: int) -> None:
        """Upload each output file to Telegram."""

        total = len(task.output_files)
        for idx, filepath in enumerate(task.output_files, 1):
            if task.state == TaskState.CANCELLED:
                return

            if task.status_message_id:
                try:
                    await client.edit_message_text(
                        chat_id, task.status_message_id,
                        pg.render_upload(filepath.name, idx, total),
                        parse_mode=ParseMode.HTML,
                        reply_markup=kb.cancel_only(task.token),
                    )
                except Exception:
                    pass

            try:
                size = filepath.stat().st_size
                ext = filepath.suffix.lower()

                if ext in (".mp4", ".mkv", ".ts", ".webm", ".avi", ".mov", ".flv"):
                    await client.send_video(
                        chat_id, str(filepath),
                        caption=f"<code>{md.escape(filepath.name)}</code>",
                        parse_mode=ParseMode.HTML,
                        supports_streaming=True,
                    )
                elif ext in (".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wav"):
                    await client.send_audio(
                        chat_id, str(filepath),
                        caption=f"<code>{md.escape(filepath.name)}</code>",
                        parse_mode=ParseMode.HTML,
                    )
                elif ext in (".srt", ".vtt", ".ass", ".ssa", ".ttml"):
                    await client.send_document(
                        chat_id, str(filepath),
                        caption=f"<code>{md.escape(filepath.name)}</code>",
                        parse_mode=ParseMode.HTML,
                    )
                else:
                    await client.send_document(
                        chat_id, str(filepath),
                        caption=f"<code>{md.escape(filepath.name)}</code> ({_human_size(size)})",
                        parse_mode=ParseMode.HTML,
                    )
            except Exception as exc:
                log.warning("Upload failed for %s: %s", filepath, exc)
                await client.send_message(
                    chat_id,
                    pg.render_error(f"Failed to upload {filepath.name}", str(exc)),
                    parse_mode=ParseMode.HTML,
                )

    async def _wait_event(evt: asyncio.Event) -> None:
        await evt.wait()
        evt.clear()


def _human_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024.0:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} PB"
