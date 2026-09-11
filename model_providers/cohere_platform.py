"""Cohere Platform provider — enterprise AI from Cohere."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from model_providers.base import ChatResponse, ProviderProfile


@dataclass
class CoherePlatformProvider(ProviderProfile):
    """Cohere Platform enterprise AI provider.

    Provides access to Cohere's latest models including
    Command A (best-in-class for agentic tasks).
    """

    name: str = "cohere-platform"
    base_url: str = "https://api.cohere.ai/v1"
    default_model: str = "command-a-03-2025"
    supports_vision: bool = False
    supports_function_calling: bool = True
    supports_streaming: bool = True

    MODELS = {
        "command-a-03-2025": "command-a-03-2025",
        "command-r-08-2024": "command-r-08-2024",
        "command-r-plus-08-2024": "command-r-plus-08-2024",
        "command": "command",
        "command-light": "command-light",
    }

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        api_key = os.environ.get("COHERE_API_KEY", "")
        if not api_key:
            raise ValueError("COHERE_API_KEY environment variable not set")

        endpoint = f"{self.base_url}/chat"
        model = model or self.default_model

        body: dict[str, Any] = {
            "model": model,
            "message": self._extract_last_message(messages),
            "chat_history": self._build_chat_history(messages),
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
            content=data.get("text", ""),
            model=data.get("model", model),
            provider=self.name,
            usage={
                "prompt_tokens": data.get("usage", {}).get("billed_tokens", 0),
                "completion_tokens": 0,
                "total_tokens": data.get("usage", {}).get("billed_tokens", 0),
            },
            raw=data,
        )

    def _extract_last_message(self, messages: list[dict[str, Any]]) -> str:
        for msg in reversed(messages):
            if msg.get("role") == "user":
                return msg.get("content", "")
        return ""

    def _build_chat_history(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, str]]:
        history = []
        for msg in messages[:-1]:
            role = msg.get("role", "user")
            if role in ("user", "assistant"):
                history.append({"role": role, "message": msg.get("content", "")})
        return history

    def validate_credentials(self) -> bool:
        api_key = os.environ.get("COHERE_API_KEY", "")
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
        return (prompt_tokens * 0.003 + completion_tokens * 0.015) / 1000.0
