"""Cache layer — TTL + LRU caching primitives."""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# Sentinel object used by ``Cache.get_or_compute`` so a cached ``None`` is
# not indistinguishable from a real cache miss. Never exposed to callers.
_MISS_SENTINEL = object()


@dataclass
class CacheEntry:
    """Single cache entry with TTL."""

    key: str
    value: Any
    expires_at: float
    created_at: float = field(default_factory=time.time)
    hits: int = 0

    def is_expired(self) -> bool:
        return time.time() >= self.expires_at


class TTLCache:
    """Simple TTL cache (no eviction)."""

    def __init__(self, default_ttl_seconds: float = 300.0) -> None:
        self._entries: dict[str, CacheEntry] = {}
        self._default_ttl = default_ttl_seconds
        self._lock = threading.Lock()

    def set(self, key: str, value: Any, ttl_seconds: float | None = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        with self._lock:
            self._entries[key] = CacheEntry(
                key=key,
                value=value,
                expires_at=time.time() + ttl,
            )

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return default
            if entry.is_expired():
                del self._entries[key]
                return default
            entry.hits += 1
            return entry.value

    def delete(self, key: str) -> bool:
        with self._lock:
            return self._entries.pop(key, None) is not None

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._entries)

    def cleanup_expired(self) -> int:
        now = time.time()
        removed = 0
        with self._lock:
            expired_keys = [k for k, v in self._entries.items() if v.expires_at <= now]
            for k in expired_keys:
                del self._entries[k]
                removed += 1
        return removed


class Cache:
    """LRU + TTL cache with statistics."""

    def __init__(
        self,
        max_size: int = 1000,
        default_ttl_seconds: float = 300.0,
    ) -> None:
        self._max_size = max_size
        self._default_ttl = default_ttl_seconds
        self._entries: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return default
            if entry.is_expired():
                del self._entries[key]
                self._expirations += 1
                self._misses += 1
                return default
            entry.hits += 1
            self._hits += 1
            self._entries.move_to_end(key)
            return entry.value

    def set(self, key: str, value: Any, ttl_seconds: float | None = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        with self._lock:
            if key in self._entries:
                del self._entries[key]
            elif len(self._entries) >= self._max_size:
                oldest_key = next(iter(self._entries))
                del self._entries[oldest_key]
                self._evictions += 1
            self._entries[key] = CacheEntry(
                key=key,
                value=value,
                expires_at=time.time() + ttl,
            )

    def delete(self, key: str) -> bool:
        with self._lock:
            return self._entries.pop(key, None) is not None

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._entries)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = (
                self._hits / total_requests
                if total_requests > 0 else 0.0
            )
            return {
                "size": len(self._entries),
                "max_size": self._max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": hit_rate,
                "evictions": self._evictions,
                "expirations": self._expirations,
            }

    def get_or_compute(
        self,
        key: str,
        compute_fn: Callable[[], Any],
        ttl_seconds: float | None = None,
    ) -> Any:
        # Use a per-call sentinel object so a cached ``None`` value (or any
        # other falsy value such as ``0``, ``""``, ``[]``) is not mistaken
        # for a cache miss and re-computed forever.
        sentinel = _MISS_SENTINEL
        value = self.get(key, default=sentinel)
        if value is sentinel:
            value = compute_fn()
            self.set(key, value, ttl_seconds)
        return value


__all__ = ["Cache", "CacheEntry", "TTLCache"]