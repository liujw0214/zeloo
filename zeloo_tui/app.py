"""ZelooTUIApp — the textual root App with 4-pane layout."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header

from tui_gateway.agent_callbacks import AgentEvent
from tui_gateway.billing_view import BillingSnapshot
from tui_gateway.change_watcher import WatchEvent
from tui_gateway.compute_host import HostInfo

from zeloo_tui.bridge import TUIBridge, format_billing
from zeloo_tui.status_bar import SKIN_CYCLE, StatusBar
from zeloo_tui.widgets import BillingPanel, ChangePanel, EventLog, HostPanel

logger = logging.getLogger(__name__)


class ZelooTUIApp(App[None]):
    CSS = """
    Screen {
        layout: vertical;
    }
    #body {
        height: 1fr;
    }
    #event-column {
        width: 2fr;
        border: round $secondary;
        padding: 0 1;
    }
    #status-column {
        width: 1fr;
    }
    #event-log {
        height: 1fr;
    }
    HostPanel, ChangePanel {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+l", "clear_log", "Clear log", show=True),
        Binding("ctrl+r", "refresh_billing", "Refresh billing", show=True),
        Binding("ctrl+t", "cycle_skin", "Cycle skin", show=True),
        Binding("f1", "help", "Help", show=True),
    ]

    def __init__(
        self,
        *,
        bridge: TUIBridge | None = None,
        log_level: str = "WARNING",
        skin: str = "default",
    ) -> None:
        super().__init__()
        self.bridge = bridge or TUIBridge()
        self._log_level = log_level
        self._skin_idx = SKIN_CYCLE.index(skin) if skin in SKIN_CYCLE else 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            with Vertical(id="event-column"):
                yield EventLog()
            with Vertical(id="status-column"):
                yield BillingPanel(id="billing-row")
                yield HostPanel(id="hosts")
                yield ChangePanel(id="changes")
        yield StatusBar(self.bridge)
        yield Footer()

    def on_mount(self) -> None:
        logging.getLogger("zeloo_tui").setLevel(self._log_level)
        self.title = "Zeloo TUI"
        self.sub_title = "self-hosted agent runtime"
        self.bridge.attach_app(self)
        self.set_interval(1.0, self._tick_clock)
        try:
            sb = self.query_one(StatusBar)
            sb.skin = SKIN_CYCLE[self._skin_idx]
        except Exception:  # noqa: BLE001
            logger.debug("StatusBar not yet mounted")

    def on_unmount(self) -> None:
        self.bridge.unsubscribe()

    def _tick_clock(self) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        self.sub_title = f"self-hosted agent runtime · {now}"

    def action_clear_log(self) -> None:
        log = self.query_one(EventLog)
        log.clear()

    def action_refresh_billing(self) -> None:
        self.bridge.refresh_billing()

    def action_cycle_skin(self) -> None:
        self._skin_idx = (self._skin_idx + 1) % len(SKIN_CYCLE)
        skin = SKIN_CYCLE[self._skin_idx]
        try:
            sb = self.query_one(StatusBar)
            sb.skin = skin
        except Exception:  # noqa: BLE001
            logger.debug("StatusBar not yet mounted")
        self.sub_title = f"self-hosted agent runtime · skin={skin}"

    def action_help(self) -> None:
        self.notify(
            "Ctrl+C quit · Ctrl+L clear log · Ctrl+R refresh billing · F1 help",
            title="Key bindings",
        )

    def bridge_on_event(self, ev: AgentEvent | str) -> None:
        text = str(ev) if not isinstance(ev, AgentEvent) else ev.session_id[:8]
        try:
            log = self.query_one(EventLog)
            log.write_event(text if isinstance(text, str) else repr(ev))
        except Exception:  # noqa: BLE001
            logger.debug("bridge_on_event: widget not ready")

    def bridge_on_billing(self, snap: BillingSnapshot) -> None:
        try:
            panel = self.query_one(BillingPanel)
            text = format_billing(snap)
            panel.update_billing(snap)
        except Exception:  # noqa: BLE001
            logger.debug("bridge_on_billing: widget not ready")

    def bridge_on_host(self, info: HostInfo) -> None:
        try:
            panel = self.query_one(HostPanel)
            panel.upsert_host(info)
        except Exception:  # noqa: BLE001
            logger.debug("bridge_on_host: widget not ready")

    def bridge_on_change(self, ev: WatchEvent) -> None:
        try:
            panel = self.query_one(ChangePanel)
            panel.append_change(ev)
        except Exception:  # noqa: BLE001
            logger.debug("bridge_on_change: widget not ready")

    def on_event_log(self, text: str) -> None:
        try:
            log = self.query_one(EventLog)
            log.write_event(text)
        except Exception:  # noqa: BLE001
            logger.debug("on_event_log: widget not ready")

    def on_billing(self, text: str) -> None:
        try:
            panel = self.query_one(BillingPanel)
            panel.update_text(text)
        except Exception:  # noqa: BLE001
            logger.debug("on_billing: widget not ready")

    def on_change(self, text: str) -> None:
        self.on_event_log(text)


__all__ = ["ZelooTUIApp"]
