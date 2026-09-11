"""Unit tests for agent.memory_compressor.

Covers:
- MemoryEntry dataclass construction & defaults
- CompressionStrategy enum values
- MemoryCompressor.compress (basic, threshold variants, strategy filters)
- MemoryCompressor.deduplicate (exact duplicates, similar content)
- compute_similarity & tfidf_similarity edge cases
- merge_similar across multi-entry clusters
- compress_to_summary length bound
- Module-level helpers (compress_memory_list, deduplicate_memory)
"""

from __future__ import annotations

from datetime import datetime, timedelta
import pytest

from agent.memory_compressor import (
    CompressionStrategy,
    MemoryCompressor,
    MemoryEntry,
    compress_memory_list,
    deduplicate_memory,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def compressor() -> MemoryCompressor:
    """Default compressor (HYBRID strategy)."""
    return MemoryCompressor()


@pytest.fixture
def tfidf_compressor() -> MemoryCompressor:
    return MemoryCompressor(strategy=CompressionStrategy.TFIDF)


@pytest.fixture
def base_time() -> datetime:
    return datetime(2026, 1, 1, 12, 0, 0)


@pytest.fixture
def sample_entries(base_time: datetime) -> list[MemoryEntry]:
    return [
        MemoryEntry(
            id="e1",
            content="The user prefers Python over JavaScript.",
            importance=0.9,
            timestamp=base_time,
            tags=["pref", "lang"],
        ),
        MemoryEntry(
            id="e2",
            content="The user prefers Python over JavaScript.",  # exact dup
            importance=0.8,
            timestamp=base_time + timedelta(minutes=5),
            tags=["lang"],
        ),
        MemoryEntry(
            id="e3",
            content="The weather in Beijing is sunny today.",
            importance=0.5,
            timestamp=base_time + timedelta(hours=1),
        ),
    ]


@pytest.fixture
def distinct_entries(base_time: datetime) -> list[MemoryEntry]:
    return [
        MemoryEntry(
            id=f"d{i}",
            content=f"Distinct fact number {i} about topic {i}.",
            importance=0.5,
            timestamp=base_time + timedelta(minutes=i),
        )
        for i in range(5)
    ]


# ── MemoryEntry dataclass ─────────────────────────────────────────────


class TestMemoryEntry:
    def test_construction_minimal(self) -> None:
        e = MemoryEntry(
            id="e1",
            content="hello world",
            importance=0.5,
            timestamp=datetime(2026, 1, 1),
        )
        assert e.id == "e1"
        assert e.content == "hello world"
        assert e.importance == 0.5

    def test_defaults(self) -> None:
        e = MemoryEntry(
            id="x",
            content="y",
            importance=0.5,
            timestamp=datetime(2026, 1, 1),
        )
        assert e.access_count == 0
        assert e.last_accessed is None
        assert e.tags == []

    def test_tags_propagate(self) -> None:
        e = MemoryEntry(
            id="x",
            content="y",
            importance=0.5,
            timestamp=datetime(2026, 1, 1),
            tags=["a", "b"],
        )
        assert e.tags == ["a", "b"]

    def test_access_count_set(self) -> None:
        e = MemoryEntry(
            id="x",
            content="y",
            importance=0.5,
            timestamp=datetime(2026, 1, 1),
            access_count=7,
        )
        assert e.access_count == 7


# ── CompressionStrategy enum ───────────────────────────────────────────


class TestCompressionStrategy:
    def test_tfidf_value(self) -> None:
        assert CompressionStrategy.TFIDF.value == "tfidf"

    def test_time_decay_value(self) -> None:
        assert CompressionStrategy.TIME_DECAY.value == "time_decay"

    def test_importance_value(self) -> None:
        assert CompressionStrategy.IMPORTANCE.value == "importance"

    def test_hybrid_value(self) -> None:
        assert CompressionStrategy.HYBRID.value == "hybrid"

    def test_enum_has_four_members(self) -> None:
        assert len(CompressionStrategy) == 4


# ── compress() ────────────────────────────────────────────────────────


class TestCompress:
    def test_compress_empty_list(
        self, compressor: MemoryCompressor
    ) -> None:
        assert compressor.compress([]) == []

    def test_compress_basic(
        self,
        compressor: MemoryCompressor,
        sample_entries: list[MemoryEntry],
    ) -> None:
        compressed = compressor.compress(sample_entries)
        # e1/e2 are exact duplicates — at most 2 unique pieces
        assert len(compressed) <= len(sample_entries)
        assert len(compressed) >= 1

    def test_compress_with_threshold(
        self,
        compressor: MemoryCompressor,
        sample_entries: list[MemoryEntry],
    ) -> None:
        out = compressor.compress(sample_entries, similarity_threshold=0.5)
        assert len(out) >= 1
        assert all(isinstance(e, MemoryEntry) for e in out)

    def test_compress_strategy_tfidf(
        self,
        tfidf_compressor: MemoryCompressor,
        sample_entries: list[MemoryEntry],
    ) -> None:
        out = tfidf_compressor.compress(sample_entries)
        assert isinstance(out, list)

    def test_compress_strategy_importance(
        self, sample_entries: list[MemoryEntry]
    ) -> None:
        c = MemoryCompressor(strategy=CompressionStrategy.IMPORTANCE)
        out = c.compress(sample_entries)
        # Importance sort keeps higher-importance entries first.
        importances = [e.importance for e in out]
        assert importances == sorted(importances, reverse=True)


# ── deduplicate() ─────────────────────────────────────────────────────


class TestDeduplicate:
    def test_deduplicate_exact_duplicates(
        self,
        compressor: MemoryCompressor,
        sample_entries: list[MemoryEntry],
    ) -> None:
        deduped = compressor.deduplicate(sample_entries)
        ids = {e.id for e in deduped}
        # e1 + e2 collapse into one; e3 is unique.
        assert len(deduped) == 2
        assert "e3" in ids
        assert ids & {"e1", "e2"}  # one of the dups survived

    def test_deduplicate_similar_but_not_equal(
        self, compressor: MemoryCompressor
    ) -> None:
        entries = [
            MemoryEntry(
                id="a",
                content="python is a great language",
                importance=0.6,
                timestamp=datetime(2026, 1, 1),
            ),
            MemoryEntry(
                id="b",
                content="python is a great language for data science",
                importance=0.7,
                timestamp=datetime(2026, 1, 2),
            ),
        ]
        deduped = compressor.deduplicate(entries)
        # deduplicate() removes *exact* duplicates only — both should survive.
        assert len(deduped) == 2

    def test_deduplicate_keeps_highest_importance(
        self, compressor: MemoryCompressor
    ) -> None:
        entries = [
            MemoryEntry(
                id="low",
                content="SAME",
                importance=0.3,
                timestamp=datetime(2026, 1, 1),
            ),
            MemoryEntry(
                id="high",
                content="same",
                importance=0.9,
                timestamp=datetime(2026, 1, 1),
            ),
        ]
        deduped = compressor.deduplicate(entries)
        assert len(deduped) == 1
        assert deduped[0].importance == 0.9

    def test_deduplicate_empty(self, compressor: MemoryCompressor) -> None:
        assert compressor.deduplicate([]) == []

    def test_deduplicate_aggregates_access_count(
        self, compressor: MemoryCompressor
    ) -> None:
        entries = [
            MemoryEntry(
                id="a",
                content="dup content",
                importance=0.5,
                timestamp=datetime(2026, 1, 1),
                access_count=2,
            ),
            MemoryEntry(
                id="b",
                content="dup content",
                importance=0.5,
                timestamp=datetime(2026, 1, 1),
                access_count=5,
            ),
        ]
        deduped = compressor.deduplicate(entries)
        assert deduped[0].access_count == 7


# ── compute_similarity() & tfidf_similarity() ─────────────────────────


class TestSimilarity:
    def test_compute_similarity_same_string(
        self, compressor: MemoryCompressor
    ) -> None:
        # Multi-token case goes through TF-IDF cosine → ≈1.0 (not exact due
        # to floating point). Single-token case uses the fast-path equality.
        sim = compressor.compute_similarity("hello world", "hello world")
        assert sim == pytest.approx(1.0, abs=1e-6)
        # Single-token fast-path returns exact 1.0.
        assert compressor.compute_similarity("python", "python") == 1.0

    def test_compute_similarity_different(
        self, compressor: MemoryCompressor
    ) -> None:
        sim = compressor.compute_similarity("hello there", "completely unrelated text")
        assert sim < 0.5

    def test_compute_similarity_empty_first(
        self, compressor: MemoryCompressor
    ) -> None:
        assert compressor.compute_similarity("", "hello") == 0.0

    def test_compute_similarity_empty_second(
        self, compressor: MemoryCompressor
    ) -> None:
        assert compressor.compute_similarity("hello", "") == 0.0

    def test_compute_similarity_both_empty(
        self, compressor: MemoryCompressor
    ) -> None:
        assert compressor.compute_similarity("", "") == 0.0

    def test_compute_similarity_single_token_match(
        self, compressor: MemoryCompressor
    ) -> None:
        # Single-token fast-path: identical tokens → 1.0.
        assert compressor.compute_similarity("python", "python") == 1.0

    def test_compute_similarity_single_token_mismatch(
        self, compressor: MemoryCompressor
    ) -> None:
        assert compressor.compute_similarity("python", "rust") == 0.0

    def test_tfidf_similarity_returns_in_range(
        self, compressor: MemoryCompressor
    ) -> None:
        sim = compressor.tfidf_similarity("Python is great", "Python is awesome")
        assert 0.0 <= sim <= 1.0

    def test_tfidf_similarity_identical(
        self, compressor: MemoryCompressor
    ) -> None:
        sim = compressor.tfidf_similarity("identical text", "identical text")
        assert sim == pytest.approx(1.0, abs=1e-6)

    def test_tfidf_similarity_empty(
        self, compressor: MemoryCompressor
    ) -> None:
        assert compressor.tfidf_similarity("", "hello") == 0.0


# ── merge_similar() ───────────────────────────────────────────────────


class TestMergeSimilar:
    def test_merge_similar_basic(
        self,
        compressor: MemoryCompressor,
        sample_entries: list[MemoryEntry],
    ) -> None:
        merged = compressor.merge_similar(sample_entries)
        assert len(merged) >= 1

    def test_merge_similar_singleton(
        self, compressor: MemoryCompressor
    ) -> None:
        entries = [
            MemoryEntry(
                id="x",
                content="lonely fact",
                importance=0.5,
                timestamp=datetime(2026, 1, 1),
            )
        ]
        merged = compressor.merge_similar(entries)
        assert len(merged) == 1

    def test_merge_similar_collapses_high_overlap(
        self, compressor: MemoryCompressor
    ) -> None:
        entries = [
            MemoryEntry(
                id="a",
                content="python is a great language for web backends",
                importance=0.6,
                timestamp=datetime(2026, 1, 1),
            ),
            MemoryEntry(
                id="b",
                content="python is a great language for web backends",
                importance=0.7,
                timestamp=datetime(2026, 1, 2),
            ),
        ]
        merged = compressor.merge_similar(entries)
        # Identical long content should collapse to one.
        assert len(merged) == 1


# ── compress_to_summary() ─────────────────────────────────────────────


class TestCompressToSummary:
    def test_summary_respects_max_length(
        self, compressor: MemoryCompressor
    ) -> None:
        entries = [
            MemoryEntry(
                id=f"e{i}",
                content="A" * 100,
                importance=0.9,
                timestamp=datetime(2026, 1, 1),
            )
            for i in range(5)
        ]
        summary = compressor.compress_to_summary(entries, max_length=50)
        assert len(summary) <= 50

    def test_summary_empty_input(self, compressor: MemoryCompressor) -> None:
        assert compressor.compress_to_summary([]) == ""

    def test_summary_contains_importance(
        self, compressor: MemoryCompressor
    ) -> None:
        entries = [
            MemoryEntry(
                id="e1",
                content="Important fact.",
                importance=0.9,
                timestamp=datetime(2026, 1, 1),
            )
        ]
        summary = compressor.compress_to_summary(entries, max_length=200)
        assert "0.90" in summary

    def test_summary_single_entry(
        self, compressor: MemoryCompressor
    ) -> None:
        entries = [
            MemoryEntry(
                id="only",
                content="Only fact",
                importance=0.5,
                timestamp=datetime(2026, 1, 1),
            )
        ]
        summary = compressor.compress_to_summary(entries)
        assert "Only fact" in summary


# ── Module-level helpers ──────────────────────────────────────────────


class TestHelperFunctions:
    def test_compress_memory_list_returns_list(self) -> None:
        entries = [
            {
                "id": "1",
                "content": "test fact",
                "importance": 0.5,
                "timestamp": "2026-01-01T00:00:00",
            }
        ]
        result = compress_memory_list(entries)
        assert isinstance(result, list)

    def test_compress_memory_list_collapses_duplicates(self) -> None:
        entries = [
            {
                "id": "1",
                "content": "duplicated fact",
                "importance": 0.5,
                "timestamp": "2026-01-01T00:00:00",
            },
            {
                "id": "2",
                "content": "duplicated fact",
                "importance": 0.5,
                "timestamp": "2026-01-01T00:00:00",
            },
        ]
        result = compress_memory_list(entries)
        assert len(result) == 1

    def test_deduplicate_memory_collapses(self) -> None:
        entries = [
            {"id": "1", "content": "dup"},
            {"id": "2", "content": "dup"},
        ]
        result = deduplicate_memory(entries)
        assert len(result) == 1

    def test_deduplicate_memory_keeps_unique(self) -> None:
        entries = [
            {"id": "1", "content": "fact one"},
            {"id": "2", "content": "fact two"},
            {"id": "3", "content": "fact one"},  # dup of 1
        ]
        result = deduplicate_memory(entries)
        assert len(result) == 2

    def test_compress_memory_list_empty(self) -> None:
        assert compress_memory_list([]) == []

    def test_deduplicate_memory_empty(self) -> None:
        assert deduplicate_memory([]) == []
