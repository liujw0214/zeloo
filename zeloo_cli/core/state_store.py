"""State store — key-value persistence with TTL and atomic operations."""

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


@dataclass
class StateEntry:
    """A stored state entry."""

    key: str
    value: Any
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    expires_at: float | None = None
    version: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class StateStore:
    """Thread-safe in-memory state store with TTL and atomic ops.

    Supports:
    - TTL-based expiry
    - Optimistic concurrency control via version
    - Atomic compare-and-swap
    - JSON-serializable values
    - Snapshot/restore for backup
    """

    def __init__(self, default_ttl_seconds: float | None = None) -> None:
        self._store: dict[str, StateEntry] = {}
        self._lock = threading.RLock()
        self._default_ttl = default_ttl_seconds
        self._change_listeners: list[Callable[[str, Any, Any], None]] = []

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return default
            if entry.expires_at is not None and time.time() > entry.expires_at:
                del self._store[key]
                return default
            return entry.value

    def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Set a value."""
        with self._lock:
            old = self._store.get(key)
            old_value = old.value if old else None
            ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
            entry = StateEntry(
                key=key,
                value=value,
                expires_at=time.time() + ttl if ttl else None,
                version=(old.version + 1) if old else 1,
                metadata=metadata or {},
            )
            self._store[key] = entry
            self._notify(key, old_value, value)

    def delete(self, key: str) -> bool:
        with self._lock:
            entry = self._store.pop(key, None)
            if entry is not None:
                self._notify(key, entry.value, None)
            return entry is not None

    def has(self, key: str) -> bool:
        with self._lock:
            return key in self._store

    def keys(self) -> list[str]:
        with self._lock:
            now = time.time()
            return [
                k for k, v in self._store.items()
                if v.expires_at is None or v.expires_at > now
            ]

    def expire(self, key: str, ttl_seconds: float) -> bool:
        """Set TTL on an existing key."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return False
            entry.expires_at = time.time() + ttl_seconds
        return True

    def compare_and_swap(
        self,
        key: str,
        expected_value: Any,
        new_value: Any,
        expected_version: int | None = None,
    ) -> bool:
        """Atomically update if value/version matches expected."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                if expected_value is None:
                    self.set(key, new_value)
                    return True
                return False
            if expected_version is not None and entry.version != expected_version:
                return False
            if entry.value != expected_value:
                return False
            old_value = entry.value
            entry.value = new_value
            entry.updated_at = time.time()
            entry.version += 1
            self._notify(key, old_value, new_value)
        return True

    def get_with_version(self, key: str) -> tuple[Any, int] | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if entry.expires_at is not None and time.time() > entry.expires_at:
                del self._store[key]
                return None
            return entry.value, entry.version

    def add_change_listener(
        self, listener: Callable[[str, Any, Any], None]
    ) -> None:
        self._change_listeners.append(listener)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                key: {
                    "value": entry.value,
                    "created_at": entry.created_at,
                    "updated_at": entry.updated_at,
                    "expires_at": entry.expires_at,
                    "version": entry.version,
                }
                for key, entry in self._store.items()
            }

    def restore(self, snapshot_data: dict[str, Any]) -> None:
        with self._lock:
            for key, data in snapshot_data.items():
                self._store[key] = StateEntry(
                    key=key,
                    value=data["value"],
                    created_at=data.get("created_at", time.time()),
                    updated_at=data.get("updated_at", time.time()),
                    expires_at=data.get("expires_at"),
                    version=data.get("version", 1),
                )

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def size(self) -> int:
        with self._lock:
            now = time.time()
            return sum(
                1 for v in self._store.values()
                if v.expires_at is None or v.expires_at > now
            )

    def cleanup_expired(self) -> int:
        now = time.time()
        removed = 0
        with self._lock:
            expired_keys = [
                k for k, v in self._store.items()
                if v.expires_at is not None and v.expires_at <= now
            ]
            for k in expired_keys:
                del self._store[k]
                removed += 1
        return removed

    def _notify(self, key: str, old: Any, new: Any) -> None:
        for listener in self._change_listeners:
            try:
                listener(key, old, new)
            except Exception as e:
                logger.warning("State change listener error: %s", e)


__all__ = ["StateStore", "StateEntry"]