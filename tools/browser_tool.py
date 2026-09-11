"""Browser core tools - comprehensive browser automation functionality.

This module provides the main browser automation tools including navigation,
interaction, content extraction, and session management. All tools return
standardized response format with success, data, and error fields.

Example::

    from tools.browser_tool import (
        browser_navigate,
        browser_click,
        browser_screenshot,
        browser_get_text,
    )

    # Navigate to a URL
    result = browser_navigate("https://example.com")
    print(result)

    # Click an element
    result = browser_click("#submit-button")

    # Get page text
    result = browser_get_text()
"""

from __future__ import annotations

import base64
import logging
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from tools.base import tool
from tools.browser_tool_install import check_playwright_installed

logger = logging.getLogger(__name__)


@dataclass
class BrowserToolResult:
    """Standardized browser tool result format."""

    success: bool
    data: Any = None
    error: str | None = None
    page_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary format."""
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "page_id": self.page_id,
        }

    def __str__(self) -> str:
        """String representation for tool return."""
        if self.success:
            if isinstance(self.data, dict) and "message" in self.data:
                return self.data["message"]
            return str(self.data)[:500] if self.data else "OK"
        return f"Error: {self.error}"


_global_session_id: str | None = None
_global_page_id: str | None = None
_global_page: Any = None
_browser_lock = threading.Lock()


def _get_or_create_session() -> tuple[Any, str, str]:
    """Get or create a browser session.

    Returns:
        Tuple of (page, session_id, page_id).
    """
    global _global_session_id, _global_page_id, _global_page

    if not check_playwright_installed():
        raise RuntimeError(
            "Playwright is not installed. "
            "Install with: pip install playwright && playwright install chromium"
        )

    with _browser_lock:
        if _global_page is not None:
            return _global_page, _global_session_id or "", _global_page_id or ""

        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 720})
        page = context.new_page()
        page.set_default_timeout(30000)

        _global_session_id = str(uuid.uuid4())
        _global_page_id = str(uuid.uuid4())
        _global_page = page

        logger.info("Created new browser session: %s", _global_session_id)
        return page, _global_session_id, _global_page_id


def _safe_execute(func: callable, *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Execute a browser function safely and return standardized result.

    Args:
        func: Function to execute.
        *args: Positional arguments for the function.
        **kwargs: Keyword arguments for the function.

    Returns:
        Standardized result dictionary.
    """
    try:
        page, session_id, page_id = _get_or_create_session()
        result = func(page, *args, **kwargs)
        return {
            "success": True,
            "data": result,
            "error": None,
            "page_id": page_id,
        }
    except Exception as e:
        logger.exception("Browser tool execution failed")
        return {
            "success": False,
            "data": None,
            "error": str(e),
            "page_id": None,
        }


@tool(name="browser_navigate", description="Navigate to a URL in the browser", toolset="browser")
def browser_navigate(url: str) -> dict[str, Any]:
    """Navigate the browser to a URL.

    Args:
        url: The URL to navigate to.

    Returns:
        Dictionary with success status, page title, and URL.
    """
    def _navigate(page: Any) -> dict[str, str]:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return {
            "message": f"Navigated to {url}",
            "title": page.title(),
            "url": page.url,
        }

    return _safe_execute(_navigate)


@tool(name="browser_screenshot", description="Take a screenshot of the current page", toolset="browser")
def browser_screenshot(filename: str = "screenshot.png", full_page: bool = False) -> dict[str, Any]:
    """Take a screenshot of the current page.

    Args:
        filename: File path to save the screenshot.
        full_page: If True, capture the entire scrollable page.

    Returns:
        Dictionary with success status and screenshot data.
    """
    def _screenshot(page: Any) -> dict[str, Any]:
        import os
        os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)
        page.screenshot(path=filename, full_page=full_page)

        with open(filename, "rb") as f:
            img_data = base64.b64encode(f.read()).decode("utf-8")

        return {
            "message": f"Screenshot saved to {filename}",
            "path": filename,
            "data": img_data,
        }

    return _safe_execute(_screenshot)


