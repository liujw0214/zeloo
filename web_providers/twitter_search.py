"""Twitter / X search provider."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult

logger = logging.getLogger(__name__)


@dataclass
class TwitterSearchProvider(SearchProvider):
    """Twitter/X v2 API search provider.

    Requires Bearer Token (X_BEARER_TOKEN).
    """

    name: str = "twitter"
    base_url: str = "https://api.twitter.com/2"
    default_num_results: int = 10

    def search(
        self,
        query: str,
        num_results: int | None = None,
        **kwargs: Any,
    ) -> SearchResponse:
        bearer = os.environ.get("X_BEARER_TOKEN", "") or os.environ.get(
            "TWITTER_BEARER_TOKEN", ""
        )
        if not bearer:
            logger.warning("Twitter/X requires X_BEARER_TOKEN")
            return SearchResponse(
                query=query, results=[], total_results=0, provider=self.name,
            )

        params: dict[str, Any] = {
            "query": query,
            "max_results": min(max(num_results or self.default_num_results, 10), 100),
            "tweet.fields": "created_at,author_id,public_metrics,lang",
        }
        if kwargs.get("since_id"):
            params["since_id"] = kwargs["since_id"]
        if kwargs.get("until_id"):
            params["until_id"] = kwargs["until_id"]
        if kwargs.get("lang"):
            params["lang"] = kwargs["lang"]

        headers = {"Authorization": f"Bearer {bearer}"}
        endpoint = f"{self.base_url}/tweets/search/recent"

        with httpx.Client(timeout=15.0) as client:
            response = client.get(endpoint, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()

        tweets = data.get("data", [])
        results = [
            SearchResult(
                title=f"Tweet by {t.get('author_id', 'unknown')}",
                url=f"https://twitter.com/i/web/status/{t.get('id', '')}",
                snippet=t.get("text", ""),
                source="twitter",
                metadata={
                    "tweet_id": t.get("id"),
                    "author_id": t.get("author_id"),
                    "created_at": t.get("created_at"),
                    "lang": t.get("lang"),
                    "retweets": t.get("public_metrics", {}).get("retweet_count"),
                    "likes": t.get("public_metrics", {}).get("like_count"),
                },
            )
            for t in tweets
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
            os.environ.get("X_BEARER_TOKEN")
            or os.environ.get("TWITTER_BEARER_TOKEN")
        )