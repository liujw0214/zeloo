"""Groq model provider — ultra-low-latency inference on Llama/Mixtral."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from model_providers.base import ChatResponse, ProviderProfile

logger = logging.getLogger(__name__)

_GROQ_BASE_URL = "https://api.groq.com/openai/v1"

_RATES: dict[str, tuple[float, float]] = {
    "llama-3.3-70b-versatile": (0.00, 0.59),
    "llama-3.1-70b-versatile": (0.00, 0.59),
    "llama-3.1-8b-instant": (0.00, 0.04),
    "llama-3.2-90b-vision-preview": (0.00, 0.59),
    "llama-3.2-11b-vision-preview": (0.00, 0.10),
    "mixtral-8x7b-32768": (0.00, 0.24),
}


class GroqProvider(ProviderProfile):
    """Groq API provider (OpenAI-compatible).

    Groq provides ultra-low-latency inference. Free tier available.
    Requires a ``GROQ_API_KEY`` environment variable or ``api_key`` argument.
    """

    name = "groq"
    base_url = _GROQ_BASE_URL
    default_model = "llama-3.3-70b-versatile"
    supports_vision = True
    supports_function_calling = True
    supports_streaming = True

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(api_key or os.environ.get("GROQ_API_KEY", ""), **kwargs)

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
        rates = _RATES.get(model, (0.00, 0.59))
        return input_tokens * rates[0] / 1_000_000 + output_tokens * rates[1] / 1_000_000

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        if not self.api_key:
            raise RuntimeError(
                "Groq API key not set. Set GROQ_API_KEY or pass api_key."
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

        with httpx.Client(timeout=60.0) as client:
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
