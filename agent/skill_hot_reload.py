"""Skill hot-reload — detect filesystem changes to SKILL.md and notify subscribers.

This module provides a lightweight polling-based watcher for the skills
directory tree. It exposes a ``SkillHotReloader`` that:

  * Tracks ``(path, mtime_ns, size)`` fingerprints for every SKILL.md under
    one or more watched roots.
  * On every ``poll()`` invocation (cheap; no third-party deps), emits
    ``SkillChangeEvent`` objects describing what changed (``added``,
    ``modified``, ``removed``) since the last poll.
  * Lets callers register zero or more callback subscribers — used by the
    runtime to invalidate caches, re-register tool descriptions, or push
    updates into the prompt builder.

Design notes:

  * Polling is used instead of OS file events because:

      - Skills live in user home directories (``~/.Zeloo/skills``) which
        may live on different filesystems / network mounts where
        ``inotify`` / ``FSEvents`` are unreliable.
      - Skills may also be added inside the project bundle (read-only on
        some platforms).
      - The poll interval is short (~500 ms by default) and the fingerprint
        comparison is O(N) over a small set, so the cost is negligible.

  * The module is **dependency-free** and degrades gracefully: if
    ``watchdog`` is installed the same API still works and a future
    optimization can use it transparently.

  * Thread-safe — the snapshot dictionary is protected by an ``RLock``.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

logger = logging.getLogger(__name__)


class SkillChangeKind(StrEnum):
    """Type of filesystem change detected for a skill."""

    ADDED = "added"
    MODIFIED = "modified"
    REMOVED = "removed"


@dataclass(frozen=True)
class SkillChangeEvent:
    """A single change detected for one skill file.

    Attributes:
        kind: What happened (``added`` / ``modified`` / ``removed``).
        path: Absolute path to the SKILL.md file (or the path that *was*
            the SKILL.md, for ``removed`` events).
        skill_name: Directory name (the conventional skill identifier).
        previous_mtime: Previous mtime in nanoseconds (``None`` for ``added``).
        current_mtime: Current mtime in nanoseconds (``None`` for ``removed``).
    """

    kind: SkillChangeKind
    path: Path
    skill_name: str
    previous_mtime: int | None = None
    current_mtime: int | None = None


@dataclass
class _Fingerprint:
    """Internal fingerprint for one SKILL.md file."""

    mtime_ns: int
    size: int
    skill_name: str

    @classmethod
    def from_path(cls, path: Path) -> _Fingerprint | None:
        try:
            st = path.stat()
        except (FileNotFoundError, OSError):
            return None
        return cls(
            mtime_ns=st.st_mtime_ns,
            size=st.st_size,
            skill_name=path.parent.name,
        )


ChangeCallback = Callable[[SkillChangeEvent], None]


class SkillHotReloader:
    """Polling-based watcher for SKILL.md files.

    Example::

        reloader = SkillHotReloader()
        reloader.add_root(Path.home() / ".Zeloo" / "skills")
        reloader.subscribe(lambda evt: print(evt))

        # In a background thread:
        while True:
            reloader.poll()
            time.sleep(0.5)
    """

    def __init__(
        self,
        roots: Iterable[Path] | None = None,
        poll_interval_s: float = 0.5,
        skill_filename: str = "SKILL.md",
    ) -> None:
        self._roots: list[Path] = []
        self._poll_interval = float(poll_interval_s)
        self._skill_filename = skill_filename
        self._fingerprints: dict[Path, _Fingerprint] = {}
        self._subscribers: list[ChangeCallback] = []
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        if roots:
            for r in roots:
                self.add_root(r)

    # ── Configuration ────────────────────────────────────────────

    def add_root(self, root: Path) -> None:
        """Add *root* to the watch list. Creates no I/O until ``poll()``."""
        root = Path(root).resolve()
        with self._lock:
            if root not in self._roots:
                self._roots.append(root)

    def roots(self) -> list[Path]:
        """Return a copy of the currently-watched roots."""
        with self._lock:
            return list(self._roots)

    def subscribe(self, callback: ChangeCallback) -> None:
        """Register *callback* to receive change events.

        Exceptions raised by callbacks are logged but do not stop delivery
        to other subscribers.
        """
        if not callable(callback):
            raise TypeError("callback must be callable")
        with self._lock:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: ChangeCallback) -> bool:
        """Remove *callback*; returns True if it was registered."""
        with self._lock:
            try:
                self._subscribers.remove(callback)
                return True
            except ValueError:
                return False

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    # ── Polling ──────────────────────────────────────────────────

    def poll(self) -> list[SkillChangeEvent]:
        """Scan watched roots and return events since the last poll.

        Calling this twice in a row with no filesystem change returns
        an empty list. New roots added between polls are picked up
        automatically.
        """
        events: list[SkillChangeEvent] = []

        with self._lock:
            current: dict[Path, _Fingerprint] = {}

            for root in self._roots:
                if not root.is_dir():
                    continue
                try:
                    for skill_md in root.rglob(self._skill_filename):
                        fp = _Fingerprint.from_path(skill_md)
                        if fp is None:
                            continue
                        current[skill_md] = fp
                except OSError as exc:
                    logger.warning("skill_hot_reload: scan failed for %s: %s", root, exc)

            # Detect adds and modifications
            for path, fp in current.items():
                prev = self._fingerprints.get(path)
                if prev is None:
                    events.append(
                        SkillChangeEvent(
                            kind=SkillChangeKind.ADDED,
                            path=path,
                            skill_name=fp.skill_name,
                            previous_mtime=None,
                            current_mtime=fp.mtime_ns,
                        )
                    )
                elif prev.mtime_ns != fp.mtime_ns or prev.size != fp.size:
                    events.append(
                        SkillChangeEvent(
                            kind=SkillChangeKind.MODIFIED,
                            path=path,
                            skill_name=fp.skill_name,
                            previous_mtime=prev.mtime_ns,
                            current_mtime=fp.mtime_ns,
                        )
                    )

            # Detect removals
            for path, prev in self._fingerprints.items():
                if path not in current:
                    events.append(
                        SkillChangeEvent(
                            kind=SkillChangeKind.REMOVED,
                            path=path,
                            skill_name=prev.skill_name,
                            previous_mtime=prev.mtime_ns,
                            current_mtime=None,
                        )
                    )

            self._fingerprints = current

            subscribers = list(self._subscribers)

        # Deliver outside the lock to prevent deadlocks if callbacks
        # call back into the reloader (e.g. subscribe during delivery).
        for evt in events:
            for cb in subscribers:
                try:
                    cb(evt)
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "skill_hot_reload: subscriber raised for %s: %s", evt, exc
                    )

        return events

    # ── Background loop ──────────────────────────────────────────

    def start(self) -> None:
        """Start a daemon thread that polls every ``poll_interval_s``.

        Safe to call multiple times — a second call is a no-op while the
        thread is alive.
        """
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="SkillHotReloader",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float | None = 2.0) -> None:
        """Signal the background thread to stop and wait briefly for it."""
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.poll()
            except Exception as exc:  # noqa: BLE001
                logger.exception("skill_hot_reload: poll() crashed: %s", exc)
            # Wait, but wake up promptly on stop().
            self._stop_event.wait(self._poll_interval)

    # ── Introspection ────────────────────────────────────────────

    def snapshot(self) -> dict[Path, tuple[int, int]]:
        """Return a snapshot of known fingerprints (for tests / debugging).

        Keys are absolute paths; values are ``(mtime_ns, size)``.
        """
        with self._lock:
            return {p: (fp.mtime_ns, fp.size) for p, fp in self._fingerprints.items()}

    def tracked_count(self) -> int:
        with self._lock:
            return len(self._fingerprints)


# ── Module-level singleton (process-wide convenience) ─────────────

_default_reloader: SkillHotReloader | None = None
_default_lock = threading.Lock()


def get_default_reloader() -> SkillHotReloader:
    """Return the process-wide :class:`SkillHotReloader` (lazy-created)."""
    global _default_reloader
    with _default_lock:
        if _default_reloader is None:
            roots: list[Path] = []
            try:
                from agent.zeloo_constants import get_skills_dir

                roots.append(get_skills_dir())
            except Exception:  # noqa: BLE001
                pass
            bundled = Path(__file__).resolve().parent.parent / "skills"
            if bundled.is_dir():
                roots.append(bundled)
            _default_reloader = SkillHotReloader(roots=roots)
        return _default_reloader


def reset_default_reloader() -> None:
    """Stop and clear the module-level singleton (used in tests)."""
    global _default_reloader
    with _default_lock:
        if _default_reloader is not None:
            _default_reloader.stop()
        _default_reloader = None


__all__ = [
    "SkillChangeEvent",
    "SkillChangeKind",
    "SkillHotReloader",
    "get_default_reloader",
    "reset_default_reloader",
]
