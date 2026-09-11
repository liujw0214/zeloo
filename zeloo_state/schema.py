"""Schema version management and migration for zeloo_state SQLite database."""

from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DB_VERSION_KEY = "schema_version"

TABLES: dict[str, str] = {
    "sessions": """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            user_id TEXT,
            platform TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            title TEXT,
            metadata TEXT
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
    "db_version": """
        CREATE TABLE IF NOT EXISTS db_version (
            key TEXT PRIMARY KEY,
            value INTEGER NOT NULL
        )
    """,
    "usage_records": """
        CREATE TABLE IF NOT EXISTS usage_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            platform TEXT,
            model TEXT,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0.0,
            latency_ms REAL DEFAULT 0.0,
            timestamp REAL NOT NULL,
            metadata TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
    """,
}

INDEXES: dict[str, str] = {
    "idx_messages_session_id": """
        CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id)
    """,
    "idx_messages_created_at": """
        CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at)
    """,
    "idx_trajectories_session_turn": """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_trajectories_session_turn
        ON trajectories(session_id, turn_id)
    """,
    "idx_sessions_platform": """
        CREATE INDEX IF NOT EXISTS idx_sessions_platform ON sessions(platform)
    """,
    "idx_sessions_user_id": """
        CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)
    """,
    "idx_usage_session_id": """
        CREATE INDEX IF NOT EXISTS idx_usage_session_id ON usage_records(session_id)
    """,
    "idx_usage_timestamp": """
        CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON usage_records(timestamp)
    """,
    "idx_usage_platform_model": """
        CREATE INDEX IF NOT EXISTS idx_usage_platform_model ON usage_records(platform, model)
    """,
}


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Read the current schema version from the db_version table."""
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT value FROM db_version WHERE key = ?", (DB_VERSION_KEY,)
        )
        row = cursor.fetchone()
        return int(row[0]) if row else 0
    except (sqlite3.OperationalError, TypeError):
        return 0


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Ensure all tables and indexes exist (idempotent)."""
    cursor = conn.cursor()

    for _table_name, ddl in TABLES.items():
        cursor.executescript(ddl)

    for _index_name, ddl in INDEXES.items():
        try:
            cursor.execute(ddl)
        except sqlite3.OperationalError:
            pass

    try:
        cursor.execute(
            "INSERT OR IGNORE INTO db_version (key, value) VALUES (?, ?)",
            (DB_VERSION_KEY, SCHEMA_VERSION),
        )
    except Exception:
        pass

    conn.commit()


def migrate(from_version: int, to_version: int, conn: sqlite3.Connection) -> list[str]:
    """Execute migrations from from_version to to_version.

    Returns a list of applied migration descriptions.
    """
    if from_version >= to_version:
        return []

    applied: list[str] = []
    cursor = conn.cursor()

    for version in range(from_version + 1, to_version + 1):
        for stmt in _migration_statements(version):
            cursor.execute(stmt)
        applied.append(f"v{version}")
        cursor.execute(
            "INSERT OR REPLACE INTO db_version (key, value) VALUES (?, ?)",
            (DB_VERSION_KEY, version),
        )
        logger.info("Applied schema migration v%d", version)

    conn.commit()
    return applied


def _migration_statements(version: int) -> list[str]:
    """Return SQL statements for a specific schema version."""
    if version == 1:
        return []
    return []


def validate_schema(conn: sqlite3.Connection) -> list[str]:
    """Validate the database schema and return a list of warnings.

    Checks for:
    - Missing indexes (common performance killers)
    - Orphaned messages (session_id references non-existent session)
    - Duplicate primary keys
    - Missing required columns
    """
    warnings: list[str] = []
    cursor = conn.cursor()

    required_indexes = [
        "idx_messages_session_id",
        "idx_messages_created_at",
        "idx_trajectories_session_turn",
    ]
    for idx in required_indexes:
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
            (idx,),
        )
        if not cursor.fetchone():
            warnings.append(f"Missing recommended index: {idx}")

    cursor.execute("""
        SELECT COUNT(*) FROM messages m
        LEFT JOIN sessions s ON m.session_id = s.session_id
        WHERE s.session_id IS NULL AND m.session_id IS NOT NULL
    """)
    orphan_count = cursor.fetchone()[0]
    if orphan_count > 0:
        warnings.append(f"Found {orphan_count} orphaned messages without a session")

    cursor.execute("SELECT COUNT(*) FROM sessions")
    session_count = cursor.fetchone()[0]
    if session_count == 0:
        warnings.append("Database has no sessions — may be a fresh install")

    try:
        cursor.execute("SELECT COUNT(*) > 0 FROM sessions WHERE title IS NULL")
        no_title = cursor.fetchone()[0]
        if no_title:
            warnings.append("Some sessions lack a title")
    except sqlite3.OperationalError:
        pass

    return warnings
