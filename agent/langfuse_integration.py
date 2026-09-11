"""Langfuse tracing integration for Zeloo Agent.

LLM observability via direct HTTP calls to Langfuse API.
Requires: LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST (optional)
"""

from __future__ import annotations

import atexit
import os
import queue
import threading
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx


DEFAULT_HOST = "https://cloud.langfuse.com"
BATCH_SIZE = 100
FLUSH_INTERVAL_SECONDS = 5.0


@dataclass
class TraceContext:
    """Context for an active trace."""

    trace_id: str
    name: str
    start_time: datetime
    metadata: dict[str, Any] | None
    end_time: datetime | None = None
    tags: list[str] = field(default_factory=list)
    user_id: str | None = None
    version: str | None = None


@dataclass
class LLMCallEvent:
    """Represents an LLM call event."""

    id: str
    trace_id: str
    name: str
    start_time: datetime
    end_time: datetime
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost: float | None
    prompt_tokens_cost: float | None
    completion_tokens_cost: float | None
    status: str
    model_parameters: dict[str, Any] | None
    metadata: dict[str, Any] | None
    level: str = "DEFAULT"
    status_message: str | None = None


@dataclass
class ToolCallEvent:
    """Represents a tool call event."""

    id: str
    trace_id: str
    name: str
    start_time: datetime
    end_time: datetime
    success: bool
    metadata: dict[str, Any] | None
    status_message: str | None = None
    level: str = "DEFAULT"


@dataclass
class TraceEvent:
    """Represents a trace event (generation or span)."""

    id: str
    trace_id: str
    name: str
    start_time: datetime
    end_time: datetime
    event_type: str
    metadata: dict[str, Any] | None
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    status: str | None = None
    status_message: str | None = None
    level: str = "DEFAULT"
    parent_observation_id: str | None = None


