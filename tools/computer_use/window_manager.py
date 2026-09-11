"""Window manager — list, focus, and inspect desktop windows."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class WindowInfo:
    """Metadata for a desktop window."""

    title: str
    left: int
    top: int
    width: int
    height: int
    is_active: bool = False
    is_visible: bool = True


@dataclass
class WindowListResult:
    """Result of listing windows."""

    success: bool
    windows: list[WindowInfo] = field(default_factory=list)
    count: int = 0
    error: str = ""


def list_windows() -> WindowListResult:
    """Return all visible top-level windows."""
    try:
        from tools.computer_use import require_backend

        _, pygetwindow = require_backend()
    except RuntimeError as exc:
        return WindowListResult(False, error=str(exc))

    try:
        active = pygetwindow.getActiveWindow()
        active_title = active.title if active else ""
        wins: list[WindowInfo] = []
        for w in pygetwindow.getAllWindows():
            if not w.title:
                continue
            wins.append(
                WindowInfo(
                    title=w.title,
                    left=w.left,
                    top=w.top,
                    width=w.width,
                    height=w.height,
                    is_active=(w.title == active_title),
                    is_visible=w.visible,
                )
            )
        return WindowListResult(True, wins, len(wins))
    except Exception as exc:
        logger.exception("list_windows failed")
        return WindowListResult(False, error=str(exc))


def focus_window(title: str) -> bool:
    """Bring a window with the given *title* to the foreground.

    Returns True if a matching window was found and focused.
    """
    try:
        from tools.computer_use import require_backend

        _, pygetwindow = require_backend()
    except RuntimeError:
        return False

    try:
        matches = pygetwindow.getWindowsWithTitle(title)
        if not matches:
            return False
        win = matches[0]
        if win.isMinimized:
            win.restore()
        win.activate()
        return True
    except Exception as exc:
        logger.exception("focus_window failed: %s", exc)
        return False


def get_window_by_title(title: str) -> WindowInfo | None:
    """Return :class:`WindowInfo` for the first window matching *title*."""
    try:
        from tools.computer_use import require_backend

        _, pygetwindow = require_backend()
    except RuntimeError:
        return None

    matches = pygetwindow.getWindowsWithTitle(title)
    if not matches:
        return None
    w = matches[0]
    return WindowInfo(
        title=w.title,
        left=w.left,
        top=w.top,
        width=w.width,
        height=w.height,
        is_active=w.isActive,
        is_visible=w.visible,
    )