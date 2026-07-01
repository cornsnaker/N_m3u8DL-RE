"""Centralized runtime configuration for the N_m3u8DL-RE Telegram bot.

All values are sourced from environment variables so the bot can be deployed
without code changes. A ``.env`` file is loaded automatically when present.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def _load_dotenv() -> None:
    """Best-effort loader for a local ``.env`` file."""

    env_path = Path(os.getenv("M3U8BOT_ENV_FILE", ".env"))
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class Config:
    """Immutable view of the bot configuration."""

    api_id: int
    api_hash: str
    bot_token: str

    work_dir: Path
    download_dir: Path
    tmp_dir: Path

    n_m3u8dl_re_bin: str
    ffmpeg_bin: str
    mp4decrypt_bin: str
    mkvmerge_bin: str
    shaka_packager_bin: str

    thread_count: int
    max_concurrent_tasks: int
    progress_update_interval: float
    upload_split_size: int

    allowed_user_ids: frozenset[int] = field(default_factory=frozenset)

    @classmethod
    def from_env(cls) -> "Config":
        _load_dotenv()

        work_dir = Path(os.getenv("WORK_DIR", "./downloads")).expanduser().resolve()
        download_dir = work_dir / "output"
        tmp_dir = work_dir / "tmp"

        allowed_raw = os.getenv("ALLOWED_USER_IDS", "").strip()
        allowed_ids = frozenset(
            int(tok)
            for tok in allowed_raw.replace(",", " ").split()
            if tok.strip().lstrip("-").isdigit()
        )

        return cls(
            api_id=_get_int("TELEGRAM_API_ID", 0),
            api_hash=os.getenv("TELEGRAM_API_HASH", ""),
            bot_token=os.getenv("BOT_TOKEN", ""),
            work_dir=work_dir,
            download_dir=download_dir,
            tmp_dir=tmp_dir,
            n_m3u8dl_re_bin=os.getenv("N_M3U8DL_RE_BIN", "N_m3u8DL-RE"),
            ffmpeg_bin=os.getenv("FFMPEG_BIN", "ffmpeg"),
            mp4decrypt_bin=os.getenv("MP4DECRYPT_BIN", "mp4decrypt"),
            mkvmerge_bin=os.getenv("MKVMERGE_BIN", "mkvmerge"),
            shaka_packager_bin=os.getenv("SHAKA_PACKAGER_BIN", "packager"),
            thread_count=_get_int("THREAD_COUNT", 16),
            max_concurrent_tasks=_get_int("MAX_CONCURRENT_TASKS", 3),
            progress_update_interval=float(os.getenv("PROGRESS_INTERVAL", "5")),
            upload_split_size=_get_int("UPLOAD_SPLIT_SIZE", 2_000_000_000),
            allowed_user_ids=allowed_ids,
        )

    def validate(self) -> list[str]:
        """Return a list of human-readable configuration problems."""

        problems: list[str] = []
        if self.api_id <= 0:
            problems.append("TELEGRAM_API_ID is missing or invalid.")
        if not self.api_hash:
            problems.append("TELEGRAM_API_HASH is missing.")
        if not self.bot_token:
            problems.append("BOT_TOKEN is missing.")
        return problems

    def is_user_allowed(self, user_id: Optional[int]) -> bool:
        if not self.allowed_user_ids:
            return True
        return user_id is not None and user_id in self.allowed_user_ids

    def ensure_dirs(self) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
