"""Mojeek Search provider — independent crawler-based search."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult


@dataclass
class MojeekProvider(SearchProvider):
    """Mojeek Search API provider.

    Privacy-respecting independent crawler-based search engine.
    No API key required for basic use.
    """

    name: str = "mojeek"
    base_url: str = "https://api.mojeek.com/search"
    default_num_results: int = 10

    def search(
        self,
        query: str,
        num_results: int | None = None,
        **kwargs: Any,
    ) -> SearchResponse:
        api_key = os.environ.get("MOJEEK_API_KEY", "")

        params: dict[str, Any] = {
            "q": query,
            "fmt": "json",
            "result_count": min(num_results or self.default_num_results, 100),
        }
        if api_key:
            params["api_key"] = api_key
        if kwargs.get("language"):
            params["language"] = kwargs["language"]
        if kwargs.get("region"):
            params["region"] = kwargs["region"]

        with httpx.Client(timeout=15.0) as client:
            response = client.get(self.base_url, params=params)
            response.raise_for_status()
            data = response.json()

        raw_results = data.get("response", {}).get("results", [])
        results = [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("desc", ""),
                source="mojeek",
                metadata={
                    "domain": r.get("domain"),
                    "rank": r.get("rank"),
                    "score": r.get("score"),
                },
            )
            for r in raw_results
        ]

        return SearchResponse(
            query=query,
            results=results,
            total_results=int(data.get("response", {}).get("total", 0)),
            provider=self.name,
            raw=data,
        )

    def validate_credentials(self) -> bool:
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    self.base_url,
                    params={"q": "test", "fmt": "json", "result_count": 1},
                )
                return resp.status_code == 200
        except Exception:
            return False