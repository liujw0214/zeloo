"""Scroll control — vertical and horizontal scrolling."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ScrollResult:
    """Result of a scroll action."""

    success: bool
    clicks: int
    direction: str
    x: int
    y: int
    error: str = ""


def scroll(
    clicks: int,
    x: int | None = None,
    y: int | None = None,
    direction: str = "vertical",
) -> ScrollResult:
    """Scroll at the current (or specified) cursor position.

    Args:
        clicks: Number of wheel clicks. Positive = up / right, negative = down / left.
        x: Optional x coord to move before scrolling.
        y: Optional y coord to move before scrolling.
        direction: ``"vertical"`` (default) or ``"horizontal"``.
    """
    if direction not in {"vertical", "horizontal"}:
        return ScrollResult(
            False,
            clicks,
            direction,
            x or 0,
            y or 0,
            error=f"invalid direction: {direction}",
        )

    try:
        from tools.computer_use import require_backend

        pyautogui, _ = require_backend()
    except RuntimeError as exc:
        return ScrollResult(False, clicks, direction, x or 0, y or 0, error=str(exc))

    try:
        if x is not None and y is not None:
            pyautogui.moveTo(x, y)

        if direction == "vertical":
            pyautogui.scroll(clicks)
        else:
            pyautogui.hscroll(clicks)

        pos = pyautogui.position()
        return ScrollResult(
            True,
            clicks,
            direction,
            int(pos.x),
            int(pos.y),
        )
    except Exception as exc:
        logger.exception("scroll failed")
        return ScrollResult(False, clicks, direction, x or 0, y or 0, error=str(exc))