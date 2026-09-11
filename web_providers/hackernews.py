"""Hacker News search provider — Algolia-powered HN search."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult

logger = logging.getLogger(__name__)


@dataclass
class HackerNewsProvider(SearchProvider):
    """Hacker News search provider via Algolia HN Search API.

    Free public API for searching HN stories, comments, users.
    """

    name: str = "hackernews"
    base_url: str = "https://hn.algolia.com/api/v1"
    default_num_results: int = 10

    def search(
        self,
        query: str,
        num_results: int | None = None,
        **kwargs: Any,
    ) -> SearchResponse:
        params: dict[str, Any] = {
            "query": query,
            "hitsPerPage": min(num_results or self.default_num_results, 100),
        }
        if kwargs.get("tags"):
            params["tags"] = kwargs["tags"]
        if kwargs.get("numeric_filters"):
            params["numericFilters"] = kwargs["numeric_filters"]
        if kwargs.get("page"):
            params["page"] = kwargs["page"]

        endpoint = f"{self.base_url}/search"
        with httpx.Client(timeout=15.0) as client:
            response = client.get(endpoint, params=params)
            response.raise_for_status()
            data = response.json()

        hits = data.get("hits", [])
        results = [
            SearchResult(
                title=h.get("title", h.get("story_title", "")),
                url=h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID', '')}",
                snippet=h.get("story_text", "") or h.get("comment_text", ""),
                source="hackernews",
                metadata={
                    "object_id": h.get("objectID"),
                    "author": h.get("author"),
                    "points": h.get("points"),
                    "num_comments": h.get("num_comments"),
                    "created_at": h.get("created_at"),
                    "type": h.get("_tags", [None])[0],
                },
            )
            for h in hits
        ]

        return SearchResponse(
            query=query,
            results=results,
            total_results=int(data.get("nbHits", len(results))),
            provider=self.name,
            raw=data,
            metadata={
                "page": data.get("page"),
                "total_pages": data.get("nbPages"),
                "processing_time_ms": data.get("processingTimeMS"),
            },
        )

    def get_front_page(self, limit: int = 30) -> list[dict[str, Any]]:
        """Get top stories from Hacker News front page."""
        with httpx.Client(timeout=15.0) as client:
            ids_resp = client.get(
                "https://hacker-news.firebaseio.com/v0/topstories.json"
            )
            ids_resp.raise_for_status()
            ids = ids_resp.json()[:limit]

        results = []
        for item_id in ids:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
                )
                if resp.status_code == 200:
                    item = resp.json()
                    results.append(item)
        return results

    def validate_credentials(self) -> bool:
        return True