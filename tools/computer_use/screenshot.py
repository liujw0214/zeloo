"""Screen capture — full screen, window, or rectangular region.

Returns a :class:`ScreenshotResult` with base64-encoded PNG bytes plus
width / height metadata.
"""

from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ScreenshotResult:
    """A captured screenshot."""

    base64: str
    width: int
    height: int
    format: str = "png"
    region: str = "full"
    error: str = ""


def capture_screenshot(
    region: str = "full",
    window_id: int | None = None,
    rect: tuple[int, int, int, int] | None = None,
) -> ScreenshotResult:
    """Capture the screen and return a :class:`ScreenshotResult`.

    Args:
        region: One of ``"full"``, ``"window"``, or ``"rect"``.
        window_id: When *region* is ``"window"``, the OS window id to capture.
        rect: When *region* is ``"rect"``, a ``(x, y, width, height)`` tuple.

    Returns:
        A :class:`ScreenshotResult` with base64 PNG and dimensions. On
        failure the result has ``error`` set and empty base64.
    """
    try:
        from tools.computer_use import require_backend

        pyautogui, _ = require_backend()
    except RuntimeError as exc:
        return ScreenshotResult(base64="", width=0, height=0, error=str(exc))

    try:
        if region == "window" and window_id is not None:
            try:
                import pygetwindow  # type: ignore[import-untyped]

                win = pygetwindow.getWindowsWithTitle("")[window_id]
            except (IndexError, Exception):
                win = None
            if win is None:
                return ScreenshotResult(
                    base64="", width=0, height=0, error=f"Window id {window_id} not found"
                )
            x, y, w, h = win.left, win.top, win.width, win.height
            img = pyautogui.screenshot(region=(x, y, w, h))
        elif region == "rect" and rect is not None:
            img = pyautogui.screenshot(region=rect)
        else:
            img = pyautogui.screenshot()

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        encoded = base64.b64encode(buf.getvalue()).decode("ascii")

        return ScreenshotResult(
            base64=encoded,
            width=img.width,
            height=img.height,
            region=region,
        )
    except Exception as exc:
        logger.exception("screenshot failed")
        return ScreenshotResult(base64="", width=0, height=0, error=str(exc))