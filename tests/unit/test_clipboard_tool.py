"""Unit tests for tools/clipboard_tool.py.

Covers:
- ClipboardEntry dataclass (to_dict / from_dict)
- ClipboardTool.read/write/history (mocked subprocess)
- History deduplication of consecutive duplicates
- Persistence to ~/.Zeloo/clipboard_history.json
- Cross-platform backend selection (Windows / macOS / Linux)
- @tool-decorated function registration
"""

# ruff: noqa: E402
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from tools.clipboard_tool import (  # noqa: E402
    ClipboardEntry,
    ClipboardTool,
    clipboard_add,
    clipboard_clear,
    clipboard_history,
    clipboard_read,
    clipboard_write,
)


# ─────────────────────────────────────────────────────────────────────────────
# ClipboardEntry
# ─────────────────────────────────────────────────────────────────────────────


class TestClipboardEntry:
    def test_defaults(self) -> None:
        e = ClipboardEntry(content="x", timestamp=datetime.now())
        assert e.content_type == "text"

    def test_to_dict(self) -> None:
        ts = datetime(2026, 1, 1, 12, 0, 0)
        e = ClipboardEntry(content="hello", timestamp=ts, content_type="text")
        d = e.to_dict()
        assert d["content"] == "hello"
        assert d["content_type"] == "text"
        assert d["timestamp"] == ts.isoformat()

    def test_from_dict_round_trip(self) -> None:
        ts = datetime(2026, 2, 2, 9, 30)
        original = ClipboardEntry(content="data", timestamp=ts)
        payload = original.to_dict()
        rehydrated = ClipboardEntry.from_dict(payload)
        assert rehydrated.content == "data"
        assert rehydrated.timestamp == ts

    def test_from_dict_invalid_timestamp(self) -> None:
        e = ClipboardEntry.from_dict({"content": "x", "timestamp": "not-a-date"})
        assert e.content == "x"
        assert isinstance(e.timestamp, datetime)

    def test_from_dict_missing_fields(self) -> None:
        e = ClipboardEntry.from_dict({})
        assert e.content == ""
        assert e.content_type == "text"


# ─────────────────────────────────────────────────────────────────────────────
# ClipboardTool: history operations
# ─────────────────────────────────────────────────────────────────────────────


