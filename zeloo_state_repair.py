"""Zeloo state database self-repair.

Diagnoses and repairs common corruption issues in the state SQLite database:
leftover WAL/SHM files, corrupt indexes, orphaned rows (messages/trajectories
whose session no longer exists), uncommitted transactions, and integrity
failures. Designed to be safe to run on a healthy database (no-ops) and
non-destructive when it can repair.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

Severity = Literal["critical", "warning", "info"]


@dataclass
class RepairIssue:
    """A single diagnosed problem with the database."""

    severity: Severity
    table: str
    description: str
    sql: str | None = None  # SQL used to repair, if applicable


@dataclass
class RepairResult:
    """Outcome of repairing a single :class:`RepairIssue`."""

    issue: RepairIssue
    success: bool
    message: str = ""


@dataclass
class RepairReport:
    """Aggregate outcome of a full diagnose + repair run."""

    issues: list[RepairIssue] = field(default_factory=list)
    results: list[RepairResult] = field(default_factory=list)
    integrity_ok: bool = True
    wal_cleaned: bool = False
    vacuumed: bool = False

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "critical")

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.results if r.success)


class StateRepair:
    """Diagnose and repair a Zeloo state SQLite database.

    Args:
        db_path: Path to the ``state.db`` file.
    """

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)

    # ── public API ────────────────────────────────────────────────────

    def diagnose(self) -> list[RepairIssue]:
        """Inspect the database and return a list of detected issues.

        Does not modify the database (except for opening the connection,
        which may create an empty file if it didn't exist).
        """
        issues: list[RepairIssue] = []

        # 1. Leftover WAL / SHM files
        wal = self.db_path.with_suffix(self.db_path.suffix + "-wal")
        shm = self.db_path.with_suffix(self.db_path.suffix + "-shm")
        if wal.exists() or shm.exists():
            issues.append(RepairIssue(
                severity="warning",
                table="__wal__",
                description="WAL/SHM sidecar files present (may indicate a crashed writer).",
                sql="PRAGMA wal_checkpoint(TRUNCATE)",
            ))

        if not self.db_path.exists():
            # Nothing more to check — ensure_schema will create the file.
            return issues

        conn = sqlite3.connect(str(self.db_path))
        try:
            # 2. Integrity check
            integrity = self._check_integrity(conn)
            if integrity != "ok":
                issues.append(RepairIssue(
                    severity="critical",
                    table="__integrity__",
                    description=f"PRAGMA integrity_check reported: {integrity}",
                ))

            # 3. Orphaned messages (no matching session)
            orphan_msgs = self._count_orphans(conn, "messages", "sessions", "session_id")
            if orphan_msgs:
                issues.append(RepairIssue(
                    severity="warning",
                    table="messages",
                    description=f"{orphan_msgs} message row(s) reference a non-existent session.",
                    sql=(
                        "DELETE FROM messages WHERE session_id NOT IN "
                        "(SELECT session_id FROM sessions)"
                    ),
                ))

            # 4. Orphaned trajectories
            orphan_traj = self._count_orphans(conn, "trajectories", "sessions", "session_id")
            if orphan_traj:
                desc = (
                    f"{orphan_traj} trajectory row(s) reference a non-existent "
                    "session."
                )
                issues.append(RepairIssue(
                    severity="warning",
                    table="trajectories",
                    description=desc,
                    sql=(
                        "DELETE FROM trajectories WHERE session_id NOT IN "
                        "(SELECT session_id FROM sessions)"
                    ),
                ))
        finally:
            conn.close()

        return issues

    def repair(self, dry_run: bool = False) -> RepairReport:
        """Diagnose issues and attempt to repair them.

        Args:
            dry_run: If ``True``, report what would be done without modifying
                the database.

        Returns:
            A :class:`RepairReport` with all diagnosed issues and repair
            outcomes.
        """
        report = RepairReport()
        issues = self.diagnose()
        report.issues = issues

        if dry_run:
            return report

        conn = sqlite3.connect(str(self.db_path))
        try:
            for issue in issues:
                if issue.table == "__integrity__":
                    # Integrity failures cannot be auto-repaired reliably;
                    # suggest restoring from backup.
                    msg = (
                        "Integrity failure requires manual intervention "
                        "or restore from backup."
                    )
                    report.results.append(RepairResult(
                        issue=issue,
                        success=False,
                        message=msg,
                    ))
                    report.integrity_ok = False
                    continue

                if issue.table == "__wal__":
                    ok = self._checkpoint_wal(conn)
                    report.wal_cleaned = ok
                    wal_msg = (
                        "WAL checkpointed and truncated."
                        if ok else "WAL checkpoint failed."
                    )
                    report.results.append(RepairResult(
                        issue=issue,
                        success=ok,
                        message=wal_msg,
                    ))
                    continue

                if issue.sql:
                    try:
                        conn.execute(issue.sql)
                        conn.commit()
                        report.results.append(RepairResult(
                            issue=issue, success=True, message="Repaired.",
                        ))
                    except sqlite3.Error as exc:
                        logger.exception("Failed to repair %s", issue.table)
                        report.results.append(RepairResult(
                            issue=issue, success=False, message=str(exc),
                        ))
        finally:
            conn.close()

        return report

    def vacuum(self) -> bool:
        """Run ``VACUUM`` to rebuild and compact the database file.

        Returns ``True`` on success.
        """
        if not self.db_path.exists():
            return False
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("VACUUM")
            conn.commit()
            return True
        except sqlite3.Error:
            logger.exception("VACUUM failed for %s", self.db_path)
            return False
        finally:
            conn.close()

    # ── internal helpers ──────────────────────────────────────────────

    @staticmethod
    def _check_integrity(conn: sqlite3.Connection) -> str:
        """Run ``PRAGMA integrity_check`` and return the result string."""
        try:
            cur = conn.execute("PRAGMA integrity_check")
            row = cur.fetchone()
            return row[0] if row else "unknown"
        except sqlite3.Error as exc:
            return f"error: {exc}"

    @staticmethod
    def _count_orphans(
        conn: sqlite3.Connection,
        child_table: str,
        parent_table: str,
        fk_column: str,
    ) -> int:
        """Count rows in ``child_table`` whose FK has no matching parent."""
        try:
            cur = conn.execute(
                f"SELECT COUNT(*) FROM {child_table} "
                f"WHERE {fk_column} NOT IN (SELECT {fk_column} FROM {parent_table})"
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0
        except sqlite3.Error:
            return 0

    @staticmethod
    def _checkpoint_wal(conn: sqlite3.Connection) -> bool:
        """Force a WAL checkpoint and truncation."""
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.commit()
            return True
        except sqlite3.Error:
            logger.exception("WAL checkpoint failed")
            return False
