"""Database self-diagnosis and repair for zeloo_state."""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class Severity(str, Enum):  # noqa: UP042
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass
class RepairIssue:
    """A diagnosed database issue."""

    severity: Severity
    table: str
    description: str
    sql: str | None = None
    rows_affected: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity.value,
            "table": self.table,
            "description": self.description,
            "sql": self.sql,
            "rows_affected": self.rows_affected,
        }


@dataclass
class RepairResult:
    """Result of a repair operation."""

    issue: RepairIssue
    success: bool
    message: str
    rows_fixed: int = 0


_DELETE_ORPHANED_MESSAGES = (
    "DELETE FROM messages "
    "WHERE session_id NOT IN (SELECT session_id FROM sessions WHERE session_id IS NOT NULL)"
)

_DELETE_ORPHANED_TRAJECTORIES = (
    "DELETE FROM trajectories "
    "WHERE session_id NOT IN (SELECT session_id FROM sessions WHERE session_id IS NOT NULL)"
)

_CREATE_MISSING_IDX = (
    "CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id)"
)

_WAL_CHECKPOINT = "PRAGMA wal_checkpoint(TRUNCATE)"


class StateRepair:
    """Database self-repair engine."""

    def __init__(self, db_path: Path | str | None = None):
        from agent.zeloo_constants import get_state_db_path
        self.db_path = Path(db_path) if db_path else get_state_db_path()
        self._issues: list[RepairIssue] = []
        self._lock = threading.Lock()

    def diagnose(self) -> list[RepairIssue]:
        """Run all diagnostic checks."""
        self._issues.clear()
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            self._check_orphaned_messages(conn)
            self._check_orphaned_trajectories(conn)
            self._check_missing_indexes(conn)
            self._check_null_sessions(conn)
            self._check_wal(conn)
            conn.close()
        except sqlite3.Error as e:
            logger.error("Diagnosis failed: %s", e)
            self._issues.append(
                RepairIssue(
                    severity=Severity.CRITICAL,
                    table="<database>",
                    description=f"Cannot open database: {e}",
                    sql=None,
                )
            )
        return list(self._issues)

    def repair(
        self,
        dry_run: bool = False,
        severity_filter: Severity | None = None,
    ) -> list[RepairResult]:
        """Apply repairs for diagnosed issues."""
        results: list[RepairResult] = []
        for issue in self._issues:
            if severity_filter and issue.severity.value < severity_filter.value:
                continue
            if not issue.sql:
                continue
            result = self._apply_repair(issue, dry_run)
            results.append(result)
        return results

    def vacuum(self) -> None:
        """Execute VACUUM to rebuild the database."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("VACUUM")
            conn.close()
            logger.info("Vacuumed: %s", self.db_path)
        except sqlite3.Error as e:
            logger.error("Vacuum failed: %s", e)

    def analyze(self) -> None:
        """Execute ANALYZE for query planner stats."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("ANALYZE")
            conn.close()
            logger.info("Analyzed: %s", self.db_path)
        except sqlite3.Error as e:
            logger.error("Analyze failed: %s", e)

    def _apply_repair(
        self, issue: RepairIssue, dry_run: bool
    ) -> RepairResult:
        """Apply a single repair."""
        if dry_run or not issue.sql:
            return RepairResult(
                issue=issue,
                success=True,
                message=f"[DRY RUN] Would execute: {issue.sql}",
                rows_fixed=0,
            )
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute(issue.sql)
            rows_fixed = cursor.rowcount
            conn.commit()
            conn.close()
            msg = f"Repaired: {issue.description} ({rows_fixed} rows)"
            logger.info(msg)
            return RepairResult(issue=issue, success=True, message=msg, rows_fixed=rows_fixed)
        except sqlite3.Error as e:
            msg = f"Repair failed: {issue.description}: {e}"
            logger.error(msg)
            return RepairResult(issue=issue, success=False, message=msg, rows_fixed=0)

    def _check_orphaned_messages(self, conn: sqlite3.Connection) -> None:
        """Detect messages without a valid session."""
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM messages m "
            "LEFT JOIN sessions s ON m.session_id = s.session_id "
            "WHERE s.session_id IS NULL"
        )
        count = cursor.fetchone()[0]
        if count > 0:
            self._issues.append(
                RepairIssue(
                    severity=Severity.WARNING,
                    table="messages",
                    description=f"{count} messages orphaned (no session)",
                    sql=_DELETE_ORPHANED_MESSAGES,
                    rows_affected=count,
                )
            )

    def _check_orphaned_trajectories(self, conn: sqlite3.Connection) -> None:
        """Detect trajectories without a valid session."""
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM trajectories t "
            "LEFT JOIN sessions s ON t.session_id = s.session_id "
            "WHERE s.session_id IS NULL"
        )
        count = cursor.fetchone()[0]
        if count > 0:
            self._issues.append(
                RepairIssue(
                    severity=Severity.INFO,
                    table="trajectories",
                    description=f"{count} trajectories orphaned (no session)",
                    sql=_DELETE_ORPHANED_TRAJECTORIES,
                    rows_affected=count,
                )
            )

    def _check_missing_indexes(self, conn: sqlite3.Connection) -> None:
        """Check for missing performance indexes on large tables."""
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM messages")
        msg_count = cursor.fetchone()[0]
        if msg_count > 10000:
            cursor.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND name='idx_messages_session_id'"
            )
            if not cursor.fetchone():
                self._issues.append(
                    RepairIssue(
                        severity=Severity.WARNING,
                        table="messages",
                        description="Large messages table missing idx_messages_session_id",
                        sql=_CREATE_MISSING_IDX,
                    )
                )

    def _check_null_sessions(self, conn: sqlite3.Connection) -> None:
        """Check for sessions with NULL session_id."""
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM sessions WHERE session_id IS NULL")
        null_count = cursor.fetchone()[0]
        if null_count > 0:
            self._issues.append(
                RepairIssue(
                    severity=Severity.CRITICAL,
                    table="sessions",
                    description=f"{null_count} sessions have NULL session_id",
                    sql="DELETE FROM sessions WHERE session_id IS NULL",
                    rows_affected=null_count,
                )
            )

    def _check_wal(self, conn: sqlite3.Connection) -> None:
        """Check WAL checkpoint status."""
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        if mode == "wal":
            cursor.execute("PRAGMA wal_checkpoint(PASSIVE)")
            result = cursor.fetchone()
            if result and result[2] > 1000:
                frames = result[2]
                self._issues.append(
                    RepairIssue(
                        severity=Severity.INFO,
                        table="<database>",
                        description=f"WAL checkpoint recommended ({frames} uncheckpointed frames)",
                        sql=_WAL_CHECKPOINT,
                    )
                )
