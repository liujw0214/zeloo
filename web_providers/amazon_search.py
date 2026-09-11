"""Amazon product search provider."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult

logger = logging.getLogger(__name__)


@dataclass
class AmazonSearchProvider(SearchProvider):
    """Amazon Product Advertising API or Rainforest API provider.

    Uses Rainforest API (easier to set up) when RAINFOREST_API_KEY is set.
    Falls back to PA-API documentation otherwise.
    """

    name: str = "amazon"
    base_url: str = "https://api.rainforestapi.com/request"
    default_num_results: int = 10

    def search(
        self,
        query: str,
        num_results: int | None = None,
        **kwargs: Any,
    ) -> SearchResponse:
        api_key = os.environ.get("RAINFOREST_API_KEY", "")
        if not api_key:
            logger.warning(
                "Amazon requires RAINFOREST_API_KEY (Rainforest API)"
            )
            return SearchResponse(
                query=query, results=[], total_results=0, provider=self.name,
            )

        params: dict[str, Any] = {
            "api_key": api_key,
            "type": "search",
            "amazon_domain": kwargs.get("amazon_domain", "amazon.com"),
            "search_term": query,
            "max_results": min(num_results or self.default_num_results, 50),
        }
        if kwargs.get("category_id"):
            params["category_id"] = kwargs["category_id"]
        if kwargs.get("min_price"):
            params["min_price"] = kwargs["min_price"]
        if kwargs.get("max_price"):
            params["max_price"] = kwargs["max_price"]

        with httpx.Client(timeout=20.0) as client:
            response = client.get(self.base_url, params=params)
            response.raise_for_status()
            data = response.json()

        results = []
        for product in data.get("search_results", []):
            price = product.get("price", {})
            results.append(
                SearchResult(
                    title=product.get("title", ""),
                    url=product.get("link", ""),
                    snippet=product.get("description", ""),
                    source="amazon",
                    metadata={
                        "asin": product.get("asin"),
                        "price": price.get("value") if price else None,
                        "currency": price.get("currency") if price else None,
                        "rating": product.get("rating"),
                        "reviews_count": product.get("ratings_total"),
                        "prime_eligible": product.get("is_prime_eligible"),
                        "image_url": product.get("image"),
                    },
                )
            )

        return SearchResponse(
            query=query,
            results=results,
            total_results=int(data.get("total_results", len(results))),
            provider=self.name,
            raw=data,
        )

    def get_product(self, asin: str) -> dict[str, Any]:
        """Get product details by ASIN."""
        api_key = os.environ.get("RAINFOREST_API_KEY", "")
        if not api_key:
            return {"error": "RAINFOREST_API_KEY not set"}

        params = {
            "api_key": api_key,
            "type": "product",
            "asin": asin,
        }
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(self.base_url, params=params)
            resp.raise_for_status()
        return resp.json()

    def validate_credentials(self) -> bool:
        return bool(os.environ.get("RAINFOREST_API_KEY", ""))