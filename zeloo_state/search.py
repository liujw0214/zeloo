"""Zeloo state — unified search facade across sessions and messages.

This subpackage exposes the :class:`MessageSearch` class from the top-level
``zeloo_state_search`` module and adds convenience functions for common
cross-session search patterns.

Architecture::

    zeloo_state/search.py        # This file — facade + re-exports
            │
            └── zeloo_state_search.py   # Top-level: MessageSearch (FTS5 + semantic)

Usage::

    from zeloo_state.search import (
        MessageSearch,
        SearchResult,
        search_all,
        get_recent_sessions,
    )

    search = MessageSearch(Path("~/.Zeloo/state.db"))
    results = search.search("configure terminal backend", session_id="s1", mode="fts")
    for r in results:
        print(f"[{r.session_id}] {r.content[:80]}...")
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zeloo_state_search import MessageSearch as _MessageSearch
from zeloo_state_search import SearchResult as _SearchResult

MessageSearch = _MessageSearch
SearchResult = _SearchResult


@dataclass
class SessionSearchResult:
    """A session-level search result (grouped by session)."""

    session_id: str
    platform: str | None
    message_count: int
    snippet: str
    relevance: float


def search_all(
    db_path: Path,
    query: str,
    limit: int = 20,
    mode: str = "fts",
) -> list[SearchResult]:
    """Search across all sessions (no session filter).

    Args:
        db_path: Path to the state database.
        query: Search query string.
        limit: Maximum results to return.
        mode: ``"fts"`` (keyword) or ``"semantic"`` (embedding).

    Returns:
        List of :class:`SearchResult` ordered by relevance.
    """
    search = MessageSearch(db_path)
    return search.search(query, session_id=None, limit=limit, mode=mode)


def get_recent_sessions(
    db_path: Path,
    limit: int = 20,
    platform: str | None = None,
) -> list[dict[str, Any]]:
    """Return recently active sessions.

    Args:
        db_path: Path to the state database.
        limit: Maximum number of sessions to return.
        platform: Optional platform filter.

    Returns:
        List of session dicts ordered by ``updated_at`` descending.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        if platform:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE platform = ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (platform, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def iter_search_results(
    db_path: Path,
    query: str,
    session_ids: list[str] | None = None,
    limit_per_session: int = 5,
) -> Iterator[tuple[str, SearchResult]]:
    """Search multiple sessions and yield results as (session_id, result) pairs.

    Args:
        db_path: Path to the state database.
        query: Search query string.
        session_ids: List of sessions to search. If None, searches all.
        limit_per_session: Maximum results per session.

    Yields:
        Tuples of (session_id, SearchResult).
    """
    search = MessageSearch(db_path)

    if session_ids is None:
        sessions = get_recent_sessions(db_path, limit=50)
        session_ids = [s["session_id"] for s in sessions]

    for sid in session_ids:
        results = search.search(query, session_id=sid, limit=limit_per_session)
        for result in results:
            yield (sid, result)