@tool(name="browser_click", description="Click an element by CSS selector", toolset="browser")
def browser_click(selector: str) -> dict[str, Any]:
    """Click an element matching a CSS selector.

    Args:
        selector: CSS selector for the element to click.

    Returns:
        Dictionary with success status.
    """
    def _click(page: Any) -> dict[str, str]:
        page.click(selector)
        return {"message": f"Clicked element: {selector}"}

    return _safe_execute(_click)


@tool(name="browser_type", description="Type text into an input field", toolset="browser")
def browser_type(selector: str, text: str, delay: int = 0) -> dict[str, Any]:
    """Type text into an input field.

    Args:
        selector: CSS selector for the input element.
        text: Text to type.
        delay: Delay in milliseconds between keystrokes.

    Returns:
        Dictionary with success status.
    """
    def _type(page: Any) -> dict[str, str]:
        page.fill(selector, text)
        return {"message": f"Typed text into: {selector}"}

    return _safe_execute(_type)


@tool(name="browser_get_html", description="Get the HTML content of the page", toolset="browser")
def browser_get_html() -> dict[str, Any]:
    """Get the full HTML content of the current page.

    Returns:
        Dictionary with success status and HTML content.
    """
    def _get_html(page: Any) -> dict[str, str]:
        html = page.content()
        return {
            "message": f"Retrieved HTML ({len(html)} bytes)",
            "html": html[:50000],
            "length": len(html),
        }

    return _safe_execute(_get_html)


@tool(name="browser_get_text", description="Get the visible text content of the page", toolset="browser")
def browser_get_text(selector: str = "body") -> dict[str, Any]:
    """Get the visible text content of an element or the page.

    Args:
        selector: CSS selector for the element (default: body).

    Returns:
        Dictionary with success status and text content.
    """
    def _get_text(page: Any) -> dict[str, Any]:
        text = page.inner_text(selector)
        return {
            "message": f"Retrieved text from: {selector}",
            "text": text[:20000],
            "length": len(text),
        }

    return _safe_execute(_get_text)


@tool(name="browser_scroll", description="Scroll the page up or down", toolset="browser")
def browser_scroll(direction: str = "down", amount: int = 500) -> dict[str, Any]:
    """Scroll the page in a direction.

    Args:
        direction: Scroll direction ('up', 'down', 'left', 'right').
        amount: Number of pixels to scroll.

    Returns:
        Dictionary with success status.
    """
    def _scroll(page: Any) -> dict[str, Any]:
        if direction == "down":
            page.evaluate(f"window.scrollBy(0, {amount})")
        elif direction == "up":
            page.evaluate(f"window.scrollBy(0, {-amount})")
        elif direction == "left":
            page.evaluate(f"window.scrollBy({-amount}, 0)")
        elif direction == "right":
            page.evaluate(f"window.scrollBy({amount}, 0)")
        else:
            return {"message": f"Unknown direction: {direction}", "success": False}

        return {"message": f"Scrolled {direction} by {amount}px"}

    return _safe_execute(_scroll)


@tool(name="browser_scroll_to_element", description="Scroll to a specific element", toolset="browser")
def browser_scroll_to_element(selector: str) -> dict[str, Any]:
    """Scroll to an element to make it visible.

    Args:
        selector: CSS selector for the target element.

    Returns:
        Dictionary with success status.
    """
    def _scroll_to(page: Any) -> dict[str, str]:
        page.evaluate(
            f"""
            document.querySelector('{selector}').scrollIntoView({{
                behavior: 'smooth',
                block: 'center'
            }});
            """
        )
        return {"message": f"Scrolled to element: {selector}"}

    return _safe_execute(_scroll_to)


