"""PubMed provider — biomedical literature search."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult

logger = logging.getLogger(__name__)


@dataclass
class PubMedProvider(SearchProvider):
    """PubMed E-utilities API provider.

    Free biomedical literature search via NCBI E-utilities.
    """

    name: str = "pubmed"
    base_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    default_num_results: int = 10

    def search(
        self,
        query: str,
        num_results: int | None = None,
        **kwargs: Any,
    ) -> SearchResponse:
        api_key = os.environ.get("NCBI_API_KEY", "")
        tool = "pubmed"
        email = os.environ.get("NCBI_EMAIL", "[email protected]")

        params: dict[str, Any] = {
            "db": tool,
            "term": query,
            "retmax": min(num_results or self.default_num_results, 100),
            "retmode": "json",
            "tool": "Zeloo",
            "email": email,
        }
        if api_key:
            params["api_key"] = api_key
        if kwargs.get("date_from"):
            params["mindate"] = kwargs["date_from"]
        if kwargs.get("date_to"):
            params["maxdate"] = kwargs["date_to"]
        if kwargs.get("article_type"):
            params["type"] = kwargs["article_type"]

        search_url = f"{self.base_url}/esearch.fcgi"
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(search_url, params=params)
            resp.raise_for_status()
            search_data = resp.json()

        pmids = search_data.get("esearchresult", {}).get("idlist", [])
        total = int(search_data.get("esearchresult", {}).get("count", 0))

        if not pmids:
            return SearchResponse(
                query=query, results=[], total_results=total, provider=self.name,
            )

        fetch_params: dict[str, Any] = {
            "db": tool,
            "id": ",".join(pmids),
            "retmode": "json",
            "tool": "Zeloo",
            "email": email,
        }
        if api_key:
            fetch_params["api_key"] = api_key

        fetch_url = f"{self.base_url}/esummary.fcgi"
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(fetch_url, params=fetch_params)
            resp.raise_for_status()
            summary_data = resp.json()

        results = []
        result_data = summary_data.get("result", {})
        for pmid in pmids:
            p = result_data.get(pmid, {})
            authors = [
                a.get("name", "")
                for a in p.get("authors", [])
            ]
            results.append(
                SearchResult(
                    title=p.get("title", ""),
                    url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    snippet="; ".join(authors[:3])
                    + (" et al." if len(authors) > 3 else ""),
                    source="pubmed",
                    metadata={
                        "pmid": pmid,
                        "journal": p.get("source", ""),
                        "pubdate": p.get("pubdate", ""),
                        "volume": p.get("volume", ""),
                        "issue": p.get("issue", ""),
                        "pages": p.get("pages", ""),
                        "authors": authors,
                        "doi": next(
                            (
                                a.get("value")
                                for a in p.get("articleids", [])
                                if a.get("idtype") == "doi"
                            ),
                            None,
                        ),
                    },
                )
            )

        return SearchResponse(
            query=query,
            results=results,
            total_results=total,
            provider=self.name,
            raw={"search": search_data, "summary": summary_data},
        )

    def validate_credentials(self) -> bool:
        return True