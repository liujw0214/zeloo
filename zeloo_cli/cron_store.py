"""Cron store — Hermes Agent parity (Round 66).

Hermes Agent ships a ``hermes cron`` command for managing scheduled
tasks. Zeloo adopts the same interface (``add`` / ``remove`` / ``list``)
but stores tasks in a JSON file under ``~/.Zeloo/cron.json`` so the
operator can read/edit them directly without a database.

The store is intentionally tiny — only 4 public methods. A real
scheduler would also need a daemon process to actually execute tasks;
that's intentionally out of scope for this round.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any


class InMemoryCronStore:
    """Volatile cron store (used as fallback / for tests)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, dict[str, str]] = {}

    def list_tasks(self) -> list[dict[str, str]]:
        with self._lock:
            return [dict(t) for t in self._tasks.values()]

    def add_task(self, name: str, schedule: str, command: str) -> None:
        with self._lock:
            self._tasks[name] = {
                "name": name, "schedule": schedule, "command": command,
            }

    def remove_task(self, name: str) -> None:
        with self._lock:
            self._tasks.pop(name, None)


class CronStore(InMemoryCronStore):
    """Persistent cron store backed by ``~/.Zeloo/cron.json``.

    Reads on construction so a list is always current; writes flush
    synchronously to disk so crashes don't lose scheduled tasks.
    """

    def __init__(self, path: Path | None = None) -> None:
        super().__init__()
        self._path = path or Path(
            os.path.expanduser(os.environ.get("zeloo_HOME", "~/.Zeloo"))
        ) / "cron.json"
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data: Any = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                with self._lock:
                    for t in data:
                        if isinstance(t, dict) and "name" in t:
                            self._tasks[t["name"]] = {
                                "name": t["name"],
                                "schedule": t.get("schedule", "* * * * *"),
                                "command": t.get("command", ""),
                                "enabled": t.get("enabled", True),
                            }
        except (OSError, json.JSONDecodeError):
            pass

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            payload = json.dumps(
                list(self._tasks.values()), indent=2, sort_keys=False,
            )
        self._path.write_text(payload, encoding="utf-8")

    def add_task(self, name: str, schedule: str, command: str) -> None:
        super().add_task(name, schedule, command)
        self._flush()

    def remove_task(self, name: str) -> None:
        super().remove_task(name)
        self._flush()


__all__ = ["CronStore", "InMemoryCronStore"]
