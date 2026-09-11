"""DuckDuckGo search provider — free, no API key required."""

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

DDG_API_URL = "https://api.duckduckgo.com/"


class DuckDuckGoProvider(SearchProvider):
    """DuckDuckGo Instant Answer API — no API key required.

    Covers Wikipedia, topical articles, and disambiguation. For full web
    search results use the ``ddg-html`` endpoint or switch to Tavily/Perplexity.
    """

    name = "duckduckgo"
    base_url = DDG_API_URL

    def __init__(
        self,
        api_key: str | None = None,
        *,
        language: str = "en-US",
        **kwargs: Any,
    ) -> None:
        super().__init__(api_key, **kwargs)
        self.language = language

    def validate_credentials(self) -> bool:
        return True

    def search(
        self,
        query: str,
        *,
        num_results: int = 10,
        **kwargs: Any,
    ) -> SearchResponse:
        params: dict[str, Any] = {
            "q": query,
            "format": "json",
            "no_html": 1,
            "skip_disambig": 1,
            "kl": self.language,
        }
        params.update(kwargs)

        with httpx.Client(timeout=10.0) as client:
            resp = client.get(DDG_API_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        results: list[SearchResult] = []

        for topic in data.get("RelatedTopics", [])[:num_results]:
            if "Text" not in topic or "FirstURL" not in topic:
                continue
            results.append(
                SearchResult(
                    title=topic.get("Text", ""),
                    url=topic.get("FirstURL", ""),
                    snippet=topic.get("Text", ""),
                    score=0.0,
                    source="duckduckgo",
                    raw=topic,
                )
            )

        if data.get("AbstractText") and data.get("AbstractURL"):
            results.insert(
                0,
                SearchResult(
                    title=data.get("Heading", query),
                    url=data.get("AbstractURL", ""),
                    snippet=data.get("AbstractText", ""),
                    score=1.0,
                    source=data.get("AbstractSource", ""),
                    raw=data,
                ),
            )

        return SearchResponse(
            query=query,
            results=results[:num_results],
            total_results=len(results),
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
            "format": "json",
            "no_html": 1,
            "kl": self.language,
        }
        params.update(kwargs)

        with httpx.Client(timeout=10.0) as client:
            resp = client.get(DDG_API_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        results = [
            SearchResult(
                title=r.get("Text", ""),
                url=r.get("FirstURL", ""),
                snippet=r.get("Text", ""),
                score=0.0,
                source="duckduckgo-news",
                raw=r,
            )
            for r in data.get("RelatedTopics", [])[:num_results]
            if "Text" in r and "FirstURL" in r
        ]

        return SearchResponse(
            query=query,
            results=results,
            total_results=len(results),
            provider=self.name,
            raw=data,
        )
