"""Kagi Search provider — privacy-focused search engine."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult


@dataclass
class KagiProvider(SearchProvider):
    """Kagi Search API provider.

    Privacy-focused search engine with high-quality results.
    Supports custom ranking and various search types.
    """

    name: str = "kagi"
    base_url: str = "https://kagi.com/api/v0"
    default_num_results: int = 10

    def search(
        self,
        query: str,
        num_results: int | None = None,
        **kwargs: Any,
    ) -> SearchResponse:
        api_key = os.environ.get("KAGI_API_KEY", "")
        if not api_key:
            raise ValueError("KAGI_API_KEY must be set")

        endpoint = f"{self.base_url}/search"
        params: dict[str, Any] = {"q": query, "limit": min(num_results or self.default_num_results, 50)}  # noqa: E501
        if kwargs.get("language"):
            params["hl"] = kwargs["language"]
        if kwargs.get("region"):
            params["gl"] = kwargs["region"]

        headers = {
            "Authorization": f"Bot {api_key}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=15.0) as client:
            response = client.get(endpoint, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()

        hits = data.get("data", [])
        results = [
            SearchResult(
                title=h.get("title", ""),
                url=h.get("url", ""),
                snippet=h.get("snippet", ""),
                source="kagi",
                metadata={
                    "published": h.get("published"),
                    "list_type": h.get("list_type"),
                    "t": h.get("t"),  # type: doc/news/etc
                    "node": h.get("node"),  # for news nodes
                },
            )
            for h in hits
        ]

        related_searches = data.get("related_searches", [])

        return SearchResponse(
            query=query,
            results=results,
            total_results=int(data.get("meta", {}).get("total_results", 0))
            or len(results),
            provider=self.name,
            raw=data,
            metadata={"related_searches": related_searches},
        )

    def news_search(
        self,
        query: str,
        num_results: int = 10,
        **kwargs: Any,
    ) -> SearchResponse:
        kwargs["t"] = "news"
        result = self.search(query, num_results, **kwargs)
        result.results = [
            r for r in result.results if r.metadata.get("t") == "news"
        ]
        return result

    def validate_credentials(self) -> bool:
        api_key = os.environ.get("KAGI_API_KEY", "")
        if not api_key:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    f"{self.base_url}/search",
                    params={"q": "test", "limit": 1},
                    headers={"Authorization": f"Bot {api_key}"},
                )
                return resp.status_code == 200
        except Exception:
            return False