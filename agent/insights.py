"""insights — runtime insights and recommendations system.

This module
collects runtime observations and generates actionable insights
for the user, such as:
- Cost anomalies (spike in token usage)
- Performance degradation (slow tool calls)
- Skill usage patterns (which skills are most/least used)
- Error trends (recurring error categories)
- Session quality (completion rates, iteration counts)

Usage::

    from agent.insights import insights_engine

    insights_engine.record_token_usage(50000)
    insights_engine.record_tool_call("file_read", duration=0.05)
    insights_engine.record_error("rate_limit")
    report = insights_engine.generate_report()
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Cap the in-memory token-usage ring to keep the process footprint bounded.
# The on-disk payload mirrors the same cap (see ``_save``).
_TOKEN_RING_CAP = 1000
# Persist at most once every ``_FLUSH_INTERVAL_S`` seconds to avoid one
# disk write per record on hot paths (every tool call → every error → every
# token delta). The most recent unsaved delta can still be lost on a crash.
_FLUSH_INTERVAL_S = 2.0


@dataclass
class ToolStat:
    """Statistics for a single tool."""

    call_count: int = 0
    total_duration: float = 0.0
    error_count: int = 0

    @property
    def avg_duration(self) -> float:
        if self.call_count == 0:
            return 0.0
        return self.total_duration / self.call_count


class InsightsEngine:
    """Collects runtime metrics and generates insights reports.

    Metrics are kept in memory and optionally persisted to disk for
    cross-session analysis.
    """

    def __init__(self, storage_path: str | Path | None = None) -> None:
        self._storage_path = (
            Path(storage_path).expanduser()
            if storage_path
            else Path("~/.Zeloo/insights.json").expanduser()
        )
        self._tool_stats: dict[str, ToolStat] = defaultdict(ToolStat)
        self._error_counts: dict[str, int] = defaultdict(int)
        self._token_usage: list[tuple[float, int]] = []  # (timestamp, delta)
        self._session_count: int = 0
        self._total_iterations: int = 0
        # Disk-write throttling: avoid one JSON rewrite per recorded event.
        self._dirty = False
        self._last_flush = 0.0
        self._lock = threading.Lock()
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _load(self) -> None:
        """Load insights from disk."""
        if not self._storage_path.exists():
            return
        try:
            data = json.loads(self._storage_path.read_text(encoding="utf-8"))
            self._session_count = data.get("session_count", 0)
            self._total_iterations = data.get("total_iterations", 0)
            for name, stat in data.get("tool_stats", {}).items():
                self._tool_stats[name] = ToolStat(
                    call_count=stat.get("call_count", 0),
                    total_duration=stat.get("total_duration", 0.0),
                    error_count=stat.get("error_count", 0),
                )
            self._error_counts.update(data.get("error_counts", {}))
            self._token_usage = [
                (ts, tok) for ts, tok in data.get("token_usage", [])
            ]
        except Exception:
            logger.exception("Failed to load insights")

    def _save(self) -> None:
        """Persist insights to disk."""
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "session_count": self._session_count,
                "total_iterations": self._total_iterations,
                "tool_stats": {
                    name: {
                        "call_count": s.call_count,
                        "total_duration": s.total_duration,
                        "error_count": s.error_count,
                    }
                    for name, s in self._tool_stats.items()
                },
                "error_counts": dict(self._error_counts),
                "token_usage": self._token_usage[-_TOKEN_RING_CAP:],
            }
            self._storage_path.write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
        except Exception:
            logger.exception("Failed to save insights")

    def _schedule_flush(self) -> None:
        """Mark state dirty and flush if enough time has elapsed.

        Replaces the previous pattern of writing JSON on every single event,
        which made a high-volume tool-call loop hot-path expensive.
        """
        self._dirty = True
        now = time.time()
        if now - self._last_flush >= _FLUSH_INTERVAL_S:
            self._flush()

    def _flush(self) -> None:
        """Force-write current state to disk."""
        with self._lock:
            if not self._dirty:
                return
            self._dirty = False
            self._last_flush = time.time()
            self._save()

    # ------------------------------------------------------------------
    # Metric recording
    # ------------------------------------------------------------------
    def record_tool_call(self, tool_name: str, duration: float, error: bool = False) -> None:
        """Record a tool call with its duration and error status."""
        with self._lock:
            stat = self._tool_stats[tool_name]
            stat.call_count += 1
            stat.total_duration += duration
            if error:
                stat.error_count += 1
        self._schedule_flush()

    def record_error(self, error_category: str) -> None:
        """Record an error occurrence by category."""
        with self._lock:
            self._error_counts[error_category] += 1
        self._schedule_flush()

    def record_token_usage(self, tokens: int) -> None:
        """Record a token-usage delta for the current session.

        ``tokens`` is the number of tokens consumed *since the last call*,
        not a cumulative total. The internal ring buffer is capped so a
        multi-hour session cannot grow unbounded.
        """
        with self._lock:
            self._token_usage.append((time.time(), tokens))
            # Drop oldest entries when the in-memory ring exceeds the cap.
            if len(self._token_usage) > _TOKEN_RING_CAP:
                del self._token_usage[: len(self._token_usage) - _TOKEN_RING_CAP]
        self._schedule_flush()

    def record_session(self, iterations: int = 0) -> None:
        """Record a completed session."""
        with self._lock:
            self._session_count += 1
            self._total_iterations += iterations
        self._schedule_flush()

    # ------------------------------------------------------------------
    # Insight generation
    # ------------------------------------------------------------------
    def generate_report(self) -> dict[str, Any]:
        """Generate an insights report with recommendations.

        Returns a dict with sections: summary, tool_usage, errors,
        cost, and recommendations.
        """
        with self._lock:
            now = time.time()
            one_hour_ago = now - 3600

            # Token usage in last hour
            recent_tokens = sum(
                tok for ts, tok in self._token_usage if ts >= one_hour_ago
            )

            # Top tools by usage
            top_tools = sorted(
                self._tool_stats.items(),
                key=lambda x: x[1].call_count,
                reverse=True,
            )[:10]

            # Tools with high error rates
            error_tools = [
                (name, s)
                for name, s in self._tool_stats.items()
                if s.call_count > 0 and s.error_count / s.call_count > 0.1
            ]

            # Top errors
            top_errors = sorted(
                self._error_counts.items(),
                key=lambda x: x[1],
                reverse=True,
            )[:5]

            session_count = self._session_count
            total_iterations = self._total_iterations
            token_records = len(self._token_usage)

        recommendations: list[str] = []

        if recent_tokens > 100000:
            recommendations.append(
                f"High token usage in last hour ({recent_tokens} tokens). "
                "Consider enabling smart model routing or context compression."
            )

        for name, stat in error_tools:
            error_rate = stat.error_count / stat.call_count * 100
            recommendations.append(
                f"Tool '{name}' has {error_rate:.0f}% error rate "
                f"({stat.error_count}/{stat.call_count}). Investigate failures."
            )

        if top_errors:
            top_err, count = top_errors[0]
            recommendations.append(
                f"Most common error: '{top_err}' ({count} occurrences). "
                "Review error_classifier reports for patterns."
            )

        avg_iterations = (
            total_iterations / session_count
            if session_count > 0
            else 0
        )
        if avg_iterations > 50:
            recommendations.append(
                f"Average iterations per session is high ({avg_iterations:.0f}). "
                "Consider optimizing tool usage or enabling budget grace calls."
            )

        return {
            "summary": {
                "total_sessions": session_count,
                "total_iterations": total_iterations,
                "avg_iterations_per_session": round(avg_iterations, 1),
                "tools_used": len(self._tool_stats),
            },
            "token_usage": {
                "last_hour": recent_tokens,
                "total_records": token_records,
            },
            "top_tools": [
                {
                    "name": name,
                    "calls": s.call_count,
                    "avg_duration_ms": round(s.avg_duration * 1000, 1),
                    "errors": s.error_count,
                }
                for name, s in top_tools
            ],
            "top_errors": [
                {"category": cat, "count": count}
                for cat, count in top_errors
            ],
            "recommendations": recommendations,
        }


# Global singleton
insights_engine = InsightsEngine()
