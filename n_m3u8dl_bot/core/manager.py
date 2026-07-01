"""Task lifecycle manager: creation, scheduling, execution and cleanup."""

from __future__ import annotations

import asyncio
import logging
import shutil
from typing import Optional

from pyrogram import Client

from ..config import Config
from ..ui import keyboards as kb
from ..ui import progress as pg
from ..upload.uploader import Uploader
from . import downloader
from .status import StatusReporter
from .task import Task, TaskState, new_token

log = logging.getLogger("n_m3u8dl_bot.manager")

_STALE_SECONDS = 600  # 10 minutes without starting -> prune


class TaskManager:
    def __init__(self, client: Client, config: Config) -> None:
        self._client = client
        self._config = config
        self._tasks: dict[str, Task] = {}
        self._active_count = 0
        self._uploader = Uploader(client)

    def create_task(
        self,
        *,
        chat_id: int,
        user_id: int,
        trigger_message_id: int,
        url: str,
        flags: list[str],
    ) -> Task:
        self._prune()
        token = new_token()
        work_subdir = self._config.download_dir / token
        task = Task(
            token=token,
            chat_id=chat_id,
            user_id=user_id,
            trigger_message_id=trigger_message_id,
            url=url,
            flags=flags,
            work_subdir=work_subdir,
        )
        self._tasks[token] = task
        return task

    def get(self, token: str) -> Optional[Task]:
        return self._tasks.get(token)

    def cancel(self, token: str) -> None:
        task = self._tasks.get(token)
        if task:
            task.cancel()

    def attach_reporter(self, task: Task, reporter: StatusReporter) -> None:
        task.reporter = reporter

    def launch(self, task: Task) -> bool:
        """Start execution of a pending task. Returns False if already started."""

        if task.state != TaskState.PENDING:
            return False
        if self._active_count >= self._config.max_concurrent_tasks:
            task.state = TaskState.QUEUED
            return True
        task.state = TaskState.DOWNLOADING
        self._active_count += 1
        asyncio.create_task(self._run(task))
        return True

    async def _run(self, task: Task) -> None:
        try:
            await self._execute(task)
        except Exception:
            log.exception("Unhandled error in task %s", task.token)
            task.state = TaskState.FAILED
            if task.reporter:
                await task.reporter.finalize(
                    pg.render_error("Download failed", "Internal error")
                )
        finally:
            self._active_count = max(0, self._active_count - 1)

    async def _execute(self, task: Task) -> None:
        assert task.work_subdir is not None

        if task.reporter:
            await task.reporter.update(
                pg.render_status("Downloading", ["Starting N_m3u8DL-RE..."], emoji="\U0001f4e5"),
                reply_markup=kb.cancel_only(task.token),
                force=True,
            )

        async def _on_progress(pct: float, raw_line: str) -> None:
            if task.reporter:
                await task.reporter.update(
                    pg.render_progress(
                        "Downloading",
                        done=pct,
                        total=100.0,
                        extra=raw_line[:120],
                    ),
                    reply_markup=kb.cancel_only(task.token),
                )

        proc, rc = await downloader.run_download(
            self._config.n_m3u8dl_bin,
            task.url,
            task.flags,
            save_dir=task.work_subdir,
            progress_cb=_on_progress,
            cancel_event=task.cancel_event,
        )
        task.process = proc

        if task.cancelled:
            task.state = TaskState.CANCELLED
            if task.reporter:
                await task.reporter.finalize(
                    pg.render_status("Cancelled", ["Task was cancelled by user."], emoji="\U0001f6d1")
                )
            self._cleanup(task)
            return

        if rc != 0:
            task.state = TaskState.FAILED
            if task.reporter:
                await task.reporter.finalize(
                    pg.render_error("Download failed", f"N_m3u8DL-RE exited with code {rc}")
                )
            return

        # Collect output files.
        produced = list(task.work_subdir.rglob("*"))
        produced = [f for f in produced if f.is_file() and not f.name.endswith(".json")]
        task.produced_files = produced

        if not produced:
            task.state = TaskState.FAILED
            if task.reporter:
                await task.reporter.finalize(
                    pg.render_error("No output files", "N_m3u8DL-RE produced no downloadable files.")
                )
            return

        # Upload phase.
        task.state = TaskState.UPLOADING
        if task.reporter:
            await task.reporter.update(
                pg.render_status(
                    "Uploading",
                    [f"Uploading {len(produced)} file(s) to Telegram..."],
                    emoji="\U0001f4e4",
                ),
                reply_markup=kb.cancel_only(task.token),
                force=True,
            )

        for idx, fpath in enumerate(produced, 1):
            if task.cancelled:
                task.state = TaskState.CANCELLED
                if task.reporter:
                    await task.reporter.finalize(
                        pg.render_status("Cancelled", emoji="\U0001f6d1")
                    )
                self._cleanup(task)
                return

            size_mb = fpath.stat().st_size / (1024 * 1024)
            if size_mb > self._config.max_upload_size_mb:
                log.warning("Skipping %s (%.1f MB > limit)", fpath.name, size_mb)
                continue

            async def _upload_progress(done: float, total: float, speed: float) -> None:
                if task.reporter:
                    await task.reporter.update(
                        pg.render_progress(
                            f"Uploading ({idx}/{len(produced)})",
                            done=done,
                            total=total,
                            speed=speed,
                            extra=fpath.name,
                        ),
                        reply_markup=kb.cancel_only(task.token),
                    )

            try:
                await self._uploader.send_document(
                    task.chat_id,
                    fpath,
                    caption=f"<code>{fpath.name}</code>",
                    progress_cb=_upload_progress,
                    reply_to=task.trigger_message_id,
                )
            except Exception:
                log.exception("Failed to upload %s", fpath.name)

        task.state = TaskState.DONE
        if task.reporter:
            await task.reporter.finalize(
                pg.render_status(
                    "Done",
                    [f"Uploaded {len(produced)} file(s)."],
                    emoji="\u2705",
                )
            )
        self._cleanup(task)

    def _cleanup(self, task: Task) -> None:
        """Remove task working directory."""

        if task.work_subdir and task.work_subdir.exists():
            try:
                shutil.rmtree(task.work_subdir)
            except OSError:
                log.warning("Failed to clean up %s", task.work_subdir)

    def _prune(self) -> None:
        """Remove stale pending tasks."""

        import time

        now = time.monotonic()
        stale = [
            t
            for t in self._tasks.values()
            if t.state == TaskState.PENDING and (now - t.created_at) > _STALE_SECONDS
        ]
        for t in stale:
            del self._tasks[t.token]
