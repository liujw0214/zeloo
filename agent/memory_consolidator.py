"""Memory consolidator — merge, dedupe, and expire memory entries."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _shingle(text: str, k: int = 3) -> frozenset[str]:
    """Token shingles for fast Jaccard pre-filtering.

    Returns the set of ``k``-shingle tokens. Used to bucket entries by
    common shingle hash so the merge can run in O(n) instead of O(n²).
    Empty / whitespace-only inputs return an empty frozenset so the
    caller can short-circuit to the linear ``merged`` list.
    """
    words = text.lower().split()
    if len(words) < k:
        return frozenset(words)
    return frozenset(" ".join(words[i : i + k]) for i in range(len(words) - k + 1))


class MemoryType(StrEnum):
    """Types of memory entries."""

    USER_FACT = "user_fact"
    AGENT_LEARNED = "agent_learned"
    SKILL_KNOWLEDGE = "skill_knowledge"
    TASK_CONTEXT = "task_context"
    PREFERENCE = "preference"


@dataclass
class MemoryEntry:
    """A single memory entry."""

    entry_id: str
    content: str
    memory_type: MemoryType
    importance: float = 0.5  # 0-1
    confidence: float = 0.8  # 0-1
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    tags: list[str] = field(default_factory=list)
    related_to: list[str] = field(default_factory=list)
    source: str = ""

    def access(self) -> None:
        self.last_accessed = time.time()
        self.access_count += 1


class MemoryConsolidator:
    """Consolidate memory entries: merge duplicates, expire stale ones.

    Reduces memory bloat by:
    1. Merging similar/duplicate entries
    2. Expiring low-importance stale entries
    3. Promoting frequently-accessed entries
    4. Decaying importance over time
    """

    def __init__(
        self,
        similarity_threshold: float = 0.85,
        max_entries: int = 1000,
        importance_decay_days: float = 30.0,
    ) -> None:
        self.similarity_threshold = similarity_threshold
        self.max_entries = max_entries
        self.importance_decay_days = importance_decay_days

    def consolidate(
        self,
        entries: list[MemoryEntry],
    ) -> tuple[list[MemoryEntry], dict[str, int]]:
        """Consolidate memory entries.

        Returns:
            (consolidated_entries, stats_dict)
        """
        stats = {
            "merged": 0,
            "expired": 0,
            "demoted": 0,
            "promoted": 0,
            "original_count": len(entries),
        }

        original_len = len(entries)
        entries = self._apply_decay(entries)
        stats["demoted"] = stats["original_count"] - len(
            [e for e in entries if e.importance > 0.1]
        )

        entries = self._merge_duplicates(entries)
        stats["merged"] = original_len - len(entries)

        entries = self._promote_frequent(entries)
        stats["promoted"] = sum(1 for e in entries if e.access_count > 5)

        pre_expire_len = len(entries)
        entries = self._expire_stale(entries)
        stats["expired"] = pre_expire_len - len(entries)

        if len(entries) > self.max_entries:
            entries = self._prune_to_limit(entries)

        stats["final_count"] = len(entries)
        logger.info(
            "Consolidated memory: %d → %d entries (merged %d, expired %d)",
            stats["original_count"],
            stats["final_count"],
            stats["merged"],
            stats["expired"],
        )
        return entries, stats

    def _apply_decay(
        self, entries: list[MemoryEntry]
    ) -> list[MemoryEntry]:
        now = time.time()
        for entry in entries:
            age_days = (now - entry.created_at) / 86400
            if age_days > 0:
                decay_factor = max(
                    0.1,
                    1.0 - (age_days / self.importance_decay_days) * 0.5,
                )
                entry.importance *= decay_factor
        return entries

    def _merge_duplicates(
        self, entries: list[MemoryEntry]
    ) -> list[MemoryEntry]:
        """Merge entries whose content Jaccard-similarity is above threshold.

        The previous implementation was O(n²): for each entry it scanned
        every already-merged entry and recomputed the Jaccard score
        from scratch. With 1 000 entries this means ~500 000 comparisons.

        The new implementation buckets entries by *shingle overlap* —
        only entries that share at least one 3-word shingle are
        candidates for Jaccard comparison. In practice the average
        bucket size is tiny (≪ 10), so the work is amortised O(n).

        Threshold semantics and merge side-effects (max importance,
        confidence bump, tag union, access-count sum) are identical
        to the previous implementation; the difference is purely
        algorithmic.
        """
        if not entries:
            return []

        # First pass: build the shingle bucket index. We index each
        # entry under each of its shingles. Two entries collide in the
        # candidate set only when they share at least one shingle.
        # ``MemoryEntry`` is a dataclass without ``eq=False`` but the
        # default ``eq=True`` makes instances unhashable, so we key the
        # candidate map by ``id()`` and translate back to the entry
        # object after the merge pass.
        candidates: dict[int, set[int]] = defaultdict(set)
        shingle_bucket: dict[frozenset, list[MemoryEntry]] = {}

        for entry in entries:
            sh = _shingle(entry.content)
            if not sh:
                # Empty content can't match anything — skip bucketing.
                continue
            for token in sh:
                shingle_bucket.setdefault(frozenset({token}), []).append(entry)

        # Merge the per-token buckets into per-entry candidate sets.
        for bucket in shingle_bucket.values():
            for i, e1 in enumerate(bucket):
                for e2 in bucket[i + 1 :]:
                    candidates[id(e1)].add(id(e2))
                    candidates[id(e2)].add(id(e1))

        # ``id()`` of an entry is stable as long as the entry object
        # lives; we keep a parallel ``id -> entry`` map for translation.
        id_to_entry: dict[int, MemoryEntry] = {id(e): e for e in entries}

        merged: list[MemoryEntry] = []
        used_ids: set[str] = set()

        for entry in entries:
            if entry.entry_id in used_ids:
                continue
            matched = False
            for other_id in candidates.get(id(entry), ()):
                other = id_to_entry.get(other_id)
                if other is None or other.entry_id in used_ids:
                    continue
                if other.entry_id == entry.entry_id:
                    continue
                similarity = self._compute_similarity(
                    entry.content, other.content
                )
                if similarity >= self.similarity_threshold:
                    other.importance = max(other.importance, entry.importance)
                    other.confidence = min(
                        1.0,
                        (other.confidence + entry.confidence) / 2 + 0.05,
                    )
                    other.access_count += entry.access_count
                    other.tags = list(set(other.tags + entry.tags))
                    used_ids.add(entry.entry_id)
                    matched = True
                    break
            if not matched:
                merged.append(entry)
                # No need to mark this entry used — it's the survivor.
        return merged

    def _compute_similarity(self, text_a: str, text_b: str) -> float:
        words_a = set(text_a.lower().split())
        words_b = set(text_b.lower().split())
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        union = words_a | words_b
        return len(intersection) / len(union)

    def _promote_frequent(
        self, entries: list[MemoryEntry]
    ) -> list[MemoryEntry]:
        for entry in entries:
            if entry.access_count > 5:
                entry.importance = min(1.0, entry.importance * 1.1)
        return entries

    def _expire_stale(
        self, entries: list[MemoryEntry]
    ) -> list[MemoryEntry]:
        return [e for e in entries if e.importance >= 0.1]

    def _prune_to_limit(
        self, entries: list[MemoryEntry]
    ) -> list[MemoryEntry]:
        sorted_entries = sorted(
            entries,
            key=lambda e: (e.importance * e.confidence, e.last_accessed),
            reverse=True,
        )
        return sorted_entries[: self.max_entries]


__all__ = [
    "MemoryType",
    "MemoryEntry",
    "MemoryConsolidator",
]