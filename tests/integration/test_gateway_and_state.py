"""Integration tests for gateway platforms and state management cross-cutting concerns."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)


def test_platform_registry_loads_all_adapters():
    """platform_registry should list all registered platform adapters."""
    from gateway import platform_registry

    names = platform_registry.list_platforms()
    assert len(names) > 0

    assert "telegram" in names
    assert "discord" in names


def test_platform_registry_resolves_by_name():
    """platform_registry should resolve platform by name string."""
    from gateway import platform_registry

    adapter_cls = platform_registry.get_platform("telegram")
    assert adapter_cls is not None


def test_state_schema_version_tracking(tmp_path):
    """zeloo_state schema should track its own version."""
    import sqlite3

    from zeloo_state.schema import SCHEMA_VERSION, ensure_schema, get_schema_version

    db_path = tmp_path / "state.db"
    conn = sqlite3.connect(db_path)

    ensure_schema(conn)

    version = get_schema_version(conn)
    assert version == SCHEMA_VERSION
    conn.close()


def test_state_repair_detects_issues(tmp_path):
    """StateRepair should diagnose database issues."""
    from zeloo_state.repair import StateRepair

    repair = StateRepair(db_path=tmp_path / "repair.db")

    issues = repair.diagnose()
    assert isinstance(issues, list)


def test_state_guard_rw_lock_concurrent_reads(tmp_path):
    """RWLock should allow concurrent reads without blocking."""
    import sqlite3
    import threading
    import time

    from zeloo_state.guard import RWLock
    from zeloo_state.schema import ensure_schema

    db_path = tmp_path / "guard.db"
    conn = sqlite3.connect(db_path)
    ensure_schema(conn)
    conn.close()

    lock = RWLock()
    results = []
    errors = []

    def read_session(sid):
        try:
            ctx = lock.read_lock()
            ctx.__enter__()
            time.sleep(0.01)
            results.append(f"read_{sid}")
            ctx.__exit__(None, None, None)
        except Exception as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=read_session, args=(f"s{i}",)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    assert len(results) == 5


def test_state_readpool_write_transaction(tmp_path):
    """ConnectionPool write_transaction should execute within a transaction."""
    import sqlite3

    from zeloo_state.readpool import ConnectionPool
    from zeloo_state.schema import ensure_schema

    db_path = tmp_path / "pool.db"
    conn0 = sqlite3.connect(db_path)
    ensure_schema(conn0)
    conn0.close()

    pool = ConnectionPool(db_path=db_path, pool_size=1)

    result = []
    with pool.write_transaction() as tx:
        tx.execute(
            "INSERT OR IGNORE INTO sessions (session_id, created_at, updated_at) VALUES (?, ?, ?)",
            ("s1", 0.0, 0.0),
        )
        result.append("inserted")

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT session_id FROM sessions WHERE session_id=?", ("s1",)).fetchone()
    conn.close()

    assert row == ("s1",)
    pool.close()


def test_state_maintenance_run_once(tmp_path):
    """MaintenanceScheduler.run_once should vacuum and analyze without error."""
    import sqlite3

    from zeloo_state.maintenance import MaintenanceScheduler
    from zeloo_state.schema import ensure_schema

    db_path = tmp_path / "maint.db"
    conn = sqlite3.connect(db_path)
    ensure_schema(conn)

    for i in range(100):
        conn.execute(
            "INSERT OR IGNORE INTO sessions (session_id, created_at, updated_at) VALUES (?, ?, ?)",
            (f"s{i}", conn.total_changes, conn.total_changes),
        )
    conn.commit()
    conn.close()

    sched = MaintenanceScheduler(db_path=db_path)
    report = sched.run_once()

    assert report.vacuum_done is True
    assert report.analyze_done is True


def test_state_usage_record_and_aggregate(tmp_path):
    """UsageTracker should record usage and return aggregated stats."""
    from zeloo_state.usage import UsageTracker

    db_path = tmp_path / "usage.db"
    tracker = UsageTracker(db_path=db_path)

    tracker.record(
        session_id="s1",
        platform="openai",
        model="gpt-4o-mini",
        input_tokens=1000,
        output_tokens=200,
        latency_ms=100.0,
        metadata=None,
        cost_usd=None,
    )
    tracker.record(
        session_id="s1",
        platform="openai",
        model="gpt-4o-mini",
        input_tokens=500,
        output_tokens=100,
        latency_ms=50.0,
        metadata=None,
        cost_usd=None,
    )

    total = tracker.get_total_usage()
    assert isinstance(total, dict)
    assert total["total_in"] >= 1500
    assert total["total_out"] >= 300


def test_mcp_tool_filter_include_exclude():
    """mcp tool_filter should include/exclude tools correctly."""
    from mcp import tool_filter

    all_tools = [
        {"name": "file_read", "description": "read a file"},
        {"name": "shell_exec", "description": "run shell command"},
        {"name": "memory_search", "description": "search memory"},
    ]

    filtered = tool_filter.filter_tools(all_tools, include=["file_read", "memory_search"])
    names = {t["name"] for t in filtered}
    assert "file_read" in names
    assert "memory_search" in names
    assert "shell_exec" not in names

    filtered_ex = tool_filter.filter_tools(all_tools, exclude=["shell_exec"])
    names_ex = {t["name"] for t in filtered_ex}
    assert "shell_exec" not in names_ex
    assert len(filtered_ex) == 2


def test_cli_config_loads_with_env_override(tmp_path, monkeypatch):
    """CLI config should load and expose model/provider keys."""
    from zeloo_cli.config import load_config

    monkeypatch.setenv("zeloo_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("zeloo_PROVIDER", "openai")

    cfg = load_config()

    assert isinstance(cfg, dict)


def test_cli_doctor_runs_checks():
    """CLI doctor subcommand should run all checks without error."""
    import argparse

    from zeloo_cli.subcommands.doctor import DoctorCmd

    cmd = DoctorCmd()
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers().add_parser("doctor")
    cmd.configure_parser(sub)
    ns = parser.parse_args(["doctor"])

    result = cmd.run(ns)

    assert result in (0, 1)


if __name__ == "__main__":
    test_platform_registry_loads_all_adapters()
    test_platform_registry_resolves_by_name()
    test_state_schema_version_tracking()
    test_state_repair_detects_issues()
    test_state_guard_rw_lock_concurrent_reads()
    test_state_readpool_write_transaction()
    test_state_maintenance_run_once()
    test_state_usage_record_and_aggregate()
    test_mcp_tool_filter_include_exclude()
    test_cli_config_loads_with_env_override()
    test_cli_doctor_runs_checks()
    print("All gateway/state integration tests passed!")
