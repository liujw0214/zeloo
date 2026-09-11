"""Timeout — per-call/stream/batch timeout policy with context manager."""

from __future__ import annotations

import functools
import inspect
import logging
import signal
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

TimeoutKind = Literal["call", "stream", "batch"]


class TimeoutExceeded(Exception):
    """Raised when an operation exceeds its allotted timeout."""

    def __init__(self, seconds: float, kind: str = "call") -> None:
        super().__init__(f"Operation exceeded {seconds:.2f}s timeout ({kind})")
        self.seconds = seconds
        self.kind = kind


@dataclass
class TimeoutStats:
    """Tracked timeout statistics."""

    total_operations: int = 0
    timeouts_triggered: int = 0
    total_wait_seconds: float = 0.0


class TimeoutPolicy:
    """Per-call / per-stream / per-batch timeout configuration."""

    def __init__(
        self,
        call_timeout: float = 30.0,
        stream_timeout: float = 120.0,
        batch_timeout: float = 600.0,
    ) -> None:
        self.call_timeout = max(0.0, call_timeout)
        self.stream_timeout = max(0.0, stream_timeout)
        self.batch_timeout = max(0.0, batch_timeout)
        self._stats = TimeoutStats()
        self._lock = threading.Lock()

    def get_timeout(self, kind: TimeoutKind) -> float:
        """Return the configured timeout for the given operation kind."""
        if kind == "call":
            return self.call_timeout
        if kind == "stream":
            return self.stream_timeout
        if kind == "batch":
            return self.batch_timeout
        raise ValueError(f"unknown timeout kind: {kind!r}")

    def set_timeout(self, kind: TimeoutKind, seconds: float) -> None:
        seconds = max(0.0, seconds)
        if kind == "call":
            self.call_timeout = seconds
        elif kind == "stream":
            self.stream_timeout = seconds
        elif kind == "batch":
            self.batch_timeout = seconds
        else:
            raise ValueError(f"unknown timeout kind: {kind!r}")

    def with_timeout(self, seconds: float) -> TimeoutContext:
        """Create a TimeoutContext with the given deadline."""
        return TimeoutContext(seconds, stats=self._stats)

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "total_operations": self._stats.total_operations,
                "timeouts_triggered": self._stats.timeouts_triggered,
                "total_wait_seconds": round(
                    self._stats.total_wait_seconds, 4
                ),
            }

    def _record_start(self) -> float:
        with self._lock:
            self._stats.total_operations += 1
        return time.monotonic()

    def _record_end(self, start: float, exceeded: bool) -> None:
        with self._lock:
            self._stats.total_wait_seconds += time.monotonic() - start
            if exceeded:
                self._stats.timeouts_triggered += 1


class TimeoutContext:
    """Context manager / decorator that enforces a wall-clock timeout.

    Uses a background timer thread. Suitable for both sync functions and
    arbitrary code blocks. Raises ``TimeoutExceeded`` when the deadline
    is missed.
    """

    def __init__(
        self,
        seconds: float,
        kind: TimeoutKind = "call",
        stats: TimeoutStats | None = None,
    ) -> None:
        self._seconds = max(0.0, seconds)
        self._kind = kind
        self._stats = stats
        self._deadline: float | None = None
        self._timer: threading.Timer | None = None
        self._expired = threading.Event()
        self._start_time: float | None = None

    @property
    def seconds(self) -> float:
        return self._seconds

    @property
    def expired(self) -> bool:
        return self._expired.is_set()

    @property
    def remaining(self) -> float:
        if self._deadline is None:
            return self._seconds
        return max(0.0, self._deadline - time.monotonic())

    def __enter__(self) -> TimeoutContext:
        self._start_time = time.monotonic()
        if self._stats is not None:
            with getattr(self._stats, "_lock", threading.Lock()):
                self._stats.total_operations += 1
        self._deadline = self._start_time + self._seconds
        if self._seconds > 0:
            self._timer = threading.Timer(
                self._seconds, self._on_expire
            )
            self._timer.daemon = True
            self._timer.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self._cancel()
        if self._stats is not None and self._start_time is not None:
            elapsed = time.monotonic() - self._start_time
            with getattr(self._stats, "_lock", threading.Lock()):
                self._stats.total_wait_seconds += elapsed
                if self._expired.is_set():
                    self._stats.timeouts_triggered += 1
        if self._expired.is_set():
            raise TimeoutExceeded(self._seconds, self._kind)

    def _on_expire(self) -> None:
        self._expired.set()
        logger.warning("Timeout of %.2fs exceeded (%s)", self._seconds, self._kind)

    def _cancel(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None


def with_timeout(
    seconds: float,
    kind: TimeoutKind = "call",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: enforce a wall-clock timeout on the wrapped function."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                with TimeoutContext(seconds, kind=kind) as ctx:
                    return await func(*args, **kwargs)
                # If ctx exits without raising but expired, re-raise.
                if ctx.expired:
                    raise TimeoutExceeded(seconds, kind)

            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            with TimeoutContext(seconds, kind=kind):
                return func(*args, **kwargs)

        return sync_wrapper

    return decorator


__all__ = [
    "TimeoutContext",
    "TimeoutExceeded",
    "TimeoutKind",
    "TimeoutPolicy",
    "TimeoutStats",
    "with_timeout",
]