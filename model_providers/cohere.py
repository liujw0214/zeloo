"""Cohere model provider — Command R series with RAG-optimized models."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from model_providers.base import ChatResponse, ProviderProfile

logger = logging.getLogger(__name__)

_COHERE_BASE_URL = "https://api.cohere.ai/v1"

_RATES: dict[str, tuple[float, float]] = {
    "command-r-plus": (3.00, 15.00),
    "command-r": (0.50, 1.50),
    "command-r7b": (0.50, 1.50),
    "command": (0.50, 1.50),
    "command-light": (0.50, 1.50),
}


class CohereProvider(ProviderProfile):
    """Cohere API provider.

    Supports Command R series — optimized for RAG and tool use.
    Requires a ``COHERE_API_KEY`` environment variable or ``api_key`` argument.
    """

    name = "cohere"
    base_url = _COHERE_BASE_URL
    default_model = "command-r-plus"
    supports_vision = False
    supports_function_calling = True
    supports_streaming = True

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(api_key or os.environ.get("COHERE_API_KEY", ""), **kwargs)

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
        rates = _RATES.get(model, (3.00, 15.00))
        return input_tokens * rates[0] / 1_000_000 + output_tokens * rates[1] / 1_000_000

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        if not self.api_key:
            raise RuntimeError(
                "Cohere API key not set. Set COHERE_API_KEY or pass api_key."
            )
        target_model = model or self.default_model

        chat_messages = [{"role": m["role"], "content": m["content"]} for m in messages]

        payload: dict[str, Any] = {
            "model": target_model,
            "message": chat_messages[-1]["content"] if chat_messages else "",
            "chat_history": chat_messages[:-1],
        }
        for key in ("temperature", "max_tokens", "p"):
            if key in kwargs:
                payload[key] = kwargs[key]

        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                f"{self.base_url}/chat",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        text = data.get("text", "")
        usage = data.get("usage", {})
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))

        return ChatResponse(
            content=text,
            model=target_model,
            provider=self.name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            raw=data,
            finish_reason=data.get("finish_reason", "stop"),
            cost_usd=self.estimate_cost(prompt_tokens, completion_tokens, target_model),
        )
