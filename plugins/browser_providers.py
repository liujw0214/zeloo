"""Browser provider plugins — alternative backends for web automation.

While :mod:`tools.browser_tools` uses a local Playwright browser, this
module provides cloud-based and scraping-focused alternatives that can
be used when a local browser is unavailable or when scraping at scale.

Providers:
  * ``browserbase`` — headless cloud browsers via the Browserbase API
  * ``firecrawl``  — extract clean markdown from any URL
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "BrowserProvider",
    "BrowserbaseProvider",
    "FirecrawlProvider",
    "get_browser_provider",
    "list_browser_providers",
]


@dataclass
class BrowserResult:
    """Result from a browser action."""

    url: str
    content: str
    title: str = ""
    success: bool = True
    error: str = ""


class BrowserProvider(ABC):
    """Abstract base for cloud/scraping browser providers."""

    name: str = "base"

    @abstractmethod
    def fetch(self, url: str, **kwargs: Any) -> BrowserResult:
        """Fetch a URL and return extracted content."""


class BrowserbaseProvider(BrowserProvider):
    """Browserbase cloud browser provider.

    Uses the Browserbase session API to load a page in a headless cloud
    browser and return its HTML content.

    Requires ``BROWSERBASE_API_KEY`` and ``BROWSERBASE_PROJECT_ID``.
    """

    name = "browserbase"

    def __init__(
        self,
        api_key: str | None = None,
        project_id: str | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("BROWSERBASE_API_KEY", "")
        self.project_id = project_id or os.environ.get("BROWSERBASE_PROJECT_ID", "")

    def fetch(self, url: str, **kwargs: Any) -> BrowserResult:
        """Load a page in a Browserbase cloud session and return its HTML."""
        import httpx

        if not self.api_key or not self.project_id:
            return BrowserResult(
                url=url,
                content="",
                success=False,
                error=(
                    "BROWSERBASE_API_KEY and BROWSERBASE_PROJECT_ID "
                    "environment variables are required."
                ),
            )

        api_url = (
            f"https://api.browserbase.com/v1/sessions/extract"
            f"?sessionId={kwargs.get('session_id', '')}"
        )
        headers = {
            "X-BB-API-Key": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "url": url,
            "projectId": self.project_id,
            "allFrames": kwargs.get("all_frames", False),
        }

        try:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(api_url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()

            return BrowserResult(
                url=url,
                content=data.get("content", ""),
                title=data.get("title", ""),
                success=True,
            )
        except Exception as exc:
            return BrowserResult(
                url=url,
                content="",
                success=False,
                error=str(exc),
            )


class FirecrawlProvider(BrowserProvider):
    """Firecrawl web scraping provider.

    Extracts clean markdown content from any URL using the Firecrawl API.

    Requires ``FIRECRAWL_API_KEY``.
    """

    name = "firecrawl"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("FIRECRAWL_API_KEY", "")

    def fetch(self, url: str, **kwargs: Any) -> BrowserResult:
        """Scrape a URL and return clean markdown content."""
        import httpx

        if not self.api_key:
            return BrowserResult(
                url=url,
                content="",
                success=False,
                error="FIRECRAWL_API_KEY environment variable is required.",
            )

        api_url = "https://api.firecrawl.dev/v1/scrape"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "url": url,
            "formats": kwargs.get("formats", ["markdown"]),
            "onlyMainContent": kwargs.get("only_main_content", True),
        }

        try:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(api_url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()

            result = data.get("data", {})
            return BrowserResult(
                url=url,
                content=result.get("markdown", ""),
                title=result.get("metadata", {}).get("title", ""),
                success=True,
            )
        except Exception as exc:
            return BrowserResult(
                url=url,
                content="",
                success=False,
                error=str(exc),
            )

    def crawl(self, url: str, limit: int = 10, **kwargs: Any) -> list[BrowserResult]:
        """Crawl a site starting from *url*, returning up to *limit* pages."""
        import httpx

        if not self.api_key:
            return [
                BrowserResult(
                    url=url,
                    content="",
                    success=False,
                    error="FIRECRAWL_API_KEY required.",
                )
            ]

        api_url = "https://api.firecrawl.dev/v1/crawl"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "url": url,
            "limit": limit,
            "scrapeOptions": {
                "formats": ["markdown"],
                "onlyMainContent": kwargs.get("only_main_content", True),
            },
        }

        try:
            with httpx.Client(timeout=120.0) as client:
                resp = client.post(api_url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()

            crawl_id = data.get("id")
            if not crawl_id:
                return [
                    BrowserResult(url=url, content="", success=False, error="No crawl ID returned.")
                ]

            import time

            results: list[BrowserResult] = []
            for _ in range(120):
                status_resp = client.get(
                    f"{api_url}/{crawl_id}", headers=headers
                )
                status_resp.raise_for_status()
                status_data = status_resp.json()

                if status_data.get("status") == "completed":
                    for item in status_data.get("data", []):
                        md = item.get("markdown", "")
                        results.append(
                            BrowserResult(
                                url=item.get("url", url),
                                content=md,
                                title=item.get("metadata", {}).get("title", ""),
                                success=bool(md),
                            )
                        )
                    break
                if status_data.get("status") == "failed":
                    results.append(
                        BrowserResult(url=url, content="", success=False, error="Crawl failed.")
                    )
                    break
                time.sleep(1.0)

            return results[:limit]
        except Exception as exc:
            return [
                BrowserResult(url=url, content="", success=False, error=str(exc))
            ]


_REGISTRY: dict[str, type[BrowserProvider]] = {
    "browserbase": BrowserbaseProvider,
    "firecrawl": FirecrawlProvider,
}


def get_browser_provider(name: str, **kwargs: Any) -> BrowserProvider | None:
    """Return an instance of the named browser provider, or None."""
    cls = _REGISTRY.get(name.lower())
    if cls is None:
        return None
    return cls(**kwargs)


def list_browser_providers() -> list[str]:
    """Return the names of all available browser providers."""
    return sorted(_REGISTRY.keys())
