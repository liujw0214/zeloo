"""Zeloo state database schema — versioned definitions and migrations.

Centralizes the SQLite schema so that ``zeloo_state.SessionDB`` and any
tool that touches the state database share a single source of truth. Supports
schema versioning and forward migrations so existing databases can be upgraded
in place without data loss.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)

#: Current schema version. Bump when TABLES/INDEXES change and add a migration.
SCHEMA_VERSION = 1

#: Base table definitions (version 1). Matches the schema historically used by
#: ``SessionDB._init_schema`` so existing databases are recognised as v1.
TABLES: dict[str, str] = {
    "sessions": """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            user_id TEXT,
            platform TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            title TEXT
        )
    """,
    "messages": """
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
        )
    """,
    "trajectories": """
        CREATE TABLE IF NOT EXISTS trajectories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            turn_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            created_at REAL NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
    """,
    "messages_fts": """
        CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
            content, content_rowid, tokenize='unicode61'
        )
    """,
}

#: Secondary indexes for performance.
INDEXES: dict[str, str] = {
    "idx_messages_session_id":
        "CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id)",
    "idx_messages_created_at":
        "CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at)",
    "idx_trajectories_session_turn": (
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_trajectories_session_turn "
        "ON trajectories(session_id, turn_id)"
    ),
}

#: Maps a target version to a callable that migrates ``from_version`` → it.
#: Each migration is idempotent and safe to run on an already-migrated DB.
_MIGRATIONS: dict[int, Any] = {}


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Return the schema version recorded in the database.

    Reads from the ``db_version`` table. Returns ``0`` when the table or the
    version row is missing (e.g. a legacy database created before versioning).
    """
    try:
        cur = conn.execute(
            "SELECT version FROM db_version ORDER BY applied_at DESC LIMIT 1"
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0
    except sqlite3.OperationalError:
        # db_version table does not exist yet — treat as pre-versioning.
        return 0


def _record_version(conn: sqlite3.Connection, version: int) -> None:
    """Persist the current schema version into the ``db_version`` table."""
    import time

    conn.execute(
        "CREATE TABLE IF NOT EXISTS db_version ("
        "version INTEGER NOT NULL, "
        "applied_at REAL NOT NULL"
        ")"
    )
    conn.execute(
        "INSERT INTO db_version (version, applied_at) VALUES (?, ?)",
        (version, time.time()),
    )


def ensure_schema(conn: sqlite3.Connection) -> int:
    """Create or upgrade the schema to :data:`SCHEMA_VERSION`.

    Returns the version the database is now at. Safe to call repeatedly.
    """
    current = get_schema_version(conn)

    # Always (re)create tables and indexes — statements use IF NOT EXISTS,
    # so this is idempotent and harmless on an already-initialised DB.
    for ddl in TABLES.values():
        conn.execute(ddl)
    for ddl in INDEXES.values():
        conn.execute(ddl)

    # Run forward migrations for any skipped versions.
    for target in sorted(_MIGRATIONS):
        if current < target <= SCHEMA_VERSION:
            logger.info("Migrating state schema v%d → v%d", current, target)
            _MIGRATIONS[target](conn)
            current = target

    if current < SCHEMA_VERSION:
        # No explicit migrations needed; just bump the recorded version.
        current = SCHEMA_VERSION

    _record_version(conn, current)
    conn.commit()
    return current


def list_tables() -> list[str]:
    """Return the names of all tables defined in this schema."""
    return list(TABLES.keys())


def list_indexes() -> list[str]:
    """Return the names of all indexes defined in this schema."""
    return list(INDEXES.keys())
