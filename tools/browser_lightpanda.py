"""LightPanda lightweight headless browser adapter.

Provides async browser automation using LightPanda (lightweight pyppeteer alternative).
Gracefully degrades when the library is unavailable.

Example::

    from tools.browser_lightpanda import LightPandaAdapter, lightpanda_navigate
    session = await LightPandaAdapter().connect()
    await session.navigate("https://example.com")
    result = lightpanda_navigate("https://example.com")
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

logger = logging.getLogger(__name__)

_LIGHTPANDA_AVAILABLE = importlib.util.find_spec("lightpanda") is not None


class LightPandaError(RuntimeError):
    """Base exception for LightPanda operations."""


class LightPandaConnectionError(LightPandaError):
    """Raised when connection to browser fails."""


class LightPandaTimeoutError(LightPandaError):
    """Raised when an operation times out."""


class LightPandaNotFoundError(LightPandaError):
    """Raised when an element is not found."""


def is_lightpanda_available() -> bool:
    """Check if LightPanda library is available."""
    return _LIGHTPANDA_AVAILABLE


def get_chrome_path() -> str | None:
    """Find system Chrome/Chromium executable path."""
    if sys.platform == "win32":
        paths = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        ]
    elif sys.platform == "darwin":
        paths = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    else:
        paths = ["/usr/bin/google-chrome", "/usr/bin/chromium"]

    for path in paths:
        if os.path.isfile(path):
            return path
    return shutil.which("google-chrome") or shutil.which("chromium")


def install_lightpanda() -> bool:
    """Install LightPanda library."""
    try:
        result = subprocess.run([sys.executable, "-m", "pip", "install", "lightpanda"], capture_output=True, text=True)
        return result.returncode == 0
    except Exception:
        return False


@dataclass
class LightPandaElement:
    """Represents a DOM element in the page."""

    session: "LightPandaSession"
    selector: str
    handle: Any = field(default=None)

    def click(self, timeout: float = 5.0) -> None:
        """Click the element."""
        if not _LIGHTPANDA_AVAILABLE:
            raise LightPandaError("LightPanda not available. Install with: pip install lightpanda")
        try:
            self.session._get_element(self.selector).click(timeout=timeout * 1000)
        except Exception as e:
            raise LightPandaError(f"Failed to click {self.selector}: {e}") from e

    def send_keys(self, text: str) -> None:
        """Type text into the element."""
        if not _LIGHTPANDA_AVAILABLE:
            raise LightPandaError("LightPanda not available. Install with: pip install lightpanda")
        try:
            self.session._get_element(self.selector).type(text, delay=50)
        except Exception as e:
            raise LightPandaError(f"Failed to send keys to {self.selector}: {e}") from e

    def hover(self) -> None:
        """Hover over the element."""
        if not _LIGHTPANDA_AVAILABLE:
            raise LightPandaError("LightPanda not available. Install with: pip install lightpanda")
        self.session._get_element(self.selector).hover()

    def scroll_into_view(self) -> None:
        """Scroll element into view."""
        self.session.evaluate(f"document.querySelector('{self.selector}')?.scrollIntoView({{behavior: 'smooth', block: 'center'}})")

    def get_text(self) -> str:
        """Get visible text content."""
        result = self.session.evaluate(f"document.querySelector('{self.selector}')?.textContent?.trim() || ''")
        return str(result) if result else ""

    def get_attribute(self, name: str) -> str | None:
        """Get an attribute value."""
        result = self.session.evaluate(f"document.querySelector('{self.selector}')?.getAttribute('{name}')")
        return result if result else None

    def get_inner_html(self) -> str:
        """Get inner HTML."""
        result = self.session.evaluate(f"document.querySelector('{self.selector}')?.innerHTML || ''")
        return str(result) if result else ""

    def is_visible(self) -> bool:
        """Check if element is visible."""
        result = self.session.evaluate(
            """(function() {
                const el = document.querySelector(arguments[0]);
                if (!el) return false;
                const s = window.getComputedStyle(el);
                return el.offsetWidth > 0 && el.offsetHeight > 0 && s.visibility !== 'hidden' && s.display !== 'none';
            })(arguments[0])""", self.selector)
        return bool(result)

    def is_enabled(self) -> bool:
        """Check if element is enabled."""
        result = self.session.evaluate(f"!document.querySelector('{self.selector}')?.disabled")
        return bool(result)

    def bounding_box(self) -> dict | None:
        """Get bounding box of element."""
        result = self.session.evaluate(
            """(function() {
                const el = document.querySelector(arguments[0]);
                if (!el) return null;
                const r = el.getBoundingClientRect();
                return {x: r.x, y: r.y, width: r.width, height: r.height};
            })(arguments[0])""", self.selector)
        return result if result else None


@dataclass
class LightPandaSession:
    """Represents a browser page session."""

    adapter: "LightPandaAdapter"
    page: Any = field(default=None)
    _url: str = ""
    _title: str = ""
    _closed: bool = False

    async def navigate(self, url: str, wait_until: Literal["load", "domcontentloaded", "networkidle"] = "domcontentloaded", timeout: float = 30.0) -> bool:
        """Navigate to a URL."""
        if not _LIGHTPANDA_AVAILABLE:
            raise LightPandaError("LightPanda not available. Install with: pip install lightpanda")
        if self.page is None:
            raise LightPandaConnectionError("No active page session")

        try:
            wait_map = {"load": "load", "domcontentloaded": "domcontentloaded", "networkidle": "networkidle"}
            await self.page.goto(url, waitUntil=wait_map.get(wait_until, "domcontentloaded"), timeout=timeout * 1000)
            self._url = self.page.url
            self._title = await self.page.title()
            return True
        except Exception as e:
            if "Timeout" in str(e):
                raise LightPandaTimeoutError(f"Navigation timed out: {url}") from e
            raise LightPandaError(f"Navigation failed: {e}") from e

    async def screenshot(self, format: Literal["png", "jpeg", "webp"] = "png", full_page: bool = False, quality: int | None = None) -> bytes:
        """Capture screenshot of the page."""
        if not _LIGHTPANDA_AVAILABLE:
            raise LightPandaError("LightPanda not available. Install with: pip install lightpanda")
        if self.page is None:
            raise LightPandaConnectionError("No active page session")

        opts: dict[str, Any] = {"type": format, "fullPage": full_page}
        if quality and format in ("jpeg", "webp"):
            opts["quality"] = quality
        result = await self.page.screenshot(**opts)
        return result if isinstance(result, bytes) else result.encode("utf-8")

    async def evaluate(self, script: str) -> Any:
        """Evaluate JavaScript in page context."""
        if not _LIGHTPANDA_AVAILABLE:
            raise LightPandaError("LightPanda not available. Install with: pip install lightpanda")
        if self.page is None:
            raise LightPandaConnectionError("No active page session")
        return await self.page.evaluate(script)

    async def evaluate_async(self, script: str) -> Any:
        """Evaluate async JavaScript in page context."""
        if not _LIGHTPANDA_AVAILABLE:
            raise LightPandaError("LightPanda not available. Install with: pip install lightpanda")
        if self.page is None:
            raise LightPandaConnectionError("No active page session")
        return await self.page.evaluate(script, force_expr=False)

    def get_element(self, selector: str) -> LightPandaElement:
        """Get element by CSS selector."""
        return LightPandaElement(session=self, selector=selector)

    async def wait_for_selector(self, selector: str, timeout: float = 10.0) -> LightPandaElement:
        """Wait for element to appear."""
        if not _LIGHTPANDA_AVAILABLE:
            raise LightPandaError("LightPanda not available. Install with: pip install lightpanda")
        if self.page is None:
            raise LightPandaConnectionError("No active page session")

        try:
            await self.page.waitForSelector(selector, timeout=timeout * 1000)
            return LightPandaElement(session=self, selector=selector)
        except Exception:
            raise LightPandaTimeoutError(f"Element not found within {timeout}s: {selector}")

    async def get_cookies(self) -> list[dict]:
        """Get all cookies from current page."""
        if not _LIGHTPANDA_AVAILABLE or self.page is None:
            return []
        try:
            cookies = await self.page.cookies()
            return cookies if isinstance(cookies, list) else []
        except Exception:
            return []

    async def set_cookies(self, cookies: list[dict]) -> None:
        """Set cookies in browser."""
        if not _LIGHTPANDA_AVAILABLE or self.page is None:
            raise LightPandaConnectionError("No active page session")
        for cookie in cookies:
            await self.page.setCookie(cookie)

    async def get_local_storage(self) -> dict:
        """Get all localStorage data."""
        if self.page is None:
            raise LightPandaConnectionError("No active page session")
        try:
            import json
            result = await self.evaluate("JSON.stringify(localStorage)")
            return json.loads(result) if result else {}
        except Exception:
            return {}

    async def set_local_storage(self, data: dict) -> None:
        """Set localStorage data."""
        if self.page is None:
            raise LightPandaConnectionError("No active page session")
        for key, value in data.items():
            await self.evaluate(f"localStorage.setItem('{key}', JSON.stringify({value!r}))")

    async def close(self) -> None:
        """Close the page session."""
        if self._closed:
            return
        self._closed = True
        if self.page is not None and _LIGHTPANDA_AVAILABLE:
            try:
                await self.page.close()
            except Exception:
                pass
        self.page = None

    def get_current_url(self) -> str:
        """Get current page URL."""
        return self._url

    def get_title(self) -> str:
        """Get current page title."""
        return self._title

    async def get_html(self) -> str:
        """Get complete HTML content."""
        if self.page is None:
            raise LightPandaConnectionError("No active page session")
        return await self.page.content()

    def _get_element(self, selector: str) -> Any:
        """Get element handle."""
        if self.page is None:
            raise LightPandaConnectionError("No active page session")
        return self.page.locator(selector)

    async def emulate_device(self, device_name: str) -> None:
        """Emulate a device (iPhone, Android, etc.)."""
        presets = {
            "iPhone 6": {"userAgent": "Mozilla/5.0 (iPhone; CPU iPhone OS 9_1 like Mac OS X) AppleWebKit/601.1.46 Version/9.0 Mobile/13B143 Safari/601.1", "viewport": {"width": 375, "height": 667}},
            "iPhone 12": {"userAgent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_4 like Mac OS X) AppleWebKit/605.1.15 Version/14.1 Mobile/15E148 Safari/604.1", "viewport": {"width": 390, "height": 844}},
            "Android": {"userAgent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/91.0.4472.120 Mobile Safari/537.36", "viewport": {"width": 360, "height": 640}},
        }
        preset = presets.get(device_name)
        if preset and self.page:
            await self.page.setExtraHTTPHeaders({"User-Agent": preset["userAgent"]})
        logger.info("Emulating device: %s", device_name)

    async def set_viewport(self, width: int, height: int, device_scale_factor: float = 1.0) -> None:
        """Set viewport size."""
        viewport = {"width": width, "height": height, "deviceScaleFactor": device_scale_factor}
        if self.page and _LIGHTPANDA_AVAILABLE:
            await self.page.setViewport(viewport)
        logger.info("Set viewport: %dx%d", width, height)

    async def set_user_agent(self, user_agent: str) -> None:
        """Set custom user agent."""
        if self.page and _LIGHTPANDA_AVAILABLE:
            await self.page.setUserAgent(user_agent)
        logger.info("Set user agent: %s", user_agent[:50])

    async def block_resources(self, resource_types: list[str]) -> None:
        """Block specific resource types from loading."""
        if self.page is None:
            raise LightPandaConnectionError("No active page session")
        await self.page.route("**/*", lambda route: route.abort() if route.request.resourceType in resource_types else route.continue_())
        logger.info("Blocking resources: %s", resource_types)

    async def intercept_requests(self, handler: Callable) -> None:
        """Intercept and handle requests."""
        if self.page is None:
            raise LightPandaConnectionError("No active page session")
        if not _LIGHTPANDA_AVAILABLE:
            raise LightPandaError("LightPanda not available")
        await self.page.setRequestInterception(True)
        self.page.on("request", handler)
        logger.info("Request interception enabled")


class LightPandaAdapter:
    """LightPanda headless browser adapter.

    Provides async browser automation using LightPanda.

    Example::

        async with LightPandaAdapter() as adapter:
            session = await adapter.connect()
            await session.navigate("https://example.com")
    """

    def __init__(self, executable_path: str | None = None, headless: bool = True, args: list[str] | None = None, port: int | None = None) -> None:
        self.executable_path = executable_path or get_chrome_path()
        self.headless = headless
        self.args = args or []
        self.port = port or 9222
        self._browser: Any = None
        self._context: Any = None
        self._session: LightPandaSession | None = None
        self._closed: bool = False

    async def connect(self) -> LightPandaSession:
        """Connect to or launch a browser instance."""
        if not _LIGHTPANDA_AVAILABLE:
            raise LightPandaError("LightPanda library not available. Install with: pip install lightpanda")

        if self._session is not None and not self._closed:
            return self._session

        try:
            import lightpanda
            opts: dict[str, Any] = {"headless": self.headless, "args": self.args or ["--no-sandbox"]}
            if self.executable_path:
                opts["executablePath"] = self.executable_path
            self._browser = await lightpanda.launch(**opts)
            self._context = await self._browser.newContext(viewport={"width": 1280, "height": 720})
            page = await self._context.newPage()
            self._session = LightPandaSession(adapter=self, page=page)
            self._closed = False
            logger.info("LightPanda browser connected")
            return self._session
        except ImportError:
            raise LightPandaConnectionError("Failed to import lightpanda")
        except Exception as e:
            raise LightPandaConnectionError(f"Failed to connect to browser: {e}") from e

    async def disconnect(self) -> None:
        """Disconnect from browser and clean up resources."""
        if self._closed:
            return
        self._closed = True
        if self._session:
            await self._session.close()
        self._session = None
        if self._context and _LIGHTPANDA_AVAILABLE:
            try:
                await self._context.close()
            except Exception:
                pass
        self._context = None
        if self._browser and _LIGHTPANDA_AVAILABLE:
            try:
                await self._browser.close()
            except Exception:
                pass
        self._browser = None
        logger.info("LightPanda browser disconnected")

    def is_connected(self) -> bool:
        """Check if adapter is connected to browser."""
        return self._session is not None and not self._closed

    async def __aenter__(self) -> "LightPandaAdapter":
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.disconnect()


_global_adapter: LightPandaAdapter | None = None
_global_session: LightPandaSession | None = None


async def _get_or_create_session() -> LightPandaSession:
    """Get or create a global LightPanda session."""
    global _global_adapter, _global_session
    if _global_adapter is None:
        _global_adapter = LightPandaAdapter()
        _global_session = await _global_adapter.connect()
    if _global_session is None or _global_adapter._closed:
        _global_adapter = LightPandaAdapter()
        _global_session = await _global_adapter.connect()
    return _global_session


def _run_async(coro: Any) -> Any:
    """Run async coroutine in sync context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                return executor.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def _result(success: bool, data: Any = None, error: str | None = None) -> dict[str, Any]:
    """Serialize result to standard format."""
    return {"success": success, "data": data, "error": error}


