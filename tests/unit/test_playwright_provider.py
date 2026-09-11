"""Tests for browser/playwright.py — Playwright browser provider."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestPlaywrightAvailability:
    def test_module_imports_without_playwright(self) -> None:
        from browser import playwright as pw_module

        assert hasattr(pw_module, "PlaywrightBrowserProvider")
        assert hasattr(pw_module, "_PLAYWRIGHT_AVAILABLE")

    def test_returns_false_when_playwright_missing(self) -> None:
        with patch("browser.playwright._PLAYWRIGHT_AVAILABLE", False):
            from browser.playwright import PlaywrightBrowserProvider

            provider = PlaywrightBrowserProvider()
            assert provider.validate_credentials() is False

    def test_navigate_returns_error_snapshot_when_missing(self) -> None:
        with patch("browser.playwright._PLAYWRIGHT_AVAILABLE", False):
            from browser.playwright import PlaywrightBrowserProvider

            provider = PlaywrightBrowserProvider()
            snapshot = provider.navigate("https://example.com")
            assert snapshot.error is not None
            assert snapshot.status_code == 0


class TestPlaywrightProviderInit:
    def test_default_config(self) -> None:
        from browser.playwright import PlaywrightBrowserProvider

        provider = PlaywrightBrowserProvider()
        assert provider.name == "playwright"
        assert provider.browser_type == "chromium"
        assert provider.headless is True
        assert provider.timeout == 30000

    def test_custom_config(self) -> None:
        from browser.playwright import PlaywrightBrowserProvider

        provider = PlaywrightBrowserProvider(
            browser_type="firefox",
            headless=False,
            timeout=60000,
        )
        assert provider.browser_type == "firefox"
        assert provider.headless is False
        assert provider.timeout == 60000


class TestPlaywrightProviderRegistry:
    def test_playwright_registered(self) -> None:
        from browser import get_provider

        provider = get_provider("playwright")
        assert provider is not None
        assert provider.name == "playwright"

    def test_all_providers_include_playwright(self) -> None:
        from browser import list_providers

        providers = list_providers()
        assert "playwright" in providers
        assert "browserbase" in providers
        assert "firecrawl" in providers


class TestPlaywrightCleanup:
    def test_cleanup_handles_no_browser(self) -> None:
        from browser.playwright import PlaywrightBrowserProvider

        provider = PlaywrightBrowserProvider()
        provider._cleanup()
        assert provider._playwright is None
        assert provider._browser is None
        assert provider._context is None

    def test_cleanup_handles_errors_silently(self) -> None:
        from browser.playwright import PlaywrightBrowserProvider

        provider = PlaywrightBrowserProvider()
        mock_pw = MagicMock()
        mock_pw.stop.side_effect = RuntimeError("shutdown failed")
        provider._playwright = mock_pw
        provider._browser = MagicMock()
        provider._context = MagicMock()
        provider._cleanup()
        assert provider._playwright is None


class TestPlaywrightNavigate:
    def test_navigate_calls_page_goto(self) -> None:
        from browser.playwright import PlaywrightBrowserProvider

        provider = PlaywrightBrowserProvider()
        mock_page = MagicMock()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_page.goto.return_value = mock_response
        mock_page.content.return_value = "<html><title>Test</title></html>"
        mock_page.title.return_value = "Test Page"
        mock_page.wait_for_selector.return_value = None

        with patch.object(provider, "_ensure_page", return_value=mock_page):
            snapshot = provider.navigate(
                "https://example.com",
                wait_for="body",
                timeout=10,
            )
        assert snapshot.url == "https://example.com"
        assert snapshot.title == "Test Page"
        assert snapshot.status_code == 200
        mock_page.close.assert_called_once()

    def test_navigate_handles_exception(self) -> None:
        from browser.playwright import PlaywrightBrowserProvider

        provider = PlaywrightBrowserProvider()
        mock_page = MagicMock()
        mock_page.goto.side_effect = RuntimeError("navigation failed")

        with patch.object(provider, "_ensure_page", return_value=mock_page):
            snapshot = provider.navigate("https://example.com")
        assert snapshot.error is not None
        assert "navigation failed" in snapshot.error


class TestPlaywrightScreenshot:
    def test_screenshot_returns_bytes(self) -> None:
        from browser.playwright import PlaywrightBrowserProvider

        provider = PlaywrightBrowserProvider()
        mock_page = MagicMock()
        mock_page.screenshot.return_value = b"\x89PNG_FAKE_DATA"

        with patch.object(provider, "_ensure_page", return_value=mock_page):
            data = provider.screenshot("https://example.com")
        assert data == b"\x89PNG_FAKE_DATA"
        mock_page.close.assert_called_once()

    def test_screenshot_full_page(self) -> None:
        from browser.playwright import PlaywrightBrowserProvider

        provider = PlaywrightBrowserProvider()
        mock_page = MagicMock()
        mock_page.screenshot.return_value = b"full_page_data"

        with patch.object(provider, "_ensure_page", return_value=mock_page):
            data = provider.screenshot("https://example.com", full_page=True)
        mock_page.screenshot.assert_called_with(full_page=True)
        assert data == b"full_page_data"


class TestPlaywrightCrawl:
    def test_crawl_collects_pages(self) -> None:
        from browser.playwright import PlaywrightBrowserProvider

        provider = PlaywrightBrowserProvider()
        mock_page = MagicMock()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_page.goto.return_value = mock_response
        mock_page.content.return_value = "<html><title>Root</title></html>"
        mock_page.title.return_value = "Root"
        mock_page.query_selector_all.return_value = []

        with patch.object(provider, "_ensure_page", return_value=mock_page):
            result = provider.crawl("https://example.com", depth=0)
        assert result.provider == "playwright"
        assert result.crawl_url == "https://example.com"
        assert result.total_pages >= 1

    def test_crawl_respects_max_pages(self) -> None:
        from browser.playwright import PlaywrightBrowserProvider

        provider = PlaywrightBrowserProvider()
        mock_page = MagicMock()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_page.goto.return_value = mock_response
        mock_page.content.return_value = "<html><title>X</title></html>"
        mock_page.title.return_value = "X"
        mock_page.query_selector_all.return_value = []

        with patch.object(provider, "_ensure_page", return_value=mock_page):
            result = provider.crawl("https://example.com", depth=10, max_pages=1)
        assert result.total_pages <= 1