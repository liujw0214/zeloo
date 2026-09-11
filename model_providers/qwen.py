"""Qwen provider — Alibaba Cloud open-source models."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from model_providers.base import ChatResponse, ProviderProfile


@dataclass
class QwenProvider(ProviderProfile):
    """Qwen (Alibaba Cloud) inference provider.

    Provides access to Qwen series models including Qwen2.5 and Qwen VL.
    OpenAI-compatible API via DashScope or compatible endpoints.
    """

    name: str = "qwen"
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    default_model: str = "qwen-turbo"
    supports_vision: bool = True
    supports_function_calling: bool = True
    supports_streaming: bool = True

    MODELS = {
        "qwen-turbo": "qwen-turbo",
        "qwen-plus": "qwen-plus",
        "qwen-max": "qwen-max",
        "qwen-max-longcontext": "qwen-max-longcontext",
        "qwen-vl-plus": "qwen-vl-plus",
        "qwen-vl-max": "qwen-vl-max",
        "qwen2.5-72b-instruct": "qwen2.5-72b-instruct",
        "qwen2.5-32b-instruct": "qwen2.5-32b-instruct",
        "qwen2.5-7b-instruct": "qwen2.5-7b-instruct",
    }

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        api_key = os.environ.get("DASHSCOPE_API_KEY", "")
        if not api_key:
            raise ValueError("DASHSCOPE_API_KEY environment variable not set")

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
        api_key = os.environ.get("DASHSCOPE_API_KEY", "")
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
        return (prompt_tokens * 0.00008 + completion_tokens * 0.00024) / 1000.0