def lightpanda_navigate(url: str, wait_until: str = "domcontentloaded") -> dict[str, Any]:
    """Navigate to a URL using LightPanda."""
    async def _navigate() -> dict[str, Any]:
        session = await _get_or_create_session()
        try:
            await session.navigate(url, wait_until=wait_until)
            return _result(True, {"url": url, "title": session._title})
        except LightPandaError as e:
            return _result(False, error=str(e))
    return _run_async(_navigate())


def lightpanda_screenshot(url: str | None = None, full_page: bool = False, format: str = "png") -> dict[str, Any]:
    """Take a screenshot using LightPanda."""
    import base64
    async def _screenshot() -> dict[str, Any]:
        session = await _get_or_create_session()
        if url:
            await session.navigate(url)
        try:
            img_bytes = await session.screenshot(format=format, full_page=full_page)
            return _result(True, {"format": format, "data": base64.b64encode(img_bytes).decode("utf-8"), "size": len(img_bytes)})
        except LightPandaError as e:
            return _result(False, error=str(e))
    return _run_async(_screenshot())


def lightpanda_click(selector: str) -> dict[str, Any]:
    """Click an element using LightPanda."""
    async def _click() -> dict[str, Any]:
        session = await _get_or_create_session()
        try:
            session.get_element(selector).click()
            return _result(True, {"selector": selector, "action": "clicked"})
        except LightPandaError as e:
            return _result(False, error=str(e))
    return _run_async(_click())


def lightpanda_evaluate(script: str) -> dict[str, Any]:
    """Evaluate JavaScript using LightPanda."""
    async def _eval() -> dict[str, Any]:
        session = await _get_or_create_session()
        try:
            result = await session.evaluate(script)
            return _result(True, {"result": str(result)[:5000] if result else None})
        except LightPandaError as e:
            return _result(False, error=str(e))
    return _run_async(_eval())


def lightpanda_fill(selector: str, text: str) -> dict[str, Any]:
    """Fill an input field using LightPanda."""
    async def _fill() -> dict[str, Any]:
        session = await _get_or_create_session()
        try:
            session.get_element(selector).send_keys(text)
            return _result(True, {"selector": selector, "action": "filled"})
        except LightPandaError as e:
            return _result(False, error=str(e))
    return _run_async(_fill())


def lightpanda_wait(selector: str, timeout: float = 10.0) -> dict[str, Any]:
    """Wait for an element using LightPanda."""
    async def _wait() -> dict[str, Any]:
        session = await _get_or_create_session()
        try:
            await session.wait_for_selector(selector, timeout=timeout)
            return _result(True, {"selector": selector, "found": True})
        except LightPandaError as e:
            return _result(False, error=str(e))
    return _run_async(_wait())
