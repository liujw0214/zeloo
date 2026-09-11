"""Display information — screen size, DPI, mouse position."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DisplayInfo:
    """Metadata about the primary display."""

    width: int
    height: int
    mouse_x: int
    mouse_y: int
    backend_available: bool = True
    error: str = ""


def get_display_info() -> DisplayInfo:
    """Return :class:`DisplayInfo` for the primary display and current mouse pos."""
    try:
        from tools.computer_use import require_backend

        pyautogui, _ = require_backend()
    except RuntimeError as exc:
        return DisplayInfo(0, 0, 0, 0, backend_available=False, error=str(exc))

    try:
        size = pyautogui.size()
        pos = pyautogui.position()
        return DisplayInfo(
            width=int(size.width),
            height=int(size.height),
            mouse_x=int(pos.x),
            mouse_y=int(pos.y),
            backend_available=True,
        )
    except Exception as exc:
        logger.exception("get_display_info failed")
        return DisplayInfo(0, 0, 0, 0, backend_available=False, error=str(exc))