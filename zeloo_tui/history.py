"""TUI input history and slash-command completion.

Borrowed design from Hermes Agent's ``useInputHistory`` / ``useCompletion``
hooks (see docs/58 §5). The Textual port keeps the same cursor /
draft semantics but exposes plain Python helpers so they're easy to
unit-test without a Textual App.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass
class InputHistory:
    """Ring buffer of input lines with up/down navigation + draft restoration.

    Cursor semantics (Hermes Agent pattern):

    * ``cursor == -1`` ⇒ user is editing the live draft (no history entry).
    * ``cursor >= 0``  ⇒ user is browsing ``entries[-(cursor + 1)]``.

    Pressing ↑ on the draft saves it into ``self.draft``; pressing ↓ past
    the bottom restores it.
    """

    entries: list[str] = field(default_factory=list)
    cursor: int = -1
    draft: str = ""
    max_size: int = 500

    def push(self, line: str) -> None:
        """Append a line; skip whitespace-only, dedup consecutive, cap at ``max_size``."""
        if not line or not line.strip():
            return
        if self.entries and self.entries[-1] == line:
            return
        self.entries.append(line)
        if len(self.entries) > self.max_size:
            self.entries = self.entries[-self.max_size :]
        # New entry invalidates any in-progress history walk.
        self.cursor = -1
        self.draft = ""

    def up(self, current_text: str) -> str | None:
        if not self.entries:
            return None
        if self.cursor == -1:
            self.draft = current_text
        if self.cursor < len(self.entries) - 1:
            self.cursor += 1
        return self.entries[-(self.cursor + 1)]

    def down(self, current_text: str) -> str | None:  # noqa: ARG002 — parity with up()
        if self.cursor > -1:
            self.cursor -= 1
            if self.cursor == -1:
                return self.draft
            return self.entries[-(self.cursor + 1)]
        return None

    def reset(self) -> None:
        self.cursor = -1
        self.draft = ""


# ---------------------------------------------------------------------------
# Slash-command completion
# ---------------------------------------------------------------------------


SLASH_COMMANDS: list[dict[str, str]] = [
    {
        "name": "/help",
        "description": "Show the available commands and key bindings",
        "example": "/help",
    },
    {
        "name": "/model",
        "description": "Switch the active LLM model",
        "example": "/model gpt-4o",
    },
    {
        "name": "/session",
        "description": "Show the current session id",
        "example": "/session",
    },
    {
        "name": "/review",
        "description": "Trigger a background review of the current session",
        "example": "/review",
    },
    {
        "name": "/plugins",
        "description": "List loaded plugins and their tools",
        "example": "/plugins",
    },
    {
        "name": "/stats",
        "description": "Show cache hit / miss statistics",
        "example": "/stats",
    },
    {
        "name": "/clear",
        "description": "Clear the EventLog panel",
        "example": "/clear",
    },
    {
        "name": "/skin",
        "description": "Switch the active skin theme",
        "example": "/skin starlight",
    },
]


def filter_slash_commands(query: str) -> list[dict[str, str]]:
    """Return slash commands that match ``query`` as a prefix.

    ``query`` must start with ``/``; everything else yields ``[]``.
    Matching is case-insensitive.
    """
    q = (query or "").lstrip()
    if not q.startswith("/"):
        return []
    return [c for c in SLASH_COMMANDS if c["name"].lower().startswith(q.lower())]


def iter_slash_commands() -> Iterable[dict[str, str]]:
    """Iterate the full slash-command catalogue."""
    return iter(SLASH_COMMANDS)


__all__ = [
    "InputHistory",
    "SLASH_COMMANDS",
    "filter_slash_commands",
    "iter_slash_commands",
]