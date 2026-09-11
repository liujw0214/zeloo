"""Memory compressor — similarity, dedup, and summary-based compression.

Strategies: TF-IDF cosine, time-decay, importance, or a hybrid blend.
Companion to ``memory_consolidator.py``; sits *upstream* of
``memory_gc.py`` so the GC only sees already-reduced inputs.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    return [t.lower() for t in _TOKEN_RE.findall(text) if t.strip()]


def _now() -> datetime:
    return datetime.utcnow()


@dataclass
class MemoryEntry:
    id: str
    content: str
    importance: float  # 0.0-1.0
    timestamp: datetime
    access_count: int = 0
    last_accessed: datetime | None = None
    tags: list[str] = field(default_factory=list)


class CompressionStrategy(Enum):
    TFIDF = "tfidf"
    TIME_DECAY = "time_decay"
    IMPORTANCE = "importance"
    HYBRID = "hybrid"


def _entry_from_dict(d: dict[str, Any]) -> MemoryEntry:
    ts = d.get("timestamp")
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    elif ts is None:
        ts = _now()
    la = d.get("last_accessed")
    if isinstance(la, str):
        la = datetime.fromisoformat(la)
    return MemoryEntry(
        id=str(d.get("id") or d.get("entry_id") or ""),
        content=str(d.get("content") or ""),
        importance=float(d.get("importance", 0.5)),
        timestamp=ts,
        access_count=int(d.get("access_count", 0)),
        last_accessed=la,
        tags=list(d.get("tags") or []),
    )


def _entry_to_dict(e: MemoryEntry) -> dict[str, Any]:
    return {
        "id": e.id,
        "content": e.content,
        "importance": e.importance,
        "timestamp": e.timestamp.isoformat() if e.timestamp else None,
        "access_count": e.access_count,
        "last_accessed": e.last_accessed.isoformat() if e.last_accessed else None,
        "tags": list(e.tags),
    }


class MemoryCompressor:
    """Reduce memory entries via similarity-based merging + scoring."""

    def __init__(self, strategy: CompressionStrategy = CompressionStrategy.HYBRID) -> None:
        self.strategy = strategy

    def compress(
        self,
        entries: list[MemoryEntry],
        similarity_threshold: float = 0.85,
    ) -> list[MemoryEntry]:
        """Deduplicate, merge, then apply the strategy filter."""
        if not entries:
            return []
        merged = self.merge_similar(self.deduplicate(entries))
        if self.strategy == CompressionStrategy.TFIDF:
            return self._filter_by_similarity(merged, similarity_threshold)
        if self.strategy == CompressionStrategy.TIME_DECAY:
            return self._filter_by_recency(merged)
        if self.strategy == CompressionStrategy.IMPORTANCE:
            return self._filter_by_importance(merged)
        return self._filter_hybrid(merged)

    def deduplicate(self, entries: list[MemoryEntry]) -> list[MemoryEntry]:
        """Remove exact-content duplicates (case-insensitive)."""
        seen: dict[str, MemoryEntry] = {}
        order: list[str] = []
        for entry in entries:
            key = entry.content.strip().lower()
            if key not in seen:
                seen[key] = MemoryEntry(
                    id=entry.id,
                    content=entry.content,
                    importance=entry.importance,
                    timestamp=entry.timestamp,
                    access_count=entry.access_count,
                    last_accessed=entry.last_accessed,
                    tags=list(entry.tags),
                )
                order.append(key)
                continue
            survivor = seen[key]
            survivor.access_count += entry.access_count
            survivor.importance = max(survivor.importance, entry.importance)
            for t in entry.tags:
                if t not in survivor.tags:
                    survivor.tags.append(t)
        return [seen[k] for k in order]

    def compute_similarity(self, a: str, b: str) -> float:
        """TF-IDF cosine similarity in ``[0.0, 1.0]``."""
        tokens_a = _tokenize(a)
        tokens_b = _tokenize(b)
        if not tokens_a or not tokens_b:
            return 0.0
        if len(tokens_a) == 1 and len(tokens_b) == 1:
            return 1.0 if tokens_a[0] == tokens_b[0] else 0.0
        return self.tfidf_similarity(a, b)

    def tfidf_similarity(self, a: str, b: str) -> float:
        """Cosine similarity over a 2-document TF-IDF space."""
        docs = [_tokenize(a), _tokenize(b)]
        if not docs[0] or not docs[1]:
            return 0.0
        df: Counter[str] = Counter()
        for d in docs:
            for term in set(d):
                df[term] += 1
        n = len(docs)
        vectors: list[dict[str, float]] = []
        for d in docs:
            tf: Counter[str] = Counter(d)
            length = max(1, len(d))
            vec: dict[str, float] = {}
            for term, count in tf.items():
                idf = math.log((n + 1) / (df[term] + 1)) + 1.0
                vec[term] = (count / length) * idf
            vectors.append(vec)
        return _cosine(vectors[0], vectors[1])

    def merge_similar(self, entries: list[MemoryEntry]) -> list[MemoryEntry]:
        """Union-find merge of entries with similarity ≥ 0.85."""
        if len(entries) < 2:
            return list(entries)
        buckets: dict[str, list[int]] = {}
        for idx, entry in enumerate(entries):
            for sh in _shingles(entry.content, k=3):
                buckets.setdefault(sh, []).append(idx)
        parent = list(range(len(entries)))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(i: int, j: int) -> None:
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[ri] = rj

        for indices in buckets.values():
            if len(indices) < 2:
                continue
            anchor = indices[0]
            for other in indices[1:]:
                if find(anchor) == find(other):
                    continue
                if self.compute_similarity(
                    entries[anchor].content, entries[other].content
                ) >= 0.85:
                    union(anchor, other)

        groups: dict[int, list[int]] = {}
        for idx in range(len(entries)):
            groups.setdefault(find(idx), []).append(idx)
        merged: list[MemoryEntry] = []
        for root_idxs in groups.values():
            members = [entries[i] for i in root_idxs]
            merged.append(
                members[0] if len(members) == 1 else _merge_members(members)
            )
        return merged

    def compress_to_summary(
        self,
        entries: list[MemoryEntry],
        max_length: int = 500,
    ) -> str:
        """Return a bullet-pointed summary capped at *max_length* chars."""
        if not entries:
            return ""
        ranked = sorted(
            entries,
            key=lambda e: (e.importance, e.access_count, e.timestamp),
            reverse=True,
        )
        lines: list[str] = []
        total = 0
        for entry in ranked:
            tag_str = f" [{', '.join(entry.tags)}]" if entry.tags else ""
            line = f"- ({entry.importance:.2f}){tag_str} {entry.content.strip()}"
            if total + len(line) > max_length and lines:
                break
            lines.append(line)
            total += len(line) + 1
        summary = "\n".join(lines)
        if len(summary) > max_length:
            summary = summary[: max_length - 1] + "…"
        return summary

    # ── Strategy filters ────────────────────────────────────────

    def _filter_by_similarity(
        self, entries: list[MemoryEntry], threshold: float
    ) -> list[MemoryEntry]:
        if len(entries) < 2:
            return list(entries)
        keep: list[MemoryEntry] = []
        for entry in entries:
            others = [e for e in entries if e.id != entry.id]
            if not others:
                keep.append(entry)
                continue
            avg = sum(self.compute_similarity(entry.content, o.content) for o in others) / len(others)
            if avg >= (1.0 - threshold) or entry.importance >= 0.7:
                keep.append(entry)
        return keep

    def _filter_by_recency(self, entries: list[MemoryEntry]) -> list[MemoryEntry]:
        now = _now()
        scored: list[tuple[float, MemoryEntry]] = []
        for entry in entries:
            age_days = max(0.0, (now - entry.timestamp).total_seconds() / 86400)
            scored.append((entry.importance * math.exp(-age_days / 30.0), entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored if e.importance >= 0.1]

    def _filter_by_importance(self, entries: list[MemoryEntry]) -> list[MemoryEntry]:
        return sorted(entries, key=lambda e: e.importance, reverse=True)

    def _filter_hybrid(self, entries: list[MemoryEntry]) -> list[MemoryEntry]:
        now = _now()
        scored: list[tuple[float, MemoryEntry]] = []
        for entry in entries:
            age_days = max(0.0, (now - entry.timestamp).total_seconds() / 86400)
            recency = math.exp(-age_days / 60.0)
            access_boost = 1.0 + math.log1p(max(0, entry.access_count)) * 0.1
            scored.append((entry.importance * recency * access_boost, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored]


def _shingles(text: str, k: int = 3) -> Iterable[str]:
    tokens = _tokenize(text)
    if len(tokens) < k:
        return set(tokens) if tokens else set()
    return {" ".join(tokens[i : i + k]) for i in range(len(tokens) - k + 1)}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    num = sum(a[t] * b[t] for t in common)
    den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    if den == 0:
        return 0.0
    return max(0.0, min(1.0, num / den))


def _merge_members(members: list[MemoryEntry]) -> MemoryEntry:
    """Pick the highest-ranked survivor; fold stats onto it."""
    members_sorted = sorted(
        members, key=lambda e: (e.importance, e.access_count), reverse=True
    )
    head = members_sorted[0]
    merged_tags: list[str] = []
    seen_tags: set[str] = set()
    total_access = 0
    max_importance = head.importance
    last_accessed: datetime | None = head.last_accessed
    for m in members_sorted:
        total_access += m.access_count
        max_importance = max(max_importance, m.importance)
        for t in m.tags:
            if t not in seen_tags:
                seen_tags.add(t)
                merged_tags.append(t)
        if m.last_accessed and (last_accessed is None or m.last_accessed > last_accessed):
            last_accessed = m.last_accessed
    return MemoryEntry(
        id=head.id,
        content=head.content,
        importance=max_importance,
        timestamp=head.timestamp,
        access_count=total_access,
        last_accessed=last_accessed,
        tags=merged_tags,
    )


def compress_memory_list(entries: list[dict]) -> list[dict]:
    """Convenience: dict in / dict out via :class:`MemoryCompressor`."""
    parsed = [_entry_from_dict(d) for d in entries]
    return [_entry_to_dict(e) for e in MemoryCompressor().compress(parsed)]


def deduplicate_memory(entries: list[dict]) -> list[dict]:
    """Convenience: dedup dicts by content."""
    parsed = [_entry_from_dict(d) for d in entries]
    return [_entry_to_dict(e) for e in MemoryCompressor().deduplicate(parsed)]


__all__ = [
    "MemoryEntry",
    "CompressionStrategy",
    "MemoryCompressor",
    "compress_memory_list",
    "deduplicate_memory",
]
