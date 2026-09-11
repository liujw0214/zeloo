"""Lightweight cron scheduler — parse cron expressions and run tasks on time.

Supports three expression formats:
1. **Standard 5-field cron**: ``minute hour day-of-month month day-of-week``
   e.g. ``*/5 * * * *`` (every 5 minutes)
2. **Duration shorthand**: ``Ns`` / ``Nm`` / ``Nh`` / ``Nd`` / ``Nw``
   e.g. ``30m`` (every 30 min) → ``*/30 * * * *``
3. **Natural language aliases**: ``@hourly`` / ``@daily`` / ``@weekly`` / ``@monthly``

Field values: ``*`` (any), ``N`` (exact), ``N-M`` (range), ``N,M`` (list),
``*/N`` (step). Runs in a background daemon thread; tasks are executed
synchronously within the tick loop (keep them short or offload to threads).
"""

from __future__ import annotations

import json
import logging
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import fcntl  # noqa: F401
except ImportError:
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

MAX_FIELD_VALUE = {0: 59, 1: 23, 2: 31, 3: 12, 4: 6}


# Duration shorthand: Ns / Nm / Nh / Nd / Nw → 5-field cron
_DURATION_MAP: dict[str, tuple[int, int, int, int, int]] = {
    "@yearly": (0, 0, 1, 1, "*"),
    "@annually": (0, 0, 1, 1, "*"),
    "@monthly": (0, 0, 1, "*", "*"),
    "@weekly": (0, 0, "*", "*", 0),
    "@daily": (0, 0, "*", "*", "*"),
    "@midnight": (0, 0, "*", "*", "*"),
    "@hourly": (0, "*", "*", "*", "*"),
}


def parse_duration(expr: str) -> str:
    """Convert a duration shorthand to a standard 5-field cron expression.

    Supported formats:
    - ``Ns`` / ``Nm`` / ``Nh`` / ``Nd`` / ``Nw`` — seconds/minutes/hours/days/weeks
    - ``@hourly`` / ``@daily`` / ``@weekly`` / ``@monthly`` / ``@yearly``
    - ``*/Nm`` / ``*/Nh`` — step notation (already cron-like, returned as-is)
    - ``*/5 * * * *`` — already a cron expression, returned as-is

    Raises:
        ValueError: If the format is unrecognised.
    """
    expr = expr.strip()
    if not expr:
        raise ValueError("Empty expression")

    if expr.startswith("*/"):
        return expr  # already a step cron

    # Count whitespace to detect standard 5-field cron
    if len(expr.split()) == 5:
        return expr  # standard cron, return as-is

    # Natural-language aliases
    lower = expr.lower()
    if lower in _DURATION_MAP:
        parts = _DURATION_MAP[lower]
        return " ".join(
            str(v) if isinstance(v, int) else v for v in parts
        )

    # Duration shorthand: number + unit
    if len(expr) >= 2 and expr[-1] in "smhdw" and expr[:-1].isdigit():
        value = int(expr[:-1])
        unit = expr[-1]
        if unit == "s":
            return f"*/{max(1, value // 60 if value % 60 == 0 else 60)} * * * *"
        if unit == "m":
            return f"*/{value} * * * *"
        if unit == "h":
            return f"0 */{value} * * *"
        if unit == "d":
            return f"0 0 */{value} * *"
        if unit == "w":
            return f"0 0 * * {value}"

    raise ValueError(f"Unrecognised cron expression: {expr!r}")


def _parse_field(expr: str, field_index: int) -> set[int]:
    """Parse a single cron field into a set of allowed integers."""
    max_val = MAX_FIELD_VALUE[field_index]
    result: set[int] = set()

    for part in expr.split(","):
        step = 1
        if "/" in part:
            part, step_str = part.split("/", 1)
            step = int(step_str)

        if part == "*":
            start, end = 0, max_val
        elif "-" in part:
            start_str, end_str = part.split("-", 1)
            start, end = int(start_str), int(end_str)
        else:
            val = int(part)
            if val < 0 or val > max_val:
                raise ValueError(f"Value {val} out of range for field {field_index}")
            result.add(val)
            continue

        for v in range(start, end + 1, step):
            if 0 <= v <= max_val:
                result.add(v)

    return result


