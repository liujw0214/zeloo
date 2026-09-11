"""Skyscanner flight search provider via SerpAPI."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult

logger = logging.getLogger(__name__)


@dataclass
class SkyscannerProvider(SearchProvider):
    """Skyscanner flight search via SerpAPI's Google Flights engine."""

    name: str = "skyscanner"
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
            logger.warning("Skyscanner via SerpAPI requires SERPAPI_API_KEY")
            return SearchResponse(
                query=query, results=[], total_results=0, provider=self.name,
            )

        params: dict[str, Any] = {
            "api_key": api_key,
            "engine": "google_flights",
            "q": query,
            "num": min(num_results or self.default_num_results, 100),
        }
        if kwargs.get("departure_id"):
            params["departure_id"] = kwargs["departure_id"]
        if kwargs.get("arrival_id"):
            params["arrival_id"] = kwargs["arrival_id"]
        if kwargs.get("outbound_date"):
            params["outbound_date"] = kwargs["outbound_date"]
        if kwargs.get("return_date"):
            params["return_date"] = kwargs["return_date"]
        if kwargs.get("currency"):
            params["currency"] = kwargs["currency"]
        if kwargs.get("adults"):
            params["adults"] = kwargs["adults"]
        if kwargs.get("flight_type"):
            params["type"] = kwargs["flight_type"]

        with httpx.Client(timeout=30.0) as client:
            response = client.get(self.base_url, params=params)
            response.raise_for_status()
            data = response.json()

        flights = data.get("best_flights", []) + data.get("other_flights", [])
        results = [
            SearchResult(
                title=f"{f.get('flights', [{}])[0].get('departure_airport', {}).get('name', '')} → "
                      f"{f.get('flights', [{}])[0].get('arrival_airport', {}).get('name', '')}",
                url="https://www.skyscanner.com/",
                snippet=f"{f.get('total_duration', 0)} min • ${f.get('price', 0)}",
                source="skyscanner",
                metadata={
                    "price_usd": f.get("price"),
                    "duration_minutes": f.get("total_duration"),
                    "stops": len(f.get("flights", [])) - 1,
                    "airlines": [
                        fl.get("airline")
                        for fl in f.get("flights", [])
                    ],
                    "departure_time": f.get("flights", [{}])[0].get("departure_airport", {}).get("time"),  # noqa: E501
                    "arrival_time": f.get("flights", [{}])[-1].get("arrival_airport", {}).get("time"),  # noqa: E501
                },
            )
            for f in flights
        ]

        return SearchResponse(
            query=query,
            results=results,
            total_results=len(results),
            provider=self.name,
            raw=data,
        )

    def validate_credentials(self) -> bool:
        return bool(os.environ.get("SERPAPI_API_KEY", ""))