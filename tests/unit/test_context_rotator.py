"""Unit tests for agent.context_rotator.

Covers:
- ContextRotator default / custom initialisation
- rotate() eviction flow when over budget
- rotate() leaves small messages untouched
- mark_for_eviction() and restore_placeholder() round-trip
- get_eviction_history() chronological list
- clear_history() resets persisted state
- EvictionEvent dataclass shape
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.context_rotator import (
    DEFAULT_PLACEHOLDER,
    ContextRotator,
    EvictionEvent,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def rotator(tmp_path: Path) -> ContextRotator:
    return ContextRotator(
        token_budget=200,
        history_path=tmp_path / "history.json",
    )


@pytest.fixture
def small_messages() -> list[dict]:
    return [
        {"role": "system", "content": "you are helpful"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


@pytest.fixture
def tool_messages() -> list[dict]:
    """Multiple tool-role messages — only tool messages get evicted."""
    return [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "do thing"},
        {"role": "tool", "name": "first", "content": "x" * 800},
        {"role": "assistant", "content": "ack"},
        {"role": "tool", "name": "second", "content": "y" * 800},
        {"role": "assistant", "content": "done"},
    ]


# ── Init ──────────────────────────────────────────────────────────────


class TestInit:
    def test_default(self, tmp_path: Path) -> None:
        rotator = ContextRotator(history_path=tmp_path / "h.json")
        assert rotator.token_budget == 8000
        assert rotator.placeholder == DEFAULT_PLACEHOLDER
        assert rotator.history_path.parent.exists()

    def test_custom(self, tmp_path: Path) -> None:
        rotator = ContextRotator(
            token_budget=256,
            history_path=tmp_path / "h.json",
            placeholder="<<EVICTED>>",
        )
        assert rotator.token_budget == 256
        assert rotator.placeholder == "<<EVICTED>>"


# ── rotate ────────────────────────────────────────────────────────────


class TestRotate:
    def test_under_budget_no_change(self, rotator: ContextRotator, small_messages: list[dict]) -> None:
        result = rotator.rotate(small_messages)
        assert result is small_messages
        # No tool messages → no eviction.
        assert all(not m.get("_evicted") for m in result)

    def test_over_budget_evicts_tool(self, rotator: ContextRotator, tool_messages: list[dict]) -> None:
        rotator.rotate(tool_messages)
        evicted_count = sum(1 for m in tool_messages if m.get("_evicted"))
        # At least one of the tool messages should have been evicted.
        assert evicted_count >= 1
        # System message must remain untouched.
        assert tool_messages[0]["content"] == "sys"

    def test_skips_already_evicted(self, rotator: ContextRotator, tool_messages: list[dict]) -> None:
        rotator.rotate(tool_messages)
        # Re-rotate should be idempotent.
        before = sum(1 for m in tool_messages if m.get("_evicted"))
        rotator.rotate(tool_messages)
        after = sum(1 for m in tool_messages if m.get("_evicted"))
        assert before == after

    def test_user_messages_preserved(self, rotator: ContextRotator) -> None:
        msgs = [
            {"role": "user", "content": "x" * 2000},
            {"role": "assistant", "content": "y" * 2000},
        ]
        rotator.rotate(msgs)
        # Neither role is "tool" → neither should be evicted.
        assert all(not m.get("_evicted") for m in msgs)


# ── mark_for_eviction / restore_placeholder ───────────────────────────


class TestMarkerAndRestore:
    def test_mark_does_not_raise(self, rotator: ContextRotator) -> None:
        rotator.mark_for_eviction("foo")

    def test_restore_after_rotate(self, rotator: ContextRotator, tool_messages: list[dict]) -> None:
        rotator.rotate(tool_messages)
        evicted_msg = next(m for m in tool_messages if m.get("_evicted"))
        msg_id = evicted_msg["message_id"]
        original = rotator.restore_placeholder(msg_id)
        assert original is not None
        assert original.startswith("x" * 100) or original.startswith("y" * 100)

    def test_restore_unknown_returns_none(self, rotator: ContextRotator) -> None:
        assert rotator.restore_placeholder("nope") is None


# ── history / clear ────────────────────────────────────────────────────


class TestHistory:
    def test_empty_history(self, rotator: ContextRotator) -> None:
        assert rotator.get_eviction_history() == []

    def test_history_records_eviction(self, rotator: ContextRotator, tool_messages: list[dict]) -> None:
        rotator.rotate(tool_messages)
        history = rotator.get_eviction_history()
        assert len(history) >= 1
        for entry in history:
            assert "message_id" in entry
            assert "evicted_at" in entry
            assert "original_chars" in entry

    def test_clear_history(self, rotator: ContextRotator, tool_messages: list[dict]) -> None:
        rotator.rotate(tool_messages)
        assert rotator.get_eviction_history()
        rotator.clear_history()
        assert rotator.get_eviction_history() == []


# ── EvictionEvent dataclass ───────────────────────────────────────────


class TestEvictionEvent:
    def test_to_dict(self) -> None:
        event = EvictionEvent(
            message_id="abc",
            evicted_at=1.0,
            original_chars=400,
            placeholder_chars=20,
            tool_name="search",
        )
        d = event.to_dict()
        assert d["message_id"] == "abc"
        assert d["tool_name"] == "search"
        assert d["original_chars"] == 400