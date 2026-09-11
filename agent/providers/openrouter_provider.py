"""OpenRouter Provider — aggregated access to 200+ models.

OpenRouter exposes a single OpenAI-compatible endpoint that fronts
models from OpenAI, Anthropic, Google, Mistral, Meta and many open
weights projects. This provider implements the OpenAI Chat Completions
shape and adds OpenRouter-specific request headers (``HTTP-Referer``,
``X-Title``) used for analytics and rate-limit tiering.

Configuration keys:

* ``api_key`` (str) — OpenRouter API key. Falls back to
  ``OPENROUTER_API_KEY``.
* ``base_url`` (str) — Defaults to ``https://openrouter.ai/api/v1``.
* ``default_model`` (str) — Defaults to
  ``"anthropic/claude-3.5-sonnet"``.
* ``app_name`` (str) — Optional ``X-Title`` header value.
* ``app_url`` (str) — Optional ``HTTP-Referer`` header value.
* ``timeout`` (float) — Request timeout in seconds.

The provider registers itself as ``"openrouter"`` on import.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from agent.providers._http import (
    async_post_json,
    build_error_response,
    build_success_response,
    sync_get_json,
)
from agent.providers.base import BaseProvider
from agent.providers.registry import register_provider

logger = logging.getLogger(__name__)


_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_MODEL = "anthropic/claude-3.5-sonnet"
_KEY_ENV = "OPENROUTER_API_KEY"

_DEFAULT_POPULAR_MODELS: tuple[str, ...] = (
    "anthropic/claude-3.5-sonnet",
    "anthropic/claude-3-opus",
    "anthropic/claude-3-haiku",
    "openai/gpt-4o",
    "openai/gpt-4o-mini",
    "openai/o1-preview",
    "openai/o1-mini",
    "google/gemini-pro-1.5",
    "google/gemini-flash-1.5",
    "meta-llama/llama-3.1-405b-instruct",
    "meta-llama/llama-3.1-70b-instruct",
    "mistralai/mistral-large-latest",
    "qwen/qwen-2.5-72b-instruct",
    "deepseek/deepseek-chat",
)


class OpenRouterProvider(BaseProvider):
    """OpenRouter aggregation provider (OpenAI-compatible)."""

    name = "openrouter"
    default_model = _DEFAULT_MODEL
    base_url = _DEFAULT_BASE_URL
    supports_vision = True
    supports_function_calling = True
    supports_streaming = True

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        if not self.api_key:
            self.config["api_key"] = os.environ.get(_KEY_ENV, "")
        if not self.base_url:
            self.config["base_url"] = _DEFAULT_BASE_URL

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        if self.config.get("app_name"):
            headers["X-Title"] = str(self.config["app_name"])
        if self.config.get("app_url"):
            headers["HTTP-Referer"] = str(self.config["app_url"])
        return headers

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Call OpenRouter's OpenAI-compatible ``/chat/completions`` endpoint."""
        if not self.api_key:
            return build_error_response(
                provider=self.name,
                error="OpenRouter API key not configured (set OPENROUTER_API_KEY)",
                status=401,
            )
        target_model = model or self.default_model
        payload: dict[str, Any] = {
            "model": target_model,
            "messages": messages,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
        }
        for key in (
            "tools", "tool_choice", "top_p", "frequency_penalty",
            "presence_penalty", "stop", "user", "seed", "response_format",
            "n", "transforms",
        ):
            if key in kwargs and kwargs[key] is not None:
                payload[key] = kwargs[key]
        # OpenRouter-specific routing knobs.
        if "route" in kwargs and kwargs["route"]:
            payload["route"] = kwargs["route"]
        if "provider" in kwargs and kwargs["provider"]:
            payload["provider"] = kwargs["provider"]
        if stream:
            payload["stream"] = True

        url = f"{self.base_url.rstrip('/')}/chat/completions"
        result = await async_post_json(
            url,
            headers=self._headers(),
            json_payload=payload,
            timeout=self.timeout,
        )
        if not result.get("ok"):
            return build_error_response(
                provider=self.name,
                error=str(result.get("error", "unknown error")),
                status=int(result.get("status", 0)),
                raw=result.get("raw"),
            )

        body: dict[str, Any] = result.get("data", {})
        choice = (body.get("choices") or [{}])[0]
        message = choice.get("message", {}) if isinstance(choice, dict) else {}
        usage = body.get("usage", {}) or {}
        tool_calls = message.get("tool_calls") or []
        return build_success_response(
            provider=self.name,
            content=str(message.get("content") or ""),
            model=body.get("model", target_model),
            finish_reason=str(choice.get("finish_reason", "stop") if isinstance(choice, dict) else "stop"),
            usage={
                "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
                "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
                "total_tokens": int(usage.get("total_tokens", 0) or 0),
            },
            raw=body,
            tool_calls=tool_calls if isinstance(tool_calls, list) else [],
        )

    def list_models(self) -> list[str]:
        """Return OpenRouter's catalogue.

        Falls back to a curated list of popular models on error.
        """
        if not self.api_key:
            return list(_DEFAULT_POPULAR_MODELS)
        try:
            result = sync_get_json(
                f"{self.base_url.rstrip('/')}/models",
                headers=self._headers(),
                timeout=min(self.timeout, 5.0),
            )
            if result.get("ok"):
                data = result.get("data", {})
                models = data.get("data", []) if isinstance(data, dict) else []
                ids = sorted(
                    m.get("id") for m in models if isinstance(m, dict) and m.get("id")
                )
                return ids or list(_DEFAULT_POPULAR_MODELS)
        except Exception:  # pragma: no cover
            pass
        return list(_DEFAULT_POPULAR_MODELS)

    def is_available(self) -> bool:
        """Return True when the configured key can reach ``/models``."""
        if not self.api_key:
            return False
        try:
            result = sync_get_json(
                f"{self.base_url.rstrip('/')}/models",
                headers=self._headers(),
                timeout=min(self.timeout, 5.0),
            )
            return bool(result.get("ok"))
        except Exception:
            return False


register_provider("openrouter", OpenRouterProvider)


__all__ = ["OpenRouterProvider"]
