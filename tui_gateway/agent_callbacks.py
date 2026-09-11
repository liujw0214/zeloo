"""Agent lifecycle callbacks for the TUI gateway.

Provides a registry for Agent state-change events (start/think/tool_call/
finish/error) and dispatch them to subscribed TUI views. The gateway itself
remains stateless — this module only fans out events.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class AgentEventType(StrEnum):
    START = "start"
    THINK = "think"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    FINISH = "finish"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class AgentEvent:
    type: AgentEventType
    session_id: str
    timestamp: float = field(default_factory=time.time)
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }


CallbackFn = Callable[[AgentEvent], None]


class CallbackRegistry:
    """Stores per-event-type subscribers and dispatches events.

    Subscribers are plain callables. Exceptions raised by a subscriber are
    logged but never propagated (so a broken view can't bring down the agent).
    """

    def __init__(self) -> None:
        self._subscribers: dict[AgentEventType, list[CallbackFn]] = {
            t: [] for t in AgentEventType
        }
        self._history: list[AgentEvent] = []
        self._max_history = 200

    def subscribe(self, event_type: AgentEventType, callback: CallbackFn) -> Callable[[], None]:
        self._subscribers[event_type].append(callback)

        def _unsubscribe() -> None:
            try:
                self._subscribers[event_type].remove(callback)
            except ValueError:
                pass

        return _unsubscribe

    def emit(self, event: AgentEvent) -> None:
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]

        for cb in self._subscribers.get(event.type, []):
            try:
                cb(event)
            except Exception:
                logger.exception(
                    "Subscriber for %s raised; continuing", event.type.value
                )

    def history(self, session_id: str | None = None, limit: int = 50) -> list[AgentEvent]:
        items = self._history
        if session_id is not None:
            items = [e for e in items if e.session_id == session_id]
        return items[-limit:]

    def clear_history(self) -> None:
        self._history.clear()


_registry = CallbackRegistry()


def get_registry() -> CallbackRegistry:
    return _registry


def emit_start(session_id: str, **payload: Any) -> None:
    _registry.emit(AgentEvent(AgentEventType.START, session_id, payload=dict(payload)))


def emit_think(session_id: str, **payload: Any) -> None:
    _registry.emit(AgentEvent(AgentEventType.THINK, session_id, payload=dict(payload)))


def emit_tool_call(session_id: str, name: str, args: dict[str, Any] | None = None) -> None:
    _registry.emit(
        AgentEvent(
            AgentEventType.TOOL_CALL,
            session_id,
            payload={"name": name, "args": args or {}},
        )
    )


def emit_tool_result(session_id: str, name: str, result: Any) -> None:
    _registry.emit(
        AgentEvent(
            AgentEventType.TOOL_RESULT,
            session_id,
            payload={"name": name, "result": result},
        )
    )


def emit_finish(session_id: str, **payload: Any) -> None:
    _registry.emit(
        AgentEvent(AgentEventType.FINISH, session_id, payload=dict(payload))
    )


def emit_error(session_id: str, exc: BaseException) -> None:
    _registry.emit(
        AgentEvent(
            AgentEventType.ERROR,
            session_id,
            payload={"error": str(exc), "type": type(exc).__name__},
        )
    )


def emit_cancelled(session_id: str) -> None:
    _registry.emit(AgentEvent(AgentEventType.CANCELLED, session_id))
