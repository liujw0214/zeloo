"""Computer-use backends — platform-specific implementations.

Each backend implements the :class:`ComputerBackend` protocol for a specific
OS. The factory function :func:`get_backend` auto-detects the current platform
and returns the appropriate backend instance.

Usage::

    from tools.computer_use.backends import get_backend

    backend = get_backend()
    result = backend.screenshot()
    backend.mouse_move(100, 200)
    windows = backend.list_windows()
"""

from __future__ import annotations

import platform
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

__all__ = [
    "get_backend",
    "ComputerBackend",
    "ScreenshotResult",
    "MouseResult",
    "WindowInfo",
]


@dataclass
class ScreenshotResult:
    base64: str = ""
    width: int = 0
    height: int = 0
    format: str = "png"
    error: str = ""


@dataclass
class MouseResult:
    success: bool = False
    action: str = ""
    error: str = ""
    final_x: int = 0
    final_y: int = 0


@dataclass
class WindowInfo:
    handle: int = 0
    title: str = ""
    left: int = 0
    top: int = 0
    width: int = 0
    height: int = 0
    is_visible: bool = True


class ComputerBackend(ABC):
    """Protocol for platform-specific computer-control backends."""

    @abstractmethod
    def screenshot(self, region: str = "full") -> ScreenshotResult:
        """Capture the screen. region is 'full', 'window', or 'rect'."""
        ...

    @abstractmethod
    def mouse_move(self, x: int, y: int, relative: bool = False) -> MouseResult:
        """Move the mouse cursor."""
        ...

    @abstractmethod
    def mouse_click(
        self,
        x: int | None = None,
        y: int | None = None,
        button: str = "left",
        clicks: int = 1,
    ) -> MouseResult:
        """Click the mouse."""
        ...

    @abstractmethod
    def mouse_drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        button: str = "left",
    ) -> MouseResult:
        """Drag the mouse."""
        ...

    @abstractmethod
    def key_press(self, key: str) -> bool:
        """Press a single key."""
        ...

    @abstractmethod
    def text_input(self, text: str) -> bool:
        """Type a string of text."""
        ...

    @abstractmethod
    def hotkey(self, *keys: str) -> bool:
        """Press a key combination."""
        ...

    @abstractmethod
    def scroll(self, clicks: int, direction: str = "vertical") -> bool:
        """Scroll the mouse wheel."""
        ...

    @abstractmethod
    def list_windows(self) -> list[WindowInfo]:
        """Return all visible top-level windows."""
        ...

    @abstractmethod
    def focus_window(self, handle: int) -> bool:
        """Bring a window to the foreground by handle."""
        ...

    @abstractmethod
    def get_display_info(self) -> dict[str, Any]:
        """Return display size, DPI, and scaling info."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this backend can run on the current platform."""
        ...


def get_backend() -> ComputerBackend:
    """Return the appropriate ComputerBackend for the current platform.

    Raises:
        RuntimeError: If no backend is available for this platform.
    """
    system = platform.system().lower()

    if system == "windows":
        from tools.computer_use.backends.windows import WindowsBackend

        return WindowsBackend()
    if system == "darwin":
        from tools.computer_use.backends.macos import MacOSBackend

        return MacOSBackend()
    if system == "linux":
        from tools.computer_use.backends.linux import LinuxBackend

        return LinuxBackend()

    raise RuntimeError(
        f"No computer-use backend available for platform: {platform.system()}. "
        "Supported platforms: Windows, macOS, Linux."
    )
