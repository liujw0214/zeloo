"""Data loaders for trajectory and training-set access.

Provides async-friendly loaders for compressed and raw trajectory files.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Trajectory:
    session_id: str
    turn_id: int
    user_message: str
    tool_calls: list[dict[str, Any]]
    assistant_response: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Trajectory:
        return cls(
            session_id=d.get("session_id", ""),
            turn_id=int(d.get("turn_id", 0)),
            user_message=d.get("user_message", ""),
            tool_calls=list(d.get("tool_calls", [])),
            assistant_response=d.get("assistant_response", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "user_message": self.user_message,
            "tool_calls": self.tool_calls,
            "assistant_response": self.assistant_response,
        }


class TrajectoryLoader:
    """Loads trajectory records from a directory of .jsonl files."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def files(self) -> list[Path]:
        if not self.root.exists():
            return []
        return sorted(self.root.rglob("*.jsonl"))

    def iter_records(self, max_records: int | None = None) -> Iterator[Trajectory]:
        count = 0
        for path in self.files():
            try:
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            logger.warning("Skipping invalid JSONL line in %s", path)
                            continue
                        yield Trajectory.from_dict(obj)
                        count += 1
                        if max_records is not None and count >= max_records:
                            return
            except OSError:
                logger.warning("Could not read %s", path)

    def count(self) -> int:
        total = 0
        for path in self.files():
            try:
                with open(path, encoding="utf-8") as f:
                    total += sum(1 for line in f if line.strip())
            except OSError:
                continue
        return total
