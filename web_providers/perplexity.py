"""Perplexity search provider — AI-powered conversational search."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from web_providers.base import (
    SearchProvider,
    SearchResponse,
    SearchResult,
)

logger = logging.getLogger(__name__)

PERPLEXITY_API_URL = "https://api.perplexity.ai/search"


class PerplexityProvider(SearchProvider):
    """Perplexity AI search — conversational, source-grounded answers.

    Requires a ``PERPLEXITY_API_KEY`` environment variable or ``api_key`` argument.
    See https://perplexity.ai
    """

    name = "perplexity"
    base_url = PERPLEXITY_API_URL

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str = "sonar",
        **kwargs: Any,
    ) -> None:
        import os

        super().__init__(api_key or os.environ.get("PERPLEXITY_API_KEY", ""), **kwargs)
        self.model = model

    def validate_credentials(self) -> bool:
        if not self.api_key:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    PERPLEXITY_API_URL,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": "test"}],
                        "max_tokens": 10,
                    },
                )
                return resp.status_code in (200, 400, 401, 403)
        except httpx.RequestError:
            return False

    def search(
        self,
        query: str,
        *,
        num_results: int = 10,
        **kwargs: Any,
    ) -> SearchResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": query}],
            "max_tokens": 500,
            "temperature": 0.2,
        }
        payload.update(kwargs)

        with httpx.Client(timeout=20.0) as client:
            resp = client.post(
                PERPLEXITY_API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        raw_results = data.get("results", [])
        results = [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("snippet", ""),
                score=r.get("score", 0.0),
                source=r.get("source", ""),
                published_date=r.get("published_date"),
                raw=r,
            )
            for r in raw_results
        ]

        if not results:
            answer = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if answer:
                results.append(
                    SearchResult(
                        title="Perplexity Answer",
                        url="",
                        snippet=answer,
                        score=1.0,
                        source="perplexity",
                    )
                )

        return SearchResponse(
            query=query,
            results=results[:num_results],
            total_results=len(results),
            provider=self.name,
            raw=data,
        )

    def news_search(
        self,
        query: str,
        *,
        num_results: int = 10,
        **kwargs: Any,
    ) -> SearchResponse:
        return self.search(query, num_results=num_results, **kwargs)
