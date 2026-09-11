"""Forward :class:`agent.audit_log.AuditEvent` records to Langfuse.

The local audit log gives us tamper-evident on-disk records. Langfuse
gives us searchable, queryable, multi-tenant observability. This bridge
keeps both in sync without coupling either module:

  * :class:`AuditObserver` is a callable observer that maps an
    :class:`AuditEvent` to one Langfuse span.
  * :func:`install_default_observer` wires it up to the default
    :class:`AuditLog` and uses :func:`langfuse_integration.get_tracer`
    as the destination — but the tracer is injected, so tests can
    substitute a mock.
  * :func:`event_to_span_payload` is pure and unit-tested so the
    severity / level mapping stays correct.

Severity mapping (audit event ``outcome`` → Langfuse ``level``):

  * ``outcome == "blocked"`` → ``level = WARNING``
  * ``outcome == "error"``   → ``level = ERROR``
  * ``outcome == "ok"``      → ``level = DEFAULT``

A subset of event kinds are tagged with a higher severity than their
``outcome`` implies (e.g. ``estop_triggered`` always ERROR, even when
``outcome == "ok"``, because the event itself is high-impact).
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from agent.audit_log import AuditEvent, get_default_audit_log

if TYPE_CHECKING:
    from agent.langfuse_integration import LangfuseTracer

logger = logging.getLogger(__name__)


# ── Span-level mapping ──────────────────────────────────────────

# Events whose mere occurrence is an ERROR regardless of outcome.
_HIGH_IMPACT_KINDS: frozenset[str] = frozenset(
    {
        "estop_triggered",
        "webhook_failed",
        "llm_output_secret_alert",
        "tool_output_secret_found",
        "file_read_secret_found",
        "system_prompt_secret_found",
        "audit_chain_tampered",  # reserved for future use
    }
)

# Events that are always benign — keep level=DEFAULT unless outcome says otherwise.
# (Currently empty; kept as an explicit extension point.)


def event_to_span_payload(event: AuditEvent) -> dict[str, Any]:
    """Convert an :class:`AuditEvent` to a Langfuse-friendly payload.

    Returns a dict with:

      * ``name``     — the Langfuse span display name
      * ``level``    — ``DEFAULT`` / ``WARNING`` / ``ERROR``
      * ``status``   — ``SUCCESS`` / ``ERROR`` (Langfuse convention)
      * ``metadata`` — copy of the event's structured details

    The mapping is deterministic and depends only on *event fields*, so
    it is safe to unit-test without touching the network.
    """
    outcome = (event.outcome or "").strip().lower()
    kind = event.kind or "unknown"
    level = _resolve_level(kind=kind, outcome=outcome)

    return {
        "name": f"audit:{kind}",
        "level": level,
        "status": "ERROR" if level == "ERROR" else "SUCCESS",
        "metadata": {
            "audit_kind": kind,
            "audit_actor": event.actor,
            "audit_resource": event.resource,
            "audit_outcome": outcome,
            "audit_seq": event.seq,
            "audit_prev_hash": event.prev_hash,
            "audit_hash": event.hash,
            "audit_ts": event.ts,
            **dict(event.detail or {}),
        },
    }


def _resolve_level(*, kind: str, outcome: str) -> str:
    if kind in _HIGH_IMPACT_KINDS:
        return "ERROR"
    if outcome == "error":
        return "ERROR"
    if outcome == "blocked":
        return "WARNING"
    return "DEFAULT"


# ── Observer ────────────────────────────────────────────────────


class AuditObserver:
    """Callable observer that forwards events to a Langfuse tracer."""

    def __init__(
        self,
        tracer: LangfuseTracer | None = None,
        *,
        trace_name: str = "Zeloo-audit",
        # If True, events whose kind is not interesting (per
        # ``sample_rate``) are dropped before reaching the tracer.
        sample_rate: float = 1.0,
    ) -> None:
        if sample_rate < 0.0 or sample_rate > 1.0:
            raise ValueError("sample_rate must be in [0.0, 1.0]")
        self._tracer = tracer  # may be None at install time; resolved at call time
        self._trace_name = trace_name
        self._sample_rate = sample_rate
        self._lock = threading.Lock()
        self._stats = {
            "events": 0,
            "forwarded": 0,
            "dropped_no_tracer": 0,
            "dropped_sampled": 0,
            "tracer_errors": 0,
        }

    def set_tracer(self, tracer: LangfuseTracer | None) -> None:
        """Replace the tracer (e.g. after a config reload)."""
        with self._lock:
            self._tracer = tracer

    # ── Observer callback API ──────────────────────────────────

    def __call__(self, event: AuditEvent) -> None:
        self.forward(event)

    def forward(self, event: AuditEvent) -> None:
        with self._lock:
            self._stats["events"] += 1
            tracer = self._tracer or _auto_tracer()
            if tracer is None or not getattr(tracer, "enabled", False):
                self._stats["dropped_no_tracer"] += 1
                return
            if self._sample_rate < 1.0:
                import random

                if random.random() > self._sample_rate:
                    self._stats["dropped_sampled"] += 1
                    return

        payload = event_to_span_payload(event)
        try:
            # Wrap each event in its own trace so it's independently
            # queryable in the Langfuse UI; use the event hash as a
            # stable trace id so re-runs don't duplicate.
            with tracer.trace(
                self._trace_name,
                metadata={"audit_kind": event.kind, "audit_seq": event.seq},
            ) as ctx:
                tracer.log_tool_call(
                    trace_id=ctx.trace_id,
                    tool_name=payload["name"],
                    success=(payload["status"] != "ERROR"),
                    metadata=payload["metadata"],
                    level=payload["level"],
                )
            with self._lock:
                self._stats["forwarded"] += 1
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._stats["tracer_errors"] += 1
            logger.warning("audit_observability: tracer call failed: %s", exc)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return dict(self._stats)


# ── Helpers ──────────────────────────────────────────────────────


def _auto_tracer() -> LangfuseTracer | None:
    """Try to pick up the default tracer lazily (avoid import cycles)."""
    try:
        from agent.langfuse_integration import get_tracer

        return get_tracer()
    except Exception:  # noqa: BLE001
        return None


# ── Default install / uninstall ──────────────────────────────────


_installed_lock = threading.Lock()
_installed_observer: AuditObserver | None = None


def install_default_observer(
    *,
    tracer: LangfuseTracer | None = None,
    sample_rate: float = 1.0,
    trace_name: str = "Zeloo-audit",
) -> AuditObserver:
    """Wire up the default :class:`AuditLog` to forward events to Langfuse.

    Idempotent: repeats return the existing observer instead of
    stacking duplicates.

    Args:
        tracer: Explicit tracer to use. ``None`` falls back to
            :func:`langfuse_integration.get_tracer`.
        sample_rate: 0.0 - 1.0 fraction of events to forward
            (default 1.0 = all). Useful for high-throughput deployments.
        trace_name: Display name for the parent trace that each event
            spans into.
    """
    global _installed_observer
    with _installed_lock:
        if _installed_observer is not None:
            if tracer is not None:
                _installed_observer.set_tracer(tracer)
            return _installed_observer

        observer = AuditObserver(
            tracer=tracer,
            sample_rate=sample_rate,
            trace_name=trace_name,
        )
        get_default_audit_log().attach_observer(observer)
        _installed_observer = observer
        logger.info(
            "audit_observability: installed default observer (sample_rate=%.2f)",
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
        try:
            get_default_audit_log().detach_observer(observer)
        except Exception:  # noqa: BLE001
            pass
        return True


def get_installed_observer() -> AuditObserver | None:
    """Return the active default observer (or ``None``)."""
    with _installed_lock:
        return _installed_observer


__all__ = [
    "AuditObserver",
    "event_to_span_payload",
    "get_installed_observer",
    "install_default_observer",
    "uninstall_default_observer",
]
