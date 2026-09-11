"""Firecrawl web scraping and crawling provider."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult

logger = logging.getLogger(__name__)

_FIRECRAWL_BASE_URL = "https://api.firecrawl.dev"


class FirecrawlProvider(SearchProvider):
    """Firecrawl web scraping and crawl provider.

    Scrapes and converts websites into clean Markdown. Supports sitemap
    discovery, batch scraping, and crawl capabilities.
    Requires a ``FIRECRAWL_API_KEY`` environment variable or ``api_key`` argument.
    See https://firecrawl.dev
    """

    name = "firecrawl"
    base_url = _FIRECRAWL_BASE_URL

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        import os as _os
        super().__init__(api_key or _os.environ.get("FIRECRAWL_API_KEY", ""), **kwargs)

    def validate_credentials(self) -> bool:
        if not self.api_key:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    f"{self.base_url}/v1/health",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                return resp.status_code < 500
        except httpx.RequestError:
            return False

    def search(self, query: str, num_results: int = 10, **kwargs: Any) -> SearchResponse:
        if not self.api_key:
            raise RuntimeError(
                "Firecrawl API key not set. Set FIRECRAWL_API_KEY or pass api_key."
            )
        payload: dict[str, Any] = {
            "query": query,
            "limit": num_results,
        }
        if kwargs.get("screenshot"):
            payload["screenshot"] = True
        if kwargs.get("page_options"):
            payload["pageOptions"] = kwargs["page_options"]

        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                f"{self.base_url}/v1/search",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        results: list[SearchResult] = []
        for item in data.get("data", []):
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("description", item.get("markdown", ""))[:300],
                    score=float(item.get("score", 0.0)),
                    source=item.get("source", ""),
                    raw=item,
                )
            )

        return SearchResponse(
            query=query,
            results=results,
            total_results=data.get("total", len(results)),
            provider=self.name,
            raw=data,
        )

    def scrape(self, url: str, **kwargs: Any) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("Firecrawl API key not set.")
        payload: dict[str, Any] = {"url": url}
        if kwargs.get("formats"):
            payload["formats"] = kwargs["formats"]
        else:
            payload["formats"] = ["markdown", "html"]
        if kwargs.get("page_options"):
            payload["pageOptions"] = kwargs["page_options"]

        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                f"{self.base_url}/v0/scrape",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()
