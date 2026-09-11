"""Tavily search provider — real-time search API with AI-optimised results."""

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

TAVILY_API_URL = "https://api.tavily.com/search"


class TavilyProvider(SearchProvider):
    """Tavily AI-powered search provider.

    Requires a ``TAVILY_API_KEY`` environment variable or ``api_key`` argument.
    Free tier: 1000 searches/month. See https://tavily.com
    """

    name = "tavily"
    base_url = TAVILY_API_URL

    def __init__(
        self,
        api_key: str | None = None,
        *,
        search_depth: str = "basic",
        **kwargs: Any,
    ) -> None:
        import os

        super().__init__(api_key or os.environ.get("TAVILY_API_KEY", ""), **kwargs)
        self.search_depth = search_depth

    def validate_credentials(self) -> bool:
        if not self.api_key:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    TAVILY_API_URL,
                    params={"api_key": self.api_key, "query": "test", "max_results": 1},
                )
                return resp.status_code in (200, 400, 401, 403)
        except httpx.RequestError:
            return False

    def search(
        self,
        query: str,
        *,
        num_results: int = 10,
        **kwargs: Any,
    ) -> SearchResponse:
        payload: dict[str, Any] = {
            "api_key": self.api_key,
            "query": query,
            "max_results": num_results,
            "search_depth": self.search_depth,
            "include_answer": True,
            "include_raw_content": False,
        }
        payload.update(kwargs)

        with httpx.Client(timeout=15.0) as client:
            resp = client.post(TAVILY_API_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()

        results = [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("content", ""),
                score=r.get("score", 0.0),
                source=r.get("source", ""),
                raw=r,
            )
            for r in data.get("results", [])
        ]

        return SearchResponse(
            query=query,
            results=results,
            total_results=data.get("total_results", len(results)),
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
        url = "https://api.tavily.com/search_news"
        payload: dict[str, Any] = {
            "api_key": self.api_key,
            "query": query,
            "max_results": num_results,
            "search_depth": self.search_depth,
            "include_answer": True,
        }
        payload.update(kwargs)

        with httpx.Client(timeout=15.0) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        results = [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("content", ""),
                score=r.get("score", 0.0),
                source=r.get("source", ""),
                published_date=r.get("published_date"),
                raw=r,
            )
            for r in data.get("results", [])
        ]

        return SearchResponse(
            query=query,
            results=results,
            total_results=data.get("total_results", len(results)),
            provider=self.name,
            raw=data,
        )
