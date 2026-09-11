"""Forward :class:`agent.error_tracker.ErrorEvent` records to Langfuse.

Companion to :mod:`agent.audit_observability`: where that module wires
the *audit log* (security-relevant events) to Langfuse, this one
wires the *error tracker* (runtime / LLM errors) to the same backend.

Design choices:

  * Pure mapping function (:func:`event_to_span_payload`) so the
    severity / level mapping is unit-testable without touching the
    network.
  * :class:`ErrorObserver` is the fan-out target — instances can be
    attached to one or more :class:`ErrorTracker` instances.
  * :func:`install_default_observer` wires up the module-level
    singleton error tracker (lazily created via ``get_default_error_tracker``)
    to forward to Langfuse.
  * ``sample_rate`` allows high-throughput deployments to forward a
    fraction of events while still writing all of them to the local
    SQLite store.

Severity mapping (``ErrorEvent.severity`` → Langfuse ``level``):

  * ``fatal``   → ``ERROR``
  * ``error``   → ``ERROR``
  * ``warning`` → ``WARNING``
  * ``info``    → ``DEFAULT``

Dedup-aware: when the same fingerprint already exists in the SQLite
store, ``occurrence_count`` is forwarded as a metadata field so
dashboards can surface noisy errors.
"""

from __future__ import annotations

import logging
import random
import threading
from typing import TYPE_CHECKING, Any

from agent.error_tracker import ErrorEvent

if TYPE_CHECKING:
    from agent.langfuse_integration import LangfuseTracer

logger = logging.getLogger(__name__)


# ── Span-level mapping ──────────────────────────────────────────

_SEVERITY_RANK = {"info": 1, "warning": 2, "error": 3, "fatal": 4}


def event_to_span_payload(event: ErrorEvent) -> dict[str, Any]:
    """Convert an :class:`ErrorEvent` to a Langfuse-friendly payload.

    Returns a dict with:

      * ``name``     — the Langfuse span display name
      * ``level``    — ``DEFAULT`` / ``WARNING`` / ``ERROR``
      * ``status``   — ``SUCCESS`` (Langfuse convention) or ``ERROR``
      * ``metadata`` — copy of the structured details

    The mapping is deterministic and depends only on *event fields*, so
    it is safe to unit-test without touching the network.
    """
    severity = (event.severity or "error").strip().lower()
    level = _resolve_level(severity)
    return {
        "name": f"error:{event.category or 'unknown'}",
        "level": level,
        "status": "ERROR" if level == "ERROR" else "SUCCESS",
        "metadata": {
            "error_fingerprint": event.fingerprint,
            "error_category": event.category,
            "error_severity": severity,
            "error_message": event.message,
            "occurrence_count": event.occurrence_count,
            "first_seen": event.first_seen,
            "last_seen": event.last_seen,
            "session_id": event.session_id,
            "provider": event.provider,
            "model": event.model,
            "context": event.context,
            "has_stack_trace": bool(event.stack_trace),
        },
    }


def _resolve_level(severity: str) -> str:
    if severity not in _SEVERITY_RANK:
        # Unknown severity → treat as error.
        return "ERROR"
    if severity in ("error", "fatal"):
        return "ERROR"
    if severity == "warning":
        return "WARNING"
    return "DEFAULT"


# ── Observer ────────────────────────────────────────────────────


#: Default cap on the stack trace preview sent to Langfuse.
#: Override via the ``stack_trace_max_chars`` constructor argument on
#: :class:`ErrorObserver` (or the matching ``install_default_observer`` kwarg).
DEFAULT_STACK_TRACE_MAX_CHARS = 1000


class ErrorObserver:
    """Callable observer that forwards :class:`ErrorEvent` to a Langfuse tracer.

    Attach to one or more :class:`agent.error_tracker.ErrorTracker`
    instances via :meth:`ErrorTracker.attach_observer`.
    """

    def __init__(
        self,
        tracer: LangfuseTracer | None = None,
        *,
        trace_name: str = "Zeloo-errors",
        sample_rate: float = 1.0,
        stack_trace_max_chars: int = DEFAULT_STACK_TRACE_MAX_CHARS,
    ) -> None:
        if sample_rate < 0.0 or sample_rate > 1.0:
            raise ValueError("sample_rate must be in [0.0, 1.0]")
        if stack_trace_max_chars < 0:
            raise ValueError("stack_trace_max_chars must be >= 0")
        self._tracer = tracer  # may be None at install time
        self._trace_name = trace_name
        self._sample_rate = sample_rate
        # Cap on the stack trace preview sent to Langfuse. The full
        # trace is always available in the local SQLite store; this
        # only bounds the size of the Langfuse metadata payload.
        self._stack_trace_max_chars = int(stack_trace_max_chars)
        self._lock = threading.Lock()
        self._stats = {
            "events": 0,
            "forwarded": 0,
            "dropped_no_tracer": 0,
            "dropped_sampled": 0,
            "tracer_errors": 0,
        }

    def set_tracer(self, tracer: LangfuseTracer | None) -> None:
        with self._lock:
            self._tracer = tracer

    # ── Observer callback API ──────────────────────────────────

    def __call__(self, event: ErrorEvent) -> None:
        self.forward(event)

    def forward(self, event: ErrorEvent) -> None:
        with self._lock:
            self._stats["events"] += 1
            tracer = self._tracer or _auto_tracer()
            if tracer is None or not getattr(tracer, "enabled", False):
                self._stats["dropped_no_tracer"] += 1
                return
            if self._sample_rate < 1.0 and random.random() > self._sample_rate:
                self._stats["dropped_sampled"] += 1
                return

        payload = event_to_span_payload(event)
        try:
            with tracer.trace(
                self._trace_name,
                metadata={
                    "error_fingerprint": event.fingerprint,
                    "error_category": event.category,
                },
            ) as ctx:
                # Include stack trace truncated in metadata (capped to
                # avoid blowing up Langfuse). The full trace is in the
                # local SQLite store for forensic drill-down. The cap is
                # configurable via ``stack_trace_max_chars`` so callers
                # can tune the metadata payload size for their Langfuse
                # plan limits.
                metadata = dict(payload["metadata"])
                if event.stack_trace and self._stack_trace_max_chars > 0:
                    metadata["stack_trace_preview"] = event.stack_trace[
                        : self._stack_trace_max_chars
                    ]
                    metadata["stack_trace_preview_truncated"] = (
                        len(event.stack_trace) > self._stack_trace_max_chars
                    )

                tracer.log_tool_call(
                    trace_id=ctx.trace_id,
                    tool_name=payload["name"],
                    success=(payload["status"] != "ERROR"),
                    metadata=metadata,
                    level=payload["level"],
                    status_message=event.message[:200] or None,
                )
            with self._lock:
                self._stats["forwarded"] += 1
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._stats["tracer_errors"] += 1
            logger.warning("error_observability: tracer call failed: %s", exc)

    def set_stack_trace_max_chars(self, value: int) -> None:
        """Update the stack-trace preview cap at runtime.

        ``value < 0`` is rejected. ``0`` disables the preview entirely
        (only the boolean flag ``has_stack_trace`` survives).
        """
        if value < 0:
            raise ValueError("stack_trace_max_chars must be >= 0")
        with self._lock:
            self._stack_trace_max_chars = int(value)

    def stats(self) -> dict[str, int]:
        with self._lock:
            stats = dict(self._stats)
            stats["stack_trace_max_chars"] = self._stack_trace_max_chars
            return stats