@tool(name="browser_go_back", description="Navigate back in browser history", toolset="browser")
def browser_go_back() -> dict[str, Any]:
    """Navigate back one page in browser history.

    Returns:
        Dictionary with success status and page title.
    """
    def _go_back(page: Any) -> dict[str, str]:
        page.go_back()
        return {
            "message": "Navigated back",
            "title": page.title(),
            "url": page.url,
        }

    return _safe_execute(_go_back)


@tool(name="browser_go_forward", description="Navigate forward in browser history", toolset="browser")
def browser_go_forward() -> dict[str, Any]:
    """Navigate forward one page in browser history.

    Returns:
        Dictionary with success status and page title.
    """
    def _go_forward(page: Any) -> dict[str, str]:
        page.go_forward()
        return {
            "message": "Navigated forward",
            "title": page.title(),
            "url": page.url,
        }

    return _safe_execute(_go_forward)


@tool(name="browser_new_tab", description="Open a new browser tab", toolset="browser")
def browser_new_tab(url: str | None = None) -> dict[str, Any]:
    """Open a new browser tab and optionally navigate to a URL.

    Args:
        url: Optional URL to navigate to in the new tab.

    Returns:
        Dictionary with success status and new tab index.
    """
    def _new_tab(page: Any) -> dict[str, Any]:
        new_page = page.context.new_page()
        if url:
            new_page.goto(url, wait_until="domcontentloaded", timeout=30000)

        pages = page.context.pages
        tab_index = pages.index(new_page)

        return {
            "message": f"Created new tab (index: {tab_index})",
            "tab_index": tab_index,
            "url": new_page.url,
        }

    return _safe_execute(_new_tab)


@tool(name="browser_switch_tab", description="Switch to a different browser tab", toolset="browser")
def browser_switch_tab(tab_index: int) -> dict[str, Any]:
    """Switch to a browser tab by index.

    Args:
        tab_index: Zero-based index of the tab to switch to.

    Returns:
        Dictionary with success status and new tab URL.
    """
    def _switch_tab(page: Any) -> dict[str, Any]:
        pages = page.context.pages
        if tab_index < 0 or tab_index >= len(pages):
            raise ValueError(f"Tab index {tab_index} out of range (0-{len(pages) - 1})")

        target_page = pages[tab_index]
        target_page.bring_to_front()

        return {
            "message": f"Switched to tab {tab_index}",
            "url": target_page.url,
            "title": target_page.title(),
        }

    return _safe_execute(_switch_tab)


@tool(name="browser_close_tab", description="Close a browser tab", toolset="browser")
def browser_close_tab(tab_index: int | None = None) -> dict[str, Any]:
    """Close a browser tab by index.

    Args:
        tab_index: Zero-based index of the tab to close.
                   If None, closes the current tab.

    Returns:
        Dictionary with success status.
    """
    def _close_tab(page: Any) -> dict[str, Any]:
        pages = page.context.pages

        if tab_index is None:
            if len(pages) <= 1:
                return {"message": "Cannot close last tab", "success": False}
            page.close()
            return {"message": "Closed current tab"}

        if tab_index < 0 or tab_index >= len(pages):
            raise ValueError(f"Tab index {tab_index} out of range")

        if len(pages) <= 1:
            return {"message": "Cannot close last tab", "success": False}

        pages[tab_index].close()
        return {"message": f"Closed tab {tab_index}"}

    return _safe_execute(_close_tab)


@tool(name="browser_get_tabs", description="Get list of all open browser tabs", toolset="browser")
def browser_get_tabs() -> dict[str, Any]:
    """Get information about all open browser tabs.

    Returns:
        Dictionary with success status and list of tabs.
    """
    def _get_tabs(page: Any) -> dict[str, Any]:
        pages = page.context.pages
        tabs = []

        for i, p in enumerate(pages):
            try:
                tabs.append({
                    "index": i,
                    "url": p.url,
                    "title": p.title(),
                    "is_current": p == page,
                })
            except Exception:
                tabs.append({
                    "index": i,
                    "url": "unknown",
                    "title": "unknown",
                    "is_current": p == page,
                })

        return {
            "message": f"Found {len(tabs)} tabs",
            "tabs": tabs,
            "count": len(tabs),
        }

    return _safe_execute(_get_tabs)


