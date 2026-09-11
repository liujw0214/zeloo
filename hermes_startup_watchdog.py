"""Startup-liveness watchdog — catch gateways that wedge before the loop starts.

This closes the gap between process-start and event-loop-arming: if the
gateway deadlocks before the event loop runs (observed failure class on
Windows with futex-parking), the watchdog dumps all-thread stacks via
faulthandler and exits with the service-restart code so systemd/s6 revive.

Slow-but-alive startups are NOT killed — ``report_startup_progress()``
and process-CPU consumption are used as progress signals.

Env vars:
  ZELOO_STARTUP_WATCHDOG=0        to disable
  ZELOO_STARTUP_WATCHDOG_TIMEOUT_S  to tune the deadline (default 300s)
"""

from __future__ import annotations

import faulthandler
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_STARTUP_WATCHDOG_TIMEOUT_S = 300.0
_MIN_TIMEOUT_S = 30.0

SERVICE_RESTART_EXIT_CODE = 75

ENV_STARTUP_WATCHDOG = "ZELOO_STARTUP_WATCHDOG"
ENV_STARTUP_WATCHDOG_TIMEOUT_S = "ZELOO_STARTUP_WATCHDOG_TIMEOUT_S"

FALSEY = frozenset({"0", "false", "no", "off"})
_POLL_SLICE_S = 5.0
_CPU_PROGRESS_MIN_S = 0.5
_MAX_CPU_EXTENSIONS = 3
_MAX_LEASE_S = 900.0
_LEDGER_JOIN_TIMEOUT_S = 5.0

_ARMED = "armed"
_DISARMED = "disarmed"

_handle_lock = threading.Lock()
_handle: Optional["StartupWatchdogHandle"] = None


def _process_zeloo_home() -> Path:
    """ZELOO_HOME for diagnostic files."""
    val = os.environ.get("ZELOO_HOME", "").strip()
    if val:
        return Path(val)
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return base / "Zeloo"
    return Path.home() / ".Zeloo"


def get_startup_watchdog_dump_path(home: Optional[Path] = None) -> Path:
    base = home if home is not None else _process_zeloo_home()
    return base / "logs" / "startup-watchdog.log"


def startup_watchdog_disabled() -> bool:
    raw = os.environ.get(ENV_STARTUP_WATCHDOG, "").strip().lower()
    return raw in FALSEY


def resolve_startup_watchdog_timeout() -> float:
    raw = os.environ.get(ENV_STARTUP_WATCHDOG_TIMEOUT_S, "").strip()
    if not raw:
        return DEFAULT_STARTUP_WATCHDOG_TIMEOUT_S
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_STARTUP_WATCHDOG_TIMEOUT_S
    if value <= 0:
        return DEFAULT_STARTUP_WATCHDOG_TIMEOUT_S
    return max(value, _MIN_TIMEOUT_S)


def _write_dump_record(record: dict[str, Any]) -> None:
    try:
        path = get_startup_watchdog_dump_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
    except Exception:
        pass


def _mark_lifecycle_exit(exit_code: int) -> None:
    try:
        from gateway.lifecycle_ledger import mark_exited

        mark_exited(exit_code, reason="startup_liveness_watchdog")
    except Exception:
        pass


