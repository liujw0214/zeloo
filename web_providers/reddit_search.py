"""Reddit search provider."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult

logger = logging.getLogger(__name__)


@dataclass
class RedditSearchProvider(SearchProvider):
    """Reddit API search provider.

    Searches posts and comments via official Reddit API.
    Requires REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET (or bearer token).
    """

    name: str = "reddit"
    base_url: str = "https://oauth.reddit.com"
    default_num_results: int = 10

    def _get_headers(self) -> dict[str, str]:
        bearer = os.environ.get("REDDIT_BEARER_TOKEN", "")
        if bearer:
            return {"Authorization": f"Bearer {bearer}", "User-Agent": "Zeloo/1.0"}
        client_id = os.environ.get("REDDIT_CLIENT_ID", "")
        client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "")
        if client_id and client_secret:
            try:
                with httpx.Client(timeout=10.0) as client:
                    auth_resp = client.post(
                        "https://www.reddit.com/api/v1/access_token",
                        auth=(client_id, client_secret),
                        data={"grant_type": "client_credentials"},
                        headers={"User-Agent": "Zeloo/1.0"},
                    )
                    auth_resp.raise_for_status()
                    token = auth_resp.json().get("access_token", "")
                    return {
                        "Authorization": f"Bearer {token}",
                        "User-Agent": "Zeloo/1.0",
                    }
            except Exception as e:
                logger.warning("Reddit auth failed: %s", e)
        return {}

    def search(
        self,
        query: str,
        num_results: int | None = None,
        **kwargs: Any,
    ) -> SearchResponse:
        headers = self._get_headers()
        if not headers:
            logger.warning(
                "Reddit requires REDDIT_BEARER_TOKEN or "
                "REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET"
            )
            return SearchResponse(
                query=query, results=[], total_results=0, provider=self.name,
            )

        params: dict[str, Any] = {
            "q": query,
            "limit": min(num_results or self.default_num_results, 100),
            "sort": kwargs.get("sort", "relevance"),
        }
        if kwargs.get("subreddit"):
            params["restrict_sr"] = kwargs["subreddit"]
        if kwargs.get("time_filter"):
            params["t"] = kwargs["time_filter"]

        endpoint = f"{self.base_url}/search"
        with httpx.Client(timeout=15.0) as client:
            response = client.get(endpoint, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()

        posts = data.get("data", {}).get("children", [])
        results = [
            SearchResult(
                title=p.get("data", {}).get("title", ""),
                url=f"https://reddit.com{p.get('data', {}).get('permalink', '')}",
                snippet=p.get("data", {}).get("selftext", ""),
                source="reddit",
                metadata={
                    "subreddit": p.get("data", {}).get("subreddit"),
                    "score": p.get("data", {}).get("score"),
                    "num_comments": p.get("data", {}).get("num_comments"),
                    "author": p.get("data", {}).get("author"),
                    "created_utc": p.get("data", {}).get("created_utc"),
                    "url": p.get("data", {}).get("url"),
                    "thumbnail": p.get("data", {}).get("thumbnail"),
                },
            )
            for p in posts
        ]

        return SearchResponse(
            query=query,
            results=results,
            total_results=len(results),
            provider=self.name,
            raw=data,
        )

    def validate_credentials(self) -> bool:
        return bool(
            os.environ.get("REDDIT_BEARER_TOKEN")
            or (
                os.environ.get("REDDIT_CLIENT_ID")
                and os.environ.get("REDDIT_CLIENT_SECRET")
            )
        )