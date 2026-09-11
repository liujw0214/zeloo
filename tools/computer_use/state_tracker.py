"""Action history tracker — record past computer-use actions for replay.

Useful for debugging and for the agent to review its own actions.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ActionRecord:
    """A single computer-use action."""

    timestamp: float
    action: str
    target: str = ""
    params: dict = field(default_factory=dict)
    success: bool = True
    error: str = ""


class StateTracker:
    """Thread-safe in-memory history of computer-use actions."""

    def __init__(self, max_records: int = 1000) -> None:
        self._max = max_records
        self._lock = threading.Lock()
        self._records: list[ActionRecord] = []

    def record(
        self,
        action: str,
        target: str = "",
        params: dict | None = None,
        success: bool = True,
        error: str = "",
    ) -> None:
        """Append an action to the history (FIFO eviction when over capacity)."""
        rec = ActionRecord(
            timestamp=time.time(),
            action=action,
            target=target,
            params=params or {},
            success=success,
            error=error,
        )
        with self._lock:
            self._records.append(rec)
            if len(self._records) > self._max:
                self._records = self._records[-self._max :]

    def recent(self, limit: int = 20) -> list[ActionRecord]:
        """Return the most recent *limit* actions (newest last)."""
        with self._lock:
            return list(self._records[-limit:])

    def clear(self) -> int:
        """Clear all records and return how many were removed."""
        with self._lock:
            count = len(self._records)
            self._records.clear()
            return count

    def stats(self) -> dict:
        """Return aggregate stats: total, success_rate, by_action counts."""
        with self._lock:
            total = len(self._records)
            success = sum(1 for r in self._records if r.success)
            by_action: dict[str, int] = {}
            for r in self._records:
                by_action[r.action] = by_action.get(r.action, 0) + 1
            return {
                "total": total,
                "successful": success,
                "failed": total - success,
                "success_rate": round(success / total, 3) if total else 0.0,
                "by_action": by_action,
            }

    def to_dicts(self, limit: int = 50) -> list[dict]:
        """Return recent actions as plain dicts (for JSON serialization)."""
        return [asdict(r) for r in self.recent(limit)]


_tracker = StateTracker()


def get_tracker() -> StateTracker:
    """Return the process-wide singleton tracker."""
    return _tracker