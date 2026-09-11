"""Tests for the Kanban multi-agent board."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

from agent.kanban import KanbanBoard, TaskStatus


def _make_board(tmp: Path) -> KanbanBoard:
    return KanbanBoard(board_id="test", storage_path=tmp / "board.json")


def test_kanban_create_and_show(tmp_path):
    board = _make_board(tmp_path)
    tid = board.create_task("Fix bug", tenant="team-a", priority=5)
    task = board.get_task(tid)
    assert task is not None
    assert task.title == "Fix bug"
    assert task.tenant == "team-a"
    assert task.status == TaskStatus.TODO


def test_kanban_assign_and_complete(tmp_path):
    board = _make_board(tmp_path)
    tid = board.create_task("Task")
    assert board.assign_task(tid, "worker-1")
    task = board.get_task(tid)
    assert task.status == TaskStatus.IN_PROGRESS
    assert task.assignee == "worker-1"
    board.complete_task(tid)
    assert board.get_task(tid).status == TaskStatus.COMPLETED


def test_kanban_fail_retry(tmp_path):
    board = _make_board(tmp_path)
    tid = board.create_task("Failing", max_retries=2)
    board.assign_task(tid, "w")
    board.fail_task(tid, "error 1")
    assert board.get_task(tid).status == TaskStatus.TODO
    board.assign_task(tid, "w")
    board.fail_task(tid, "error 2")
    assert board.get_task(tid).status == TaskStatus.BLOCKED


def test_kanban_zombie_reclaim(tmp_path):
    board = _make_board(tmp_path)
    tid = board.create_task("Zombie")
    board.assign_task(tid, "dead-worker")
    board._tasks[tid].heartbeat = 0  # simulate stale heartbeat
    reclaimed = board.reclaim_zombies()
    assert tid in reclaimed
    assert board.get_task(tid).status == TaskStatus.TODO
    assert board.get_task(tid).assignee is None


def test_kanban_list_and_stats(tmp_path):
    board = _make_board(tmp_path)
    t1 = board.create_task("A", tenant="x")
    board.create_task("B", tenant="y")
    board.complete_task(t1)
    tasks = board.list_tasks(status=TaskStatus.COMPLETED)
    assert len(tasks) == 1
    stats = board.get_stats()
    assert stats["total"] == 2
    assert stats["completed"] == 1


def test_kanban_persistence(tmp_path):
    board = _make_board(tmp_path)
    tid = board.create_task("Persistent")
    board2 = _make_board(tmp_path)
    assert board2.get_task(tid) is not None


if __name__ == "__main__":
    import shutil

    tests = [
        test_kanban_create_and_show,
        test_kanban_assign_and_complete,
        test_kanban_fail_retry,
        test_kanban_zombie_reclaim,
        test_kanban_list_and_stats,
        test_kanban_persistence,
    ]
    for t in tests:
        base = Path(tempfile.mkdtemp())
        t(base)
        shutil.rmtree(base)
    print("All kanban tests passed!")
