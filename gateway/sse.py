"""Server-Sent Events (SSE) streaming helpers.

Implements the SSE wire protocol on top of ``asyncio`` and provides
handy generators for:

* Chat completions (``stream_chat``) — emits ``delta`` events shaped like
  the OpenAI streaming response.
* Long-running task progress (``stream_progress``) — emits percentage
  events and a terminal ``done`` event.

All public methods are :class:`collections.abc.AsyncGenerator` instances
so they can be plugged directly into FastAPI / Starlette / aiohttp SSE
endpoints.

Reference: https://html.spec.whatwg.org/multipage/server-sent-events.html
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event dataclass
# ---------------------------------------------------------------------------


@dataclass
class SSEEvent:
    """A single Server-Sent Event.

    Attributes:
        data: Payload string. May be plain text or JSON-encoded.
        event: Optional event ``type`` (defaults to ``message``).
        id: Optional event id used by the client to resume on reconnect.
        retry: Optional reconnection delay hint, in milliseconds.
    """

    data: str
    event: str | None = None
    id: str | None = None
    retry: int | None = None

    def render(self) -> str:
        """Render the event into the SSE wire protocol format."""
        lines: list[str] = []
        if self.event:
            lines.append(f"event: {self.event}")
        if self.id is not None:
            lines.append(f"id: {self.id}")
        if self.retry is not None:
            lines.append(f"retry: {self.retry}")
        # Per spec, multi-line data must be split across multiple "data:" lines.
        for chunk in self.data.split("\n"):
            lines.append(f"data: {chunk}")
        # A blank line terminates the event.
        return "\n".join(lines) + "\n\n"


# ---------------------------------------------------------------------------
# Stream
# ---------------------------------------------------------------------------


@dataclass
class _StreamState:
    """Internal state carried between generator yields."""

    last_heartbeat: float = field(default_factory=time.monotonic)


class SSEStream:
    """Async SSE stream generator with heartbeat support.

    Args:
        heartbeat_seconds: Seconds between synthetic heartbeat comments.
            Set to ``0`` to disable heartbeats.
    """

    def __init__(self, heartbeat_seconds: float = 30.0) -> None:
        """Store the heartbeat interval."""
        self._heartbeat = max(0.0, float(heartbeat_seconds))

    # ── Helpers ──────────────────────────────────────────────────────

    def format_event(self, event: SSEEvent) -> str:
        """Format an :class:`SSEEvent` into the wire protocol string."""
        return event.render()

    @staticmethod
    def format_event_static(
        *,
        data: str,
        event: str | None = None,
        id: str | None = None,
        retry: int | None = None,
    ) -> str:
        """Build a wire-format SSE string without instantiating an SSEEvent.

        Convenience wrapper used by callers that already know their payload
        is plain (no multi-line ``data`` splits required beyond the default).
        """
        return SSEEvent(data=data, event=event, id=id, retry=retry).render()

    @staticmethod
    def _comment(text: str) -> str:
        """Wrap a keep-alive comment in the SSE protocol framing."""
        return f": {text}\n\n"

    async def _maybe_heartbeat(self, state: _StreamState) -> str | None:
        """Return a heartbeat line if the interval has elapsed."""
        if self._heartbeat <= 0:
            return None
        now = time.monotonic()
        if now - state.last_heartbeat >= self._heartbeat:
            state.last_heartbeat = now
            return self._comment("keep-alive")
        return None

    # ── Generic wrapper ──────────────────────────────────────────────

    async def stream(
        self, generator: AsyncGenerator[dict, None]
    ) -> AsyncGenerator[str, None]:
        """Wrap an arbitrary async dict generator into SSE wire output.

        Each yielded dict is converted to an :class:`SSEEvent`. The dict's
        ``"event"`` key (if present) is used as the SSE event type.
        """
        state = _StreamState()
        try:
            async for item in generator:
                heartbeat = await self._maybe_heartbeat(state)
                if heartbeat:
                    yield heartbeat
                payload = item if isinstance(item, SSEEvent) else SSEEvent(
                    data=json.dumps(item, ensure_ascii=False),
                    event=item.get("event") if isinstance(item, dict) else None,
                    id=item.get("id") if isinstance(item, dict) else None,
                )
                yield self.format_event(payload)
        finally:
            # Always emit a final heartbeat so clients know the stream closed cleanly.
            yield self._comment("end-of-stream")

    # ── Chat completions ─────────────────────────────────────────────

    async def stream_chat(
        self,
        prompt: str,
        provider: str = "openai",
        model: str = "gpt-4o",
    ) -> AsyncGenerator[str, None]:
        """Emit an OpenAI-shaped chat-completion stream.

        Splits ``prompt`` into word-sized chunks so the resulting stream
        has the shape expected by OpenAI /v1/chat/completions consumers.
        Provider / model metadata is included in every event.
        """
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        created = int(time.time())
        words = prompt.split() or [""]
        state = _StreamState()
        try:
            for index, word in enumerate(words):
                if self._heartbeat > 0 and (time.monotonic() - state.last_heartbeat) >= self._heartbeat:
                    state.last_heartbeat = time.monotonic()
                    yield self._comment("keep-alive")
                delta = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": word + (" " if index < len(words) - 1 else "")},
                            "finish_reason": None,
                        }
                    ],
                }
                event = SSEEvent(
                    data=json.dumps(delta, ensure_ascii=False),
                    event="message",
                    id=f"{completion_id}-{index}",
                )
                yield self.format_event(event)
                # Cooperative yield so other tasks get a chance to run.
                await asyncio.sleep(0)

            # Final stop event.
            stop = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            yield self.format_event(SSEEvent(data=json.dumps(stop, ensure_ascii=False), event="message"))
        finally:
            yield self._comment(f"end-of-stream provider={provider}")

    # ── Progress ─────────────────────────────────────────────────────

    async def stream_progress(
        self, task_id: str, total_steps: int
    ) -> AsyncGenerator[str, None]:
        """Emit percentage progress events for ``total_steps`` increments.

        Each event payload looks like::

            {"task_id": "...", "step": 3, "total": 10, "percent": 30.0}

        A final ``done`` event is emitted with ``percent == 100.0``.
        """
        if total_steps <= 0:
            raise ValueError("total_steps must be > 0")
        state = _StreamState()
        try:
            for step in range(1, total_steps + 1):
                if self._heartbeat > 0 and (time.monotonic() - state.last_heartbeat) >= self._heartbeat:
                    state.last_heartbeat = time.monotonic()
                    yield self._comment("keep-alive")
                payload = {
                    "task_id": task_id,
                    "step": step,
                    "total": total_steps,
                    "percent": round(step / total_steps * 100.0, 2),
                }
                event_type = "done" if step == total_steps else "progress"
                yield self.format_event(
                    SSEEvent(data=json.dumps(payload), event=event_type, id=f"{task_id}-{step}")
                )
                await asyncio.sleep(0)
        finally:
            yield self._comment(f"end-of-stream task={task_id}")