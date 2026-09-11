"""Retry — exponential backoff retry decorator with multiple strategies."""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class RetryStrategy(StrEnum):
    """Retry delay calculation strategies."""

    FIXED = "fixed"                       # Constant delay between attempts
    LINEAR = "linear"                     # Delay grows linearly with attempt number
    EXPONENTIAL = "exponential"           # Delay doubles each attempt
    EXPONENTIAL_JITTER = "exponential_jitter"  # Exponential + random jitter


@dataclass
class RetryStats:
    """Aggregated retry statistics."""

    total_attempts: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    retries: int = 0
    last_attempt_at: float = 0.0
    exceptions_seen: dict[str, int] = field(default_factory=dict)


class RetryPolicy:
    """Configurable retry policy.

    Determines how long to wait between attempts and which exceptions
    should be considered retryable.
    """

    def __init__(
        self,
        max_attempts: int = 3,
        strategy: RetryStrategy = RetryStrategy.EXPONENTIAL_JITTER,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        jitter_factor: float = 0.1,
        retryable_exceptions: tuple[type[BaseException], ...] = (Exception,),
    ) -> None:
        self.max_attempts = max(1, max_attempts)
        self.strategy = strategy
        self.base_delay = max(0.0, base_delay)
        self.max_delay = max(self.base_delay, max_delay)
        self.jitter_factor = max(0.0, min(1.0, jitter_factor))
        self.retryable_exceptions = retryable_exceptions
        self._stats = RetryStats()
        self._lock = threading.Lock()

    def calculate_delay(self, attempt: int) -> float:
        """Compute delay before attempt N (attempt is 1-indexed)."""
        if attempt <= 0:
            return 0.0
        raw = self._raw_delay(attempt)
        bounded = min(raw, self.max_delay)
        if self.strategy == RetryStrategy.EXPONENTIAL_JITTER:
            jitter_range = bounded * self.jitter_factor
            bounded = bounded + random.uniform(-jitter_range, jitter_range)
        return max(0.0, bounded)

    def _raw_delay(self, attempt: int) -> float:
        if self.strategy == RetryStrategy.FIXED:
            return self.base_delay
        if self.strategy == RetryStrategy.LINEAR:
            return self.base_delay * attempt
        return self.base_delay * (2 ** (attempt - 1))

    def is_retryable(self, exception: BaseException) -> bool:
        """Return True if the exception should trigger a retry."""
        return isinstance(exception, self.retryable_exceptions)

    def record_attempt(
        self, success: bool, exception: BaseException | None = None
    ) -> None:
        with self._lock:
            self._stats.total_attempts += 1
            self._stats.last_attempt_at = time.time()
            if success:
                self._stats.successful_calls += 1
            else:
                self._stats.failed_calls += 1
                if exception is not None:
                    name = type(exception).__name__
                    self._stats.exceptions_seen[name] = (
                        self._stats.exceptions_seen.get(name, 0) + 1
                    )

    def record_retry(self) -> None:
        with self._lock:
            self._stats.retries += 1

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "total_attempts": self._stats.total_attempts,
                "successful_calls": self._stats.successful_calls,
                "failed_calls": self._stats.failed_calls,
                "retries": self._stats.retries,
                "last_attempt_at": self._stats.last_attempt_at,
                "exceptions_seen": dict(self._stats.exceptions_seen),
            }


def _sleep(delay: float) -> None:
    if delay > 0:
        time.sleep(delay)


async def _async_sleep(delay: float) -> None:
    if delay > 0:
        await asyncio.sleep(delay)


def retry(
    max_attempts: int = 3,
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL_JITTER,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter_factor: float = 0.1,
    retryable_exceptions: tuple[type[BaseException], ...] = (Exception,),
    on_retry: Callable[[int, BaseException], None] | None = None,
    policy: RetryPolicy | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator factory wrapping a function with retry behavior.

    Works for both sync and async functions. Async detection via
    ``inspect.iscoroutinefunction``.
    """
    policy = policy or RetryPolicy(
        max_attempts=max_attempts,
        strategy=strategy,
        base_delay=base_delay,
        max_delay=max_delay,
        jitter_factor=jitter_factor,
        retryable_exceptions=retryable_exceptions,
    )

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                last_exc: BaseException | None = None
                for attempt in range(1, policy.max_attempts + 1):
                    try:
                        result = await func(*args, **kwargs)
                        policy.record_attempt(success=True)
                        return result
                    except BaseException as exc:
                        last_exc = exc
                        policy.record_attempt(success=False, exception=exc)
                        if not policy.is_retryable(exc):
                            raise
                        if attempt >= policy.max_attempts:
                            break
                        if on_retry is not None:
                            try:
                                on_retry(attempt, exc)
                            except Exception:  # noqa: BLE001
                                logger.exception("on_retry callback raised")
                        policy.record_retry()
                        await _async_sleep(policy.calculate_delay(attempt))
                assert last_exc is not None
                raise last_exc

            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: BaseException | None = None
            for attempt in range(1, policy.max_attempts + 1):
                try:
                    result = func(*args, **kwargs)
                    policy.record_attempt(success=True)
                    return result
                except BaseException as exc:
                    last_exc = exc
                    policy.record_attempt(success=False, exception=exc)
                    if not policy.is_retryable(exc):
                        raise
                    if attempt >= policy.max_attempts:
                        break
                    if on_retry is not None:
                        try:
                            on_retry(attempt, exc)
                        except Exception:  # noqa: BLE001
                            logger.exception("on_retry callback raised")
                    policy.record_retry()
                    _sleep(policy.calculate_delay(attempt))
            assert last_exc is not None
            raise last_exc

        sync_wrapper.retry_policy = policy  # type: ignore[attr-defined]
        return sync_wrapper

    return decorator


__all__ = [
    "RetryPolicy",
    "RetryStats",
    "RetryStrategy",
    "retry",
]