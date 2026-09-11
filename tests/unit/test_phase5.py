"""Tests for Phase 5 modules: cron scheduler, execute_code, browser, todo."""

# ruff: noqa: E402
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

import pytest

from cron.scheduler import CronScheduler, cron_matches, parse_cron


@pytest.fixture(autouse=True)
def _zeloo_home_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate all tests that touch zeloo_HOME to a temp dir."""
    monkeypatch.setenv("zeloo_HOME", str(tmp_path))

# ── Cron tests ──────────────────────────────────────────────────────

def test_parse_cron_wildcard():
    fields = parse_cron("* * * * *")
    assert all(len(f) > 0 for f in fields)
    assert 0 in fields[0]  # minute 0
    assert 23 in fields[1]  # hour 23


def test_parse_cron_specific():
    fields = parse_cron("30 9 * * 1")
    assert fields[0] == {30}
    assert fields[1] == {9}
    assert fields[4] == {1}  # Monday


def test_parse_cron_range():
    fields = parse_cron("0 9-17 * * *")
    assert fields[1] == set(range(9, 18))


def test_parse_cron_step():
    fields = parse_cron("*/15 * * * *")
    assert fields[0] == {0, 15, 30, 45}


def test_parse_cron_list():
    fields = parse_cron("0,30 * * * *")
    assert fields[0] == {0, 30}


def test_cron_matches_exact():
    # 9:30 on any day
    dt = datetime(2026, 9, 7, 9, 30)
    assert cron_matches("30 9 * * *", dt) is True


def test_cron_no_match():
    dt = datetime(2026, 9, 7, 10, 0)
    assert cron_matches("30 9 * * *", dt) is False


def test_cron_scheduler_add_list_remove():
    sched = CronScheduler()
    sched.add_job("test", "* * * * *", lambda: None)
    jobs = sched.list_jobs()
    assert len(jobs) == 1
    assert jobs[0]["name"] == "test"
    sched.remove_job("test")
    assert sched.list_jobs() == []


# ── execute_code tests ──────────────────────────────────────────────

@pytest.mark.slow
def test_execute_code_returns_output():
    from tools.code_exec import execute_code
    result = execute_code("print('hello world')")
    assert "hello world" in result


@pytest.mark.slow
def test_execute_code_captures_stderr():
    from tools.code_exec import execute_code
    result = execute_code("import sys; sys.stderr.write('err msg')")
    assert "err msg" in result


@pytest.mark.slow
def test_execute_code_timeout():
    from tools.code_exec import execute_code
    result = execute_code("import time; time.sleep(10)", timeout=1)
    assert "timed out" in result


# ── Todo tests ──────────────────────────────────────────────────────

def test_todo_add_and_list():
    from tools.todo_tools import _save_todos, todo_add, todo_list
    _save_todos([])  # reset
    todo_add("test task", "high")
    listing = todo_list()
    assert "test task" in listing
    assert "high" in listing


def test_todo_complete():
    from tools.todo_tools import _save_todos, todo_add, todo_complete, todo_list
    _save_todos([])
    todo_add("task to complete")
    result = todo_complete(1)
    assert "Completed" in result
    # Should show as done
    listing = todo_list()
    assert "[x]" in listing


def test_todo_remove():
    from tools.todo_tools import _save_todos, todo_add, todo_list, todo_remove
    _save_todos([])
    todo_add("task to remove")
    result = todo_remove(1)
    assert "Removed" in result
    listing = todo_list()
    assert "task to remove" not in listing


# ── Browser tool registration tests ─────────────────────────────────

def test_browser_tools_registered():
    from tools.base import discover_builtin_tools, get_registry
    discover_builtin_tools()
    names = get_registry().get_names()
    browser_tools = [n for n in names if n.startswith("browser_")]
    assert len(browser_tools) >= 10


def test_browser_tool_without_playwright_returns_error():
    """browser_navigate should return a friendly error without playwright."""
    from tools.browser_tools import browser_navigate
    try:
        import playwright  # noqa: F401
        # playwright is installed; skip this test
        return
    except ImportError:
        result = browser_navigate("http://example.com")
        assert "playwright" in result.lower() or "Error" in result


if __name__ == "__main__":
    test_parse_cron_wildcard()
    test_parse_cron_specific()
    test_parse_cron_range()
    test_parse_cron_step()
    test_parse_cron_list()
    test_cron_matches_exact()
    test_cron_no_match()
    test_cron_scheduler_add_list_remove()
    test_execute_code_returns_output()
    test_execute_code_captures_stderr()
    test_execute_code_timeout()
    test_todo_add_and_list()
    test_todo_complete()
    test_todo_remove()
    test_browser_tools_registered()
    test_browser_tool_without_playwright_returns_error()
    print("All Phase 5 tests passed!")
