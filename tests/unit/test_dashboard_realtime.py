"""Tests for the Zeloo dashboard WebSocket realtime bridge."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from zeloo_cli.core.event_bus import EventBus  # noqa: E402
from zeloo_cli.core.realtime_engine import (  # noqa: E402
    RealtimeEngine,
    SubscriptionChannel,
)
from zeloo_cli.web_routers import realtime as rt  # noqa: E402


# --------------------------------------------------------------------------- #
# 1. DashboardRealtimeBridge — basic wiring
# --------------------------------------------------------------------------- #


def test_bridge_initial_state():
    bus = EventBus()
    engine = RealtimeEngine()
    bridge = rt.DashboardRealtimeBridge(bus, engine)
    assert bridge.channel == "dashboard"
    assert bridge.get_stats()["subscriptions"] == 0


def test_bridge_subscribes_to_default_events():
    bus = EventBus()
    engine = RealtimeEngine()
    bridge = rt.DashboardRealtimeBridge(bus, engine)

    async def runner():
        await bridge.start()
        # Force synchronous dispatch on the bus.
        bus.publish("session.started", {"sid": "abc"}, synchronous=True)
        await asyncio.sleep(0)

    asyncio.run(runner())
    stats = bridge.get_stats()
    assert stats["subscriptions"] >= 1
    assert "session.started" in stats["events"]


def test_bridge_forwards_event_payload():
    bus = EventBus()
    engine = RealtimeEngine()
    bridge = rt.DashboardRealtimeBridge(bus, engine)
    sub = engine.subscribe("dashboard")

    async def runner():
        await bridge.start()
        bus.publish("token.streamed", {"delta": "hi"}, synchronous=True)
        await asyncio.sleep(0)

    asyncio.run(runner())

    # Drain the subscriber queue.
    msg = sub.queue.get_nowait()
    assert msg["event"] == "token.streamed"
    assert msg["payload"] == {"delta": "hi"}
    assert "ts" in msg


def test_bridge_stop_unsubscribes():
    bus = EventBus()
    engine = RealtimeEngine()
    bridge = rt.DashboardRealtimeBridge(bus, engine)

    async def runner():
        await bridge.start()
        await bridge.stop()

    asyncio.run(runner())
    assert bridge.get_stats()["subscriptions"] == 0


def test_bridge_custom_event_set():
    bus = EventBus()
    engine = RealtimeEngine()
    bridge = rt.DashboardRealtimeBridge(
        bus, engine, events=("only.this",), channel="custom"
    )
    assert bridge.channel == "custom"
    assert bridge.get_stats()["events"] == ["only.this"]


def test_bridge_engine_stats_present():
    bus = EventBus()
    engine = RealtimeEngine()
    bridge = rt.DashboardRealtimeBridge(bus, engine)
    stats = bridge.get_stats()
    assert "engine" in stats
    assert "channels" in stats["engine"]


# --------------------------------------------------------------------------- #
# 2. End-to-end fanout
# --------------------------------------------------------------------------- #


def test_multiple_subscribers_all_receive_event():
    bus = EventBus()
    engine = RealtimeEngine()
    bridge = rt.DashboardRealtimeBridge(bus, engine)
    sub_a = engine.subscribe("dashboard")
    sub_b = engine.subscribe("dashboard")

    async def runner():
        await bridge.start()
        bus.publish("cost.recorded", {"usd": 0.42}, synchronous=True)
        await asyncio.sleep(0)

    asyncio.run(runner())
    msg_a = sub_a.queue.get_nowait()
    msg_b = sub_b.queue.get_nowait()
    assert msg_a["event"] == "cost.recorded"
    assert msg_b["event"] == "cost.recorded"


def test_non_dict_payload_is_wrapped():
    bus = EventBus()
    engine = RealtimeEngine()
    bridge = rt.DashboardRealtimeBridge(bus, engine)
    sub = engine.subscribe("dashboard")

    async def runner():
        await bridge.start()
        bus.publish("tool.invoked", "raw-string", synchronous=True)
        await asyncio.sleep(0)

    asyncio.run(runner())
    msg = sub.queue.get_nowait()
    assert msg["payload"] == {"value": "raw-string"}


def test_event_metadata_propagates():
    bus = EventBus()
    engine = RealtimeEngine()
    bridge = rt.DashboardRealtimeBridge(bus, engine)
    sub = engine.subscribe("dashboard")

    async def runner():
        await bridge.start()
        bus.publish(
            "memory.appended",
            {"item": "x"},
            source="memory_manager",
            synchronous=True,
        )
        await asyncio.sleep(0)

    asyncio.run(runner())
    msg = sub.queue.get_nowait()
    assert msg["source"] == "memory_manager"
    assert "event_id" in msg


# --------------------------------------------------------------------------- #
# 3. WebSocket handler
# --------------------------------------------------------------------------- #


class FakeWebSocket:
    """Minimal stand-in for a websocket connection."""

    def __init__(self, incoming: list[str] | None = None) -> None:
        self.incoming = incoming or []
        self.sent: list[str] = []
        self._idx = 0

    async def send(self, payload):
        # Mirror FastAPI WebSocket: payload may be a dict (we JSON-dump it).
        if isinstance(payload, (dict, list)):
            self.sent.append(json.dumps(payload))
        else:
            self.sent.append(str(payload))

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._idx >= len(self.incoming):
            raise StopAsyncIteration
        item = self.incoming[self._idx]
        self._idx += 1
        return item


def test_ws_handler_emits_hello_message():
    bus = EventBus()
    engine = RealtimeEngine()
    bridge = rt.DashboardRealtimeBridge(bus, engine)

    async def runner():
        await bridge.start()
        rt.set_bridge(bridge)
        ws = FakeWebSocket(incoming=[])
        try:
            await asyncio.wait_for(rt.dashboard_ws_handler(ws), timeout=0.2)
        except asyncio.TimeoutError:
            pass
        return ws.sent

    sent = asyncio.run(runner())
    assert any('"hello"' in s for s in sent)
    rt.set_bridge(None)


def test_ws_handler_forwards_published_event():
    bus = EventBus()
    engine = RealtimeEngine()
    bridge = rt.DashboardRealtimeBridge(bus, engine)

    async def runner():
        await bridge.start()
        rt.set_bridge(bridge)
        ws = FakeWebSocket(incoming=[])
        task = asyncio.create_task(rt.dashboard_ws_handler(ws))
        await asyncio.sleep(0)
        # Trigger a bus event the bridge is subscribed to.
        bus.publish("session.started", {"sid": "abc"}, synchronous=True)
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        return ws.sent

    sent = asyncio.run(runner())
    rt.set_bridge(None)
    # The hello frame + the session.started frame should both appear.
    assert any('"session.started"' in s for s in sent)


def test_ws_handler_requires_bridge():
    rt.set_bridge(None)

    async def runner():
        ws = FakeWebSocket(incoming=[])
        try:
            await rt.dashboard_ws_handler(ws)
        except RuntimeError as exc:
            return str(exc)
        return ""

    msg = asyncio.run(runner())
    assert "DashboardRealtimeBridge" in msg


# --------------------------------------------------------------------------- #
# 4. Bridge lifecycle and engine helpers
# --------------------------------------------------------------------------- #


def test_start_is_idempotent():
    bus = EventBus()
    engine = RealtimeEngine()
    bridge = rt.DashboardRealtimeBridge(bus, engine)

    async def runner():
        await bridge.start()
        await bridge.start()
        return bridge.get_stats()["subscriptions"]

    n = asyncio.run(runner())
    # Idempotent: should not double-subscribe to the same topic.
    assert n == len(rt.DEFAULT_DASHBOARD_EVENTS)


def test_stop_then_restart_resubscribes():
    bus = EventBus()
    engine = RealtimeEngine()
    bridge = rt.DashboardRealtimeBridge(bus, engine)

    async def runner():
        await bridge.start()
        first = bridge.get_stats()["subscriptions"]
        await bridge.stop()
        second = bridge.get_stats()["subscriptions"]
        await bridge.start()
        third = bridge.get_stats()["subscriptions"]
        return first, second, third

    first, second, third = asyncio.run(runner())
    assert first > 0
    assert second == 0
    assert third > 0


def test_bridge_publish_failure_is_swallowed():
    bus = EventBus()
    engine = MagicMock()
    engine.stats = MagicMock(return_value={"channels": 0, "total_subscribers": 0})
    engine.publish = MagicMock(side_effect=RuntimeError("boom"))
    bridge = rt.DashboardRealtimeBridge(bus, engine)

    async def runner():
        await bridge.start()
        bus.publish("session.started", {"sid": "x"}, synchronous=True)
        await asyncio.sleep(0)

    # Must not raise — errors in the realtime engine are debug-logged.
    asyncio.run(runner())
    assert engine.publish.called
