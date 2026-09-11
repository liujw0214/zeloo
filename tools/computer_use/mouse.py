"""Mouse control — move / click / drag."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class MouseActionResult:
    """Result from a mouse action."""

    success: bool
    action: str
    error: str = ""
    final_x: int = 0
    final_y: int = 0


def move_mouse(x: int, y: int, relative: bool = False, duration: float = 0.0) -> MouseActionResult:
    """Move the cursor to absolute coords or relative offset."""
    try:
        from tools.computer_use import require_backend

        pyautogui, _ = require_backend()
    except RuntimeError as exc:
        return MouseActionResult(False, "move", error=str(exc))

    try:
        if relative:
            pyautogui.moveRel(x, y, duration=duration)
        else:
            pyautogui.moveTo(x, y, duration=duration)
        return MouseActionResult(True, "move", final_x=x, final_y=y)
    except Exception as exc:
        logger.exception("mouse move failed")
        return MouseActionResult(False, "move", error=str(exc))


def click_mouse(
    x: int | None = None,
    y: int | None = None,
    button: str = "left",
    clicks: int = 1,
) -> MouseActionResult:
    """Click at absolute (x, y) or current position.

    Args:
        x: Optional x coord. If None, click at current cursor position.
        y: Optional y coord. If None, click at current cursor position.
        button: ``"left"``, ``"right"``, or ``"middle"``.
        clicks: Number of clicks (use 2 for double-click).
    """
    if button not in {"left", "right", "middle"}:
        return MouseActionResult(False, "click", error=f"invalid button: {button}")

    try:
        from tools.computer_use import require_backend

        pyautogui, _ = require_backend()
    except RuntimeError as exc:
        return MouseActionResult(False, "click", error=str(exc))

    try:
        if x is None or y is None:
            pyautogui.click(clicks=clicks, button=button)
        else:
            pyautogui.click(x, y, clicks=clicks, button=button)

        final = pyautogui.position()
        return MouseActionResult(
            True,
            "click",
            final_x=int(final.x),
            final_y=int(final.y),
        )
    except Exception as exc:
        logger.exception("mouse click failed")
        return MouseActionResult(False, "click", error=str(exc))


def drag_mouse(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    duration: float = 1.0,
    button: str = "left",
) -> MouseActionResult:
    """Drag from (start_x, start_y) to (end_x, end_y) over *duration* seconds."""
    if button not in {"left", "right", "middle"}:
        return MouseActionResult(False, "drag", error=f"invalid button: {button}")

    try:
        from tools.computer_use import require_backend

        pyautogui, _ = require_backend()
    except RuntimeError as exc:
        return MouseActionResult(False, "drag", error=str(exc))

    try:
        pyautogui.moveTo(start_x, start_y)
        pyautogui.dragTo(end_x, end_y, duration=duration, button=button)
        return MouseActionResult(True, "drag", final_x=end_x, final_y=end_y)
    except Exception as exc:
        logger.exception("mouse drag failed")
        return MouseActionResult(False, "drag", error=str(exc))