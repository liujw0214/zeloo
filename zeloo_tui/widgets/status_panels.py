"""Status panels — Billing / Host / Change.

Each panel is a thin ``Static``/``DataTable`` wrapper around the
formatted text the bridge pushes onto the UI thread.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from textual.widgets import DataTable, Static


@dataclass(frozen=True)
class PanelLimits:
    """Centralised ring-buffer / row-count caps for the status panels.

    Grouped into a dataclass so tests and callers can introspect the
    policy in one place rather than chasing module-level constants.
    """

    host_rows: int = 8
    change_rows: int = 50


# Module-level convenience for backwards-compatible imports.
CHANGE_LIMIT: int = PanelLimits.change_rows
HOST_LIMIT: int = PanelLimits.host_rows


class BillingPanel(Static):
    """Rolling cost summary."""

    DEFAULT_CSS = """
    BillingPanel {
        border: round $accent;
        height: 5;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("id", "billing-panel")
        kwargs.setdefault("markup", True)
        super().__init__("[dim]loading billing…[/dim]", **kwargs)  # type: ignore[arg-type]

    def update_text(self, text: str) -> None:
        self.update(text)

    def update_billing(self, snap: Any) -> None:
        from zeloo_tui.bridge import format_billing
        self.update(format_billing(snap))


class HostPanel(DataTable):
    """Top-N compute hosts."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("id", "host-panel")
        kwargs.setdefault("cursor_type", "row")
        kwargs.setdefault("zebra_stripes", True)
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._hosts: deque[dict[str, Any]] = deque(maxlen=HOST_LIMIT)

    def on_mount(self) -> None:  # type: ignore[no-untyped-def]
        self.add_columns("name", "os", "cpu", "mem free/total MB", "disk GB")

    def update_host(self, info: Any) -> None:
        self._hosts.appendleft(
            {
                "name": info.name,
                "os": info.os,
                "cpu": info.cpu_count,
                "mem": f"{info.memory_available_mb}/{info.memory_total_mb}",
                "disk": f"{info.disk_free_gb:.1f}",
            }
        )
        self.clear()
        for row in list(self._hosts)[:HOST_LIMIT]:
            self.add_row(
                row["name"],
                row["os"],
                str(row["cpu"]),
                row["mem"],
                row["disk"],
            )

    def upsert_host(self, info: Any) -> None:
        for i, entry in enumerate(self._hosts):
            if entry["name"] == info.name:
                self._hosts[i] = {
                    "name": info.name,
                    "os": info.os,
                    "cpu": info.cpu_count,
                    "mem": f"{info.memory_available_mb}/{info.memory_total_mb}",
                    "disk": f"{info.disk_free_gb:.1f}",
                }
                self.clear()
                for row in list(self._hosts)[:HOST_LIMIT]:
                    self.add_row(row["name"], row["os"], str(row["cpu"]), row["mem"], row["disk"])
                return
        self.update_host(info)


class ChangePanel(DataTable):
    """Recent file-change events."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("id", "change-panel")
        kwargs.setdefault("cursor_type", "row")
        kwargs.setdefault("zebra_stripes", True)
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._changes: deque[tuple[str, str, str]] = deque(maxlen=CHANGE_LIMIT)

    def on_mount(self) -> None:  # type: ignore[no-untyped-def]
        self.add_columns("time", "kind", "path")

    def update_change(self, ev: Any) -> None:
        from datetime import datetime as _dt

        ts = _dt.fromtimestamp(ev.timestamp).strftime("%H:%M:%S")
        self._changes.appendleft((ts, ev.kind, str(ev.path)))
        self.clear()
        for row in list(self._changes)[:CHANGE_LIMIT]:
            self.add_row(*row)

    def append_change(self, ev: Any) -> None:
        self.update_change(ev)


__all__ = ["BillingPanel", "HostPanel", "ChangePanel"]