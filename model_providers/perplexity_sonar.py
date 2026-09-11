"""Perplexity Sonar provider — real-time web search + reasoning models."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from model_providers.base import ChatResponse, ProviderProfile


@dataclass
class PerplexitySonarProvider(ProviderProfile):
    """Perplexity Sonar API provider.

    Provides real-time web search via Sonar models with citations.
    Supports both search and chat completion modes.
    """

    name: str = "perplexity"
    base_url: str = "https://api.perplexity.ai"
    default_model: str = "sonar"
    supports_vision: bool = False
    supports_function_calling: bool = True
    supports_streaming: bool = True

    MODELS = {
        "sonar": "sonar",
        "sonar-pro": "sonar-pro",
        "sonar-reasoning": "sonar-reasoning",
        "sonar-reasoning-pro": "sonar-reasoning-pro",
    }

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        api_key = os.environ.get("PERPLEXITY_API_KEY", "")
        if not api_key:
            raise ValueError("PERPLEXITY_API_KEY environment variable not set")

        endpoint = f"{self.base_url}/chat/completions"
        model = model or self.default_model

        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "return_citations": True,
            "search_recency_filter": "month",
        }
        if kwargs.get("temperature"):
            body["temperature"] = kwargs["temperature"]
        if kwargs.get("max_tokens"):
            body["max_tokens"] = kwargs["max_tokens"]
        if kwargs.get("stream"):
            body["stream"] = True

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=120.0) as client:
            response = client.post(endpoint, json=body, headers=headers)
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"]["content"]
        citations = data.get("citations", [])

        return ChatResponse(
            content=content,
            model=data.get("model", model),
            provider=self.name,
            usage={
                "prompt_tokens": data.get("usage", {}).get("prompt_tokens", 0),
                "completion_tokens": data.get("usage", {}).get("completion_tokens", 0),
                "total_tokens": data.get("usage", {}).get("total_tokens", 0),
            },
            raw={"data": data, "citations": citations},
        )

    def validate_credentials(self) -> bool:
        api_key = os.environ.get("PERPLEXITY_API_KEY", "")
        if not api_key:
            return False
        headers = {"Authorization": f"Bearer {api_key}"}
        test_body = {
            "model": self.default_model,
            "messages": [{"role": "user", "content": "test"}],
        }
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    f"{self.base_url}/chat/completions",
                    json=test_body,
                    headers=headers,
                )
                return resp.status_code in (200, 400)
        except Exception:
            return False

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (prompt_tokens * 0.000015 + completion_tokens * 0.000015) / 1000.0
