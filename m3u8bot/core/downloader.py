"""N_m3u8DL-RE process wrapper.

Spawns the CLI binary, streams stdout/stderr and parses progress lines to
update the task's live progress counters.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from ..config import Config
from .task import Task, TaskProgress, TaskState

log = logging.getLogger("m3u8bot.downloader")

# Progress patterns emitted by N_m3u8DL-RE on stdout.
# Example lines:
#   Vid  0% [                    ]  0.00 KBps  eta --:--:--
#   Vid 54% [■■■■■■■■■■          ]  12.3 MBps  eta 00:00:14
_PROGRESS_RE = re.compile(
    r"(?P<type>Vid|Aud|Sub|Mix)\s+"
    r"(?P<pct>[\d.]+)%\s+"
    r"\[.*?\]\s+"
    r"(?P<speed>[\d.]+\s*\w+(?:ps|/s)?)\s+"
    r"eta\s+(?P<eta>\S+)",
    re.IGNORECASE,
)

# "All works done" or similar final lines.
_DONE_RE = re.compile(r"(All works done|Done|mixed|muxed)", re.IGNORECASE)

# Error patterns.
_ERROR_RE = re.compile(r"(ERROR|Exception|Failed|异常|错误)", re.IGNORECASE)


def build_command(
    config: Config,
    task: Task,
) -> list[str]:
    """Assemble the full CLI command list for N_m3u8DL-RE."""

    cmd: list[str] = [config.n_m3u8dl_re_bin, task.url]

    # Always set output and tmp dirs.
    output_dir = config.download_dir / task.token
    output_dir.mkdir(parents=True, exist_ok=True)
    task.output_dir = output_dir

    cmd.extend(["--save-dir", str(output_dir)])
    cmd.extend(["--tmp-dir", str(config.tmp_dir / task.token)])
    cmd.extend(["--no-log"])
    cmd.extend(["--disable-update-check"])
    cmd.extend(["--force-ansi-console"])

    # Set binary paths if user has not overridden them.
    has = {a.split("=")[0].lstrip("-") for a in task.cli_args}

    if "ffmpeg-binary-path" not in has:
        cmd.extend(["--ffmpeg-binary-path", config.ffmpeg_bin])

    if "decryption-binary-path" not in has:
        cmd.extend(["--decryption-binary-path", config.mp4decrypt_bin])

    if "thread-count" not in has:
        cmd.extend(["--thread-count", str(config.thread_count)])

    # Append user-supplied flags verbatim.
    cmd.extend(task.cli_args)

    return cmd


def _parse_progress(line: str, progress: TaskProgress) -> None:
    """Update progress counters from a single output line."""

    m = _PROGRESS_RE.search(line)
    if m:
        progress.stage = {
            "vid": "Downloading Video",
            "aud": "Downloading Audio",
            "sub": "Downloading Subtitles",
            "mix": "Muxing",
        }.get(m.group("type").lower(), "Downloading")
        try:
            progress.percent = float(m.group("pct"))
        except ValueError:
            pass
        progress.speed = m.group("speed")
        progress.eta = m.group("eta")
        return

    if _DONE_RE.search(line):
        progress.stage = "Done"
        progress.percent = 100.0


async def run_download(
    config: Config,
    task: Task,
    on_progress: Optional[asyncio.Event] = None,
) -> None:
    """Execute N_m3u8DL-RE and stream progress updates into ``task.progress``.

    Parameters
    ----------
    on_progress:
        If provided, the event is set each time the progress is updated so
        the UI layer can react immediately.
    """

    cmd = build_command(config, task)
    log.info("Spawning: %s", " ".join(cmd))

    task.state = TaskState.RUNNING
    task.progress = TaskProgress(stage="Starting download")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=None,
        )
    except FileNotFoundError:
        task.state = TaskState.FAILED
        task.error = (
            f"N_m3u8DL-RE binary not found at '{config.n_m3u8dl_re_bin}'. "
            "Set N_M3U8DL_RE_BIN in .env or install it."
        )
        return
    except OSError as exc:
        task.state = TaskState.FAILED
        task.error = f"Failed to spawn N_m3u8DL-RE: {exc}"
        return

    assert proc.stdout is not None
    last_error = ""
    try:
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            log.debug("[%s] %s", task.token, line)
            _parse_progress(line, task.progress)
            if _ERROR_RE.search(line):
                last_error = line
            if on_progress:
                on_progress.set()
    except asyncio.CancelledError:
        proc.kill()
        task.state = TaskState.CANCELLED
        return

    rc = await proc.wait()
    if rc != 0 and task.state != TaskState.CANCELLED:
        task.state = TaskState.FAILED
        task.error = last_error or f"N_m3u8DL-RE exited with code {rc}"
        return

    # Collect output files.
    if task.output_dir and task.output_dir.exists():
        task.output_files = sorted(
            p
            for p in task.output_dir.rglob("*")
            if p.is_file() and not p.name.endswith(".json") and not p.name.startswith(".")
        )

    if not task.output_files:
        task.state = TaskState.FAILED
        task.error = "Download completed but no output files were found."
        return

    task.progress.stage = "Done"
    task.progress.percent = 100.0
