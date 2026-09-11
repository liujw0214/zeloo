"""Keyboard control — typing text and pressing key combinations."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class KeyboardActionResult:
    """Result from a keyboard action."""

    success: bool
    action: str
    text: str = ""
    keys: str = ""
    error: str = ""


def type_text(text: str, interval: float = 0.0) -> KeyboardActionResult:
    """Type *text* at the current cursor position.

    Args:
        text: The text to type. Special characters like ``\\n`` produce
            line breaks (Enter key).
        interval: Seconds between keystrokes. Default 0 (no delay).
    """
    try:
        from tools.computer_use import require_backend

        pyautogui, _ = require_backend()
    except RuntimeError as exc:
        return KeyboardActionResult(False, "type", error=str(exc))

    try:
        if interval > 0:
            pyautogui.typewrite(text, interval=interval)
        else:
            pyautogui.write(text)
        return KeyboardActionResult(True, "type", text=text)
    except Exception as exc:
        logger.exception("type_text failed")
        return KeyboardActionResult(False, "type", text=text, error=str(exc))


def press_key(key: str) -> KeyboardActionResult:
    """Press a single key (e.g. ``"enter"``, ``"tab"``, ``"escape"``)."""
    try:
        from tools.computer_use import require_backend

        pyautogui, _ = require_backend()
    except RuntimeError as exc:
        return KeyboardActionResult(False, "press", error=str(exc))

    try:
        pyautogui.press(key)
        return KeyboardActionResult(True, "press", keys=key)
    except Exception as exc:
        logger.exception("press_key failed")
        return KeyboardActionResult(False, "press", keys=key, error=str(exc))


def hotkey(*keys: str) -> KeyboardActionResult:
    """Press multiple keys together (e.g. ``"ctrl"``, ``"c"`` for copy)."""
    if not keys:
        return KeyboardActionResult(False, "hotkey", error="no keys provided")

    try:
        from tools.computer_use import require_backend

        pyautogui, _ = require_backend()
    except RuntimeError as exc:
        return KeyboardActionResult(False, "hotkey", error=str(exc))

    try:
        pyautogui.hotkey(*keys)
        return KeyboardActionResult(True, "hotkey", keys="+".join(keys))
    except Exception as exc:
        logger.exception("hotkey failed")
        return KeyboardActionResult(
            False,
            "hotkey",
            keys="+".join(keys),
            error=str(exc),
        )