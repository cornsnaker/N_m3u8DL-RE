"""Download task data model.

Each user request creates a ``Task`` that tracks its lifecycle from URL
submission through download, optional decryption/muxing and final upload.
"""

from __future__ import annotations

import enum
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


class TaskState(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    UPLOADING = "uploading"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskProgress:
    """Mutable progress counters updated by the downloader."""

    stage: str = "Waiting"
    percent: float = 0.0
    speed: str = ""
    eta: str = ""
    detail: str = ""


@dataclass
class Task:
    """Represents a single download job."""

    token: str
    chat_id: int
    user_id: int
    trigger_message_id: int
    url: str
    cli_args: list[str] = field(default_factory=list)
    state: TaskState = TaskState.PENDING
    progress: TaskProgress = field(default_factory=TaskProgress)
    output_dir: Optional[Path] = None
    output_files: list[Path] = field(default_factory=list)
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    status_message_id: Optional[int] = None

    @staticmethod
    def generate_token() -> str:
        return secrets.token_hex(4)
