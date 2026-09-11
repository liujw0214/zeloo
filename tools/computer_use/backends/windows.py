"""Windows backend — pywinauto + pyautogui for Windows 10/11."""

from __future__ import annotations

import base64
import io
import platform

from tools.computer_use.backends import (
    ComputerBackend,
    MouseResult,
    ScreenshotResult,
    WindowInfo,
)


class WindowsBackend(ComputerBackend):
    _pyautogui: type | None = None
    _pygetwindow: type | None = None
    _PIL_ImageGrab: type | None = None

    def __init__(self) -> None:
        self._system = "windows"

    def is_available(self) -> bool:
        if platform.system().lower() != "windows":
            return False
        try:
            import pyautogui  # noqa: F401
            import pygetwindow  # noqa: F401
            from PIL import ImageGrab  # noqa: F401
            return True
        except ImportError:
            return False

    def _ensure_modules(self) -> None:
        if self._pyautogui is not None:
            return
        try:
            import pyautogui as _pyautogui
            import pygetwindow as _pygetwindow
            from PIL import ImageGrab as _ImageGrab
            self._pyautogui = _pyautogui
            self._pygetwindow = _pygetwindow
            self._PIL_ImageGrab = _ImageGrab
        except ImportError as exc:
            raise RuntimeError(
                "Windows computer-use backend requires: pip install pyautogui pygetwindow Pillow"
            ) from exc

    def screenshot(self, region: str = "full") -> ScreenshotResult:
        try:
            self._ensure_modules()
        except RuntimeError as exc:
            return ScreenshotResult(error=str(exc))

        try:
            img = self._PIL_ImageGrab.grab()
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            encoded = base64.b64encode(buf.getvalue()).decode("ascii")
            return ScreenshotResult(
                base64=encoded,
                width=img.width,
                height=img.height,
            )
        except Exception as exc:  # noqa: BLE001
            return ScreenshotResult(error=str(exc))

    def mouse_move(self, x: int, y: int, relative: bool = False) -> MouseResult:
        try:
            self._ensure_modules()
        except RuntimeError as exc:
            return MouseResult(success=False, action="move", error=str(exc))

        try:
            if relative:
                self._pyautogui.moveRel(x, y)
            else:
                self._pyautogui.moveTo(x, y)
            pos = self._pyautogui.position()
            return MouseResult(
                success=True,
                action="move",
                final_x=int(pos.x),
                final_y=int(pos.y),
            )
        except Exception as exc:  # noqa: BLE001
            return MouseResult(success=False, action="move", error=str(exc))

    def mouse_click(
        self,
        x: int | None = None,
        y: int | None = None,
        button: str = "left",
        clicks: int = 1,
    ) -> MouseResult:
        try:
            self._ensure_modules()
        except RuntimeError as exc:
            return MouseResult(success=False, action="click", error=str(exc))

        try:
            self._pyautogui.click(x=x, y=y, clicks=clicks, button=button)
            pos = self._pyautogui.position()
            return MouseResult(
                success=True,
                action="click",
                final_x=int(pos.x),
                final_y=int(pos.y),
            )
        except Exception as exc:  # noqa: BLE001
            return MouseResult(success=False, action="click", error=str(exc))

    def mouse_drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        button: str = "left",
    ) -> MouseResult:
        try:
            self._ensure_modules()
        except RuntimeError as exc:
            return MouseResult(success=False, action="drag", error=str(exc))

        try:
            self._pyautogui.moveTo(start_x, start_y)
            self._pyautogui.dragTo(end_x, end_y, button=button)
            return MouseResult(
                success=True,
                action="drag",
                final_x=end_x,
                final_y=end_y,
            )
        except Exception as exc:  # noqa: BLE001
            return MouseResult(success=False, action="drag", error=str(exc))

    def key_press(self, key: str) -> bool:
        try:
            self._ensure_modules()
        except RuntimeError:
            return False
        try:
            self._pyautogui.press(key)
            return True
        except Exception:  # noqa: BLE001
            return False

    def text_input(self, text: str) -> bool:
        try:
            self._ensure_modules()
        except RuntimeError:
            return False
        try:
            self._pyautogui.write(text)
            return True
        except Exception:  # noqa: BLE001
            return False

    def hotkey(self, *keys: str) -> bool:
        if not keys:
            return False
        try:
            self._ensure_modules()
        except RuntimeError:
            return False
        try:
            self._pyautogui.hotkey(*keys)
            return True
        except Exception:  # noqa: BLE001
            return False

    def scroll(self, clicks: int, direction: str = "vertical") -> bool:
        try:
            self._ensure_modules()
        except RuntimeError:
            return False
        try:
            if direction == "vertical":
                self._pyautogui.scroll(clicks)
            else:
                self._pyautogui.hscroll(clicks)
            return True
        except Exception:  # noqa: BLE001
            return False

    def list_windows(self) -> list[WindowInfo]:
        try:
            self._ensure_modules()
        except RuntimeError:
            return []

        wins: list[WindowInfo] = []
        try:
            for w in self._pygetwindow.getAllWindows():
                if not w.title:
                    continue
                wins.append(
                    WindowInfo(
                        handle=w.handle,
                        title=w.title,
                        left=w.left,
                        top=w.top,
                        width=w.width,
                        height=w.height,
                        is_visible=getattr(w, "visible", True),
                    )
                )
        except Exception:  # noqa: BLE001
            pass
        return wins

    def focus_window(self, handle: int) -> bool:
        try:
            self._ensure_modules()
        except RuntimeError:
            return False
        try:
            wins = [w for w in self._pygetwindow.getAllWindows() if w.handle == handle]
            if not wins:
                return False
            win = wins[0]
            if win.isMinimized:
                win.restore()
            win.activate()
            return True
        except Exception:  # noqa: BLE001
            return False

    def get_display_info(self) -> dict:
        try:
            import ctypes
            user32 = ctypes.windll.user32
            width = user32.GetSystemMetrics(0)
            height = user32.GetSystemMetrics(1)
            return {
                "width": width,
                "height": height,
                "platform": "windows",
            }
        except Exception:  # noqa: BLE001
            return {"width": 1920, "height": 1080, "platform": "windows"}
