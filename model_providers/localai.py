"""LocalAI provider — self-hosted OpenAI-compatible inference."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from model_providers.base import ChatResponse, ProviderProfile


@dataclass
class LocalAIProvider(ProviderProfile):
    """LocalAI self-hosted provider.

    Connects to a LocalAI server for self-hosted inference.
    OpenAI-compatible API, supports Llama, Mistral, Phi, Gemma, etc.
    """

    name: str = "localai"
    base_url: str = "http://localhost:8080/v1"
    default_model: str = "llama-3.3-70b"
    supports_vision: bool = False
    supports_function_calling: bool = True
    supports_streaming: bool = True

    MODELS = {
        "llama-3.3-70b": "llama-3.3-70b",
        "llama-3.1-8b": "llama-3.1-8b",
        "mistral-7b": "mistral-7b",
        "gemma-2b": "gemma-2b",
        "phi-3": "phi-3",
    }

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        base_url = os.environ.get("LOCALAI_BASE_URL", self.base_url)
        model = model or self.default_model

        endpoint = f"{base_url}/chat/completions"

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

        with httpx.Client(timeout=300.0) as client:
            response = client.post(endpoint, json=body)
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
        base_url = os.environ.get("LOCALAI_BASE_URL", self.base_url)
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{base_url}/models")
                return resp.status_code == 200
        except Exception:
            return False

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return 0.0
