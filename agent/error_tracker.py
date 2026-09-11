"""Error tracking — structured recording of runtime errors.

Persists error events to SQLite so they can be aggregated, queried,
and exported for debugging. Each :class:`ErrorEvent` carries the same
fields used by Sentry (without the dependency):

* category (from :mod:`agent.error_classifier`)
* severity (fatal / error / warning / info)
* message, stack trace, request context
* timestamp, session_id, provider, model
* fingerprint (dedup key for grouping)

The default store is a single ``error_events`` table in the same
database that backs :mod:`zeloo_state` so errors appear alongside
sessions for unified debugging.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS error_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL,
    category TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    stack_trace TEXT,
    session_id TEXT,
    provider TEXT,
    model TEXT,
    context_json TEXT,
    timestamp REAL NOT NULL,
    occurrence_count INTEGER DEFAULT 1,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_error_fingerprint
    ON error_events(fingerprint, last_seen DESC);
CREATE INDEX IF NOT EXISTS idx_error_session
    ON error_events(session_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_error_category
    ON error_events(category, timestamp DESC);
"""


@dataclass
class ErrorEvent:
    """A single error occurrence."""

    fingerprint: str
    category: str
    severity: str
    message: str
    timestamp: float
    first_seen: float
    last_seen: float
    occurrence_count: int = 1
    stack_trace: str = ""
    session_id: str = ""
    provider: str = ""
    model: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "category": self.category,
            "severity": self.severity,
            "message": self.message,
            "timestamp": self.timestamp,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "occurrence_count": self.occurrence_count,
            "stack_trace": self.stack_trace,
            "session_id": self.session_id,
            "provider": self.provider,
            "model": self.model,
            "context": self.context,
        }


