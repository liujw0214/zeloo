"""Exa search provider — neural search for AI applications."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult

logger = logging.getLogger(__name__)

_EXA_BASE_URL = "https://api.exa.ai"


class ExaProvider(SearchProvider):
    """Exa neural search provider — semantic search optimized for AI.

    Supports full-text, semantic, and keyword search with category filtering.
    Requires an ``EXA_API_KEY`` environment variable or ``api_key`` argument.
    See https://exa.ai
    """

    name = "exa"
    base_url = _EXA_BASE_URL

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        import os as _os
        super().__init__(api_key or _os.environ.get("EXA_API_KEY", ""), **kwargs)

    def validate_credentials(self) -> bool:
        if not self.api_key:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    f"{self.base_url}/health",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                return resp.status_code < 500
        except httpx.RequestError:
            return False

    def search(
        self,
        query: str,
        num_results: int = 10,
        **kwargs: Any,
    ) -> SearchResponse:
        if not self.api_key:
            raise RuntimeError("Exa API key not set. Set EXA_API_KEY or pass api_key.")

        payload: dict[str, Any] = {
            "query": query,
            "numResults": num_results,
        }
        if kwargs.get("type"):
            payload["type"] = kwargs["type"]
        if kwargs.get("category"):
            payload["category"] = kwargs["category"]
        if kwargs.get("text"):
            payload["text"] = {"maxCharacters": kwargs.get("text_max_chars", 1000)}
        if kwargs.get("highlight"):
            payload["highlights"] = {"numSentences": kwargs.get("num_sentences", 3)}

        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{self.base_url}/search",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        results: list[SearchResult] = []
        for item in data.get("results", []):
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("snippet", item.get("text", ""))[:300],
                    score=float(item.get("score", 0.0)),
                    source=item.get("domain", ""),
                    published_date=item.get("publishedDate"),
                    raw=item,
                )
            )

        return SearchResponse(
            query=query,
            results=results,
            total_results=data.get("total", len(results)),
            provider=self.name,
            raw=data,
        )

    def news_search(self, query: str, num_results: int = 10, **kwargs: Any) -> SearchResponse:
        return self.search(query, num_results, type="news", **kwargs)
