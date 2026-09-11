"""Google Custom Search Engine provider."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult


@dataclass
class GoogleCSEProvider(SearchProvider):
    """Google Programmable Search Engine (CSE) provider.

    Uses Google's JSON API for custom search engines.
    Requires both API key and search engine ID (cx).
    """

    name: str = "google_cse"
    base_url: str = "https://www.googleapis.com/customsearch/v1"
    default_num_results: int = 10

    def search(
        self,
        query: str,
        num_results: int | None = None,
        **kwargs: Any,
    ) -> SearchResponse:
        api_key = os.environ.get("GOOGLE_CSE_API_KEY", "")
        cx = os.environ.get("GOOGLE_CSE_ID", "")
        if not api_key or not cx:
            raise ValueError("GOOGLE_CSE_API_KEY and GOOGLE_CSE_ID must be set")

        params: dict[str, Any] = {
            "key": api_key,
            "cx": cx,
            "q": query,
            "num": min(num_results or self.default_num_results, 10),
        }
        if kwargs.get("language"):
            params["lr"] = f"lang_{kwargs['language']}"
        if kwargs.get("safe"):
            params["safe"] = kwargs["safe"]
        if kwargs.get("time_filter"):
            params["dateRestrict"] = kwargs["time_filter"]
        if kwargs.get("site_filter"):
            params["siteSearch"] = kwargs["site_filter"]

        with httpx.Client(timeout=15.0) as client:
            response = client.get(self.base_url, params=params)
            response.raise_for_status()
            data = response.json()

        items = data.get("items", [])
        results = [
            SearchResult(
                title=i.get("title", ""),
                url=i.get("link", ""),
                snippet=i.get("snippet", ""),
                source="google_cse",
                metadata={
                    "display_link": i.get("displayLink"),
                    "formatted_url": i.get("formattedUrl"),
                    "image": i.get("image"),
                },
            )
            for i in items
        ]

        return SearchResponse(
            query=query,
            results=results,
            total_results=int(data.get("searchInformation", {}).get("totalResults", 0)),
            provider=self.name,
            raw=data,
        )

    def validate_credentials(self) -> bool:
        api_key = os.environ.get("GOOGLE_CSE_API_KEY", "")
        cx = os.environ.get("GOOGLE_CSE_ID", "")
        if not api_key or not cx:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    self.base_url,
                    params={"key": api_key, "cx": cx, "q": "test", "num": 1},
                )
                return resp.status_code == 200
        except Exception:
            return False

    def news_search(
        self,
        query: str,
        num_results: int = 10,
        **kwargs: Any,
    ) -> SearchResponse:
        kwargs["time_filter"] = kwargs.get("time_filter", "d1")
        return self.search(query, num_results, **kwargs)