class TestClipboardToolHistory:
    @pytest.fixture
    def tool(self, tmp_path: Path) -> ClipboardTool:
        return ClipboardTool(history_path=tmp_path / "history.json", max_history=5)

    def test_initial_history_empty(self, tool: ClipboardTool) -> None:
        assert tool.history() == []

    def test_add_to_history(self, tool: ClipboardTool) -> None:
        tool.add_to_history("first")
        entries = tool.history()
        assert len(entries) == 1
        assert entries[0].content == "first"

    def test_consecutive_duplicates_replaced(self, tool: ClipboardTool) -> None:
        tool.add_to_history("same")
        tool.add_to_history("same")
        tool.add_to_history("same")
        assert len(tool.history()) == 1

    def test_different_entries_kept(self, tool: ClipboardTool) -> None:
        tool.add_to_history("a")
        tool.add_to_history("b")
        tool.add_to_history("a")  # not consecutive duplicate -> appended
        tool.add_to_history("a")  # consecutive -> replaces previous entry
        entries = tool.history()
        # "a" at idx 0, "b" at idx 1, then a new "a" appended, then "a" replaces it
        # (still one trailing entry)
        assert entries[0].content == "a"
        assert entries[1].content == "b"
        assert entries[-1].content == "a"
        assert len(entries) == 3

    def test_max_history_evicts_oldest(self, tool: ClipboardTool) -> None:
        for i in range(7):
            tool.add_to_history(f"entry-{i}")
        entries = tool.history()
        assert len(entries) == 5
        assert entries[0].content == "entry-2"
        assert entries[-1].content == "entry-6"

    def test_clear_history(self, tool: ClipboardTool) -> None:
        tool.add_to_history("a")
        tool.add_to_history("b")
        tool.clear_history()
        assert tool.history() == []
        # In-memory + on-disk both cleared.
        assert tool.history_path.exists()
        assert json.loads(tool.history_path.read_text()) == []

    def test_history_path_persists(self, tool: ClipboardTool) -> None:
        tool.add_to_history("persistent")
        assert tool.history_path.exists()
        data = json.loads(tool.history_path.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        assert data[0]["content"] == "persistent"

    def test_load_corrupt_history(self, tmp_path: Path) -> None:
        path = tmp_path / "h.json"
        path.write_text("{not valid json", encoding="utf-8")
        tool = ClipboardTool(history_path=path)
        assert tool.history() == []

    def test_load_non_list_history(self, tmp_path: Path) -> None:
        path = tmp_path / "h.json"
        path.write_text("{\"oops\": 1}", encoding="utf-8")
        tool = ClipboardTool(history_path=path)
        assert tool.history() == []

    def test_get_entry(self, tool: ClipboardTool) -> None:
        tool.add_to_history("a")
        tool.add_to_history("b")
        e = tool.get_entry(0)
        assert e is not None
        assert e.content == "a"
        assert tool.get_entry(99) is None
        assert tool.get_entry(-1) is None

    def test_delete_entry(self, tool: ClipboardTool) -> None:
        tool.add_to_history("a")
        tool.add_to_history("b")
        assert tool.delete_entry(0) is True
        assert [e.content for e in tool.history()] == ["b"]
        assert tool.delete_entry(99) is False


# ─────────────────────────────────────────────────────────────────────────────
# ClipboardTool: read/write (mocked backend)
# ─────────────────────────────────────────────────────────────────────────────


class TestClipboardToolReadWrite:
    @pytest.fixture
    def tool(self, tmp_path: Path) -> ClipboardTool:
        return ClipboardTool(history_path=tmp_path / "h.json", max_history=10)

    def test_read_via_backend(self, tool: ClipboardTool) -> None:
        with patch.object(tool.backend, "read", return_value="hello") as mock_read:
            assert tool.read() == "hello"
            mock_read.assert_called_once()

    def test_write_records_in_history(self, tool: ClipboardTool) -> None:
        with patch.object(tool.backend, "write", return_value=True) as mock_write:
            ok = tool.write("hi")
        assert ok is True
        mock_write.assert_called_once_with("hi")
        assert tool.history()[-1].content == "hi"

    def test_write_failure_does_not_record(self, tool: ClipboardTool) -> None:
        with patch.object(tool.backend, "write", return_value=False):
            ok = tool.write("oops")
        assert ok is False
        assert tool.history() == []

    def test_clear_delegates_to_backend(self, tool: ClipboardTool) -> None:
        with patch.object(tool.backend, "clear", return_value=True) as mock_clear:
            assert tool.clear() is True
        mock_clear.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# Cross-platform backend selection
# ─────────────────────────────────────────────────────────────────────────────


class TestClipboardBackendSelection:
    def test_windows_backend(self) -> None:
        with patch("tools.clipboard_tool.sys.platform", "win32"):
            with patch("tools.clipboard_tool.shutil.which", return_value=None):
                from tools.clipboard_tool import _ClipboardBackend

                backend = _ClipboardBackend()
        assert backend.platform == "win32"
        # PowerShell is always used on Windows.
        assert backend.tool_name == "powershell"

    def test_macos_backend_with_pbcopy(self) -> None:
        with patch("tools.clipboard_tool.sys.platform", "darwin"):
            with patch("tools.clipboard_tool.shutil.which", return_value="/usr/bin/pbcopy"):
                from tools.clipboard_tool import _ClipboardBackend

                backend = _ClipboardBackend()
        assert backend.platform == "darwin"
        assert backend.tool_name == "pbcopy"

    def test_macos_backend_missing_pbcopy(self) -> None:
        with patch("tools.clipboard_tool.sys.platform", "darwin"):
            with patch("tools.clipboard_tool.shutil.which", return_value=None):
                from tools.clipboard_tool import _ClipboardBackend

                backend = _ClipboardBackend()
        assert backend.tool_name == ""

    def test_linux_backend_prefers_xclip(self) -> None:
        def fake_which(name: str) -> str | None:
            if name == "xclip":
                return "/usr/bin/xclip"
            return None

        with patch("tools.clipboard_tool.sys.platform", "linux"):
            with patch("tools.clipboard_tool.shutil.which", side_effect=fake_which):
                from tools.clipboard_tool import _ClipboardBackend

                backend = _ClipboardBackend()
        assert backend.tool_name == "xclip"

    def test_linux_backend_falls_back_to_xsel(self) -> None:
        def fake_which(name: str) -> str | None:
            if name == "xsel":
                return "/usr/bin/xsel"
            return None

        with patch("tools.clipboard_tool.sys.platform", "linux"):
            with patch("tools.clipboard_tool.shutil.which", side_effect=fake_which):
                from tools.clipboard_tool import _ClipboardBackend

                backend = _ClipboardBackend()
        assert backend.tool_name == "xsel"

    def test_linux_no_tool(self) -> None:
        with patch("tools.clipboard_tool.sys.platform", "linux"):
            with patch("tools.clipboard_tool.shutil.which", return_value=None):
                from tools.clipboard_tool import _ClipboardBackend

                backend = _ClipboardBackend()
        assert backend.tool_name == ""


# ─────────────────────────────────────────────────────────────────────────────
# Persistence round-trip
# ─────────────────────────────────────────────────────────────────────────────


class TestClipboardPersistence:
    def test_reload_preserves_entries(self, tmp_path: Path) -> None:
        path = tmp_path / "persist.json"
        t1 = ClipboardTool(history_path=path, max_history=5)
        t1.add_to_history("hello")
        t1.add_to_history("world")

        t2 = ClipboardTool(history_path=path, max_history=5)
        assert [e.content for e in t2.history()] == ["hello", "world"]

    def test_consecutive_dedupe_persists(self, tmp_path: Path) -> None:
        path = tmp_path / "dedupe.json"
        t = ClipboardTool(history_path=path, max_history=10)
        t.add_to_history("a")
        t.add_to_history("a")
        t.add_to_history("a")
        # Only one entry on disk after dedupe.
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data) == 1

    def test_history_path_under_default(self, monkeypatch, tmp_path: Path) -> None:
        # The default path is ``~/.Zeloo/clipboard_history.json``.
        monkeypatch.setattr(
            "tools.clipboard_tool.Path.home",
            classmethod(lambda cls: tmp_path),
        )
        from tools.clipboard_tool import _default_history_path

        path = _default_history_path()
        assert path.name == "clipboard_history.json"
        assert path.parent.name == ".Zeloo"
        assert path.parent.parent == tmp_path


