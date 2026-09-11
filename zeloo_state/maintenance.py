"""Scheduled maintenance tasks for zeloo_state database."""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class MaintenanceStats:
    """Statistics from a maintenance run."""

    started_at: float
    duration_seconds: float
    vacuum_done: bool
    analyze_done: bool
    repair_done: bool
    issues_found: int
    issues_fixed: int
    bytes_saved: int
    messages_cleaned: int
    sessions_pruned: int


class MaintenanceScheduler:
    """Background maintenance scheduler for the state database.

    Runs periodic:
    - VACUUM (database compaction)
    - ANALYZE (query planner statistics)
    - Repair (self-healing diagnostics)
    - Cleanup (orphaned records, old sessions)
    """

    def __init__(
        self,
        db_path: Path | str | None = None,
        interval_hours: float = 24.0,
        enabled: bool = True,
    ):
        from agent.zeloo_constants import get_state_db_path

        self.db_path = Path(db_path) if db_path else get_state_db_path()
        self.interval_hours = interval_hours
        self.enabled = enabled
        self._thread: threading.Thread | None = None
        self._shutdown = threading.Event()
        self._last_run: float | None = None
        self._last_stats: MaintenanceStats | None = None

    def start(self) -> None:
        """Start the background maintenance thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("Maintenance scheduler already running")
            return
        if not self.enabled:
            logger.info("Maintenance scheduler disabled")
            return

        self._shutdown.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="state-maintenance",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Maintenance scheduler started (interval=%.1fh)", self.interval_hours
        )

    def stop(self) -> None:
        """Stop the background maintenance thread."""
        self._shutdown.set()
        if self._thread:
            self._thread.join(timeout=30.0)
            self._thread = None
        logger.info("Maintenance scheduler stopped")

    def run_once(self) -> MaintenanceStats:
        """Run a single maintenance pass synchronously."""
        return self._execute_maintenance()

    def get_last_stats(self) -> MaintenanceStats | None:
        """Return statistics from the last maintenance run."""
        return self._last_stats

    def _loop(self) -> None:
        """Background maintenance loop."""
        interval_seconds = self.interval_hours * 3600.0

        while not self._shutdown.is_set():
            try:
                self._last_stats = self._execute_maintenance()
            except Exception as e:
                logger.error("Maintenance run failed: %s", e)

            self._last_run = time.time()
            self._shutdown.wait(timeout=interval_seconds)

    def _execute_maintenance(self) -> MaintenanceStats:
        """Execute all maintenance tasks."""
        start = time.time()

        from zeloo_state.repair import StateRepair

        repair_engine = StateRepair(self.db_path)
        issues = repair_engine.diagnose()
        repair_results = repair_engine.repair(severity_filter=None)

        repair_done = len(repair_results) > 0
        issues_fixed = sum(1 for r in repair_results if r.success)

        issues_found = len(issues)

        repair_engine.analyze()

        size_before = self.db_path.stat().st_size
        repair_engine.vacuum()
        vacuum_done = True
        analyze_done = True

        size_after = self.db_path.stat().st_size
        bytes_saved = max(0, size_before - size_after)

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute(
            "DELETE FROM messages WHERE session_id NOT IN (SELECT session_id FROM sessions)"
        )
        messages_cleaned = cursor.rowcount

        cursor.execute("SELECT COUNT(*) FROM sessions")
        _session_count = cursor.fetchone()[0]
        sessions_pruned = 0

        conn.commit()
        conn.close()

        duration = time.time() - start

        stats = MaintenanceStats(
            started_at=start,
            duration_seconds=duration,
            vacuum_done=vacuum_done,
            analyze_done=analyze_done,
            repair_done=repair_done,
            issues_found=issues_found,
            issues_fixed=issues_fixed,
            bytes_saved=bytes_saved,
            messages_cleaned=messages_cleaned,
            sessions_pruned=sessions_pruned,
        )

        logger.info(
            "Maintenance done in %.1fs: %d issues found, %d fixed, %d msgs, %d bytes saved",
            duration,
            issues_found,
            issues_fixed,
            messages_cleaned,
            bytes_saved,
        )

        return stats

    def prune_old_sessions(self, keep_days: int = 90) -> int:
        """Delete sessions older than keep_days.

        Args:
            keep_days: Number of days to retain. Sessions inactive longer
                      than this are deleted.

        Returns:
            Number of sessions pruned.
        """
        cutoff = time.time() - (keep_days * 86400)

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM sessions WHERE updated_at < ?",
            (cutoff,),
        )
        pruned = cursor.rowcount
        conn.commit()
        conn.close()

        logger.info("Pruned %d old sessions (older than %d days)", pruned, keep_days)
        return pruned
