"""Bulkhead — semaphore-based concurrency isolation (per tenant/service)."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class BulkheadFull(Exception):
    """Raised when the bulkhead cannot admit a new caller."""

    def __init__(self, name: str, message: str | None = None) -> None:
        super().__init__(message or f"Bulkhead '{name}' is full")
        self.bulkhead_name = name


@dataclass
class BulkheadStats:
    """Bulkhead runtime statistics."""

    current_concurrent: int = 0
    max_concurrent: int = 0
    waiting: int = 0
    total_acquired: int = 0
    total_rejected: int = 0
    total_released: int = 0
    last_acquire_at: float = 0.0
    last_reject_at: float = 0.0


@dataclass
class _Waiter:
    """A pending acquire request tracked for stats / timeout."""

    event: threading.Event = field(default_factory=threading.Event)
    granted: bool = False


class Bulkhead:
    """Concurrency isolation via semaphore.

    - ``max_concurrent``: hard cap on simultaneous holders.
    - ``queue_size``: how many callers may wait when the bulkhead is full.
    - Admit policy: try semaphore (non-blocking) → optional queue → reject.
    """

    def __init__(
        self,
        name: str,
        max_concurrent: int = 10,
        queue_size: int = 100,
    ) -> None:
        self.name = name
        self.max_concurrent = max(1, max_concurrent)
        self.queue_size = max(0, queue_size)
        self._sem = threading.Semaphore(self.max_concurrent)
        self._active = 0
        self._active_lock = threading.Lock()
        self._stats = BulkheadStats()
        self._waiters: list[_Waiter] = []
        self._lock = threading.Lock()

    def _try_acquire_slot(self) -> bool:
        acquired = self._sem.acquire(blocking=False)
        if not acquired:
            return False
        with self._active_lock:
            self._active += 1
            self._stats.current_concurrent = self._active
            if self._active > self._stats.max_concurrent:
                self._stats.max_concurrent = self._active
        with self._lock:
            self._stats.total_acquired += 1
            self._stats.last_acquire_at = time.time()
        return True

    def _release_slot(self) -> None:
        with self._active_lock:
            self._active = max(0, self._active - 1)
            self._stats.current_concurrent = self._active
        self._sem.release()
        with self._lock:
            self._stats.total_released += 1
            self._wake_next_waiter()

    def _wake_next_waiter(self) -> None:
        if not self._waiters:
            return
        waiter = self._waiters.pop(0)
        if not waiter.event.is_set():
            waiter.granted = True
            waiter.event.set()

    def acquire(self, timeout: float | None = None) -> BulkheadLease:
        """Acquire a bulkhead slot.

        Returns a lease that must be used as a context manager so the slot
        is released deterministically.
        """
        if self._try_acquire_slot():
            return BulkheadLease(self)

        with self._lock:
            if len(self._waiters) >= self.queue_size:
                self._stats.total_rejected += 1
                self._stats.last_reject_at = time.time()
                raise BulkheadFull(self.name)
            waiter = _Waiter()
            self._waiters.append(waiter)
            self._stats.waiting = len(self._waiters)

        signaled = waiter.event.wait(timeout=timeout)
        with self._lock:
            self._stats.waiting = len(self._waiters)
            if not signaled or not waiter.granted:
                if waiter in self._waiters:
                    self._waiters.remove(waiter)
                self._stats.total_rejected += 1
                self._stats.last_reject_at = time.time()
                raise BulkheadFull(self.name)

        if not self._try_acquire_slot():
            # Slot freed but semaphore was raced; reject.
            with self._lock:
                self._stats.total_rejected += 1
                self._stats.last_reject_at = time.time()
            raise BulkheadFull(self.name)
        return BulkheadLease(self)

    def release(self) -> None:
        """Release a previously acquired slot."""
        self._release_slot()

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "name": self.name,
                "max_concurrent": self.max_concurrent,
                "queue_size": self.queue_size,
                "current_concurrent": self._stats.current_concurrent,
                "max_observed_concurrent": self._stats.max_concurrent,
                "waiting": self._stats.waiting,
                "total_acquired": self._stats.total_acquired,
                "total_rejected": self._stats.total_rejected,
                "total_released": self._stats.total_released,
                "last_acquire_at": self._stats.last_acquire_at,
                "last_reject_at": self._stats.last_reject_at,
            }

    def reset(self) -> None:
        """Reset statistics (does not release in-flight slots)."""
        with self._lock:
            self._stats = BulkheadStats(
                current_concurrent=self._stats.current_concurrent,
                max_concurrent=self._stats.max_concurrent,
            )


class BulkheadLease:
    """Context manager wrapping a bulkhead slot."""

    def __init__(self, bulkhead: Bulkhead) -> None:
        self._bulkhead = bulkhead
        self._released = False

    def __enter__(self) -> BulkheadLease:
        return self

    def __exit__(self, *args: Any) -> None:
        self.release()

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._bulkhead.release()


class BulkheadRegistry:
    """Thread-safe registry of named bulkheads."""

    def __init__(self) -> None:
        self._bulkheads: dict[str, Bulkhead] = {}
        self._lock = threading.Lock()

    def get_or_create(
        self,
        name: str,
        max_concurrent: int = 10,
        queue_size: int = 100,
    ) -> Bulkhead:
        with self._lock:
            existing = self._bulkheads.get(name)
            if existing is not None:
                return existing
            bulkhead = Bulkhead(
                name=name,
                max_concurrent=max_concurrent,
                queue_size=queue_size,
            )
            self._bulkheads[name] = bulkhead
            logger.debug("Created bulkhead %r", name)
            return bulkhead

    def get(self, name: str) -> Bulkhead | None:
        with self._lock:
            return self._bulkheads.get(name)

    def remove(self, name: str) -> bool:
        with self._lock:
            return self._bulkheads.pop(name, None) is not None

    def list_all(self) -> list[Bulkhead]:
        with self._lock:
            return list(self._bulkheads.values())

    def run(
        self,
        name: str,
        func: Callable[..., Any],
        *args: Any,
        max_concurrent: int = 10,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> Any:
        """Acquire a bulkhead slot and invoke ``func``."""
        bulkhead = self.get_or_create(name, max_concurrent=max_concurrent)
        with bulkhead.acquire(timeout=timeout):
            return func(*args, **kwargs)


__all__ = [
    "Bulkhead",
    "BulkheadFull",
    "BulkheadLease",
    "BulkheadRegistry",
    "BulkheadStats",
]