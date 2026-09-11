"""Linux backend — pyautogui for Linux (X11 / Wayland via XDG)."""

from __future__ import annotations

import platform

from tools.computer_use.backends import (
    ComputerBackend,
    MouseResult,
    ScreenshotResult,
    WindowInfo,
)


class LinuxBackend(ComputerBackend):
    _pyautogui: type | None = None

    def __init__(self) -> None:
        self._system = "linux"

    def is_available(self) -> bool:
        if platform.system().lower() != "linux":
            return False
        try:
            import pyautogui  # noqa: F401
            return True
        except ImportError:
            return False

    def _ensure_modules(self) -> None:
        if self._pyautogui is not None:
            return
        try:
            import pyautogui as _pyautogui
            _pyautogui.FAILSAFE = True
            self._pyautogui = _pyautogui
        except ImportError as exc:
            raise RuntimeError(
                "Linux computer-use backend requires: pip install pyautogui"
            ) from exc

    def screenshot(self, region: str = "full") -> ScreenshotResult:
        try:
            self._ensure_modules()
        except RuntimeError as exc:
            return ScreenshotResult(error=str(exc))

        try:
            img = self._pyautogui.screenshot()
            import base64
            import io
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
            import subprocess
            result = subprocess.run(
                ["xdotool", "search", "--onlyvisible", "--name", "."],
                capture_output=True,
                text=True,
                timeout=5,
            )
            wins: list[WindowInfo] = []
            for line in result.stdout.splitlines():
                try:
                    handle = int(line.strip())
                    wins.append(
                        WindowInfo(handle=handle, title=f"Window {handle}")
                    )
                except ValueError:
                    continue
            return wins
        except FileNotFoundError:
            return []
        except Exception:  # noqa: BLE001
            return []

    def focus_window(self, handle: int) -> bool:
        try:
            import subprocess
            subprocess.run(
                ["xdotool", "windowactivate", str(handle)],
                capture_output=True,
                timeout=5,
            )
            return True
        except Exception:  # noqa: BLE001
            return False

    def get_display_info(self) -> dict:
        try:
            import subprocess
            result = subprocess.run(
                ["xdotool", "getdisplaygeometry"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            parts = result.stdout.strip().split()
            if len(parts) == 2:
                return {
                    "width": int(parts[0]),
                    "height": int(parts[1]),
                    "platform": "linux",
                }
        except Exception:  # noqa: BLE001
            pass
        return {"width": 1920, "height": 1080, "platform": "linux"}
