"""Unit tests for agent.background_tasks.

Covers:
- BackgroundTaskRegistry default / custom db_path init
- submit() returning a TaskHandle and starting a thread
- get_status() reporting lifecycle transitions
- get_result() returning function output / raising on failure
- cancel() requesting cancellation
- subscribe_progress() receiving final progress callback
- list_tasks() filtering by status
- cleanup_finished() purging old terminal tasks
- TaskHandle dataclass shape and to_dict
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from agent.background_tasks import (
    BackgroundTaskRegistry,
    TaskHandle,
    TaskStatus,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def registry(tmp_path: Path) -> BackgroundTaskRegistry:
    return BackgroundTaskRegistry(db_path=tmp_path / "tasks.db")


def _sleeper(seconds: float = 0.05, **kwargs) -> float:
    time.sleep(seconds)
    return seconds


def _adder(a: int, b: int, **kwargs) -> int:
    return a + b


def _exploder(**kwargs) -> None:
    raise RuntimeError("task failed")


# ── Init ──────────────────────────────────────────────────────────────


class TestInit:
    def test_default_init(self, tmp_path: Path) -> None:
        reg = BackgroundTaskRegistry(db_path=tmp_path / "db")
        assert reg.db_path == tmp_path / "db"
        assert reg.db_path.parent.exists()


# ── submit ────────────────────────────────────────────────────────────


class TestSubmit:
    def test_returns_handle(self, registry: BackgroundTaskRegistry) -> None:
        handle = registry.submit("noop", _sleeper)
        assert isinstance(handle, TaskHandle)
        assert handle.name == "noop"
        assert handle.task_id

    def test_starts_with_pending(self, registry: BackgroundTaskRegistry) -> None:
        handle = registry.submit("noop", _sleeper)
        # Either PENDING or RUNNING depending on scheduling.
        assert handle.status in (TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.DONE)


# ── get_status / get_result ───────────────────────────────────────────


class TestStatusAndResult:
    def test_unknown_id_raises(self, registry: BackgroundTaskRegistry) -> None:
        with pytest.raises(KeyError):
            registry.get_status("does-not-exist")

    def test_get_result_success(self, registry: BackgroundTaskRegistry) -> None:
        handle = registry.submit("add", _adder, 2, 3)
        result = registry.get_result(handle.task_id, timeout=5)
        assert result == 5
        assert handle.status == TaskStatus.DONE

    def test_get_result_failure_raises(self, registry: BackgroundTaskRegistry) -> None:
        handle = registry.submit("boom", _exploder)
        with pytest.raises(RuntimeError):
            registry.get_result(handle.task_id, timeout=5)
        assert handle.status == TaskStatus.FAILED


# ── cancel ────────────────────────────────────────────────────────────


class TestCancel:
    def test_cancel_unknown_returns_false(self, registry: BackgroundTaskRegistry) -> None:
        assert registry.cancel("nope") is False

    def test_cancel_finished_returns_false(self, registry: BackgroundTaskRegistry) -> None:
        handle = registry.submit("fast", _sleeper, 0.01)
        registry.get_result(handle.task_id, timeout=2)
        # Task already done — cancel is no-op.
        assert registry.cancel(handle.task_id) is False

    def test_cancel_running_signals(self, registry: BackgroundTaskRegistry) -> None:
        handle = registry.submit("slow", _sleeper, 1.0)
        time.sleep(0.05)  # let it transition to RUNNING
        assert registry.cancel(handle.task_id) is True


# ── subscribe_progress ────────────────────────────────────────────────


class TestSubscribe:
    def test_callback_invoked_on_completion(self, registry: BackgroundTaskRegistry) -> None:
        received: list[float] = []
        handle = registry.submit("ok", _sleeper, 0.01)
        registry.subscribe_progress(handle.task_id, lambda p: received.append(p))
        registry.get_result(handle.task_id, timeout=2)
        # The final completion callback should fire at least once with 1.0.
        assert received
        assert received[-1] == 1.0


# ── list_tasks ────────────────────────────────────────────────────────


class TestListTasks:
    def test_empty(self, registry: BackgroundTaskRegistry) -> None:
        assert registry.list_tasks() == []

    def test_filter_by_status(self, registry: BackgroundTaskRegistry) -> None:
        handle = registry.submit("quick", _sleeper, 0.01)
        registry.get_result(handle.task_id, timeout=2)
        done_list = registry.list_tasks(status=TaskStatus.DONE)
        assert any(h.task_id == handle.task_id for h in done_list)
        running_list = registry.list_tasks(status=TaskStatus.RUNNING)
        assert all(h.task_id != handle.task_id for h in running_list)


# ── cleanup_finished ──────────────────────────────────────────────────


class TestCleanup:
    def test_no_op_when_recent(self, registry: BackgroundTaskRegistry) -> None:
        handle = registry.submit("quick", _sleeper, 0.01)
        registry.get_result(handle.task_id, timeout=2)
        # Tasks finished seconds ago, default retention is 24h → not removed.
        removed = registry.cleanup_finished(older_than_hours=24)
        assert removed == 0

    def test_removes_old_finished(self, registry: BackgroundTaskRegistry) -> None:
        handle = registry.submit("quick", _sleeper, 0.01)
        registry.get_result(handle.task_id, timeout=2)
        # Force finished_at into the past, both in-memory and in the SQLite
        # store so cleanup_finished can find the row.
        old_ts = time.time() - 100 * 3600
        handle.finished_at = old_ts
        import sqlite3 as _sq
        with _sq.connect(registry.db_path) as conn:
            conn.execute(
                "UPDATE tasks SET finished_at = ? WHERE task_id = ?",
                (old_ts, handle.task_id),
            )
            conn.commit()
        removed = registry.cleanup_finished(older_than_hours=24)
        assert removed == 1
        assert registry.list_tasks() == []


# ── TaskHandle shape ──────────────────────────────────────────────────


class TestTaskHandle:
    def test_to_dict(self) -> None:
        h = TaskHandle(task_id="x", name="n", status=TaskStatus.DONE, progress=1.0)
        d = h.to_dict()
        assert d["task_id"] == "x"
        assert d["name"] == "n"
        assert d["status"] == "done"
        assert d["progress"] == 1.0

    def test_defaults(self) -> None:
        h = TaskHandle(task_id="x", name="n")
        assert h.status == TaskStatus.PENDING
        assert h.progress == 0.0
        assert h.started_at is None
        assert h.finished_at is None
        assert h.result is None
        assert h.error is None