"""Agent analytics — usage statistics and performance metrics."""

from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class AgentMetrics:
    """Aggregated agent performance metrics."""

    total_sessions: int = 0
    total_turns: int = 0
    total_tool_calls: int = 0
    successful_tool_calls: int = 0
    failed_tool_calls: int = 0
    avg_response_time_ms: float = 0.0
    avg_tokens_per_turn: float = 0.0
    total_cost_usd: float = 0.0
    tool_usage_distribution: dict[str, int] = field(default_factory=dict)
    error_distribution: dict[str, int] = field(default_factory=dict)
    time_window_start: float = field(default_factory=time.time)
    time_window_end: float = field(default_factory=time.time)
    avg_turns_per_session: float = 0.0


class AgentAnalytics:
    """Track and analyze agent performance metrics.

    Provides insights into:
    - Response times
    - Tool usage patterns
    - Error rates
    - Cost efficiency
    - Token consumption
    """

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []

    def record_turn(
        self,
        session_id: str,
        turn_id: int,
        tool_calls: list[str] | None = None,
        response_time_ms: float = 0.0,
        tokens_used: int = 0,
        cost_usd: float = 0.0,
        success: bool = True,
        error: str = "",
    ) -> None:
        """Record metrics for a single turn."""
        event = {
            "timestamp": time.time(),
            "session_id": session_id,
            "turn_id": turn_id,
            "tool_calls": tool_calls or [],
            "response_time_ms": response_time_ms,
            "tokens_used": tokens_used,
            "cost_usd": cost_usd,
            "success": success,
            "error": error,
        }
        self._events.append(event)
        logger.debug("Recorded turn metrics: session=%s turn=%d", session_id, turn_id)

    def get_metrics(
        self,
        since: float | None = None,
        until: float | None = None,
    ) -> AgentMetrics:
        """Get aggregated metrics for a time window."""
        if since is None:
            since = 0.0
        upper = until if until is not None else time.time()
        events = [e for e in self._events if since <= e["timestamp"] <= upper]

        if not events:
            return AgentMetrics(
                time_window_start=since,
                time_window_end=until or time.time(),
            )

        tool_counter: Counter = Counter()
        error_counter: Counter = Counter()
        successful = 0
        failed = 0
        total_cost = 0.0
        for event in events:
            for tool in event.get("tool_calls", []):
                tool_counter[tool] += 1
            if event.get("success", True):
                successful += 1
            else:
                failed += 1
                if event.get("error"):
                    error_counter[event["error"][:50]] += 1
            total_cost += event.get("cost_usd", 0.0)

        # Compute averages from the *filtered* event set so the returned
        # metric actually matches the requested time window.
        avg_response = (
            sum(e.get("response_time_ms", 0.0) for e in events) / len(events)
        )
        avg_tokens = sum(int(e.get("tokens_used", 0)) for e in events) / len(events)

        sessions = {e["session_id"] for e in events}
        avg_turns_per_session = len(events) / max(len(sessions), 1)

        return AgentMetrics(
            total_sessions=len(sessions),
            total_turns=len(events),
            total_tool_calls=sum(tool_counter.values()),
            successful_tool_calls=successful,
            failed_tool_calls=failed,
            avg_response_time_ms=avg_response,
            avg_tokens_per_turn=avg_tokens,
            total_cost_usd=total_cost,
            tool_usage_distribution=dict(tool_counter),
            error_distribution=dict(error_counter),
            time_window_start=events[0]["timestamp"],
            time_window_end=events[-1]["timestamp"],
            avg_turns_per_session=avg_turns_per_session,
        )

    def get_tool_rankings(self, top_n: int = 10) -> list[tuple[str, int]]:
        """Get most-used tools."""
        counter: Counter = Counter()
        for event in self._events:
            for tool in event.get("tool_calls", []):
                counter[tool] += 1
        return counter.most_common(top_n)

    def get_error_rate(self) -> float:
        """Get overall error rate."""
        if not self._events:
            return 0.0
        failed = sum(1 for e in self._events if not e.get("success", True))
        return failed / len(self._events)

    def reset(self) -> None:
        """Clear all recorded metrics."""
        self._events.clear()


__all__ = [
    "AgentMetrics",
    "AgentAnalytics",
]