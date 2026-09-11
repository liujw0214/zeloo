"""Cerebras provider — ultra-fast GPU inference."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from model_providers.base import ChatResponse, ProviderProfile


@dataclass
class CerebrasProvider(ProviderProfile):
    """Cerebras API provider.

    Provides ultra-fast inference using Cerebras wafer-scale engines.
    OpenAI-compatible API.
    """

    name: str = "cerebras"
    base_url: str = "https://api.cerebras.ai/v1"
    default_model: str = "llama-3.3-70b"
    supports_vision: bool = False
    supports_function_calling: bool = True
    supports_streaming: bool = True

    MODELS = {
        "llama-3.3-70b": "llama-3.3-70b",
        "llama-3.1-8b": "llama-3.1-8b",
        "qwen-2.5-72b": "qwen-2.5-72b",
        "qwen-2.5-32b": "qwen-2.5-32b",
        "qwen-2.5-7b": "qwen-2.5-7b",
        "mistral-7b": "mistral-7b",
    }

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        api_key = os.environ.get("CEREBRAS_API_KEY", "")
        if not api_key:
            raise ValueError("CEREBRAS_API_KEY environment variable not set")

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
        api_key = os.environ.get("CEREBRAS_API_KEY", "")
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
        return (prompt_tokens * 0.00006 + completion_tokens * 0.00006) / 1000.0
