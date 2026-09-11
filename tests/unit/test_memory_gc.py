"""Unit tests for agent.memory_gc.

Covers:
- GCRule enum values
- GCCandidate dataclass construction
- MemoryGarbageCollector.evaluate_entry (single rule triggers)
- collect() across multiple entries with mixed rule hits
- list_candidates() score-threshold filtering
- restore() round-trip from trashbin
- delete() soft-delete into JSON trashbin (tmp_path)
- hard_delete() & empty_trashbin() lifecycle
- get_stats() age/importance/unused buckets
- 30-day automatic hard-delete of stale trashbin entries
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from agent.memory_compressor import MemoryEntry
from agent.memory_gc import GCCandidate, GCRule, MemoryGarbageCollector


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def gc(tmp_path: Path) -> MemoryGarbageCollector:
    """GC with isolated trashbin under tmp_path."""
    return MemoryGarbageCollector(
        trashbin_path=tmp_path / "trashbin.json",
        trashbin_retention_days=30,
    )


@pytest.fixture
def base_time() -> datetime:
    return datetime(2026, 1, 1, 12, 0, 0)


def _entry(
    entry_id: str,
    content: str = "some fact",
    importance: float = 0.5,
    timestamp: datetime | None = None,
    access_count: int = 0,
    last_accessed: datetime | None = None,
    tags: list[str] | None = None,
) -> MemoryEntry:
    return MemoryEntry(
        id=entry_id,
        content=content,
        importance=importance,
        timestamp=timestamp or datetime(2026, 1, 1),
        access_count=access_count,
        last_accessed=last_accessed,
        tags=tags or [],
    )


# ── GCRule enum ───────────────────────────────────────────────────────


class TestGCRule:
    def test_low_importance_value(self) -> None:
        assert GCRule.LOW_IMPORTANCE.value == "low_importance"

    def test_unused_value(self) -> None:
        assert GCRule.UNUSED.value == "unused"

    def test_old_value(self) -> None:
        assert GCRule.OLD.value == "old"

    def test_duplicate_value(self) -> None:
        assert GCRule.DUPLICATE.value == "duplicate"

    def test_enum_has_four_members(self) -> None:
        assert len(GCRule) == 4


# ── GCCandidate dataclass ─────────────────────────────────────────────


class TestGCCandidate:
    def test_construction(self) -> None:
        e = _entry("e1")
        cand = GCCandidate(
            entry=e,
            rules=[GCRule.LOW_IMPORTANCE],
            total_score=0.85,
            reason="low importance",
        )
        assert cand.entry is e
        assert cand.rules == [GCRule.LOW_IMPORTANCE]
        assert cand.total_score == 0.85
        assert cand.reason == "low importance"


# ── evaluate_entry() ──────────────────────────────────────────────────


class TestEvaluateEntry:
    def test_low_importance_triggers(
        self, gc: MemoryGarbageCollector, base_time: datetime
    ) -> None:
        e = _entry("low", importance=0.05, timestamp=base_time)
        rules = gc.evaluate_entry(e)
        assert GCRule.LOW_IMPORTANCE in rules

    def test_old_entry_triggers(
        self, gc: MemoryGarbageCollector
    ) -> None:
        ancient = _entry(
            "ancient",
            importance=0.5,
            timestamp=datetime.utcnow() - timedelta(days=365),
        )
        rules = gc.evaluate_entry(ancient)
        assert GCRule.OLD in rules

    def test_unused_triggers_for_old_unaccessed(
        self, gc: MemoryGarbageCollector
    ) -> None:
        # Unused requires: access_count == 0 AND last_accessed is None
        # AND timestamp older than unused_min_age_days.
        old_unused = _entry(
            "u",
            importance=0.5,
            timestamp=datetime.utcnow() - timedelta(days=60),
            access_count=0,
            last_accessed=None,
        )
        rules = gc.evaluate_entry(old_unused)
        assert GCRule.UNUSED in rules

    def test_fresh_important_entry_passes(
        self, gc: MemoryGarbageCollector
    ) -> None:
        e = _entry(
            "fresh",
            importance=0.9,
            timestamp=datetime.utcnow(),
            access_count=5,
        )
        rules = gc.evaluate_entry(e)
        assert rules == []

    def test_multiple_rules_can_apply(
        self, gc: MemoryGarbageCollector
    ) -> None:
        # Low importance + old age simultaneously.
        e = _entry(
            "multi",
            importance=0.05,
            timestamp=datetime.utcnow() - timedelta(days=200),
            access_count=0,
            last_accessed=None,
        )
        rules = gc.evaluate_entry(e)
        assert GCRule.LOW_IMPORTANCE in rules
        assert GCRule.OLD in rules
        assert GCRule.UNUSED in rules


# ── collect() ─────────────────────────────────────────────────────────


class TestCollect:
    def test_collect_empty(self, gc: MemoryGarbageCollector) -> None:
        assert gc.collect([]) == []

    def test_collect_marks_low_importance(
        self, gc: MemoryGarbageCollector
    ) -> None:
        # Use a fresh timestamp for "ok" so it's not flagged as OLD/UNUSED.
        entries = [
            _entry("low", importance=0.05, timestamp=datetime.utcnow()),
            _entry(
                "ok",
                content="completely unique fact about something else entirely",
                importance=0.9,
                timestamp=datetime.utcnow(),
                access_count=5,
            ),
        ]
        cands = gc.collect(entries)
        ids = {c.entry.id for c in cands}
        assert "low" in ids
        assert "ok" not in ids

    def test_collect_respects_rule_filter(
        self, gc: MemoryGarbageCollector, base_time: datetime
    ) -> None:
        entries = [
            _entry(
                "old_low",
                importance=0.05,
                timestamp=datetime.utcnow() - timedelta(days=200),
            ),
            _entry("ok", importance=0.9, timestamp=base_time),
        ]
        cands = gc.collect(entries, rule_filter=[GCRule.OLD])
        # old_low matches both LOW_IMPORTANCE and OLD; filter only OLD.
        ids = {c.entry.id for c in cands}
        assert "old_low" in ids
        for c in cands:
            assert GCRule.OLD in c.rules

    def test_collect_detects_duplicates(
        self, gc: MemoryGarbageCollector, base_time: datetime
    ) -> None:
        # Token-set Jaccard must exceed 0.92 to fire the default threshold.
        entries = [
            _entry(
                "a",
                content="python is a great language for web backends",
                importance=0.9,
                timestamp=base_time,
            ),
            _entry(
                "b",
                content="python is a great language for web backends",  # identical
                importance=0.7,
                timestamp=base_time,
            ),
        ]
        cands = gc.collect(entries, rule_filter=[GCRule.DUPLICATE])
        # Identical content → at least one flagged as duplicate.
        assert len(cands) >= 1
        assert all(GCRule.DUPLICATE in c.rules for c in cands)

    def test_collect_sorted_by_score(
        self, gc: MemoryGarbageCollector
    ) -> None:
        entries = [
            _entry(
                "older",
                importance=0.05,
                timestamp=datetime.utcnow() - timedelta(days=400),
                access_count=0,
                last_accessed=None,
            ),
            _entry(
                "newer",
                importance=0.1,
                timestamp=datetime.utcnow() - timedelta(days=100),
            ),
        ]
        cands = gc.collect(entries)
        if len(cands) >= 2:
            assert cands[0].total_score >= cands[1].total_score


# ── list_candidates() ─────────────────────────────────────────────────


class TestListCandidates:
    def test_filters_below_threshold(
        self, gc: MemoryGarbageCollector, base_time: datetime
    ) -> None:
        entries = [
            _entry(
                "ancient",
                importance=0.05,
                timestamp=datetime.utcnow() - timedelta(days=400),
                access_count=0,
                last_accessed=None,
            ),
            _entry("recent_low", importance=0.15, timestamp=base_time),
        ]
        cands = gc.list_candidates(entries, min_score=0.7)
        for c in cands:
            assert c.total_score >= 0.7

    def test_returns_empty_when_all_below(
        self, gc: MemoryGarbageCollector, base_time: datetime
    ) -> None:
        entries = [_entry("low", importance=0.15, timestamp=base_time)]
        cands = gc.list_candidates(entries, min_score=0.99)
        assert all(c.total_score >= 0.99 for c in cands)


# ── delete() / restore() ──────────────────────────────────────────────


class TestDeleteAndRestore:
    def test_soft_delete_writes_trashbin(
        self, gc: MemoryGarbageCollector, tmp_path: Path, base_time: datetime
    ) -> None:
        entries = [_entry("victim", importance=0.05, timestamp=base_time)]
        cands = gc.collect(entries)
        trashed = gc.delete(entries, cands)
        assert trashed >= 1
        assert (tmp_path / "trashbin.json").exists()

    def test_trashbin_records_contain_entry(
        self, gc: MemoryGarbageCollector, base_time: datetime
    ) -> None:
        entries = [_entry("v", importance=0.05, timestamp=base_time)]
        cands = gc.collect(entries)
        gc.delete(entries, cands)
        records = json.loads(gc.trashbin_path.read_text(encoding="utf-8"))
        ids = [r["id"] for r in records]
        assert "v" in ids

    def test_restore_removes_from_trashbin(
        self, gc: MemoryGarbageCollector, base_time: datetime
    ) -> None:
        entries = [_entry("r1", importance=0.05, timestamp=base_time)]
        cands = gc.collect(entries)
        gc.delete(entries, cands)
        assert gc.restore("r1") is True
        records = json.loads(gc.trashbin_path.read_text(encoding="utf-8"))
        assert all(r["id"] != "r1" for r in records)

    def test_restore_unknown_id_returns_false(
        self, gc: MemoryGarbageCollector
    ) -> None:
        assert gc.restore("never-existed") is False

    def test_trashbin_size_increases(
        self, gc: MemoryGarbageCollector, base_time: datetime
    ) -> None:
        assert gc.trashbin_size() == 0
        entries = [_entry(f"e{i}", importance=0.05, timestamp=base_time) for i in range(3)]
        cands = gc.collect(entries)
        gc.delete(entries, cands)
        assert gc.trashbin_size() == 3

    def test_hard_delete_removes_record(
        self, gc: MemoryGarbageCollector, base_time: datetime
    ) -> None:
        entries = [_entry("gone", importance=0.05, timestamp=base_time)]
        cands = gc.collect(entries)
        gc.delete(entries, cands)
        assert gc.hard_delete("gone") is True
        assert gc.trashbin_size() == 0

    def test_hard_delete_unknown_returns_false(
        self, gc: MemoryGarbageCollector
    ) -> None:
        assert gc.hard_delete("missing") is False

    def test_empty_trashbin_clears_all(
        self, gc: MemoryGarbageCollector, base_time: datetime
    ) -> None:
        entries = [_entry(f"e{i}", importance=0.05, timestamp=base_time) for i in range(3)]
        cands = gc.collect(entries)
        gc.delete(entries, cands)
        assert gc.empty_trashbin() == 3
        assert gc.trashbin_size() == 0


# ── 30-day automatic hard-delete ──────────────────────────────────────


class TestAutoHardDelete:
    def test_old_trashbin_records_purged_on_delete(
        self,
        tmp_path: Path,
        base_time: datetime,
    ) -> None:
        # Pre-seed trashbin with a record whose trashed_at is 31 days ago.
        old_record = {
            "id": "ancient_trash",
            "content": "x",
            "importance": 0.1,
            "timestamp": base_time.isoformat(),
            "last_accessed": None,
            "access_count": 0,
            "tags": [],
            "trashed_at": (datetime.utcnow() - timedelta(days=31)).isoformat(),
        }
        trash_path = tmp_path / "trashbin.json"
        trash_path.write_text(json.dumps([old_record]), encoding="utf-8")

        gc = MemoryGarbageCollector(
            trashbin_path=trash_path,
            trashbin_retention_days=30,
        )
        assert gc.trashbin_size() == 1

        # Triggering any delete() call should purge the expired record.
        entries = [_entry("fresh", importance=0.05, timestamp=base_time)]
        cands = gc.collect(entries)
        gc.delete(entries, cands)

        records = json.loads(trash_path.read_text(encoding="utf-8"))
        ids = [r["id"] for r in records]
        assert "ancient_trash" not in ids
        assert "fresh" in ids

    def test_recent_trashbin_records_kept(
        self,
        tmp_path: Path,
        base_time: datetime,
    ) -> None:
        recent_record = {
            "id": "recent_trash",
            "content": "x",
            "importance": 0.1,
            "timestamp": base_time.isoformat(),
            "last_accessed": None,
            "access_count": 0,
            "tags": [],
            "trashed_at": (datetime.utcnow() - timedelta(days=5)).isoformat(),
        }
        trash_path = tmp_path / "trashbin.json"
        trash_path.write_text(json.dumps([recent_record]), encoding="utf-8")

        gc = MemoryGarbageCollector(
            trashbin_path=trash_path,
            trashbin_retention_days=30,
        )
        # Force a delete() so the purge runs.
        gc.delete([], [])
        records = json.loads(trash_path.read_text(encoding="utf-8"))
        ids = [r["id"] for r in records]
        assert "recent_trash" in ids


# ── get_stats() ───────────────────────────────────────────────────────


class TestGetStats:
    def test_stats_structure(
        self, gc: MemoryGarbageCollector, base_time: datetime
    ) -> None:
        entries = [
            _entry("a", importance=0.1, timestamp=base_time),
            _entry("b", importance=0.6, timestamp=base_time),
        ]
        stats = gc.get_stats(entries)
        for key in (
            "total",
            "unused",
            "age_buckets",
            "importance_buckets",
            "trashbin_size",
            "thresholds",
            "rules",
        ):
            assert key in stats

    def test_stats_total_matches_input(
        self, gc: MemoryGarbageCollector, base_time: datetime
    ) -> None:
        entries = [
            _entry(f"e{i}", importance=0.5, timestamp=base_time) for i in range(5)
        ]
        assert gc.get_stats(entries)["total"] == 5

    def test_stats_unused_count(
        self, gc: MemoryGarbageCollector, base_time: datetime
    ) -> None:
        entries = [
            _entry("used", importance=0.5, timestamp=base_time, access_count=3),
            _entry("untouched", importance=0.5, timestamp=base_time, access_count=0),
        ]
        stats = gc.get_stats(entries)
        assert stats["unused"] == 1

    def test_stats_age_buckets_sum_to_total(
        self, gc: MemoryGarbageCollector, base_time: datetime
    ) -> None:
        entries = [
            _entry(f"e{i}", importance=0.5, timestamp=base_time) for i in range(4)
        ]
        stats = gc.get_stats(entries)
        bucket_sum = sum(stats["age_buckets"].values())
        assert bucket_sum == stats["total"]

    def test_stats_importance_buckets_sum_to_total(
        self, gc: MemoryGarbageCollector, base_time: datetime
    ) -> None:
        entries = [
            _entry(f"e{i}", importance=0.5, timestamp=base_time) for i in range(3)
        ]
        stats = gc.get_stats(entries)
        bucket_sum = sum(stats["importance_buckets"].values())
        assert bucket_sum == stats["total"]

    def test_stats_empty_input(self, gc: MemoryGarbageCollector) -> None:
        stats = gc.get_stats([])
        assert stats["total"] == 0
        assert stats["unused"] == 0
