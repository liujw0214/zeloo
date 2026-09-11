"""Indeed job search provider via SerpAPI."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult

logger = logging.getLogger(__name__)


@dataclass
class IndeedProvider(SearchProvider):
    """Indeed job search via SerpAPI's Indeed engine."""

    name: str = "indeed"
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
            logger.warning("Indeed via SerpAPI requires SERPAPI_API_KEY")
            return SearchResponse(
                query=query, results=[], total_results=0, provider=self.name,
            )

        params: dict[str, Any] = {
            "api_key": api_key,
            "engine": "indeed",
            "q": query,
            "num": min(num_results or self.default_num_results, 100),
        }
        if kwargs.get("location"):
            params["location"] = kwargs["location"]
        if kwargs.get("country"):
            params["country"] = kwargs["country"]
        if kwargs.get("date_posted"):
            params["date_posted"] = kwargs["date_posted"]
        if kwargs.get("remote_only"):
            params["remote"] = "true"
        if kwargs.get("experience_level"):
            params["experience_level"] = kwargs["experience_level"]
        if kwargs.get("salary_min"):
            params["salary_min"] = kwargs["salary_min"]

        with httpx.Client(timeout=30.0) as client:
            response = client.get(self.base_url, params=params)
            response.raise_for_status()
            data = response.json()

        jobs = data.get("organic_results", [])
        results = [
            SearchResult(
                title=job.get("title", ""),
                url=job.get("link", ""),
                snippet=job.get("snippet", ""),
                source="indeed",
                metadata={
                    "company": job.get("company_name", ""),
                    "location": job.get("location", ""),
                    "salary": job.get("salary"),
                    "posted_date": job.get("date_posted"),
                    "job_type": job.get("job_type"),
                    "remote": job.get("remote"),
                    "rating": job.get("rating"),
                },
            )
            for job in jobs
        ]

        return SearchResponse(
            query=query,
            results=results,
            total_results=int(data.get("search_information", {}).get("total_results", 0)),
            provider=self.name,
            raw=data,
        )

    def validate_credentials(self) -> bool:
        return bool(os.environ.get("SERPAPI_API_KEY", ""))