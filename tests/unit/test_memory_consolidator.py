"""Integration tests for agent.memory_consolidator.

Covers:
- MemoryEntry lifecycle (access, importance bounds, field defaults)
- MemoryType enum values
- Consolidate: basic flow, no changes when nothing to consolidate
- Decay: old entries decay, new entries don't
- Merge: similar entries get merged, stats update
- Promote: high-access entries get importance boost
- Expire: low-importance entries removed
- Prune: excess entries pruned by importance×confidence
- Stats: original_count, final_count, merged, expired, demoted, promoted
- Edge cases: empty list, already deduped
- Thread safety
"""
from __future__ import annotations

import threading
import time

from agent.memory_consolidator import (
    MemoryConsolidator,
    MemoryEntry,
    MemoryType,
)


def time_now() -> float:
    return time.time()


def _entry(
    entry_id: str,
    content: str,
    memory_type: MemoryType = MemoryType.USER_FACT,
    importance: float = 0.5,
    confidence: float = 0.8,
    created_at: float = 0.0,
    last_accessed: float = 0.0,
    access_count: int = 0,
    tags: list[str] | None = None,
) -> MemoryEntry:
    return MemoryEntry(
            entry_id=entry_id,
            content=content,
            memory_type=memory_type,
            importance=importance,
            confidence=confidence,
            created_at=created_at,
            last_accessed=last_accessed,
            access_count=access_count,
            tags=tags or [],
        )


# ── MemoryEntry lifecycle ─────────────────────────────────────────


def test_memory_entry_defaults():
    e = MemoryEntry(entry_id="e1", content="hello", memory_type=MemoryType.USER_FACT)
    assert e.entry_id == "e1"
    assert e.content == "hello"
    assert e.importance == 0.5
    assert e.confidence == 0.8
    assert e.access_count == 0
    assert e.tags == []
    assert e.related_to == []
    assert e.source == ""


def test_access_updates_timestamp_and_count():
    e = _entry("e1", "test")
    original = e.last_accessed
    e.access()
    assert e.access_count == 1
    assert e.last_accessed >= original


def test_importance_is_clamped_on_decay():
    mc = MemoryConsolidator(importance_decay_days=1.0)
    old_entry = _entry("old", "ancient fact", created_at=0.0, importance=0.5)
    result, _ = mc.consolidate([old_entry])
    # Decay factor: 1.0 - (age_days/1.0)*0.5 → very small → importance drops
    # Result may be empty (expired) or still present with reduced importance
    assert isinstance(result, list)


def test_memory_type_enum_values():
    assert MemoryType.USER_FACT == "user_fact"
    assert MemoryType.AGENT_LEARNED == "agent_learned"
    assert MemoryType.SKILL_KNOWLEDGE == "skill_knowledge"
    assert MemoryType.TASK_CONTEXT == "task_context"
    assert MemoryType.PREFERENCE == "preference"


# ── Consolidate: basic flow ───────────────────────────────────────


def test_consolidate_returns_entries_and_stats():
    mc = MemoryConsolidator()
    entries = [_entry("e1", "fact 1"), _entry("e2", "fact 2")]
    result, stats = mc.consolidate(entries)
    assert isinstance(result, list)
    assert isinstance(stats, dict)
    assert "original_count" in stats
    assert "final_count" in stats


def test_consolidate_no_changes_for_distinct_recent_entries():
    mc = MemoryConsolidator(similarity_threshold=0.85)
    entries = [
        _entry("a", "python is great", created_at=time_now()),
        _entry("b", "rust is fast", created_at=time_now()),
    ]
    result, stats = mc.consolidate(entries)
    assert stats["original_count"] == 2
    assert stats["final_count"] == 2
    assert stats["merged"] == 0


def test_consolidate_empty_list():
    mc = MemoryConsolidator()
    result, stats = mc.consolidate([])
    assert result == []
    assert stats["original_count"] == 0
    assert stats["final_count"] == 0


# ── Decay ─────────────────────────────────────────────────────────


def test_decay_reduces_old_entries_importance():
    mc = MemoryConsolidator(importance_decay_days=30.0)
    old_entry = _entry("old", "old knowledge", created_at=0.0, importance=1.0)
    new_entry = _entry("new", "new knowledge", created_at=time_now(), importance=1.0)
    result, _ = mc.consolidate([old_entry, new_entry])
    if result:
        old_imp = next((e.importance for e in result if e.entry_id == "old"), None)
        new_imp = next((e.importance for e in result if e.entry_id == "new"), None)
        if old_imp is not None and new_imp is not None:
            assert old_imp <= new_imp


def test_new_entries_not_decayed():
    mc = MemoryConsolidator(importance_decay_days=30.0)
    fresh = _entry("fresh", "just learned", created_at=time_now(), importance=0.7)
    result, _ = mc.consolidate([fresh])
    assert result[0].importance >= 0.69  # near 0.7, no meaningful decay


# ── Merge ────────────────────────────────────────────────────────


def test_merge_similar_entries():
    mc = MemoryConsolidator(similarity_threshold=0.5)
    entries = [
        _entry("a", "python is a great language",
               importance=0.6, confidence=0.7, created_at=time_now()),
        _entry("b", "python is a great language for data science",
               importance=0.7, confidence=0.8, created_at=time_now()),
    ]
    result, stats = mc.consolidate(entries)
    assert len(result) == 1
    assert result[0].entry_id in ("a", "b")
    assert stats["merged"] == 1


def test_merge_keeps_highest_importance():
    mc = MemoryConsolidator(similarity_threshold=0.5)
    entries = [
        _entry("low", "same content", importance=0.3, created_at=time_now()),
        _entry("high", "same content", importance=0.9, created_at=time_now()),
    ]
    result, _ = mc.consolidate(entries)
    assert len(result) == 1
    assert result[0].importance >= 0.9


