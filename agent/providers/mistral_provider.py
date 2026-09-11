"""Mistral Provider — Mistral Large, Codestral, Mixtral, and Embeddings.

Implements the Mistral AI Chat Completions API. The provider also
supports the ``embeddings`` endpoint (used by the agent's retrieval
features) and the ``fim`` (fill-in-the-middle) endpoint exposed by
Codestral.

Configuration keys:

* ``api_key`` (str) — Mistral API key. Falls back to ``MISTRAL_API_KEY``.
* ``base_url`` (str) — Defaults to ``https://api.mistral.ai/v1``.
* ``default_model`` (str) — Defaults to ``mistral-large-latest``.
* ``timeout`` (float) — Request timeout in seconds.

The provider registers itself as ``"mistral"`` on import.
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


_DEFAULT_BASE_URL = "https://api.mistral.ai/v1"
_DEFAULT_MODEL = "mistral-large-latest"
_KEY_ENV = "MISTRAL_API_KEY"

_KNOWN_MISTRAL_MODELS: tuple[str, ...] = (
    "mistral-large-latest",
    "mistral-medium-latest",
    "mistral-small-latest",
    "mistral-saba-latest",
    "ministral-8b-latest",
    "ministral-3b-latest",
    "codestral-latest",
    "codestral-mamba-latest",
    "pixtral-12b-2409",
    "pixtral-large-latest",
    "open-mistral-7b",
    "open-mixtral-8x7b",
    "open-mixtral-8x22b",
)


class MistralProvider(BaseProvider):
    """Mistral AI provider (chat + embeddings)."""

    name = "mistral"
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
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
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
        """Call Mistral's ``/chat/completions`` endpoint."""
        if not self.api_key:
            return build_error_response(
                provider=self.name,
                error="Mistral API key not configured (set MISTRAL_API_KEY)",
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
            "tools", "tool_choice", "top_p", "stop", "presence_penalty",
            "frequency_penalty", "response_format", "seed", "n", "safe_prompt",
        ):
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
        """Return Mistral's catalogue.

        Tries ``GET /models``; falls back to the curated list on error.
        """
        if not self.api_key:
            return list(_KNOWN_MISTRAL_MODELS)
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
                return ids or list(_KNOWN_MISTRAL_MODELS)
        except Exception:  # pragma: no cover
            pass
        return list(_KNOWN_MISTRAL_MODELS)

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


register_provider("mistral", MistralProvider)


__all__ = ["MistralProvider"]
