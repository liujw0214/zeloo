"""SerpAPI provider — multi-engine search scraping service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult


@dataclass
class SerpAPIProvider(SearchProvider):
    """SerpAPI provider for multi-engine search results.

    Supports Google, Bing, Yahoo, DuckDuckGo, YouTube,
    Amazon and 30+ other search engines.
    """

    name: str = "serpapi"
    base_url: str = "https://serpapi.com/search"
    default_num_results: int = 10

    def search(
        self,
        query: str,
        num_results: int | None = None,
        **kwargs: Any,
    ) -> SearchResponse:
        api_key = os.environ.get("SERPAPI_API_KEY", "")
        if not api_key:
            raise ValueError("SERPAPI_API_KEY must be set")

        params: dict[str, Any] = {
            "api_key": api_key,
            "q": query,
            "num": min(num_results or self.default_num_results, 100),
            "engine": kwargs.get("engine", "google"),
            "output": "json",
        }
        if kwargs.get("country"):
            params["gl"] = kwargs["country"]
        if kwargs.get("language"):
            params["hl"] = kwargs["language"]
        if kwargs.get("time_filter"):
            params["tbs"] = kwargs["time_filter"]
        if kwargs.get("device"):
            params["device"] = kwargs["device"]
        if kwargs.get("page"):
            params["page"] = kwargs["page"]

        with httpx.Client(timeout=30.0) as client:
            response = client.get(self.base_url, params=params)
            response.raise_for_status()
            data = response.json()

        organic = data.get("organic_results", [])
        results = [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("link", ""),
                snippet=r.get("snippet", ""),
                source="serpapi",
                metadata={
                    "position": r.get("position"),
                    "displayed_link": r.get("displayed_link"),
                    "date": r.get("date"),
                    "rich_snippet": r.get("rich_snippet"),
                    "sitelinks": r.get("sitelinks", []),
                },
            )
            for r in organic
        ]

        return SearchResponse(
            query=query,
            results=results,
            total_results=int(data.get("search_information", {}).get("total_results", 0)),
            provider=self.name,
            raw=data,
        )

    def news_search(
        self,
        query: str,
        num_results: int = 10,
        **kwargs: Any,
    ) -> SearchResponse:
        kwargs["engine"] = "google_news"
        return self.search(query, num_results, **kwargs)

    def image_search(
        self,
        query: str,
        num_results: int = 10,
        **kwargs: Any,
    ) -> SearchResponse:
        kwargs["engine"] = "google_images"
        return self.search(query, num_results, **kwargs)

    def validate_credentials(self) -> bool:
        api_key = os.environ.get("SERPAPI_API_KEY", "")
        if not api_key:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    self.base_url,
                    params={"api_key": api_key, "q": "test", "num": 1},
                )
                return resp.status_code == 200
        except Exception:
            return False