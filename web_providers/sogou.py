"""Sogou Search provider — Chinese search engine."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult

logger = logging.getLogger(__name__)


@dataclass
class SogouProvider(SearchProvider):
    """Sogou search via SerpAPI.

    Chinese search engine popular for WeChat content indexing.
    """

    name: str = "sogou"
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
            logger.warning("Sogou via SerpAPI requires SERPAPI_API_KEY")
            return SearchResponse(
                query=query, results=[], total_results=0, provider=self.name,
            )

        params: dict[str, Any] = {
            "api_key": api_key,
            "engine": "sogou",
            "q": query,
            "num": min(num_results or self.default_num_results, 100),
        }
        if kwargs.get("time_filter"):
            params["tbs"] = kwargs["time_filter"]

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
                source="sogou",
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