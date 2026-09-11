"""Stack Overflow search provider — public API, no auth needed."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult

logger = logging.getLogger(__name__)


@dataclass
class StackOverflowProvider(SearchProvider):
    """Stack Overflow public API search provider.

    Free public API for searching programming Q&A.
    No authentication required for basic queries.
    """

    name: str = "stackoverflow"
    base_url: str = "https://api.stackexchange.com/2.3"
    default_num_results: int = 10

    def search(
        self,
        query: str,
        num_results: int | None = None,
        **kwargs: Any,
    ) -> SearchResponse:
        params: dict[str, Any] = {
            "intitle": query,
            "site": "stackoverflow",
            "order": "desc",
            "sort": kwargs.get("sort", "relevance"),
            "pagesize": min(num_results or self.default_num_results, 50),
            "filter": "withbody",
        }
        if kwargs.get("tagged"):
            params["tagged"] = kwargs["tagged"]
        if kwargs.get("accepted_only"):
            params["accepted"] = "True"
        if kwargs.get("min_score"):
            params["min"] = kwargs["min_score"]

        endpoint = f"{self.base_url}/search/advanced"
        with httpx.Client(timeout=15.0) as client:
            response = client.get(endpoint, params=params)
            response.raise_for_status()
            data = response.json()

        questions = data.get("items", [])
        results = [
            SearchResult(
                title=q.get("title", ""),
                url=q.get("link", ""),
                snippet=q.get("excerpt", ""),
                source="stackoverflow",
                metadata={
                    "question_id": q.get("question_id"),
                    "score": q.get("score"),
                    "is_answered": q.get("is_answered"),
                    "accepted_answer_id": q.get("accepted_answer_id"),
                    "view_count": q.get("view_count"),
                    "answer_count": q.get("answer_count"),
                    "tags": q.get("tags", []),
                    "is_closed": q.get("closed_date"),
                },
            )
            for q in questions
        ]

        return SearchResponse(
            query=query,
            results=results,
            total_results=len(results),
            provider=self.name,
            raw=data,
            metadata={
                "quota_remaining": data.get("quota_remaining"),
                "quota_max": data.get("quota_max"),
                "has_more": data.get("has_more"),
            },
        )

    def get_answers(
        self, question_id: int, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Get answers for a specific question."""
        params = {
            "site": "stackoverflow",
            "order": "desc",
            "sort": "votes",
            "pagesize": limit,
            "filter": "withbody",
        }
        endpoint = f"{self.base_url}/questions/{question_id}/answers"
        with httpx.Client(timeout=15.0) as client:
            response = client.get(endpoint, params=params)
            response.raise_for_status()
        return response.json().get("items", [])

    def validate_credentials(self) -> bool:
        return True