class StartupWatchdogHandle:
    """Disarm/inspect handle for the armed startup watchdog thread."""

    def __init__(self, timeout_s: float, exit_code: int):
        self.timeout_s = timeout_s
        self.exit_code = exit_code
        self.armed_at = time.monotonic()
        self._state = _ARMED
        self._state_lock = threading.Lock()
        self._deadline = self.armed_at + timeout_s
        self._disarmed_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._extensions = 0
        self._lease_until = 0.0
        self._lease_phase: Optional[str] = None

    def disarm(self) -> None:
        """Startup reached a live event loop — stand down. Idempotent."""
        with self._state_lock:
            if self._state == _ARMED:
                self._state = _DISARMED
        self._disarmed_event.set()

    def kick(self, extra_s: float = 0.0) -> None:
        """Push the deadline out by timeout + extra_s (for intentional sleeps)."""
        with self._state_lock:
            self._deadline = time.monotonic() + self.timeout_s + max(0.0, extra_s)

    def report_progress(self, phase: str, lease_s: float) -> None:
        """Declare that the current phase owns the lease for up to lease_s seconds."""
        with self._state_lock:
            self._lease_phase = phase
            self._lease_until = time.monotonic() + min(lease_s, _MAX_LEASE_S)

    def _remaining(self) -> float:
        return max(0.0, self._deadline - time.monotonic())

    def _fire(self) -> None:
        """Kill the process — called on the watchdog thread."""
        faulthandler.dump_traceback(all_threads=True)

        pid = os.getpid()
        record = {
            "event": "startup_watchdog_fire",
            "pid": pid,
            "timeout_s": self.timeout_s,
            "extensions": self._extensions,
            "lease_phase": self._lease_phase,
            "timestamp": time.time(),
        }
        _write_dump_record(record)

        def ledger_and_exit() -> None:
            _mark_lifecycle_exit(self.exit_code)
            os._exit(self.exit_code)

        t = threading.Thread(target=ledger_and_exit, daemon=True)
        t.start()
        t.join(timeout=_LEDGER_JOIN_TIMEOUT_S)
        os._exit(self.exit_code)

    def _wait_loop(self) -> None:
        process_start = time.process_time()
        while True:
            elapsed = self._disarmed_event.wait(timeout=_POLL_SLICE_S)
            if elapsed:
                return

            with self._state_lock:
                if self._state != _ARMED:
                    return
                remaining = self._remaining()
                lease_active = time.monotonic() < self._lease_until

            if remaining > 0 or lease_active:
                if remaining <= 0:
                    self.kick(0.0)
                continue

            cpu_delta = time.process_time() - process_start
            if cpu_delta >= _CPU_PROGRESS_MIN_S and self._extensions < _MAX_CPU_EXTENSIONS:
                self._extensions += 1
                self.kick(0.0)
                process_start = time.process_time()
                logger.debug(
                    "startup_watchdog: CPU progress detected, extending deadline "
                    "(extension %d/%d)",
                    self._extensions,
                    _MAX_CPU_EXTENSIONS,
                )
                continue

            logger.error(
                "startup_watchdog: startup did not reach a live loop within "
                "%.0fs (extensions=%d, lease=%s); exiting with code %d",
                self.timeout_s,
                self._extensions,
                self._lease_phase,
                self.exit_code,
            )
            self._fire()

    def _thread_target(self) -> None:
        try:
            self._wait_loop()
        except Exception:
            logger.debug("startup_watchdog thread exiting", exc_info=True)


def arm_startup_watchdog(
    timeout_s: Optional[float] = None,
    exit_code: int = SERVICE_RESTART_EXIT_CODE,
) -> Optional[StartupWatchdogHandle]:
    """Arm the startup watchdog and return a handle.

    Returns None when disabled via env var.
    Call ``handle.disarm()`` when the event loop is confirmed live.
    """
    if startup_watchdog_disabled():
        return None

    if timeout_s is None:
        timeout_s = resolve_startup_watchdog_timeout()

    handle = StartupWatchdogHandle(timeout_s, exit_code)
    t = threading.Thread(target=handle._thread_target, name="startup-watchdog", daemon=True)
    handle._thread = t
    t.start()

    with _handle_lock:
        global _handle
        _handle = handle

    return handle


def kick_startup_watchdog(extra_s: float = 0.0) -> None:
    """Push the watchdog deadline (for intentional sleeps)."""
    with _handle_lock:
        if _handle is not None:
            _handle.kick(extra_s)


def report_startup_progress(phase: str, lease_s: float = 60.0) -> None:
    """Declare progress so the watchdog knows startup is alive."""
    with _handle_lock:
        if _handle is not None:
            _handle.report_progress(phase, lease_s)


def disarm_startup_watchdog() -> None:
    """Disarm the watchdog when the event loop is confirmed live."""
    with _handle_lock:
        if _handle is not None:
            _handle.disarm()