@tool(name="browser_execute_js", description="Execute JavaScript in the browser", toolset="browser")
def browser_execute_js(script: str) -> dict[str, Any]:
    """Execute JavaScript code in the browser context.

    Args:
        script: JavaScript code to execute.

    Returns:
        Dictionary with success status and execution result.
    """
    def _execute_js(page: Any) -> dict[str, Any]:
        result = page.evaluate(script)
        return {
            "message": "JavaScript executed",
            "result": str(result)[:5000] if result is not None else None,
        }

    return _safe_execute(_execute_js)


@tool(name="browser_get_cookies", description="Get browser cookies for the current page", toolset="browser")
def browser_get_cookies() -> dict[str, Any]:
    """Get all cookies from the current browser context.

    Returns:
        Dictionary with success status and cookie list.
    """
    def _get_cookies(page: Any) -> dict[str, Any]:
        cookies = page.context.cookies()
        return {
            "message": f"Retrieved {len(cookies)} cookies",
            "cookies": cookies,
            "count": len(cookies),
        }

    return _safe_execute(_get_cookies)


@tool(name="browser_set_cookies", description="Set cookies in the browser", toolset="browser")
def browser_set_cookies(cookies: list[dict[str, Any]]) -> dict[str, Any]:
    """Set cookies in the browser context.

    Args:
        cookies: List of cookie dictionaries with name, value, and optional fields.

    Returns:
        Dictionary with success status.
    """
    def _set_cookies(page: Any) -> dict[str, Any]:
        page.context.add_cookies(cookies)
        return {"message": f"Set {len(cookies)} cookies"}

    return _safe_execute(_set_cookies)


@tool(name="browser_clear_cookies", description="Clear all browser cookies", toolset="browser")
def browser_clear_cookies() -> dict[str, Any]:
    """Clear all cookies from the current browser context.

    Returns:
        Dictionary with success status.
    """
    def _clear_cookies(page: Any) -> dict[str, Any]:
        page.context.clear_cookies()
        return {"message": "Cleared all cookies"}

    return _safe_execute(_clear_cookies)


@tool(name="browser_wait", description="Wait for a specified time or element", toolset="browser")
def browser_wait(selector: str = "", timeout: int = 5000) -> dict[str, Any]:
    """Wait for a selector to appear or for a timeout.

    Args:
        selector: CSS selector to wait for. If empty, just waits.
        timeout: Timeout in milliseconds.

    Returns:
        Dictionary with success status.
    """
    def _wait(page: Any) -> dict[str, Any]:
        if selector:
            page.wait_for_selector(selector, timeout=timeout)
            return {"message": f"Element appeared: {selector}"}
        else:
            page.wait_for_timeout(timeout)
            return {"message": f"Waited {timeout}ms"}

    return _safe_execute(_wait)


@tool(name="browser_hover", description="Hover over an element", toolset="browser")
def browser_hover(selector: str) -> dict[str, Any]:
    """Hover over an element.

    Args:
        selector: CSS selector for the element to hover over.

    Returns:
        Dictionary with success status.
    """
    def _hover(page: Any) -> dict[str, str]:
        page.hover(selector)
        return {"message": f"Hovered over: {selector}"}

    return _safe_execute(_hover)


@tool(name="browser_press", description="Press a keyboard key", toolset="browser")
def browser_press(key: str, selector: str = "") -> dict[str, Any]:
    """Press a keyboard key.

    Args:
        key: Key name (e.g., 'Enter', 'Escape', 'Tab').
        selector: Optional CSS selector to focus before pressing.

    Returns:
        Dictionary with success status.
    """
    def _press(page: Any) -> dict[str, str]:
        if selector:
            page.locator(selector).press(key)
        else:
            page.keyboard.press(key)
        return {"message": f"Pressed key: {key}"}

    return _safe_execute(_press)


