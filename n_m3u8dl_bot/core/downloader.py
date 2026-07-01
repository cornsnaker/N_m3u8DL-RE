"""Subprocess wrapper around the N_m3u8DL-RE CLI binary.

Launches the binary with user-supplied flags, parses real-time stdout for
progress information, and reports it back via a callback.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Callable, Coroutine, Optional

log = logging.getLogger("n_m3u8dl_bot.downloader")

ProgressCb = Callable[[float, str], Coroutine]

# Matches percentage patterns like "50.00%" or "100%" in N_m3u8DL-RE output.
_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
# Matches speed patterns like "12.5MB/s" or "100KB/s".
_SPEED_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)/s", re.IGNORECASE)

# All supported N_m3u8DL-RE flags for validation / help text.
ALL_FLAGS: dict[str, str] = {
    "--tmp-dir": "Set temporary file directory",
    "--save-dir": "Set output directory",
    "--save-name": "Set output filename",
    "--save-pattern": "Set output file naming template (vars: <SaveName>, <Id>, <Codecs>, etc.)",
    "--log-file-path": "Set log file path",
    "--base-url": "Set BaseURL",
    "--thread-count": "Set download thread count [default: CPU cores]",
    "--download-retry-count": "Retry count per segment on error [default: 3]",
    "--http-request-timeout": "HTTP request timeout in seconds [default: 100]",
    "--force-ansi-console": "Force ANSI-compatible terminal",
    "--no-ansi-color": "Remove ANSI colors",
    "--auto-select": "Auto-select best tracks of all types",
    "--skip-merge": "Skip segment merge",
    "--skip-download": "Skip download",
    "--check-segments-count": "Check downloaded vs expected segment count [default: True]",
    "--binary-merge": "Binary merge",
    "--use-ffmpeg-concat-demuxer": "Use ffmpeg concat demuxer instead of concat protocol",
    "--del-after-done": "Delete temp files when done [default: True]",
    "--no-date-info": "Don't write date info during muxing",
    "--no-log": "Disable log file output",
    "--write-meta-json": "Write meta json after parsing [default: True]",
    "--append-url-params": "Append input URL params to segments",
    "-mt|--concurrent-download": "Concurrently download audio, video and subtitles",
    "-H|--header": 'Set custom headers, e.g. -H "Cookie: foo" -H "User-Agent: bar"',
    "--sub-only": "Select only subtitle tracks",
    "--sub-format": "Subtitle output format: SRT | VTT [default: SRT]",
    "--auto-subtitle-fix": "Automatically fix subtitles [default: True]",
    "--ffmpeg-binary-path": "Full path to ffmpeg binary",
    "--log-level": "Log level: DEBUG | ERROR | INFO | OFF | WARN [default: INFO]",
    "--ui-language": "UI language: en-US | zh-CN | zh-TW",
    "--urlprocessor-args": "Arguments passed to URL Processors",
    "--key": "Decryption key(s): --key KID1:KEY1 --key KID2:KEY2",
    "--key-text-file": "Key file for KID-based key lookup",
    "--decryption-engine": "Decryption engine: FFMPEG | MP4DECRYPT | SHAKA_PACKAGER [default: MP4DECRYPT]",
    "--decryption-binary-path": "Full path to mp4decrypt/shaka-packager binary",
    "--mp4-real-time-decryption": "Decrypt MP4 segments in real time",
    "-R|--max-speed": "Speed limit, e.g. 15M 100K",
    "-M|--mux-after-done": "Mux streams after download (format=mp4:muxer=ffmpeg:...)",
    "--custom-hls-method": "HLS encryption method (AES_128|CENC|CHACHA20|NONE|...)",
    "--custom-hls-key": "HLS decryption key (file, HEX or Base64)",
    "--custom-hls-iv": "HLS decryption IV (file, HEX or Base64)",
    "--use-system-proxy": "Use system default proxy [default: True]",
    "--custom-proxy": "Set proxy URL, e.g. http://127.0.0.1:8888",
    "--custom-range": "Download only part of segments, e.g. 0-10, 05:00-20:00",
    "--task-start-at": "Delay task start until this time (yyyyMMddHHmmss)",
    "--live-perform-as-vod": "Download live streams as VOD",
    "--live-real-time-merge": "Real-time merge when recording live",
    "--live-keep-segments": "Keep segments during live recording [default: True]",
    "--live-pipe-mux": "Real-time mux to TS via pipeline + ffmpeg",
    "--live-fix-vtt-by-audio": "Fix VTT subtitles using audio start time",
    "--live-record-limit": "Live recording time limit (HH:mm:ss)",
    "--live-wait-time": "Live playlist refresh interval (seconds)",
    "--live-take-count": "Initial segment count for live recording [default: 16]",
    "--mux-import": "Import external media during mux (path=P:lang=L:name=N)",
    "-sv|--select-video": "Select video streams by regex (res=REGEX:codecs=REGEX:for=best)",
    "-sa|--select-audio": "Select audio streams by regex (lang=REGEX:for=best)",
    "-ss|--select-subtitle": "Select subtitle streams by regex",
    "-dv|--drop-video": "Drop video streams by regex",
    "-da|--drop-audio": "Drop audio streams by regex",
    "-ds|--drop-subtitle": "Drop subtitle streams by regex",
    "--ad-keyword": "URL keyword regex for ad segments",
    "--disable-update-check": "Disable version update check",
    "--allow-hls-multi-ext-map": "Allow multiple #EXT-X-MAP in HLS (experimental)",
}

# Flags that are boolean (no value argument).
BOOLEAN_FLAGS: frozenset[str] = frozenset({
    "--force-ansi-console",
    "--no-ansi-color",
    "--auto-select",
    "--skip-merge",
    "--skip-download",
    "--binary-merge",
    "--use-ffmpeg-concat-demuxer",
    "--no-date-info",
    "--no-log",
    "--append-url-params",
    "-mt", "--concurrent-download",
    "--sub-only",
    "--mp4-real-time-decryption",
    "--live-perform-as-vod",
    "--live-real-time-merge",
    "--live-pipe-mux",
    "--live-fix-vtt-by-audio",
    "--disable-update-check",
    "--allow-hls-multi-ext-map",
})


def build_command(
    binary: str,
    url: str,
    flags: list[str],
    *,
    save_dir: str,
) -> list[str]:
    """Build the full CLI command list for N_m3u8DL-RE."""

    cmd = [binary, url, "--save-dir", save_dir, "--no-ansi-color"]

    # Inject --del-after-done and --auto-select if not explicitly provided.
    flag_names = {f.split("=")[0].lower() for f in flags}
    if "--del-after-done" not in flag_names:
        cmd.extend(["--del-after-done", "true"])
    if "--auto-select" not in flag_names:
        cmd.append("--auto-select")

    cmd.extend(flags)
    return cmd


async def run_download(
    binary: str,
    url: str,
    flags: list[str],
    *,
    save_dir: Path,
    progress_cb: Optional[ProgressCb] = None,
    cancel_event: Optional[asyncio.Event] = None,
) -> tuple[asyncio.subprocess.Process, int]:
    """Run N_m3u8DL-RE and stream progress to ``progress_cb``.

    Returns ``(process, returncode)``.
    """

    save_dir.mkdir(parents=True, exist_ok=True)
    cmd = build_command(binary, url, flags, save_dir=str(save_dir))
    log.info("Running: %s", " ".join(cmd))

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(save_dir),
    )

    last_pct = 0.0
    full_output: list[str] = []

    async def _read_output() -> None:
        nonlocal last_pct
        assert proc.stdout is not None
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip()
            full_output.append(line)
            log.debug("N_m3u8DL-RE: %s", line)

            if progress_cb is not None:
                pct_match = _PCT_RE.search(line)
                if pct_match:
                    pct = float(pct_match.group(1))
                    if pct > last_pct:
                        last_pct = pct
                        await progress_cb(pct, line)

    async def _watch_cancel() -> None:
        if cancel_event is None:
            return
        await cancel_event.wait()
        try:
            proc.kill()
        except ProcessLookupError:
            pass

    read_task = asyncio.create_task(_read_output())
    cancel_task = asyncio.create_task(_watch_cancel()) if cancel_event else None

    await proc.wait()
    read_task.cancel()
    if cancel_task is not None:
        cancel_task.cancel()

    try:
        await read_task
    except asyncio.CancelledError:
        pass

    assert proc.returncode is not None
    if proc.returncode != 0:
        log.warning("N_m3u8DL-RE exited %d. Last output:\n%s", proc.returncode, "\n".join(full_output[-20:]))

    return proc, proc.returncode
