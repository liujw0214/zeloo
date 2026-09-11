"""OpenStreetMap geocoding and place search provider."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult

logger = logging.getLogger(__name__)


@dataclass
class OpenStreetMapProvider(SearchProvider):
    """OpenStreetMap Nominatim geocoding/search provider.

    Free public API for geocoding and place search.
    Rate-limited to 1 request per second.
    """

    name: str = "openstreetmap"
    base_url: str = "https://nominatim.openstreetmap.org"
    default_num_results: int = 10

    def search(
        self,
        query: str,
        num_results: int | None = None,
        **kwargs: Any,
    ) -> SearchResponse:
        params: dict[str, Any] = {
            "q": query,
            "format": "json",
            "limit": min(num_results or self.default_num_results, 50),
            "addressdetails": 1,
        }
        if kwargs.get("country_codes"):
            params["countrycodes"] = kwargs["country_codes"]
        if kwargs.get("bbox"):
            params["viewbox"] = ",".join(map(str, kwargs["bbox"]))
            params["bounded"] = 1
        if kwargs.get("limit_to_country"):
            params["countrycodes"] = kwargs["limit_to_country"]

        endpoint = f"{self.base_url}/search"
        headers = {"User-Agent": "Zeloo/1.0"}
        with httpx.Client(timeout=15.0) as client:
            response = client.get(endpoint, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()

        results = []
        for item in data:
            results.append(
                SearchResult(
                    title=item.get("display_name", ""),
                    url=f"https://www.openstreetmap.org/{item.get('osm_type', 'way')}/{item.get('osm_id', '')}",  # noqa: E501
                    snippet=item.get("display_name", ""),
                    source="openstreetmap",
                    metadata={
                        "osm_id": item.get("osm_id"),
                        "osm_type": item.get("osm_type"),
                        "lat": float(item.get("lat", 0)),
                        "lon": float(item.get("lon", 0)),
                        "type": item.get("type"),
                        "category": item.get("category"),
                        "importance": item.get("importance"),
                        "address": item.get("address"),
                        "bounding_box": item.get("boundingbox"),
                    },
                )
            )

        return SearchResponse(
            query=query,
            results=results,
            total_results=len(results),
            provider=self.name,
            raw=data,
        )

    def reverse_geocode(
        self, lat: float, lon: float, zoom: int = 18
    ) -> dict[str, Any]:
        """Reverse geocode coordinates to an address."""
        params = {
            "lat": lat,
            "lon": lon,
            "format": "json",
            "zoom": zoom,
            "addressdetails": 1,
        }
        headers = {"User-Agent": "Zeloo/1.0"}
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(
                f"{self.base_url}/reverse",
                params=params,
                headers=headers,
            )
            resp.raise_for_status()
        return resp.json()

    def validate_credentials(self) -> bool:
        return True