@tool(name="browser_select_option", description="Select an option from a dropdown", toolset="browser")
def browser_select_option(selector: str, value: str) -> dict[str, Any]:
    """Select an option from a dropdown select element.

    Args:
        selector: CSS selector for the select element.
        value: Value of the option to select.

    Returns:
        Dictionary with success status.
    """
    def _select(page: Any) -> dict[str, str]:
        page.select_option(selector, value)
        return {"message": f"Selected option: {value}"}

    return _safe_execute(_select)


@tool(name="browser_check", description="Check a checkbox or radio button", toolset="browser")
def browser_check(selector: str) -> dict[str, Any]:
    """Check a checkbox or radio button.

    Args:
        selector: CSS selector for the checkbox or radio button.

    Returns:
        Dictionary with success status.
    """
    def _check(page: Any) -> dict[str, str]:
        page.check(selector)
        return {"message": f"Checked: {selector}"}

    return _safe_execute(_check)


@tool(name="browser_uncheck", description="Uncheck a checkbox", toolset="browser")
def browser_uncheck(selector: str) -> dict[str, Any]:
    """Uncheck a checkbox.

    Args:
        selector: CSS selector for the checkbox.

    Returns:
        Dictionary with success status.
    """
    def _uncheck(page: Any) -> dict[str, str]:
        page.uncheck(selector)
        return {"message": f"Unchecked: {selector}"}

    return _safe_execute(_uncheck)


@tool(name="browser_reload", description="Reload the current page", toolset="browser")
def browser_reload() -> dict[str, Any]:
    """Reload the current page.

    Returns:
        Dictionary with success status and new page title.
    """
    def _reload(page: Any) -> dict[str, str]:
        page.reload()
        return {
            "message": "Page reloaded",
            "title": page.title(),
            "url": page.url,
        }

    return _safe_execute(_reload)


@tool(name="browser_get_url", description="Get the current page URL", toolset="browser")
def browser_get_url() -> dict[str, Any]:
    """Get the URL of the current page.

    Returns:
        Dictionary with success status and URL.
    """
    def _get_url(page: Any) -> dict[str, str]:
        return {
            "message": f"Current URL: {page.url}",
            "url": page.url,
            "title": page.title(),
        }

    return _safe_execute(_get_url)


@tool(name="browser_close", description="Close the browser", toolset="browser")
def browser_close() -> dict[str, Any]:
    """Close the browser and release resources.

    Returns:
        Dictionary with success status.
    """
    global _global_page, _global_session_id, _global_page_id

    with _browser_lock:
        if _global_page is not None:
            try:
                _global_page.context.close()
            except Exception:
                pass
            try:
                _global_page = None
            except Exception:
                pass

        _global_session_id = None
        _global_page_id = None

    return {
        "success": True,
        "data": {"message": "Browser closed"},
        "error": None,
        "page_id": None,
    }


@tool(name="browser_info", description="Get information about the current browser session", toolset="browser")
def browser_info() -> dict[str, Any]:
    """Get information about the current browser session.

    Returns:
        Dictionary with session information.
    """
    global _global_session_id, _global_page_id, _global_page

    if _global_page is None:
        return {
            "success": True,
            "data": {
                "message": "No active browser session",
                "has_session": False,
            },
            "error": None,
            "page_id": None,
        }

    with _browser_lock:
        return {
            "success": True,
            "data": {
                "message": "Browser session active",
                "session_id": _global_session_id,
                "page_id": _global_page_id,
                "url": _global_page.url,
                "title": _global_page.title(),
            },
            "error": None,
            "page_id": _global_page_id,
        }


def get_current_page() -> Any | None:
    """Get the current Playwright page object.

    Returns:
        Playwright Page object or None if no session active.
    """
    global _global_page

    if _global_page is None:
        try:
            page, _, _ = _get_or_create_session()
            return page
        except Exception:
            return None

    return _global_page
