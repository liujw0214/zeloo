"""Yahoo Search provider — legacy Yahoo search API."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult

logger = logging.getLogger(__name__)


@dataclass
class YahooSearchProvider(SearchProvider):
    """Yahoo Search API via SerpAPI.

    Note: Yahoo discontinued direct API; uses SerpAPI's Yahoo engine.
    """

    name: str = "yahoo_search"
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
            logger.warning("Yahoo via SerpAPI requires SERPAPI_API_KEY")
            return SearchResponse(
                query=query, results=[], total_results=0, provider=self.name,
            )

        params: dict[str, Any] = {
            "api_key": api_key,
            "engine": "yahoo",
            "p": query,
            "num": min(num_results or self.default_num_results, 100),
        }
        if kwargs.get("region"):
            params["vl"] = kwargs["region"]
        if kwargs.get("language"):
            params["hl"] = kwargs["language"]

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
                source="yahoo_search",
                metadata={"displayed_link": r.get("displayed_link")},
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

    def validate_credentials(self) -> bool:
        return bool(os.environ.get("SERPAPI_API_KEY", ""))