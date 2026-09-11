"""Bing Web Search API provider."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult

logger = logging.getLogger(__name__)


@dataclass
class BingWebProvider(SearchProvider):
    """Bing Web Search API provider (Azure Cognitive Services)."""

    name: str = "bing_web"
    base_url: str = "https://api.bing.microsoft.com/v7.0/search"
    default_num_results: int = 10

    def search(
        self,
        query: str,
        num_results: int | None = None,
        **kwargs: Any,
    ) -> SearchResponse:
        api_key = os.environ.get("BING_SEARCH_API_KEY", "")
        if not api_key:
            logger.warning("Bing Web requires BING_SEARCH_API_KEY")
            return SearchResponse(
                query=query, results=[], total_results=0, provider=self.name,
            )

        params: dict[str, Any] = {
            "q": query,
            "count": min(num_results or self.default_num_results, 50),
            "responseFilter": "webPages",
        }
        if kwargs.get("market"):
            params["mkt"] = kwargs["market"]
        if kwargs.get("language"):
            params["setLang"] = kwargs["language"]
        if kwargs.get("safe_search"):
            params["safeSearch"] = kwargs["safe_search"]
        if kwargs.get("time_filter"):
            params["freshness"] = kwargs["time_filter"]

        headers = {
            "Ocp-Apim-Subscription-Key": api_key,
        }

        with httpx.Client(timeout=15.0) as client:
            response = client.get(self.base_url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()

        pages = data.get("webPages", {}).get("value", [])
        results = [
            SearchResult(
                title=p.get("name", ""),
                url=p.get("url", ""),
                snippet=p.get("snippet", ""),
                source="bing_web",
                metadata={
                    "display_url": p.get("displayUrl"),
                    "date_published": p.get("datePublished"),
                    "language": p.get("language"),
                },
            )
            for p in pages
        ]

        return SearchResponse(
            query=query,
            results=results,
            total_results=int(data.get("webPages", {}).get("totalEstimatedMatches", len(results))),
            provider=self.name,
            raw=data,
        )

    def news_search(
        self,
        query: str,
        num_results: int = 10,
        **kwargs: Any,
    ) -> SearchResponse:
        api_key = os.environ.get("BING_SEARCH_API_KEY", "")
        if not api_key:
            return SearchResponse(
                query=query, results=[], total_results=0, provider=self.name,
            )

        url = "https://api.bing.microsoft.com/v7.0/news/search"
        params = {"q": query, "count": min(num_results, 50)}
        headers = {"Ocp-Apim-Subscription-Key": api_key}

        with httpx.Client(timeout=15.0) as client:
            response = client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()

        articles = data.get("value", [])
        results = [
            SearchResult(
                title=a.get("name", ""),
                url=a.get("url", ""),
                snippet=a.get("description", ""),
                source="bing_web",
                metadata={
                    "date_published": a.get("datePublished"),
                    "provider": a.get("provider", [{}])[0].get("name"),
                },
            )
            for a in articles
        ]

        return SearchResponse(
            query=query,
            results=results,
            total_results=int(data.get("totalEstimatedMatches", len(results))),
            provider=self.name,
            raw=data,
        )

    def validate_credentials(self) -> bool:
        return bool(os.environ.get("BING_SEARCH_API_KEY", ""))