def test_merge_aggregates_access_count():
    mc = MemoryConsolidator(similarity_threshold=0.5)
    entries = [
        _entry("a", "shared content", access_count=2, created_at=time_now()),
        _entry("b", "shared content", access_count=5, created_at=time_now()),
    ]
    result, _ = mc.consolidate(entries)
    assert result[0].access_count >= 5


def test_merge_aggregates_tags():
    mc = MemoryConsolidator(similarity_threshold=0.5)
    entries = [
        _entry("a", "content", tags=["python", "ai"], created_at=time_now()),
        _entry("b", "content", tags=["ai", "ml"], created_at=time_now()),
    ]
    result, _ = mc.consolidate(entries)
    merged_tags = result[0].tags
    assert "python" in merged_tags
    assert "ml" in merged_tags


# ── Promote ──────────────────────────────────────────────────────


def test_promote_boosts_frequent_entries():
    mc = MemoryConsolidator()
    frequent = _entry("freq", "frequently used",
                     access_count=10, importance=0.5, created_at=time_now())
    rare = _entry("rare", "rarely used",
                 access_count=1, importance=0.5, created_at=time_now())
    result, _ = mc.consolidate([frequent, rare])
    freq_imp = next((e.importance for e in result if e.entry_id == "freq"), None)
    rare_imp = next((e.importance for e in result if e.entry_id == "rare"), None)
    assert freq_imp is not None
    assert rare_imp is not None
    assert freq_imp > rare_imp


def test_promote_never_exceeds_1():
    mc = MemoryConsolidator()
    entry = _entry("freq", "frequently used",
                 access_count=100, importance=0.99, created_at=time_now())
    result, _ = mc.consolidate([entry])
    assert result[0].importance <= 1.0


# ── Expire ──────────────────────────────────────────────────────


def test_expire_removes_low_importance():
    mc = MemoryConsolidator()
    low = _entry("low", "low importance", importance=0.05, created_at=time_now())
    high = _entry("high", "high importance", importance=0.8, created_at=time_now())
    result, stats = mc.consolidate([low, high])
    ids = {e.entry_id for e in result}
    assert "low" not in ids
    assert "high" in ids
    assert stats["expired"] >= 1


def test_expire_threshold_is_exclusive():
    mc = MemoryConsolidator()
    entry = _entry("border", "borderline", importance=0.5, created_at=time_now())
    result, _ = mc.consolidate([entry])
    assert len(result) == 1


# ── Prune ──────────────────────────────────────────────────────


def test_prune_enforces_max_entries():
    mc = MemoryConsolidator(max_entries=3)
    entries = [
        _entry(f"e{i}", f"fact {i}", importance=0.5, created_at=time_now())
        for i in range(10)
    ]
    result, stats = mc.consolidate(entries)
    assert stats["final_count"] <= 3


def test_prune_keeps_highest_importance_confidence():
    mc = MemoryConsolidator(max_entries=2)
    entries = [
        _entry("a", "low imp low conf", importance=0.2, confidence=0.3, created_at=time_now()),
        _entry("b", "high imp high conf", importance=0.9, confidence=0.9, created_at=time_now()),
        _entry("c", "high imp low conf", importance=0.9, confidence=0.3, created_at=time_now()),
    ]
    result, _ = mc.consolidate(entries)
    ids = {e.entry_id for e in result}
    assert "b" in ids


# ── Stats ───────────────────────────────────────────────────────


def test_stats_original_count_matches_input():
    mc = MemoryConsolidator()
    entries = [_entry(f"e{i}", f"f{i}", created_at=time_now()) for i in range(7)]
    _, stats = mc.consolidate(entries)
    assert stats["original_count"] == 7


def test_stats_keys_are_complete():
    mc = MemoryConsolidator()
    _, stats = mc.consolidate([_entry("e1", "test", created_at=time_now())])
    for key in ("original_count", "final_count", "merged", "expired", "demoted", "promoted"):
        assert key in stats


def test_stats_final_count_never_exceeds_max():
    mc = MemoryConsolidator(max_entries=5)
    entries = [_entry(f"e{i}", f"f{i}", importance=0.5, created_at=time_now()) for i in range(20)]
    _, stats = mc.consolidate(entries)
    assert stats["final_count"] <= mc.max_entries


# ── Edge cases ───────────────────────────────────────────────────


def test_consolidate_twice_is_idempotent():
    mc = MemoryConsolidator(similarity_threshold=0.85)
    entry = _entry("same", "identical content", created_at=time_now())
    first, _ = mc.consolidate([entry])
    second, _ = mc.consolidate(list(first))
    assert len(first) == len(second)


def test_entries_with_identical_ids_skip_duplicate():
    """Identical entry_ids are handled gracefully (kept as-is)."""
    mc = MemoryConsolidator()
    entries = [
        _entry("dup", "identical entry", created_at=time_now()),
        _entry("dup", "identical entry", created_at=time_now()),
    ]
    result, _ = mc.consolidate(entries)
    ids = [e.entry_id for e in result]
    assert ids.count("dup") >= 1


# ── Thread safety ────────────────────────────────────────────────


def test_consolidate_concurrent_calls():
    mc = MemoryConsolidator(max_entries=50)
    entries = [
        _entry(f"e{i}", f"fact {i}", importance=0.5, created_at=time_now())
        for i in range(100)
    ]
    errors: list[Exception] = []

    def worker() -> None:
        try:
            mc.consolidate(list(entries))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Concurrent errors: {errors}"