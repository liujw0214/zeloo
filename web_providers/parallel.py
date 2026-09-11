"""Parallel.ai provider — multi-engine parallel search."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult


@dataclass
class ParallelProvider(SearchProvider):
    """Parallel.ai search API provider.

    Performs parallel searches across multiple engines and
    aggregates results with AI-powered ranking.
    """

    name: str = "parallel"
    base_url: str = "https://api.parallel.ai/v1beta"
    default_num_results: int = 10

    def search(
        self,
        query: str,
        num_results: int | None = None,
        **kwargs: Any,
    ) -> SearchResponse:
        api_key = os.environ.get("PARALLEL_API_KEY", "")
        if not api_key:
            raise ValueError("PARALLEL_API_KEY must be set")

        endpoint = f"{self.base_url}/search"
        payload: dict[str, Any] = {
            "query": query,
            "max_results": min(num_results or self.default_num_results, 20),
        }
        if kwargs.get("mode"):
            payload["mode"] = kwargs["mode"]
        if kwargs.get("engines"):
            payload["engines"] = kwargs["engines"]
        if kwargs.get("recency"):
            payload["recency_filter"] = kwargs["recency"]

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "x-parallel-beta": "search-extract-2025-09",
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.post(endpoint, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        results = []
        for r in data.get("results", []):
            results.append(
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=r.get("excerpts", [""])[0] if r.get("excerpts") else "",
                    source="parallel",
                    metadata={
                        "engine": r.get("engine"),
                        "publish_date": r.get("publish_date"),
                        "confidence": r.get("confidence"),
                    },
                )
            )

        return SearchResponse(
            query=query,
            results=results,
            total_results=len(results),
            provider=self.name,
            raw=data,
        )

    def news_search(
        self,
        query: str,
        num_results: int = 10,
        **kwargs: Any,
    ) -> SearchResponse:
        kwargs["mode"] = "news"
        return self.search(query, num_results, **kwargs)

    def validate_credentials(self) -> bool:
        api_key = os.environ.get("PARALLEL_API_KEY", "")
        if not api_key:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    f"{self.base_url}/search",
                    json={"query": "test", "max_results": 1},
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                )
                return resp.status_code == 200
        except Exception:
            return False