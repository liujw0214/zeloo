"""estop — emergency stop mechanism for the agent runtime.

This provides a global
emergency stop that can halt all agent activity immediately.

The estop is a process-wide flag that, when set, causes:
- The conversation loop to break at the next iteration boundary
- All pending tool calls to be cancelled
- No new LLM calls to be made

Usage::

    from agent.estop import estop

    # Trigger emergency stop
    estop.trigger(reason="User requested stop")

    # Check if stopped
    if estop.is_stopped():
        return

    # Reset (for testing or after resolution)
    estop.reset()
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EstopState:
    """Current emergency stop state."""

    stopped: bool = False
    reason: str = ""
    triggered_at: float = 0.0
    triggered_by: str = "system"
    stack: list[dict[str, Any]] = field(default_factory=list)


class EmergencyStop:
    """Process-wide emergency stop controller.

    Thread-safe. Supports nested triggers (stack-based) so multiple
    subsystems can request a stop independently.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = EstopState()

    def trigger(self, reason: str = "", by: str = "system") -> None:
        """Trigger the emergency stop.

        Args:
            reason: Human-readable reason for the stop.
            by: Identifier of the component triggering the stop.
        """
        first_trigger = False
        with self._lock:
            if not self._state.stopped:
                first_trigger = True
                self._state.stopped = True
                self._state.reason = reason
                self._state.triggered_at = time.time()
                self._state.triggered_by = by
            # Push onto the stack for nested stops
            self._state.stack.append(
                {"reason": reason, "by": by, "at": time.time()}
            )
            logger.warning("ESTOP triggered by '%s': %s", by, reason)
        # Audit (only the first activation is the security-relevant event;
        # nested triggers are logged at debug level to avoid noise).
        if first_trigger:
            try:
                from agent.audit_log import audit_event

                audit_event(
                    "estop_triggered",
                    actor=by,
                    resource="estop",
                    outcome="ok",
                    detail={"reason": reason},
                )
            except Exception:  # noqa: BLE001
                pass

    def reset(self) -> None:
        """Reset the emergency stop (clears all stack entries)."""
        was_stopped = False
        with self._lock:
            was_stopped = self._state.stopped
            self._state.stopped = False
            self._state.reason = ""
            self._state.triggered_at = 0.0
            self._state.triggered_by = "system"
            self._state.stack.clear()
            logger.info("ESTOP reset")
        if was_stopped:
            try:
                from agent.audit_log import audit_event

                audit_event(
                    "estop_reset",
                    actor="system",
                    resource="estop",
                    outcome="ok",
                )
            except Exception:  # noqa: BLE001
                pass

    def is_stopped(self) -> bool:
        """Return True if the emergency stop is active."""
        with self._lock:
            return self._state.stopped

    def get_state(self) -> EstopState:
        """Return a snapshot of the current estop state."""
        with self._lock:
            return EstopState(
                stopped=self._state.stopped,
                reason=self._state.reason,
                triggered_at=self._state.triggered_at,
                triggered_by=self._state.triggered_by,
                stack=list(self._state.stack),
            )


# Global singleton
estop = EmergencyStop()
