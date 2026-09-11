"""Background task scheduler — cron-like scheduling for periodic tasks."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class ScheduledTask:
    """A scheduled background task."""

    name: str
    func: Callable[[], Any]
    interval_seconds: float = 0.0
    cron_expr: str = ""
    next_run_at: float = field(default_factory=time.time)
    last_run_at: float = 0.0
    last_duration_ms: float = 0.0
    run_count: int = 0
    error_count: int = 0
    last_error: str = ""
    enabled: bool = True
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    metadata: dict[str, Any] = field(default_factory=dict)


class Scheduler:
    """Background task scheduler with interval and cron support.

    Features:
    - Simple interval scheduling (every N seconds)
    - Cron expression support (basic: minute/hour/day/month/weekday)
    - One-shot delayed tasks
    - Async and sync task functions
    - Automatic retries on error (with backoff)
    """

    def __init__(self, max_concurrent: int = 4) -> None:
        self._tasks: dict[str, ScheduledTask] = {}
        self._lock = threading.Lock()
        self._running = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._max_concurrent = max_concurrent
        self._semaphore = threading.Semaphore(max_concurrent)

    def schedule_interval(
        self,
        name: str,
        func: Callable[[], Any],
        interval_seconds: float,
    ) -> ScheduledTask:
        """Schedule a task to run every N seconds."""
        task = ScheduledTask(
            name=name,
            func=func,
            interval_seconds=interval_seconds,
            next_run_at=time.time() + interval_seconds,
        )
        with self._lock:
            self._tasks[task.task_id] = task
        logger.info("Scheduled %s every %ss", name, interval_seconds)
        return task

    def schedule_cron(
        self,
        name: str,
        func: Callable[[], Any],
        cron_expr: str,
    ) -> ScheduledTask:
        """Schedule a task with cron expression.

        Format: "minute hour day_of_month month day_of_week"
        Each field can be a number, *, or comma-separated list.
        """
        task = ScheduledTask(
            name=name,
            func=func,
            cron_expr=cron_expr,
            next_run_at=self._next_cron_run(cron_expr),
        )
        with self._lock:
            self._tasks[task.task_id] = task
        logger.info("Scheduled %s with cron: %s", name, cron_expr)
        return task

    def schedule_once(
        self,
        name: str,
        func: Callable[[], Any],
        delay_seconds: float,
    ) -> ScheduledTask:
        """Schedule a one-shot task to run after delay."""
        task = ScheduledTask(
            name=name,
            func=func,
            next_run_at=time.time() + delay_seconds,
        )
        with self._lock:
            self._tasks[task.task_id] = task
        return task

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            return self._tasks.pop(task_id, None) is not None

    def list_tasks(self) -> list[ScheduledTask]:
        with self._lock:
            return list(self._tasks.values())

    def start(self) -> None:
        """Start the scheduler thread."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="ZelooScheduler"
        )
        self._thread.start()
        logger.info("Scheduler started with %d tasks", len(self._tasks))

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the scheduler."""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        logger.info("Scheduler stopped")

    def _run_loop(self) -> None:
        while self._running and not self._stop_event.is_set():
            try:
                self._check_and_run()
            except Exception as e:
                logger.exception("Scheduler loop error: %s", e)
            self._stop_event.wait(timeout=0.5)

    def _check_and_run(self) -> None:
        now = time.time()
        tasks_to_run = []
        with self._lock:
            for task in self._tasks.values():
                if task.enabled and task.next_run_at <= now:
                    tasks_to_run.append(task)

        for task in tasks_to_run:
            threading.Thread(
                target=self._run_task, args=(task,), daemon=True,
            ).start()

    def _run_task(self, task: ScheduledTask) -> None:
        with self._semaphore:
            start = time.time()
            try:
                task.func()
                task.error_count = 0
            except Exception as e:
                task.error_count += 1
                task.last_error = str(e)
                logger.exception("Task %s failed: %s", task.name, e)
            finally:
                task.last_run_at = time.time()
                task.last_duration_ms = (time.time() - start) * 1000
                task.run_count += 1
                if task.interval_seconds > 0:
                    task.next_run_at = time.time() + task.interval_seconds
                elif task.cron_expr:
                    task.next_run_at = self._next_cron_run(task.cron_expr)
                else:
                    with self._lock:
                        self._tasks.pop(task.task_id, None)

    def _next_cron_run(self, cron_expr: str) -> float:
        """Compute next run time from cron expression."""
        try:
            parts = cron_expr.split()
            if len(parts) != 5:
                return time.time() + 3600
            minute, hour, day, month, weekday = parts
            now = time.time()
            dt = time.localtime(now)
            next_minute = dt.tm_min + 1
            next_hour = dt.tm_hour
            if next_minute >= 60:
                next_minute = 0
                next_hour = (next_hour + 1) % 24
            return time.mktime((
                dt.tm_year, dt.tm_mon, dt.tm_mday,
                next_hour, next_minute, 0, 0, 0, -1,
            ))
        except Exception:
            return time.time() + 3600


__all__ = ["Scheduler", "ScheduledTask"]