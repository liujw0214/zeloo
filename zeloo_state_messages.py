"""Zeloo state — extended message operations.

Provides cursor-based pagination, JSON export, and JSON import for the
messages table managed by :class:`zeloo_state.SessionDB`.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from zeloo_state_schema import ensure_schema


@dataclass
class MessagePage:
    """A single page of messages returned by :func:`get_messages_paginated`."""

    messages: list[dict[str, Any]]
    next_before: float | None
    has_more: bool


@dataclass
class ExportMetadata:
    """Metadata attached to a JSON export file."""

    schema_version: int
    exported_at: str
    message_count: int
    session_id: str | None = None


@dataclass
class MessageExporter:
    """Export messages from a session (or all sessions) to JSONL or JSON."""

    db_path: Path

    def export_session(
        self,
        session_id: str,
        output_path: Path | None = None,
        format: str = "jsonl",
    ) -> Path:
        """Export all messages for ``session_id`` to a JSONL file.

        Args:
            session_id: The session whose messages to export.
            output_path: Destination file. If ``None``, derives
                ``<session_id>_<timestamp>.jsonl`` next to the DB.
            format: ``"jsonl"`` (one JSON object per line) or ``"json"``
                (a single JSON array). Defaults to ``"jsonl"``.

        Returns:
            The path to the written file.
        """
        conn = sqlite3.connect(str(self.db_path))
        ensure_schema(conn)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, session_id, role, content, tool_calls, tool_call_id, "
            "name, created_at FROM messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        conn.close()

        messages = [self._row_to_dict(row) for row in rows]
        now = datetime.now(UTC).isoformat(timespec="seconds")
        metadata = ExportMetadata(
            schema_version=1,
            exported_at=f"{now}Z",
            message_count=len(messages),
            session_id=session_id,
        )

        if output_path is None:
            ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            ext = "jsonl" if format == "jsonl" else "json"
            output_path = self.db_path.parent / f"{session_id}_{ts}.{ext}"

        payload = {
            "metadata": {
                "schema_version": metadata.schema_version,
                "exported_at": metadata.exported_at,
                "message_count": metadata.message_count,
                "session_id": metadata.session_id,
            },
            "messages": messages,
        }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        if format == "jsonl":
            lines = [json.dumps(msg) for msg in messages]
            output_path.write_text("\n".join(lines), encoding="utf-8")
        else:
            output_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        return output_path

    def export_all(self, output_path: Path) -> Path:
        """Export every message in the database to a single JSONL file.

        Args:
            output_path: Destination file.

        Returns:
            The path to the written file.
        """
        conn = sqlite3.connect(str(self.db_path))
        ensure_schema(conn)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT session_id, id, role, content, tool_calls, tool_call_id, "
            "name, created_at FROM messages ORDER BY id ASC"
        ).fetchall()
        conn.close()

        lines = [json.dumps(self._row_to_dict(row)) for row in rows]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines), encoding="utf-8")
        return output_path

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d: dict[str, Any] = dict(row)
        d["created_at_iso"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        return d


def get_messages_paginated(
    db_path: Path,
    session_id: str,
    before: float | None = None,
    limit: int = 20,
) -> MessagePage:
    """Return a page of messages for ``session_id`` ordered by ``id`` descending.

    This function uses cursor-based pagination (``before`` = ``created_at`` of
    the last item on the previous page) to avoid offset drift when rows are
    inserted concurrently.

    Args:
        db_path: Path to the state database.
        session_id: Session to fetch messages for.
        before: Return messages with ``created_at < before``. Pass ``None``
            (the default) to fetch the most recent ``limit`` messages.
        limit: Maximum number of messages to return. Defaults to 20.

    Returns:
        A :class:`MessagePage` containing up to ``limit`` messages, a
        ``next_before`` timestamp to pass for the next page, and a ``has_more``
        flag indicating whether more rows exist.
    """
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    ensure_schema(conn)
    conn.row_factory = sqlite3.Row

    if before is not None:
        query = (
            "SELECT id, session_id, role, content, tool_calls, tool_call_id, "
            "name, created_at FROM messages "
            "WHERE session_id = ? AND created_at < ? "
            "ORDER BY id DESC LIMIT ?"
        )
        params: tuple[str, float, int] = (session_id, before, limit + 1)
    else:
        query = (
            "SELECT id, session_id, role, content, tool_calls, tool_call_id, "
            "name, created_at FROM messages "
            "WHERE session_id = ? "
            "ORDER BY id DESC LIMIT ?"
        )
        params = (session_id, limit + 1)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    if len(rows) > limit:
        rows = rows[:limit]
        has_more = True
        next_before = float(rows[-1]["created_at"])
    else:
        has_more = False
        next_before = None

    messages = [dict(row) for row in reversed(rows)]
    return MessagePage(messages=messages, next_before=next_before, has_more=has_more)


def import_messages(
    db_path: Path,
    source: Path,
    session_id: str,
    replace: bool = False,
) -> int:
    """Import JSONL messages into ``session_id``.

    Args:
        db_path: Path to the destination state database.
        source: A JSONL file (one JSON object per line).
        session_id: Target session for imported messages.
        replace: If ``True``, delete all existing messages for the session
            before importing. Defaults to ``False`` (append mode).

    Returns:
        The number of messages imported.

    Raises:
        ValueError: If the file format is invalid.
    """
    if not source.exists():
        raise FileNotFoundError(f"Source file not found: {source}")

    lines = source.read_text(encoding="utf-8").splitlines()
    if not lines:
        return 0

    messages: list[dict[str, Any]] = []
    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            messages.append(json.loads(stripped))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid JSON on line {lineno}: {exc}"
            ) from exc

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    ensure_schema(conn)
    conn.row_factory = sqlite3.Row

    if replace:
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))

    import_time = datetime.now(UTC).timestamp()
    imported = 0
    for msg in messages:
        role = str(msg.get("role", ""))
        content = msg.get("content")
        tool_calls = msg.get("tool_calls")
        tool_call_id = msg.get("tool_call_id")
        name = msg.get("name")
        created_at = msg.get("created_at")
        if created_at is None:
            created_at = import_time

        cursor = conn.execute(
            "INSERT INTO messages (session_id, role, content, tool_calls, "
            "tool_call_id, name, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                role,
                content,
                json.dumps(tool_calls) if tool_calls else None,
                tool_call_id,
                name,
                float(created_at),
            ),
        )
        if content:
            conn.execute(
                "INSERT INTO messages_fts (rowid, content) VALUES (?, ?)",
                (cursor.lastrowid, content),
            )
        imported += 1

    conn.commit()
    conn.close()
    return imported
