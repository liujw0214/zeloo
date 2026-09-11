"""Keenable provider — knowledge graph powered search."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult


@dataclass
class KeenableProvider(SearchProvider):
    """Keenable knowledge graph search provider.

    Provides semantic search powered by knowledge graph entities
    and relationships.
    """

    name: str = "keenable"
    base_url: str = "https://api.keenable.io/v1"
    default_num_results: int = 10

    def search(
        self,
        query: str,
        num_results: int | None = None,
        **kwargs: Any,
    ) -> SearchResponse:
        api_key = os.environ.get("KEENABLE_API_KEY", "")
        if not api_key:
            raise ValueError("KEENABLE_API_KEY must be set")

        endpoint = f"{self.base_url}/search"
        payload: dict[str, Any] = {
            "query": query,
            "limit": min(num_results or self.default_num_results, 30),
        }
        if kwargs.get("entities"):
            payload["entity_types"] = kwargs["entities"]
        if kwargs.get("min_confidence"):
            payload["min_confidence"] = kwargs["min_confidence"]

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=20.0) as client:
            response = client.post(endpoint, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        results = []
        for r in data.get("results", []):
            results.append(
                SearchResult(
                    title=r.get("title", r.get("entity_name", "")),
                    url=r.get("url", ""),
                    snippet=r.get("description", r.get("snippet", "")),
                    source="keenable",
                    metadata={
                        "entity_id": r.get("entity_id"),
                        "entity_type": r.get("entity_type"),
                        "score": r.get("relevance_score"),
                        "related": r.get("related_entities", []),
                    },
                )
            )

        return SearchResponse(
            query=query,
            results=results,
            total_results=int(data.get("total", len(results))),
            provider=self.name,
            raw=data,
        )

    def entity_lookup(self, entity_id: str) -> str:
        """Get detailed knowledge graph entity."""
        api_key = os.environ.get("KEENABLE_API_KEY", "")
        if not api_key:
            return '{"error": "KEENABLE_API_KEY not set"}'

        endpoint = f"{self.base_url}/entities/{entity_id}"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=15.0) as client:
            resp = client.get(endpoint, headers=headers)
            resp.raise_for_status()
        return resp.text

    def validate_credentials(self) -> bool:
        api_key = os.environ.get("KEENABLE_API_KEY", "")
        if not api_key:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    f"{self.base_url}/search",
                    json={"query": "test", "limit": 1},
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                return resp.status_code == 200
        except Exception:
            return False