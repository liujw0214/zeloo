"""Rate limiter — token bucket and sliding window rate limiting."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class RateLimitStrategy(StrEnum):
    """Rate limiting strategies."""

    TOKEN_BUCKET = "token_bucket"
    SLIDING_WINDOW = "sliding_window"
    FIXED_WINDOW = "fixed_window"


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""

    allowed: bool
    remaining: int
    reset_at: float
    retry_after: float = 0.0


class RateLimiter:
    """Multi-strategy rate limiter.

    Supports:
    - Token bucket: refills at a constant rate
    - Sliding window: tracks individual request timestamps
    - Fixed window: counts requests in fixed time buckets
    """

    def __init__(
        self,
        capacity: int = 100,
        refill_rate: float = 10.0,
        strategy: RateLimitStrategy = RateLimitStrategy.TOKEN_BUCKET,
        window_seconds: float = 60.0,
    ) -> None:
        self._capacity = capacity
        self._refill_rate = refill_rate
        self._strategy = strategy
        self._window = window_seconds
        self._lock = threading.Lock()
        self._buckets: dict[str, dict[str, Any]] = {}

    def check(
        self,
        key: str = "default",
        cost: int = 1,
    ) -> RateLimitResult:
        """Check if a request should be allowed."""
        with self._lock:
            bucket = self._buckets.setdefault(key, self._new_bucket())
            if self._strategy == RateLimitStrategy.TOKEN_BUCKET:
                return self._check_token_bucket(bucket, cost)
            elif self._strategy == RateLimitStrategy.SLIDING_WINDOW:
                return self._check_sliding_window(bucket, cost)
            else:
                return self._check_fixed_window(bucket, cost)

    def try_acquire(self, key: str = "default", cost: int = 1) -> bool:
        """Try to acquire tokens. Returns True if allowed."""
        return self.check(key, cost).allowed

    def reset(self, key: str = "default") -> None:
        with self._lock:
            self._buckets.pop(key, None)

    def _new_bucket(self) -> dict[str, Any]:
        if self._strategy == RateLimitStrategy.TOKEN_BUCKET:
            return {"tokens": float(self._capacity), "last_refill": time.time()}
        elif self._strategy == RateLimitStrategy.SLIDING_WINDOW:
            return {"timestamps": []}
        else:
            return {"window_start": time.time(), "count": 0}

    def _check_token_bucket(
        self, bucket: dict[str, Any], cost: int
    ) -> RateLimitResult:
        now = time.time()
        elapsed = now - bucket["last_refill"]
        new_tokens = min(
            self._capacity,
            bucket["tokens"] + elapsed * self._refill_rate,
        )
        bucket["last_refill"] = now

        if new_tokens >= cost:
            bucket["tokens"] = new_tokens - cost
            return RateLimitResult(
                allowed=True,
                remaining=int(bucket["tokens"]),
                reset_at=now + (self._capacity - bucket["tokens"]) / self._refill_rate,
            )
        else:
            retry_after = (cost - new_tokens) / self._refill_rate
            bucket["tokens"] = new_tokens
            return RateLimitResult(
                allowed=False,
                remaining=int(new_tokens),
                reset_at=now + retry_after,
                retry_after=retry_after,
            )

    def _check_sliding_window(
        self, bucket: dict[str, Any], cost: int
    ) -> RateLimitResult:
        now = time.time()
        window_start = now - self._window
        timestamps = [t for t in bucket["timestamps"] if t > window_start]
        bucket["timestamps"] = timestamps

        if len(timestamps) + cost <= self._capacity:
            for _ in range(cost):
                bucket["timestamps"].append(now)
            return RateLimitResult(
                allowed=True,
                remaining=self._capacity - len(bucket["timestamps"]),
                reset_at=timestamps[0] + self._window if timestamps else now + self._window,
            )
        else:
            retry_after = max(0, timestamps[0] + self._window - now)
            return RateLimitResult(
                allowed=False,
                remaining=0,
                reset_at=timestamps[0] + self._window,
                retry_after=retry_after,
            )

    def _check_fixed_window(
        self, bucket: dict[str, Any], cost: int
    ) -> RateLimitResult:
        now = time.time()
        if now - bucket["window_start"] >= self._window:
            bucket["window_start"] = now
            bucket["count"] = 0

        if bucket["count"] + cost <= self._capacity:
            bucket["count"] += cost
            return RateLimitResult(
                allowed=True,
                remaining=self._capacity - bucket["count"],
                reset_at=bucket["window_start"] + self._window,
            )
        else:
            retry_after = bucket["window_start"] + self._window - now
            return RateLimitResult(
                allowed=False,
                remaining=0,
                reset_at=bucket["window_start"] + self._window,
                retry_after=retry_after,
            )


__all__ = ["RateLimiter", "RateLimitResult", "RateLimitStrategy"]