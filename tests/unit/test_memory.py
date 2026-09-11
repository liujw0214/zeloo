"""Tests for memory tools — MemoryStore and the memory/session_search tools."""

# ruff: noqa: E402
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from agent.memory_manager import MemoryStore
from tools.memory_tool import memory, session_search

# ── MemoryStore tests ────────────────────────────────────────────────


def test_memory_store_write_and_read() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = MemoryStore(home=Path(tmp))
        store.write("memory", "hello memory")
        assert store.read("memory") == "hello memory"


def test_memory_store_write_user() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = MemoryStore(home=Path(tmp))
        store.write("user", "user profile data")
        assert store.read("user") == "user profile data"


def test_memory_store_read_missing_returns_empty() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = MemoryStore(home=Path(tmp))
        assert store.read("memory") == ""


def test_memory_store_append_to_empty() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = MemoryStore(home=Path(tmp))
        store.append("memory", "first entry")
        assert store.read("memory") == "first entry"


def test_memory_store_append_to_existing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = MemoryStore(home=Path(tmp))
        store.write("memory", "line1")
        store.append("memory", "line2")
        content = store.read("memory")
        assert "line1" in content
        assert "line2" in content
        assert "line1" in content.split("\n")[0]


def test_memory_store_write_truncates_long_content() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = MemoryStore(home=Path(tmp), max_chars=10)
        store.write("memory", "x" * 100)
        assert len(store.read("memory")) == 10


def test_memory_store_format_for_prompt_empty() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = MemoryStore(home=Path(tmp))
        assert store.format_for_system_prompt("memory") == ""


def test_memory_store_format_for_prompt_with_content() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = MemoryStore(home=Path(tmp))
        store.write("memory", "some memory")
        formatted = store.format_for_system_prompt("memory")
        assert "MEMORY" in formatted
        assert "some memory" in formatted


# ── memory tool tests (mocked agent) ─────────────────────────────────


def test_memory_tool_no_agent_returns_error() -> None:
    with patch("run_agent._current_agent") as mock_ctx:
        mock_ctx.get.return_value = None
        result = memory("read")
        assert "Error" in result
        assert "not available" in result.lower()


def test_memory_tool_read() -> None:
    mock_store = MagicMock()
    mock_store.read.return_value = "stored memory content"
    mock_agent = MagicMock()
    mock_agent._memory_store = mock_store
    with patch("run_agent._current_agent") as mock_ctx:
        mock_ctx.get.return_value = mock_agent
        result = memory("read", "memory")
    assert result == "stored memory content"
    mock_store.read.assert_called_once_with("memory")


def test_memory_tool_write() -> None:
    mock_store = MagicMock()
    mock_agent = MagicMock()
    mock_agent._memory_store = mock_store
    with patch("run_agent._current_agent") as mock_ctx:
        mock_ctx.get.return_value = mock_agent
        result = memory("write", "memory", "new content")
    assert "written" in result.lower()
    mock_store.write.assert_called_once_with("memory", "new content")


def test_memory_tool_append() -> None:
    mock_store = MagicMock()
    mock_agent = MagicMock()
    mock_agent._memory_store = mock_store
    with patch("run_agent._current_agent") as mock_ctx:
        mock_ctx.get.return_value = mock_agent
        result = memory("append", "user", "extra info")
    assert "appended" in result.lower()
    mock_store.append.assert_called_once_with("user", "extra info")


def test_memory_tool_unknown_action() -> None:
    mock_store = MagicMock()
    mock_agent = MagicMock()
    mock_agent._memory_store = mock_store
    with patch("run_agent._current_agent") as mock_ctx:
        mock_ctx.get.return_value = mock_agent
        result = memory("delete", "memory")
    assert "Error" in result
    assert "Unknown action" in result


def test_session_search_no_agent_returns_error() -> None:
    with patch("run_agent._current_agent") as mock_ctx:
        mock_ctx.get.return_value = None
        result = session_search("test")
        assert "Error" in result


if __name__ == "__main__":
    test_memory_store_write_and_read()
    test_memory_store_write_user()
    test_memory_store_read_missing_returns_empty()
    test_memory_store_append_to_empty()
    test_memory_store_append_to_existing()
    test_memory_store_write_truncates_long_content()
    test_memory_store_format_for_prompt_empty()
    test_memory_store_format_for_prompt_with_content()
    test_memory_tool_no_agent_returns_error()
    test_memory_tool_read()
    test_memory_tool_write()
    test_memory_tool_append()
    test_memory_tool_unknown_action()
    test_session_search_no_agent_returns_error()
    print("All memory tests passed!")
