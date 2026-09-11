"""Browser navigation origin tracking.

Track which URL triggered which action within a session. Useful for
security auditing, replay debugging, and proving that an action was
prompted by a specific origin (or set of origins).

Example::

    tracker = OriginTracker()
    tracker.record(
        session_id="sess-1",
        from_url="https://example.com",
        to_url="https://example.com/login",
        action="navigate",
    )
    history = tracker.get_history("sess-1")
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class OriginEntry:
    """A single navigation or action edge within a session.

    Attributes:
        entry_id: Stable identifier for this record.
        session_id: Owning browser session.
        from_url: Origin URL (may be ``"about:blank"`` for the first nav).
        to_url: Target URL of the action.
        action: Free-form action name (navigate, click, submit, ...).
        timestamp: Unix time (seconds) when the action was recorded.
        metadata: Arbitrary key/value annotations (DOM id, selector, etc.).
    """

    session_id: str
    from_url: str
    to_url: str
    action: str
    timestamp: float
    metadata: dict[str, Any] = field(default_factory=dict)
    entry_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict."""
        return asdict(self)

    @property
    def origin_domain(self) -> str:
        """Best-effort hostname of ``from_url`` (empty on parse failure)."""
        return _domain(self.from_url)

    @property
    def target_domain(self) -> str:
        """Best-effort hostname of ``to_url`` (empty on parse failure)."""
        return _domain(self.to_url)

    def is_cross_origin(self) -> bool:
        """True if origin and target live on different hostnames."""
        a = self.origin_domain
        b = self.target_domain
        if not a or not b:
            return False
        return a != b


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _domain(url: str) -> str:
    """Extract hostname from ``url``; empty string on parse failure."""
    if not url:
        return ""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return (parsed.hostname or "").lower()
    except Exception:  # pragma: no cover - defensive
        return ""


def _now() -> float:
    return time.time()


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------


