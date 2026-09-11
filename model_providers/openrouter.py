"""OpenRouter model provider.

OpenRouter (https://openrouter.ai) provides a single OpenAI-compatible API
endpoint that proxies 100+ models from many vendors (OpenAI, Anthropic,
Google, Meta, Mistral, etc.). This is the easiest way to access many
models without separate API keys per vendor.

Cost estimates (USD, per 1M tokens). OpenRouter normalizes pricing but
varies per model. We default to a conservative estimate; the OpenRouter
response includes ``usage.cost`` for actual billing.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from model_providers.base import ChatResponse, ProviderProfile

logger = logging.getLogger(__name__)

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_OPENROUTER_DEFAULT_MODEL = "anthropic/claude-3.5-sonnet"
_OPENROUTER_MODELS = (
    "openai/gpt-4o",
    "openai/gpt-4o-mini",
    "openai/gpt-4-turbo",
    "anthropic/claude-3.5-sonnet",
    "anthropic/claude-3-haiku",
    "google/gemini-pro-1.5",
    "meta-llama/llama-3.1-405b-instruct",
    "meta-llama/llama-3.1-70b-instruct",
    "mistralai/mistral-large-latest",
    "qwen/qwen-2.5-72b-instruct",
    "deepseek/deepseek-chat",
    "x-ai/grok-beta",
)

# Conservative fallback rates (input, output per 1M tokens).
# OpenRouter response includes usage.cost when available.
_FALLBACK_RATES: dict[str, tuple[float, float]] = {
    "openai/gpt-4o": (2.50, 10.00),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "openai/gpt-4-turbo": (10.00, 30.00),
    "anthropic/claude-3.5-sonnet": (3.00, 15.00),
    "anthropic/claude-3-haiku": (0.25, 1.25),
    "google/gemini-pro-1.5": (2.50, 7.50),
    "meta-llama/llama-3.1-405b-instruct": (3.00, 3.00),
    "meta-llama/llama-3.1-70b-instruct": (0.88, 0.88),
    "mistralai/mistral-large-latest": (2.00, 6.00),
    "qwen/qwen-2.5-72b-instruct": (0.40, 0.40),
    "deepseek/deepseek-chat": (0.27, 1.10),
    "x-ai/grok-beta": (5.00, 15.00),
}


class OpenRouterProvider(ProviderProfile):
    """Provider implementation for OpenRouter API.

    OpenRouter uses an OpenAI-compatible schema, so the request/response
    parsing follows the OpenAI pattern.
    """

    name = "openrouter"
    base_url = _OPENROUTER_BASE_URL
    default_model = _OPENROUTER_DEFAULT_MODEL
    supports_streaming = True
    supports_vision = True
    supports_function_calling = True

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(api_key, **kwargs)
        if self.api_key is None:
            self.api_key = os.environ.get("OPENROUTER_API_KEY")

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """Call the OpenRouter chat completions endpoint."""
        if not self.api_key:
            raise RuntimeError(
                "OpenRouter API key not set. Provide api_key or set OPENROUTER_API_KEY."
            )

        target_model = model or self.default_model
        payload: dict[str, Any] = {
            "model": target_model,
            "messages": messages,
        }
        for key in ("temperature", "max_tokens", "top_p", "frequency_penalty", "tools"):
            if key in kwargs:
                payload[key] = kwargs[key]

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "HTTP-Referer": "https://github.com/your-org/Zeloo",
                "X-Title": "Zeloo",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")[:200]
            raise RuntimeError(f"OpenRouter API error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"OpenRouter connection error: {exc.reason}") from exc

        choice = data.get("choices", [{}])[0]
        usage = data.get("usage", {})
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))
        total_tokens = int(usage.get("total_tokens", prompt_tokens + completion_tokens))

        # Prefer server-reported cost if available; fall back to local rates.
        server_cost = usage.get("cost")
        if server_cost is not None:
            cost = float(server_cost)
        else:
            cost = self.estimate_cost(prompt_tokens, completion_tokens, target_model)

        return ChatResponse(
            content=choice.get("message", {}).get("content", ""),
            model=target_model,
            provider=self.name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            finish_reason=choice.get("finish_reason", "stop"),
            raw=data,
            cost_usd=cost,
        )

    def validate_credentials(self) -> bool:
        """Send a minimal chat request to verify the API key works."""
        try:
            self.chat_completion(
                [{"role": "user", "content": "ping"}],
                model=self.default_model,
                max_tokens=1,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.debug("OpenRouter credential validation failed: %s", exc)
            return False

    def estimate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str | None = None,
    ) -> float:
        """Return USD cost estimate using OpenRouter pricing table."""
        target = (model or self.default_model).lower()
        rate_in, rate_out = _FALLBACK_RATES.get(target, (2.50, 10.00))
        in_cost = prompt_tokens / 1_000_000 * rate_in
        out_cost = completion_tokens / 1_000_000 * rate_out
        return round(in_cost + out_cost, 8)
