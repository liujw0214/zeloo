"""SearXNG search provider — self-hosted meta search engine."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult

logger = logging.getLogger(__name__)


class SearXNGProvider(SearchProvider):
    """SearXNG meta-search provider.

    Aggregates results from 70+ search engines. Can be self-hosted or use
    public instances. No API key required for most public instances.
    See https://searxng.org
    """

    name = "searxng"
    base_url = ""

    def __init__(self, api_key: str | None = None, base_url: str = "", **kwargs: Any) -> None:
        import os as _os
        super().__init__(api_key or _os.environ.get("SEARXNG_BASE_URL", base_url or ""), **kwargs)
        self.base_url = self.api_key or base_url or _os.environ.get(
            "SEARXNG_BASE_URL", "https://search.example.com"
        )

    def validate_credentials(self) -> bool:
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(f"{self.base_url}/healthz")
                return resp.status_code < 500
        except httpx.RequestError:
            return False

    def search(self, query: str, num_results: int = 10, **kwargs: Any) -> SearchResponse:
        params: dict[str, Any] = {
            "q": query,
            "format": "json",
            "engines": kwargs.get("engines", ""),
            "categories": kwargs.get("categories", ""),
            "language": kwargs.get("language", "auto"),
            "safesearch": kwargs.get("safesearch", 1),
        }
        if num_results:
            params["limit"] = min(num_results, 50)

        with httpx.Client(timeout=30.0) as client:
            resp = client.get(
                f"{self.base_url}/search",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        results: list[SearchResult] = []
        for item in data.get("results", [])[:num_results]:
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("content", "")[:300],
                    score=0.0,
                    source=item.get("engine", ""),
                    published_date=item.get("publishedDate"),
                    raw=item,
                )
            )

        return SearchResponse(
            query=query,
            results=results,
            total_results=len(results),
            provider=self.name,
            raw=data,
        )

    def news_search(self, query: str, num_results: int = 10, **kwargs: Any) -> SearchResponse:
        params = kwargs.copy()
        params["categories"] = "news"
        return self.search(query, num_results, **params)
