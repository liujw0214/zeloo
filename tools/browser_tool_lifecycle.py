"""Browser lifecycle management with startup and shutdown hooks.

This module provides lifecycle management for browser resources, including
automatic cleanup, graceful shutdown, and emergency cleanup procedures.

Example::

    from tools.browser_tool_lifecycle import (
        BrowserLifecycle,
        setup_lifecycle_hooks,
        cleanup_all_sessions,
    )

    lifecycle = BrowserLifecycle()
    lifecycle.start()
    # ... use browser tools ...
    lifecycle.stop()
"""

from __future__ import annotations

import atexit
import logging
import signal
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class LifecycleState(Enum):
    """Browser lifecycle states."""

    UNINITIALIZED = "uninitialized"
    INITIALIZING = "initializing"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class LifecycleHook:
    """A lifecycle hook callback."""

    name: str
    callback: Callable[[], Any]
    order: int = 0
    timeout: float = 30.0
    enabled: bool = True


@dataclass
class LifecycleStats:
    """Statistics about browser lifecycle operations."""

    start_time: datetime | None = None
    stop_time: datetime | None = None
    sessions_created: int = 0
    sessions_closed: int = 0
    cleanup_attempts: int = 0
    cleanup_failures: int = 0
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary format."""
        return {
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "stop_time": self.stop_time.isoformat() if self.stop_time else None,
            "sessions_created": self.sessions_created,
            "sessions_closed": self.sessions_closed,
            "cleanup_attempts": self.cleanup_attempts,
            "cleanup_failures": self.cleanup_failures,
            "last_error": self.last_error,
            "uptime_seconds": (
                (datetime.now() - self.start_time).total_seconds()
                if self.start_time and self.stop_time is None
                else 0
            ),
        }


class BrowserLifecycle:
    """Manages browser lifecycle with startup and shutdown hooks.

    This class handles the complete lifecycle of browser resources,
    including initialization, graceful shutdown, and emergency cleanup.

    Example::

        lifecycle = BrowserLifecycle()

        # Register cleanup hooks
        lifecycle.register_hook(LifecycleHook(
            name="close_tabs",
            callback=lambda: print("Closing tabs"),
            order=1
        ))

        lifecycle.register_hook(LifecycleHook(
            name="close_sessions",
            callback=lambda: print("Closing sessions"),
            order=2
        ))

        # Start lifecycle
        lifecycle.start()

        # ... use browser ...

        # Stop lifecycle (will call all hooks in reverse order)
        lifecycle.stop()
    """

    def __init__(self) -> None:
        self._state = LifecycleState.UNINITIALIZED
        self._lock = threading.Lock()
        self._hooks: list[LifecycleHook] = []
        self._stats = LifecycleStats()
        self._atexit_registered = False
        self._signal_handlers_registered = False
        self._session_manager: Any = None

    @property
    def state(self) -> LifecycleState:
        """Get current lifecycle state."""
        return self._state

    @property
    def is_running(self) -> bool:
        """Check if lifecycle is in running state."""
        return self._state == LifecycleState.RUNNING

    def set_session_manager(self, manager: Any) -> None:
        """Set the session manager for lifecycle operations.

        Args:
            manager: BrowserSessionManager instance.
        """
        self._session_manager = manager

    def register_hook(
        self,
        name: str,
        callback: Callable[[], Any],
        order: int = 0,
        timeout: float = 30.0,
    ) -> None:
        """Register a lifecycle hook.

        Hooks are called in order during shutdown (ascending order).

        Args:
            name: Unique name for the hook.
            callback: Function to call during lifecycle events.
            order: Execution order (lower = earlier).
            timeout: Maximum time to wait for callback completion.
        """
        hook = LifecycleHook(
            name=name,
            callback=callback,
            order=order,
            timeout=timeout,
        )

        with self._lock:
            self._hooks.append(hook)
            self._hooks.sort(key=lambda h: h.order)

        logger.debug("Registered lifecycle hook: %s (order=%d)", name, order)

    def unregister_hook(self, name: str) -> bool:
        """Unregister a lifecycle hook.

        Args:
            name: Name of the hook to remove.

        Returns:
            True if hook was found and removed.
        """
        with self._lock:
            for i, hook in enumerate(self._hooks):
                if hook.name == name:
                    self._hooks.pop(i)
                    logger.debug("Unregistered lifecycle hook: %s", name)
                    return True
        return False

    def start(self) -> bool:
        """Start the browser lifecycle.

        Returns:
            True if lifecycle started successfully.
        """
        with self._lock:
            if self._state == LifecycleState.RUNNING:
                logger.warning("Lifecycle already running")
                return True

            if self._state == LifecycleState.INITIALIZING:
                logger.warning("Lifecycle already initializing")
                return False

            self._state = LifecycleState.INITIALIZING

        try:
            self._setup_signal_handlers()
            self._register_atexit()

            self._stats.start_time = datetime.now()
            self._state = LifecycleState.RUNNING

            logger.info("Browser lifecycle started")
            return True

        except Exception as e:
            self._state = LifecycleState.ERROR
            self._stats.last_error = str(e)
            logger.error("Failed to start lifecycle: %s", e)
            return False

    def stop(self, force: bool = False) -> bool:
        """Stop the browser lifecycle and run cleanup hooks.

        Args:
            force: If True, skip waiting for hooks to complete.

        Returns:
            True if lifecycle stopped successfully.
        """
        with self._lock:
            if self._state in (LifecycleState.STOPPED, LifecycleState.UNINITIALIZED):
                return True

            if self._state == LifecycleState.STOPPING:
                logger.warning("Lifecycle already stopping")
                return False

            self._state = LifecycleState.STOPPING

        logger.info("Stopping browser lifecycle...")

        try:
            self._run_cleanup_hooks(reverse=True)
            self._cleanup_sessions()

            self._stats.stop_time = datetime.now()
            self._state = LifecycleState.STOPPED

            logger.info("Browser lifecycle stopped")
            return True

        except Exception as e:
            self._state = LifecycleState.ERROR
            self._stats.last_error = str(e)
            logger.error("Error during lifecycle stop: %s", e)
            return False

    def _run_cleanup_hooks(self, reverse: bool = True) -> None:
        """Run all registered cleanup hooks.

        Args:
            reverse: If True, run hooks in reverse order.
        """
        with self._lock:
            hooks_to_run = list(reversed(self._hooks) if reverse else self._hooks)

        for hook in hooks_to_run:
            if not hook.enabled:
                continue

            self._stats.cleanup_attempts += 1
            logger.debug("Running cleanup hook: %s", hook.name)

            try:
                if hook.timeout > 0:
                    import time

                    result = [None]
                    exception = [None]

                    def run_hook():
                        try:
                            result[0] = hook.callback()
                        except Exception as e:
                            exception[0] = e

                    thread = threading.Thread(target=run_hook, daemon=True)
                    thread.start()
                    thread.join(timeout=hook.timeout)

                    if thread.is_alive():
                        logger.warning(
                            "Cleanup hook '%s' timed out after %.1fs",
                            hook.name,
                            hook.timeout,
                        )
                    elif exception[0]:
                        raise exception[0]
                else:
                    hook.callback()

            except Exception as e:
                self._stats.cleanup_failures += 1
                logger.error("Cleanup hook '%s' failed: %s", hook.name, e)

    def _cleanup_sessions(self) -> None:
        """Clean up all browser sessions."""
        if self._session_manager is None:
            return

        try:
            closed = self._session_manager.close_all_sessions()
            self._stats.sessions_closed = closed
            logger.debug("Closed %d browser sessions", closed)
        except Exception as e:
            self._stats.cleanup_failures += 1
            logger.error("Failed to cleanup sessions: %s", e)

    def _setup_signal_handlers(self) -> None:
        """Register signal handlers for graceful shutdown."""
        if self._signal_handlers_registered:
            return

        def signal_handler(signum: int, frame: Any) -> None:
            signal_name = signal.Signals(signum).name
            logger.info("Received signal %s, initiating graceful shutdown...", signal_name)
            self.stop()

        try:
            signal.signal(signal.SIGTERM, signal_handler)
            signal.signal(signal.SIGINT, signal_handler)

            if sys.platform != "win32":
                signal.signal(signal.SIGHUP, signal_handler)

            self._signal_handlers_registered = True
            logger.debug("Signal handlers registered")

        except Exception as e:
            logger.warning("Failed to register signal handlers: %s", e)

    def _register_atexit(self) -> None:
        """Register atexit handler for cleanup."""
        if self._atexit_registered:
            return

        try:
            atexit.register(self._atexit_cleanup)
            self._atexit_registered = True
            logger.debug("Atexit handler registered")

        except Exception as e:
            logger.warning("Failed to register atexit handler: %s", e)

    def _atexit_cleanup(self) -> None:
        """Cleanup function registered with atexit."""
        try:
            if self._state == LifecycleState.RUNNING:
                logger.debug("Running atexit cleanup")
                self._run_cleanup_hooks(reverse=True)
                self._cleanup_sessions()
        except Exception as e:
            logger.error("Error during atexit cleanup: %s", e)

    def get_stats(self) -> dict[str, Any]:
        """Get lifecycle statistics.

        Returns:
            Dictionary containing lifecycle statistics.
        """
        with self._lock:
            return self._stats.to_dict()

    def record_session_created(self) -> None:
        """Record that a new session was created."""
        self._stats.sessions_created += 1

    def record_session_closed(self) -> None:
        """Record that a session was closed."""
        self._stats.sessions_closed += 1


_lifecycle_instance: BrowserLifecycle | None = None
_lifecycle_lock = threading.Lock()


def get_lifecycle() -> BrowserLifecycle:
    """Get the global lifecycle instance.

    Returns:
        The global BrowserLifecycle singleton.
    """
    global _lifecycle_instance
    with _lifecycle_lock:
        if _lifecycle_instance is None:
            _lifecycle_instance = BrowserLifecycle()
        return _lifecycle_instance


def cleanup_all_sessions() -> int:
    """Clean up all browser sessions using the global lifecycle.

    Returns:
        Number of sessions cleaned up.
    """
    lifecycle = get_lifecycle()
    if lifecycle._session_manager:
        return lifecycle._session_manager.close_all_sessions()
    return 0


def _emergency_cleanup_all_sessions() -> None:
    """Emergency cleanup - no logging or error handling.

    This function is designed to be called in the most critical
    situations where normal cleanup might fail.
    """
    try:
        lifecycle = get_lifecycle()
        if lifecycle._session_manager:
            lifecycle._session_manager.close_all_sessions()
    except Exception:
        pass

    try:
        import sys
        if "playwright" in sys.modules:
            try:
                from playwright.sync_api import sync_playwright

                pw = sync_playwright()
                pw.stop()
            except Exception:
                pass
    except Exception:
        pass


def setup_lifecycle_hooks(
    session_manager: Any,
    lifecycle: BrowserLifecycle | None = None,
) -> BrowserLifecycle:
    """Set up standard lifecycle hooks for browser management.

    Args:
        session_manager: BrowserSessionManager instance.
        lifecycle: Optional existing lifecycle to configure.

    Returns:
        Configured BrowserLifecycle instance.
    """
    if lifecycle is None:
        lifecycle = get_lifecycle()

    lifecycle.set_session_manager(session_manager)

    lifecycle.register_hook(
        name="close_sessions",
        callback=lambda: session_manager.close_all_sessions(),
        order=100,
        timeout=60.0,
    )

    return lifecycle


def register_emergency_cleanup() -> None:
    """Register emergency cleanup to run on process termination.

    This should only be used in critical scenarios where normal
    cleanup might not execute.
    """
    import os

    try:
        if hasattr(os, "register_at_fork"):
            os.register_at_fork(
                after_in_child=_emergency_cleanup_all_sessions,
                after_in_parent=None,
            )
    except Exception as e:
        logger.warning("Failed to register fork cleanup: %s", e)


def reset_session_manager() -> None:
    """Reset the session manager and close all sessions.

    This function is used to clean up the global session manager
    and ensure all browser sessions are properly closed.
    """
    lifecycle = get_lifecycle()
    if lifecycle._session_manager:
        lifecycle._session_manager.close_all_sessions()

    global _lifecycle_instance
    _lifecycle_instance = None
