"""Real-time billing/cost display for the TUI gateway.

Listens to `AgentEvent` callbacks and renders a rolling cost summary.
No persistence — values are recomputed on each call from the usage tracker.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zeloo_cli.observability import UsageTracker

logger = logging.getLogger(__name__)


@dataclass
class BillingSnapshot:
    period: str
    total_cost_usd: float
    total_input_tokens: int
    total_output_tokens: int
    total_calls: int
    top_providers: list[tuple[str, int]]

    def render(self) -> str:
        lines = [
            f"== Billing ({self.period}) ==",
            f"  Calls:       {self.total_calls}",
            f"  Input tok:   {self.total_input_tokens}",
            f"  Output tok:  {self.total_output_tokens}",
            f"  Cost USD:    ${self.total_cost_usd:.4f}",
            "  Top providers:",
        ]
        for name, count in self.top_providers:
            lines.append(f"    - {name}: {count}")
        return "\n".join(lines)


class BillingView:
    def __init__(self, tracker: UsageTracker | None = None, period: str = "day") -> None:
        self._tracker = tracker
        self.period = period
        self._last_snapshot: BillingSnapshot | None = None

    def snapshot(self, period: str | None = None) -> BillingSnapshot:
        from zeloo_cli.observability import UsageTracker

        tracker = self._tracker or UsageTracker()
        summary = tracker.get_summary(period or self.period)
        snap = BillingSnapshot(
            period=summary.period,
            total_cost_usd=summary.total_cost_usd,
            total_input_tokens=summary.total_input_tokens,
            total_output_tokens=summary.total_output_tokens,
            total_calls=summary.total_calls,
            top_providers=summary.top_providers,
        )
        self._last_snapshot = snap
        return snap

    def render(self, period: str | None = None) -> str:
        return self.snapshot(period).render()

    def on_event(self, event) -> None:  # AgentEvent-like
        if event.type.value == "finish":
            try:
                self.snapshot()
            except Exception:
                logger.exception("Failed to refresh billing on finish")
