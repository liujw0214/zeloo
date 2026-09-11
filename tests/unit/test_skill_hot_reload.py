"""Tests for skill_hot_reload module — polling watcher for SKILL.md files."""

from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, ".")


def _write_skill(root: Path, name: str, body: str = "hello") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    p = skill_dir / "SKILL.md"
    p.write_text(body, encoding="utf-8")
    return p


# ── Core polling behavior ─────────────────────────────────────────


def test_poll_returns_no_events_on_first_run_when_directory_is_empty():
    from agent.skill_hot_reload import SkillHotReloader

    with tempfile.TemporaryDirectory() as td:
        rel = SkillHotReloader(roots=[Path(td)])
        events = rel.poll()
        assert events == []
        assert rel.tracked_count() == 0


def test_poll_detects_added_skill():
    from agent.skill_hot_reload import SkillChangeKind, SkillHotReloader

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        rel = SkillHotReloader(roots=[root])
        _write_skill(root, "alpha")
        events = rel.poll()
        assert len(events) == 1
        assert events[0].kind == SkillChangeKind.ADDED
        assert events[0].skill_name == "alpha"
        assert rel.tracked_count() == 1


def test_poll_detects_modified_skill():
    from agent.skill_hot_reload import SkillChangeKind, SkillHotReloader

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = _write_skill(root, "beta", body="v1")
        rel = SkillHotReloader(roots=[root])
        rel.poll()  # baseline
        time.sleep(0.05)  # ensure mtime_ns changes on coarse filesystems
        p.write_text("v2 — much longer body to push mtime and size", encoding="utf-8")
        events = rel.poll()
        assert len(events) == 1
        assert events[0].kind == SkillChangeKind.MODIFIED
        assert events[0].skill_name == "beta"


def test_poll_detects_removed_skill():
    from agent.skill_hot_reload import SkillChangeKind, SkillHotReloader

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        skill_dir = root / "gamma"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("x", encoding="utf-8")
        rel = SkillHotReloader(roots=[root])
        rel.poll()
        skill_md.unlink()  # remove the SKILL.md file
        events = rel.poll()
        assert len(events) == 1
        assert events[0].kind == SkillChangeKind.REMOVED
        assert events[0].skill_name == "gamma"


def test_poll_is_stable_when_nothing_changes():
    from agent.skill_hot_reload import SkillHotReloader

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_skill(root, "stable")
        rel = SkillHotReloader(roots=[root])
        rel.poll()
        events = rel.poll()
        assert events == []


def test_poll_handles_nested_subdirectories():
    from agent.skill_hot_reload import SkillChangeKind, SkillHotReloader

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # Mimic category/optional_skills/ structure
        nested = root / "category" / "sub-skill"
        nested.mkdir(parents=True)
        (nested / "SKILL.md").write_text("nested", encoding="utf-8")
        rel = SkillHotReloader(roots=[root])
        events = rel.poll()
        assert len(events) == 1
        assert events[0].kind == SkillChangeKind.ADDED
        assert events[0].skill_name == "sub-skill"


# ── Subscribers ───────────────────────────────────────────────────


def test_subscriber_receives_events():
    from agent.skill_hot_reload import SkillChangeEvent, SkillHotReloader

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        rel = SkillHotReloader(roots=[root])
        captured: list[SkillChangeEvent] = []
        rel.subscribe(captured.append)
        assert rel.subscriber_count() == 1

        _write_skill(root, "watched")
        rel.poll()
        assert len(captured) == 1
        assert captured[0].skill_name == "watched"


def test_subscriber_exception_does_not_break_delivery():
    from agent.skill_hot_reload import SkillHotReloader

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        rel = SkillHotReloader(roots=[root])
        good_calls: list[int] = []

        def bad(_evt):
            raise RuntimeError("boom")

        rel.subscribe(bad)
        rel.subscribe(lambda _evt: good_calls.append(1))

        _write_skill(root, "x")
        rel.poll()
        assert len(good_calls) == 1


def test_unsubscribe_removes_callback():
    from agent.skill_hot_reload import SkillHotReloader

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        rel = SkillHotReloader(roots=[root])
        cb = lambda _e: None  # noqa: E731
        rel.subscribe(cb)
        assert rel.subscriber_count() == 1
        assert rel.unsubscribe(cb) is True
        assert rel.subscriber_count() == 0
        assert rel.unsubscribe(cb) is False