class LangfuseClient:
    """Lightweight HTTP client for Langfuse API."""

    def __init__(
        self,
        public_key: str,
        secret_key: str,
        host: str = DEFAULT_HOST,
    ) -> None:
        self.public_key = public_key
        self.secret_key = secret_key
        self.host = host.rstrip("/")
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            import httpx
            self._client = httpx.Client(
                headers={
                    "Authorization": f"Bearer {self.secret_key}",
                    "Content-Type": "application/json",
                    "X-Sdk-Lang": "python",
                },
                timeout=30.0,
            )
        return self._client

    def _make_url(self, path: str) -> str:
        return f"{self.host}/api/public{path}"

    def create_trace(
        self,
        trace_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": trace_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        if metadata:
            payload["metadata"] = metadata
        response = self.client.post(self._make_url("/traces"), json=payload)
        response.raise_for_status()
        return response.json()

    def create_generation(
        self,
        trace_id: str,
        generation_id: str,
        name: str,
        start_time: datetime,
        end_time: datetime,
        model: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        cost: float | None,
        prompt_tokens_cost: float | None,
        completion_tokens_cost: float | None,
        status: str,
        model_parameters: dict[str, Any] | None,
        metadata: dict[str, Any] | None,
        level: str,
        status_message: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": generation_id,
            "trace_id": trace_id,
            "name": name,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "status": status,
            "level": level,
        }
        if cost is not None:
            payload["cost"] = cost
        if prompt_tokens_cost is not None:
            payload["prompt_tokens_cost"] = prompt_tokens_cost
        if completion_tokens_cost is not None:
            payload["completion_tokens_cost"] = completion_tokens_cost
        if model_parameters:
            payload["model_parameters"] = model_parameters
        if metadata:
            payload["metadata"] = metadata
        if status_message:
            payload["status_message"] = status_message

        response = self.client.post(
            self._make_url("/generations"),
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    def create_span(
        self,
        trace_id: str,
        span_id: str,
        name: str,
        start_time: datetime,
        end_time: datetime,
        metadata: dict[str, Any] | None,
        input_data: dict[str, Any] | None,
        output_data: dict[str, Any] | None,
        status: str | None,
        status_message: str | None,
        level: str,
        parent_observation_id: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": span_id,
            "trace_id": trace_id,
            "name": name,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "type": "SPAN",
            "level": level,
        }
        if metadata:
            payload["metadata"] = metadata
        if input_data:
            payload["input"] = input_data
        if output_data:
            payload["output"] = output_data
        if status:
            payload["status"] = status
        if status_message:
            payload["status_message"] = status_message
        if parent_observation_id:
            payload["parent_observation_id"] = parent_observation_id

        response = self.client.post(
            self._make_url("/spans"),
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None


class LangfuseTracer:
    """Record LLM calls, tool calls, and traces to Langfuse."""

    def __init__(
        self,
        public_key: str | None = None,
        secret_key: str | None = None,
        host: str | None = None,
        enabled: bool = True,
    ) -> None:
        self.public_key = public_key or os.environ.get("LANGFUSE_PUBLIC_KEY", "")
        self.secret_key = secret_key or os.environ.get("LANGFUSE_SECRET_KEY", "")
        self.host = host or os.environ.get("LANGFUSE_HOST", DEFAULT_HOST)
        self.enabled = enabled and bool(self.public_key) and bool(self.secret_key)

        self._client: LangfuseClient | None = None
        self._event_queue: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue(
            maxsize=10000,
        )
        self._worker_thread: threading.Thread | None = None
        self._shutdown_event = threading.Event()
        self._traces: dict[str, TraceContext] = {}
        self._lock = threading.Lock()

        if self.enabled:
            self._start_worker()
            atexit.register(self.flush)

    @property
    def client(self) -> LangfuseClient | None:
        if self._client is None and self.enabled:
            self._client = LangfuseClient(
                public_key=self.public_key,
                secret_key=self.secret_key,
                host=self.host,
            )
        return self._client

    def _start_worker(self) -> None:
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="langfuse-flush-worker",
        )
        self._worker_thread.start()

    def _worker_loop(self) -> None:
        batch: list[tuple[str, dict[str, Any]]] = []
        last_flush = time.monotonic()

        while not self._shutdown_event.is_set():
            try:
                event = self._event_queue.get(timeout=0.1)
                batch.append(event)

                should_flush = (
                    len(batch) >= BATCH_SIZE
                    or (time.monotonic() - last_flush) >= FLUSH_INTERVAL_SECONDS
                )

                if should_flush and batch:
                    self._flush_batch(batch)
                    batch = []
                    last_flush = time.monotonic()

            except queue.Empty:
                if batch and (time.monotonic() - last_flush) >= FLUSH_INTERVAL_SECONDS:
                    self._flush_batch(batch)
                    batch = []
                    last_flush = time.monotonic()

    def _flush_batch(self, batch: list[tuple[str, dict[str, Any]]]) -> None:
        if not self.client:
            return

        grouped: dict[str, list[dict[str, Any]]] = {}
        for endpoint, payload in batch:
            if endpoint not in grouped:
                grouped[endpoint] = []
            grouped[endpoint].append(payload)

        for endpoint, payloads in grouped.items():
            for payload in payloads:
                try:
                    url = self.client._make_url(endpoint)
                    self.client.client.post(url, json=payload)
                except Exception:
                    pass

    @contextmanager
    def trace(
        self,
        name: str,
        metadata: dict[str, Any] | None = None,
    ) -> Generator[TraceContext, None, None]:
        """Start a new trace, returns a context manager."""
        trace_id = str(uuid.uuid4())
        start_time = datetime.now(UTC)
        context = TraceContext(
            trace_id=trace_id,
            name=name,
            start_time=start_time,
            metadata=metadata,
        )

        with self._lock:
            self._traces[trace_id] = context

        try:
            if self.enabled and self.client:
                try:
                    self.client.create_trace(trace_id, metadata)
                except Exception:
                    pass
            yield context
        finally:
            context.end_time = datetime.now(UTC)
            with self._lock:
                self._traces.pop(trace_id, None)

    def log_llm_call(
        self,
        trace_id: str | None,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost: float | None = None,
        latency_ms: float | None = None,
        metadata: dict[str, Any] | None = None,
        prompt_tokens_cost: float | None = None,
        completion_tokens_cost: float | None = None,
        name: str = "llm_call",
        model_parameters: dict[str, Any] | None = None,
        status: str = "SUCCESS",
        status_message: str | None = None,
        level: str = "DEFAULT",
    ) -> str | None:
        """Record an LLM API call."""
        if not self.enabled:
            return None

        generation_id = str(uuid.uuid4())
        total_tokens = input_tokens + output_tokens

        if latency_ms is not None:
            end_time = datetime.now(UTC)
            start_time = datetime.fromtimestamp(
                end_time.timestamp() - (latency_ms / 1000),
                tz=UTC,
            )
        else:
            end_time = datetime.now(UTC)
            start_time = end_time

        event = LLMCallEvent(
            id=generation_id,
            trace_id=trace_id or "",
            name=name,
            start_time=start_time,
            end_time=end_time,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost=cost,
            prompt_tokens_cost=prompt_tokens_cost,
            completion_tokens_cost=completion_tokens_cost,
            status=status,
            model_parameters=model_parameters,
            metadata=metadata,
            level=level,
            status_message=status_message,
        )

        self._queue_event(
            "/generations",
            {
                "id": event.id,
                "trace_id": event.trace_id,
                "name": event.name,
                "start_time": event.start_time.isoformat(),
                "end_time": event.end_time.isoformat(),
                "model": event.model,
                "input_tokens": event.input_tokens,
                "output_tokens": event.output_tokens,
                "total_tokens": event.total_tokens,
                "status": event.status,
                "level": event.level,
                **({} if event.cost is None else {"cost": event.cost}),
                **(
                    {}
                    if event.prompt_tokens_cost is None
                    else {"prompt_tokens_cost": event.prompt_tokens_cost}
                ),
                **(
                    {}
                    if event.completion_tokens_cost is None
                    else {"completion_tokens_cost": event.completion_tokens_cost}
                ),
                **(
                    {}
                    if event.model_parameters is None
                    else {"model_parameters": event.model_parameters}
                ),
                **({} if event.metadata is None else {"metadata": event.metadata}),
                **(
                    {}
                    if event.status_message is None
                    else {"status_message": event.status_message}
                ),
            },
        )

        return generation_id

    def log_tool_call(
        self,
        trace_id: str | None,
        tool_name: str,
        duration_ms: float | None = None,
        success: bool = True,
        metadata: dict[str, Any] | None = None,
        name: str | None = None,
        status_message: str | None = None,
        level: str = "DEFAULT",
    ) -> str | None:
        """Record a tool call."""
        if not self.enabled:
            return None

        span_id = str(uuid.uuid4())
        end_time = datetime.now(UTC)

        if duration_ms is not None:
            start_time = datetime.fromtimestamp(
                end_time.timestamp() - (duration_ms / 1000),
                tz=UTC,
            )
        else:
            start_time = end_time

        display_name = name or tool_name
        status = "SUCCESS" if success else "ERROR"

        self._queue_event(
            "/spans",
            {
                "id": span_id,
                "trace_id": trace_id or "",
                "name": display_name,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "type": "SPAN",
                "status": status,
                "level": level,
                **({} if metadata is None else {"metadata": metadata}),
                **(
                    {}
                    if status_message is None
                    else {"status_message": status_message}
                ),
            },
        )

        return span_id

    def _queue_event(self, endpoint: str, payload: dict[str, Any]) -> None:
        try:
            self._event_queue.put_nowait((endpoint, payload))
        except queue.Full:
            pass

    def flush(self) -> None:
        """Send buffered traces to Langfuse (batch HTTP calls)."""
        if not self.client:
            return

        batch: list[tuple[str, dict[str, Any]]] = []
        while True:
            try:
                event = self._event_queue.get_nowait()
                batch.append(event)
            except queue.Empty:
                break

        if batch:
            self._flush_batch(batch)


# ── Module-level singleton ──────────────────────────────────────

_default_tracer: LangfuseTracer | None = None
_default_tracer_lock = threading.Lock()


def get_tracer() -> LangfuseTracer | None:
    """Return the process-wide :class:`LangfuseTracer` (or ``None`` if disabled).

    Lazy-creates one from the ``LANGFUSE_PUBLIC_KEY`` / ``LANGFUSE_SECRET_KEY``
    environment variables. Returns ``None`` when the env vars are missing or
    ``LANGFUSE_ENABLED=0`` is set, so callers can simply do::

        tracer = get_tracer()
        if tracer and tracer.enabled:
            tracer.log_tool_call(...)
    """
    global _default_tracer
    with _default_tracer_lock:
        if _default_tracer is None:
            enabled = os.environ.get("LANGFUSE_ENABLED", "1").strip().lower() not in (
                "0",
                "false",
                "no",
            )
            _default_tracer = LangfuseTracer(enabled=enabled)
        return _default_tracer


def set_tracer(tracer: LangfuseTracer | None) -> None:
    """Replace the process-wide tracer (or clear with ``None``).

    Used by tests and by tooling that wants a custom tracer (different
    host / mock / disabled). Passing ``None`` clears the singleton so
    the next :func:`get_tracer` call rebuilds it from env vars.
    """
    global _default_tracer
    with _default_tracer_lock:
        if _default_tracer is not None and _default_tracer is not tracer:
            # Best-effort flush before replacement.
            try:
                _default_tracer.flush()
            except Exception:  # noqa: BLE001
                pass
        _default_tracer = tracer
