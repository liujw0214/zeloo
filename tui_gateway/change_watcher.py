"""File-change watcher for TUI gateway hot-reload of config and skills."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class WatchEvent:
    path: Path
    kind: str  # created / modified / deleted
    timestamp: float = field(default_factory=time.time)


class ChangeWatcher:
    """Lightweight polling-based watcher.

    Uses mtime + size comparison rather than watchdog/fs events so it has
    no native deps and works the same on Linux/macOS/Windows.
    """

    def __init__(self, root: Path, interval: float = 1.0) -> None:
        self._root = Path(root)
        self._interval = interval
        self._snapshots: dict[Path, tuple[float, int]] = {}
        self._callbacks: list[Callable[[WatchEvent], None]] = []

    def on_change(self, callback: Callable[[WatchEvent], None]) -> Callable[[], None]:
        self._callbacks.append(callback)

        def _remove() -> None:
            try:
                self._callbacks.remove(callback)
            except ValueError:
                pass

        return _remove

    def _scan_once(self) -> list[WatchEvent]:
        events: list[WatchEvent] = []
        if not self._root.exists():
            return events

        current: dict[Path, tuple[float, int]] = {}
        for path in self._root.rglob("*"):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            current[path] = (stat.st_mtime, stat.st_size)

        for path, sig in current.items():
            prev = self._snapshots.get(path)
            if prev is None:
                events.append(WatchEvent(path, "created"))
            elif prev != sig:
                events.append(WatchEvent(path, "modified"))

        for path in self._snapshots:
            if path not in current:
                events.append(WatchEvent(path, "deleted"))

        self._snapshots = current
        return events

    def poll(self) -> list[WatchEvent]:
        events = self._scan_once()
        for ev in events:
            for cb in self._callbacks:
                try:
                    cb(ev)
                except Exception:
                    logger.exception("Change watcher callback raised")
        return events

    def watch_forever(self) -> None:
        while True:
            self.poll()
            time.sleep(self._interval)
