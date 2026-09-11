"""Distributed tracing — OpenTelemetry-compatible span tracking."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class Span:
    """A single span in a distributed trace."""

    span_id: str
    trace_id: str
    parent_span_id: str | None
    operation_name: str
    service_name: str = "Zeloo"
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    tags: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    status: str = "ok"
    error: str = ""

    def duration_ms(self) -> float:
        if self.ended_at is None:
            return (time.time() - self.started_at) * 1000
        return (self.ended_at - self.started_at) * 1000

    def set_tag(self, key: str, value: Any) -> None:
        self.tags[key] = value

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        self.events.append({
            "name": name,
            "timestamp": time.time(),
            "attributes": attributes or {},
        })

    def record_error(self, error: Exception) -> None:
        self.status = "error"
        self.error = str(error)

    def finish(self) -> None:
        self.ended_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id,
            "operation_name": self.operation_name,
            "service_name": self.service_name,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms(),
            "tags": self.tags,
            "events": self.events,
            "status": self.status,
            "error": self.error,
        }


class Tracer:
    """Lightweight distributed tracer.

    Provides OpenTelemetry-compatible span tracking without
    requiring external dependencies. Spans are stored in memory
    and can be exported to a backend.
    """

    def __init__(self, service_name: str = "Zeloo") -> None:
        self._service_name = service_name
        self._lock = threading.Lock()
        self._spans: list[Span] = []
        self._max_spans = 10_000
        self._active_spans: dict[str, Span] = {}

    def start_span(
        self,
        operation_name: str,
        parent_span: Span | None = None,
        tags: dict[str, Any] | None = None,
    ) -> Span:
        trace_id = (
            parent_span.trace_id
            if parent_span is not None
            else uuid.uuid4().hex
        )
        parent_id = parent_span.span_id if parent_span is not None else None
        span_id = uuid.uuid4().hex[:16]
        span = Span(
            span_id=span_id,
            trace_id=trace_id,
            parent_span_id=parent_id,
            operation_name=operation_name,
            service_name=self._service_name,
            tags=tags or {},
        )
        with self._lock:
            self._active_spans[span_id] = span
        return span

    def end_span(self, span: Span) -> None:
        span.finish()
        with self._lock:
            self._active_spans.pop(span.span_id, None)
            self._spans.append(span)
            if len(self._spans) > self._max_spans:
                self._spans = self._spans[-self._max_spans:]

    @contextmanager
    def span(
        self,
        operation_name: str,
        parent: Span | None = None,
        tags: dict[str, Any] | None = None,
    ) -> Iterator[Span]:
        """Context manager for span lifecycle."""
        s = self.start_span(operation_name, parent, tags)
        try:
            yield s
        except Exception as e:
            s.record_error(e)
            raise
        finally:
            self.end_span(s)

    def get_recent_spans(self, limit: int = 100) -> list[Span]:
        with self._lock:
            return list(self._spans[-limit:])

    def get_traces(self) -> dict[str, list[Span]]:
        traces: dict[str, list[Span]] = {}
        with self._lock:
            for span in self._spans:
                traces.setdefault(span.trace_id, []).append(span)
        for trace_spans in traces.values():
            trace_spans.sort(key=lambda s: s.started_at)
        return traces

    def clear(self) -> None:
        with self._lock:
            self._spans.clear()
            self._active_spans.clear()


__all__ = ["Span", "Tracer"]