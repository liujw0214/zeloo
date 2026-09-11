"""Unit tests for agent.task_compactor.

Covers:
- TaskCompactor default and custom cache_dir initialisation
- compact_tool_output() truncation with heuristics
- compact_tool_output() cache-hit short-circuit
- get_cache_key() stability across runs
- evict_cache_older_than() expiry purge
- get_stats() aggregate counters
- _apply_tool_specific search / log trim branches
- CompactionRecord / CompactorStats dataclasses
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from agent.task_compactor import (
    CompactionRecord,
    CompactorStats,
    TaskCompactor,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def compactor(tmp_path: Path) -> TaskCompactor:
    return TaskCompactor(
        max_output_tokens=200,
        similarity_threshold=0.85,
        cache_dir=tmp_path / "compact_cache",
    )


@pytest.fixture
def long_text() -> str:
    """~5 KB of text to exercise head/tail truncation."""
    return ("line of text that repeats. " * 200)


# ── Init ──────────────────────────────────────────────────────────────


class TestInit:
    def test_default(self, tmp_path: Path) -> None:
        # Redirect the default cache dir under tmp_path to avoid touching HOME.
        compactor = TaskCompactor(cache_dir=tmp_path / "default_cache")
        assert compactor.max_output_tokens == 400
        assert compactor.similarity_threshold == 0.85
        assert compactor.cache_dir.exists()

    def test_custom(self, tmp_path: Path) -> None:
        compactor = TaskCompactor(
            max_output_tokens=128,
            cache_dir=tmp_path / "x",
            similarity_threshold=0.7,
        )
        assert compactor.max_output_tokens == 128
        assert compactor.similarity_threshold == 0.7
        assert compactor.cache_dir == tmp_path / "x"


# ── get_cache_key ─────────────────────────────────────────────────────


class TestGetCacheKey:
    def test_stability(self, compactor: TaskCompactor) -> None:
        k1 = compactor.get_cache_key("search", "hello world")
        k2 = compactor.get_cache_key("search", "hello world")
        assert k1 == k2
        assert len(k1) == 32  # hex prefix

    def test_different_outputs(self, compactor: TaskCompactor) -> None:
        a = compactor.get_cache_key("search", "alpha")
        b = compactor.get_cache_key("search", "beta")
        assert a != b

    def test_different_tools(self, compactor: TaskCompactor) -> None:
        a = compactor.get_cache_key("tool_a", "same")
        b = compactor.get_cache_key("tool_b", "same")
        assert a != b


# ── compact_tool_output ───────────────────────────────────────────────


class TestCompactToolOutput:
    def test_empty_input_returns_empty(self, compactor: TaskCompactor) -> None:
        assert compactor.compact_tool_output("any", "") == ""

    def test_truncates_long_output(self, compactor: TaskCompactor, long_text: str) -> None:
        out = compactor.compact_tool_output("generic", long_text)
        # Head/tail heuristic should insert a compaction marker.
        assert "[... compacted" in out
        # Length should be significantly shorter than original.
        assert len(out) < len(long_text)

    def test_short_output_unchanged(self, compactor: TaskCompactor) -> None:
        short = "hello world\n\n"
        out = compactor.compact_tool_output("generic", short)
        # Whitespace normalised (collapsed blank lines) but no truncation marker.
        assert out == "hello world\n"
        assert "[... compacted" not in out

    def test_cache_hit_increments_counter(self, compactor: TaskCompactor) -> None:
        text = "some moderately long output " * 30
        first = compactor.compact_tool_output("generic", text)
        second = compactor.compact_tool_output("generic", text)
        assert first == second
        stats = compactor.get_stats()
        assert stats["hits"] >= 1
        assert stats["lookups"] >= 2

    def test_explicit_cache_key_reuse(self, compactor: TaskCompactor) -> None:
        text = "another verbose output " * 25
        key = compactor.get_cache_key("search", text)
        compactor.compact_tool_output("search", text, cache_key=key)
        # Same key, same tool — should hit cache.
        out = compactor.compact_tool_output("search", text, cache_key=key)
        assert out
        assert compactor.get_stats()["hits"] >= 1

    def test_search_tool_dedup(self, compactor: TaskCompactor) -> None:
        text = "alpha\nalpha\nbeta\nalpha\ngamma\n"
        out = compactor.compact_tool_output("search", text)
        # Duplicates should be removed.
        assert "alpha" in out
        # Unique-line count appears once per line after dedup.
        assert out.count("alpha") == 1

    def test_log_tool_truncates_head(self, compactor: TaskCompactor) -> None:
        text = "earlier entry\n" * 200 + "LATEST_EVENT"
        out = compactor.compact_tool_output("log_reader", text)
        assert "earlier log entries omitted" in out
        assert "LATEST_EVENT" in out


# ── evict_cache_older_than ─────────────────────────────────────────────


class TestEvictCache:
    def test_recent_entries_kept(self, compactor: TaskCompactor) -> None:
        compactor.compact_tool_output("a", "hello")
        evicted = compactor.evict_cache_older_than(days=7)
        assert evicted == 0
        assert compactor.get_stats()["cache_entries"] >= 1

    def test_old_entries_purged(self, compactor: TaskCompactor) -> None:
        compactor.compact_tool_output("a", "first")
        # Force timestamps into the past.
        for record in compactor._cache.values():
            record.compressed_at = time.time() - 30 * 86400
        evicted = compactor.evict_cache_older_than(days=7)
        assert evicted >= 1
        assert compactor.get_stats()["cache_entries"] == 0


# ── get_stats ─────────────────────────────────────────────────────────


class TestGetStats:
    def test_initial_stats(self, compactor: TaskCompactor) -> None:
        stats = compactor.get_stats()
        assert stats["lookups"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["cache_entries"] == 0
        assert stats["hit_rate"] == 0.0

    def test_after_operations(self, compactor: TaskCompactor) -> None:
        text = "some output text " * 50
        compactor.compact_tool_output("a", text)
        compactor.compact_tool_output("a", text)  # hit
        stats = compactor.get_stats()
        assert stats["lookups"] == 2
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["cache_entries"] == 1


# ── Dataclass round-trip ──────────────────────────────────────────────


class TestDataclasses:
    def test_compaction_record_roundtrip(self) -> None:
        record = CompactionRecord(
            cache_key="k", tool_name="tool", original_chars=100,
            compacted_chars=50, compressed_at=1.23, hits=3,
        )
        restored = CompactionRecord.from_dict(record.to_dict())
        assert restored.cache_key == "k"
        assert restored.hits == 3

    def test_compactor_stats_properties(self) -> None:
        s = CompactorStats(lookups=4, hits=1, misses=3, original_chars=200, compacted_chars=80)
        assert s.hit_rate == 0.25
        assert s.compression_ratio == 0.4
        d = s.to_dict()
        assert d["hit_rate"] == 0.25
        assert d["compression_ratio"] == 0.4