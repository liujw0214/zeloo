"""ZelooTUIChatApp — interactive Textual TUI with input history + slash completion.

This is the *active* counterpart of :class:`zeloo_tui.app.ZelooTUIApp`,
which is a passive observer. Borrowed design from Hermes Agent's
``useInputHistory`` + ``useCompletion`` hooks (see docs/58 §5).

Layout
------

::

    Header (clock)
    ┌──────────────────┬──────────────────────────┐
    │ EventLog (chat)  │ BillingPanel / Hosts /  │
    │                  │ Changes                  │
    └──────────────────┴──────────────────────────┘
    Footer (key bindings)
    [Input widget — ↑/↓ history, ``/`` triggers completion popup]

Key bindings
------------

* ``Ctrl+C`` / ``Ctrl+Q`` — quit
* ``Ctrl+L`` — clear log
* ``Enter`` — submit message
* ``Up`` / ``Down`` — walk input history
* ``Tab`` / ``Down`` (when popup open) — accept completion
* ``Esc`` — dismiss completion
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, Static

from zeloo_tui.bridge import TUIBridge
from zeloo_tui.chat_input import MultiLineState
from zeloo_tui.history import (
    SLASH_COMMANDS,
    InputHistory,
    filter_slash_commands,
)
from zeloo_tui.status_bar import SKIN_CYCLE, StatusBar
from zeloo_tui.widgets import BillingPanel, ChangePanel, EventLog, HostPanel

logger = logging.getLogger(__name__)


class CompletionPopup(Static):
    """Tiny dropdown showing matched slash commands."""

    DEFAULT_CSS = """
    CompletionPopup {
        layer: overlay;
        border: round $accent;
        background: $panel;
        padding: 0 1;
        max-height: 8;
    }
    """

    def render_matches(self, matches: list[dict[str, str]]) -> None:
        if not matches:
            self.update("")
            return
        lines = ["[b]slash commands[/b]"]
        for m in matches[:4]:
            lines.append(f"  [cyan]{m['name']}[/cyan] — {m['description']}")
        self.update("\n".join(lines))


class ZelooTUIChatApp(App[None]):  # type: ignore[misc]
    """Textual app with an interactive chat-style input row."""

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
    #input-row {
        height: 3;
        border: round $primary;
        padding: 0 1;
    }
    #completion-popup {
        dock: bottom;
        margin: 0 2;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+q", "quit", "Quit", show=False),
        Binding("ctrl+l", "clear_log", "Clear log", show=True),
        Binding("ctrl+t", "cycle_skin", "Cycle skin", show=True),
        Binding("up", "history_up", "History ↑", show=False),
        Binding("down", "history_down", "History ↓", show=False),
        Binding("escape", "dismiss_completion", "Dismiss", show=False),
    ]

    def __init__(self, *, log_level: str = "WARNING", skin: str = "default") -> None:
        super().__init__()
        self.bridge = TUIBridge()
        self.history = InputHistory()
        self._multiline = MultiLineState()
        self._log_level = log_level
        self._skin_idx = SKIN_CYCLE.index(skin) if skin in SKIN_CYCLE else 0

    # ── compose ────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            with Vertical(id="event-column"):
                yield EventLog()
            with Vertical(id="status-column"):
                yield BillingPanel()
                yield HostPanel()
                yield ChangePanel()
        yield Input(placeholder="Type a message or /command…", id="chat-input")
        yield CompletionPopup(id="completion-popup")
        yield StatusBar(self.bridge)
        yield Footer()

    # ── lifecycle ─────────────────────────────────────────────

    def on_mount(self) -> None:
        logging.getLogger("zeloo_tui").setLevel(self._log_level)
        self.title = "Zeloo TUI"
        self.sub_title = "interactive · ↑/↓ history · / commands"
        self.bridge.attach(self)
        self.set_interval(1.0, self._tick_clock)
        self.query_one("#completion-popup", CompletionPopup).render_matches([])
        try:
            sb = self.query_one(StatusBar)
            sb.skin = SKIN_CYCLE[self._skin_idx]
        except Exception:  # noqa: BLE001
            logger.debug("StatusBar not yet mounted")

    def on_unmount(self) -> None:
        self.bridge.detach()

    def _tick_clock(self) -> None:
        self.sub_title = f"interactive · {datetime.now().strftime('%H:%M:%S')}"

    # ── actions ────────────────────────────────────────────────

    def action_clear_log(self) -> None:
        log = self.query_one(EventLog)
        log.clear()

    def action_history_up(self) -> None:
        """Recall the previous history entry into the Input box."""
        chat_input = self.query_one("#chat-input", Input)
        prev = self.history.up(chat_input.value)
        if prev is not None:
            chat_input.value = prev

    def action_history_down(self) -> None:
        """Step forward in history back to the live draft."""
        chat_input = self.query_one("#chat-input", Input)
        nxt = self.history.down(chat_input.value)
        if nxt is not None:
            chat_input.value = nxt

    def action_dismiss_completion(self) -> None:
        self.query_one("#completion-popup", CompletionPopup).render_matches([])

    def action_cycle_skin(self) -> None:
        """Rotate through :data:`SKIN_CYCLE` and update the status bar."""
        self._skin_idx = (self._skin_idx + 1) % len(SKIN_CYCLE)
        skin = SKIN_CYCLE[self._skin_idx]
        try:
            sb = self.query_one(StatusBar)
            sb.skin = skin
        except Exception:  # noqa: BLE001
            logger.debug("StatusBar not yet mounted")
        self.sub_title = f"interactive · skin={skin}"

    # ── input handlers ─────────────────────────────────────────

    def on_input_changed(self, event: Input.Changed) -> None:
        """Refresh the slash-command popup + the input footer."""
        popup = self.query_one("#completion-popup", CompletionPopup)
        if event.value.startswith("/"):
            popup.render_matches(filter_slash_commands(event.value))
        else:
            popup.render_matches([])
        # Show multi-line status in the title so users always see it.
        try:
            self.sub_title = self._multiline.status(event.value)
        except Exception:  # noqa: BLE001
            logger.debug("Multi-line status update failed")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Submit the line, push into history, mirror into the EventLog.

        Multi-line: if the user ends a line with a backslash ``\\``,
        we keep accumulating and prefix the next submission. Press
        ``Esc`` (dismiss_completion) to also cancel a pending
        continuation block.
        """
        text = event.value
        if not text.strip():
            return

        chat_input = self.query_one("#chat-input", Input)
        # Multi-line accumulator: if the line ends with ``\\``, hold
        # it and stay in continuation mode. Plain text submits.
        submitted, final_text = self._multiline.feed(text)
        if not submitted:
            chat_input.value = ""
            log = self.query_one(EventLog)
            log.write_event(
                "[dim]…continuation[/dim] "
                f"buffered {len(self._multiline.buffer)} chars "
                "(next line, or blank line to cancel)"
            )
            self.sub_title = self._multiline.status("")
            return

        # Single-line submit (or accumulated multi-line commit).
        chat_input.value = ""
        self.query_one("#completion-popup", CompletionPopup).render_matches([])
        self.sub_title = self._multiline.status("")

        if final_text.startswith("/"):
            log = self.query_one(EventLog)
            log.write_event(f"[bold cyan]/cmd[/bold cyan] {final_text}")
            self._run_slash(final_text)
        else:
            self.history.push(final_text)
            log = self.query_one(EventLog)
            log.write_event(f"[bold green]→[/bold green] {final_text[:200]}")
            self.bridge.on_event_log(f"user-input → {final_text[:160]}")

    # ── slash dispatch ────────────────────────────────────────

    def _run_slash(self, raw: str) -> None:
        cmd, *rest = raw.split(maxsplit=1)
        arg = rest[0] if rest else ""
        log = self.query_one(EventLog)

        if cmd == "/help":
            log.write_event(
                "[bold]commands[/bold]  "
                + "  ".join(c["name"] for c in SLASH_COMMANDS)
            )
        elif cmd == "/clear":
            log.clear()
        elif cmd == "/session":
            log.write_event("[dim]session=local-tui-chat[/dim]")
        elif cmd == "/skin":
            self._slash_skin(arg.strip(), log)
        elif cmd == "/model":
            self._slash_model(arg.strip(), log)
        elif cmd == "/stats":
            self._slash_stats(log)
        elif cmd == "/plugins":
            self._slash_plugins(log)
        elif cmd == "/review":
            self._slash_review(arg.strip(), log)
        else:
            log.write_event(f"[dim]unknown command: {cmd} (try /help)[/dim]")

    # ── slash handlers ─────────────────────────────────────────

    def _slash_skin(self, name: str, log: EventLog) -> None:
        """``/skin [name]`` — show or cycle the active skin."""
        if not name:
            try:
                sb = self.query_one(StatusBar)
                log.write_event(f"[dim]active skin=[/dim][cyan]{sb.skin}[/cyan]")
            except Exception:  # noqa: BLE001
                log.write_event(f"[dim]active skin=default[/dim]")
            return
        # Set to the requested skin if it exists; otherwise notify.
        if name not in SKIN_CYCLE:
            log.write_event(
                f"[yellow]unknown skin[/yellow] {name!r}; "
                f"available: {' '.join(SKIN_CYCLE)}"
            )
            return
        idx = SKIN_CYCLE.index(name)
        # Walk forward (or backward) from current to the requested one.
        delta = (idx - self._skin_idx) % len(SKIN_CYCLE)
        for _ in range(delta):
            self.action_cycle_skin()
        log.write_event(f"[green]skin switched[/green] to [cyan]{SKIN_CYCLE[self._skin_idx]}[/cyan]")

    def _slash_model(self, spec: str, log: EventLog) -> None:
        """``/model [provider/name]`` — show or set the active model."""
        if not spec:
            log.write_event("[dim]current model=default (gpt-4o)[/dim]")
            return
        # Persist the choice so a subsequent ``zeloo chat`` picks it up.
        from zeloo_cli.config import load_config, save_config

        cfg = load_config()
        cfg["model"] = spec
        save_config(cfg)
        log.write_event(f"[green]model set[/green] → [cyan]{spec}[/cyan]")

    def _slash_stats(self, log: EventLog) -> None:
        """``/stats`` — show bridge + cache counters."""
        stats = self.bridge.state
        log.write_event(
            f"[dim]events=[/dim]{len(stats.events)}  "
            f"[dim]hosts=[/dim]{len(stats.hosts)}  "
            f"[dim]changes=[/dim]{len(stats.changes)}  "
            f"[dim]history=[/dim]{len(self.history.entries)}"
        )

    def _slash_plugins(self, log: EventLog) -> None:
        """``/plugins`` — list loaded plugins (Hermes Agent parity)."""
        try:
            from plugins.manager import PluginManager

            mgr = PluginManager(plugin_dirs=["plugins"])
            infos = mgr.load_all()
        except Exception as exc:  # noqa: BLE001
            log.write_event(f"[yellow]plugin manager unavailable:[/yellow] {exc}")
            return
        if not infos:
            log.write_event("[dim]no plugins loaded[/dim]")
            return
        for name, info in infos.items():
            tools = ", ".join(info.tools_added) if info.tools_added else "—"
            status = "OK" if info.enabled else f"FAIL ({info.error})"
            log.write_event(f"  [b]{name}[/b]  [dim]{status}[/dim]  tools: {tools}")

    def _slash_review(self, target: str, log: EventLog) -> None:
        """``/review [target]`` — trigger background review (Hermes Agent)."""
        try:
            from agent.background_review import run_background_review

            import threading

            payload = {
                "session_id": f"tui-{self.bridge.state.events.__len__()}",
                "target": target or "(unspecified)",
                "model": "gpt-4o-mini",
            }
            threading.Thread(
                target=run_background_review, args=(payload,),
                daemon=True, name="tui-slash-review",
            ).start()
            log.write_event("[green]background review started[/green]")
        except Exception as exc:  # noqa: BLE001
            log.write_event(f"[yellow]review unavailable:[/yellow] {exc}")


__all__ = ["ZelooTUIChatApp", "CompletionPopup"]