"""Fireworks AI provider.

High-performance inference with function calling support.
Fireworks AI provides fast inference for open and proprietary models
through an OpenAI-compatible API.

Configuration keys (in ``config`` dict):

* ``api_key`` (str) — Fireworks API key. Falls back to ``FIREWORKS_API_KEY``.
* ``base_url`` (str) — API base URL. Defaults to
  ``https://api.fireworks.ai/v1``.
* ``default_model`` (str) — Defaults to ``accounts/fireworks/models/llama-v3p1-8b-instruct``.
* ``timeout`` (float) — Request timeout in seconds.

The provider registers itself as ``"fireworks"`` on import.
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


_DEFAULT_BASE_URL = "https://api.fireworks.ai/v1"
_DEFAULT_MODEL = "accounts/fireworks/models/llama-v3p1-8b-instruct"
_KEY_ENV = "FIREWORKS_API_KEY"

_KNOWN_FIREWORKS_MODELS: tuple[str, ...] = (
    "accounts/fireworks/models/llama-v3p1-8b-instruct",
    "accounts/fireworks/models/llama-v3p1-70b-instruct",
    "accounts/fireworks/models/llama-v3-8b-instruct",
    "accounts/fireworks/models/llama-v3-70b-instruct",
    "accounts/fireworks/models/llama-v3p3-8b-instruct",
    "accounts/fireworks/models/qwen2p5-72b-instruct",
    "accounts/fireworks/models/qwen2p5-7b-instruct",
    "accounts/fireworks/models/deepseek-v3",
    "accounts/fireworks/models/deepseek-v3-base",
    "accounts/fireworks/models/mixtral-8x7b-instruct",
    "accounts/fireworks/models/firefunction-v2",
    "accounts/fireworks/models/firefunction-v1",
)


class FireworksProvider(BaseProvider):
    """Fireworks AI provider.

    Provides access to high-performance inference through the Fireworks AI
    API. Compatible with OpenAI SDK and function calling via the standard
    tools parameter.
    """

    name = "fireworks"
    default_model = _DEFAULT_MODEL
    base_url = _DEFAULT_BASE_URL
    supports_vision = False
    supports_function_calling = True
    supports_streaming = True

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        if not self.api_key:
            self.config["api_key"] = os.environ.get(_KEY_ENV, "")
        if not self.base_url:
            self.config["base_url"] = _DEFAULT_BASE_URL
        if not self.default_model:
            self.config["default_model"] = _DEFAULT_MODEL

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not self.api_key:
            return build_error_response(
                provider=self.name,
                error="Fireworks API key not configured (set FIREWORKS_API_KEY)",
                status=401,
            )

        target_model = model or self.default_model
        payload: dict[str, Any] = {
            "model": target_model,
            "messages": messages,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
        }

        passthrough_keys = (
            "tools",
            "tool_choice",
            "response_format",
            "top_p",
            "frequency_penalty",
            "presence_penalty",
            "stop",
            "user",
            "seed",
            "n",
            "parallel_tool_calls",
        )
        for key in passthrough_keys:
            if key in kwargs and kwargs[key] is not None:
                payload[key] = kwargs[key]

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
        fallback = list(_KNOWN_FIREWORKS_MODELS)
        if not self.api_key:
            return fallback
        try:
            result = sync_get_json(
                f"{self.base_url.rstrip('/')}/models",
                headers=self._headers(),
                timeout=min(self.timeout, 10.0),
            )
            if not result.get("ok"):
                return fallback
            data = result.get("data", {})
            models = data.get("data", []) if isinstance(data, dict) else []
            ids = sorted(
                m.get("id") for m in models if isinstance(m, dict) and m.get("id")
            )
            return ids or fallback
        except Exception:
            return fallback

    def is_available(self) -> bool:
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


register_provider("fireworks", FireworksProvider)


__all__ = ["FireworksProvider"]
