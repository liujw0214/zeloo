"""xAI Grok search provider."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from web_providers.base import SearchProvider, SearchResponse, SearchResult


@dataclass
class GrokSearchProvider(SearchProvider):
    """xAI Grok web search provider.

    Uses xAI's Grok model with live web search capability
    for AI-powered real-time search results with citations.
    """

    name: str = "grok_search"
    base_url: str = "https://api.x.ai/v1"
    default_num_results: int = 10

    def search(
        self,
        query: str,
        num_results: int | None = None,
        **kwargs: Any,
    ) -> SearchResponse:
        api_key = os.environ.get("XAI_API_KEY", "")
        if not api_key:
            raise ValueError("XAI_API_KEY must be set")

        endpoint = f"{self.base_url}/chat/completions"
        model = kwargs.get("model", "grok-3")
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": f"You are a search assistant. Return results as JSON array with keys: title, url, snippet. Provide up to {num_results or self.default_num_results} results.",  # noqa: E501
                },
                {"role": "user", "content": query},
            ],
            "search_enabled": True,
            "stream": False,
        }
        if kwargs.get("temperature"):
            payload["temperature"] = kwargs["temperature"]
        if kwargs.get("max_tokens"):
            payload["max_tokens"] = kwargs["max_tokens"]
        if kwargs.get("country"):
            payload["country"] = kwargs["country"]
        if kwargs.get("time_filter"):
            payload["search_recency_filter"] = kwargs["time_filter"]

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.post(endpoint, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"]["content"]

        results = []
        try:
            import json as _json
            if content.strip().startswith("["):
                parsed = _json.loads(content)
                for item in parsed:
                    if isinstance(item, dict):
                        results.append(
                            SearchResult(
                                title=item.get("title", ""),
                                url=item.get("url", ""),
                                snippet=item.get("snippet", ""),
                                source="grok_search",
                                metadata={"model": model},
                            )
                        )
            else:
                results.append(
                    SearchResult(
                        title="Grok Response",
                        url="",
                        snippet=content,
                        source="grok_search",
                        metadata={"model": model, "raw": True},
                    )
                )
        except Exception:
            results.append(
                SearchResult(
                    title="Grok Response",
                    url="",
                    snippet=content,
                    source="grok_search",
                    metadata={"model": model, "raw": True},
                )
            )

        citations = data["choices"][0]["message"].get("citations", [])

        return SearchResponse(
            query=query,
            results=results,
            total_results=len(results),
            provider=self.name,
            raw=data,
            metadata={"citations": citations, "raw_content": content},
        )

    def validate_credentials(self) -> bool:
        api_key = os.environ.get("XAI_API_KEY", "")
        if not api_key:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    f"{self.base_url}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                return resp.status_code == 200
        except Exception:
            return False