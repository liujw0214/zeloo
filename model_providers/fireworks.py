"""Fireworks AI model provider — high-throughput OpenAI-compatible inference."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from model_providers.base import ChatResponse, ProviderProfile

logger = logging.getLogger(__name__)

_FIREWORKS_BASE_URL = "https://api.fireworks.ai/v1"

_RATES: dict[str, tuple[float, float]] = {
    "accounts/fireworks/models/llama-v3p3-70b-instruct": (0.60, 1.80),
    "accounts/fireworks/models/llama-v3p1-8b-instruct": (0.20, 0.60),
    "accounts/fireworks/models/deepseek-v3p7b": (0.20, 0.60),
    "accounts/fireworks/models/qwen2p5-72b-instruct": (0.60, 1.80),
}


class FireworksProvider(ProviderProfile):
    """Fireworks AI inference provider (OpenAI-compatible API).

    Requires a ``FIREWORKS_API_KEY`` environment variable or ``api_key`` argument.
    """

    name = "fireworks"
    base_url = _FIREWORKS_BASE_URL
    default_model = "accounts/fireworks/models/llama-v3p3-70b-instruct"
    supports_vision = False
    supports_function_calling = True
    supports_streaming = True

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(api_key or os.environ.get("FIREWORKS_API_KEY", ""), **kwargs)
        if not self.api_key:
            self.api_key = os.environ.get("FIREWORKS_API_KEY", "")

    def validate_credentials(self) -> bool:
        if not self.api_key:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    f"{self.base_url}/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                return resp.status_code < 500
        except httpx.RequestError:
            return False

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        rates = _RATES.get(model, (0.60, 1.80))
        return input_tokens * rates[0] / 1_000_000 + output_tokens * rates[1] / 1_000_000

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        if not self.api_key:
            raise RuntimeError(
                "Fireworks API key not set. Set FIREWORKS_API_KEY or pass api_key."
            )
        target_model = model or self.default_model
        payload: dict[str, Any] = {
            "model": target_model,
            "messages": messages,
        }
        for key in ("temperature", "max_tokens", "top_p"):
            if key in kwargs:
                payload[key] = kwargs[key]

        tools = kwargs.get("tools")
        if tools:
            payload["tools"] = tools

        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]
        msg = choice.get("message", {})
        content = msg.get("content", "")

        usage = data.get("usage", {})
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))

        return ChatResponse(
            content=content or "",
            model=target_model,
            provider=self.name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            raw=data,
            finish_reason=choice.get("finish_reason", "stop"),
            cost_usd=self.estimate_cost(prompt_tokens, completion_tokens, target_model),
            tool_calls=msg.get("tool_calls"),
        )
