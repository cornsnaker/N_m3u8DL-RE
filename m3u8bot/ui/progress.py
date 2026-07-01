"""Progress display and status card renderers."""

from __future__ import annotations

from typing import Optional

from . import fmt as md

_FILLED = "\u25a0"
_EMPTY = "\u25a1"
_BAR_LEN = 10


def human_size(num_bytes: Optional[float]) -> str:
    if not num_bytes or num_bytes < 0:
        return "0 B"
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if value < 1024.0:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{value:.2f} EB"


def bar(percent: float, length: int = _BAR_LEN) -> str:
    pct = max(0.0, min(100.0, percent))
    filled = int(round((pct / 100.0) * length))
    filled = max(0, min(length, filled))
    return _FILLED * filled + _EMPTY * (length - filled)


def render_progress(
    stage: str,
    percent: float = 0.0,
    speed: str = "",
    eta: str = "",
    extra: str = "",
) -> str:
    """Render a download progress card."""

    lines = [
        md.bold(f"\U0001f504 {md.escape(stage)}"),
        f"Speed: {md.code(speed or '--')} | ETA: {md.code(eta or '--:--:--')}",
        f"[{bar(percent)}] {md.code(f'{percent:.1f}%')}",
    ]
    if extra:
        lines.append(md.escape(extra))
    return md.quote_block(lines)


def render_status(title: str, lines: Optional[list[str]] = None, *, emoji: str = "\u2139\ufe0f") -> str:
    body = [md.bold(f"{emoji} {md.escape(title)}")]
    for line in lines or []:
        body.append(md.escape(line))
    return md.quote_block(body)


def render_error(message: str, detail: Optional[str] = None) -> str:
    lines = [md.bold(f"\u274c {md.escape('Error')}"), md.escape(message)]
    if detail:
        snippet = detail.strip().splitlines()[-1] if detail.strip() else detail
        lines.append(md.code(snippet[:200]))
    return md.quote_block(lines)


def render_upload(filename: str, current: int, total: int) -> str:
    pct = (current / total * 100) if total else 0
    lines = [
        md.bold(f"\U0001f4e4 {md.escape('Uploading')}"),
        f"File: {md.code(filename)}",
        f"[{bar(pct)}] {md.code(f'{current}/{total}')}",
    ]
    return md.quote_block(lines)
