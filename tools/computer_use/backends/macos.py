"""macOS backend — pyobjc-framework for macOS."""

from __future__ import annotations

import platform

from tools.computer_use.backends import (
    ComputerBackend,
    MouseResult,
    ScreenshotResult,
    WindowInfo,
)


class MacOSBackend(ComputerBackend):
    _pyautogui: type | None = None

    def __init__(self) -> None:
        self._system = "darwin"

    def is_available(self) -> bool:
        if platform.system().lower() != "darwin":
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
                "macOS computer-use backend requires: pip install pyautogui"
            ) from exc

    def screenshot(self, region: str = "full") -> ScreenshotResult:
        try:
            self._ensure_modules()
        except RuntimeError as exc:
            return ScreenshotResult(error=str(exc))

        try:
            import Quartz
            from PIL import Image

            main_display = Quartz.CGMainDisplayID()
            if region == "full":
                image_ref = Quartz.CGDisplayCreateImage(main_display)
            else:
                return ScreenshotResult(error="region截取在 macOS 后端暂不支持")

            if image_ref is None:
                return ScreenshotResult(error="Failed to capture screen")

            width = Quartz.CGImageGetWidth(image_ref)
            height = Quartz.CGImageGetHeight(image_ref)
            image = Image.frombuffer(
                "RGBA", (width, height),
                Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(image_ref)),
                "raw", "BGRA", width * 4, width * 4 * height
            )
            image = image.convert("RGB")

            import base64
            import io
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            encoded = base64.b64encode(buf.getvalue()).decode("ascii")
            return ScreenshotResult(
                base64=encoded,
                width=width,
                height=height,
            )
        except ImportError as exc:
            return ScreenshotResult(error=f"缺少依赖: {exc}")
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
            import Quartz
        except ImportError:
            return []
        wins: list[WindowInfo] = []
        try:
            options = Quartz.kCGWindowListOptionOnScreenOnly
            window_list = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)
            for win in window_list:
                layer = win.get("kCGWindowLayer", 0)
                if layer != 0:
                    continue
                bounds = win.get("kCGWindowBounds", {})
                title = win.get("kCGWindowName", "")
                owner = win.get("kCGWindowOwnerName", "")
                window_id = win.get("kCGWindowNumber", 0)
                if not title:
                    continue
                wins.append(
                    WindowInfo(
                        handle=window_id,
                        title=f"{owner}: {title}" if owner else title,
                        left=int(bounds.get("X", 0)),
                        top=int(bounds.get("Y", 0)),
                        width=int(bounds.get("Width", 0)),
                        height=int(bounds.get("Height", 0)),
                    )
                )
        except Exception:  # noqa: BLE001
            pass
        return wins

    def focus_window(self, handle: int) -> bool:
        return False

    def get_display_info(self) -> dict:
        try:
            import Quartz
            display_id = Quartz.CGMainDisplayID()
            width = Quartz.CGDisplayPixelsWide(display_id)
            height = Quartz.CGDisplayPixelsHigh(display_id)
            return {
                "width": width,
                "height": height,
                "platform": "darwin",
            }
        except Exception:  # noqa: BLE001
            return {"width": 1440, "height": 900, "platform": "darwin"}
