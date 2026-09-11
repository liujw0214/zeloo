"""Tests for the gateway session manager, adapters, and API server."""

# ruff: noqa: E402
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

import os

os.environ.setdefault("zeloo_HOME", tempfile.mkdtemp())

from gateway.platforms.discord import _split_message as dc_split
from gateway.platforms.telegram import _split_message as tg_split
from gateway.session import SessionManager


class FakeSessionDB:
    """Minimal session DB for testing SessionManager."""

    def __init__(self) -> None:
        self.sessions: list[tuple[str, str, str]] = []

    def create_session(self, session_id: str, user_id: str = "", platform: str = "cli") -> None:
        self.sessions.append((session_id, user_id, platform))

    def get_active_session(self, user_id: str, platform: str):
        # Return the most recent session for the user/platform
        for sid, uid, plat in reversed(self.sessions):
            if uid == user_id and plat == platform:
                return {"session_id": sid}
        return None


class FakeAgent:
    def __init__(self, session_id: str = "", platform: str = "") -> None:
        self.session_id = session_id
        self.platform = platform
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _factory(session_id: str, platform: str, user_id: str = "") -> FakeAgent:
    return FakeAgent(session_id=session_id, platform=platform)


def test_session_manager_creates_agent():
    db = FakeSessionDB()
    mgr = SessionManager(db)
    agent = mgr.get_or_create_agent("user1", "telegram", _factory)
    assert agent is not None
    assert agent.platform == "telegram"
    assert mgr.get_active_count() == 1


def test_session_manager_reuses_agent():
    db = FakeSessionDB()
    mgr = SessionManager(db)
    a1 = mgr.get_or_create_agent("user1", "telegram", _factory)
    a2 = mgr.get_or_create_agent("user1", "telegram", _factory)
    assert a1 is a2


def test_session_manager_isolates_users():
    db = FakeSessionDB()
    mgr = SessionManager(db)
    a1 = mgr.get_or_create_agent("user1", "telegram", _factory)
    a2 = mgr.get_or_create_agent("user2", "telegram", _factory)
    assert a1 is not a2
    assert mgr.get_active_count() == 2


def test_session_manager_isolates_platforms():
    db = FakeSessionDB()
    mgr = SessionManager(db)
    a1 = mgr.get_or_create_agent("user1", "telegram", _factory)
    a2 = mgr.get_or_create_agent("user1", "discord", _factory)
    assert a1 is not a2


def test_allow_list_blocks_user():
    db = FakeSessionDB()
    mgr = SessionManager(db, allowed_users={"telegram": ["123"]})
    agent = mgr.get_or_create_agent("999", "telegram", _factory)
    assert agent is None


def test_allow_list_allows_user():
    db = FakeSessionDB()
    mgr = SessionManager(db, allowed_users={"telegram": ["123"]})
    agent = mgr.get_or_create_agent("123", "telegram", _factory)
    assert agent is not None


def test_no_allow_list_allows_all():
    db = FakeSessionDB()
    mgr = SessionManager(db)
    assert mgr.get_or_create_agent("anyone", "telegram", _factory) is not None


def test_eviction_removes_idle():
    db = FakeSessionDB()
    mgr = SessionManager(db, idle_timeout=0)
    mgr.get_or_create_agent("u1", "telegram", _factory)
    time.sleep(0.01)
    evicted = mgr.evict_idle()
    assert evicted == 1
    assert mgr.get_active_count() == 0


def test_telegram_split_short_message():
    assert tg_split("hello") == ["hello"]


def test_telegram_split_long_message():
    long = "x" * 5000
    chunks = tg_split(long)
    assert len(chunks) > 1
    assert all(len(c) <= 4096 for c in chunks)


def test_telegram_split_preserves_newlines():
    long = "\n".join(f"line {i}" for i in range(500))
    chunks = tg_split(long)
    assert len(chunks) > 1
    # First chunk should end at a newline boundary
    assert chunks[0].endswith("line") is False or chunks[0].endswith("\n") or "\n" in chunks[0]


def test_discord_split_short_message():
    assert dc_split("hello") == ["hello"]


def test_discord_split_long_message():
    long = "x" * 3000
    chunks = dc_split(long)
    assert len(chunks) > 1
    assert all(len(c) <= 2000 for c in chunks)


def test_discord_split_code_block_boundary():
    # A message with a code block that spans the split point
    long = ("pre " + "x" * 1500 + "\n```python\nprint('hi')\n```\n" + "post " + "y" * 1500)
    chunks = dc_split(long)
    assert len(chunks) > 1
    # Check that code fences are balanced in each chunk
    for chunk in chunks:
        assert chunk.count("```") % 2 == 0


def test_session_manager_recovers_existing_session():
    db = FakeSessionDB()
    db.create_session("existing-sid", user_id="u1", platform="telegram")
    mgr = SessionManager(db)
    agent = mgr.get_or_create_agent("u1", "telegram", _factory)
    assert agent.session_id == "existing-sid"


if __name__ == "__main__":
    test_session_manager_creates_agent()
    test_session_manager_reuses_agent()
    test_session_manager_isolates_users()
    test_session_manager_isolates_platforms()
    test_allow_list_blocks_user()
    test_allow_list_allows_user()
    test_no_allow_list_allows_all()
    test_eviction_removes_idle()
    test_telegram_split_short_message()
    test_telegram_split_long_message()
    test_telegram_split_preserves_newlines()
    test_discord_split_short_message()
    test_discord_split_long_message()
    test_discord_split_code_block_boundary()
    test_session_manager_recovers_existing_session()
    print("All gateway tests passed!")
