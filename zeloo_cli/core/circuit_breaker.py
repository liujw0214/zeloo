"""Circuit breaker — resilient service call protection."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class CircuitState(StrEnum):
    """Circuit breaker states."""

    CLOSED = "closed"          # Normal operation
    OPEN = "open"              # Blocking requests
    HALF_OPEN = "half_open"    # Testing recovery


@dataclass
class CircuitStats:
    """Circuit breaker statistics."""

    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0
    consecutive_failures: int = 0
    last_failure_at: float = 0.0
    last_state_change_at: float = field(default_factory=time.time)


class CircuitBreakerOpen(Exception):
    """Raised when circuit is open."""


class CircuitBreaker:
    """Circuit breaker for protecting downstream services.

    States:
    - CLOSED: All requests pass through
    - OPEN: All requests are rejected (service assumed down)
    - HALF_OPEN: Single test request allowed to check recovery

    Auto-transitions:
    - CLOSED → OPEN: after N consecutive failures
    - OPEN → HALF_OPEN: after recovery_timeout_seconds
    - HALF_OPEN → CLOSED: on first success
    - HALF_OPEN → OPEN: on failure
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout_seconds: float = 30.0,
        success_threshold: int = 2,
        expected_exceptions: tuple[type[BaseException], ...] = (Exception,),
    ) -> None:
        self.name = name
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout_seconds
        self._success_threshold = success_threshold
        self._expected_exceptions = expected_exceptions

        self._state = CircuitState.CLOSED
        self._stats = CircuitStats()
        self._half_open_success_count = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._state

    @property
    def stats(self) -> CircuitStats:
        with self._lock:
            return self._stats

    def call(
        self, func: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any:
        """Execute function through circuit breaker."""
        if not self._allow_request():
            with self._lock:
                self._stats.rejected_calls += 1
            raise CircuitBreakerOpen(
                f"Circuit '{self.name}' is OPEN"
            )

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except self._expected_exceptions as e:
            self._on_failure()
            raise e

    def _allow_request(self) -> bool:
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return True
            if self._state == CircuitState.OPEN:
                if (
                    time.time() - self._stats.last_state_change_at
                    >= self._recovery_timeout
                ):
                    self._state = CircuitState.HALF_OPEN
                    self._stats.last_state_change_at = time.time()
                    self._half_open_success_count = 0
                    logger.info("Circuit %s → HALF_OPEN", self.name)
                    return True
                return False
            return True

    def _on_success(self) -> None:
        with self._lock:
            self._stats.total_calls += 1
            self._stats.successful_calls += 1
            self._stats.consecutive_failures = 0

            if self._state == CircuitState.HALF_OPEN:
                self._half_open_success_count += 1
                if self._half_open_success_count >= self._success_threshold:
                    self._state = CircuitState.CLOSED
                    self._stats.last_state_change_at = time.time()
                    logger.info("Circuit %s → CLOSED (recovered)", self.name)

    def _on_failure(self) -> None:
        with self._lock:
            self._stats.total_calls += 1
            self._stats.failed_calls += 1
            self._stats.consecutive_failures += 1
            self._stats.last_failure_at = time.time()

            if (
                self._state == CircuitState.HALF_OPEN
                or self._stats.consecutive_failures >= self._failure_threshold
            ):
                if self._state != CircuitState.OPEN:
                    self._state = CircuitState.OPEN
                    self._stats.last_state_change_at = time.time()
                    logger.warning(
                        "Circuit %s → OPEN (failures=%d)",
                        self.name, self._stats.consecutive_failures,
                    )

    def reset(self) -> None:
        """Manually reset the circuit breaker."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._stats = CircuitStats()
            self._half_open_success_count = 0
            logger.info("Circuit %s manually reset", self.name)


__all__ = ["CircuitBreaker", "CircuitBreakerOpen", "CircuitState", "CircuitStats"]