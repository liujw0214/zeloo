"""Tests for kanban threading + heartbeat coalescing."""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

from agent.kanban import HEARTBEAT_FLUSH_INTERVAL_S, KanbanBoard, TaskStatus


def _board(tmp: Path) -> KanbanBoard:
    return KanbanBoard(board_id="b", storage_path=tmp / "b.json")


class TestHeartbeatCoalescing:
    def test_heartbeats_coalesce_within_window(self) -> None:
        """Many rapid heartbeats must trigger at most one disk rewrite
        per coalescing window."""
        with tempfile.TemporaryDirectory() as tmp:
            board = _board(Path(tmp))
            task_id = board.create_task(title="t")
            board.assign_task(task_id, worker_id="w1")

            with patch.object(board, "_save") as mock_save:
                # Force the schedule_flush path to think we are mid-window
                board._last_flush = time.time()
                for _ in range(50):
                    board.heartbeat(task_id)
                # Within the window, no extra saves should have happened.
                assert mock_save.call_count == 0

    def test_heartbeat_triggers_flush_after_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = _board(Path(tmp))
            task_id = board.create_task(title="t")
            board.assign_task(task_id, worker_id="w1")

            with patch.object(board, "_save") as mock_save:
                # Make last_flush far enough in the past to force flush
                board._last_flush = time.time() - HEARTBEAT_FLUSH_INTERVAL_S - 1
                board.heartbeat(task_id)
                assert mock_save.call_count == 1

    def test_immediate_save_used_for_lifecycle_changes(self) -> None:
        """create_task / assign / complete / fail must flush immediately."""
        with tempfile.TemporaryDirectory() as tmp:
            board = _board(Path(tmp))
            with patch.object(board, "_save") as mock_save:
                tid = board.create_task(title="t")
                assert mock_save.call_count == 1
                board.assign_task(tid, worker_id="w")
                assert mock_save.call_count == 2
                board.complete_task(tid)
                assert mock_save.call_count == 3

    def test_flush_force_writes_pending_state(self) -> None:
        """``flush()`` must persist coalesced heartbeats before shutdown."""
        with tempfile.TemporaryDirectory() as tmp:
            board = _board(Path(tmp))
            tid = board.create_task(title="t")
            board.assign_task(tid, worker_id="w1")
            board._last_flush = time.time()
            board.heartbeat(tid)
            assert board._dirty is True
            board.flush()
            assert board._dirty is False

    def test_compact_json_no_indent(self) -> None:
        """Persistence uses compact JSON (no indent) to keep writes small."""
        with tempfile.TemporaryDirectory() as tmp:
            board = _board(Path(tmp))
            board.create_task(title="t")
            content = (Path(tmp) / "b.json").read_text(encoding="utf-8")
            assert "\n  " not in content, "JSON should be compact"


class TestThreadSafety:
    def test_concurrent_create_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = _board(Path(tmp))
            results: list[str] = []

            def make():
                tid = board.create_task(title="x")
                results.append(tid)

            threads = [threading.Thread(target=make) for _ in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(results) == 20
            assert len(set(results)) == 20  # all unique
            assert board.get_stats()["total"] == 20

    def test_concurrent_heartbeats_no_data_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = _board(Path(tmp))
            tid = board.create_task(title="t")
            board.assign_task(tid, worker_id="w")

            def beat():
                for _ in range(50):
                    board.heartbeat(tid)

            threads = [threading.Thread(target=beat) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # Flush remaining dirty state and reload — heartbeat count
            # must be the most recent value, not a half-overwritten one.
            board.flush()
            board2 = KanbanBoard(board_id="b", storage_path=Path(tmp) / "b.json")
            t = board2.get_task(tid)
            assert t is not None
            assert t.status == TaskStatus.IN_PROGRESS
            assert t.assignee == "w"

    def test_concurrent_assign_and_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = _board(Path(tmp))
            tid = board.create_task(title="t")

            def race_complete():
                board.complete_task(tid, result="done")

            t = threading.Thread(target=race_complete)
            t.start()
            t.join()
            # Final state must be consistent.
            assert board.get_task(tid).status == TaskStatus.COMPLETED


class TestReclaimZombies:
    def test_reclaim_zombie(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = _board(Path(tmp))
            tid = board.create_task(title="t")
            board.assign_task(tid, worker_id="w")
            # Backdate heartbeat to make the task appear zombie.
            board.get_task(tid).heartbeat = time.time() - 600
            reclaimed = board.reclaim_zombies()
            assert tid in reclaimed
            assert board.get_task(tid).status == TaskStatus.TODO

    def test_reclaim_no_op_when_no_zombies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = _board(Path(tmp))
            tid = board.create_task(title="t")
            board.assign_task(tid, worker_id="w")
            # Heartbeat is fresh — no reclaim.
            assert board.reclaim_zombies() == []