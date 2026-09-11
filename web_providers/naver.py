"""Naver Search provider — Korean search engine."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult

logger = logging.getLogger(__name__)


@dataclass
class NaverProvider(SearchProvider):
    """Naver Search API provider.

    Korean search engine with blog, news, image, and shopping search.
    Requires Naver Cloud Platform credentials.
    """

    name: str = "naver"
    base_url: str = "https://openapi.naver.com/v1/search/blog"
    default_num_results: int = 10

    def search(
        self,
        query: str,
        num_results: int | None = None,
        **kwargs: Any,
    ) -> SearchResponse:
        client_id = os.environ.get("NAVER_CLIENT_ID", "")
        client_secret = os.environ.get("NAVER_CLIENT_SECRET", "")

        if not client_id or not client_secret:
            logger.warning(
                "Naver requires NAVER_CLIENT_ID and NAVER_CLIENT_SECRET"
            )
            return SearchResponse(
                query=query, results=[], total_results=0, provider=self.name,
            )

        target = kwargs.get("target", "blog")
        endpoint = f"https://openapi.naver.com/v1/search/{target}"

        params: dict[str, Any] = {
            "query": query,
            "display": min(num_results or self.default_num_results, 100),
        }
        if kwargs.get("start"):
            params["start"] = kwargs["start"]
        if kwargs.get("sort"):
            params["sort"] = kwargs["sort"]

        headers = {
            "X-Naver-Client-Id": client_id,
            "X-Naver-Client-Secret": client_secret,
        }

        with httpx.Client(timeout=15.0) as client:
            response = client.get(endpoint, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()

        items = data.get("items", [])
        results = [
            SearchResult(
                title=i.get("title", "").replace("<b>", "").replace("</b>", ""),
                url=i.get("link", ""),
                snippet=i.get("description", "").replace("<b>", "").replace("</b>", ""),
                source="naver",
                metadata={
                    "blogger": i.get("bloggername", ""),
                    "post_date": i.get("postdate", ""),
                },
            )
            for i in items
        ]

        return SearchResponse(
            query=query,
            results=results,
            total_results=int(data.get("total", len(results))),
            provider=self.name,
            raw=data,
        )

    def news_search(
        self,
        query: str,
        num_results: int = 10,
        **kwargs: Any,
    ) -> SearchResponse:
        kwargs["target"] = "news"
        return self.search(query, num_results, **kwargs)

    def image_search(
        self,
        query: str,
        num_results: int = 10,
        **kwargs: Any,
    ) -> SearchResponse:
        kwargs["target"] = "image"
        return self.search(query, num_results, **kwargs)

    def shopping_search(
        self,
        query: str,
        num_results: int = 10,
        **kwargs: Any,
    ) -> SearchResponse:
        kwargs["target"] = "shop"
        return self.search(query, num_results, **kwargs)

    def validate_credentials(self) -> bool:
        return bool(
            os.environ.get("NAVER_CLIENT_ID")
            and os.environ.get("NAVER_CLIENT_SECRET")
        )