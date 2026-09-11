"""Background tasks — long-running task manager with progress callbacks."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path.home() / ".Zeloo" / "cache" / "background_tasks" / "tasks.db"
DEFAULT_RETENTION_HOURS = 24
_PROGRESS_FLUSH_INTERVAL = 0.5


class TaskStatus(str, Enum):
    """Lifecycle states for a background task."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskHandle:
    """Public-facing handle returned from :meth:`submit`."""

    task_id: str
    name: str
    status: TaskStatus = TaskStatus.PENDING
    progress: float = 0.0
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    result: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id, "name": self.name,
            "status": self.status.value, "progress": self.progress,
            "created_at": self.created_at, "started_at": self.started_at,
            "finished_at": self.finished_at, "result": self.result,
            "error": self.error, "metadata": self.metadata,
        }

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> TaskHandle:
        return cls(
            task_id=row["task_id"], name=row["name"], status=TaskStatus(row["status"]),
            progress=row["progress"], created_at=row["created_at"],
            started_at=row["started_at"], finished_at=row["finished_at"],
            result=json.loads(row["result"]) if row["result"] else None,
            error=row["error"], metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )


class _ProgressReporter:
    """Callable object given to user functions for progress reporting."""

    def __init__(self, task_id: str, handle_ref: Callable[[], TaskHandle],
                 registry: "BackgroundTaskRegistry") -> None:
        self._task_id = task_id
        self._handle_ref = handle_ref
        self._registry = registry
        self._last_flush = 0.0

    def __call__(self, progress: float) -> None:
        progress = max(0.0, min(1.0, float(progress)))
        handle = self._handle_ref()
        handle.progress = progress
        now = time.time()
        if now - self._last_flush >= _PROGRESS_FLUSH_INTERVAL:
            self._registry._persist_progress(self._task_id, progress)
            self._last_flush = now


