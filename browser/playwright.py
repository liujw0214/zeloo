"""Playwright-based browser automation provider."""
from __future__ import annotations

import logging
import time
from typing import Any

from browser.base import BrowserProvider, CrawlResult, PageSnapshot

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import Page, sync_playwright  # noqa: F401
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False


class PlaywrightBrowserProvider(BrowserProvider):
    """Playwright-based browser automation provider.

    Provides local Chromium/Firefox/WebKit browser control via Playwright.
    Does not require an API key (local browser control).

    Example::

        from browser import get_provider
        browser = get_provider("playwright")
        snapshot = browser.navigate("https://example.com")
        print(snapshot.title, snapshot.content)
    """

    name = "playwright"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        browser_type: str = "chromium",
        headless: bool = True,
        timeout: int = 30000,
        **kwargs: Any,
    ) -> None:
        super().__init__(api_key, **kwargs)
        self.browser_type = browser_type
        self.headless = headless
        self.timeout = timeout
        self._playwright = None
        self._browser = None
        self._context = None

    def _ensure_browser(self) -> None:
        if not _PLAYWRIGHT_AVAILABLE:
            raise RuntimeError(
                "Playwright not installed. Install with: pip install playwright && playwright install"
            )
        if self._playwright is None:
            self._playwright = sync_playwright().start()
        if self._browser is None:
            self._browser = getattr(self._playwright, self.browser_type).launch(
                headless=self.headless
            )
        if self._context is None:
            self._context = self._browser.new_context(
                viewport={"width": 1280, "height": 720}
            )

    def _ensure_page(self) -> Page:
        self._ensure_browser()
        assert self._context is not None
        return self._context.new_page()

    def navigate(
        self,
        url: str,
        *,
        wait_for: str | None = None,
        timeout: int = 30,
        **kwargs: Any,
    ) -> PageSnapshot:
        try:
            page = self._ensure_page()
            page.set_default_timeout(timeout * 1000)
            response = page.goto(url, wait_until="domcontentloaded")
            if wait_for:
                page.wait_for_selector(wait_for, timeout=timeout * 1000)
            content = page.content()
            title = page.title()
            page.close()
            return PageSnapshot(
                url=url,
                title=title,
                content=content,
                html=content,
                status_code=response.status if response else 0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Playwright navigate failed for %s: %s", url, exc)
            return PageSnapshot(url=url, error=str(exc), status_code=0)

    def crawl(
        self,
        url: str,
        *,
        depth: int = 1,
        max_pages: int = 10,
        **kwargs: Any,
    ) -> CrawlResult:
        start = time.time()
        visited: set[str] = set()
        pages: list[PageSnapshot] = []

        def _crawl_recursive(current_url: str, current_depth: int) -> None:
            if current_depth > depth or len(pages) >= max_pages:
                return
            if current_url in visited:
                return
            visited.add(current_url)
            snapshot = self.navigate(current_url, **kwargs)
            pages.append(snapshot)
            if current_depth < depth:
                page = self._ensure_page()
                try:
                    page.goto(current_url, wait_until="domcontentloaded")
                    links = page.query_selector_all("a[href]")
                    for link in links:
                        href = link.get_attribute("href") or ""
                        if href.startswith("http") and href not in visited:
                            _crawl_recursive(href, current_depth + 1)
                except Exception:  # noqa: BLE001
                    pass
                finally:
                    page.close()

        _crawl_recursive(url, 0)
        self._cleanup()
        return CrawlResult(
            pages=pages,
            provider=self.name,
            crawl_url=url,
            depth=depth,
            total_pages=len(pages),
            duration_ms=int((time.time() - start) * 1000),
        )

    def screenshot(
        self,
        url: str,
        *,
        full_page: bool = False,
        format: str = "png",
        **kwargs: Any,
    ) -> bytes:
        page = self._ensure_page()
        try:
            page.goto(url, wait_until="domcontentloaded")
            return page.screenshot(full_page=full_page)
        finally:
            page.close()

    def validate_credentials(self) -> bool:
        if not _PLAYWRIGHT_AVAILABLE:
            return False
        try:
            self._ensure_browser()
            return True
        except Exception:  # noqa: BLE001
            return False

    def _cleanup(self) -> None:
        if self._context:
            try:
                self._context.close()
            except Exception:  # noqa: BLE001
                pass
            self._context = None
        if self._browser:
            try:
                self._browser.close()
            except Exception:  # noqa: BLE001
                pass
            self._browser = None
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:  # noqa: BLE001
                pass
            self._playwright = None

    def __del__(self) -> None:
        try:
            self._cleanup()
        except Exception:  # noqa: BLE001
            pass
