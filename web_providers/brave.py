"""Brave Search provider — privacy-first search API with full web results."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from web_providers.base import (
    SearchProvider,
    SearchResponse,
    SearchResult,
)

logger = logging.getLogger(__name__)

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


class BraveProvider(SearchProvider):
    """Brave Search provider.

    Requires a ``BRAVE_SEARCH_API_KEY`` environment variable or ``api_key``
    argument. Free tier: 2,000 queries/month. See https://brave.com/search/api/
    """

    name = "brave"
    base_url = BRAVE_SEARCH_URL

    def __init__(
        self,
        api_key: str | None = None,
        *,
        safe_search: str = "moderate",
        **kwargs: Any,
    ) -> None:
        import os

        super().__init__(api_key or os.environ.get("BRAVE_SEARCH_API_KEY", ""), **kwargs)
        self.safe_search = safe_search

    def validate_credentials(self) -> bool:
        if not self.api_key:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    BRAVE_SEARCH_URL,
                    headers={"X-Subscription-Token": self.api_key},
                    params={"q": "test", "count": 1},
                )
                return resp.status_code in (200, 401, 403)
        except httpx.RequestError:
            return False

    def search(
        self,
        query: str,
        *,
        num_results: int = 10,
        **kwargs: Any,
    ) -> SearchResponse:
        params: dict[str, Any] = {
            "q": query,
            "count": min(num_results, 20),
            "safe_search": self.safe_search,
        }
        params.update(kwargs)

        headers = {
            "X-Subscription-Token": self.api_key,
            "Accept": "application/json",
        }

        with httpx.Client(timeout=15.0) as client:
            resp = client.get(BRAVE_SEARCH_URL, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()

        results = []
        web_results = data.get("web", {}).get("results", [])
        for r in web_results:
            results.append(
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=r.get("description", ""),
                    score=r.get("page_age", 0.0),
                    source=r.get("meta_url", {}).get("netloc", ""),
                    published_date=r.get("age"),
                    raw=r,
                )
            )

        return SearchResponse(
            query=query,
            results=results,
            total_results=data.get("web", {}).get("count", len(results)),
            provider=self.name,
            raw=data,
        )

    def news_search(
        self,
        query: str,
        *,
        num_results: int = 10,
        **kwargs: Any,
    ) -> SearchResponse:
        params: dict[str, Any] = {
            "q": query,
            "count": min(num_results, 20),
            "safe_search": self.safe_search,
        }
        params.update(kwargs)

        headers = {
            "X-Subscription-Token": self.api_key,
            "Accept": "application/json",
        }
        news_url = "https://api.search.brave.com/res/v1/news/search"

        with httpx.Client(timeout=15.0) as client:
            resp = client.get(news_url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()

        results = []
        news_results = data.get("results", [])
        for r in news_results:
            results.append(
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=r.get("description", ""),
                    score=r.get("relative_time", 0.0),
                    source=r.get("meta_url", {}).get("netloc", ""),
                    published_date=r.get("age"),
                    raw=r,
                )
            )

        return SearchResponse(
            query=query,
            results=results,
            total_results=data.get("total_count", len(results)),
            provider=self.name,
            raw=data,
        )