# ── Helpers ──────────────────────────────────────────────────────


def _auto_tracer() -> LangfuseTracer | None:
    try:
        from agent.langfuse_integration import get_tracer

        return get_tracer()
    except Exception:  # noqa: BLE001
        return None


def _get_default_error_tracker():
    """Lazy-construct a process-wide :class:`ErrorTracker` if needed.

    The default tracker writes to the shared SQLite state DB so other
    subsystems (turn finalizer, background review, etc.) see the same
    rows.
    """
    try:
        from agent.error_tracker import ErrorTracker
    except Exception:  # noqa: BLE001
        return None
    if not hasattr(_get_default_error_tracker, "_tracker"):
        _get_default_error_tracker._tracker = ErrorTracker()  # type: ignore[attr-defined]
    return _get_default_error_tracker._tracker  # type: ignore[attr-defined]


# ── Default install / uninstall ──────────────────────────────────


_installed_lock = threading.Lock()
_installed_observer: ErrorObserver | None = None


def install_default_observer(
    *,
    tracer: LangfuseTracer | None = None,
    tracker: Any | None = None,
    sample_rate: float = 1.0,
    trace_name: str = "Zeloo-errors",
    stack_trace_max_chars: int = DEFAULT_STACK_TRACE_MAX_CHARS,
) -> ErrorObserver | None:
    """Wire up an :class:`ErrorTracker` to forward events to Langfuse.

    Idempotent: repeats return the existing observer. Returns ``None``
    when no tracker could be resolved.

    Args:
        tracer: Langfuse tracer. ``None`` falls back to the
            process-wide tracer.
        tracker: Explicit :class:`ErrorTracker` to attach to. ``None``
            falls back to a lazily-constructed module-level tracker.
        sample_rate: Fraction of events to forward (0.0-1.0).
        trace_name: Display name for the parent Langfuse trace.
        stack_trace_max_chars: Maximum number of stack trace chars
            forwarded to Langfuse as ``metadata.stack_trace_preview``.
            Full traces are always preserved locally; ``0`` disables
            the preview entirely. Tuned per Langfuse plan limits.
    """
    global _installed_observer
    with _installed_lock:
        if _installed_observer is not None:
            if tracer is not None:
                _installed_observer.set_tracer(tracer)
            if stack_trace_max_chars != DEFAULT_STACK_TRACE_MAX_CHARS:
                # Allow runtime tuning of the installed observer.
                _installed_observer.set_stack_trace_max_chars(stack_trace_max_chars)
            return _installed_observer

        if tracker is None:
            tracker = _get_default_error_tracker()
        if tracker is None:
            logger.warning(
                "error_observability: no ErrorTracker available; observer not installed"
            )
            return None

        observer = ErrorObserver(
            tracer=tracer,
            sample_rate=sample_rate,
            trace_name=trace_name,
            stack_trace_max_chars=stack_trace_max_chars,
        )
        tracker.attach_observer(observer)
        _installed_observer = observer
        # Stash the tracker so uninstall can detach without
        # re-resolving a fresh default tracker.
        _installed_observer._bound_tracker = tracker  # type: ignore[attr-defined]
        logger.info(
            "error_observability: installed default observer (sample_rate=%.2f)",
            sample_rate,
        )
        return observer


def uninstall_default_observer() -> bool:
    """Tear down the default observer; returns True if one was removed."""
    global _installed_observer
    with _installed_lock:
        observer = _installed_observer
        _installed_observer = None
        if observer is None:
            return False
        tracker = getattr(observer, "_bound_tracker", None) or _get_default_error_tracker()
        if tracker is not None:
            try:
                tracker.detach_observer(observer)
            except Exception:  # noqa: BLE001
                pass
        return True


def get_installed_observer() -> ErrorObserver | None:
    with _installed_lock:
        return _installed_observer


__all__ = [
    "ErrorObserver",
    "event_to_span_payload",
    "get_installed_observer",
    "install_default_observer",
    "uninstall_default_observer",
]
