"""Tests for zeloo_cli.core.cache."""

from __future__ import annotations

import threading
import time

from zeloo_cli.core.cache import Cache, TTLCache


class TestTTLCache:
    def test_set_and_get(self) -> None:
        c = TTLCache(default_ttl_seconds=60.0)
        c.set("k", "v")
        assert c.get("k") == "v"

    def test_missing_key_returns_default(self) -> None:
        c = TTLCache()
        assert c.get("missing", default="x") == "x"
        assert c.get("missing") is None

    def test_expired_returns_default(self) -> None:
        c = TTLCache(default_ttl_seconds=0.05)
        c.set("k", "v")
        time.sleep(0.1)
        assert c.get("k") is None

    def test_delete(self) -> None:
        c = TTLCache()
        c.set("k", "v")
        assert c.delete("k") is True
        assert c.get("k") is None
        assert c.delete("k") is False

    def test_cleanup_expired_removes_only_expired(self) -> None:
        c = TTLCache(default_ttl_seconds=0.05)
        c.set("a", 1)
        time.sleep(0.1)
        c.set("b", 2)
        removed = c.cleanup_expired()
        assert removed == 1
        assert c.get("b") == 2


class TestLRUCache:
    def test_set_and_get(self) -> None:
        c = Cache(max_size=10)
        c.set("k", "v")
        assert c.get("k") == "v"

    def test_lru_eviction(self) -> None:
        c = Cache(max_size=2)
        c.set("a", 1)
        c.set("b", 2)
        c.get("a")  # a becomes most-recently-used
        c.set("c", 3)  # evicts "b" (LRU)
        assert c.get("b") is None
        assert c.get("a") == 1
        assert c.get("c") == 3

    def test_update_existing_key_no_eviction(self) -> None:
        """Updating an existing key must not evict another entry."""
        c = Cache(max_size=2)
        c.set("a", 1)
        c.set("b", 2)
        c.set("a", 10)  # update, no eviction
        assert c.size() == 2
        assert c.get("a") == 10
        assert c.get("b") == 2

    def test_expiration_increments_expirations(self) -> None:
        c = Cache(max_size=10, default_ttl_seconds=0.05)
        c.set("k", "v")
        time.sleep(0.1)
        assert c.get("k") is None
        assert c.stats()["expirations"] == 1

    def test_miss_increments_misses(self) -> None:
        c = Cache()
        c.get("absent")
        c.get("absent2")
        assert c.stats()["misses"] == 2

    def test_hit_rate_calculation(self) -> None:
        c = Cache()
        c.set("k", "v")
        c.get("k")  # hit
        c.get("k")  # hit
        c.get("n")  # miss
        stats = c.stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert abs(stats["hit_rate"] - 2 / 3) < 1e-9

    def test_hit_rate_zero_when_no_requests(self) -> None:
        c = Cache()
        assert c.stats()["hit_rate"] == 0.0

    def test_get_or_compute_calls_compute_on_miss(self) -> None:
        c = Cache()
        calls = []

        def compute() -> int:
            calls.append(1)
            return 42

        assert c.get_or_compute("k", compute) == 42
        assert len(calls) == 1
        # Second call hits the cache — compute is NOT invoked again.
        assert c.get_or_compute("k", compute) == 42
        assert len(calls) == 1

    def test_get_or_compute_caches_falsy_none(self) -> None:
        """Regression: previously, a cached ``None`` was re-computed forever."""
        c = Cache()
        calls = []

        def compute() -> None:
            calls.append(1)
            return None

        assert c.get_or_compute("k", compute) is None
        assert c.get_or_compute("k", compute) is None
        assert len(calls) == 1, "compute must run exactly once even though value is None"

    def test_get_or_compute_caches_zero_and_empty_string(self) -> None:
        """All falsy values must be cached, not re-computed."""
        c = Cache()
        zero_calls = []
        assert c.get_or_compute("zero", lambda: (zero_calls.append(1) or 0)) == 0
        assert c.get_or_compute("zero", lambda: (zero_calls.append(1) or 0)) == 0
        assert len(zero_calls) == 1

        empty_calls = []
        assert c.get_or_compute("empty", lambda: (empty_calls.append(1) or "")) == ""
        assert c.get_or_compute("empty", lambda: (empty_calls.append(1) or "")) == ""
        assert len(empty_calls) == 1

    def test_get_or_compute_ttl_respected(self) -> None:
        c = Cache(default_ttl_seconds=0.05)
        calls = []

        def compute() -> str:
            calls.append(1)
            return "v"

        c.get_or_compute("k", compute)
        time.sleep(0.1)
        c.get_or_compute("k", compute)
        assert len(calls) == 2

    def test_concurrent_get_or_compute(self) -> None:
        """Concurrent miss for the same key must not run compute twice
        within the locked set call — though strict singleflight is not
        guaranteed here. The looser invariant we test is that compute
        runs *at least* once and the cached value is consistent.
        """
        c = Cache()
        calls = []
        lock = threading.Lock()

        def compute() -> str:
            with lock:
                calls.append(1)
            return "v"

        threads = [
            threading.Thread(target=lambda: c.get_or_compute("k", compute))
            for _ in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # At minimum one call ran and everyone got the same value.
        assert len(calls) >= 1
        assert c.get("k") == "v"

    def test_clear(self) -> None:
        c = Cache(max_size=10)
        c.set("a", 1)
        c.set("b", 2)
        c.clear()
        assert c.size() == 0
        assert c.get("a") is None