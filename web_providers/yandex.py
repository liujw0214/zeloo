"""You.com Search provider — AI-first search engine."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult


@dataclass
class YouProvider(SearchProvider):
    """You.com AI Search API provider.

    AI-powered search engine returning summaries with citations.
    """

    name: str = "you"
    base_url: str = "https://api.ydc-index.io/v1"
    default_num_results: int = 10

    def search(
        self,
        query: str,
        num_results: int | None = None,
        **kwargs: Any,
    ) -> SearchResponse:
        api_key = os.environ.get("YOU_API_KEY", "")
        if not api_key:
            raise ValueError("YOU_API_KEY must be set")

        endpoint = f"{self.base_url}/search"
        params = {
            "query": query,
            "num_web_results": min(num_results or self.default_num_results, 20),
        }
        if kwargs.get("safesearch"):
            params["safesearch"] = kwargs["safesearch"]
        if kwargs.get("region"):
            params["region"] = kwargs["region"]

        headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=20.0) as client:
            response = client.get(endpoint, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()

        hits = data.get("hits", [])
        results = [
            SearchResult(
                title=h.get("title", ""),
                url=h.get("url", ""),
                snippet=h.get("description", ""),
                source="you",
                metadata={
                    "age": h.get("age"),
                    "favicon_url": h.get("favicon_url"),
                    "thumbnail_url": h.get("thumbnail_url"),
                },
            )
            for h in hits
        ]

        news = data.get("news", [])
        for n in news:
            results.append(
                SearchResult(
                    title=n.get("title", ""),
                    url=n.get("url", ""),
                    snippet=n.get("description", ""),
                    source="you",
                    metadata={"type": "news", "age": n.get("age")},
                )
            )

        return SearchResponse(
            query=query,
            results=results,
            total_results=len(results),
            provider=self.name,
            raw=data,
            metadata={"ai_summary": data.get("abstract")},
        )

    def validate_credentials(self) -> bool:
        api_key = os.environ.get("YOU_API_KEY", "")
        if not api_key:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    f"{self.base_url}/search",
                    params={"query": "test", "num_web_results": 1},
                    headers={"X-API-Key": api_key},
                )
                return resp.status_code == 200
        except Exception:
            return False