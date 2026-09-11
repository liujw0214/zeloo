"""TUIBridge — the single seam between ``tui_gateway`` and the Textual app.

Hermes-parity implementation covering:
1. subscribe/unsubscribe to all 7 AgentEventType callbacks.
2. Buffer events when the app isn't attached yet.
3. attach_app(app) — attaches to a textual app and replays buffered events.
4. record_change() / register_host() — host and change tracking.
5. refresh_billing() with optional rate-limiting (refresh_hz).
6. Headless-safe format_* helpers (no Rich dependency).
"""

from __future__ import annotations

import logging
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from tui_gateway.agent_callbacks import (
    AgentEvent,
    AgentEventType,
    CallbackRegistry,
    get_registry,
)
from tui_gateway.billing_view import BillingSnapshot, BillingView
from tui_gateway.change_watcher import WatchEvent
from tui_gateway.compute_host import HostInfo, list_hosts

logger = logging.getLogger(__name__)

EVENT_BUFFER_LIMIT = 500

_GLYPHS = {
    AgentEventType.START: "▶",
    AgentEventType.THINK: "…",
    AgentEventType.TOOL_CALL: "⚙",
    AgentEventType.TOOL_RESULT: "↳",
    AgentEventType.FINISH: "✓",
    AgentEventType.ERROR: "✗",
    AgentEventType.CANCELLED: "⊘",
}


def _rich_escape(text: str) -> str:
    return text.replace("[", "[[").replace("]", "]]")


def format_event(event: AgentEvent) -> str:
    ts = datetime.fromtimestamp(event.timestamp).strftime("%H:%M:%S")
    glyph = _GLYPHS.get(event.type, "?")
    payload = event.payload or {}

    sid = event.session_id[:8] if event.session_id else "-"

    if event.type is AgentEventType.START:
        model = payload.get("model", "")
        parts = [f"start sid={sid}"]
        if model:
            parts.append(model)
    elif event.type is AgentEventType.THINK:
        parts = [f"think sid={sid} iter={payload.get('iteration', '?')}"]
    elif event.type is AgentEventType.TOOL_CALL:
        name = _rich_escape(str(payload.get("name", "?")))
        args = payload.get("args") or {}
        if isinstance(args, dict):
            pairs = [f"{k}={_rich_escape(str(v))}" for k, v in list(args.items())[:2]]
        else:
            pairs = []
        parts = [f"tool sid={sid} {name}({', '.join(pairs)})"]
    elif event.type is AgentEventType.TOOL_RESULT:
        name = payload.get("name", "?")
        result = payload.get("result")
        if result is None:
            suffix = "(empty)"
        elif isinstance(result, str) and len(result) > 60:
            suffix = repr(result[:60]) + "…"
        elif isinstance(result, str):
            suffix = repr(result)
        else:
            suffix = repr(result)[:80]
        parts = [f"result sid={sid} {name} → {suffix}"]
    elif event.type is AgentEventType.FINISH:
        tokens_raw = payload.get("tokens", "?")
        tokens_display = _rich_escape(str(tokens_raw))
        result = payload.get("result", "")
        if result and isinstance(result, str):
            result_display = _rich_escape(result[:80])
            parts = [f"finish sid={sid} tokens=[{tokens_display}] → {result_display}"]
        else:
            parts = [f"finish sid={sid} tokens=[{tokens_display}]"]
    elif event.type is AgentEventType.ERROR:
        err_type = payload.get("type", "?")
        err_msg = _rich_escape(str(payload.get("error", "")))
        parts = [f"error sid={sid} {err_type}: {err_msg}"]
    elif event.type is AgentEventType.CANCELLED:
        parts = [f"cancelled sid={sid} user-cancelled"]
    else:
        parts = [f"? sid={sid}"]

    return ts + " [" + glyph + "] " + " ".join(parts)


def format_billing(snap: BillingSnapshot | None) -> str:
    if snap is None:
        return "[dim]no usage yet[/dim]"
    return (
        f"${snap.total_cost_usd:.4f} USD · "
        f"{snap.total_calls} calls · "
        f"in={snap.total_input_tokens:,} out={snap.total_output_tokens:,}"
    )


def format_host(info: HostInfo) -> list[str]:
    return [
        info.name,
        info.os,
        str(info.cpu_count),
    ]


def format_change(ev: WatchEvent) -> str:
    ts = datetime.fromtimestamp(ev.timestamp).strftime("%H:%M:%S")
    path_str = str(ev.path)
    return f"{ts} [{ev.kind}] {path_str}"


