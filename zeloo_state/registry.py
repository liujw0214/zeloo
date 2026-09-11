"""Session registry — query session metadata without loading full state."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SessionRecord:
    """Lightweight session metadata record."""

    session_id: str
    platform: str
    user_id: str | None = None
    created_at: float = 0.0
    updated_at: float = 0.0
    title: str | None = None
    message_count: int = 0
    turn_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "platform": self.platform,
            "user_id": self.user_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "title": self.title,
            "message_count": self.message_count,
            "turn_count": self.turn_count,
        }


class SessionRegistry:
    """Read-only registry for session metadata queries."""

    def __init__(self, db_path: str | None = None):
        from agent.zeloo_constants import get_state_db_path

        self.db_path = db_path or str(get_state_db_path())

    def _connect(self) -> sqlite3.Connection:
        """Create a read connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def query(
        self,
        platform: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[SessionRecord]:
        """Query sessions by platform."""
        conn = self._connect()
        cur = conn.cursor()
        sql = "SELECT * FROM sessions"
        params: list[Any] = []
        if platform:
            sql += " WHERE platform = ?"
            params.append(platform)
        sql += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cur.execute(sql, params)
        rows = cur.fetchall()
        conn.close()
        return [self._row_to_record(row) for row in rows]

    def _row_to_record(self, row: sqlite3.Row) -> SessionRecord:
        """Convert a database row to SessionRecord."""
        session_id = str(row["session_id"])
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ?", (session_id,)
        )
        message_count = cur.fetchone()[0] if cur.fetchone() else 0
        cur.execute(
            "SELECT COUNT(DISTINCT turn_id) FROM trajectories WHERE session_id = ?", (session_id,)
        )
        turn_count = cur.fetchone()[0] if cur.fetchone() else 0
        conn.close()
        return SessionRecord(
            session_id=session_id,
            platform=str(row["platform"] or "unknown"),
            user_id=row["user_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            title=row["title"],
            message_count=message_count,
            turn_count=turn_count,
        )

    def count(self, platform: str | None = None) -> int:
        """Count sessions optionally filtered by platform."""
        conn = self._connect()
        cur = conn.cursor()
        sql = "SELECT COUNT(*) FROM sessions"
        params: list[Any] = []
        if platform:
            sql += " WHERE platform = ?"
            params.append(platform)
        cur.execute(sql, params)
        count = cur.fetchone()[0]
        conn.close()
        return count
