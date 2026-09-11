"""Computer-use tool registrations.

Wraps the pure functions in :mod:`tools.computer_use.*` as Agent-callable
tools using the ``@tool`` decorator so the Agent can drive the mouse,
keyboard, screen, and windows through natural language.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from tools.base import get_registry, tool

from . import display as _display
from . import keyboard as _keyboard
from . import mouse as _mouse
from . import screenshot as _screenshot
from . import scroll as _scroll
from . import window_manager as _wm

logger = logging.getLogger(__name__)


@tool(
    name="computer_screenshot",
    description="Capture a screenshot of the entire screen, a specific window, or a rectangular region.",  # noqa: E501
    toolset="computer_use",
)
def computer_screenshot(
    region: str = "full",
    window_id: int | None = None,
    rect: tuple[int, int, int, int] | None = None,
) -> dict[str, Any]:
    """Capture screen and return base64 PNG + dimensions."""
    result = _screenshot.capture_screenshot(region=region, window_id=window_id, rect=rect)
    return asdict(result)


@tool(
    name="computer_mouse_move",
    description="Move the mouse cursor to absolute (x, y) coordinates, "
    "or move relative to its current position.",
    toolset="computer_use",
)
def computer_mouse_move(
    x: int, y: int, relative: bool = False, duration: float = 0.0
) -> dict[str, Any]:
    result = _mouse.move_mouse(x=x, y=y, relative=relative, duration=duration)
    return asdict(result)


@tool(
    name="computer_mouse_click",
    description="Click the mouse at the given coordinates (or at current position if coords omitted).",  # noqa: E501
    toolset="computer_use",
)
def computer_mouse_click(
    x: int | None = None,
    y: int | None = None,
    button: str = "left",
    clicks: int = 1,
) -> dict[str, Any]:
    result = _mouse.click_mouse(x=x, y=y, button=button, clicks=clicks)
    return asdict(result)


@tool(
    name="computer_mouse_drag",
    description="Drag from (start_x, start_y) to (end_x, end_y) over a duration in seconds.",
    toolset="computer_use",
)
def computer_mouse_drag(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    duration: float = 1.0,
    button: str = "left",
) -> dict[str, Any]:
    result = _mouse.drag_mouse(
        start_x=start_x, start_y=start_y,
        end_x=end_x, end_y=end_y,
        duration=duration, button=button,
    )
    return asdict(result)


@tool(
    name="computer_keyboard_type",
    description="Type text at the current cursor position. Use '\\n' in text for line breaks.",
    toolset="computer_use",
)
def computer_keyboard_type(text: str, interval: float = 0.0) -> dict[str, Any]:
    result = _keyboard.type_text(text=text, interval=interval)
    return asdict(result)


@tool(
    name="computer_keyboard_press",
    description="Press a single key (e.g. 'enter', 'tab', 'escape', 'f5').",
    toolset="computer_use",
)
def computer_keyboard_press(key: str) -> dict[str, Any]:
    result = _keyboard.press_key(key=key)
    return asdict(result)


@tool(
    name="computer_keyboard_hotkey",
    description="Press multiple keys together as a hotkey (e.g. ('ctrl', 'c') for copy).",
    toolset="computer_use",
)
def computer_keyboard_hotkey(*keys: str) -> dict[str, Any]:
    result = _keyboard.hotkey(*keys)
    return asdict(result)


@tool(
    name="computer_scroll",
    description="Scroll vertically or horizontally at the current (or specified) cursor position.",
    toolset="computer_use",
)
def computer_scroll(
    clicks: int,
    x: int | None = None,
    y: int | None = None,
    direction: str = "vertical",
) -> dict[str, Any]:
    result = _scroll.scroll(clicks=clicks, x=x, y=y, direction=direction)
    return asdict(result)


@tool(
    name="computer_window_list",
    description="List all visible top-level windows with their position, size, and active state.",
    toolset="computer_use",
)
def computer_window_list() -> dict[str, Any]:
    result = _wm.list_windows()
    return asdict(result)


@tool(
    name="computer_window_focus",
    description="Bring a window matching the given title substring to the foreground.",
    toolset="computer_use",
)
def computer_window_focus(title: str) -> dict[str, Any]:
    success = _wm.focus_window(title=title)
    return {"success": success, "title": title}


@tool(
    name="computer_get_display",
    description="Get information about the primary display: screen size, "
    "mouse position, and backend availability.",
    toolset="computer_use",
)
def computer_get_display() -> dict[str, Any]:
    info = _display.get_display_info()
    return asdict(info)


COMPUTER_USE_TOOLS: list[str] = [
    "computer_screenshot",
    "computer_mouse_move",
    "computer_mouse_click",
    "computer_mouse_drag",
    "computer_keyboard_type",
    "computer_keyboard_press",
    "computer_keyboard_hotkey",
    "computer_scroll",
    "computer_window_list",
    "computer_window_focus",
    "computer_get_display",
]


def is_computer_use_registered() -> bool:
    """Return True iff all computer_use tools are present in the global registry."""
    registry = get_registry()
    return all(registry.get(name) is not None for name in COMPUTER_USE_TOOLS)
