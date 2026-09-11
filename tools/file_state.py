"""Track file state changes for undo/redo and conflict detection."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class FileSnapshot:
    """Represents a snapshot of file state."""
    snapshot_id: str
    path: str
    content_hash: str
    created_at: float
    content: str = ""
    size: int = 0
    line_count: int = 0


class FileStateTracker:
    """Track file state changes for undo/redo and conflict detection.

    Stores snapshots in SQLite for persistence and provides methods
    to create, compare, and restore file states.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        """Initialize the file state tracker.

        Args:
            db_path: Optional path to SQLite database. Uses in-memory DB if None.
        """
        if db_path is None:
            db_path = Path.home() / ".zeloo" / "file_state.db"

        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the SQLite database."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                snapshot_id TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                created_at REAL NOT NULL,
                content TEXT,
                size INTEGER DEFAULT 0,
                line_count INTEGER DEFAULT 0
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_path ON snapshots(path)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_created_at ON snapshots(created_at)
        """)
        self._conn.commit()

    def snapshot(self, path: Path) -> dict[str, Any]:
        """Create a snapshot of the current file state.

        Args:
            path: Path to the file to snapshot.

        Returns:
            Dictionary with snapshot information.
        """
        with self._lock:
            if self._conn is None:
                return {"success": False, "error": "Database not initialized"}

            try:
                normalized = str(path.resolve())
                if not path.exists():
                    return {"success": False, "error": "File does not exist"}

                content = path.read_text(encoding="utf-8", errors="replace")
                size = len(content.encode("utf-8"))
                line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)

                from tools.file_operations_common import compute_hash
                content_hash = compute_hash(path, "sha256")

                snapshot_id = str(uuid.uuid4())
                created_at = time.time()

                snapshot = FileSnapshot(
                    snapshot_id=snapshot_id,
                    path=normalized,
                    content_hash=content_hash,
                    created_at=created_at,
                    content=content[:10000],
                    size=size,
                    line_count=line_count,
                )

                self._conn.execute(
                    """
                    INSERT INTO snapshots (snapshot_id, path, content_hash, created_at, content, size, line_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot.snapshot_id,
                        snapshot.path,
                        snapshot.content_hash,
                        snapshot.created_at,
                        snapshot.content,
                        snapshot.size,
                        snapshot.line_count,
                    ),
                )
                self._conn.commit()

                return {
                    "success": True,
                    "snapshot_id": snapshot_id,
                    "path": normalized,
                    "hash": content_hash,
                    "size": size,
                    "line_count": line_count,
                    "created_at": created_at,
                }

            except Exception as e:
                return {"success": False, "error": str(e)}

    def diff(self, path: Path) -> dict[str, Any] | None:
        """Get diff between current file and latest snapshot.

        Args:
            path: Path to check.

        Returns:
            Dictionary with diff information or None if no snapshot exists.
        """
        with self._lock:
            if self._conn is None:
                return None

            normalized = str(path.resolve())

            cursor = self._conn.execute(
                """
                SELECT snapshot_id, content_hash, content, size, line_count, created_at
                FROM snapshots WHERE path = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (normalized,),
            )
            row = cursor.fetchone()

            if row is None:
                return None

            snapshot_id, old_hash, old_content, old_size, old_lines, old_time = row

            if not path.exists():
                return {
                    "changed": True,
                    "deleted": True,
                    "snapshot_id": snapshot_id,
                    "old_hash": old_hash,
                }

            current_hash = None
            try:
                from tools.file_operations_common import compute_hash
                current_hash = compute_hash(path, "sha256")
            except Exception:
                pass

            if current_hash == old_hash:
                return {"changed": False, "snapshot_id": snapshot_id}

            current_content = path.read_text(encoding="utf-8", errors="replace")
            current_size = len(current_content.encode("utf-8"))
            current_lines = current_content.count("\n") + (1 if current_content else 0)

            return {
                "changed": True,
                "snapshot_id": snapshot_id,
                "old_hash": old_hash,
                "current_hash": current_hash,
                "old_size": old_size,
                "current_size": current_size,
                "old_lines": old_lines,
                "current_lines": current_lines,
                "size_diff": current_size - old_size,
                "lines_diff": current_lines - old_lines,
            }

    def restore(self, path: Path, snapshot_id: str) -> bool:
        """Restore file to a specific snapshot.

        Args:
            path: Path to the file to restore.
            snapshot_id: ID of the snapshot to restore.

        Returns:
            True if restoration succeeded, False otherwise.
        """
        with self._lock:
            if self._conn is None:
                return False

            cursor = self._conn.execute(
                "SELECT content, path FROM snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            )
            row = cursor.fetchone()

            if row is None:
                return False

            content, stored_path = row

            if stored_path != str(path.resolve()):
                return False

            try:
                from tools.file_operations_common import safe_write
                safe_write(path, content, atomic=True)
                return True
            except Exception:
                return False

    def list_snapshots(self, path: Path) -> list[dict[str, Any]]:
        """List all snapshots for a file.

        Args:
            path: Path to list snapshots for.

        Returns:
            List of snapshot information dictionaries.
        """
        with self._lock:
            if self._conn is None:
                return []

            normalized = str(path.resolve())
            cursor = self._conn.execute(
                """
                SELECT snapshot_id, content_hash, created_at, size, line_count
                FROM snapshots WHERE path = ?
                ORDER BY created_at DESC
                """,
                (normalized,),
            )

            snapshots = []
            for row in cursor.fetchall():
                snapshots.append({
                    "snapshot_id": row[0],
                    "hash": row[1],
                    "created_at": row[2],
                    "created_at_str": time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime(row[2])
                    ),
                    "size": row[3],
                    "line_count": row[4],
                })

            return snapshots

    def get_snapshot_content(self, snapshot_id: str) -> str | None:
        """Get content of a specific snapshot.

        Args:
            snapshot_id: ID of the snapshot.

        Returns:
            Content string or None if not found.
        """
        with self._lock:
            if self._conn is None:
                return None

            cursor = self._conn.execute(
                "SELECT content FROM snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def delete_old_snapshots(self, max_age_days: int = 30) -> int:
        """Delete snapshots older than specified days.

        Args:
            max_age_days: Maximum age in days for snapshots.

        Returns:
            Number of snapshots deleted.
        """
        with self._lock:
            if self._conn is None:
                return 0

            cutoff_time = time.time() - (max_age_days * 86400)
            cursor = self._conn.execute(
                "DELETE FROM snapshots WHERE created_at < ?",
                (cutoff_time,),
            )
            self._conn.commit()
            return cursor.rowcount

    def close(self) -> None:
        """Close the database connection."""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
