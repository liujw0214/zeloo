"""Unit tests for browser module."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)


def test_page_snapshot_to_dict():
    from browser.base import PageSnapshot
    s = PageSnapshot(
        url="https://example.com",
        title="Example",
        content="Hello world",
        status_code=200,
    )
    d = s.to_dict()
    assert d["url"] == "https://example.com"
    assert d["title"] == "Example"
    assert d["content"] == "Hello world"


def test_crawl_result_to_dict():
    from browser.base import CrawlResult, PageSnapshot
    r = CrawlResult(
        pages=[
            PageSnapshot(url="https://a.com", title="A", content="", status_code=200),
        ],
        provider="browserbase",
        crawl_url="https://seed.com",
        depth=1,
        total_pages=1,
    )
    d = r.to_dict()
    assert d["provider"] == "browserbase"
    assert len(d["pages"]) == 1


def test_registry_discovers_providers():
    from browser.registry import list_providers
    names = list_providers()
    assert "browserbase" in names
    assert "firecrawl" in names


def test_registry_get_provider():
    from browser.registry import get_provider
    p = get_provider("browserbase")
    assert p is not None
    assert p.name == "browserbase"
    none_p = get_provider("nonexistent")
    assert none_p is None


def test_browserbase_validate_no_key():
    from browser.browserbase import BrowserBaseProvider
    p = BrowserBaseProvider(api_key="")
    assert p.validate_credentials() is False


def test_browserbase_navigate_mock():
    from browser.browserbase import BrowserBaseProvider
    mock_data = {
        "events": [
            {
                "textContent": "Hello from browser",
                "html": "<html></html>",
                "statusCode": 200,
                "title": "Test Page",
            }
        ],
        "title": "Test Page",
        "textContent": "Hello from browser",
        "html": "<html></html>",
        "statusCode": 200,
    }
    with patch("browser.browserbase.httpx") as mock_httpx:
        mc = MagicMock()
        mock_httpx.Client.return_value.__enter__.return_value = mc
        post_resp = MagicMock()
        post_resp.json.return_value = {"id": "sess123", "debuggerUrl": "http://debug:9222"}
        get_resp = MagicMock()
        get_resp.json.return_value = mock_data
        mc.post.return_value = post_resp
        mc.get.return_value = get_resp
        p = BrowserBaseProvider(api_key="fake-key")
        snap = p.navigate("https://example.com")
        assert snap.url == "https://example.com"
        assert "Hello from browser" in snap.content
        assert snap.status_code == 200


def test_firecrawl_validate_no_key():
    from browser.firecrawl import FirecrawlProvider
    p = FirecrawlProvider(api_key="")
    assert p.validate_credentials() is False


def test_firecrawl_navigate_mock():
    from browser.firecrawl import FirecrawlProvider
    mock_data = {
        "content": "Scraped content here",
        "metadata": {"title": "Doc Title", "statusCode": 200},
    }
    with patch("browser.firecrawl.httpx") as mock_httpx:
        mc = MagicMock()
        mock_httpx.Client.return_value.__enter__.return_value = mc
        post_resp = MagicMock()
        post_resp.json.return_value = mock_data
        mc.post.return_value = post_resp
        p = FirecrawlProvider(api_key="fake-key")
        snap = p.navigate("https://docs.example.com")
        assert snap.url == "https://docs.example.com"
        assert "Scraped content here" in snap.content
        assert snap.title == "Doc Title"


if __name__ == "__main__":
    test_page_snapshot_to_dict()
    test_crawl_result_to_dict()
    test_registry_discovers_providers()
    test_registry_get_provider()
    test_browserbase_validate_no_key()
    test_browserbase_navigate_mock()
    test_firecrawl_validate_no_key()
    test_firecrawl_navigate_mock()
    print("All browser tests passed!")
