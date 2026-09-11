"""Tests for zeloo_state_schema and zeloo_state_repair."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from zeloo_state_repair import RepairIssue, RepairReport, StateRepair
from zeloo_state_schema import (
    SCHEMA_VERSION,
    ensure_schema,
    get_schema_version,
    list_indexes,
    list_tables,
)


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


@pytest.fixture
def conn(tmp_db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(tmp_db_path))
    yield conn
    conn.close()


# ── schema tests ──────────────────────────────────────────────────────

class TestSchema:
    def test_ensure_schema_creates_tables(self, conn: sqlite3.Connection) -> None:
        ensure_schema(conn)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for name in ("sessions", "messages", "trajectories", "messages_fts"):
            assert name in tables

    def test_ensure_schema_creates_indexes(self, conn: sqlite3.Connection) -> None:
        ensure_schema(conn)
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        for name in list_indexes():
            assert name in indexes

    def test_ensure_schema_records_version(self, conn: sqlite3.Connection) -> None:
        ensure_schema(conn)
        assert get_schema_version(conn) == SCHEMA_VERSION

    def test_ensure_schema_idempotent(self, conn: sqlite3.Connection) -> None:
        ensure_schema(conn)
        ensure_schema(conn)
        # No error on second call; version still correct.
        assert get_schema_version(conn) == SCHEMA_VERSION

    def test_legacy_db_without_version_table(self, tmp_db_path: Path) -> None:
        """A pre-versioning DB (no db_version table) is upgraded in place."""
        conn = sqlite3.connect(str(tmp_db_path))
        # Create the v1 tables manually, like the old SessionDB did.
        conn.executescript(
            """
            CREATE TABLE sessions (
                session_id TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT,
                created_at REAL NOT NULL
            );
            """
        )
        conn.commit()
        conn.close()

        conn = sqlite3.connect(str(tmp_db_path))
        # Pre-versioning DB returns 0.
        assert get_schema_version(conn) == 0
        # ensure_schema upgrades it without dropping data.
        ensure_schema(conn)
        assert get_schema_version(conn) == SCHEMA_VERSION
        conn.close()

    def test_list_tables_returns_expected(self) -> None:
        tables = list_tables()
        assert "sessions" in tables
        assert "messages" in tables
        assert "trajectories" in tables


# ── repair tests ──────────────────────────────────────────────────────

class TestStateRepair:
    def _seed_with_orphans(self, db_path: Path) -> None:
        conn = sqlite3.connect(str(db_path))
        ensure_schema(conn)
        conn.execute(
            "INSERT INTO sessions (session_id, created_at, updated_at) "
            "VALUES (?, ?, ?)",
            ("s1", 1.0, 1.0),
        )
        conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("s1", "user", "hello", 1.0),
        )
        conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("orphan", "user", "lost", 2.0),
        )
        conn.execute(
            "INSERT INTO trajectories (session_id, turn_id, data, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("orphan", 1, "{}", 2.0),
        )
        conn.commit()
        conn.close()

    def test_diagnose_finds_orphaned_messages(self, tmp_db_path: Path) -> None:
        self._seed_with_orphans(tmp_db_path)
        repair = StateRepair(tmp_db_path)
        issues = repair.diagnose()
        tables = {i.table for i in issues}
        assert "messages" in tables
        assert "trajectories" in tables

    def test_repair_removes_orphans(self, tmp_db_path: Path) -> None:
        self._seed_with_orphans(tmp_db_path)
        repair = StateRepair(tmp_db_path)
        report = repair.repair()
        assert all(r.success for r in report.results)

        conn = sqlite3.connect(str(tmp_db_path))
        orphan_msgs = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id='orphan'"
        ).fetchone()[0]
        orphan_traj = conn.execute(
            "SELECT COUNT(*) FROM trajectories WHERE session_id='orphan'"
        ).fetchone()[0]
        conn.close()
        assert orphan_msgs == 0
        assert orphan_traj == 0

    def test_dry_run_does_not_modify(self, tmp_db_path: Path) -> None:
        self._seed_with_orphans(tmp_db_path)
        repair = StateRepair(tmp_db_path)
        report = repair.repair(dry_run=True)
        # dry_run reports issues but performs no repairs.
        assert report.results == []

        conn = sqlite3.connect(str(tmp_db_path))
        still_orphan = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id='orphan'"
        ).fetchone()[0]
        conn.close()
        assert still_orphan == 1

    def test_diagnose_clean_db_returns_no_issues(
        self, tmp_db_path: Path
    ) -> None:
        conn = sqlite3.connect(str(tmp_db_path))
        ensure_schema(conn)
        conn.execute(
            "INSERT INTO sessions (session_id, created_at, updated_at) "
            "VALUES (?, ?, ?)",
            ("s1", 1.0, 1.0),
        )
        conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("s1", "user", "hi", 1.0),
        )
        conn.commit()
        conn.close()

        repair = StateRepair(tmp_db_path)
        issues = repair.diagnose()
        assert issues == []

    def test_vacuum_succeeds(self, tmp_db_path: Path) -> None:
        conn = sqlite3.connect(str(tmp_db_path))
        ensure_schema(conn)
        conn.close()
        repair = StateRepair(tmp_db_path)
        assert repair.vacuum() is True

    def test_vacuum_missing_db_returns_false(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope.db"
        repair = StateRepair(missing)
        assert repair.vacuum() is False

    def test_report_properties(self) -> None:
        report = RepairReport()
        report.issues.append(
            RepairIssue(severity="critical", table="x", description="bad")
        )
        assert report.critical_count == 1
        assert report.success_count == 0
