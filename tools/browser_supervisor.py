"""Browser process supervisor for health monitoring and automatic recovery.

This module provides process supervision for browser instances, including
health checks, automatic restart on crash, and resource cleanup.

Example::

    from tools.browser_supervisor import BrowserSupervisor

    supervisor = BrowserSupervisor()
    supervisor.start()
    # ... browser operations ...
    supervisor.stop()
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Browser health status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    CRASHED = "crashed"
    UNKNOWN = "unknown"


@dataclass
class ProcessInfo:
    """Information about a supervised browser process."""

    pid: int
    session_id: str
    started_at: datetime
    restart_count: int = 0
    last_health_check: datetime | None = None
    last_restart: datetime | None = None
    memory_mb: float = 0.0
    cpu_percent: float = 0.0
    status: HealthStatus = HealthStatus.UNKNOWN
    error: str | None = None


@dataclass
class SupervisorConfig:
    """Configuration for browser process supervision."""

    health_check_interval: float = 30.0
    health_check_timeout: float = 10.0
    max_restart_attempts: int = 3
    restart_delay: float = 5.0
    restart_window_seconds: float = 300.0
    max_memory_mb: float = 2048.0
    enable_auto_restart: bool = True
    enable_health_monitoring: bool = True
    on_crash_callback: Callable[[str], Any] | None = None
    on_restart_callback: Callable[[str], Any] | None = None


class BrowserSupervisor:
    """Supervises browser processes for health monitoring and recovery.

    This class monitors browser processes, performs health checks,
    and automatically restarts crashed processes within configurable limits.

    Example::

        def on_crash(session_id):
            print(f"Session {session_id} crashed!")

        def on_restart(session_id):
            print(f"Session {session_id} restarted!")

        config = SupervisorConfig(
            health_check_interval=30.0,
            max_restart_attempts=3,
            on_crash_callback=on_crash,
            on_restart_callback=on_restart,
        )

        supervisor = BrowserSupervisor(config)
        supervisor.start()

        # Register a browser session
        supervisor.register_session(session_id, process_pid)

        # ... operations ...

        supervisor.stop()
    """

    def __init__(self, config: SupervisorConfig | None = None) -> None:
        self.config = config or SupervisorConfig()
        self._processes: dict[str, ProcessInfo] = {}
        self._lock = threading.Lock()
        self._running = False
        self._monitor_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def register_session(
        self,
        session_id: str,
        pid: int | None = None,
        restart_callback: Callable[[], bool] | None = None,
    ) -> bool:
        """Register a browser session for supervision.

        Args:
            session_id: Unique identifier for the session.
            pid: Process ID of the browser (optional).
            restart_callback: Function to call for session restart.

        Returns:
            True if session registered successfully.
        """
        with self._lock:
            if session_id in self._processes:
                logger.warning("Session %s already registered", session_id)
                return False

            process_info = ProcessInfo(
                pid=pid or 0,
                session_id=session_id,
                started_at=datetime.now(),
            )
            self._processes[session_id] = process_info

            logger.info("Registered session %s for supervision", session_id)
            return True

    def unregister_session(self, session_id: str) -> bool:
        """Unregister a browser session from supervision.

        Args:
            session_id: Session identifier to remove.

        Returns:
            True if session was found and removed.
        """
        with self._lock:
            if session_id in self._processes:
                self._processes.pop(session_id)
                logger.info("Unregistered session %s from supervision", session_id)
                return True
            return False

    def update_session_pid(self, session_id: str, pid: int) -> bool:
        """Update the process ID for a supervised session.

        Args:
            session_id: Session identifier.
            pid: New process ID.

        Returns:
            True if session found and updated.
        """
        with self._lock:
            process_info = self._processes.get(session_id)
            if process_info:
                process_info.pid = pid
                return True
            return False

    def start(self) -> bool:
        """Start the supervisor monitoring loop.

        Returns:
            True if supervisor started successfully.
        """
        if self._running:
            logger.warning("Supervisor already running")
            return True

        self._running = True
        self._stop_event.clear()

        self._monitor_thread = threading.Thread(
            target=self._monitoring_loop,
            daemon=True,
            name="BrowserSupervisor",
        )
        self._monitor_thread.start()

        logger.info("Browser supervisor started")
        return True

    def stop(self) -> bool:
        """Stop the supervisor monitoring loop.

        Returns:
            True if supervisor stopped successfully.
        """
        if not self._running:
            return True

        self._running = False
        self._stop_event.set()

        if self._monitor_thread:
            self._monitor_thread.join(timeout=5.0)
            self._monitor_thread = None

        logger.info("Browser supervisor stopped")
        return True

    def _monitoring_loop(self) -> None:
        """Main monitoring loop."""
        while self._running and not self._stop_event.is_set():
            try:
                self._check_all_processes()
                self._cleanup_stale_processes()
            except Exception as e:
                logger.exception("Error in monitoring loop: %s", e)

            self._stop_event.wait(self.config.health_check_interval)

    def _check_all_processes(self) -> None:
        """Check health of all supervised processes."""
        with self._lock:
            session_ids = list(self._processes.keys())

        for session_id in session_ids:
            try:
                self._check_process_health(session_id)
            except Exception as e:
                logger.error("Error checking process %s: %s", session_id, e)

    def _check_process_health(self, session_id: str) -> None:
        """Check health of a single process."""
        with self._lock:
            process_info = self._processes.get(session_id)
            if not process_info:
                return

        if process_info.pid <= 0:
            process_info.status = HealthStatus.UNKNOWN
            return

        is_alive = self._is_process_alive(process_info.pid)
        process_info.last_health_check = datetime.now()

        if is_alive:
            self._update_process_metrics(process_info)
            if process_info.memory_mb > self.config.max_memory_mb:
                process_info.status = HealthStatus.DEGRADED
                logger.warning(
                    "Session %s memory usage high: %.1f MB",
                    session_id,
                    process_info.memory_mb,
                )
            else:
                process_info.status = HealthStatus.HEALTHY
        else:
            process_info.status = HealthStatus.CRASHED
            self._handle_crash(process_info)

    def _is_process_alive(self, pid: int) -> bool:
        """Check if a process is still running."""
        try:
            import os

            if sys.platform == "win32":
                import ctypes

                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                STILL_ACTIVE = 259

                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if handle:
                    try:
                        exit_code = ctypes.c_ulong()
                        kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                        return exit_code.value == STILL_ACTIVE
                    finally:
                        kernel32.CloseHandle(handle)
                return False
            else:
                import signal

                return os.kill(pid, 0) == 0
        except (OSError, ProcessLookupError, PermissionError):
            return False
        except Exception as e:
            logger.debug("Error checking process %d: %s", pid, e)
            return False

    def _update_process_metrics(self, process_info: ProcessInfo) -> None:
        """Update CPU and memory metrics for a process."""
        try:
            if sys.platform == "win32":
                import psutil

                try:
                    process = psutil.Process(process_info.pid)
                    process_info.memory_mb = process.memory_info().rss / 1024 / 1024
                    process_info.cpu_percent = process.cpu_percent()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            else:
                import psutil

                try:
                    process = psutil.Process(process_info.pid)
                    process_info.memory_mb = process.memory_info().rss / 1024 / 1024
                    process_info.cpu_percent = process.cpu_percent()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except ImportError:
            pass
        except Exception as e:
            logger.debug("Failed to update process metrics: %s", e)

    def _handle_crash(self, process_info: ProcessInfo) -> None:
        """Handle a crashed browser process."""
        logger.warning(
            "Process %s (pid=%d) crashed (restarts=%d)",
            process_info.session_id,
            process_info.pid,
            process_info.restart_count,
        )

        if self.config.on_crash_callback:
            try:
                self.config.on_crash_callback(process_info.session_id)
            except Exception as e:
                logger.error("Crash callback failed: %s", e)

        if not self.config.enable_auto_restart:
            return

        if self._can_restart(process_info):
            self._restart_process(process_info)

    def _can_restart(self, process_info: ProcessInfo) -> bool:
        """Check if a process can be restarted."""
        if process_info.restart_count >= self.config.max_restart_attempts:
            return False

        if process_info.last_restart:
            window_start = datetime.now() - timedelta(
                seconds=self.config.restart_window_seconds
            )
            if process_info.last_restart < window_start:
                return True

            recent_restarts = 0
            for info in self._processes.values():
                if (
                    info.last_restart
                    and info.last_restart > window_start
                    and info.session_id == process_info.session_id
                ):
                    recent_restarts += 1

            return recent_restarts < self.config.max_restart_attempts

        return True

    def _restart_process(self, process_info: ProcessInfo) -> None:
        """Attempt to restart a crashed process."""
        logger.info(
            "Attempting to restart session %s (attempt %d)",
            process_info.session_id,
            process_info.restart_count + 1,
        )

        time.sleep(self.config.restart_delay)

        process_info.restart_count += 1
        process_info.last_restart = datetime.now()
        process_info.status = HealthStatus.UNKNOWN
        process_info.error = None

        if self.config.on_restart_callback:
            try:
                self.config.on_restart_callback(process_info.session_id)
            except Exception as e:
                logger.error("Restart callback failed: %s", e)

    def _cleanup_stale_processes(self) -> None:
        """Remove stale process entries."""
        with self._lock:
            stale_sessions = []

            for session_id, info in self._processes.items():
                if info.status == HealthStatus.CRASHED:
                    if info.last_restart and info.last_restart < datetime.now() - timedelta(
                        seconds=self.config.restart_window_seconds
                    ):
                        if info.restart_count >= self.config.max_restart_attempts:
                            stale_sessions.append(session_id)

            for session_id in stale_sessions:
                self._processes.pop(session_id, None)
                logger.info("Removed stale session: %s", session_id)

    def get_process_info(self, session_id: str) -> dict[str, Any] | None:
        """Get information about a supervised process.

        Args:
            session_id: Session identifier.

        Returns:
            Dictionary with process information or None if not found.
        """
        with self._lock:
            process_info = self._processes.get(session_id)
            if not process_info:
                return None

            return {
                "session_id": process_info.session_id,
                "pid": process_info.pid,
                "started_at": process_info.started_at.isoformat(),
                "restart_count": process_info.restart_count,
                "last_health_check": (
                    process_info.last_health_check.isoformat()
                    if process_info.last_health_check
                    else None
                ),
                "last_restart": (
                    process_info.last_restart.isoformat()
                    if process_info.last_restart
                    else None
                ),
                "memory_mb": round(process_info.memory_mb, 2),
                "cpu_percent": round(process_info.cpu_percent, 2),
                "status": process_info.status.value,
                "error": process_info.error,
            }

    def get_all_processes(self) -> list[dict[str, Any]]:
        """Get information about all supervised processes.

        Returns:
            List of process information dictionaries.
        """
        with self._lock:
            session_ids = list(self._processes.keys())

        return [
            info
            for session_id in session_ids
            if (info := self.get_process_info(session_id)) is not None
        ]

    def get_supervisor_stats(self) -> dict[str, Any]:
        """Get supervisor statistics.

        Returns:
            Dictionary with supervisor statistics.
        """
        with self._lock:
            total = len(self._processes)
            healthy = sum(
                1 for p in self._processes.values() if p.status == HealthStatus.HEALTHY
            )
            crashed = sum(
                1 for p in self._processes.values() if p.status == HealthStatus.CRASHED
            )
            total_restarts = sum(p.restart_count for p in self._processes.values())

        return {
            "running": self._running,
            "total_processes": total,
            "healthy_processes": healthy,
            "crashed_processes": crashed,
            "total_restarts": total_restarts,
            "config": {
                "health_check_interval": self.config.health_check_interval,
                "max_restart_attempts": self.config.max_restart_attempts,
                "max_memory_mb": self.config.max_memory_mb,
                "enable_auto_restart": self.config.enable_auto_restart,
            },
        }


import sys

_supervisor_instance: BrowserSupervisor | None = None
_supervisor_lock = threading.Lock()


def get_supervisor(config: SupervisorConfig | None = None) -> BrowserSupervisor:
    """Get the global supervisor instance.

    Args:
        config: Optional supervisor configuration.

    Returns:
        The global BrowserSupervisor singleton.
    """
    global _supervisor_instance
    with _supervisor_lock:
        if _supervisor_instance is None:
            _supervisor_instance = BrowserSupervisor(config)
        return _supervisor_instance


def reset_supervisor() -> None:
    """Reset the global supervisor."""
    global _supervisor_instance
    with _supervisor_lock:
        if _supervisor_instance is not None:
            _supervisor_instance.stop()
            _supervisor_instance = None
