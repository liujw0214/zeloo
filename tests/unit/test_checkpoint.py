"""Tests for agent.checkpoint — atomic writes + index caching."""

from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from agent.checkpoint import CheckpointManager


def _manager(tmp: Path) -> CheckpointManager:
    return CheckpointManager(checkpoint_dir=str(tmp / "ckpts"))


class TestSaveAndLoad:
    def test_save_returns_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mgr = _manager(Path(tmp))
            ckpt = mgr.save(
                session_id="s1", turn_id=1,
                messages=[{"role": "user", "content": "hi"}],
            )
            assert ckpt.session_id == "s1"
            assert ckpt.turn_id == 1
            assert ckpt.messages == [{"role": "user", "content": "hi"}]

    def test_load_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mgr1 = _manager(Path(tmp))
            msgs = [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "hi"},
            ]
            ckpt1 = mgr1.save(session_id="s", turn_id=5, messages=msgs)
            mgr2 = _manager(Path(tmp))
            ckpt2 = mgr2.load(ckpt1.checkpoint_id)
            assert ckpt2 is not None
            assert ckpt2.messages == msgs
            assert ckpt2.turn_id == 5

    def test_load_unknown_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mgr = _manager(Path(tmp))
            assert mgr.load("ckpt_doesnotexist") is None

    def test_token_count_estimated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mgr = _manager(Path(tmp))
            msgs = [{"role": "user", "content": "x" * 100}]
            ckpt = mgr.save(session_id="s", turn_id=1, messages=msgs)
            # 100 chars / 4 = 25
            assert ckpt.token_count == 25


class TestAtomicWrites:
    def test_save_uses_compact_json(self) -> None:
        """Atomic write must use compact JSON (no indent) to keep size small."""
        with tempfile.TemporaryDirectory() as tmp:
            mgr = _manager(Path(tmp))
            mgr.save(
                session_id="s", turn_id=1,
                messages=[{"role": "user", "content": "x"}],
            )
            # Find the on-disk file.
            files = list((Path(tmp) / "ckpts").glob("*.json"))
            assert len(files) == 1
            content = files[0].read_text(encoding="utf-8")
            assert "\n  " not in content, "JSON should be compact"

    def test_no_tmp_files_left_behind(self) -> None:
        """Successful saves must not leave .tmp files behind."""
        with tempfile.TemporaryDirectory() as tmp:
            mgr = _manager(Path(tmp))
            for i in range(5):
                mgr.save(session_id="s", turn_id=i, messages=[])
            tmps = list((Path(tmp) / "ckpts").glob("*.tmp"))
            assert tmps == []

    def test_atomic_write_cleans_tmp_on_failure(self) -> None:
        """If the rename step fails, the .tmp file is removed.

        Inject an OSError into ``os.replace`` and verify cleanup.
        """
        with tempfile.TemporaryDirectory() as tmp:
            mgr = _manager(Path(tmp))
            with patch("agent.checkpoint.os.replace", side_effect=OSError("boom")):
                try:
                    mgr.save(session_id="s", turn_id=1, messages=[])
                except OSError:
                    pass
            tmps = list((Path(tmp) / "ckpts").glob("*.tmp"))
            assert tmps == []


class TestIndexCaching:
    def test_list_checkpoints_uses_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mgr = _manager(Path(tmp))
            mgr.save(session_id="s", turn_id=1, messages=[])
            mgr.save(session_id="s", turn_id=2, messages=[])
            # Populate cache by calling list once.
            cks = mgr.list_checkpoints()
            assert len(cks) == 2
            # Subsequent calls should hit cache — no filesystem IO.
            with patch("pathlib.Path.glob") as mock_glob:
                cks2 = mgr.list_checkpoints()
            assert len(cks2) == 2
            mock_glob.assert_not_called()

    def test_list_filters_by_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mgr = _manager(Path(tmp))
            mgr.save(session_id="a", turn_id=1, messages=[])
            mgr.save(session_id="b", turn_id=1, messages=[])
            mgr.save(session_id="a", turn_id=2, messages=[])
            only_a = mgr.list_checkpoints(session_id="a")
            assert {c.session_id for c in only_a} == {"a"}
            assert len(only_a) == 2

    def test_load_returns_from_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mgr = _manager(Path(tmp))
            ckpt = mgr.save(session_id="s", turn_id=1, messages=[])
            # Save populates cache — subsequent load should not open file.
            with patch("builtins.open", side_effect=AssertionError("should not open")):
                loaded = mgr.load(ckpt.checkpoint_id)
            assert loaded is not None
            assert loaded.checkpoint_id == ckpt.checkpoint_id


