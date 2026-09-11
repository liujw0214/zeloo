"""Volcengine (火山引擎) provider — ByteDance AI inference."""

from __future__ import annotations

import base64
import hashlib
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

from model_providers.base import ChatResponse, ProviderProfile


@dataclass
class VolcEngineProvider(ProviderProfile):
    """Volcengine (ByteDance) AI inference provider.

    Provides access to Doubao and other ByteDance models
    via Volcengine's AI platform.
    """

    name: str = "volcengine"
    base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    default_model: str = "doubao-seed-32k"
    supports_vision: bool = False
    supports_function_calling: bool = True
    supports_streaming: bool = True

    MODELS = {
        "doubao-seed-32k": "doubao-seed-32k",
        "doubao-pro-32k": "doubao-pro-32k",
        "doubao-lite-32k": "doubao-lite-32k",
        "doubao-seed-256k": "doubao-seed-256k",
    }

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        api_key = os.environ.get("VOLCENGINE_API_KEY", "")
        if not api_key:
            raise ValueError("VOLCENGINE_API_KEY environment variable not set")

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

        timestamp = int(time.time())
        sign_str = f"GET\n/v3/chat/completions\n{api_key}:{timestamp}"
        sign = base64.b64encode(
            hashlib.sha256(sign_str.encode()).digest()
        ).decode()

        headers = {
            "Authorization": f"Bearer {api_key}:{timestamp}:{sign}",
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
        api_key = os.environ.get("VOLCENGINE_API_KEY", "")
        if not api_key:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(f"{self.base_url}/models", headers={"Authorization": f"Bearer {api_key}"})
                return resp.status_code == 200
        except Exception:
            return False

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (prompt_tokens * 0.00005 + completion_tokens * 0.0002) / 1000.0
