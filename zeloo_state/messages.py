"""Message persistence — stores and retrieves individual turns in the state DB.

This module complements ``zeloo_state/sessions.py`` by providing fine-grained
access to individual messages within a session.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Message:
    id: int
    session_id: str
    turn_id: int
    role: str
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    tool_results: list[dict[str, Any]] | None = None
    model: str | None = None
    tokens: int | None = None
    cost_usd: float | None = None
    timestamp: str | None = None


class MessageStore:
    """CRUD operations for individual messages within a session."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = Path.home() / ".Zeloo" / "state.db"
        self.db_path = Path(db_path)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                turn_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tool_calls TEXT,
                tool_results TEXT,
                model TEXT,
                tokens INTEGER,
                cost_usd REAL,
                timestamp TEXT DEFAULT (datetime('now')),
                UNIQUE(session_id, turn_id, role)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)"
        )
        conn.commit()
        conn.close()

    def add(
        self,
        session_id: str,
        turn_id: int,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_results: list[dict[str, Any]] | None = None,
        model: str | None = None,
        tokens: int | None = None,
        cost_usd: float | None = None,
    ) -> int:
        conn = sqlite3.connect(str(self.db_path))
        try:
            cursor = conn.execute(
                """
                INSERT OR REPLACE INTO messages
                    (session_id, turn_id, role, content, tool_calls, tool_results,
                     model, tokens, cost_usd)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    turn_id,
                    role,
                    content,
                    json.dumps(tool_calls) if tool_calls else None,
                    json.dumps(tool_results) if tool_results else None,
                    model,
                    tokens,
                    cost_usd,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            conn.close()

    def list_by_session(
        self,
        session_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Message]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT id, session_id, turn_id, role, content, tool_calls,
                       tool_results, model, tokens, cost_usd, timestamp
                FROM messages
                WHERE session_id = ?
                ORDER BY turn_id, id
                LIMIT ? OFFSET ?
                """,
                (session_id, limit, offset),
            ).fetchall()
            return [self._row_to_message(r) for r in rows]
        finally:
            conn.close()

    def get(self, message_id: int) -> Message | None:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM messages WHERE id = ?", (message_id,)
            ).fetchone()
            return self._row_to_message(row) if row else None
        finally:
            conn.close()

    def delete_session(self, session_id: str) -> int:
        conn = sqlite3.connect(str(self.db_path))
        try:
            cursor = conn.execute(
                "DELETE FROM messages WHERE session_id = ?", (session_id,)
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    def count_by_session(self, session_id: str) -> int:
        conn = sqlite3.connect(str(self.db_path))
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return row[0] if row else 0
        finally:
            conn.close()

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> Message:
        return Message(
            id=row["id"],
            session_id=row["session_id"],
            turn_id=row["turn_id"],
            role=row["role"],
            content=row["content"],
            tool_calls=json.loads(row["tool_calls"]) if row["tool_calls"] else None,
            tool_results=(
                json.loads(row["tool_results"]) if row["tool_results"] else None
            ),
            model=row["model"],
            tokens=row["tokens"],
            cost_usd=row["cost_usd"],
            timestamp=row["timestamp"],
        )
