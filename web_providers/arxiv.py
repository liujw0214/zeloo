"""Arxiv provider — preprint scientific paper search."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult

logger = logging.getLogger(__name__)


@dataclass
class ArxivProvider(SearchProvider):
    """Arxiv API provider.

    Free scientific paper search across physics, math, CS, biology, etc.
    Uses the public Arxiv API without authentication.
    """

    name: str = "arxiv"
    base_url: str = "http://export.arxiv.org/api/query"
    default_num_results: int = 10

    def search(
        self,
        query: str,
        num_results: int | None = None,
        **kwargs: Any,
    ) -> SearchResponse:
        max_results = min(num_results or self.default_num_results, 50)
        params: dict[str, Any] = {
            "search_query": self._build_query(query, kwargs),
            "start": 0,
            "max_results": max_results,
            "sortBy": kwargs.get("sort_by", "relevance"),
            "sortOrder": kwargs.get("sort_order", "descending"),
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.get(self.base_url, params=params)
            response.raise_for_status()
            content = response.text

        entries = self._parse_atom(content)
        results = [
            SearchResult(
                title=e.get("title", ""),
                url=e.get("id", ""),
                snippet=e.get("summary", ""),
                source="arxiv",
                metadata={
                    "authors": e.get("authors", []),
                    "published": e.get("published"),
                    "updated": e.get("updated"),
                    "categories": e.get("categories", []),
                    "pdf_url": e.get("pdf_url"),
                    "primary_category": e.get("primary_category"),
                },
            )
            for e in entries
        ]

        return SearchResponse(
            query=query,
            results=results,
            total_results=len(results),
            provider=self.name,
            raw={"entries": entries},
        )

    def _build_query(self, query: str, kwargs: dict[str, Any]) -> str:
        parts = [f'all:{query}']
        if kwargs.get("author"):
            parts.append(f'au:{kwargs["author"]}')
        if kwargs.get("title"):
            parts.append(f'ti:{kwargs["title"]}')
        if kwargs.get("abstract"):
            parts.append(f'abs:{kwargs["abstract"]}')
        if kwargs.get("category"):
            cat = kwargs["category"]
            if isinstance(cat, list):
                cat = " OR ".join(f"cat:{c}" for c in cat)
            else:
                cat = f"cat:{cat}"
            parts.append(f"({cat})")
        return " AND ".join(parts)

    def _parse_atom(self, xml_text: str) -> list[dict[str, Any]]:
        import xml.etree.ElementTree as ET
        ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
        root = ET.fromstring(xml_text)
        entries: list[dict[str, Any]] = []
        for entry in root.findall("atom:entry", ns):
            data: dict[str, Any] = {
                "id": self._text(entry, "atom:id"),
                "title": self._text(entry, "atom:title"),
                "summary": self._text(entry, "atom:summary"),
                "published": self._text(entry, "atom:published"),
                "updated": self._text(entry, "atom:updated"),
            }
            authors = [
                self._text(a, "atom:name")
                for a in entry.findall("atom:author", ns)
            ]
            data["authors"] = authors
            cats = [
                c.get("term", "")
                for c in entry.findall("atom:category", ns)
            ]
            data["categories"] = cats
            primary = entry.find("arxiv:primary_category", ns)
            if primary is not None:
                data["primary_category"] = primary.get("term", "")
            for link in entry.findall("atom:link", ns):
                if link.get("title") == "pdf":
                    data["pdf_url"] = link.get("href", "")
            entries.append(data)
        return entries

    def _text(self, element: Any, path: str) -> str:
        found = element.find(path, {"atom": "http://www.w3.org/2005/Atom"})
        if found is not None and found.text:
            return found.text.strip().replace("\n", " ")
        return ""

    def validate_credentials(self) -> bool:
        return True


__all__ = ["ArxivProvider"]