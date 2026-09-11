"""Tests for agent/session_flush.py (M4 — session-end memory flush)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from agent.session_flush import (  # noqa: E402
    SessionMemoryFlusher,
    install_session_flush_hook,
)
from plugins.hooks import HookType, get_hook_registry  # noqa: E402


# ── SessionMemoryFlusher unit tests ──────────────────────────────────


def _flusher(tmp: Path, max_chars: int = 8000) -> SessionMemoryFlusher:
    mem = tmp / "MEMORY.md"
    return SessionMemoryFlusher(mem_path=mem, max_chars=max_chars)


def test_add_fact_records_line_with_date(tmp_path: Path) -> None:
    flusher = _flusher(tmp_path)
    flusher.add_fact("User prefers dark mode.")
    written = flusher.flush()
    assert written == 1
    body = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "User prefers dark mode." in body
    # Date prefix in YYYY-MM-DD format
    import re

    assert re.search(r"-\s*\[\d{4}-\d{2}-\d{2}\] User prefers dark mode\.", body)


def test_add_fact_with_tags_appended(tmp_path: Path) -> None:
    flusher = _flusher(tmp_path)
    flusher.add_fact("Loves Python", tags=["lang", "python"])
    flusher.flush()
    body = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "#lang" in body
    assert "#python" in body


def test_flush_with_no_pending_returns_zero(tmp_path: Path) -> None:
    flusher = _flusher(tmp_path)
    assert flusher.flush() == 0
    # The file should not be created on a no-op flush.
    assert not (tmp_path / "MEMORY.md").exists()


def test_flush_appends_to_existing_file(tmp_path: Path) -> None:
    mem = tmp_path / "MEMORY.md"
    mem.write_text("# Header\n\n", encoding="utf-8")
    flusher = SessionMemoryFlusher(mem_path=mem)
    flusher.add_fact("first fact")
    flusher.flush()
    body = mem.read_text(encoding="utf-8")
    assert body.startswith("# Header")
    assert "first fact" in body


def test_flush_creates_parent_dir(tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "down" / "MEMORY.md"
    flusher = SessionMemoryFlusher(mem_path=nested)
    flusher.add_fact("nested fact")
    assert flusher.flush() == 1
    assert nested.exists()


def test_flush_clears_pending_buffer(tmp_path: Path) -> None:
    flusher = _flusher(tmp_path)
    flusher.add_fact("once")
    flusher.flush()
    # A second flush with no new facts must be a no-op.
    assert flusher.flush() == 0


def test_archive_triggers_when_size_exceeds_double_max(tmp_path: Path) -> None:
    """When ``2 × max_chars`` is exceeded, the file is rotated to archive/."""
    mem = tmp_path / "MEMORY.md"
    flusher = SessionMemoryFlusher(mem_path=mem, max_chars=100)
    # Seed a file just below the rotation threshold.
    mem.write_text("x" * 199, encoding="utf-8")  # len() == 199 ≤ 2*100 == 200

    flusher.add_fact("trigger archive")
    flusher.flush()

    archive_dir = tmp_path / "archive"
    assert archive_dir.exists()
    archives = list(archive_dir.glob("*-MEMORY.md"))
    assert len(archives) == 1
    # The fresh MEMORY.md is recreated with a header.
    body = mem.read_text(encoding="utf-8")
    assert "Persistent memory (archived)" in body


def test_archive_does_not_trigger_under_threshold(tmp_path: Path) -> None:
    mem = tmp_path / "MEMORY.md"
    flusher = SessionMemoryFlusher(mem_path=mem, max_chars=1000)
    mem.write_text("small", encoding="utf-8")
    flusher.add_fact("still small")
    flusher.flush()
    archive_dir = tmp_path / "archive"
    assert not archive_dir.exists()


# ── install_session_flush_hook integration ───────────────────────────


def test_install_registers_handler(tmp_path: Path) -> None:
    mem = tmp_path / "MEMORY.md"
    flusher = install_session_flush_hook(mem_path=mem)
    try:
        # The registry must contain at least one callback for ON_SESSION_END.
        registry = get_hook_registry()
        callbacks = registry._hooks.get(HookType.ON_SESSION_END, [])
        assert any(cb is not None for _, cb in callbacks)
    finally:
        # Cleanup: unregister by plugin name so we don't leak between tests.
        registry = get_hook_registry()
        registry.unregister(HookType.ON_SESSION_END, "zeloo.session_flush")


def test_install_handler_flushes_facts_via_metadata(tmp_path: Path) -> None:
    mem = tmp_path / "MEMORY.md"
    flusher = install_session_flush_hook(mem_path=mem)
    try:
        flusher.add_fact("preloaded")
        registry = get_hook_registry()
        # Fire with metadata={'facts': [...]} to mimic run_agent.shutdown.
        registry.fire(HookType.ON_SESSION_END, "sess-1", duration=1.0)
        # The preloaded fact should have been flushed on shutdown.
        assert "preloaded" in mem.read_text(encoding="utf-8")
    finally:
        registry = get_hook_registry()
        registry.unregister(HookType.ON_SESSION_END, "zeloo.session_flush")


def test_install_handler_accepts_facts_in_metadata(tmp_path: Path) -> None:
    mem = tmp_path / "MEMORY.md"
    flusher = install_session_flush_hook(mem_path=mem)
    try:
        registry = get_hook_registry()
        registry.fire(
            HookType.ON_SESSION_END,
            "sess-2",
            duration=2.0,
            facts=["Likes dark mode", ("Allergic to shellfish", ["health"])],
        )
        body = mem.read_text(encoding="utf-8")
        assert "Likes dark mode" in body
        assert "Allergic to shellfish" in body
        assert "#health" in body
    finally:
        registry = get_hook_registry()
        registry.unregister(HookType.ON_SESSION_END, "zeloo.session_flush")


def test_install_handler_failure_does_not_propagate(tmp_path: Path) -> None:
    """Even if the flusher throws internally, the registry swallows it."""
    mem = tmp_path / "MEMORY.md"
    flusher = install_session_flush_hook(mem_path=mem)
    try:
        # Force a failure by monkey-patching ``flush`` to raise.
        def _boom() -> int:
            raise RuntimeError("disk full")

        flusher.flush = _boom  # type: ignore[assignment]
        registry = get_hook_registry()
        # Must not raise — the registry's fire() catches per-callback errors.
        registry.fire(HookType.ON_SESSION_END, "sess-3")
    finally:
        registry = get_hook_registry()
        registry.unregister(HookType.ON_SESSION_END, "zeloo.session_flush")