"""Dead Letter Queue — persistent storage for failed tasks with retry support."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat() if dt is not None else None


def _from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


@dataclass
class DLQEntry:
    """A persisted dead-letter entry."""

    id: str
    payload: dict[str, Any]
    error: str
    failed_at: datetime
    attempts: int
    last_retry_at: datetime | None
    metadata: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending | resolved | abandoned

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> DLQEntry:
        return cls(
            id=row["id"],
            payload=json.loads(row["payload"]) if row["payload"] else {},
            error=row["error"],
            failed_at=_from_iso(row["failed_at"]) or _utcnow(),
            attempts=row["attempts"],
            last_retry_at=_from_iso(row["last_retry_at"]),
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            status=row["status"],
        )


class DeadLetterQueue:
    """Persistent DLQ for failed tasks (SQLite-backed)."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS dlq_entries (
        id            TEXT PRIMARY KEY,
        payload       TEXT NOT NULL,
        error         TEXT NOT NULL,
        failed_at     TEXT NOT NULL,
        attempts      INTEGER NOT NULL DEFAULT 1,
        last_retry_at TEXT,
        metadata      TEXT,
        status        TEXT NOT NULL DEFAULT 'pending'
    );
    CREATE INDEX IF NOT EXISTS idx_dlq_status ON dlq_entries(status);
    CREATE INDEX IF NOT EXISTS idx_dlq_failed_at ON dlq_entries(failed_at);
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or Path.home() / ".Zeloo" / "dlq.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            self.db_path,
            detect_types=sqlite3.PARSE_DECLTYPES,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(self.SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def enqueue(
        self,
        payload: dict[str, Any],
        error: str,
        attempts: int = 1,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Record a failed task in the DLQ."""
        entry_id = uuid.uuid4().hex
        now = _iso(_utcnow())
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO dlq_entries
                    (id, payload, error, failed_at, attempts, metadata, status)
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    entry_id,
                    json.dumps(payload, ensure_ascii=False, default=str),
                    error[:2000],
                    now,
                    max(1, attempts),
                    json.dumps(metadata or {}, ensure_ascii=False, default=str),
                ),
            )
            self._conn.commit()
        logger.warning("DLQ enqueued id=%s error=%s", entry_id, error)
        return entry_id

    def dequeue(self, entry_id: str) -> bool:
        """Mark an entry as resolved (consumed)."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE dlq_entries SET status='resolved' WHERE id=?",
                (entry_id,),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def list_pending(self, limit: int = 100) -> list[DLQEntry]:
        """List pending entries ordered by oldest first."""
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT * FROM dlq_entries
                WHERE status = 'pending'
                ORDER BY failed_at ASC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cur.fetchall()
        return [DLQEntry.from_row(r) for r in rows]

    def get(self, entry_id: str) -> DLQEntry | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM dlq_entries WHERE id=?", (entry_id,)
            )
            row = cur.fetchone()
        return DLQEntry.from_row(row) if row else None

    def retry(self, entry_id: str, handler: Callable[[dict], Any]) -> bool:
        """Run handler against the entry's payload.

        On success the entry is marked resolved; on failure attempts is
        incremented and last_retry_at is bumped.
        """
        entry = self.get(entry_id)
        if entry is None or entry.status != "pending":
            return False
        try:
            handler(entry.payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "DLQ retry failed id=%s error=%s", entry_id, exc
            )
            self._bump_retry(entry_id, entry.attempts + 1)
            return False
        self.dequeue(entry_id)
        return True

    def _bump_retry(self, entry_id: str, attempts: int) -> None:
        with self._lock:
            self._conn.execute(
                """
                UPDATE dlq_entries
                SET attempts=?, last_retry_at=?
                WHERE id=?
                """,
                (attempts, _iso(_utcnow()), entry_id),
            )
            self._conn.commit()

    def retry_all(
        self,
        handler: Callable[[dict], Any],
        max_age_days: int = 30,
    ) -> int:
        """Retry every pending entry younger than ``max_age_days``.

        Returns the number of entries successfully processed.
        """
        cutoff = _iso(_utcnow() - timedelta(days=max_age_days))
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT id FROM dlq_entries
                WHERE status='pending' AND failed_at >= ?
                ORDER BY failed_at ASC
                """,
                (cutoff,),
            )
            ids = [row["id"] for row in cur.fetchall()]
        success = 0
        for entry_id in ids:
            if self.retry(entry_id, handler):
                success += 1
        return success

    def cleanup(self, older_than_days: int = 90) -> int:
        """Delete resolved entries older than ``older_than_days``."""
        cutoff = _iso(_utcnow() - timedelta(days=older_than_days))
        with self._lock:
            cur = self._conn.execute(
                """
                DELETE FROM dlq_entries
                WHERE status='resolved' AND failed_at < ?
                """,
                (cutoff,),
            )
            self._conn.commit()
            return cur.rowcount

    def abandon(self, entry_id: str) -> bool:
        """Mark an entry as abandoned (kept but no longer retried)."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE dlq_entries SET status='abandoned' WHERE id=?",
                (entry_id,),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending,
                    SUM(CASE WHEN status='resolved' THEN 1 ELSE 0 END) AS resolved,
                    SUM(CASE WHEN status='abandoned' THEN 1 ELSE 0 END) AS abandoned
                FROM dlq_entries
                """
            )
            row = cur.fetchone()
        return {
            "db_path": str(self.db_path),
            "total": row["total"] or 0,
            "pending": row["pending"] or 0,
            "resolved": row["resolved"] or 0,
            "abandoned": row["abandoned"] or 0,
        }


__all__ = [
    "DLQEntry",
    "DeadLetterQueue",
]