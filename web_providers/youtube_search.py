"""YouTube Data API search provider."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult

logger = logging.getLogger(__name__)


@dataclass
class YouTubeSearchProvider(SearchProvider):
    """YouTube Data API v3 search provider.

    Searches videos, channels, and playlists via official Google API.
    """

    name: str = "youtube"
    base_url: str = "https://www.googleapis.com/youtube/v3"
    default_num_results: int = 10

    def search(
        self,
        query: str,
        num_results: int | None = None,
        **kwargs: Any,
    ) -> SearchResponse:
        api_key = os.environ.get("YOUTUBE_API_KEY", "")
        if not api_key:
            logger.warning("YouTube requires YOUTUBE_API_KEY")
            return SearchResponse(
                query=query, results=[], total_results=0, provider=self.name,
            )

        params: dict[str, Any] = {
            "key": api_key,
            "part": "snippet",
            "q": query,
            "type": kwargs.get("type", "video"),
            "maxResults": min(num_results or self.default_num_results, 50),
        }
        if kwargs.get("channel_id"):
            params["channelId"] = kwargs["channel_id"]
        if kwargs.get("order"):
            params["order"] = kwargs["order"]
        if kwargs.get("published_after"):
            params["publishedAfter"] = kwargs["published_after"]
        if kwargs.get("region_code"):
            params["regionCode"] = kwargs["region_code"]

        endpoint = f"{self.base_url}/search"
        with httpx.Client(timeout=15.0) as client:
            response = client.get(endpoint, params=params)
            response.raise_for_status()
            data = response.json()

        items = data.get("items", [])
        results = [
            SearchResult(
                title=item.get("snippet", {}).get("title", ""),
                url=(
                    f"https://www.youtube.com/watch?v={item['id'].get('videoId', '')}"
                    if item.get("id", {}).get("videoId")
                    else f"https://www.youtube.com/channel/{item['id'].get('channelId', '')}"
                ),
                snippet=item.get("snippet", {}).get("description", ""),
                source="youtube",
                metadata={
                    "channel_title": item.get("snippet", {}).get("channelTitle"),
                    "published_at": item.get("snippet", {}).get("publishedAt"),
                    "thumbnail_url": item.get("snippet", {}).get("thumbnails", {}).get("high", {}).get("url"),  # noqa: E501
                    "video_id": item.get("id", {}).get("videoId"),
                    "channel_id": item.get("id", {}).get("channelId"),
                },
            )
            for item in items
        ]

        return SearchResponse(
            query=query,
            results=results,
            total_results=int(data.get("pageInfo", {}).get("totalResults", 0)),
            provider=self.name,
            raw=data,
        )

    def get_video_stats(self, video_id: str) -> dict[str, Any]:
        """Get statistics for a specific video."""
        api_key = os.environ.get("YOUTUBE_API_KEY", "")
        if not api_key:
            return {"error": "YOUTUBE_API_KEY not set"}

        endpoint = f"{self.base_url}/videos"
        params = {
            "key": api_key,
            "part": "statistics,snippet,contentDetails",
            "id": video_id,
        }
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(endpoint, params=params)
            resp.raise_for_status()
        return resp.json()

    def validate_credentials(self) -> bool:
        return bool(os.environ.get("YOUTUBE_API_KEY", ""))