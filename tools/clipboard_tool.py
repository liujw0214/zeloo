"""Clipboard tools with cross-platform fallbacks.

Reads and writes the system clipboard on Windows, macOS, and Linux. Each
write is automatically recorded to a JSON history file (default
``~/.Zeloo/clipboard_history.json``) so the user can recall recent
entries.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tools.base import tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default storage path
# ---------------------------------------------------------------------------


def _default_history_path() -> Path:
    """Return the default location of the clipboard history file."""
    base = Path.home() / ".Zeloo"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("Failed to create %s: %s", base, exc)
    return base / "clipboard_history.json"


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass
class ClipboardEntry:
    """A single clipboard history entry."""

    content: str
    timestamp: datetime
    content_type: str = "text"

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict."""
        return {
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "content_type": self.content_type,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> ClipboardEntry:
        """Rehydrate an entry from its JSON-serialisable form."""
        ts = payload.get("timestamp")
        try:
            timestamp = datetime.fromisoformat(ts) if ts else datetime.now()
        except ValueError:
            timestamp = datetime.now()
        return cls(
            content=payload.get("content", ""),
            timestamp=timestamp,
            content_type=payload.get("content_type", "text"),
        )


# ---------------------------------------------------------------------------
# Cross-platform backends
# ---------------------------------------------------------------------------


class _ClipboardBackend:
    """Thin wrapper around the available OS clipboard mechanism."""

    def __init__(self) -> None:
        self._platform = sys.platform
        self._tool = self._detect_tool()

    @property
    def platform(self) -> str:
        """Return the active platform identifier (``win32`` / ``darwin`` / ``linux``)."""
        return self._platform

    @property
    def tool_name(self) -> str:
        """Return the binary name of the active clipboard tool."""
        return self._tool or ""

    def _detect_tool(self) -> str | None:
        """Detect which clipboard binary is available on the current platform."""
        if self._platform.startswith("win"):
            # PowerShell is always present on Windows; nothing to look up.
            return "powershell"
        if self._platform == "darwin":
            return "pbcopy" if shutil.which("pbcopy") else None
        # Linux: prefer xclip, then xsel.
        if shutil.which("xclip"):
            return "xclip"
        if shutil.which("xsel"):
            return "xsel"
        return None

    def read(self) -> str:
        """Read the current clipboard text. Returns ``""`` on failure."""
        try:
            if self._platform.startswith("win"):
                return self._read_windows()
            if self._platform == "darwin":
                return self._read_macos()
            return self._read_linux()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Clipboard read failed: %s", exc)
            return ""

    def write(self, text: str) -> bool:
        """Write ``text`` to the clipboard. Returns True on success."""
        try:
            if self._platform.startswith("win"):
                return self._write_windows(text)
            if self._platform == "darwin":
                return self._write_macos(text)
            return self._write_linux(text)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Clipboard write failed: %s", exc)
            return False

    def clear(self) -> bool:
        """Empty the clipboard. Returns True on success."""
        return self.write("")

    # ---- Windows --------------------------------------------------------

    def _read_windows(self) -> str:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if proc.returncode != 0:
            return ""
        return proc.stdout.rstrip("\r\n")

    def _write_windows(self, text: str) -> bool:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value $input"],
            input=text, capture_output=True, text=True, timeout=10, check=False,
        )
        return proc.returncode == 0

    # ---- macOS ----------------------------------------------------------

    def _read_macos(self) -> str:
        proc = subprocess.run(
            ["pbpaste"], capture_output=True, text=True, timeout=10, check=False,
        )
        return proc.stdout if proc.returncode == 0 else ""

    def _write_macos(self, text: str) -> bool:
        proc = subprocess.run(
            ["pbcopy"], input=text, capture_output=True,
            text=True, timeout=10, check=False,
        )
        return proc.returncode == 0

    # ---- Linux ----------------------------------------------------------

    def _read_linux(self) -> str:
        if self._tool == "xclip":
            cmd = ["xclip", "-selection", "clipboard", "-o"]
        elif self._tool == "xsel":
            cmd = ["xsel", "--clipboard", "--output"]
        else:
            return ""
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10, check=False,
        )
        return proc.stdout if proc.returncode == 0 else ""

    def _write_linux(self, text: str) -> bool:
        if self._tool == "xclip":
            cmd = ["xclip", "-selection", "clipboard"]
        elif self._tool == "xsel":
            cmd = ["xsel", "--clipboard", "--input"]
        else:
            return False
        proc = subprocess.run(
            cmd, input=text, capture_output=True, text=True, timeout=10, check=False,
        )
        return proc.returncode == 0


# ---------------------------------------------------------------------------
# Main tool class
# ---------------------------------------------------------------------------


