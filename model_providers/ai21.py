"""AI21 Jurassic provider — frontier reasoning and completion models."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from model_providers.base import ChatResponse, ProviderProfile


@dataclass
class AI21Provider(ProviderProfile):
    """AI21 Jurassic API provider.

    Provides access to Jamba and Jurassic series models with
    ultra-long context and high reasoning quality.
    """

    name: str = "ai21"
    base_url: str = "https://api.ai21.com/studio/v1"
    default_model: str = "jamba-1.5-large"
    supports_vision: bool = False
    supports_function_calling: bool = True
    supports_streaming: bool = True

    MODELS = {
        "jamba-1.5-large": "jamba-1.5-large",
        "jamba-1.5-mini": "jamba-1.5-mini",
        "jamba-1-ultra": "jamba-1-ultra",
        "j2-ultra": "j2-ultra",
        "j2-mid": "j2-mid",
    }

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        api_key = os.environ.get("AI21_API_KEY", "")
        if not api_key:
            raise ValueError("AI21_API_KEY environment variable not set")

        endpoint = f"{self.base_url}/chat"
        model = model or self.default_model

        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if kwargs.get("temperature"):
            body["temperature"] = kwargs["temperature"]
        if kwargs.get("max_tokens"):
            body["maxTokens"] = kwargs["max_tokens"]
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

        return ChatResponse(
            content=content,
            model=data.get("model", model),
            provider=self.name,
            usage={
                "prompt_tokens": data.get("usage", {}).get("prompt_tokens", 0),
                "completion_tokens": data.get("usage", {}).get("completion_tokens", 0),
                "total_tokens": data.get("usage", {}).get("total_tokens", 0),
            },
            raw=data,
        )

    def validate_credentials(self) -> bool:
        api_key = os.environ.get("AI21_API_KEY", "")
        if not api_key:
            return False
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(f"{self.base_url}/models", headers=headers)
                return resp.status_code == 200
        except Exception:
            return False

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (prompt_tokens * 0.0005 + completion_tokens * 0.0015) / 1000.0
