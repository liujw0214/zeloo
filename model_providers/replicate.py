"""Replicate provider — open models via Replicate API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from model_providers.base import ChatResponse, ProviderProfile


@dataclass
class ReplicateProvider(ProviderProfile):
    """Replicate API provider.

    Supports Llama, SDXL, and many open-source models via Replicate.
    Uses the chat completions endpoint for chat models.
    """

    name: str = "replicate"
    base_url: str = "https://api.replicate.com/v1"
    default_model: str = "meta/llama-3-70b-instruct"
    supports_vision: bool = False
    supports_function_calling: bool = True
    supports_streaming: bool = True

    MODELS = {
        "meta/llama-3-70b-instruct": "meta/llama-3-70b-instruct",
        "meta/llama-3-8b-instruct": "meta/llama-3-8b-instruct",
        "meta/llama-3.1-70b-instruct": "meta/llama-3.1-70b-instruct",
        "mistralai/mistral-7b-instruct": "mistralai/mistral-7b-instruct-v0.2",
        "deepseek-ai/deepseek-coder-33b": "deepseek-ai/deepseek-coder-33b-instruct",
        "stability-ai/sdxl": "stability-ai/sdxl:39ed52f2a78e934b3ba6e2a81ad9a80",
    }

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        api_key = os.environ.get("REPLICATE_API_KEY", "")
        if not api_key:
            raise ValueError("REPLICATE_API_KEY environment variable not set")

        endpoint = f"{self.base_url}/chat/completions"
        model = model or self.default_model

        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
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

        return ChatResponse(
            content=data["choices"][0]["message"]["content"],
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
        api_key = os.environ.get("REPLICATE_API_KEY", "")
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
        return (prompt_tokens * 0.00035 + completion_tokens * 0.00035) / 1000.0