class ClipboardTool:
    """High-level clipboard API with persistent history.

    History is persisted as a JSON file with at most ``max_history`` entries
    (oldest entries are evicted when the limit is reached). All file
    operations are guarded by a lock so the tool is safe to share between
    threads within the same process.
    """

    def __init__(
        self, history_path: Path | None = None, max_history: int = 20,
    ) -> None:
        """Initialise the clipboard tool.

        Args:
            history_path: Location of the JSON history file. Defaults to
                ``~/.Zeloo/clipboard_history.json``.
            max_history: Maximum number of entries to retain in history.
        """
        self._history_path = history_path or _default_history_path()
        self._max_history = max(1, max_history)
        self._backend = _ClipboardBackend()
        self._lock = threading.Lock()
        self._entries: list[ClipboardEntry] = self._load_history()

    # ----------------------------------------------------------- backend

    @property
    def backend(self) -> _ClipboardBackend:
        """Return the active clipboard backend."""
        return self._backend

    @property
    def history_path(self) -> Path:
        """Return the path of the history file."""
        return self._history_path

    # -------------------------------------------------------- read/write

    def read(self) -> str:
        """Return the current clipboard contents."""
        return self._backend.read()

    def write(self, text: str) -> bool:
        """Write ``text`` to the clipboard and record it in history."""
        ok = self._backend.write(text)
        if ok:
            self.add_to_history(text)
        return ok

    def clear(self) -> bool:
        """Empty the clipboard. Does not affect the on-disk history."""
        return self._backend.clear()

    # ----------------------------------------------------------- history

    def history(self) -> list[ClipboardEntry]:
        """Return a copy of the history list (most recent last)."""
        with self._lock:
            return list(self._entries)

    def add_to_history(self, content: str) -> None:
        """Append ``content`` to the in-memory and on-disk history."""
        if content is None:
            return
        entry = ClipboardEntry(content=content, timestamp=datetime.now())
        with self._lock:
            # De-duplicate consecutive duplicates to avoid history spam.
            if self._entries and self._entries[-1].content == content:
                self._entries[-1] = entry
            else:
                self._entries.append(entry)
                if len(self._entries) > self._max_history:
                    self._entries = self._entries[-self._max_history:]
            self._save_history_locked()

    def get_entry(self, index: int) -> ClipboardEntry | None:
        """Return the entry at ``index`` (0 = oldest) or ``None`` if missing."""
        with self._lock:
            if index < 0 or index >= len(self._entries):
                return None
            return self._entries[index]

    def delete_entry(self, index: int) -> bool:
        """Delete the entry at ``index``. Returns True if removed."""
        with self._lock:
            if index < 0 or index >= len(self._entries):
                return False
            del self._entries[index]
            self._save_history_locked()
            return True

    def clear_history(self) -> None:
        """Erase all stored history entries from memory and disk."""
        with self._lock:
            self._entries.clear()
            self._save_history_locked()

    # -------------------------------------------------------- persistence

    def _load_history(self) -> list[ClipboardEntry]:
        """Load history from disk; return ``[]`` if the file is missing/corrupt."""
        if not self._history_path.exists():
            return []
        try:
            raw = json.loads(self._history_path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                return []
            return [ClipboardEntry.from_dict(item) for item in raw if isinstance(item, dict)]
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load clipboard history: %s", exc)
            return []

    def _save_history_locked(self) -> None:
        """Persist the current history list to disk (caller holds the lock)."""
        try:
            payload = [entry.to_dict() for entry in self._entries]
            self._history_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._history_path.with_suffix(self._history_path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._history_path)
        except OSError as exc:
            logger.warning("Failed to save clipboard history: %s", exc)


# ---------------------------------------------------------------------------
# @tool-decorated wrappers
# ---------------------------------------------------------------------------


_default_tool = ClipboardTool()


@tool(
    name="clipboard_read",
    description="Read the current clipboard contents",
    dangerous=False, toolset="clipboard",
)
def clipboard_read() -> dict:
    """Return the current clipboard contents.

    Returns:
        A dict with ``success``, ``content``, ``platform``, and ``tool``.
    """
    content = _default_tool.read()
    return {
        "success": True,
        "content": content,
        "platform": _default_tool.backend.platform,
        "tool": _default_tool.backend.tool_name,
    }


@tool(
    name="clipboard_write",
    description="Write text to the clipboard",
    dangerous=True, toolset="clipboard",
)
def clipboard_write(text: str) -> dict:
    """Overwrite the clipboard with ``text``.

    Args:
        text: The text to place on the clipboard.
    """
    ok = _default_tool.write(text)
    return {
        "success": ok,
        "length": len(text) if isinstance(text, str) else 0,
        "history_size": len(_default_tool.history()),
    }


@tool(
    name="clipboard_clear",
    description="Empty the system clipboard",
    dangerous=True, toolset="clipboard",
)
def clipboard_clear() -> dict:
    """Clear the clipboard contents."""
    ok = _default_tool.clear()
    return {"success": ok}


@tool(
    name="clipboard_history",
    description="View recent clipboard history",
    dangerous=False, toolset="clipboard",
)
def clipboard_history() -> dict:
    """Return the persistent clipboard history.

    Returns:
        A dict with ``success`` and ``entries`` (each entry has content,
        timestamp, content_type).
    """
    entries = [entry.to_dict() for entry in _default_tool.history()]
    return {"success": True, "entries": entries, "count": len(entries)}


@tool(
    name="clipboard_add",
    description="Manually add a snippet to clipboard history without writing to the OS clipboard",
    dangerous=False, toolset="clipboard",
)
def clipboard_add(content: str) -> dict:
    """Record ``content`` in clipboard history.

    Args:
        content: The text snippet to remember.
    """
    _default_tool.add_to_history(content)
    return {
        "success": True,
        "history_size": len(_default_tool.history()),
    }