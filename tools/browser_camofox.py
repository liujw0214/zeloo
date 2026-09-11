"""Camofox browser adapter - Firefox automation via camofox library.

This module provides a Python adapter for Camofox, a Firefox automation
library similar to Playwright but specifically designed for Firefox/Gecko engine.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import shutil
import sys
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from camofox import CamofoxPage
    from camofox import CamofoxElement as CamofoxElementLib

logger = logging.getLogger(__name__)

_CAMOFOX_SPEC: importlib.util.ModuleSpec | None = importlib.util.find_spec("camofox")
CAMOFOX_AVAILABLE: bool = _CAMOFOX_SPEC is not None


@dataclass
class CamofoxSession:
    """Represents an active Camofox browser session."""

    session_id: str
    page: Any
    adapter: "CamofoxAdapter"
    _closed: bool = field(default=False, repr=False)

    def navigate(self, url: str, timeout: float = 30.0) -> bool:
        if self._closed:
            raise CamofoxError("Session is closed")
        try:
            self.page.goto(url, timeout=timeout * 1000)
            logger.info("Navigated to %s", url)
            return True
        except TimeoutError as e:
            raise CamofoxTimeoutError(f"Navigation to {url} timed out after {timeout}s") from e
        except Exception as e:
            raise CamofoxError(f"Navigation failed: {e}") from e

    def screenshot(self, format: Literal["png", "jpeg"] = "png", full_page: bool = False) -> bytes:
        if self._closed:
            raise CamofoxError("Session is closed")
        try:
            return self.page.screenshot(full_page=full_page)
        except Exception as e:
            raise CamofoxError(f"Screenshot failed: {e}") from e

    def evaluate(self, script: str) -> Any:
        if self._closed:
            raise CamofoxError("Session is closed")
        try:
            return self.page.evaluate(script)
        except Exception as e:
            raise CamofoxError(f"JavaScript evaluation failed: {e}") from e

    def get_element(self, selector: str) -> "CamofoxElement":
        if self._closed:
            raise CamofoxError("Session is closed")
        try:
            element = self.page.query_selector(selector)
            if element is None:
                raise CamofoxError(f"Element not found: {selector}")
            return CamofoxElement(element, self)
        except CamofoxError:
            raise
        except Exception as e:
            raise CamofoxError(f"Failed to get element {selector}: {e}") from e

    def get_elements(self, selector: str) -> list["CamofoxElement"]:
        if self._closed:
            raise CamofoxError("Session is closed")
        try:
            return [CamofoxElement(el, self) for el in self.page.query_selector_all(selector)]
        except Exception as e:
            raise CamofoxError(f"Failed to get elements {selector}: {e}") from e

    def get_cookies(self) -> list[dict[str, Any]]:
        if self._closed:
            raise CamofoxError("Session is closed")
        return self.page.cookies

    def set_cookies(self, cookies: list[dict[str, Any]]) -> None:
        if self._closed:
            raise CamofoxError("Session is closed")
        self.page.cookies = cookies

    def get_current_url(self) -> str:
        if self._closed:
            raise CamofoxError("Session is closed")
        return self.page.url

    def get_title(self) -> str:
        if self._closed:
            raise CamofoxError("Session is closed")
        return self.page.title

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.page.close()
        except Exception as e:
            logger.warning("Error closing session: %s", e)


@dataclass
class CamofoxElement:
    element: Any
    session: CamofoxSession

    def click(self) -> None:
        try:
            self.element.click()
        except Exception as e:
            raise CamofoxError(f"Element click failed: {e}") from e

    def send_keys(self, text: str) -> None:
        try:
            self.element.type(text)
        except Exception as e:
            raise CamofoxError(f"Send keys failed: {e}") from e

    def get_text(self) -> str:
        try:
            return self.element.text_content or ""
        except Exception as e:
            raise CamofoxError(f"Failed to get text: {e}") from e

    def get_attribute(self, name: str) -> str | None:
        try:
            return self.element.get_attribute(name)
        except Exception as e:
            raise CamofoxError(f"Failed to get attribute {name}: {e}") from e

    def is_visible(self) -> bool:
        try:
            return self.element.is_visible()
        except Exception:
            return False

    def screenshot(self) -> bytes:
        try:
            return self.element.screenshot()
        except Exception as e:
            raise CamofoxError(f"Element screenshot failed: {e}") from e


class CamofoxAdapter:
    def __init__(
        self,
        binary_path: str | None = None,
        headless: bool = True,
        profile_path: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.binary_path = binary_path
        self.headless = headless
        self.profile_path = profile_path
        self.timeout = timeout
        self._camofox: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._session: CamofoxSession | None = None
        self._connected: bool = False
        self._lock = threading.Lock()

    def connect(self) -> CamofoxSession:
        if not CAMOFOX_AVAILABLE:
            raise CamofoxError("Camofox is not installed. Install with: pip install camofox")

        with self._lock:
            if self._connected and self._session:
                return self._session
            try:
                from camofox import Camofox
                self._camofox = Camofox()
                firefox_kwargs: dict[str, Any] = {"headless": self.headless}
                if self.binary_path:
                    firefox_kwargs["executable_path"] = self.binary_path
                else:
                    _firefox_binary = get_firefox_binary()
                    if _firefox_binary:
                        firefox_kwargs["executable_path"] = _firefox_binary
                if self.profile_path:
                    firefox_kwargs["user_data_dir"] = self.profile_path
                self._browser = self._camofox.firefox(**firefox_kwargs)
                self._context = self._browser.new_context(viewport={"width": 1280, "height": 720})
                page = self._context.new_page()
                page.set_default_timeout(self.timeout * 1000)
                session_id = str(uuid.uuid4())
                self._session = CamofoxSession(session_id=session_id, page=page, adapter=self)
                self._connected = True
                logger.info("Camofox connected session_id=%s headless=%s", session_id, self.headless)
                return self._session
            except Exception as e:
                logger.error("Failed to connect to Camofox: %s", e)
                self._cleanup()
                raise CamofoxConnectionError(f"Failed to connect: {e}") from e

    def disconnect(self) -> None:
        with self._lock:
            self._cleanup()

    def is_connected(self) -> bool:
        return self._connected and self._session is not None and not self._session._closed

    def _cleanup(self) -> None:
        self._connected = False
        if self._session and not self._session._closed:
            try:
                self._session._closed = True
            except Exception:
                pass
        self._session = None
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
            self._context = None
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._camofox:
            try:
                self._camofox.stop()
            except Exception:
                pass
            self._camofox = None

    async def __aenter__(self) -> "CamofoxAdapter":
        self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.disconnect()

    def __enter__(self) -> "CamofoxAdapter":
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.disconnect()


class CamofoxError(RuntimeError):
    pass


class CamofoxConnectionError(CamofoxError):
    pass


class CamofoxTimeoutError(CamofoxError):
    pass


def install_camofox() -> bool:
    if CAMOFOX_AVAILABLE:
        logger.info("Camofox is installed")
        return True
    logger.warning("Camofox is not installed. Install with: pip install camofox")
    return False


def get_firefox_binary() -> str | None:
    """Find the system Firefox binary path."""
    for name in ["firefox", "firefox.exe", "Firefox.app"]:
        path = shutil.which(name)
        if path:
            logger.debug("Found Firefox at: %s", path)
            return path

    if sys.platform == "win32":
        program_files = [
            os.environ.get("PROGRAMFILES", "C:\\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)"),
        ]
        for pf in program_files:
            firefox_path = Path(pf) / "Mozilla Firefox" / "firefox.exe"
            if firefox_path.exists():
                return str(firefox_path)

    elif sys.platform == "darwin":
        mac_firefox = Path("/Applications/Firefox.app/Contents/MacOS/firefox")
        if mac_firefox.exists():
            return str(mac_firefox)

    elif sys.platform.startswith("linux"):
        for lpath in ["/usr/bin/firefox", "/usr/local/bin/firefox"]:
            if Path(lpath).expanduser().exists():
                return str(Path(lpath).expanduser())

    logger.debug("Firefox binary not found in common locations")
    return None


def get_default_profile_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", "~/.mozilla/firefox"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Firefox"
    else:
        base = Path.home() / ".mozilla" / "firefox"
    return base


_camofox_global_adapter: CamofoxAdapter | None = None
_camofox_global_session: CamofoxSession | None = None


def _get_session() -> CamofoxSession:
    """Get or create a global Camofox session."""
    global _camofox_global_adapter, _camofox_global_session

    if _camofox_global_adapter is None:
        _camofox_global_adapter = CamofoxAdapter(headless=True)
        _camofox_global_session = _camofox_global_adapter.connect()
    elif not _camofox_global_adapter.is_connected():
        _camofox_global_adapter = CamofoxAdapter(headless=True)
        _camofox_global_session = _camofox_global_adapter.connect()

    return _camofox_global_session


def _safe_result(success: bool, data: Any = None, error: str | None = None) -> dict[str, Any]:
    return {"success": success, "data": data, "error": error}


def _tool_wrapper(func: Any) -> Any:
    from tools.base import tool
    return tool(name=func.__name__, description=func.__doc__, toolset="browser")(func)


@_tool_wrapper
def camofox_navigate(url: str) -> dict[str, Any]:
    try:
        if not install_camofox():
            return _safe_result(False, error="Camofox not installed")
        session = _get_session()
        session.navigate(url)
        return _safe_result(True, data={
            "message": f"Navigated to {url}",
            "title": session.get_title(),
            "url": session.get_current_url(),
        })
    except CamofoxError as e:
        return _safe_result(False, error=str(e))
    except Exception as e:
        logger.exception("camofox_navigate failed")
        return _safe_result(False, error=str(e))


@_tool_wrapper
def camofox_screenshot(url: str | None = None, full_page: bool = False) -> dict[str, Any]:
    try:
        if not install_camofox():
            return _safe_result(False, error="Camofox not installed")
        session = _get_session()
        if url:
            session.navigate(url)
        import base64
        img_bytes = session.screenshot(full_page=full_page)
        img_base64 = base64.b64encode(img_bytes).decode("utf-8")
        return _safe_result(True, data={
            "message": f"Screenshot captured ({len(img_bytes)} bytes)",
            "data": img_base64,
            "size": len(img_bytes),
        })
    except CamofoxError as e:
        return _safe_result(False, error=str(e))
    except Exception as e:
        logger.exception("camofox_screenshot failed")
        return _safe_result(False, error=str(e))


@_tool_wrapper
def camofox_click(selector: str) -> dict[str, Any]:
    try:
        if not install_camofox():
            return _safe_result(False, error="Camofox not installed")
        session = _get_session()
        element = session.get_element(selector)
        element.click()
        return _safe_result(True, data={"message": f"Clicked element: {selector}"})
    except CamofoxError as e:
        return _safe_result(False, error=str(e))
    except Exception as e:
        logger.exception("camofox_click failed")
        return _safe_result(False, error=str(e))


@_tool_wrapper
def camofox_evaluate(script: str) -> dict[str, Any]:
    try:
        if not install_camofox():
            return _safe_result(False, error="Camofox not installed")
        session = _get_session()
        result = session.evaluate(script)
        return _safe_result(True, data={
            "message": "JavaScript executed",
            "result": str(result)[:5000] if result is not None else None,
        })
    except CamofoxError as e:
        return _safe_result(False, error=str(e))
    except Exception as e:
        logger.exception("camofox_evaluate failed")
        return _safe_result(False, error=str(e))


@_tool_wrapper
def camofox_get_text(selector: str | None = None) -> dict[str, Any]:
    try:
        if not install_camofox():
            return _safe_result(False, error="Camofox not installed")
        session = _get_session()
        if selector:
            element = session.get_element(selector)
            text = element.get_text()
        else:
            text = session.evaluate("document.body.innerText")
        return _safe_result(True, data={
            "message": f"Retrieved text" + (f" from: {selector}" if selector else ""),
            "text": text[:20000],
            "length": len(text),
        })
    except CamofoxError as e:
        return _safe_result(False, error=str(e))
    except Exception as e:
        logger.exception("camofox_get_text failed")
        return _safe_result(False, error=str(e))


@_tool_wrapper
def camofox_fill(selector: str, text: str) -> dict[str, Any]:
    try:
        if not install_camofox():
            return _safe_result(False, error="Camofox not installed")
        session = _get_session()
        element = session.get_element(selector)
        element.send_keys(text)
        return _safe_result(True, data={
            "message": f"Filled text into: {selector}",
            "text": text,
        })
    except CamofoxError as e:
        return _safe_result(False, error=str(e))
    except Exception as e:
        logger.exception("camofox_fill failed")
        return _safe_result(False, error=str(e))


@_tool_wrapper
def camofox_close() -> dict[str, Any]:
    global _camofox_global_adapter, _camofox_global_session
    try:
        if _camofox_global_adapter is not None:
            _camofox_global_adapter.disconnect()
            _camofox_global_adapter = None
            _camofox_global_session = None
        return _safe_result(True, data={"message": "Camofox closed"})
    except Exception as e:
        logger.exception("camofox_close failed")
        return _safe_result(False, error=str(e))


@_tool_wrapper
def camofox_info() -> dict[str, Any]:
    global _camofox_global_adapter, _camofox_global_session
    try:
        if _camofox_global_adapter is None or not _camofox_global_adapter.is_connected():
            return _safe_result(True, data={
                "message": "No active Camofox session",
                "connected": False,
            })
        session = _camofox_global_session
        return _safe_result(True, data={
            "message": "Camofox session active",
            "connected": True,
            "session_id": session.session_id,
            "url": session.get_current_url(),
            "title": session.get_title(),
        })
    except Exception as e:
        logger.exception("camofox_info failed")
        return _safe_result(False, error=str(e))
