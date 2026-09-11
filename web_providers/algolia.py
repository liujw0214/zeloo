"""Algolia Search provider — hosted search-as-a-service."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult

logger = logging.getLogger(__name__)


@dataclass
class AlgoliaProvider(SearchProvider):
    """Algolia Search provider.

    Hosted full-text search API with typo-tolerance and ranking.
    """

    name: str = "algolia"
    base_url: str = "https://www.algolia.net/api/v1"
    default_num_results: int = 10

    def search(
        self,
        query: str,
        num_results: int | None = None,
        **kwargs: Any,
    ) -> SearchResponse:
        app_id = os.environ.get("ALGOLIA_APP_ID", "")
        api_key = os.environ.get("ALGOLIA_SEARCH_API_KEY", "")
        index_name = os.environ.get("ALGOLIA_INDEX_NAME", "")

        if not app_id or not api_key or not index_name:
            logger.warning(
                "Algolia requires ALGOLIA_APP_ID, ALGOLIA_SEARCH_API_KEY, "
                "ALGOLIA_INDEX_NAME"
            )
            return SearchResponse(
                query=query, results=[], total_results=0, provider=self.name,
            )

        endpoint = f"https://{app_id}-dsn.algolia.net/1/indexes/{index_name}/query"

        params: dict[str, Any] = {
            "query": query,
            "hitsPerPage": min(num_results or self.default_num_results, 100),
        }
        if kwargs.get("facet"):
            params["facetFilters"] = kwargs["facet"]
        if kwargs.get("filter"):
            params["filters"] = kwargs["filter"]
        if kwargs.get("ranking"):
            params["ranking"] = kwargs["ranking"]

        headers = {
            "X-Algolia-Application-Id": app_id,
            "X-Algolia-API-Key": api_key,
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=15.0) as client:
            response = client.post(endpoint, json=params, headers=headers)
            response.raise_for_status()
            data = response.json()

        hits = data.get("hits", [])
        results = [
            SearchResult(
                title=h.get("title", h.get("name", "")),
                url=h.get("url", ""),
                snippet=h.get("description", h.get("summary", "")),
                source="algolia",
                metadata={
                    "object_id": h.get("objectID"),
                    "highlight": h.get("_highlightResult"),
                    "ranking": h.get("_rankingInfo"),
                    "type": h.get("type"),
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
                "processing_time_ms": data.get("processingTimeMS"),
                "page": data.get("page"),
                "total_pages": data.get("nbPages"),
            },
        )

    def validate_credentials(self) -> bool:
        return bool(
            os.environ.get("ALGOLIA_APP_ID")
            and os.environ.get("ALGOLIA_SEARCH_API_KEY")
        )