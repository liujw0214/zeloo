"""Memory garbage collector — rule-based eviction with soft-delete trashbin.

Sits downstream of :class:`MemoryCompressor`: the compressor reduces
volume, the GC identifies rule-violating entries and moves them to a
trashbin (``~/.Zeloo/memory_trashbin.json``). Hard delete is deferred
until ``trashbin_retention_days`` have elapsed.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path

from agent.memory_compressor import MemoryEntry, _now
from agent.zeloo_constants import get_zeloo_home

logger = logging.getLogger(__name__)


class GCRule(Enum):
    LOW_IMPORTANCE = "low_importance"  # importance < threshold
    UNUSED = "unused"                  # access_count == 0 and old enough
    OLD = "old"                         # timestamp > max_age
    DUPLICATE = "duplicate"            # similar to another entry


@dataclass
class GCCandidate:
    """Entry flagged for GC plus its reason."""

    entry: MemoryEntry
    rules: list[GCRule]
    total_score: float  # 0.0-1.0 — higher = more urgent
    reason: str


class MemoryGarbageCollector:
    """Identify and soft-delete stale memory entries.

    Args:
        low_importance_threshold: Entries below this score trigger
            :attr:`GCRule.LOW_IMPORTANCE`.
        max_age_days: Entries older than this trigger :attr:`GCRule.OLD`.
        unused_min_age_days: How long an untouched entry may live before
            :attr:`GCRule.UNUSED` fires.
        duplicate_threshold: Token-set ratio above which two entries
            are treated as duplicates.
        trashbin_retention_days: Days before trashbin entries are purged.
        trashbin_path: Override path; defaults to ``~/.Zeloo/memory_trashbin.json``.
    """

    DEFAULT_TRASHBIN = Path("memory_trashbin.json")

    def __init__(
        self,
        low_importance_threshold: float = 0.2,
        max_age_days: int = 90,
        unused_min_age_days: int = 30,
        duplicate_threshold: float = 0.92,
        trashbin_retention_days: int = 30,
        trashbin_path: Path | None = None,
    ) -> None:
        self.low_importance_threshold = low_importance_threshold
        self.max_age_days = max_age_days
        self.unused_min_age_days = unused_min_age_days
        self.duplicate_threshold = duplicate_threshold
        self.trashbin_retention_days = trashbin_retention_days
        self.trashbin_path = (
            Path(trashbin_path)
            if trashbin_path is not None
            else get_zeloo_home() / self.DEFAULT_TRASHBIN.name
        )
        self._lock = threading.Lock()

    # ── Rule evaluation ──────────────────────────────────────────

    def evaluate_entry(self, entry: MemoryEntry) -> list[GCRule]:
        """Return the list of rules that *entry* currently violates."""
        rules: list[GCRule] = []
        if entry.importance < self.low_importance_threshold:
            rules.append(GCRule.LOW_IMPORTANCE)
        now = _now()
        if (
            entry.access_count == 0
            and entry.last_accessed is None
            and entry.timestamp is not None
            and entry.timestamp < now - timedelta(days=self.unused_min_age_days)
        ):
            rules.append(GCRule.UNUSED)
        if entry.timestamp is not None and entry.timestamp < now - timedelta(
            days=self.max_age_days
        ):
            rules.append(GCRule.OLD)
        return rules

    # ── Collection ───────────────────────────────────────────────

    def collect(
        self,
        entries: list[MemoryEntry],
        rule_filter: list[GCRule] | None = None,
    ) -> list[GCCandidate]:
        """Return all entries violating at least one rule, sorted by score."""
        candidates: list[GCCandidate] = []
        for entry in entries:
            rules = self.evaluate_entry(entry)
            if rule_filter is not None:
                rules = [r for r in rules if r in rule_filter]
            if not rules:
                continue
            candidates.append(
                GCCandidate(
                    entry=entry,
                    rules=rules,
                    total_score=self._score(entry, rules),
                    reason=self._explain(entry, rules),
                )
            )
        if rule_filter is None or GCRule.DUPLICATE in rule_filter:
            candidates.extend(self._find_duplicates(entries, rule_filter))
        return self._merge_candidates(candidates)

    def list_candidates(
        self,
        entries: list[MemoryEntry],
        min_score: float = 0.5,
    ) -> list[GCCandidate]:
        """Same as :meth:`collect` but filtered by ``total_score >= min_score``."""
        return [c for c in self.collect(entries) if c.total_score >= min_score]

    # ── Trashbin operations ──────────────────────────────────────

    def _trashbin_records(self) -> list[dict]:
        if not self.trashbin_path.exists():
            return []
        try:
            payload = json.loads(self.trashbin_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not load trashbin %s: %s", self.trashbin_path, exc)
            return []
        return payload if isinstance(payload, list) else []

    def _save_trashbin(self, records: list[dict]) -> None:
        self.trashbin_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.trashbin_path.with_suffix(self.trashbin_path.suffix + ".tmp")
        tmp.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.trashbin_path)

    def restore(self, memory_id: str) -> bool:
        """Remove *memory_id* from the trashbin (soft-undelete)."""
        with self._lock:
            records = self._trashbin_records()
            kept = [r for r in records if r.get("id") != memory_id]
            if len(kept) == len(records):
                return False
            self._save_trashbin(kept)
            logger.info("Restored memory entry %s from trashbin", memory_id)
            return True

    def delete(
        self,
        entries: list[MemoryEntry],
        candidates: list[GCCandidate],
    ) -> int:
        """Move the *candidates* into the trashbin (soft delete).

        Also hard-deletes trashbin records older than
        ``trashbin_retention_days``. Returns the count newly trashed.
        """
        candidate_ids = {c.entry.id for c in candidates}
        with self._lock:
            self._purge_expired_trashbin_locked()
            records = self._trashbin_records()
            now = _now()
            trashed = 0
            for entry in entries:
                if entry.id in candidate_ids:
                    records.append(self._serialise_trashbin_entry(entry, now))
                    trashed += 1
            self._save_trashbin(records)
            logger.info("Soft-deleted %d entries into trashbin", trashed)
            return trashed

    def hard_delete(self, memory_id: str) -> bool:
        """Immediately remove *memory_id* from the trashbin (irreversible)."""
        with self._lock:
            records = self._trashbin_records()
            kept = [r for r in records if r.get("id") != memory_id]
            if len(kept) == len(records):
                return False
            self._save_trashbin(kept)
            return True

    def empty_trashbin(self) -> int:
        """Hard-delete everything in the trashbin. Returns the count removed."""
        with self._lock:
            records = self._trashbin_records()
            self._save_trashbin([])
            return len(records)

    def trashbin_size(self) -> int:
        return len(self._trashbin_records())

    # ── Stats ─────────────────────────────────────────────────────

    def get_stats(self, entries: list[MemoryEntry]) -> dict:
        """Aggregate counts useful for dashboards / debugging."""
        now = _now()
        age_buckets = {"fresh_7d": 0, "7_30d": 0, "30_90d": 0, "older": 0}
        importance_buckets = {"0-0.2": 0, "0.2-0.5": 0, "0.5-0.8": 0, "0.8-1.0": 0}
        unused = 0
        for e in entries:
            age = (now - e.timestamp).days if e.timestamp else 0
            if age <= 7:
                age_buckets["fresh_7d"] += 1
            elif age <= 30:
                age_buckets["7_30d"] += 1
            elif age <= 90:
                age_buckets["30_90d"] += 1
            else:
                age_buckets["older"] += 1
            if e.importance < 0.2:
                importance_buckets["0-0.2"] += 1
            elif e.importance < 0.5:
                importance_buckets["0.2-0.5"] += 1
            elif e.importance < 0.8:
                importance_buckets["0.5-0.8"] += 1
            else:
                importance_buckets["0.8-1.0"] += 1
            if e.access_count == 0:
                unused += 1
        return {
            "total": len(entries),
            "unused": unused,
            "age_buckets": age_buckets,
            "importance_buckets": importance_buckets,
            "trashbin_size": self.trashbin_size(),
            "trashbin_path": str(self.trashbin_path),
            "trashbin_retention_days": self.trashbin_retention_days,
            "rules": [r.value for r in GCRule],
            "thresholds": {
                "low_importance": self.low_importance_threshold,
                "max_age_days": self.max_age_days,
                "unused_min_age_days": self.unused_min_age_days,
                "duplicate_threshold": self.duplicate_threshold,
            },
        }

    # ── Internal helpers ──────────────────────────────────────────

    def _score(self, entry: MemoryEntry, rules: list[GCRule]) -> float:
        """Higher score = more urgent to evict (range 0.0-1.0)."""
        score = 0.0
        if GCRule.LOW_IMPORTANCE in rules:
            score += 1.0 - entry.importance
        if GCRule.UNUSED in rules:
            score += 0.4
        if GCRule.OLD in rules:
            age_days = max(0, (_now() - entry.timestamp).days) if entry.timestamp else 0
            score += min(1.0, age_days / 180.0) * 0.6
        if GCRule.DUPLICATE in rules:
            score += 0.3
        return max(0.0, min(1.0, score))

    def _explain(self, entry: MemoryEntry, rules: list[GCRule]) -> str:
        bits = [f"rule={r.value}" for r in rules]
        return f"id={entry.id} importance={entry.importance:.2f} " + " ".join(bits)

    def _merge_candidates(self, candidates: list[GCCandidate]) -> list[GCCandidate]:
        """De-duplicate by ``entry.id``, merging rule lists and reasons."""
        merged: dict[str, GCCandidate] = {}
        for cand in candidates:
            existing = merged.get(cand.entry.id)
            if existing is None:
                merged[cand.entry.id] = cand
                continue
            for r in cand.rules:
                if r not in existing.rules:
                    existing.rules.append(r)
            existing.total_score = max(existing.total_score, cand.total_score)
            existing.reason = existing.reason + "; " + cand.reason
        return sorted(merged.values(), key=lambda c: c.total_score, reverse=True)

    def _find_duplicates(
        self,
        entries: list[MemoryEntry],
        rule_filter: list[GCRule] | None,
    ) -> list[GCCandidate]:
        """Token-set ratio scan for duplicates."""
        seen_keys: list[tuple[frozenset[str], int]] = []
        cands: list[GCCandidate] = []
        for entry in entries:
            tokens = frozenset(t.lower() for t in entry.content.split() if t)
            if not tokens:
                continue
            for prev_tokens, prev_idx in seen_keys:
                union = len(tokens | prev_tokens)
                if not union:
                    continue
                ratio = len(tokens & prev_tokens) / union
                if ratio >= self.duplicate_threshold:
                    other = entries[prev_idx]
                    loser = entry if entry.importance < other.importance else other
                    if rule_filter and GCRule.DUPLICATE not in rule_filter:
                        continue
                    cands.append(
                        GCCandidate(
                            entry=loser,
                            rules=[GCRule.DUPLICATE],
                            total_score=self._score(loser, [GCRule.DUPLICATE]),
                            reason=f"duplicate of {other.id} (ratio={ratio:.2f})",
                        )
                    )
            seen_keys.append((tokens, len(seen_keys)))
        return cands

    def _serialise_trashbin_entry(
        self, entry: MemoryEntry, trashed_at: datetime
    ) -> dict:
        return {
            "id": entry.id,
            "content": entry.content,
            "importance": entry.importance,
            "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
            "last_accessed": (
                entry.last_accessed.isoformat() if entry.last_accessed else None
            ),
            "access_count": entry.access_count,
            "tags": list(entry.tags),
            "trashed_at": trashed_at.isoformat(),
        }

    def _purge_expired_trashbin_locked(self) -> None:
        records = self._trashbin_records()
        if not records:
            return
        cutoff = _now() - timedelta(days=self.trashbin_retention_days)
        kept: list[dict] = []
        purged = 0
        for record in records:
            ts = record.get("trashed_at")
            try:
                trashed_at = datetime.fromisoformat(ts) if ts else None
            except ValueError:
                trashed_at = None
            if trashed_at is None or trashed_at < cutoff:
                purged += 1
                continue
            kept.append(record)
        if purged:
            self._save_trashbin(kept)
            logger.info(
                "Hard-deleted %d trashbin entries older than %d days",
                purged,
                self.trashbin_retention_days,
            )


__all__ = ["GCRule", "GCCandidate", "MemoryGarbageCollector"]
