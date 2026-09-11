"""Tests for the headless TUI bridge (no textual App required).

The actual textual widgets are tested via :mod:`test_tui_widgets` —
those tests use the running Textual pilot harness. This file exercises
the pure-Python formatter and bridge logic so they work without an
interactive terminal.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from tui_gateway.agent_callbacks import (
    AgentEvent,
    AgentEventType,
    CallbackRegistry,
    emit_finish,
    emit_start,
    emit_tool_call,
    get_registry,
)
from tui_gateway.change_watcher import WatchEvent
from tui_gateway.compute_host import HostInfo
from zeloo_tui import is_textual_available
from zeloo_tui.bridge import (
    TUIBridge,
    format_billing,
    format_change,
    format_event,
    format_host,
)


def _make_host(name: str = "h", cpu: int = 4, mem_total: int = 16000) -> HostInfo:
    """Build a HostInfo with sensible defaults for tests."""
    return HostInfo(
        name=name,
        os="Linux 6.0",
        cpu_count=cpu,
        memory_total_mb=mem_total,
        memory_available_mb=mem_total // 2,
        disk_free_gb=100.0,
        python_version="3.12.0",
    )


# ── formatters ────────────────────────────────────────────────────────


class TestFormatEvent:
    def test_format_start_includes_session(self) -> None:
        ev = AgentEvent(AgentEventType.START, "abcdef1234", payload={"x": 1})
        out = format_event(ev)
        assert "start" in out
        assert "abcdef12" in out  # truncated session id

    def test_format_tool_call_args_rendered(self) -> None:
        ev = AgentEvent(
            AgentEventType.TOOL_CALL,
            "sess1",
            payload={"name": "web_search", "args": {"q": "hello"}},
        )
        out = format_event(ev)
        assert "web_search" in out
        assert "hello" in out

    def test_format_tool_call_no_args(self) -> None:
        ev = AgentEvent(
            AgentEventType.TOOL_CALL,
            "sess1",
            payload={"name": "noop"},
        )
        out = format_event(ev)
        assert "noop" in out

    def test_format_tool_result_truncated(self) -> None:
        long_result = "x" * 200
        ev = AgentEvent(
            AgentEventType.TOOL_RESULT,
            "sess1",
            payload={"name": "f", "result": long_result},
        )
        out = format_event(ev)
        # The repr is truncated to 80 chars.
        assert out.count("x") <= 80

    def test_format_tool_result_empty(self) -> None:
        ev = AgentEvent(
            AgentEventType.TOOL_RESULT,
            "sess1",
            payload={"name": "f", "result": None},
        )
        out = format_event(ev)
        assert "(empty)" in out

    def test_format_error_includes_type_and_message(self) -> None:
        ev = AgentEvent(
            AgentEventType.ERROR,
            "sess1",
            payload={"error": "boom", "type": "ValueError"},
        )
        out = format_event(ev)
        assert "ValueError" in out
        assert "boom" in out

        assert "boom" in out

    def test_format_event_escapes_brackets(self) -> None:
        """Payloads with ``[`` or ``]`` must not be parsed as Rich markup.

        Regression test for Round 53 — without escaping, the output
        string contained unmatched ``[/]`` tags that corrupted the
        RichLog rendering.
        """
        ev = AgentEvent(
            AgentEventType.TOOL_CALL,
            "sess1",
            payload={"name": "f", "args": {"q": "[bracketed]"}},
        )
        out = format_event(ev)
        # ``[`` / ``]`` in payload must be doubled so Rich treats them
        # as literal text.
        assert "[[bracketed]]" in out

        ev2 = AgentEvent(
            AgentEventType.FINISH,
            "sess1",
            payload={"result": "ok", "tokens": "[1, 2, 3]"},
        )
        out2 = format_event(ev2)
        # Tokens rendered via repr() produce ``{'tokens': '[1, 2, 3]'}``
        # — the ``[`` / ``]`` must be escaped.
        assert "[[1, 2, 3]]" in out2


class TestFormatHelpers:
    def test_format_billing(self) -> None:
        from tui_gateway.billing_view import BillingSnapshot

        snap = BillingSnapshot(
            period="day",
            total_cost_usd=0.1234,
            total_input_tokens=1000,
            total_output_tokens=2000,
            total_calls=7,
            top_providers=[("openai", 5)],
        )
        out = format_billing(snap)
        assert "$0.1234" in out
        assert "7 calls" in out
        assert "openai" not in out  # top_providers not in compact form

    def test_format_change_created(self) -> None:
        ev = WatchEvent(path="/etc/config.yaml", kind="created")
        out = format_change(ev)
        assert "created" in out
        assert "/etc/config.yaml" in out

    def test_format_host(self) -> None:
        host = _make_host("local-1", cpu=4)
        cols = format_host(host)
        # We render (name, os, cpu_count) — the bridge surfaces these
        # three so operators can see "what's running where".
        assert cols[0] == "local-1"
        assert "Linux" in cols[1]
        assert cols[2] == "4"


# ── bridge ────────────────────────────────────────────────────────────


class TestBridgeSubscription:
    def test_subscribe_unsubscribe(self) -> None:
        registry = get_registry()
        # Snapshot subscriber counts so we can restore them.
        baseline = {t: len(registry._subscribers[t]) for t in AgentEventType}  # noqa: SLF001

        bridge = TUIBridge()
        bridge.subscribe()
        for t in AgentEventType:
            assert len(registry._subscribers[t]) == baseline[t] + 1

        bridge.unsubscribe()
        for t in AgentEventType:
            assert len(registry._subscribers[t]) == baseline[t]

    def test_event_buffered_before_app_attached(self) -> None:
        # Use an isolated registry so we don't pollute the global one.
        registry = CallbackRegistry()
        original = get_registry()
        try:
            import tui_gateway.agent_callbacks as cb_module

            cb_module._registry = registry  # type: ignore[attr-defined]
            bridge = TUIBridge()
            bridge.subscribe()
            emit_start("test-session", model="demo")
            emit_tool_call("test-session", name="f", args={"x": 1})
            emit_finish("test-session", tokens=42)
            types_in_buffer = [e.type for e in bridge.events]
            assert AgentEventType.START in types_in_buffer
            assert AgentEventType.TOOL_CALL in types_in_buffer
            assert AgentEventType.FINISH in types_in_buffer
        finally:
            import tui_gateway.agent_callbacks as cb_module

            cb_module._registry = original  # type: ignore[attr-defined]
            bridge.unsubscribe()

    def test_attach_app_dispatches_buffered_events(self) -> None:
        """When the app attaches late, the bridge replays its buffer."""
        registry = CallbackRegistry()
        original = get_registry()
        try:
            import tui_gateway.agent_callbacks as cb_module

            cb_module._registry = registry  # type: ignore[attr-defined]
            bridge = TUIBridge()
            bridge.subscribe()
            emit_start("late-session", model="late")
            emit_tool_call("late-session", name="f", args={})
            # The bridge has buffered two events without an app.
            assert len(bridge.events) == 2

            # Pretend the textual app came up *now*. Make ``call_from_thread``
            # behave like a real textual app: synchronously invoke the
            # callback so we can verify the dispatch path.
            app = MagicMock()

            def _fake_call_from_thread(method, *args):  # noqa: ARG001
                return method(*args)

            app.call_from_thread.side_effect = _fake_call_from_thread
            bridge.attach_app(app)
            # attach_app replays the buffer: bridge_on_event should
            # have been called for each buffered event.
            assert app.bridge_on_event.call_count == 2
            # And the events carry the session id we emitted.
            replayed_sessions = [
                call.args[0].session_id for call in app.bridge_on_event.call_args_list
            ]
            assert all(s == "late-session" for s in replayed_sessions)
        finally:
            import tui_gateway.agent_callbacks as cb_module

            cb_module._registry = original  # type: ignore[attr-defined]
            bridge.unsubscribe()

    def test_finish_triggers_billing_refresh(self) -> None:
        """The bridge should refresh billing on every finish event."""
        registry = CallbackRegistry()
        original = get_registry()
        try:
            import tui_gateway.agent_callbacks as cb_module

            cb_module._registry = registry  # type: ignore[attr-defined]
            bridge = TUIBridge()
            # Patch BillingView.snapshot to count calls.
            from tui_gateway import billing_view as bv_module

            original_snap = bv_module.BillingView.snapshot
            call_count = {"n": 0}

            def counting_snap(self, period=None):  # noqa: ARG001
                call_count["n"] += 1
                # Return a minimal snapshot-like object.
                from tui_gateway.billing_view import BillingSnapshot

                return BillingSnapshot(
                    period="day",
                    total_cost_usd=0.0,
                    total_input_tokens=0,
                    total_output_tokens=0,
                    total_calls=0,
                    top_providers=[],
                )

            bv_module.BillingView.snapshot = counting_snap  # type: ignore[method-assign]
            bridge.subscribe()
            emit_finish("sess1")
            emit_finish("sess2")
            assert call_count["n"] >= 2
            bv_module.BillingView.snapshot = original_snap  # type: ignore[method-assign]
        finally:
            import tui_gateway.agent_callbacks as cb_module

            cb_module._registry = original  # type: ignore[attr-defined]
            bridge.unsubscribe()

    def test_record_change_appends(self) -> None:
        bridge = TUIBridge()
        for i in range(5):
            bridge.record_change(WatchEvent(path=Path(f"/p/{i}"), kind="modified"))
        assert len(bridge.changes) == 5
        assert bridge.changes[-1].path == Path("/p/4")

    def test_register_host_keeps_latest(self) -> None:
        bridge = TUIBridge()
        h1 = _make_host("a", cpu=4)
        h2 = _make_host("a", cpu=8)
        bridge.register_host(h1)
        bridge.register_host(h2)
        assert len(bridge.hosts) == 1
        assert bridge.hosts[0].cpu_count == 8


# ── availability ──────────────────────────────────────────────────────


class TestAvailability:
    def test_refresh_billing_respects_refresh_hz_zero(self) -> None:
        """With ``refresh_hz=0`` the bridge must not overwrite an
        explicitly-set ``_billing`` snapshot.

        Regression test for Round 53: in demo mode the emitter
        writes ``bridge._billing`` then the periodic poll (and every
        FINISH event) called ``refresh_billing()`` which queried the
        UsageTracker and clobbered the demo snapshot with $0.0000.
        """
        from tui_gateway.billing_view import BillingSnapshot

        b = TUIBridge(refresh_hz=0.0)
        # Seed an explicit snapshot.
        snap = BillingSnapshot(
            period="day",
            total_cost_usd=9.99,
            total_input_tokens=100,
            total_output_tokens=200,
            total_calls=42,
            top_providers=[],
        )
        b._billing = snap
        # ``refresh_billing()`` must re-dispatch the same snapshot,
        # not pull from UsageTracker (which has no real data).
        result = b.refresh_billing()
        assert result is snap
        assert result.total_cost_usd == 9.99

    def test_is_textual_available(self) -> None:
        # Should match the actual import status.
        result = is_textual_available()
        try:
            import textual  # noqa: F401

            assert result is True
        except ImportError:
            assert result is False


# Path import at the bottom to avoid name conflict in earlier tests.
from pathlib import Path  # noqa: E402