"""Async task queue with worker pool."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class TaskStatus(StrEnum):
    """Status of a queued task."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskResult:
    """Result of a task execution."""

    task_id: str
    status: TaskStatus
    result: Any = None
    error: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    duration_ms: float = 0.0


@dataclass
class Task:
    """A unit of work for the task queue."""

    name: str
    func: Callable[..., Any]
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    priority: int = 0
    max_retries: int = 0
    timeout: float = 0.0  # 0 = no timeout
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


class TaskQueue:
    """Async task queue with worker pool.

    Features:
    - Priority queue
    - Configurable worker count
    - Automatic retries
    - Per-task timeout
    - Result tracking
    """

    def __init__(
        self,
        num_workers: int = 4,
        max_queue_size: int = 1000,
        shutdown_timeout: float = 30.0,
    ) -> None:
        self._num_workers = num_workers
        self._max_queue_size = max_queue_size
        self._shutdown_timeout = shutdown_timeout

        self._queue: asyncio.PriorityQueue | None = None
        self._results: dict[str, TaskResult] = {}
        self._futures: dict[str, Future] = {}
        self._workers: list[threading.Thread] = []
        self._stop_event = threading.Event()
        self._executor: ThreadPoolExecutor | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._ready_event = threading.Event()
        self._started = False
        self._lock = threading.Lock()

    def submit(
        self,
        func: Callable[..., Any],
        *args: Any,
        name: str = "",
        priority: int = 0,
        max_retries: int = 0,
        timeout: float = 0.0,
        **kwargs: Any,
    ) -> str:
        """Submit a task. Returns task_id."""
        if not self._started:
            self.start()

        task = Task(
            name=name or func.__name__,
            func=func,
            args=args,
            kwargs=kwargs,
            priority=priority,
            max_retries=max_retries,
            timeout=timeout,
        )

        with self._lock:
            self._results[task.task_id] = TaskResult(
                task_id=task.task_id,
                status=TaskStatus.PENDING,
            )

        self._enqueue(task)
        self._ready_event.set()
        logger.debug("Submitted task %s (%s)", task.task_id, task.name)
        return task.task_id

    def get_result(
        self, task_id: str, timeout: float | None = None
    ) -> TaskResult | None:
        """Get task result, optionally waiting for completion."""
        deadline = time.time() + (timeout or 0)
        while True:
            with self._lock:
                result = self._results.get(task_id)
            if result is None:
                return None
            if result.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                return result
            if deadline and time.time() >= deadline:
                return result
            time.sleep(0.05)

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            result = self._results.get(task_id)
            if result is None:
                return False
            if result.status == TaskStatus.PENDING:
                result.status = TaskStatus.CANCELLED
                return True
        return False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._stop_event.clear()
        self._ready_event.clear()
        self._executor = ThreadPoolExecutor(max_workers=self._num_workers)
        self._loop_thread = threading.Thread(
            target=self._run_loop, daemon=True, name="TaskQueueLoop"
        )
        self._loop_thread.start()

    def shutdown(self, wait: bool = True) -> None:
        self._stop_event.set()
        self._ready_event.set()
        if wait and self._loop_thread is not None:
            self._loop_thread.join(timeout=self._shutdown_timeout)
        if self._executor is not None:
            self._executor.shutdown(wait=wait)
            self._executor = None
        self._started = False

    def stats(self) -> dict[str, Any]:
        with self._lock:
            pending = sum(
                1 for r in self._results.values()
                if r.status == TaskStatus.PENDING
            )
            running = sum(
                1 for r in self._results.values()
                if r.status == TaskStatus.RUNNING
            )
            completed = sum(
                1 for r in self._results.values()
                if r.status == TaskStatus.COMPLETED
            )
            failed = sum(
                1 for r in self._results.values()
                if r.status == TaskStatus.FAILED
            )
        return {
            "pending": pending,
            "running": running,
            "completed": completed,
            "failed": failed,
            "total": len(self._results),
            "workers": self._num_workers,
        }

    def _enqueue(self, task: Task) -> None:
        if self._loop is None or self._queue is None:
            time.sleep(0.1)
            return self._enqueue(task)
        try:
            asyncio.run_coroutine_threadsafe(
                self._queue.put((task.priority, task.created_at, task)),
                self._loop,
            )
        except Exception as e:
            logger.warning("Enqueue failed: %s", e)

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._queue = asyncio.PriorityQueue(maxsize=self._max_queue_size)

        for _ in range(self._num_workers):
            self._loop.create_task(self._worker())

        try:
            self._loop.run_until_complete(self._dispatcher())
        finally:
            self._loop.close()

    async def _dispatcher(self) -> None:
        while not self._stop_event.is_set():
            try:
                priority, ts, task = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0,
                )
                if self._executor is None:
                    continue
                future = self._executor.submit(self._execute_task, task)
                with self._lock:
                    self._futures[task.task_id] = future
            except TimeoutError:
                continue
            except Exception as e:
                logger.exception("Dispatcher error: %s", e)

    def _execute_task(self, task: Task) -> None:
        with self._lock:
            result = self._results.get(task.task_id)
            if result is None or result.status == TaskStatus.CANCELLED:
                return
            result.status = TaskStatus.RUNNING
            result.started_at = time.time()

        attempts = 0
        last_error = ""
        while attempts <= task.max_retries:
            try:
                if task.timeout > 0:
                    fut = self._executor.submit(task.func, *task.args, **task.kwargs)
                    output = fut.result(timeout=task.timeout)
                else:
                    output = task.func(*task.args, **task.kwargs)

                with self._lock:
                    result = self._results.get(task.task_id)
                    if result is not None:
                        result.status = TaskStatus.COMPLETED
                        result.result = output
                        result.completed_at = time.time()
                        result.duration_ms = (
                            (time.time() - result.started_at) * 1000
                        )
                return
            except Exception as e:
                last_error = str(e)
                attempts += 1
                logger.warning(
                    "Task %s attempt %d failed: %s",
                    task.task_id, attempts, e,
                )

        with self._lock:
            result = self._results.get(task.task_id)
            if result is not None:
                result.status = TaskStatus.FAILED
                result.error = last_error
                result.completed_at = time.time()
                result.duration_ms = (
                    (time.time() - result.started_at) * 1000
                )


__all__ = ["Task", "TaskQueue", "TaskResult", "TaskStatus"]