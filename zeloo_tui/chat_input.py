"""Multi-line TUI input — borrowed design from Hermes Agent's REPL.

Hermes Agent's TUI accepts ``\\`` followed by ``Enter`` to extend the
current input across lines (it gets concatenated before submit). The
bottom of the screen shows a small character / line counter so the
user always knows where they stand.

This module is a tiny mixin so :class:`zeloo_tui.chat_app.ZelooTUIChatApp`
can compose it without inheriting from a second base class.
"""

from __future__ import annotations

from dataclasses import dataclass


MAX_INPUT_CHARS = 4096  # matches Textual's default Input area size


@dataclass
class MultiLineState:
    """Tracks a multi-line input buffer + a continuation flag.

    The :class:`textual.widgets.Input` widget is single-line, so we
    expose ``/accumulate`` as a sentinel: when the user types ``\\`` at
    end of line and presses Enter, the newline + content is held
    here and prefixed onto the next submission. Plain Enter submits.
    """

    buffer: str = ""
    pending_continuation: bool = False
    history_hint: str = ""

    def feed(self, text: str) -> tuple[bool, str]:
        """Submit ``text``.

        Returns ``(submitted, final_text)`` where ``submitted=True``
        means the line was committed (the buffer was reset).
        ``submitted=False`` indicates the user typed ``\\`` at the end
        and we should keep accumulating.
        """
        full = (self.buffer + "\n" + text) if self.buffer else text

        # Detach continuation: if the line ends with an unescaped
        # backslash followed by a newline request, treat as continuation.
        # We use the convention that the *user* appends ``\\`` then
        # presses Enter — we see the backslash as part of the text.
        if full.endswith("\\") and not self.pending_continuation:
            # Strip the trailing backslash and keep going.
            self.buffer = full[:-1] + "\n"
            self.pending_continuation = True
            return False, ""

        # If we were already accumulating, this line continues the
        # previous block.
        if self.pending_continuation:
            self.buffer = full + "\n"
            # Stay in continuation mode if the user adds another ``\``.
            if text.endswith("\\"):
                self.buffer = full + "\n"
                return False, ""
            self.pending_continuation = False

        # Normal submission — clear the buffer.
        self.buffer = ""
        self.pending_continuation = False
        return True, full.rstrip("\\").rstrip()

    def status(self, current: str) -> str:
        """Return a one-line status string for the input footer."""
        chars = len(self.buffer) + len(current)
        lines = (self.buffer + current).count("\n") + 1
        if self.pending_continuation:
            mode = "MULTI"
        else:
            mode = "SINGLE"
        return f"[dim]{mode}[/dim]  [dim]chars={chars}/{MAX_INPUT_CHARS}  lines={lines}[/dim]"


__all__ = ["MultiLineState", "MAX_INPUT_CHARS"]