def test_subscribe_rejects_non_callable():
    from agent.skill_hot_reload import SkillHotReloader

    rel = SkillHotReloader()
    try:
        rel.subscribe("not a callable")  # type: ignore[arg-type]
    except TypeError:
        return
    raise AssertionError("expected TypeError")


# ── add_root / multiple roots ─────────────────────────────────────


def test_add_root_deduplicates():
    from agent.skill_hot_reload import SkillHotReloader

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        rel = SkillHotReloader()
        rel.add_root(root)
        rel.add_root(root)
        assert rel.roots().count(root.resolve()) == 1


def test_multiple_roots_are_scanned():
    from agent.skill_hot_reload import SkillHotReloader

    with tempfile.TemporaryDirectory() as td1, tempfile.TemporaryDirectory() as td2:
        r1, r2 = Path(td1), Path(td2)
        _write_skill(r1, "a")
        _write_skill(r2, "b")
        rel = SkillHotReloader(roots=[r1, r2])
        events = rel.poll()
        names = {e.skill_name for e in events}
        assert names == {"a", "b"}


# ── Background thread ────────────────────────────────────────────


def test_start_and_stop_thread():
    from agent.skill_hot_reload import SkillHotReloader

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        rel = SkillHotReloader(roots=[root], poll_interval_s=0.05)
        received: list[str] = []
        rel.subscribe(lambda evt: received.append(evt.skill_name))
        rel.start()
        try:
            _write_skill(root, "background")
            # Give the thread time to poll at least once.
            for _ in range(40):
                if received:
                    break
                time.sleep(0.05)
            assert "background" in received
        finally:
            rel.stop()


def test_stop_is_safe_to_call_when_never_started():
    from agent.skill_hot_reload import SkillHotReloader

    rel = SkillHotReloader()
    rel.stop()  # must not raise


def test_start_is_idempotent():
    from agent.skill_hot_reload import SkillHotReloader

    rel = SkillHotReloader(poll_interval_s=0.05)
    rel.start()
    t1 = rel._thread  # noqa: SLF001
    rel.start()
    t2 = rel._thread  # noqa: SLF001
    assert t1 is t2
    rel.stop()


# ── Module-level singleton ────────────────────────────────────────


def test_get_default_reloader_returns_singleton():
    from agent import skill_hot_reload

    skill_hot_reload.reset_default_reloader()
    try:
        a = skill_hot_reload.get_default_reloader()
        b = skill_hot_reload.get_default_reloader()
        assert a is b
    finally:
        skill_hot_reload.reset_default_reloader()


def test_reset_default_reloader_clears_state():
    from agent import skill_hot_reload

    a = skill_hot_reload.get_default_reloader()
    skill_hot_reload.reset_default_reloader()
    b = skill_hot_reload.get_default_reloader()
    assert a is not b


# ── Snapshot ──────────────────────────────────────────────────────


def test_snapshot_returns_fingerprints():
    from agent.skill_hot_reload import SkillHotReloader

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_skill(root, "snap")
        rel = SkillHotReloader(roots=[root])
        rel.poll()
        snap = rel.snapshot()
        assert len(snap) == 1
        path, (mtime, size) = next(iter(snap.items()))
        assert path.name == "SKILL.md"
        assert mtime > 0
        assert size > 0


# ── Thread-safety smoke test ─────────────────────────────────────


def test_thread_safe_subscribe_during_poll():
    """Subscribers added during delivery must not deadlock."""
    from agent.skill_hot_reload import SkillHotReloader

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        rel = SkillHotReloader(roots=[root])

        def late_subscribe(evt):
            rel.subscribe(lambda _e: None)

        rel.subscribe(late_subscribe)
        _write_skill(root, "ts")
        # Run poll in a thread with a timeout to surface deadlocks.
        result: list[list] = []
        t = threading.Thread(
            target=lambda: result.append(rel.poll()), daemon=True
        )
        t.start()
        t.join(timeout=2.0)
        assert not t.is_alive()
        assert result and len(result[0]) == 1
