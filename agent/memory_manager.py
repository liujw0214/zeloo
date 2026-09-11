"""Persistent memory management — MEMORY.md and USER.md."""

from __future__ import annotations

import logging
from pathlib import Path

from agent.zeloo_constants import get_memories_dir

logger = logging.getLogger(__name__)

DEFAULT_MAX_CHARS = 8000


class MemoryManager:
    """Manages MEMORY.md and USER.md files."""

    def __init__(self, home: Path | None = None, max_chars: int = DEFAULT_MAX_CHARS) -> None:
        self.memories_dir = home / "memories" if home else get_memories_dir()
        self.memories_dir.mkdir(parents=True, exist_ok=True)
        self.max_chars = max_chars
        self._cache: dict[str, str] = {}

    def _path(self, kind: str) -> Path:
        name = "MEMORY.md" if kind == "memory" else "USER.md"
        return self.memories_dir / name

    def read(self, kind: str) -> str:
        """Read memory content from disk."""
        path = self._path(kind)
        if not path.is_file():
            return ""
        try:
            content = path.read_text(encoding="utf-8")
            self._cache[kind] = content
            return content
        except Exception:
            logger.exception("Failed to read %s", path)
            return ""

    def write(self, kind: str, content: str) -> None:
        """Overwrite memory content."""
        if len(content) > self.max_chars:
            content = content[: self.max_chars]
        path = self._path(kind)
        path.write_text(content, encoding="utf-8")
        self._cache[kind] = content

    def append(self, kind: str, content: str) -> None:
        """Append to memory content."""
        existing = self.read(kind)
        if existing:
            new_content = existing.rstrip() + "\n\n" + content
        else:
            new_content = content
        self.write(kind, new_content)

    def load_from_disk(self) -> None:
        """Reload all memory from disk (called after context compression)."""
        for kind in ("memory", "user"):
            self._cache[kind] = self.read(kind)

    def format_for_system_prompt(self, kind: str) -> str:
        """Format memory for injection into the system prompt."""
        content = self._cache.get(kind)
        if content is None:
            content = self.read(kind)
        if not content.strip():
            return ""
        label = "MEMORY" if kind == "memory" else "USER PROFILE"
        return f"## {label}\n{content}"


MemoryStore = MemoryManager
