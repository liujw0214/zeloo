"""Serper.dev provider — Google SERP API alternative."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult


@dataclass
class SerperProvider(SearchProvider):
    """Serper.dev provider for Google SERP API.

    Provides fast, cheap access to Google Search results,
    news, images, places, and shopping.
    """

    name: str = "serper"
    base_url: str = "https://google.serper.dev"
    default_num_results: int = 10

    def search(
        self,
        query: str,
        num_results: int | None = None,
        **kwargs: Any,
    ) -> SearchResponse:
        api_key = os.environ.get("SERPER_API_KEY", "")
        if not api_key:
            raise ValueError("SERPER_API_KEY must be set")

        endpoint = f"{self.base_url}/search"
        payload: dict[str, Any] = {"q": query, "num": min(num_results or self.default_num_results, 100)}  # noqa: E501
        if kwargs.get("country"):
            payload["gl"] = kwargs["country"]
        if kwargs.get("language"):
            payload["hl"] = kwargs["language"]
        if kwargs.get("time_filter"):
            payload["tbs"] = kwargs["time_filter"]
        if kwargs.get("page"):
            payload["page"] = kwargs["page"]

        headers = {
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=15.0) as client:
            response = client.post(endpoint, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        organic = data.get("organic", [])
        results = [
            SearchResult(
                title=i.get("title", ""),
                url=i.get("link", ""),
                snippet=i.get("snippet", ""),
                source="serper",
                metadata={
                    "position": i.get("position"),
                    "displayed_link": i.get("displayedLink"),
                    "date": i.get("date"),
                    "sitelinks": i.get("sitelinks", []),
                },
            )
            for i in organic
        ]

        return SearchResponse(
            query=query,
            results=results,
            total_results=int(data.get("searchInformation", {}).get("totalResults", 0)),
            provider=self.name,
            raw=data,
        )

    def news_search(
        self,
        query: str,
        num_results: int = 10,
        **kwargs: Any,
    ) -> SearchResponse:
        api_key = os.environ.get("SERPER_API_KEY", "")
        if not api_key:
            raise ValueError("SERPER_API_KEY must be set")

        endpoint = f"{self.base_url}/news"
        payload: dict[str, Any] = {"q": query, "num": min(num_results, 100)}
        if kwargs.get("country"):
            payload["gl"] = kwargs["country"]
        if kwargs.get("language"):
            payload["hl"] = kwargs["language"]

        headers = {
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=15.0) as client:
            response = client.post(endpoint, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        news = data.get("news", [])
        results = [
            SearchResult(
                title=n.get("title", ""),
                url=n.get("link", ""),
                snippet=n.get("snippet", ""),
                source="serper",
                metadata={
                    "date": n.get("date"),
                    "source": n.get("source"),
                    "image_url": n.get("imageUrl"),
                },
            )
            for n in news
        ]

        return SearchResponse(
            query=query,
            results=results,
            total_results=len(results),
            provider=self.name,
            raw=data,
        )

    def validate_credentials(self) -> bool:
        api_key = os.environ.get("SERPER_API_KEY", "")
        if not api_key:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    f"{self.base_url}/search",
                    json={"q": "test", "num": 1},
                    headers={"X-API-KEY": api_key},
                )
                return resp.status_code == 200
        except Exception:
            return False