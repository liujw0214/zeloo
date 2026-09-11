"""Together AI model provider — open-source model hosting with OpenAI-compatible API."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from model_providers.base import ChatResponse, ProviderProfile

logger = logging.getLogger(__name__)

_TOGETHER_BASE_URL = "https://api.together.xyz/v1"

_RATES: dict[str, tuple[float, float]] = {
    "meta-llama/Llama-3.3-70B-Instruct": (0.24, 0.24),
    "meta-llama/Llama-3.1-8B-Instruct": (0.20, 0.20),
    "meta-llama/Llama-3.1-70B-Instruct": (0.24, 0.24),
    "mistralai/Mixtral-8x7B-Instruct-v0.1": (0.24, 0.24),
    "mistralai/Mistral-7B-Instruct-v0.3": (0.20, 0.20),
    "deepseek-ai/DeepSeek-V3": (0.20, 0.20),
    "Qwen/Qwen2.5-72B-Instruct": (0.24, 0.24),
    "Qwen/Qwen2.5-32B-Instruct": (0.20, 0.20),
    "google/gemma-2-27b-it": (0.20, 0.20),
    "NousResearch/Hermes-3-Llama-3.1-8B": (0.20, 0.20),
}


class TogetherProvider(ProviderProfile):
    """Together AI provider (OpenAI-compatible).

    Hosts 100+ open-source models including Llama, Mistral, DeepSeek, Qwen.
    Requires a ``TOGETHER_API_KEY`` environment variable or ``api_key`` argument.
    """

    name = "together"
    base_url = _TOGETHER_BASE_URL
    default_model = "meta-llama/Llama-3.3-70B-Instruct"
    supports_vision = False
    supports_function_calling = True
    supports_streaming = True

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(api_key or os.environ.get("TOGETHER_API_KEY", ""), **kwargs)

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
        rates = _RATES.get(model, (0.24, 0.24))
        return input_tokens * rates[0] / 1_000_000 + output_tokens * rates[1] / 1_000_000

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        if not self.api_key:
            raise RuntimeError(
                "Together API key not set. Set TOGETHER_API_KEY or pass api_key."
            )
        target_model = model or self.default_model
        payload: dict[str, Any] = {
            "model": target_model,
            "messages": messages,
        }
        for key in ("temperature", "max_tokens", "top_p", "stop"):
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
        usage = data.get("usage", {})
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))

        return ChatResponse(
            content=msg.get("content", "") or "",
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
