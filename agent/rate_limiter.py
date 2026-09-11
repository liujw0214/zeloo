"""Adaptive rate limiter — token bucket with per-error backoff.

Combines a classic :class:`TokenBucket` (refill at a steady rate) with
adaptive behavior driven by :mod:`agent.error_classifier`. When errors
are observed, the limiter:

* **RATE_LIMIT**  — multiply *current_rate* by 0.5 (or honor Retry-After)
* **SERVER_ERROR** — multiply by 0.7
* **AUTH** — raise :class:`AuthCircuitOpen` immediately (no point retrying)
* **TIMEOUT** — multiply by 0.85
* **Success** — gradually ramp back up (× 1.02 per success, capped at base)

The limiter is thread-safe and supports per-key buckets (e.g. per
provider) via :meth:`get_bucket`.

Usage::

    limiter = AdaptiveRateLimiter(base_rate=10.0)  # 10 req/sec
    bucket = limiter.get_bucket("openai")
    if not bucket.try_acquire():
        time.sleep(bucket.retry_after())
        ...
    try:
        call_provider()
        bucket.record_success()
    except Exception as exc:
        from agent.error_classifier import classify_error
        classification = classify_error(exc, provider="openai")
        bucket.record_error(classification)
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.error_classifier import ErrorClassification


logger = logging.getLogger(__name__)


class AuthCircuitOpen(Exception):
    """Raised when the auth circuit is open (repeated credential failures)."""

    def __init__(self, provider: str, failures: int) -> None:
        super().__init__(
            f"Auth circuit open for '{provider}' after {failures} failure(s)"
        )
        self.provider = provider
        self.failures = failures


@dataclass
class TokenBucket:
    """A single token bucket with adaptive rate adjustment.

    Tokens refill at ``current_rate`` per second, up to ``capacity``.
    Acquire is non-blocking; when tokens run out, callers should sleep
    :meth:`retry_after` before retrying.
    """

    name: str = "default"
    base_rate: float = 10.0  # tokens / second
    capacity: float = 20.0
    current_rate: float = 10.0
    tokens: float = 20.0
    last_refill: float = field(default_factory=time.time)

    # Adaptive state
    auth_failures: int = 0
    consecutive_successes: int = 0
    cooldown_until: float = 0.0
    total_acquired: int = 0
    total_throttled: int = 0

    def _refill(self) -> None:
        """Refill tokens based on time elapsed since last refill."""
        now = time.time()
        elapsed = now - self.last_refill
        if elapsed > 0:
            self.tokens = min(self.capacity, self.tokens + elapsed * self.current_rate)
            self.last_refill = now

    def try_acquire(self, cost: float = 1.0) -> bool:
        """Attempt to take *cost* tokens without blocking.

        Returns True if the request should proceed, False if it should
        be throttled (caller should sleep :meth:`retry_after` and
        retry).
        """
        self._refill()
        if self.tokens >= cost and time.time() >= self.cooldown_until:
            self.tokens -= cost
            self.total_acquired += 1
            return True
        self.total_throttled += 1
        return False

    def retry_after(self, cost: float = 1.0) -> float:
        """Seconds to wait before a throttled request can succeed."""
        self._refill()
        if self.tokens >= cost:
            return 0.0
        deficit = cost - self.tokens
        rate = max(self.current_rate, 0.001)
        return deficit / rate

    def record_success(self) -> None:
        """Note a successful request; gradually ramp up rate toward base."""
        self.consecutive_successes += 1
        # Ramp up by 2% per success, cap at base_rate.
        if self.consecutive_successes >= 5 and self.current_rate < self.base_rate:
            self.current_rate = min(self.base_rate, self.current_rate * 1.02)
            self.consecutive_successes = 0

    def record_error(self, classification: ErrorClassification) -> None:
        """Apply backoff based on the error classification.

        For AUTH errors: the first failure freezes the rate at zero and
        records a warning; the second failure trips the circuit and
        raises :class:`AuthCircuitOpen`. The previous implementation
        silently set ``current_rate = 0`` on the first failure (without
        raising), leaving callers to discover the dead key on their
        next ``try_acquire`` call — slow and confusing.
        """
        from agent.error_classifier import ErrorCategory

        cat = classification.category
        if cat == ErrorCategory.AUTH:
            self.auth_failures += 1
            if self.auth_failures >= 2:
                logger.warning(
                    "Auth circuit tripped for '%s' after %d failures",
                    self.name,
                    self.auth_failures,
                )
                raise AuthCircuitOpen(self.name, self.auth_failures)
            # First AUTH failure: freeze the rate at zero AND drain
            # remaining tokens so the next ``try_acquire()`` immediately
            # fails fast. Do NOT raise — the caller may still have a
            # backup credential in the pool.
            logger.warning(
                "Auth failure on '%s' (%d/2) — rate frozen at 0",
                self.name,
                self.auth_failures,
            )
            self.current_rate = 0.0
            self.tokens = 0.0
            self.consecutive_successes = 0
        elif cat == ErrorCategory.RATE_LIMIT:
            retry_after = classification.retry_delay_seconds
            self.cooldown_until = max(
                self.cooldown_until, time.time() + retry_after
            )
            self.current_rate = max(0.1, self.current_rate * 0.5)
            self.consecutive_successes = 0
        elif cat == ErrorCategory.SERVER_ERROR:
            self.current_rate = max(0.1, self.current_rate * 0.7)
            self.consecutive_successes = 0
        elif cat == ErrorCategory.TIMEOUT:
            self.current_rate = max(0.1, self.current_rate * 0.85)
            self.consecutive_successes = 0
        else:
            # Mild backoff for unclassified errors.
            self.current_rate = max(0.1, self.current_rate * 0.95)
            self.consecutive_successes = 0

    def reset(self) -> None:
        """Reset the bucket to its base configuration."""
        self.current_rate = self.base_rate
        self.tokens = self.capacity
        self.auth_failures = 0
        self.consecutive_successes = 0
        self.cooldown_until = 0.0
        self.last_refill = time.time()

    def stats(self) -> dict[str, Any]:
        """Return a snapshot of bucket state for diagnostics."""
        return {
            "name": self.name,
            "current_rate": round(self.current_rate, 3),
            "base_rate": self.base_rate,
            "tokens": round(self.tokens, 3),
            "capacity": self.capacity,
            "auth_failures": self.auth_failures,
            "cooldown_remaining": max(0.0, self.cooldown_until - time.time()),
            "total_acquired": self.total_acquired,
            "total_throttled": self.total_throttled,
        }


# from typing import Any  (above) imported for clarity below
from typing import Any  # noqa: E402


class AdaptiveRateLimiter:
    """Per-key token bucket pool with adaptive error backoff."""

    def __init__(self, base_rate: float = 10.0, capacity: float = 20.0) -> None:
        self._base_rate = base_rate
        self._capacity = capacity
        self._lock = threading.Lock()
        self._buckets: dict[str, TokenBucket] = {}

    def get_bucket(self, key: str) -> TokenBucket:
        """Return the bucket for *key*, creating it lazily."""
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = TokenBucket(
                    name=key,
                    base_rate=self._base_rate,
                    capacity=self._capacity,
                    current_rate=self._base_rate,
                    tokens=self._capacity,
                )
                self._buckets[key] = bucket
            return bucket

    def reset_all(self) -> None:
        """Reset every bucket to its base configuration."""
        with self._lock:
            for b in self._buckets.values():
                b.reset()

    def stats(self) -> dict[str, dict[str, Any]]:
        """Return stats for all buckets keyed by name."""
        with self._lock:
            return {name: b.stats() for name, b in self._buckets.items()}

    def try_call(
        self,
        key: str,
        classification_provider: str | None = None,
    ) -> bool:
        """Acquire one token from the *key* bucket (convenience method)."""
        return self.get_bucket(key).try_acquire()

    def wait_and_acquire(self, key: str, max_wait: float = 60.0) -> bool:
        """Block up to *max_wait* seconds for an available token.

        Returns True if a token was acquired, False if the wait timed out.
        """
        bucket = self.get_bucket(key)
        deadline = time.time() + max_wait
        while True:
            if bucket.try_acquire():
                return True
            sleep_for = min(bucket.retry_after(), deadline - time.time())
            if sleep_for <= 0:
                return False
            time.sleep(sleep_for)