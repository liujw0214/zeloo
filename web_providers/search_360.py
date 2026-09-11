"""360 Search provider — Chinese search engine."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult


@dataclass
class Search360Provider(SearchProvider):
    """360 Search API provider.

    Chinese search engine with safe search support.
    """

    name: str = "search_360"
    base_url: str = "https://api.so.360.cn/v3/search/news"
    default_num_results: int = 10

    def search(
        self,
        query: str,
        num_results: int | None = None,
        **kwargs: Any,
    ) -> SearchResponse:
        api_key = os.environ.get("SEARCH_360_API_KEY", "")
        if not api_key:
            raise ValueError("SEARCH_360_API_KEY must be set")

        endpoint = "https://api.so.360.cn/v3/search/news"
        params: dict[str, Any] = {
            "q": query,
            "count": min(num_results or self.default_num_results, 50),
            "token": api_key,
        }
        if kwargs.get("type"):
            params["type"] = kwargs["type"]
        if kwargs.get("site"):
            params["site"] = kwargs["site"]

        with httpx.Client(timeout=15.0) as client:
            response = client.get(endpoint, params=params)
            response.raise_for_status()
            data = response.json()

        items = data.get("result", [])
        results = []
        for item in items:
            doc = item.get("doc", {})
            results.append(
                SearchResult(
                    title=doc.get("title", ""),
                    url=doc.get("url", ""),
                    snippet=doc.get("content", ""),
                    source="search_360",
                    metadata={
                        "publish_time": doc.get("publish_time"),
                        "source": doc.get("media", {}).get("name"),
                        "score": doc.get("score"),
                    },
                )
            )

        return SearchResponse(
            query=query,
            results=results,
            total_results=int(data.get("total", 0)),
            provider=self.name,
            raw=data,
        )

    def web_search(
        self,
        query: str,
        num_results: int = 10,
        **kwargs: Any,
    ) -> SearchResponse:
        api_key = os.environ.get("SEARCH_360_API_KEY", "")
        if not api_key:
            raise ValueError("SEARCH_360_API_KEY must be set")

        endpoint = "https://api.so.360.cn/v3/search/web"
        params: dict[str, Any] = {
            "q": query,
            "count": min(num_results, 50),
            "token": api_key,
        }
        with httpx.Client(timeout=15.0) as client:
            response = client.get(endpoint, params=params)
            response.raise_for_status()
            data = response.json()

        items = data.get("result", [])
        results = [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("snippet", ""),
                source="search_360",
                metadata={"domain": item.get("domain")},
            )
            for item in items
        ]

        return SearchResponse(
            query=query,
            results=results,
            total_results=int(data.get("total", 0)),
            provider=self.name,
            raw=data,
        )

    def validate_credentials(self) -> bool:
        api_key = os.environ.get("SEARCH_360_API_KEY", "")
        if not api_key:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    "https://api.so.360.cn/v3/search/news",
                    params={"q": "test", "count": 1, "token": api_key},
                )
                return resp.status_code == 200
        except Exception:
            return False