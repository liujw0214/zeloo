"""GitHub search provider — repositories, code, issues, users."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult

logger = logging.getLogger(__name__)


@dataclass
class GitHubSearchProvider(SearchProvider):
    """GitHub REST API search provider.

    Searches repositories, code, issues, users, and topics.
    Public API works without auth (lower rate limit).
    """

    name: str = "github_search"
    base_url: str = "https://api.github.com"
    default_num_results: int = 10

    def _headers(self) -> dict[str, str]:
        token = os.environ.get("GITHUB_TOKEN", "")
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def search(
        self,
        query: str,
        num_results: int | None = None,
        **kwargs: Any,
    ) -> SearchResponse:
        params: dict[str, Any] = {
            "q": query,
            "per_page": min(num_results or self.default_num_results, 100),
            "sort": kwargs.get("sort", "best-match"),
            "order": kwargs.get("order", "desc"),
        }

        search_type = kwargs.get("type", "repositories")
        endpoint_map = {
            "repositories": "/search/repositories",
            "code": "/search/code",
            "issues": "/search/issues",
            "users": "/search/users",
            "topics": "/search/topics",
            "commits": "/search/commits",
            "labels": "/search/labels",
        }
        endpoint = f"{self.base_url}{endpoint_map.get(search_type, '/search/repositories')}"

        with httpx.Client(timeout=15.0) as client:
            response = client.get(endpoint, params=params, headers=self._headers())
            response.raise_for_status()
            data = response.json()

        items = data.get("items", [])
        results = []
        for item in items:
            if search_type == "repositories":
                results.append(
                    SearchResult(
                        title=item.get("full_name", ""),
                        url=item.get("html_url", ""),
                        snippet=item.get("description", ""),
                        source="github_search",
                        metadata={
                            "stars": item.get("stargazers_count"),
                            "forks": item.get("forks_count"),
                            "language": item.get("language"),
                            "owner": item.get("owner", {}).get("login"),
                            "updated_at": item.get("updated_at"),
                            "topics": item.get("topics", []),
                        },
                    )
                )
            elif search_type == "users":
                results.append(
                    SearchResult(
                        title=item.get("login", ""),
                        url=item.get("html_url", ""),
                        snippet=item.get("bio", "") or "",
                        source="github_search",
                        metadata={
                            "name": item.get("name"),
                            "avatar_url": item.get("avatar_url"),
                            "followers": item.get("followers"),
                        },
                    )
                )
            elif search_type in ("issues", "code"):
                results.append(
                    SearchResult(
                        title=item.get("title", item.get("name", "")),
                        url=item.get("html_url", ""),
                        snippet=item.get("body", ""),
                        source="github_search",
                        metadata={
                            "state": item.get("state"),
                            "repository": item.get("repository", {}).get("full_name"),
                            "user": item.get("user", {}).get("login"),
                            "created_at": item.get("created_at"),
                        },
                    )
                )
            else:
                results.append(
                    SearchResult(
                        title=item.get("name", item.get("title", "")),
                        url=item.get("html_url", item.get("url", "")),
                        snippet=item.get("description", ""),
                        source="github_search",
                    )
                )

        return SearchResponse(
            query=query,
            results=results,
            total_results=int(data.get("total_count", len(results))),
            provider=self.name,
            raw=data,
        )

    def validate_credentials(self) -> bool:
        return True