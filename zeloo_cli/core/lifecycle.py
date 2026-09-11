"""Lifecycle manager — application startup/shutdown orchestration."""

from __future__ import annotations

import logging
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class LifecyclePhase(StrEnum):
    """Application lifecycle phases."""

    CREATED = "created"
    INITIALIZING = "initializing"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class LifecycleHook:
    """A lifecycle hook registration."""

    name: str
    phase: LifecyclePhase
    callback: Callable[[], Any]
    priority: int = 100
    is_async: bool = False
    hook_id: str = field(default_factory=lambda: f"hook_{time.time_ns()}")


class LifecycleManager:
    """Orchestrate application startup and shutdown.

    Hooks are called in priority order (lower = earlier).
    """

    def __init__(self) -> None:
        self._hooks: dict[LifecyclePhase, list[LifecycleHook]] = {
            phase: [] for phase in LifecyclePhase
        }
        self._phase = LifecyclePhase.CREATED
        self._lock = threading.Lock()
        self._start_time: float | None = None
        self._stop_time: float | None = None

    @property
    def phase(self) -> LifecyclePhase:
        return self._phase

    @property
    def uptime_seconds(self) -> float:
        if self._start_time is None:
            return 0.0
        end = self._stop_time or time.time()
        return end - self._start_time

    def register_hook(
        self,
        phase: LifecyclePhase,
        callback: Callable[[], Any],
        name: str = "",
        priority: int = 100,
        is_async: bool = False,
    ) -> LifecycleHook:
        """Register a lifecycle hook."""
        hook = LifecycleHook(
            name=name or callback.__name__,
            phase=phase,
            callback=callback,
            priority=priority,
            is_async=is_async,
        )
        with self._lock:
            self._hooks[phase].append(hook)
            self._hooks[phase].sort(key=lambda h: h.priority)
        logger.debug("Registered hook %s for %s", hook.name, phase.value)
        return hook

    def on_initializing(
        self, callback: Callable[[], Any], name: str = "", priority: int = 100
    ) -> LifecycleHook:
        return self.register_hook(
            LifecyclePhase.INITIALIZING, callback, name, priority
        )

    def on_starting(
        self, callback: Callable[[], Any], name: str = "", priority: int = 100
    ) -> LifecycleHook:
        return self.register_hook(
            LifecyclePhase.STARTING, callback, name, priority
        )

    def on_stopping(
        self, callback: Callable[[], Any], name: str = "", priority: int = 100
    ) -> LifecycleHook:
        return self.register_hook(
            LifecyclePhase.STOPPING, callback, name, priority
        )

    def startup(self) -> bool:
        """Execute the startup sequence (initializing → starting → running)."""
        with self._lock:
            if self._phase != LifecyclePhase.CREATED:
                logger.warning(
                    "Already in phase %s, skipping startup",
                    self._phase.value,
                )
                return False
            self._phase = LifecyclePhase.INITIALIZING

        if not self._execute_phase(LifecyclePhase.INITIALIZING):
            self._phase = LifecyclePhase.ERROR
            return False

        with self._lock:
            self._phase = LifecyclePhase.STARTING

        if not self._execute_phase(LifecyclePhase.STARTING):
            self._phase = LifecyclePhase.ERROR
            return False

        with self._lock:
            self._phase = LifecyclePhase.RUNNING
            self._start_time = time.time()

        logger.info("Application started (uptime starts now)")
        return True

    def shutdown(self) -> bool:
        """Execute the shutdown sequence (stopping → stopped)."""
        with self._lock:
            if self._phase in (LifecyclePhase.STOPPED, LifecyclePhase.CREATED):
                return False
            self._phase = LifecyclePhase.STOPPING

        self._execute_phase(LifecyclePhase.STOPPING)

        with self._lock:
            self._phase = LifecyclePhase.STOPPED
            self._stop_time = time.time()

        logger.info(
            "Application stopped (uptime: %.1fs)",
            self.uptime_seconds,
        )
        return True

    def _execute_phase(self, phase: LifecyclePhase) -> bool:
        hooks = self._hooks.get(phase, [])
        for hook in hooks:
            try:
                hook.callback()
                logger.debug("Hook %s ran successfully", hook.name)
            except Exception as e:
                logger.exception(
                    "Hook %s failed in phase %s: %s",
                    hook.name, phase.value, e,
                )
                logger.error("Traceback: %s", traceback.format_exc())
                return False
        return True


__all__ = ["LifecycleManager", "LifecyclePhase", "LifecycleHook"]