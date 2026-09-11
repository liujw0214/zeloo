"""Yandex Search provider — Russian search engine."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult


@dataclass
class YandexSearchProvider(SearchProvider):
    """Yandex XML Search API provider.

    Official Yandex search engine via XML API.
    Supports Russian and other languages.
    """

    name: str = "yandex_search"
    base_url: str = "https://yandex.com/search/xml"
    default_num_results: int = 10

    def search(
        self,
        query: str,
        num_results: int | None = None,
        **kwargs: Any,
    ) -> SearchResponse:
        api_key = os.environ.get("YANDEX_SEARCH_API_KEY", "")
        if not api_key:
            raise ValueError("YANDEX_SEARCH_API_KEY must be set")

        folder_id = os.environ.get("YANDEX_FOLDER_ID", "")
        if not folder_id:
            raise ValueError("YANDEX_FOLDER_ID must be set")

        params: dict[str, Any] = {
            "folderid": folder_id,
            "apikey": api_key,
            "query": query,
            "lr": kwargs.get("region", "213"),  # default Moscow
        }
        if kwargs.get("language"):
            params["hl"] = kwargs["language"]
        if num_results:
            params["numdoc"] = min(num_results, 100)

        endpoint = "https://searchapi.api.cloud.yandex.net/v2/web/search"
        with httpx.Client(timeout=15.0) as client:
            response = client.get(endpoint, params=params)
            response.raise_for_status()
            data = response.json()

        raw_results = data.get("rawData", {}).get("response", {})
        docs = raw_results.get("results", {}).get("grouping", [])
        flat = []
        for group in docs:
            for doc in group.get("doc", []):
                flat.append(doc)

        results = [
            SearchResult(
                title=d.get("title", ""),
                url=d.get("url", ""),
                snippet=d.get("passages", [{}])[0].get("text", "")
                if d.get("passages")
                else d.get("snippet", ""),
                source="yandex_search",
                metadata={
                    "domain": d.get("domain"),
                    "mime_type": d.get("mime-type"),
                    "modtime": d.get("modtime"),
                },
            )
            for d in flat
        ]

        return SearchResponse(
            query=query,
            results=results,
            total_results=int(raw_results.get("found", {}).get("strict", 0)),
            provider=self.name,
            raw=data,
        )

    def validate_credentials(self) -> bool:
        api_key = os.environ.get("YANDEX_SEARCH_API_KEY", "")
        folder_id = os.environ.get("YANDEX_FOLDER_ID", "")
        if not api_key or not folder_id:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    "https://searchapi.api.cloud.yandex.net/v2/web/search",
                    params={
                        "folderid": folder_id,
                        "apikey": api_key,
                        "query": "test",
                        "numdoc": 1,
                    },
                )
                return resp.status_code == 200
        except Exception:
            return False