def _fingerprint(category: str, message: str, stack: str = "") -> str:
    """Compute a stable hash so identical errors group together."""
    # Take the first stack frame + message + category for grouping.
    first_frame = ""
    if stack:
        for line in stack.splitlines():
            if "File " in line:
                first_frame = line.strip()
                break
    payload = f"{category}|{first_frame}|{message[:200]}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class ErrorTracker:
    """Thread-safe SQLite-backed error event store.

    Args:
        db_path: SQLite file to write to. ``None`` uses
            ``~/.Zeloo/state.db``.
        max_events: Soft cap on rows. Oldest non-fatal events are
            pruned when the cap is exceeded. Default 10000.
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        max_events: int = 10000,
    ) -> None:
        if db_path is None:
            from agent.zeloo_constants import get_state_db_path

            db_path = get_state_db_path()
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_events = max_events
        self._lock = threading.Lock()
        # Observers receive every recorded ErrorEvent (in-process fan-out).
        # Used by :mod:`agent.error_observability` to forward to Langfuse.
        self._observers: list[Any] = []
        self._ensure_table()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_table(self) -> None:
        with self._lock:
            with self._conn() as conn:
                conn.executescript(_TABLE_SCHEMA)
                conn.commit()

    def record(
        self,
        category: str,
        message: str,
        *,
        severity: str = "error",
        stack_trace: str = "",
        session_id: str = "",
        provider: str = "",
        model: str = "",
        context: dict[str, Any] | None = None,
    ) -> ErrorEvent:
        """Record an error event. If a matching fingerprint already
        exists, increment its ``occurrence_count`` instead of inserting
        a new row.
        """
        ts = time.time()
        fingerprint = _fingerprint(category, message, stack_trace)
        ctx = context or {}

        with self._lock:
            with self._conn() as conn:
                existing = conn.execute(
                    "SELECT id, occurrence_count, first_seen "
                    "FROM error_events WHERE fingerprint = ? "
                    "ORDER BY last_seen DESC LIMIT 1",
                    (fingerprint,),
                ).fetchone()

                if existing is None:
                    conn.execute(
                        "INSERT INTO error_events "
                        "(fingerprint, category, severity, message, stack_trace, "
                        " session_id, provider, model, context_json, "
                        " timestamp, occurrence_count, first_seen, last_seen) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            fingerprint,
                            category,
                            severity,
                            message,
                            stack_trace,
                            session_id or None,
                            provider or None,
                            model or None,
                            _safe_json(ctx),
                            ts,
                            1,
                            ts,
                            ts,
                        ),
                    )
                else:
                    conn.execute(
                        "UPDATE error_events "
                        "SET occurrence_count = occurrence_count + 1, "
                        "    last_seen = ?, "
                        "    timestamp = ? "
                        "WHERE id = ?",
                        (ts, ts, existing["id"]),
                    )
                conn.commit()

        event = ErrorEvent(
            fingerprint=fingerprint,
            category=category,
            severity=severity,
            message=message,
            timestamp=ts,
            first_seen=existing["first_seen"] if existing else ts,
            last_seen=ts,
            occurrence_count=(existing["occurrence_count"] + 1) if existing else 1,
            stack_trace=stack_trace,
            session_id=session_id,
            provider=provider,
            model=model,
            context=ctx,
        )
        self._notify_observers(event)
        return event

    def record_exception(
        self,
        exc: BaseException,
        *,
        session_id: str = "",
        provider: str = "",
        model: str = "",
        severity: str = "error",
        category: str = "unknown",
        context: dict[str, Any] | None = None,
    ) -> ErrorEvent:
        """Convenience: capture an exception's type, message, and stack."""
        stack = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        msg = f"{type(exc).__name__}: {exc}"
        return self.record(
            category=category,
            message=msg,
            severity=severity,
            stack_trace=stack,
            session_id=session_id,
            provider=provider,
            model=model,
            context=context,
        )

    def query(
        self,
        *,
        category: str | None = None,
        session_id: str | None = None,
        limit: int = 50,
        min_severity: str = "info",
    ) -> list[ErrorEvent]:
        """Return recent events, optionally filtered."""
        severity_rank = {"fatal": 4, "error": 3, "warning": 2, "info": 1}
        min_rank = severity_rank.get(min_severity, 1)
        conditions: list[str] = []
        params: list[Any] = []
        if category:
            conditions.append("category = ?")
            params.append(category)
        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)
        sql = "SELECT * FROM error_events"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY last_seen DESC LIMIT ?"
        params.append(limit)

        with self._lock, self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        events: list[ErrorEvent] = []
        for r in rows:
            sev = r["severity"]
            if severity_rank.get(sev, 1) < min_rank:
                continue
            events.append(
                ErrorEvent(
                    fingerprint=r["fingerprint"],
                    category=r["category"],
                    severity=sev,
                    message=r["message"],
                    timestamp=r["timestamp"],
                    first_seen=r["first_seen"],
                    last_seen=r["last_seen"],
                    occurrence_count=r["occurrence_count"],
                    stack_trace=r["stack_trace"] or "",
                    session_id=r["session_id"] or "",
                    provider=r["provider"] or "",
                    model=r["model"] or "",
                    context=_parse_json(r["context_json"]),
                )
            )
        return events

    def stats(self) -> dict[str, Any]:
        """Return overall error statistics: total, by_category, by_severity."""
        with self._lock, self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM error_events").fetchone()[0]
            by_category = conn.execute(
                "SELECT category, COUNT(*) as n FROM error_events "
                "GROUP BY category ORDER BY n DESC"
            ).fetchall()
            by_severity = conn.execute(
                "SELECT severity, COUNT(*) as n FROM error_events "
                "GROUP BY severity ORDER BY n DESC"
            ).fetchall()
            top_fingerprints = conn.execute(
                "SELECT fingerprint, category, message, occurrence_count "
                "FROM error_events ORDER BY occurrence_count DESC LIMIT 5"
            ).fetchall()
        return {
            "total": total,
            "by_category": [dict(r) for r in by_category],
            "by_severity": [dict(r) for r in by_severity],
            "top_5": [dict(r) for r in top_fingerprints],
        }

    def prune(self, *, keep_fatal: bool = True) -> int:
        """Remove oldest non-fatal events beyond ``max_events`` cap.

        Returns the number of rows deleted.
        """
        with self._lock, self._conn() as conn:
            count = conn.execute("SELECT COUNT(*) FROM error_events").fetchone()[0]
            if count <= self.max_events:
                return 0

            target_count = int(self.max_events * 0.8)
            n_to_delete = count - target_count
            sql = (
                "DELETE FROM error_events WHERE id IN ("
                "SELECT id FROM error_events "
            )
            if keep_fatal:
                sql += "WHERE severity != 'fatal' "
            sql += "ORDER BY last_seen ASC LIMIT ?)"
            cur = conn.execute(sql, (n_to_delete,))
            conn.commit()
            return cur.rowcount

    def clear(self) -> int:
        """Remove ALL events. Returns the count removed."""
        with self._lock, self._conn() as conn:
            cur = conn.execute("DELETE FROM error_events")
            conn.commit()
            return cur.rowcount

    # ── Observers ───────────────────────────────────────────────

    def attach_observer(self, callback: Any) -> None:
        """Register *callback* to receive every recorded ErrorEvent.

        The callback signature is ``(event: ErrorEvent) -> None``.
        Exceptions raised by observers are logged but never propagate
        back into :meth:`record` (so a broken remote backend can never
        break the local error store).
        """
        with self._lock:
            if callback not in self._observers:
                self._observers.append(callback)

    def detach_observer(self, callback: Any) -> bool:
        """Remove a previously-attached observer. Returns True if found."""
        with self._lock:
            try:
                self._observers.remove(callback)
                return True
            except ValueError:
                return False

    def observer_count(self) -> int:
        with self._lock:
            return len(self._observers)

    def _notify_observers(self, event: ErrorEvent) -> None:
        """Fan out to observers outside the lock so they can't deadlock."""
        with self._lock:
            observers = list(self._observers)
        for cb in observers:
            try:
                cb(event)
            except Exception as exc:  # noqa: BLE001
                logger.warning("error_tracker: observer %r raised: %s", cb, exc)


def _safe_json(data: dict[str, Any]) -> str:
    """JSON-encode *data* defensively (never raises)."""
    try:
        import json
        return json.dumps(data, ensure_ascii=False, default=str)
    except Exception:
        return "{}"


def _parse_json(raw: str | None) -> dict[str, Any]:
    """Reverse of :func:`_safe_json`."""
    if not raw:
        return {}
    try:
        import json
        return json.loads(raw)
    except Exception:
        return {}