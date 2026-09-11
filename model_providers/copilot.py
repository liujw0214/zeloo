"""GitHub Copilot model provider — OpenAI-compatible API with GitHub token auth."""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from model_providers.base import ChatResponse, ProviderProfile

logger = logging.getLogger(__name__)

_GITHUB_COPILOT_URL = "https://api.githubcopilot.com/chat/completions"

_GITHUB_RATES: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-4": (30.00, 60.00),
    "gpt-3.5-turbo": (0.50, 1.50),
}


class GitHubCopilotProvider(ProviderProfile):
    """GitHub Copilot API provider (OpenAI-compatible with GitHub token auth).

    Supports GPT-4o, GPT-4 Turbo, GPT-4, and GPT-3.5 Turbo models via GitHub's
    Copilot API. Requires a ``GITHUB_TOKEN`` environment variable (from
    https://github.com/settings/tokens with ``copilot`` scope) or ``api_key`` argument.

    Example::

        from model_providers import get_provider
        copilot = get_provider("copilot")
        response = copilot.chat_completion([{"role": "user", "content": "Hello"}])
        print(response.content)
    """

    name = "copilot"
    base_url = _GITHUB_COPILOT_URL
    default_model = "gpt-4o"
    supports_vision = False
    supports_function_calling = True
    supports_streaming = True

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(api_key or os.environ.get("GITHUB_TOKEN", ""), **kwargs)

    def validate_credentials(self) -> bool:
        if not self.api_key:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    self.base_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "X-GitHub-Token": self.api_key,
                    },
                    json={
                        "model": self.default_model,
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1,
                    },
                )
                return resp.status_code == 200
        except Exception:
            return False

    def estimate_cost(
        self, input_tokens: int, output_tokens: int, model: str
    ) -> float:
        rates = _GITHUB_RATES.get(model, (5.00, 15.00))
        return (
            input_tokens * rates[0] / 1_000_000
            + output_tokens * rates[1] / 1_000_000
        )

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        if not self.api_key:
            raise RuntimeError(
                "GitHub token not set. Set GITHUB_TOKEN env or pass api_key."
            )
        target_model = model or self.default_model
        payload: dict[str, Any] = {
            "model": target_model,
            "messages": messages,
        }
        for key in (
            "temperature",
            "max_tokens",
            "top_p",
            "stop",
            "stream",
            "n",
        ):
            if key in kwargs:
                payload[key] = kwargs[key]

        tools = kwargs.get("tools")
        if tools:
            payload["tools"] = tools

        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "X-GitHub-Token": self.api_key,
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