class TestDelete:
    def test_delete_removes_file_and_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mgr = _manager(Path(tmp))
            ckpt = mgr.save(session_id="s", turn_id=1, messages=[])
            assert mgr.delete(ckpt.checkpoint_id) is True
            assert mgr.load(ckpt.checkpoint_id) is None
            assert ckpt.checkpoint_id not in mgr._index

    def test_delete_cleans_stale_tmp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mgr = _manager(Path(tmp))
            ckpt = mgr.save(session_id="s", turn_id=1, messages=[])
            ckpt_path = Path(tmp) / "ckpts" / f"{ckpt.checkpoint_id}.json"
            # Drop a stale .tmp alongside the checkpoint file.
            tmp_file = ckpt_path.with_suffix(ckpt_path.suffix + ".tmp")
            tmp_file.write_text("garbage", encoding="utf-8")
            mgr.delete(ckpt.checkpoint_id)
            assert not tmp_file.exists()

    def test_delete_unknown_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mgr = _manager(Path(tmp))
            assert mgr.delete("ckpt_unknown") is False


class TestCleanupOld:
    def test_keeps_latest_n(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mgr = _manager(Path(tmp))
            for i in range(7):
                mgr.save(session_id="s", turn_id=i, messages=[])
            removed = mgr.cleanup_old(keep_latest=3)
            assert removed == 4
            assert len(mgr.list_checkpoints(session_id="s")) == 3

    def test_cleanup_keeps_across_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mgr = _manager(Path(tmp))
            # 5 in session a, 3 in session b — keep 2 per session.
            for i in range(5):
                mgr.save(session_id="a", turn_id=i, messages=[])
            for i in range(3):
                mgr.save(session_id="b", turn_id=i, messages=[])
            mgr.cleanup_old(keep_latest=2)
            assert len(mgr.list_checkpoints(session_id="a")) == 2
            assert len(mgr.list_checkpoints(session_id="b")) == 2


class TestLoadLatest:
    def test_returns_most_recent_for_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mgr = _manager(Path(tmp))
            mgr.save(session_id="s", turn_id=1, messages=[{"role": "user", "content": "old"}])
            mgr.save(session_id="s", turn_id=5, messages=[{"role": "user", "content": "new"}])
            latest = mgr.load_latest("s")
            assert latest is not None
            assert latest.messages[0]["content"] == "new"
            assert latest.turn_id == 5

    def test_no_checkpoints_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mgr = _manager(Path(tmp))
            assert mgr.load_latest("nope") is None


class TestThreadSafety:
    def test_concurrent_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mgr = _manager(Path(tmp))
            threads = [
                threading.Thread(target=lambda i=i: mgr.save(
                    session_id="s", turn_id=i, messages=[]))
                for i in range(20)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            assert len(mgr.list_checkpoints()) == 20


class TestRefreshIndex:
    def test_refresh_picks_up_external_files(self) -> None:
        """Files written outside the manager should appear after refresh."""
        with tempfile.TemporaryDirectory() as tmp:
            mgr = _manager(Path(tmp))
            # Force an initial cache load (empty).
            assert mgr.list_checkpoints() == []
            # Drop a checkpoint file directly on disk.
            external = {
                "checkpoint_id": "ckpt_external",
                "session_id": "ext",
                "turn_id": 1,
                "messages": [],
                "tool_calls": [],
                "tool_results": [],
                "pending_actions": [],
                "metadata": {},
                "created_at": 1.0,
                "token_count": 0,
            }
            (Path(tmp) / "ckpts" / "ckpt_external.json").write_text(
                json.dumps(external), encoding="utf-8"
            )
            # Drop the in-memory cache and re-list — should re-read disk.
            mgr._index.clear()
            cks = mgr.list_checkpoints()
            ids = {c.checkpoint_id for c in cks}
            assert "ckpt_external" in ids