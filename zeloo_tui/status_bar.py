"""TUI status bar — borrowed design from Hermes Agent's bottom HUD.

Hermes Agent renders a persistent footer with: current mode (chat /
build / plan), token cost to date, and the active skin/theme name.
Zeloo's :class:`StatusBar` follows the same pattern: it reads from
:class:`zeloo_tui.bridge.TUIBridge.state` and refreshes on a timer.

Bind :kbd:`Ctrl+T` to cycle through the built-in skins (default →
starlight → plain → default) so the TUI and the CLI can share the
same theme names.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from textual.reactive import reactive
from textual.widgets import Static

if TYPE_CHECKING:
    from zeloo_tui.bridge import TUIBridge, BridgeState

logger = logging.getLogger(__name__)


# Skin rotation order — matches ``zeloo_cli.skin_engine.BUILTIN_SKINS``.
SKIN_CYCLE: tuple[str, ...] = ("default", "starlight", "plain")


class StatusBar(Static):
    """Bottom-of-screen HUD with mode + counters + active skin."""

    DEFAULT_CSS = """
    StatusBar {
        dock: bottom;
        height: 1;
        background: $boost;
        color: $text;
        padding: 0 1;
    }
    """

    skin: reactive[str] = reactive("default", init=False)

    def __init__(self, bridge: "TUIBridge") -> None:
        super().__init__(id="status-bar")
        self._bridge = bridge

    def watch_skin(self, _: str) -> None:
        """Re-render whenever the skin name changes."""
        self.refresh_text()

    def on_mount(self) -> None:
        self.set_interval(1.0, self.refresh_text)

    def refresh_text(self) -> None:
        state: "BridgeState" = self._bridge.state
        events = len(state.events)
        hosts = len(state.hosts)
        changes = len(state.changes)
        skin = self.skin
        now = datetime.now().strftime("%H:%M:%S")
        text = (
            f"[dim]{now}[/dim]  "
            f"[b]mode[/b]=observer  "
            f"[b]events[/b]={events}  "
            f"[b]hosts[/b]={hosts}  "
            f"[b]changes[/b]={changes}  "
            f"[b]skin[/b]=[cyan]{skin}[/cyan]"
        )
        self.update(text)


__all__ = ["StatusBar", "SKIN_CYCLE"]