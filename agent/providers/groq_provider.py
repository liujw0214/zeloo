"""Groq Provider — ultra-low-latency inference for Llama 3, Mixtral, Whisper.

Groq exposes an OpenAI-compatible Chat Completions API. This module
implements the provider as a thin wrapper that reuses OpenAI's request
shape but routes to Groq's LPU-backed endpoints. Vision is supported
for Llama 3.2 vision models.

Configuration keys:

* ``api_key`` (str) — Groq API key. Falls back to ``GROQ_API_KEY``.
* ``base_url`` (str) — Defaults to ``https://api.groq.com/openai/v1``.
* ``default_model`` (str) — Defaults to ``llama-3.3-70b-versatile``.
* ``timeout`` (float) — Request timeout in seconds.

The provider registers itself as ``"groq"`` on import.
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


_DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
_DEFAULT_MODEL = "llama-3.3-70b-versatile"
_KEY_ENV = "GROQ_API_KEY"

_KNOWN_GROQ_MODELS: tuple[str, ...] = (
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
    "llama-3.1-8b-instant",
    "llama3-70b-8192",
    "llama3-8b-8192",
    "llama-3.2-90b-vision-preview",
    "llama-3.2-11b-vision-preview",
    "llama-3.2-3b-preview",
    "llama-3.2-1b-preview",
    "mixtral-8x7b-32768",
    "gemma2-9b-it",
    "whisper-large-v3-turbo",
    "whisper-large-v3",
)


class GroqProvider(BaseProvider):
    """Groq Cloud provider (OpenAI-compatible)."""

    name = "groq"
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
        """Call Groq's OpenAI-compatible ``/chat/completions`` endpoint."""
        if not self.api_key:
            return build_error_response(
                provider=self.name,
                error="Groq API key not configured (set GROQ_API_KEY)",
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
            "n",
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
        """Return Groq's catalogue.

        Performs a best-effort ``GET /models`` call; on failure the
        curated list is returned.
        """
        if not self.api_key:
            return list(_KNOWN_GROQ_MODELS)
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
                return ids or list(_KNOWN_GROQ_MODELS)
        except Exception:  # pragma: no cover - defensive
            pass
        return list(_KNOWN_GROQ_MODELS)

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


register_provider("groq", GroqProvider)


__all__ = ["GroqProvider"]