def parse_cron(expression: str) -> list[set[int]]:
    """Parse a 5-field cron expression into a list of 5 sets.

    Returns [minutes, hours, days_of_month, months, days_of_week].
    """
    fields = expression.strip().split()
    if len(fields) != 5:
        raise ValueError(f"Expected 5 cron fields, got {len(fields)}: {expression!r}")

    return [_parse_field(f, i) for i, f in enumerate(fields)]


def cron_matches(expression: str, dt: datetime | None = None) -> bool:
    """Return True if *dt* (default: now) matches the cron expression."""
    dt = dt or datetime.now()
    fields = parse_cron(expression)
    minute, hour, dom, month, dow = fields

    # day-of-month and day-of-week are OR'd in standard cron
    dom_match = dt.day in dom
    dow_match = dt.weekday() in dow  # Monday=0 .. Sunday=6
    day_ok = dom_match or dow_match if (dom != {*range(0, 32)} or dow != {*range(0, 7)}) else True

    return (
        dt.minute in minute
        and dt.hour in hour
        and dt.month in month
        and day_ok
    )


@dataclass
class CronJob:
    """A scheduled job with its cron expression and callback."""

    name: str
    expression: str
    callback: Callable[[], Any]
    enabled: bool = True
    last_run: float | None = None
    fields: list[set[int]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.fields = parse_cron(self.expression)


class CronScheduler:
    """Runs cron jobs in a background thread.

    Features:
    - Standard 5-field cron expressions.
    - Per-minute dedup via ``_just_ran``.
    - Cross-instance file locks (flock) to prevent double-firing
      in multi-process deployments.
    - Persistent run history (JSON) with configurable retention.
    """

    def __init__(
        self,
        tick_interval: int = 30,
        lock_dir: str | Path | None = None,
        history_dir: str | Path | None = None,
        history_retention_days: int = 7,
    ) -> None:
        self._jobs: dict[str, CronJob] = {}
        self._tick_interval = tick_interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._lock_dir = (
            Path(lock_dir)
            if lock_dir
            else Path(tempfile.gettempdir()) / "Zeloo-cron-locks"
        )
        self._history_dir = (
            Path(history_dir)
            if history_dir
            else Path.home() / ".Zeloo" / "cron-history"
        )
        self._history_retention_days = history_retention_days
        self._proc_locks: dict[str, Any] = {}
        self._history_dir.mkdir(parents=True, exist_ok=True)
        self._lock_dir.mkdir(parents=True, exist_ok=True)

    def add_job(self, name: str, expression: str, callback: Callable[[], Any]) -> None:
        """Register a cron job.

        ``expression`` can be any of:
        - Standard 5-field cron: ``*/5 * * * *``
        - Duration shorthand: ``30m`` / ``2h`` / ``1d`` / ``1w``
        - Natural language alias: ``@hourly`` / ``@daily`` / ``@weekly``
        - Step notation: ``*/10 * * * *``
        The scheduler auto-detects the format and converts to standard cron.
        """
        with self._lock:
            try:
                cron_expr = parse_duration(expression)
                if cron_expr != expression:
                    logger.info("Cron expression '%s' auto-converted to '%s'", expression, cron_expr)
                expression = cron_expr
            except ValueError:
                logger.warning("Could not parse cron expression '%s' — registering as-is", expression)
            self._jobs[name] = CronJob(name=name, expression=expression, callback=callback)
            logger.info("Cron job registered: %s (%s)", name, expression)

    def remove_job(self, name: str) -> None:
        """Remove a cron job by name."""
        with self._lock:
            self._jobs.pop(name, None)

    # ── File lock (cross-process dedup) ─────────────────────────────────

    def _acquire_lock(self, job_name: str) -> bool:
        """Acquire an exclusive flock for *job_name*. Returns True if acquired."""
        if fcntl is None:
            return True  # Skip on Windows (no-op)
        lock_path = self._lock_dir / f"{job_name}.lock"
        try:
            fh = open(lock_path, "w")
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._proc_locks[job_name] = fh
            return True
        except OSError:
            return False

    def _release_lock(self, job_name: str) -> None:
        """Release the flock for *job_name*."""
        fh = self._proc_locks.pop(job_name, None)
        if fh is not None:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                fh.close()
            except Exception:  # noqa: BLE001
                pass

    # ── Persistent run history ─────────────────────────────────────────

    def _history_path(self, job_name: str) -> Path:
        return self._history_dir / f"{job_name}.json"

    def _load_history(self, job_name: str) -> list[dict[str, Any]]:
        path = self._history_path(job_name)
        if not path.exists():
            return []
        try:
            with open(path) as fh:
                return json.load(fh)
        except Exception:  # noqa: BLE001
            return []

    def _save_history(self, job_name: str, history: list[dict[str, Any]]) -> None:
        path = self._history_path(job_name)
        try:
            with open(path, "w") as fh:
                json.dump(history, fh, indent=2)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to save cron history for %s: %s", job_name, exc)

    def _prune_history(self, job_name: str) -> None:
        cutoff = datetime.now().timestamp() - self._history_retention_days * 86400
        history = [h for h in self._load_history(job_name) if h.get("ts", 0) > cutoff]
        self._save_history(job_name, history)

    def get_history(self, job_name: str) -> list[dict[str, Any]]:
        """Return the run history for *job_name*."""
        return self._load_history(job_name)

    def list_jobs(self) -> list[dict[str, Any]]:
        """Return a summary of all registered jobs."""
        with self._lock:
            return [
                {
                    "name": j.name,
                    "expression": j.expression,
                    "enabled": j.enabled,
                    "last_run": j.last_run,
                }
                for j in self._jobs.values()
            ]

    def start(self) -> None:
        """Start the scheduler background thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="cron-scheduler"
        )
        self._thread.start()
        logger.info("Cron scheduler started (tick=%ds)", self._tick_interval)

    def stop(self) -> None:
        """Stop the scheduler background thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Cron scheduler stopped")

    def _run_loop(self) -> None:
        """Tick loop: check jobs every tick_interval seconds."""
        while not self._stop_event.wait(self._tick_interval):
            now = datetime.now()
            with self._lock:
                jobs = list(self._jobs.values())
            for job in jobs:
                if not job.enabled:
                    continue
                if self._matches(job, now) and not self._just_ran(job, now):
                    if not self._acquire_lock(job.name):
                        logger.debug("Cron job %s skipped — lock held by another process", job.name)
                        continue
                    try:
                        job.callback()
                        job.last_run = now.timestamp()
                        entry = {
                            "ts": now.timestamp(),
                            "iso": now.isoformat(),
                            "expression": job.expression,
                            "success": True,
                        }
                        history = self._load_history(job.name)
                        history.append(entry)
                        self._save_history(job.name, history)
                        self._prune_history(job.name)
                    except Exception as exc:
                        logger.exception("Cron job %s failed", job.name)
                        entry = {
                            "ts": now.timestamp(),
                            "iso": now.isoformat(),
                            "expression": job.expression,
                            "success": False,
                            "error": repr(exc),
                        }
                        history = self._load_history(job.name)
                        history.append(entry)
                        self._save_history(job.name, history)
                    finally:
                        self._release_lock(job.name)

    @staticmethod
    def _matches(job: CronJob, dt: datetime) -> bool:
        minute, hour, dom, month, dow = job.fields
        dom_match = dt.day in dom
        dow_match = dt.weekday() in dow
        day_ok = (
            dom_match or dow_match
            if (dom != set(range(0, 32)) or dow != set(range(0, 7)))
            else True
        )
        return dt.minute in minute and dt.hour in hour and dt.month in month and day_ok

    @staticmethod
    def _just_ran(job: CronJob, dt: datetime) -> bool:
        """Avoid double-firing within the same minute."""
        if job.last_run is None:
            return False
        last = datetime.fromtimestamp(job.last_run)
        return (
            last.year == dt.year and last.month == dt.month
            and last.day == dt.day and last.hour == dt.hour
            and last.minute == dt.minute
        )
