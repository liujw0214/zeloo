"""WebSocket bridge for the Zeloo web dashboard.

Subscribes to the core event bus and forwards session / token / cost
events to any connected dashboard clients via the RealtimeEngine.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from zeloo_cli.core.event_bus import Event, EventBus
from zeloo_cli.core.realtime_engine import RealtimeEngine, SubscriptionChannel

logger = logging.getLogger(__name__)

# Default event topics that get fanned out to the dashboard.
DEFAULT_DASHBOARD_EVENTS: tuple[str, ...] = (
    "session.started",
    "session.ended",
    "tool.invoked",
    "token.streamed",
    "cost.recorded",
    "memory.appended",
)


class DashboardRealtimeBridge:
    """Bridges the core event bus to dashboard WebSocket clients.

    The bridge subscribes to a fixed set of Zeloo events. When any of
    those events fire on the bus, the bridge republishes a wrapped
    payload on the ``dashboard`` channel of a :class:`RealtimeEngine`.
    Dashboard WebSocket clients connected via :class:`SubscriptionChannel`
    receive the payload through their own asyncio queue or callback.
    """

    def __init__(
        self,
        event_bus: EventBus,
        engine: RealtimeEngine,
        *,
        events: tuple[str, ...] = DEFAULT_DASHBOARD_EVENTS,
        channel: str = "dashboard",
    ) -> None:
        self._bus = event_bus
        self._engine = engine
        self._events = tuple(events)
        self._channel = channel
        self._subs: list[Any] = []
        self._outbound_tasks: dict[int, asyncio.Task] = {}

    @property
    def channel(self) -> str:
        return self._channel

    async def start(self) -> None:
        """Subscribe to relevant events and forward them to the engine."""
        if self._subs:
            return
        for event_name in self._events:
            try:
                sub = self._bus.subscribe(event_name, self._make_handler(event_name))
                self._subs.append(sub)
                logger.debug("Bridge subscribed to %s", event_name)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("Could not subscribe to %s: %s", event_name, exc)

    async def stop(self) -> None:
        """Tear down all subscriptions."""
        for sub in self._subs:
            try:
                self._bus.unsubscribe(sub)
            except Exception:  # pragma: no cover - defensive
                pass
        self._subs = []

    def _make_handler(self, event_name: str):
        """Return a sync handler that republishes on the engine channel."""

        def _handler(event: Event) -> None:
            payload = {
                "event": event.topic or event_name,
                "payload": event.data if isinstance(event.data, dict) else {"value": event.data},
                "ts": datetime.now().isoformat(),
                "event_id": event.event_id,
                "source": event.source,
            }
            try:
                self._engine.publish(self._channel, payload)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("engine publish failed for %s: %s", event_name, exc)

        return _handler

    def get_stats(self) -> dict[str, Any]:
        engine_stats: dict[str, Any] = {}
        try:
            engine_stats = self._engine.stats()
        except Exception:  # pragma: no cover
            engine_stats = {}
        return {
            "subscriptions": len(self._subs),
            "events": list(self._events),
            "channel": self._channel,
            "engine": engine_stats,
        }


# --------------------------------------------------------------------------- #
# Process-wide bridge accessor.
# --------------------------------------------------------------------------- #

_BRIDGE: DashboardRealtimeBridge | None = None


def set_bridge(bridge: DashboardRealtimeBridge | None) -> None:
    """Register (or clear) the global bridge instance."""
    global _BRIDGE
    _BRIDGE = bridge


def get_bridge() -> DashboardRealtimeBridge:
    """Return the global bridge, raising if it has not been configured."""
    if _BRIDGE is None:
        raise RuntimeError(
            "DashboardRealtimeBridge has not been initialised. "
            "Call set_bridge() during application startup."
        )
    return _BRIDGE


# --------------------------------------------------------------------------- #
# WebSocket connection handler.
# --------------------------------------------------------------------------- #


async def dashboard_ws_handler(websocket: Any) -> None:
    """Handle a dashboard WebSocket connection.

    The expected websocket object exposes:

    * ``send(payload)`` — coroutine or sync callable accepting a dict
    * ``__aiter__`` / ``async for msg in ws`` — incoming messages
      (falling back to ``recv()`` if the iterator protocol is missing)

    The handler:

    1. Subscribes to the engine's ``dashboard`` channel.
    2. Greets the client with a ``hello`` frame.
    3. Pumps outbound events from the engine queue to ``send()``.
    4. Reads inbound messages for ping/pong, ``subscribe`` and
       ``stats`` requests (all currently no-ops, but reserved for
       future extension).
    """
    bridge = get_bridge()
    channel = bridge._engine.subscribe(bridge.channel)  # type: ignore[attr-defined]

    send = _resolve_send(websocket)
    try:
        # Greet the client so the connection is observable in logs/tests.
        await _safe_send(send, {
            "type": "hello",
            "channel": bridge.channel,
            "events": list(bridge._events),
        })

        async def _pump_outbound() -> None:
            while True:
                try:
                    msg = await channel.queue.get()
                except asyncio.CancelledError:
                    raise
                await _safe_send(send, msg)

        outbound_task = asyncio.create_task(_pump_outbound())

        # Inbound loop: handle ping/pong and dynamic channel subscriptions.
        try:
            async for raw in _aiter_incoming(websocket):
                await _handle_inbound(raw, channel, bridge)
        except Exception:  # pragma: no cover - defensive
            logger.debug("dashboard WS inbound loop terminated", exc_info=True)
        finally:
            outbound_task.cancel()
            try:
                await outbound_task
            except (asyncio.CancelledError, Exception):
                pass
    finally:
        try:
            bridge._engine.unsubscribe(channel)  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - defensive
            pass


async def _handle_inbound(raw: Any, channel: SubscriptionChannel,
                          bridge: DashboardRealtimeBridge) -> None:
    """Process a single message from the dashboard client."""
    text = raw if isinstance(raw, str) else getattr(raw, "data", None)
    if text is None:
        return
    try:
        msg = json.loads(text)
    except (ValueError, TypeError):
        return
    if not isinstance(msg, dict):
        return
    mtype = msg.get("type")
    if mtype == "ping":
        return
    if mtype == "subscribe":
        # Currently a single 'dashboard' channel is supported; future
        # work can map arbitrary channels here.
        return
    if mtype == "stats":
        return


def _resolve_send(websocket: Any):
    """Pick the best ``send`` callable exposed by *websocket*."""
    send = getattr(websocket, "send", None)
    if send is None:
        async def _fallback(payload: dict) -> None:
            data = json.dumps(payload)
            send_str = getattr(websocket, "send_str", None)
            if send_str is not None:
                await send_str(data)
            else:
                raise RuntimeError("websocket has no send method")
        return _fallback

    if asyncio.iscoroutinefunction(send):
        async def _shim(payload: dict) -> None:
            await send(payload if not isinstance(payload, str)
                       else json.loads(payload))
        return _shim

    async def _sync_send(payload: dict) -> None:
        send(payload)
    return _sync_send


async def _safe_send(send, payload: dict) -> None:
    try:
        await send(payload)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("dashboard WS send failed: %s", exc)


async def _aiter_incoming(websocket: Any):
    """Yield incoming WebSocket messages as raw text/bytes."""
    aiter = getattr(websocket, "__aiter__", None)
    if aiter is not None:
        async for msg in websocket:
            yield msg
        return
    recv = getattr(websocket, "recv", None)
    if recv is None:
        return
    while True:
        try:
            msg = await recv()
        except (asyncio.CancelledError, StopAsyncIteration):
            return
        if msg is None:
            return
        yield msg


__all__ = [
    "DashboardRealtimeBridge",
    "DEFAULT_DASHBOARD_EVENTS",
    "dashboard_ws_handler",
    "get_bridge",
    "set_bridge",
]
