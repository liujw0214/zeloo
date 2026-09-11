"""Flush session-end facts to MEMORY.md.

When the runtime calls ``plugins.hooks.HookType.ON_SESSION_END`` (see
``run_agent.shutdown``), we want user-level facts learned during the
session — preferences, environment hints, recurring complaints — to
land in the persistent ``MEMORY.md`` file. Without a built-in handler
the hook fires into the void, so this module wires up the missing
subscriber.

Public surface:

* :class:`SessionMemoryFlusher` — accumulates facts in memory and
  writes them out (with archival rotation) on demand.
* :func:`install_session_flush_hook` — registers the flusher as a
  callback on ``ON_SESSION_END`` against the global hook registry.

The flusher is safe to call repeatedly: empty buffers are no-ops,
write errors are logged but never raised, and the archive rotation
only triggers when the file grows beyond ``2 × max_chars``.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class SessionMemoryFlusher:
    """Persist session-end facts (user prefs, learned facts) to MEMORY.md."""

    def __init__(self, mem_path: Path, max_chars: int = 8000) -> None:
        self.mem_path = mem_path
        self.max_chars = max_chars
        self._pending: list[str] = []

    def add_fact(self, content: str, tags: list[str] | None = None) -> None:
        """Record a fact to be flushed at session-end.

        ``content`` is the human-readable fact; ``tags`` are appended
        as ``#tag`` suffixes for downstream filtering.
        """
        ts = datetime.now().strftime("%Y-%m-%d")
        line = f"- [{ts}] {content}"
        if tags:
            line += " " + " ".join(f"#{t}" for t in tags)
        self._pending.append(line)

    def flush(self) -> int:
        """Write all pending facts to MEMORY.md. Returns count written."""
        if not self._pending:
            return 0
        try:
            self.mem_path.parent.mkdir(parents=True, exist_ok=True)
            with self.mem_path.open("a", encoding="utf-8") as fh:
                for line in self._pending:
                    fh.write(line + "\n")
            written = len(self._pending)
            self._pending.clear()
            self._maybe_archive()
            return written
        except Exception as exc:
            logger.warning("Memory flush failed: %s", exc)
            return 0

    def _maybe_archive(self) -> None:
        if not self.mem_path.exists():
            return
        try:
            size = self.mem_path.stat().st_size
        except OSError:
            return
        if size > self.max_chars * 2:
            archive_dir = self.mem_path.parent / "archive"
            try:
                archive_dir.mkdir(exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                archive_path = archive_dir / f"{ts}-{self.mem_path.name}"
                self.mem_path.rename(archive_path)
                # Restore a fresh MEMORY.md
                self.mem_path.write_text(
                    "# Persistent memory (archived)\n\n", encoding="utf-8"
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Memory archive rotation failed: %s", exc)


def _default_mem_path() -> Path:
    """Resolve the default MEMORY.md path under the active Zeloo home."""
    val = os.environ.get("ZELOO_HOME", "").strip()
    if val:
        home = Path(val).expanduser()
    elif os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", "").strip()
        if local:
            home = Path(local) / "Zeloo"
        else:
            home = Path.home() / "AppData" / "Local" / "Zeloo"
    else:
        home = Path.home() / ".Zeloo"
    return home / "workspace" / "default" / "memory" / "MEMORY.md"


def install_session_flush_hook(
    mem_path: Path | None = None,
    *,
    plugin_name: str = "zeloo.session_flush",
) -> SessionMemoryFlusher:
    """Wire :class:`SessionMemoryFlusher` into the ``ON_SESSION_END`` hook.

    Returns the registered flusher so callers can call
    :meth:`SessionMemoryFlusher.add_fact` during the session. The hook
    pulls any facts stashed under ``metadata['facts']`` (a list of
    strings or ``(content, tags)`` tuples) before flushing.
    """
    from plugins.hooks import HookType, get_hook_registry

    flusher = SessionMemoryFlusher(mem_path=mem_path or _default_mem_path())
    registry = get_hook_registry()

    def _on_session_end(session_id: str, *args: object, **kwargs: object) -> None:
        # ``run_agent.shutdown`` fires the hook as
        # ``fire(HookType.ON_SESSION_END, session_id, duration=...)`` —
        # we accept both positional and keyword metadata.
        metadata: dict[str, object] = {}
        for arg in args:
            if isinstance(arg, dict):
                metadata.update(arg)
        for key, value in kwargs.items():
            metadata.setdefault(key, value)

        for fact in metadata.get("facts", []) or []:
            if isinstance(fact, tuple) and len(fact) == 2:
                content, tags = fact
                flusher.add_fact(str(content), list(tags) if tags else None)
            else:
                flusher.add_fact(str(fact))

        count = flusher.flush()
        logger.debug("Flushed %d facts at session end", count)

    registry.register(
        HookType.ON_SESSION_END,
        _on_session_end,
        plugin_name=plugin_name,
    )
    return flusher


__all__ = ["SessionMemoryFlusher", "install_session_flush_hook"]