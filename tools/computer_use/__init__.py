"""Computer-use tools — control the local computer like a human user.

Provides 8 tools for desktop automation:

* computer_screenshot  — capture screen / window / region as base64 PNG
* computer_mouse_move  — move the mouse cursor
* computer_mouse_click — left / right / middle / double click
* computer_key_press   — type text or press a key combination
* computer_scroll      — scroll vertically or horizontally
* computer_window_list — list visible windows
* computer_window_focus— bring a window to the foreground
* computer_get_display — return screen size / DPI

All backends are pluggable; if the optional ``pyautogui`` package is
not installed, tools return a friendly error message instead of crashing.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "screenshot",
    "mouse",
    "keyboard",
    "scroll",
    "window_manager",
    "display",
    "state_tracker",
    "backends",
]


def is_backend_available() -> bool:
    """Return True if the GUI backend (pyautogui / pygetwindow) is available."""
    try:
        import pyautogui  # noqa: F401

        return True
    except ImportError:
        return False


def require_backend() -> tuple[Any, Any]:
    """Import and return the (pyautogui, pygetwindow) modules.

    Raises ``RuntimeError`` with an installation hint if either is missing.
    """
    try:
        import pyautogui  # type: ignore[import-untyped]
        import pygetwindow  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "Computer-use tools require pyautogui + pygetwindow. "
            "Install with: pip install pyautogui pygetwindow"
        ) from exc

    return pyautogui, pygetwindow