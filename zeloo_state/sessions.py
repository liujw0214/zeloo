"""Session lifecycle management — archive, merge, split, and statistics.

Extends :class:`zeloo_state.SessionDB` with session-level operations:
archive (mark inactive + compress), restore, merge (combine sessions), split,
delete, and statistical summaries.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SessionStats:
    total_sessions: int = 0
    total_messages: int = 0
    total_trajectories: int = 0
    sessions_by_platform: dict[str, int] = field(default_factory=dict)
    sessions_by_date: dict[str, int] = field(default_factory=dict)
    message_count_by_platform: dict[str, int] = field(default_factory=dict)
    last_updated: str = ""


@dataclass
class ArchiveEntry:
    session_id: str
    archived_at: str
    message_count: int
    trajectory_count: int
    platform: str
    title: str


class SessionManager:
    """Session lifecycle: archive / restore / merge / split / delete / stats.

    All operations are atomic (transaction-wrapped) unless noted.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        from zeloo_state import SessionDB
        self._db = SessionDB(db_path)

    # ── Archive ───────────────────────────────────────────────────────────────

    def archive_session(
        self,
        session_id: str,
        archive_path: Path | str | None = None,
        compress: bool = True,
    ) -> Path:
        """Archive *session_id* to a JSONL bundle and delete it from the DB.

        Returns the path to the archive file.
        Raises ``SessionNotFoundError`` if the session does not exist.
        """
        from zeloo_state.errors import SessionNotFoundError

        session = self._db.get_session(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)

        messages = self._db.get_messages(session_id)
        trajectories = self._db._conn.execute(
            "SELECT turn_id, data, created_at FROM trajectories WHERE session_id = ? ORDER BY turn_id",  # noqa: E501
            (session_id,),
        ).fetchall()

        session_data = dict(session)

        bundle: dict[str, Any] = {
            "schema_version": 1,
            "archived_at": datetime.now().isoformat(),
            "session": session_data,
            "messages": [
                {k: v for k, v in row.items()} for row in messages
            ],
            "trajectories": [
                {
                    "turn_id": row["turn_id"],
                    "data": json.loads(row["data"]) if isinstance(row["data"], str) else row["data"],  # noqa: E501
                    "created_at": row["created_at"],
                }
                for row in trajectories
            ],
        }

        path = (
            Path(archive_path)
            if archive_path
            else self._db.db_path.parent / "archives" / f"{session_id}.Zeloo-archive.jsonl"
        )

        if compress:
            path = Path(str(path).replace(".jsonl", ".zst"))
            try:
                import zstandard
                ctx = zstandard.ZstdCompressor()
                data = json.dumps(bundle, ensure_ascii=False).encode("utf-8")
                with open(path, "wb") as fh:
                    fh.write(ctx.compress(data))
            except ImportError:
                logger.warning("zstandard not available, saving as JSONL")
                path = Path(str(path).replace(".zst", ".jsonl"))
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(bundle, fh, ensure_ascii=False)
        else:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(bundle, fh, ensure_ascii=False)

        self._delete_session_data(session_id)
        logger.info("Archived session %s → %s (%d messages, %d trajectories)",
                    session_id, path, len(messages), len(trajectories))
        return path

    def _delete_session_data(self, session_id: str) -> None:
        conn = self._db._conn
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM trajectories WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        conn.commit()

    # ── Restore ────────────────────────────────────────────────────────────

    def restore_session(self, archive_path: Path | str) -> str:
        """Restore a session from an archive bundle.

        Returns the new (or existing) session_id.
        """
        path = Path(archive_path)
        if path.suffix == ".zst":
            try:
                import zstandard as zstd
                dctx = zstd.ZstdDecompressor()
                raw = dctx.decompress(path.read_bytes())
                bundle = json.loads(raw.decode("utf-8"))
            except ImportError:
                bundle = json.loads(path.read_text(encoding="utf-8"))
        else:
            bundle = json.loads(path.read_text(encoding="utf-8"))

        session_row = bundle["session"]
        session_id = session_row["session_id"]

        conn = self._db._conn
        existing = conn.execute(
            "SELECT session_id FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO sessions (session_id, user_id, platform, created_at, updated_at, title) "  # noqa: E501
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    session_row.get("user_id", ""),
                    session_row.get("platform", "cli"),
                    session_row.get("created_at", time.time()),
                    time.time(),
                    session_row.get("title", ""),
                ),
            )

        for msg in bundle.get("messages", []):
            tool_calls = msg.get("tool_calls")
            if isinstance(tool_calls, str):
                tool_calls = json.loads(tool_calls)
            self._db.save_message(
                session_id=session_id,
                role=msg["role"],
                content=msg.get("content"),
                tool_calls=tool_calls,
                tool_call_id=msg.get("tool_call_id"),
                name=msg.get("name"),
            )

        for traj in bundle.get("trajectories", []):
            self._db.save_trajectory(
                session_id=session_id,
                turn_id=traj["turn_id"],
                data=traj["data"],
            )

        conn.commit()
        logger.info("Restored session %s from %s", session_id, path)
        return session_id

    # ── Merge ────────────────────────────────────────────────────────────────

    def merge_sessions(
        self,
        target_session_id: str,
        source_session_ids: list[str],
        delete_sources: bool = True,
    ) -> int:
        """Merge *source_session_ids* into *target_session_id*.

        Moves all messages and trajectories from each source into the target.
        If *delete_sources* is True, removes the source sessions after merging.

        Returns the number of messages merged.
        """
        from zeloo_state.errors import SessionNotFoundError

        if not source_session_ids:
            return 0

        target = self._db.get_session(target_session_id)
        if target is None:
            raise SessionNotFoundError(target_session_id)

        conn = self._db._conn
        merged = 0
        for sid in source_session_ids:
            src = self._db.get_session(sid)
            if src is None:
                logger.warning("merge_sessions: source session %s not found, skipping", sid)
                continue

            src_msgs = conn.execute(
                "SELECT role, content, tool_calls, tool_call_id, name FROM messages WHERE session_id = ?",  # noqa: E501
                (sid,),
            ).fetchall()
            src_trajs = conn.execute(
                "SELECT turn_id, data FROM trajectories WHERE session_id = ?",
                (sid,),
            ).fetchall()

            now = time.time()
            for msg in src_msgs:
                tool_calls = msg["tool_calls"]
                if isinstance(tool_calls, str):
                    tool_calls = json.loads(tool_calls)
                conn.execute(
                    "INSERT INTO messages "
                    "(session_id, role, content, tool_calls, tool_call_id, name, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        target_session_id,
                        msg["role"],
                        msg.get("content"),
                        json.dumps(tool_calls) if tool_calls else None,
                        msg.get("tool_call_id"),
                        msg.get("name"),
                        now,
                    ),
                )
                merged += 1

            for traj in src_trajs:
                conn.execute(
                    "INSERT INTO trajectories (session_id, turn_id, data, created_at) VALUES (?, ?, ?, ?)",  # noqa: E501
                    (target_session_id, traj["turn_id"], traj["data"], now),
                )

            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                (now, target_session_id),
            )

            if delete_sources:
                self._delete_session_data(sid)
                logger.info("Merged %d messages from %s → %s (deleted source)",
                            len(src_msgs), sid, target_session_id)
            else:
                logger.info("Merged %d messages from %s → %s (kept source)",
                            len(src_msgs), sid, target_session_id)

        conn.commit()
        return merged

    # ── Statistics ────────────────────────────────────────────────────────

    def get_stats(self) -> SessionStats:
        """Return aggregate statistics across all sessions."""
        conn = self._db._conn

        total_sessions = conn.execute(
            "SELECT COUNT(*) FROM sessions"
        ).fetchone()[0]
        total_messages = conn.execute(
            "SELECT COUNT(*) FROM messages"
        ).fetchone()[0]
        total_trajectories = conn.execute(
            "SELECT COUNT(*) FROM trajectories"
        ).fetchone()[0]

        by_platform_rows = conn.execute(
            "SELECT platform, COUNT(*) FROM sessions GROUP BY platform"
        ).fetchall()
        by_platform = {row["platform"]: row[1] for row in by_platform_rows}

        msg_by_platform_rows = conn.execute(
            "SELECT s.platform, COUNT(m.id) "
            "FROM sessions s LEFT JOIN messages m ON s.session_id = m.session_id "
            "GROUP BY s.platform"
        ).fetchall()
        msg_by_platform = {row["platform"]: row[1] for row in msg_by_platform_rows}

        date_rows = conn.execute(
            "SELECT date(created_at, 'unixepoch') AS d, COUNT(*) "
            "FROM sessions GROUP BY d ORDER BY d DESC LIMIT 30"
        ).fetchall()
        by_date = {row["d"]: row[1] for row in date_rows}

        return SessionStats(
            total_sessions=total_sessions,
            total_messages=total_messages,
            total_trajectories=total_trajectories,
            sessions_by_platform=by_platform,
            sessions_by_date=by_date,
            message_count_by_platform=msg_by_platform,
            last_updated=datetime.now().isoformat(),
        )

    def list_archives(self, archive_dir: Path | str | None = None) -> list[ArchiveEntry]:
        """List all session archives in *archive_dir* (default: ``~/.Zeloo/archives/``)."""
        if archive_dir is None:
            archive_dir = self._db.db_path.parent / "archives"
        else:
            archive_dir = Path(archive_dir)

        if not archive_dir.exists():
            return []

        entries: list[ArchiveEntry] = []
        for path in sorted(archive_dir.glob("*.Zeloo-archive*")):
            try:
                if path.suffix == ".zst":
                    try:
                        import zstandard as zstd
                        dctx = zstd.ZstdDecompressor()
                        raw = dctx.decompress(path.read_bytes())
                        session = json.loads(raw.decode("utf-8")).get("session", {})
                    except ImportError:
                        session = {}
                else:
                    session = json.loads(path.read_text(encoding="utf-8")).get("session", {})
                entries.append(
                    ArchiveEntry(
                        session_id=session.get("session_id", path.stem),
                        archived_at=str(path.stat().st_mtime),
                        message_count=0,
                        trajectory_count=0,
                        platform=session.get("platform", "unknown"),
                        title=session.get("title", ""),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not read archive %s: %s", path, exc)

        return entries