class BackgroundTaskRegistry:
    """Long-running task manager with progress callbacks and SQLite persistence."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._handles: dict[str, TaskHandle] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._cancel_flags: dict[str, threading.Event] = {}
        self._progress_subs: dict[str, list[Callable[[float], None]]] = {}
        self._init_db()
        self._hydrate()

    def _init_db(self) -> None:
        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    status TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0.0,
                    created_at REAL NOT NULL, started_at REAL, finished_at REAL,
                    result TEXT, error TEXT, metadata TEXT)"""
            )
            conn.commit()

    def _hydrate(self) -> None:
        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            for row in conn.execute("SELECT * FROM tasks"):
                self._handles[row["task_id"]] = TaskHandle.from_row(row)

    def submit(self, name: str, fn: Callable[..., Any],
               *args: Any, **kwargs: Any) -> TaskHandle:
        """Submit a callable for asynchronous execution."""
        task_id = uuid.uuid4().hex
        handle = TaskHandle(task_id=task_id, name=name)
        self._handles[task_id] = handle
        cancel_event = threading.Event()
        self._cancel_flags[task_id] = cancel_event

        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO tasks (task_id, name, status, progress, created_at, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (task_id, name, TaskStatus.PENDING.value, 0.0, handle.created_at,
                 json.dumps(handle.metadata)),
            )
            conn.commit()

        thread = threading.Thread(
            target=self._run,
            args=(handle, fn, args, kwargs, cancel_event),
            name=f"bg-task-{task_id[:8]}", daemon=True,
        )
        self._threads[task_id] = thread
        thread.start()
        return handle

    def _run(self, handle: TaskHandle, fn: Callable[..., Any],
             args: tuple[Any, ...], kwargs: dict[str, Any],
             cancel_event: threading.Event) -> None:
        handle.status = TaskStatus.RUNNING
        handle.started_at = time.time()
        self._persist_status(handle)
        reporter = _ProgressReporter(
            task_id=handle.task_id,
            handle_ref=lambda: self._handles[handle.task_id],
            registry=self,
        )
        try:
            # Convention: ``__progress__`` kwarg is replaced by the reporter.
            call_kwargs = dict(kwargs)
            call_kwargs["__progress__"] = reporter
            result = fn(*args, **call_kwargs)
            if cancel_event.is_set():
                handle.status = TaskStatus.CANCELLED
            else:
                handle.status = TaskStatus.DONE
                handle.progress = 1.0
                handle.result = result
        except Exception as exc:
            handle.status = TaskStatus.FAILED
            handle.error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
            logger.exception("Background task %s failed", handle.task_id)
        finally:
            handle.finished_at = time.time()
            self._persist_status(handle)
            self._persist_progress(handle.task_id, handle.progress)
            for cb in list(self._progress_subs.get(handle.task_id, [])):
                try:
                    cb(handle.progress)
                except Exception:
                    logger.exception("Progress callback raised")

    def cancel(self, task_id: str) -> bool:
        """Request cancellation of ``task_id``. Returns True if signalled."""
        with self._lock:
            event = self._cancel_flags.get(task_id)
            handle = self._handles.get(task_id)
            if event is None or handle is None:
                return False
            if handle.status in (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.CANCELLED):
                return False
            event.set()
            return True

    def get_status(self, task_id: str) -> TaskStatus:
        """Return the current status of a task."""
        handle = self._handles.get(task_id)
        if handle is None:
            raise KeyError(f"unknown task_id: {task_id}")
        return handle.status

    def get_result(self, task_id: str, timeout: float = 30.0) -> Any:
        """Block until the task finishes and return its result."""
        deadline = time.time() + timeout
        thread = self._threads.get(task_id)
        while thread is not None and thread.is_alive():
            if time.time() >= deadline:
                raise TimeoutError(f"task {task_id} did not finish within {timeout}s")
            thread.join(timeout=0.1)
        handle = self._handles.get(task_id)
        if handle is None:
            raise KeyError(f"unknown task_id: {task_id}")
        if handle.status == TaskStatus.FAILED:
            raise RuntimeError(handle.error or "task failed")
        if handle.status == TaskStatus.CANCELLED:
            raise RuntimeError("task was cancelled")
        return handle.result

    def subscribe_progress(self, task_id: str, callback: Callable[[float], None]) -> None:
        """Register a callback to be invoked on each progress flush."""
        with self._lock:
            self._progress_subs.setdefault(task_id, []).append(callback)

    def list_tasks(self, status: TaskStatus | None = None) -> list[TaskHandle]:
        """Return task handles, optionally filtered by status."""
        with self._lock:
            handles = list(self._handles.values())
        if status is not None:
            handles = [h for h in handles if h.status == status]
        handles.sort(key=lambda h: h.created_at, reverse=True)
        return handles

    def cleanup_finished(self, older_than_hours: int = DEFAULT_RETENTION_HOURS) -> int:
        """Remove terminal-state tasks older than ``older_than_hours``."""
        cutoff = time.time() - older_than_hours * 3600
        with self._lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM tasks WHERE status IN (?, ?, ?) AND finished_at IS NOT NULL "
                "AND finished_at < ?",
                (TaskStatus.DONE.value, TaskStatus.FAILED.value,
                 TaskStatus.CANCELLED.value, cutoff),
            )
            conn.commit()
            removed = cursor.rowcount
        stale = [tid for tid, h in self._handles.items()
                 if h.status in (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.CANCELLED)
                 and h.finished_at is not None and h.finished_at < cutoff]
        for tid in stale:
            self._handles.pop(tid, None)
            self._cancel_flags.pop(tid, None)
            self._progress_subs.pop(tid, None)
            self._threads.pop(tid, None)
        return removed

    def _persist_status(self, handle: TaskHandle) -> None:
        try:
            with self._lock, sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE tasks SET status = ?, progress = ?, started_at = ?, "
                    "finished_at = ?, result = ?, error = ? WHERE task_id = ?",
                    (handle.status.value, handle.progress, handle.started_at,
                     handle.finished_at,
                     json.dumps(handle.result) if handle.result is not None else None,
                     handle.error, handle.task_id),
                )
                conn.commit()
        except sqlite3.Error as exc:
            logger.warning("Failed to persist task status: %s", exc)

    def _persist_progress(self, task_id: str, progress: float) -> None:
        try:
            with self._lock, sqlite3.connect(self.db_path) as conn:
                conn.execute("UPDATE tasks SET progress = ? WHERE task_id = ?",
                             (progress, task_id))
                conn.commit()
        except sqlite3.Error as exc:
            logger.warning("Failed to persist task progress: %s", exc)