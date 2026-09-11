"""MonsterAPI provider — multi-model GPU inference platform."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from model_providers.base import ChatResponse, ProviderProfile


@dataclass
class MonsterAPIProvider(ProviderProfile):
    """MonsterAPI inference provider.

    Provides GPU-accelerated inference for open-source models.
    OpenAI-compatible API with flexible deployment options.
    """

    name: str = "monsterapi"
    base_url: str = "https://api.monsterapi.ai/v1"
    default_model: str = "meta-llama/Llama-3.3-70B-Instruct"
    supports_vision: bool = False
    supports_function_calling: bool = True
    supports_streaming: bool = True

    MODELS = {
        "meta-llama/Llama-3.3-70B-Instruct": "meta-llama/Llama-3.3-70B-Instruct",
        "meta-llama/Llama-3.1-8B-Instruct": "meta-llama/Llama-3.1-8B-Instruct",
        "mistralai/Mistral-7B-Instruct-v0.3": "mistralai/Mistral-7B-Instruct-v0.3",
        "Qwen/Qwen2.5-72B-Instruct": "Qwen/Qwen2.5-72B-Instruct",
    }

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        api_key = os.environ.get("MONSTERAPI_API_KEY", "")
        if not api_key:
            raise ValueError("MONSTERAPI_API_KEY environment variable not set")

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
        api_key = os.environ.get("MONSTERAPI_API_KEY", "")
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
        return (prompt_tokens * 0.00012 + completion_tokens * 0.00048) / 1000.0
