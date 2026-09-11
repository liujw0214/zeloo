"""Google Scholar provider — academic paper search."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult

logger = logging.getLogger(__name__)


@dataclass
class GoogleScholarProvider(SearchProvider):
    """Google Scholar search via SerpAPI / custom scraper.

    Note: Google Scholar doesn't have an official API.
    Uses SerpAPI's Google Scholar engine when SERPAPI_API_KEY is set.
    """

    name: str = "google_scholar"
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
            logger.warning(
                "Google Scholar requires SERPAPI_API_KEY (no official API)"
            )
            return SearchResponse(
                query=query, results=[], total_results=0, provider=self.name,
            )

        params: dict[str, Any] = {
            "api_key": api_key,
            "engine": "google_scholar",
            "q": query,
            "num": min(num_results or self.default_num_results, 100),
        }
        if kwargs.get("author"):
            params["author"] = kwargs["author"]
        if kwargs.get("year_low"):
            params["as_ylo"] = kwargs["year_low"]
        if kwargs.get("year_high"):
            params["as_yhi"] = kwargs["year_high"]
        if kwargs.get("citations_only"):
            params["as_sdt"] = "0,5"

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
                source="google_scholar",
                metadata={
                    "authors": r.get("publication_info", {}).get("authors", []),
                    "year": r.get("publication_info", {}).get("year"),
                    "venue": r.get("publication_info", {}).get("venue"),
                    "citations": r.get("inline_links", {}).get("cited_by", {}).get("total"),
                    "pdf_url": r.get("resources", [{}])[0].get("link") if r.get("resources") else None,  # noqa: E501
                },
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