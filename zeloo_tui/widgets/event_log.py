"""EventLog — RichLog wrapper that auto-truncates at 5000 lines."""

from __future__ import annotations

from textual.widgets import RichLog


class EventLog(RichLog):
    """Append-only scroll log for AgentEvent stream."""

    MAX_LINES = 5000

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("highlight", True)
        kwargs.setdefault("markup", True)
        kwargs.setdefault("wrap", False)
        kwargs.setdefault("id", "event-log")
        super().__init__(**kwargs)  # type: ignore[arg-type]

    def write_event(self, text: str) -> None:
        """Append a single line, truncating if we exceed MAX_LINES."""
        self.write(text)
        # ``RichLog`` doesn't expose a public line counter; we approximate
        # by trimming the underlying renderable lazily — the next write
        # call will discard stale content automatically when ``auto_scroll``
        # pushes past the buffer.
        if self.lines and len(self.lines) > self.MAX_LINES:
            # Drop the oldest quarter of the buffer to amortise cost.
            drop = len(self.lines) - self.MAX_LINES
            del self.lines[: drop + self.MAX_LINES // 4]


__all__ = ["EventLog"]