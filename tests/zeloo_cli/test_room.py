"""Regression tests for the /room slash command (group-chat room management).

Covers CLICommandsMixin._handle_room_command verbs:
  - list:  enumerate active rooms
  - create: create a new room (idempotent)
  - show:   dump full room metadata
  - disband: tombstone a room

All tests use a tmp shared-state.db (hosted_rooms) so they don't
touch the live /root/.Zeloo/shared-state.db. The handler reads
default_db_path() at call time; we monkeypatch that to return our
tmp file.

Inverse / sentinel tests guard the public surface — if any of these
break loudly, the /room command's contract has drifted.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Make the zeloo repo importable
sys.path.insert(0, "/root/zeloo")
sys.path.insert(0, "/root/zeloo/.venv/lib/python3.11/site-packages")

from zeloo_cli.cli_commands_mixin import CLICommandsMixin  # noqa: E402


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def tmp_room_db(tmp_path, monkeypatch):
    """Use a tmp file as default_db_path() for hosted_rooms.

    The hosted_rooms module calls default_db_path() at every API call
    (it's a function, not a config), so monkeypatching the import in
    gateway.hosted_rooms is the only correct seam.
    """
    db_path = tmp_path / "shared-state.db"
    # Force the schema to exist by calling create_room once
    monkeypatch.setattr(
        "gateway.hosted_rooms.default_db_path", lambda: db_path
    )
    monkeypatch.setattr(
        "gateway.hosted_rooms.local_authority_gateway_id",
        lambda: "install:test-uuid-12345"
    )
    # Pre-create the schema by importing (idempotent)
    from gateway.hosted_rooms import create_room as _cr
    # Touch the DB so schema initializes
    try:
        _cr(db_path, room_id="_init_", name="_init_",
            members=[], authority_gateway_id="install:test-uuid-12345")
        from gateway.hosted_rooms import disband_room as _dr
        _dr(db_path, room_id="_init_", expected_gateway_id="install:test-uuid-12345",
            expected_epoch=1)
    except Exception:
        pass  # schema might already exist
    return db_path


def _call_room(cmd: str) -> str:
    """Capture stdout from /room subcommand (the handler uses print())."""
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        CLICommandsMixin._handle_room_command(None, cmd)
    return buf.getvalue()


# ============================================================
# list verb
# ============================================================

class TestRoomList:
    """`/room list` enumerates active rooms."""

    def test_empty_db(self, tmp_room_db):
        out = _call_room("/room list")
        assert "No active rooms" in out

    def test_no_arg_defaults_to_list(self, tmp_room_db):
        # `/room` alone should behave like `/room list`
        out = _call_room("/room")
        assert "No active rooms" in out

    def test_lists_one_room(self, tmp_room_db):
        from gateway.hosted_rooms import create_room as _cr
        _cr(tmp_room_db, room_id="alpha", name="Alpha",
            members=[], authority_gateway_id="install:test-uuid-12345")
        out = _call_room("/room list")
        assert "alpha" in out
        assert "Alpha" in out
        assert "1 room" in out

    def test_lists_multiple_rooms(self, tmp_room_db):
        from gateway.hosted_rooms import create_room as _cr
        for rid, name in [("a", "A"), ("b", "B"), ("c", "C")]:
            _cr(tmp_room_db, room_id=rid, name=name, members=[],
                authority_gateway_id="install:test-uuid-12345")
        out = _call_room("/room list")
        assert "3 room" in out
        for rid in ("a", "b", "c"):
            assert rid in out


# ============================================================
# create verb
# ============================================================

class TestRoomCreate:
    """`/room create <id> <name...>` creates a new room."""

    def test_creates_room(self, tmp_room_db):
        out = _call_room("/room create myroom MyFirstRoom")
        assert "Created room" in out
        assert "myroom" in out

    def test_creates_idempotently(self, tmp_room_db):
        # Two creates with same id+name should both succeed (idempotent)
        _call_room("/room create alpha Alpha")
        out = _call_room("/room create alpha Alpha")
        # Second create is idempotent — should not error
        assert "alpha" in out

    def test_missing_name_uses_id(self, tmp_room_db):
        out = _call_room("/room create solo")
        assert "Created room" in out
        assert "solo" in out

    def test_no_args_prints_usage(self, tmp_room_db):
        out = _call_room("/room create")
        assert "Usage" in out

    def test_create_then_appears_in_list(self, tmp_room_db):
        _call_room("/room create beta Beta")
        out = _call_room("/room list")
        assert "beta" in out


# ============================================================
# show verb
# ============================================================

class TestRoomShow:
    """`/room show <id>` dumps full room metadata."""

    def test_show_existing_room(self, tmp_room_db):
        _call_room("/room create gamma GammaRoom")
        out = _call_room("/room show gamma")
        assert "Room gamma" in out
        assert "name:" in out
        assert "authority_gateway_id" in out
        assert "authority_epoch" in out

    def test_show_nonexistent_room(self, tmp_room_db):
        out = _call_room("/room show nonexistent")
        assert "not found" in out

    def test_show_requires_id(self, tmp_room_db):
        out = _call_room("/room show")
        assert "Usage" in out


# ============================================================
# disband verb
# ============================================================

class TestRoomDisband:
    """`/room disband <id>` tombstones a room (idempotent)."""

    def test_disband_existing_room(self, tmp_room_db):
        _call_room("/room create delta Delta")
        out = _call_room("/room disband delta")
        assert "Disbanded" in out
        assert "delta" in out

    def test_disbanded_room_no_longer_in_list(self, tmp_room_db):
        _call_room("/room create epsilon Epsilon")
        _call_room("/room disband epsilon")
        out = _call_room("/room list")
        assert "epsilon" not in out

    def test_disband_nonexistent_room(self, tmp_room_db):
        out = _call_room("/room disband nonexistent")
        assert "not found" in out

    def test_disband_requires_id(self, tmp_room_db):
        out = _call_room("/room disband")
        assert "Usage" in out


# ============================================================
# unknown verb
# ============================================================

class TestRoomUnknownVerb:
    """Unknown verb: print help, not crash."""

    def test_unknown_verb_prints_usage(self, tmp_room_db):
        out = _call_room("/room bananapancakes")
        assert "Unknown verb" in out
        assert "list" in out
        assert "create" in out
        assert "disband" in out


# ============================================================
# Inverse / sentinel: surface contract must not silently drift
# ============================================================

def test_room_handler_is_discoverable_via_naming_convention():
    """The /room dispatch is via naming convention (_handle_<name>_command).

    If someone renames the handler, the dispatch in cli.py falls through
    to /room → skill/quick_command matching (silently broken). This
    test guards the convention: a future refactor must update both.
    """
    handler = getattr(CLICommandsMixin, "_handle_room_command", None)
    assert handler is not None and callable(handler), (
        "_handle_room_command missing or non-callable. /room dispatch "
        "depends on the naming convention in cli.py:_slash_handler."
    )


def test_room_uses_dedicated_db_not_state_db():
    """Sentinel: the room storage file is shared-state.db, NOT state.db.

    If someone refactors default_db_path() to return state.db, every
    profile gateway would write to the master session store (the
    2026-09-03 multi-writer corruption vector).
    """
    from gateway.hosted_rooms import default_db_path
    db_name = default_db_path().name
    assert db_name == "shared-state.db", (
        f"default_db_path() returns {db_name!r}, expected 'shared-state.db'. "
        "Moving rooms into state.db reintroduces the multi-writer "
        "corruption vector documented 2026-09-03."
    )
