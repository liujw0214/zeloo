"""Zeloo Agent state management — session storage with SQLite (WAL + FTS5)."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

_state_home_override: str | None = None


def _get_state_home() -> Path:
    from pathlib import Path

    if _state_home_override:
        return Path(_state_home_override)
    import os

    env = (
        os.environ.get("ZELOO_HOME")
        or os.environ.get("zeloo_HOME")
        or os.environ.get("zelooHOME")
    )
    if env:
        return Path(env)

    return Path.home() / ".Zeloo"


def _get_state_db_path() -> Path:
    return _get_state_home() / "state.db"


def set_state_home_override(path: str | None) -> None:
    global _state_home_override
    _state_home_override = path


def _iso_time(timestamp: float | None) -> str:
    """Convert a Unix timestamp to an ISO 8601 string (empty if None)."""
    if not timestamp:
        return ""
    import datetime

    return datetime.datetime.fromtimestamp(timestamp).isoformat(timespec="seconds")


class SessionDB:
    """SQLite-backed session storage with WAL mode and FTS5 for search."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else _get_state_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        cursor = self._conn.cursor()
        cursor.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT,
                platform TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                title TEXT
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT,
                tool_calls TEXT,
                tool_call_id TEXT,
                name TEXT,
                created_at REAL NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );

            CREATE TABLE IF NOT EXISTS trajectories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                turn_id INTEGER NOT NULL,
                data TEXT NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                content, content_rowid, tokenize='unicode61'
            );
            """
        )
        self._conn.commit()

    def create_session(self, session_id: str, user_id: str = "", platform: str = "cli") -> None:
        now = time.time()
        self._conn.execute(
            "INSERT OR REPLACE INTO sessions (session_id, user_id, platform, created_at, updated_at) "  # noqa: E501
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, user_id, platform, now, now),
        )
        self._conn.commit()

    def get_session(self, session_id: str) -> sqlite3.Row | None:
        cursor = self._conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        )
        return cursor.fetchone()

    def get_active_session(self, user_id: str, platform: str) -> sqlite3.Row | None:
        """Return the most recent session for a user/platform pair."""
        cursor = self._conn.execute(
            "SELECT session_id FROM sessions "
            "WHERE user_id = ? AND platform = ? "
            "ORDER BY updated_at DESC LIMIT 1",
            (user_id, platform),
        )
        return cursor.fetchone()

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return the most recent sessions as a list of dicts.

        Each dict includes session_id, platform, created_at (ISO string),
        updated_at, and message_count.
        """
        cursor = self._conn.execute(
            "SELECT s.session_id, s.platform, s.created_at, s.updated_at, "
            "COUNT(m.id) AS message_count "
            "FROM sessions s LEFT JOIN messages m ON s.session_id = m.session_id "
            "GROUP BY s.session_id ORDER BY s.updated_at DESC LIMIT ?",
            (limit,),
        )
        rows = cursor.fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            result.append({
                "session_id": row["session_id"],
                "platform": row["platform"],
                "created_at": _iso_time(row["created_at"]),
                "updated_at": _iso_time(row["updated_at"]),
                "message_count": row["message_count"],
            })
        return result

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str | None = None,
        tool_calls: Any | None = None,
        tool_call_id: str | None = None,
        name: str | None = None,
    ) -> None:
        now = time.time()
        tool_calls_json = json.dumps(tool_calls) if tool_calls else None
        cursor = self._conn.execute(
            "INSERT INTO messages (session_id, role, content, tool_calls, tool_call_id, name, created_at) "  # noqa: E501
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, role, content, tool_calls_json, tool_call_id, name, now),
        )
        # Index for FTS
        if content:
            self._conn.execute(
                "INSERT INTO messages_fts (rowid, content) VALUES (?, ?)",
                (cursor.lastrowid, content),
            )
        self._conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE session_id = ?", (now, session_id)
        )
        self._conn.commit()

    def get_messages(self, session_id: str, limit: int = 100) -> list[sqlite3.Row]:
        cursor = self._conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        )
        return list(reversed(cursor.fetchall()))

    def search_messages(self, session_id: str, query: str, limit: int = 20) -> list[sqlite3.Row]:
        cursor = self._conn.execute(
            "SELECT m.* FROM messages m "
            "JOIN messages_fts f ON m.id = f.rowid "
            "WHERE m.session_id = ? AND messages_fts MATCH ? "
            "ORDER BY m.id DESC LIMIT ?",
            (session_id, query, limit),
        )
        return cursor.fetchall()

    def save_trajectory(self, session_id: str, turn_id: int, data: Any) -> None:
        now = time.time()
        self._conn.execute(
            "INSERT INTO trajectories (session_id, turn_id, data, created_at) VALUES (?, ?, ?, ?)",
            (session_id, turn_id, json.dumps(data), now),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
