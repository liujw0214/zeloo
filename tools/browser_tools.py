"""Browser automation tools — 10+ tools powered by Playwright.

All browser tools share a single persistent browser context so the agent
can navigate, interact, and extract content across multiple calls.

Requires the ``playwright`` package; tools return an error message if it
is not installed.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from tools.base import tool

logger = logging.getLogger(__name__)

_browser_lock = threading.Lock()
_browser_state: dict[str, Any] = {}


def _get_browser():
    """Lazily create and return a shared Playwright browser + page."""
    with _browser_lock:
        if "page" in _browser_state:
            return _browser_state["page"]

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "playwright is not installed. "
                "Install with: pip install playwright && playwright install chromium"
            ) from exc

        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        _browser_state["playwright"] = pw
        _browser_state["browser"] = browser
        _browser_state["page"] = page
        return page


def _safe_call(fn):
    """Call a browser function and return a friendly error on failure."""
    try:
        return fn()
    except Exception as e:
        logger.exception("Browser tool failed")
        return f"Error: {e}"


@tool(name="browser_navigate", description="Navigate to a URL", toolset="browser")
def browser_navigate(url: str) -> str:
    """Navigate the browser to a URL and return the page title.

    Args:
        url: The URL to navigate to.
    """
    def _go():
        page = _get_browser()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return f"Navigated to {url}\nTitle: {page.title()}"
    return _safe_call(_go)


@tool(name="browser_click", description="Click an element by selector", toolset="browser")
def browser_click(selector: str) -> str:
    """Click an element matching a CSS selector.

    Args:
        selector: CSS selector for the element.
    """
    def _go():
        page = _get_browser()
        page.click(selector)
        return f"Clicked: {selector}"
    return _safe_call(_go)


@tool(name="browser_type", description="Type text into an input", toolset="browser")
def browser_type(selector: str, text: str) -> str:
    """Type text into an input field.

    Args:
        selector: CSS selector for the input.
        text: Text to type.
    """
    def _go():
        page = _get_browser()
        page.fill(selector, text)
        return f"Typed into {selector}"
    return _safe_call(_go)


@tool(name="browser_screenshot", description="Take a screenshot of the page", toolset="browser")
def browser_screenshot(path: str = "screenshot.png") -> str:
    """Take a screenshot and save it to a file.

    Args:
        path: File path to save the screenshot.
    """
    def _go():
        page = _get_browser()
        page.screenshot(path=path)
        return f"Screenshot saved to {path}"
    return _safe_call(_go)


@tool(name="browser_get_text", description="Get the visible text of the page", toolset="browser")
def browser_get_text() -> str:
    """Return the visible text content of the current page."""
    def _go():
        page = _get_browser()
        text = page.inner_text("body")
        return text[:10000] if len(text) > 10000 else text
    return _safe_call(_go)


@tool(name="browser_get_html", description="Get the page HTML", toolset="browser")
def browser_get_html() -> str:
    """Return the full HTML of the current page."""
    def _go():
        page = _get_browser()
        html = page.content()
        return html[:20000] if len(html) > 20000 else html
    return _safe_call(_go)


@tool(name="browser_evaluate", description="Evaluate JavaScript in the page", toolset="browser")
def browser_evaluate(script: str) -> str:
    """Evaluate a JavaScript expression in the page context.

    Args:
        script: JavaScript code to evaluate.
    """
    def _go():
        page = _get_browser()
        result = page.evaluate(script)
        return str(result)
    return _safe_call(_go)


@tool(name="browser_back", description="Navigate back in history", toolset="browser")
def browser_back() -> str:
    """Navigate back one page in history."""
    def _go():
        page = _get_browser()
        page.go_back()
        return f"Went back. Title: {page.title()}"
    return _safe_call(_go)


@tool(name="browser_forward", description="Navigate forward in history", toolset="browser")
def browser_forward() -> str:
    """Navigate forward one page in history."""
    def _go():
        page = _get_browser()
        page.go_forward()
        return f"Went forward. Title: {page.title()}"
    return _safe_call(_go)


@tool(name="browser_wait", description="Wait for a selector or timeout", toolset="browser")
def browser_wait(selector: str = "", timeout: int = 5000) -> str:
    """Wait for an element to appear or for a timeout.

    Args:
        selector: CSS selector to wait for (empty = just wait timeout).
        timeout: Timeout in milliseconds.
    """
    def _go():
        page = _get_browser()
        if selector:
            page.wait_for_selector(selector, timeout=timeout)
            return f"Element appeared: {selector}"
        page.wait_for_timeout(timeout)
        return f"Waited {timeout}ms"
    return _safe_call(_go)


@tool(name="browser_close", description="Close the browser", toolset="browser")
def browser_close() -> str:
    """Close the browser and release resources."""
    global _browser_state
    with _browser_lock:
        try:
            if "browser" in _browser_state:
                _browser_state["browser"].close()
            if "playwright" in _browser_state:
                _browser_state["playwright"].stop()
        except Exception as e:
            return f"Error closing browser: {e}"
        finally:
            _browser_state.clear()
    return "Browser closed"
