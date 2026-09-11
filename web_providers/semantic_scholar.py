"""Semantic Scholar provider — AI-powered academic search."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult

logger = logging.getLogger(__name__)


@dataclass
class SemanticScholarProvider(SearchProvider):
    """Semantic Scholar Graph API provider.

    Free academic paper search with citations, abstracts, and AI-powered relevance.
    """

    name: str = "semantic_scholar"
    base_url: str = "https://api.semanticscholar.org/graph/v1"
    default_num_results: int = 10

    def search(
        self,
        query: str,
        num_results: int | None = None,
        **kwargs: Any,
    ) -> SearchResponse:
        api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
        endpoint = f"{self.base_url}/paper/search"
        params: dict[str, Any] = {
            "query": query,
            "limit": min(num_results or self.default_num_results, 100),
            "fields": "title,abstract,url,year,authors,citationCount,venue,publicationDate",
        }
        if kwargs.get("year"):
            params["year"] = kwargs["year"]
        if kwargs.get("fields_of_study"):
            params["fieldsOfStudy"] = kwargs["fields_of_study"]
        if kwargs.get("open_access_only"):
            params["openAccessPdf.url"] = ""

        headers = {}
        if api_key:
            headers["x-api-key"] = api_key

        with httpx.Client(timeout=20.0) as client:
            response = client.get(endpoint, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()

        papers = data.get("data", [])
        results = [
            SearchResult(
                title=p.get("title", ""),
                url=p.get("url", ""),
                snippet=p.get("abstract", ""),
                source="semantic_scholar",
                metadata={
                    "paper_id": p.get("paperId"),
                    "year": p.get("year"),
                    "venue": p.get("venue"),
                    "citation_count": p.get("citationCount"),
                    "authors": [
                        a.get("name") for a in p.get("authors", [])
                    ],
                    "publication_date": p.get("publicationDate"),
                },
            )
            for p in papers
        ]

        return SearchResponse(
            query=query,
            results=results,
            total_results=int(data.get("total", len(results))),
            provider=self.name,
            raw=data,
        )

    def get_paper(self, paper_id: str) -> dict[str, Any]:
        """Get detailed paper information."""
        endpoint = f"{self.base_url}/paper/{paper_id}"
        params = {"fields": "title,abstract,url,year,authors,citationCount,references,citations"}
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(endpoint, params=params)
            resp.raise_for_status()
        return resp.json()

    def get_citations(self, paper_id: str) -> list[dict[str, Any]]:
        """Get papers that cite the given paper."""
        endpoint = f"{self.base_url}/paper/{paper_id}/citations"
        params = {"fields": "title,abstract,year,authors,citationCount"}
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(endpoint, params=params)
            resp.raise_for_status()
        return resp.json().get("data", [])

    def validate_credentials(self) -> bool:
        return True