# ─────────────────────────────────────────────────────────────────────────────
# @tool-decorated registration
# ─────────────────────────────────────────────────────────────────────────────


class TestClipboardToolRegistration:
    def test_all_clipboard_tools_registered(self) -> None:
        from tools.base import get_registry

        registry = get_registry()
        for name in (
            "clipboard_read",
            "clipboard_write",
            "clipboard_clear",
            "clipboard_history",
            "clipboard_add",
        ):
            assert name in registry.get_names(), f"{name} missing"

    def test_clipboard_read_invocation(self) -> None:
        mock_backend = MagicMock()
        mock_backend.read.return_value = "snippet"
        with patch("tools.clipboard_tool._default_tool") as mock_tool:
            mock_tool.read.return_value = "snippet"
            mock_tool.backend.platform = "win32"
            mock_tool.backend.tool_name = "powershell"
            result = clipboard_read()
        assert result["success"] is True
        assert result["content"] == "snippet"

    def test_clipboard_write_invocation(self) -> None:
        with patch("tools.clipboard_tool._default_tool") as mock_tool:
            mock_tool.write.return_value = True
            mock_tool.history.return_value = [ClipboardEntry("x", datetime.now())]
            result = clipboard_write("hello")
        assert result["success"] is True
        assert result["length"] == 5
        assert result["history_size"] == 1

    def test_clipboard_clear_invocation(self) -> None:
        with patch("tools.clipboard_tool._default_tool") as mock_tool:
            mock_tool.clear.return_value = True
            result = clipboard_clear()
        assert result["success"] is True

    def test_clipboard_history_invocation(self) -> None:
        with patch("tools.clipboard_tool._default_tool") as mock_tool:
            mock_tool.history.return_value = [ClipboardEntry("a", datetime.now())]
            result = clipboard_history()
        assert result["success"] is True
        assert result["count"] == 1
        assert result["entries"][0]["content"] == "a"

    def test_clipboard_add_invocation(self) -> None:
        with patch("tools.clipboard_tool._default_tool") as mock_tool:
            mock_tool.history.return_value = [ClipboardEntry("z", datetime.now())]
            result = clipboard_add("z")
        assert result["success"] is True
        assert result["history_size"] == 1
