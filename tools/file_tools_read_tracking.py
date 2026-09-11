"""Track which files have been read for context management."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class FileReadRecord:
    """Record of a file read operation."""
    path: Path
    lines: int
    size: int
    timestamp: float = field(default_factory=time.time)
    hash_value: str = ""


class ReadTracker:
    """Track file reads for context window management.

    Uses an LRU (Least Recently Used) cache to manage tracked files,
    allowing eviction of oldest entries when the limit is reached.
    """

    def __init__(self, max_tracked: int = 200) -> None:
        """Initialize the read tracker.

        Args:
            max_tracked: Maximum number of files to track.
        """
        self._max_tracked = max_tracked
        self._lock = threading.RLock()
        self._records: OrderedDict[Path, FileReadRecord] = OrderedDict()
        self._total_lines = 0
        self._total_size = 0

    def record(self, path: Path, lines: int, size: int) -> None:
        """Record a file read operation.

        Args:
            path: Path to the file that was read.
            lines: Number of lines read.
            size: Size of the file in bytes.
        """
        with self._lock:
            normalized = path.resolve()
            if normalized in self._records:
                old_record = self._records[normalized]
                self._total_lines -= old_record.lines
                self._total_size -= old_record.size
            else:
                while len(self._records) >= self._max_tracked:
                    oldest = next(iter(self._records))
                    old_record = self._records.pop(oldest)
                    self._total_lines -= old_record.lines
                    self._total_size -= old_record.size

            record = FileReadRecord(
                path=normalized,
                lines=lines,
                size=size,
                timestamp=time.time(),
            )
            self._records[normalized] = record
            self._total_lines += lines
            self._total_size += size
            self._records.move_to_end(normalized)

    def get_tracked(self) -> list[dict[str, Any]]:
        """Get list of all tracked file records.

        Returns:
            List of dictionaries containing file read information.
        """
        with self._lock:
            return [
                {
                    "path": str(r.path),
                    "lines": r.lines,
                    "size": r.size,
                    "timestamp": r.timestamp,
                }
                for r in self._records.values()
            ]

    def get_lru_order(self) -> list[Path]:
        """Get tracked files in LRU order (oldest first).

        Returns:
            List of paths ordered from least recently used to most.
        """
        with self._lock:
            return list(self._records.keys())

    def get_mru_order(self) -> list[Path]:
        """Get tracked files in MRU order (newest first).

        Returns:
            List of paths ordered from most recently used to least.
        """
        with self._lock:
            return list(reversed(list(self._records.keys())))

    def evict_oldest(self, count: int = 1) -> list[Path]:
        """Evict the oldest tracked files.

        Args:
            count: Number of files to evict.

        Returns:
            List of paths that were evicted.
        """
        evicted: list[Path] = []
        with self._lock:
            for _ in range(min(count, len(self._records))):
                if self._records:
                    oldest = next(iter(self._records))
                    record = self._records.pop(oldest)
                    self._total_lines -= record.lines
                    self._total_size -= record.size
                    evicted.append(oldest)
        return evicted

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about tracked files.

        Returns:
            Dictionary with tracking statistics.
        """
        with self._lock:
            return {
                "tracked_count": len(self._records),
                "max_tracked": self._max_tracked,
                "total_lines": self._total_lines,
                "total_size": self._total_size,
                "total_size_mb": round(self._total_size / (1024 * 1024), 2),
            }

    def is_tracked(self, path: Path) -> bool:
        """Check if a path is currently tracked.

        Args:
            path: Path to check.

        Returns:
            True if the path is tracked, False otherwise.
        """
        with self._lock:
            return path.resolve() in self._records

    def get_record(self, path: Path) -> dict[str, Any] | None:
        """Get record for a specific path.

        Args:
            path: Path to look up.

        Returns:
            Record dictionary or None if not tracked.
        """
        with self._lock:
            normalized = path.resolve()
            if normalized not in self._records:
                return None
            r = self._records[normalized]
            return {
                "path": str(r.path),
                "lines": r.lines,
                "size": r.size,
                "timestamp": r.timestamp,
            }

    def clear(self) -> None:
        """Clear all tracked file records."""
        with self._lock:
            self._records.clear()
            self._total_lines = 0
            self._total_size = 0