class OriginTracker:
    """Track navigation origins per session.

    The tracker is bounded: when ``max_entries`` is reached, the oldest
    record is dropped. Per-session lookup is O(1) and history is
    returned in chronological order.

    Concurrency:
        All mutations are guarded by a single asyncio lock so the
        tracker is safe to share across async tasks in the same loop.
    """

    def __init__(self, max_entries: int = 500) -> None:
        """Initialize the tracker.

        Args:
            max_entries: Hard cap across all sessions (FIFO eviction).
        """
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self.max_entries: int = int(max_entries)
        self.entries: list[OriginEntry] = []
        self._by_session: dict[str, deque[OriginEntry]] = defaultdict(deque)
        self._lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Write API
    # ------------------------------------------------------------------

    async def record(
        self,
        session_id: str,
        from_url: str,
        to_url: str,
        action: str,
        timestamp: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> OriginEntry:
        """Append a new entry.

        Args:
            session_id: Owning session.
            from_url: Source URL.
            to_url: Destination URL.
            action: Action verb.
            timestamp: Optional explicit timestamp (defaults to now).
            metadata: Optional annotations.

        Returns:
            The persisted :class:`OriginEntry`.
        """
        if not session_id:
            raise ValueError("session_id is required")
        if not action:
            raise ValueError("action is required")

        entry = OriginEntry(
            session_id=session_id,
            from_url=from_url or "",
            to_url=to_url or "",
            action=action,
            timestamp=float(timestamp) if timestamp is not None else _now(),
            metadata=dict(metadata or {}),
        )

        async with self._lock:
            self._evict_if_full_locked()
            self.entries.append(entry)
            self._by_session[session_id].append(entry)
        logger.debug(
            "origin_recorded session=%s action=%s from=%s to=%s",
            session_id,
            action,
            from_url,
            to_url,
        )
        return entry

    def record_sync(
        self,
        session_id: str,
        from_url: str,
        to_url: str,
        action: str,
        **metadata: Any,
    ) -> OriginEntry:
        """Synchronous variant for non-async call sites."""
        if not session_id:
            raise ValueError("session_id is required")
        if not action:
            raise ValueError("action is required")
        entry = OriginEntry(
            session_id=session_id,
            from_url=from_url or "",
            to_url=to_url or "",
            action=action,
            timestamp=_now(),
            metadata=dict(metadata),
        )
        self._evict_if_full_locked()
        self.entries.append(entry)
        self._by_session[session_id].append(entry)
        return entry

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    def get_history(self, session_id: str) -> list[OriginEntry]:
        """Return the full history for a session (chronological)."""
        return list(self._by_session.get(session_id, ()))

    def get_last(self, session_id: str) -> OriginEntry | None:
        """Return the most recent entry for a session, or ``None``."""
        dq = self._by_session.get(session_id)
        if not dq:
            return None
        return dq[-1]

    def find_cross_origin(self, session_id: str) -> list[OriginEntry]:
        """Return entries that crossed a hostname boundary."""
        return [e for e in self.get_history(session_id) if e.is_cross_origin()]

    def find_by_action(self, session_id: str, action: str) -> list[OriginEntry]:
        """Return entries whose ``action`` matches ``action`` exactly."""
        return [e for e in self.get_history(session_id) if e.action == action]

    def sessions(self) -> list[str]:
        """Return all known session IDs."""
        return list(self._by_session.keys())

    def total_entries(self) -> int:
        """Return the total number of stored entries."""
        return len(self.entries)

    # ------------------------------------------------------------------
    # Mutating helpers
    # ------------------------------------------------------------------

    def clear(self, session_id: str) -> int:
        """Drop all entries for ``session_id``.

        Returns:
            The number of entries removed.
        """
        dq = self._by_session.get(session_id)
        if not dq:
            return 0
        removed = len(dq)
        kept = [e for e in self.entries if e.session_id != session_id]
        self.entries = kept
        del self._by_session[session_id]
        logger.info("origin_cleared session=%s removed=%d", session_id, removed)
        return removed

    def clear_all(self) -> int:
        """Drop every entry. Returns the number removed."""
        removed = len(self.entries)
        self.entries.clear()
        self._by_session.clear()
        return removed

    def export(self) -> list[dict[str, Any]]:
        """Return all entries as plain dicts (for serialization)."""
        return [e.to_dict() for e in self.entries]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _evict_if_full_locked(self) -> None:
        """Evict the oldest entry (any session) when at capacity.

        NOTE: Called from both async (``record``) and sync (``record_sync``)
        callers. ``record`` already holds ``self._lock``, so this method
        must NOT re-acquire it.
        """
        if len(self.entries) < self.max_entries:
            return
        oldest = self.entries.pop(0)
        dq = self._by_session.get(oldest.session_id)
        if dq:
            try:
                dq.popleft()
            except IndexError:
                pass
            if not dq:
                self._by_session.pop(oldest.session_id, None)
        logger.debug(
            "origin_evicted session=%s entry_id=%s",
            oldest.session_id,
            oldest.entry_id,
        )


# ---------------------------------------------------------------------------
# Convenience filter helpers (module-level)
# ---------------------------------------------------------------------------


def filter_entries(
    entries: Iterable[OriginEntry],
    *,
    action: str | None = None,
    domain: str | None = None,
    cross_origin_only: bool = False,
) -> list[OriginEntry]:
    """Filter a sequence of entries by simple predicates.

    Args:
        entries: Source iterable.
        action: If set, keep entries whose ``action`` equals this.
        domain: If set, keep entries whose target domain equals this.
        cross_origin_only: If True, keep only cross-origin entries.

    Returns:
        A new list (the input is not mutated).
    """
    out: list[OriginEntry] = []
    for e in entries:
        if action is not None and e.action != action:
            continue
        if domain is not None and e.target_domain != domain.lower():
            continue
        if cross_origin_only and not e.is_cross_origin():
            continue
        out.append(e)
    return out


def summarise(entries: Iterable[OriginEntry]) -> dict[str, Any]:
    """Produce a tiny summary report of a set of entries."""
    items = list(entries)
    by_action: dict[str, int] = defaultdict(int)
    by_domain: dict[str, int] = defaultdict(int)
    cross = 0
    for e in items:
        by_action[e.action] += 1
        d = e.target_domain or "<unknown>"
        by_domain[d] += 1
        if e.is_cross_origin():
            cross += 1
    return {
        "total": len(items),
        "cross_origin": cross,
        "by_action": dict(by_action),
        "by_target_domain": dict(by_domain),
        "first_at": items[0].timestamp if items else None,
        "last_at": items[-1].timestamp if items else None,
    }
