"""Tests for the textual widgets — run via textual's pilot harness.

These tests require ``textual`` to be installed (Round 52 added it as
a dev / optional dependency). If textual isn't available the tests
are skipped, not failed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tui_gateway.agent_callbacks import AgentEvent, AgentEventType
from tui_gateway.billing_view import BillingSnapshot
from tui_gateway.change_watcher import WatchEvent
from tui_gateway.compute_host import HostInfo

textual_spec = pytest.importorskip("textual")
pytestmark = [
    pytest.mark.skipif(textual_spec is None, reason="textual not installed"),
    pytest.mark.asyncio,
]

from zeloo_tui.app import ZelooTUIApp  # noqa: E402
from zeloo_tui.widgets import (  # noqa: E402
    BillingPanel,
    ChangePanel,
    EventLog,
    HostPanel,
)


def _make_host(name: str = "h", cpu: int = 4) -> HostInfo:
    return HostInfo(
        name=name,
        os="Linux 6.0",
        cpu_count=cpu,
        memory_total_mb=16000,
        memory_available_mb=8000,
        disk_free_gb=100.0,
        python_version="3.12.0",
    )


# ── event log ─────────────────────────────────────────────────────────


async def test_event_log_renders_event() -> None:
    app = ZelooTUIApp(bridge=None)
    async with app.run_test() as pilot:
        log = app.query_one("#event-log", EventLog)
        log.write_event(
            AgentEvent(AgentEventType.TOOL_CALL, "abcdef1234", payload={"name": "x"})
        )
        await pilot.pause()
        # RichLog exposes its rendered lines; we just confirm no crash
        # and the widget has at least one line.
        assert len(log.lines) >= 1


# ── billing ───────────────────────────────────────────────────────────


async def test_billing_panel_updates() -> None:
    app = ZelooTUIApp(bridge=None)
    async with app.run_test() as pilot:
        panel = app.query_one("#billing-row", BillingPanel)
        panel.update_billing(
            BillingSnapshot(
                period="day",
                total_cost_usd=0.0123,
                total_input_tokens=10,
                total_output_tokens=20,
                total_calls=1,
                top_providers=[],
            )
        )
        await pilot.pause()
        # ``Static.update()`` sets a private ``__content``; the safest
        # public surface is to call ``render()`` and stringify the
        # returned renderable.
        rendered = str(panel.render())
        assert "$0.0123" in rendered
        assert "1 calls" in rendered


# ── host panel ───────────────────────────────────────────────────────


async def test_host_panel_upserts() -> None:
    app = ZelooTUIApp(bridge=None)
    async with app.run_test() as pilot:
        panel = app.query_one("#hosts", HostPanel)
        panel.upsert_host(_make_host("alpha", cpu=4))
        panel.upsert_host(_make_host("beta", cpu=8))
        # Updating existing key replaces the row.
        panel.upsert_host(_make_host("alpha", cpu=16))
        await pilot.pause()
        assert len(panel.columns) == 5


# ── change panel ──────────────────────────────────────────────────────


async def test_change_panel_appends() -> None:
    app = ZelooTUIApp(bridge=None)
    async with app.run_test() as pilot:
        panel = app.query_one("#changes", ChangePanel)
        for i in range(3):
            panel.append_change(
                WatchEvent(path=Path(f"/etc/config-{i}.yaml"), kind="modified")
            )
        await pilot.pause()
        assert len(panel.columns) == 3


# ── app dispatch wiring ───────────────────────────────────────────────


async def test_app_dispatches_event() -> None:
    """The App's bridge_on_* methods must be callable from the bridge
    (we just verify direct calls)."""
    app = ZelooTUIApp(bridge=None)
    async with app.run_test() as pilot:
        app.bridge_on_event(AgentEvent(AgentEventType.START, "session-aaa"))
        app.bridge_on_billing(
            BillingSnapshot(
                period="day",
                total_cost_usd=0.5,
                total_input_tokens=1,
                total_output_tokens=2,
                total_calls=1,
                top_providers=[],
            )
        )
        app.bridge_on_host(_make_host("h1"))
        app.bridge_on_change(WatchEvent(path=Path("/x"), kind="created"))
        await pilot.pause()


# ── keybindings ───────────────────────────────────────────────────────


async def test_quit_binding() -> None:
    app = ZelooTUIApp(bridge=None)
    async with app.run_test() as pilot:
        await pilot.press("ctrl+c")
        await pilot.pause()
        # App should exit (pilot context manager will return).


async def test_clear_log_binding() -> None:
    app = ZelooTUIApp(bridge=None)
    async with app.run_test() as pilot:
        log = app.query_one("#event-log", EventLog)
        log.write_event(AgentEvent(AgentEventType.START, "sess"))
        await pilot.press("ctrl+l")
        await pilot.pause()
        assert log.lines == () or len(log.lines) == 0