class TUIBridge:
    def __init__(
        self,
        billing: BillingView | None = None,
        watcher: Any = None,
        *,
        refresh_hz: float = 0.0,
    ) -> None:
        self.events: list[AgentEvent] = []
        self.changes: list[WatchEvent] = []
        self.hosts: list[HostInfo] = []
        self._billing = billing or BillingView()
        self._watcher = watcher
        self._refresh_hz = refresh_hz
        self._last_billing_at = 0.0
        self._unsubs: list[Callable[[], None]] = []
        self._unsubs_watcher: list[Callable[[], None]] = []
        self._app: Any | None = None
        self._registry = get_registry()
        self._pending_sessions: set[str] = set()
        self._billing_result: BillingSnapshot | None = None

    # ---- headless formatter access ------------------------------------

    @property
    def changes_deque(self) -> list[WatchEvent]:
        return self.changes

    @property
    def hosts_deque(self) -> list[HostInfo]:
        return self.hosts

    # ---- subscription (Hermes-style) ----------------------------------

    def subscribe(self) -> None:
        if self._unsubs:
            return
        for t in AgentEventType:
            unsub = self._registry.subscribe(t, self._on_agent_event)
            self._unsubs.append(unsub)

    def unsubscribe(self) -> None:
        for unsub in self._unsubs:
            try:
                unsub()
            except Exception:  # noqa: BLE001
                pass
        self._unsubs.clear()

    # ---- change / host tracking ---------------------------------------

    def record_change(self, ev: WatchEvent) -> None:
        self.changes.append(ev)
        if len(self.changes) > EVENT_BUFFER_LIMIT:
            self.changes = self.changes[-EVENT_BUFFER_LIMIT:]

    def register_host(self, info: HostInfo) -> None:
        for i, existing in enumerate(self.hosts):
            if existing.name == info.name:
                self.hosts[i] = info
                return
        self.hosts.append(info)

    # ---- billing refresh ----------------------------------------------

    def refresh_billing(self) -> BillingSnapshot | None:
        if self._refresh_hz > 0:
            now = time.time()
            if now - self._last_billing_at < (1.0 / self._refresh_hz):
                return self._billing_result
            self._last_billing_at = now

        billing = self._billing

        if isinstance(billing, BillingSnapshot):
            self._billing_result = billing
            return billing

        explicit_seed = getattr(self, "__billing_seed", None)
        if explicit_seed is not None:
            self._billing_result = explicit_seed
            return explicit_seed

        try:
            snap = billing.snapshot()
            self._billing_result = snap
            return snap
        except Exception:  # noqa: BLE001
            return self._billing_result

    @property
    def _billing_snapshot_seed(self) -> BillingSnapshot | None:
        return getattr(self, "__billing_seed", None)

    @_billing_snapshot_seed.setter
    def _billing_snapshot_seed(self, value: BillingSnapshot | None) -> None:
        object.__setattr__(self, "__billing_seed", value)

    # ---- attach app (Hermes-style) ------------------------------------

    def attach_app(self, app: Any) -> None:
        self._app = app
        self.subscribe()
        if self._watcher is not None:
            self._unsubs_watcher.append(
                self._watcher.on_change(self._on_change_event)
            )
        for ev in list(self.events):
            self.bridge_on_event(ev)

    def bridge_on_event(self, ev: AgentEvent) -> None:
        method = getattr(self._app, "bridge_on_event", None)
        if method is None:
            return
        try:
            call_from_thread = getattr(self._app, "call_from_thread", None)
            if callable(call_from_thread):
                try:
                    call_from_thread(method, ev)
                    return
                except Exception:  # noqa: BLE001
                    pass
            method(ev)
        except Exception:  # noqa: BLE001
            logger.debug("bridge_on_event dispatch failed", exc_info=True)

    # ---- internal dispatch --------------------------------------------

    def _on_agent_event(self, ev: AgentEvent) -> None:
        self.events.append(ev)
        if len(self.events) > EVENT_BUFFER_LIMIT:
            self.events = self.events[-EVENT_BUFFER_LIMIT:]

        if self._app is not None:
            self.bridge_on_event(ev)

        if ev.type is AgentEventType.FINISH:
            self.refresh_billing()

    def _on_change_event(self, ev: WatchEvent) -> None:
        self.record_change(ev)
        method = getattr(self._app, "bridge_on_change", None)
        if method:
            try:
                method(ev)
            except Exception:  # noqa: BLE001
                pass


__all__ = [
    "TUIBridge",
    "format_event",
    "format_billing",
    "format_host",
    "format_change",
]
