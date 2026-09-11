"""FTS5 full-text search extension for zeloo_state."""

from __future__ import annotations

import logging
import re
import sqlite3

logger = logging.getLogger(__name__)

_TOKENIZE_ARG = "tokenize='unicode61'"


def enable_fts(conn: sqlite3.Connection, table: str) -> None:
    """Enable FTS5 on a text column of an existing table."""
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cursor.fetchall()]
    if not columns:
        raise ValueError(f"Table {table} has no columns")

    fts_table = f"{table}_fts"
    cursor.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {fts_table} "
        f"USING fts5({', '.join(columns)}, {repr(_TOKENIZE_ARG)})"
    )
    conn.commit()


def build_fts_index(
    conn: sqlite3.Connection,
    source_table: str,
    pk_column: str = "id",
) -> int:
    """Rebuild FTS index from source table content.

    Returns the number of rows indexed.
    """
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM {source_table}")
    columns = [description[0] for description in cursor.description]
    if not columns:
        return 0

    fts_table = f"{source_table}_fts"
    try:
        cursor.execute(f"DROP TABLE IF EXISTS {fts_table}")
        cursor.execute(
            f"CREATE VIRTUAL TABLE {fts_table} USING fts5("
            + ", ".join(columns)
            + f", {repr(_TOKENIZE_ARG)})"
        )
        cursor.execute(f"SELECT {pk_column}, * FROM {source_table}")
        rows = cursor.fetchall()
        for row in rows:
            cursor.execute(f"INSERT INTO {fts_table} VALUES (?, "
            + ", ".join(["?"] * len(columns))
            + ")", row)
        conn.commit()
        logger.info("FTS index built for %s: %d rows", source_table, len(rows))
        return len(rows)
    except sqlite3.OperationalError as e:
        logger.warning("FTS build skipped for %s: %s", source_table, e)
        return 0


def search_fts(
    conn: sqlite3.Connection,
    table: str,
    query: str,
    columns: list[str] | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """Search FTS5 virtual table and return ranked results."""
    if not query.strip():
        return []

    fts_table = f"{table}_fts"
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
        (fts_table,)
    )
    if not cursor.fetchone()[0]:
        return []

    if columns:
        col_list = ", ".join(columns)
    else:
        col_list = "*"

    try:
        cursor.execute(
            f"SELECT rowid, {col_list} FROM {fts_table} "
            f"WHERE {fts_table} MATCH ? ORDER BY rank LIMIT ? OFFSET ?",
            (query, limit, offset),
        )
        results = cursor.fetchall()
        return [dict(row) for row in results]
    except sqlite3.OperationalError:
        return []


def highlight_fts_result(
    text: str, query: str, snippet_size: int = 40
) -> str:
    """Highlight query terms in text using FTS5-style markers."""
    if not query or not text:
        return text
    terms = query.split()
    highlighted = text
    for term in terms:
        escaped = re.escape(term)
        highlighted = re.sub(
            f"({escaped})",
            r"**\1**",
            highlighted,
            flags=re.IGNORECASE,
        )
    return highlighted
