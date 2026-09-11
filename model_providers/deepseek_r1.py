"""DeepSeek R1 provider — reasoning models with extended thinking."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from model_providers.base import ChatResponse, ProviderProfile


@dataclass
class DeepSeekR1Provider(ProviderProfile):
    """DeepSeek R1 reasoning model provider.

    Provides access to DeepSeek R1 and R1-Zero reasoning models
    with extended thinking capabilities.
    """

    name: str = "deepseek-r1"
    base_url: str = "https://api.deepseek.com"
    default_model: str = "deepseek-reasoner"
    supports_vision: bool = False
    supports_function_calling: bool = False
    supports_streaming: bool = True

    MODELS = {
        "deepseek-reasoner": "deepseek-reasoner",
        "deepseek-r1": "deepseek-r1",
        "deepseek-r1-distill-qwen-32b": "deepseek-r1-distill-qwen-32b",
        "deepseek-r1-distill-llama-70b": "deepseek-r1-distill-llama-70b",
        "deepseek-r1-distill-llama-8b": "deepseek-r1-distill-llama-8b",
    }

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY environment variable not set")

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

        with httpx.Client(timeout=180.0) as client:
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
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
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
        return (prompt_tokens * 0.00027 + completion_tokens * 0.0011) / 1000.0
