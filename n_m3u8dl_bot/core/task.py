"""In-memory representation of a download task and its lifecycle state."""

from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from .status import StatusReporter


class TaskState(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    UPLOADING = "uploading"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


def new_token() -> str:
    """Short, URL-safe token that fits Telegram's 64-byte callback budget."""

    return secrets.token_urlsafe(6)


@dataclass(slots=True)
class Task:
    token: str
    chat_id: int
    user_id: int
    trigger_message_id: int
    url: str
    flags: list[str]

    state: TaskState = TaskState.PENDING
    created_at: float = field(default_factory=time.monotonic)

    reporter: Optional[StatusReporter] = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)

    work_subdir: Optional[Path] = None
    produced_files: list[Path] = field(default_factory=list)

    process: Optional[asyncio.subprocess.Process] = None

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def cancel(self) -> None:
        self.cancel_event.set()
        if self.process is not None:
            try:
                self.process.kill()
            except ProcessLookupError:
                pass
