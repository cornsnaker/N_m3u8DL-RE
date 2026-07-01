"""Task lifecycle manager.

Creates, tracks, launches and cleans up download tasks. Limits concurrency
and provides lookup by token.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from typing import Optional

from pyrogram import Client

from ..config import Config
from .downloader import run_download
from .task import Task, TaskState

log = logging.getLogger("m3u8bot.manager")

_TASK_TTL = 3600  # prune finished tasks older than 1 hour


class TaskManager:
    """Global task coordinator."""

    def __init__(self, client: Client, config: Config) -> None:
        self._client = client
        self._config = config
        self._tasks: dict[str, Task] = {}
        self._running: dict[str, asyncio.Task[None]] = {}
        self._progress_events: dict[str, asyncio.Event] = {}

    @property
    def client(self) -> Client:
        return self._client

    @property
    def config(self) -> Config:
        return self._config

    def create_task(
        self,
        chat_id: int,
        user_id: int,
        trigger_message_id: int,
        url: str,
        cli_args: Optional[list[str]] = None,
    ) -> Task:
        self._prune()
        token = Task.generate_token()
        task = Task(
            token=token,
            chat_id=chat_id,
            user_id=user_id,
            trigger_message_id=trigger_message_id,
            url=url,
            cli_args=cli_args or [],
        )
        self._tasks[token] = task
        return task

    def get(self, token: str) -> Optional[Task]:
        return self._tasks.get(token)

    def active_count(self) -> int:
        return sum(
            1 for t in self._tasks.values() if t.state in (TaskState.RUNNING, TaskState.UPLOADING)
        )

    def launch(self, task: Task) -> bool:
        """Start downloading. Returns False if already running or at capacity."""

        if task.state != TaskState.PENDING:
            return False
        if self.active_count() >= self._config.max_concurrent_tasks:
            return False

        evt = asyncio.Event()
        self._progress_events[task.token] = evt
        self._running[task.token] = asyncio.create_task(
            self._run_task(task, evt), name=f"dl-{task.token}"
        )
        return True

    async def _run_task(self, task: Task, progress_event: asyncio.Event) -> None:
        try:
            await run_download(self._config, task, on_progress=progress_event)
        except Exception as exc:
            log.exception("Unhandled error in task %s", task.token)
            task.state = TaskState.FAILED
            task.error = str(exc)
        finally:
            self._running.pop(task.token, None)
            self._progress_events.pop(task.token, None)

    def cancel(self, token: str) -> None:
        task = self._tasks.get(token)
        if task:
            task.state = TaskState.CANCELLED
        running = self._running.pop(token, None)
        if running and not running.done():
            running.cancel()
        self._progress_events.pop(token, None)

    def get_progress_event(self, token: str) -> Optional[asyncio.Event]:
        return self._progress_events.get(token)

    def cleanup_task(self, token: str) -> None:
        """Remove temporary files for a finished task."""

        task = self._tasks.get(token)
        if task and task.output_dir and task.output_dir.exists():
            shutil.rmtree(task.output_dir, ignore_errors=True)
        tmp = self._config.tmp_dir / token
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)

    def _prune(self) -> None:
        now = time.time()
        expired = [
            token
            for token, task in self._tasks.items()
            if task.state
            in (TaskState.DONE, TaskState.FAILED, TaskState.CANCELLED)
            and now - task.created_at > _TASK_TTL
        ]
        for token in expired:
            self.cleanup_task(token)
            self._tasks.pop(token, None)
