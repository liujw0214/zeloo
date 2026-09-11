"""OpenAI Provider — GPT-4o, GPT-4 Turbo, o1, and compatible endpoints.

This provider talks to the OpenAI Chat Completions API. It also
covers OpenAI-compatible endpoints (Azure OpenAI, vLLM, Together AI,
…) when configured with a non-default ``base_url``. Vision inputs are
passed through as ``image_url`` content parts so the same code path
handles GPT-4o vision, function calling via the ``tools`` parameter,
and o1 reasoning models (which use ``max_completion_tokens`` instead
of ``max_tokens``).

Configuration keys (in ``config`` dict):

* ``api_key`` (str) — OpenAI API key. Falls back to ``OPENAI_API_KEY``.
* ``base_url`` (str) — Override the default ``https://api.openai.com/v1``.
* ``organization`` (str) — Optional ``OpenAI-Organization`` header.
* ``default_model`` (str) — Defaults to ``gpt-4o``.
* ``timeout`` (float) — Request timeout in seconds.
* ``max_retries`` (int) — Number of automatic retries on 5xx / network errors.

The provider registers itself as ``"openai"`` on import.
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


_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_DEFAULT_MODEL = "gpt-4o"
_OPENAI_KEY_ENV = "OPENAI_API_KEY"

# o1 reasoning models require ``max_completion_tokens`` rather than
# ``max_tokens`` (which they reject). The provider checks the model
# name against this set when assembling the request body.
_O1_REASONING_PREFIXES: tuple[str, ...] = ("o1-", "o1", "o3-", "o3", "o4-")


class OpenAIProvider(BaseProvider):
    """OpenAI Chat Completions provider.

    Supports GPT-4o (vision), GPT-4 Turbo, GPT-4, GPT-3.5 Turbo and
    the o1 / o3 reasoning families. Function calling and streaming
    are supported through the standard ``tools`` / ``stream`` kwargs.
    """

    name = "openai"
    default_model = _DEFAULT_MODEL
    base_url = _DEFAULT_BASE_URL
    supports_vision = True
    supports_function_calling = True
    supports_streaming = True

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        # Fall back to env var if not configured.
        if not self.api_key:
            self.config["api_key"] = os.environ.get(_OPENAI_KEY_ENV, "")
        if not self.base_url:
            self.config["base_url"] = _DEFAULT_BASE_URL
        if not self.default_model:
            self.config["default_model"] = _DEFAULT_MODEL

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        """Build the standard OpenAI request headers."""
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        org = self.config.get("organization")
        if org:
            headers["OpenAI-Organization"] = str(org)
        return headers

    def _is_reasoning_model(self, model: str) -> bool:
        """Return True when *model* belongs to the o1/o3 reasoning family."""
        m = (model or "").lower()
        return any(m.startswith(prefix) for prefix in _O1_REASONING_PREFIXES)

    # ------------------------------------------------------------------
    # BaseProvider interface
    # ------------------------------------------------------------------
    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Call the OpenAI ``/chat/completions`` endpoint.

        Args:
            messages: OpenAI-style message list.
            model: Model identifier (e.g. ``"gpt-4o"``).
            temperature: Sampling temperature (0.0-2.0).
            max_tokens: Maximum tokens to generate.
            stream: Whether to stream the response. The OpenAI SSE
                stream is collected into a single payload by this
                implementation; downstream callers that need
                token-by-token streaming should use the OpenAI SDK
                directly.
            **kwargs: Forwarded as additional request fields. Common
                keys: ``tools``, ``tool_choice``, ``response_format``,
                ``top_p``, ``frequency_penalty``, ``presence_penalty``,
                ``stop``, ``user``.

        Returns:
            A standardized response dict. See :data:`build_success_response`
            and :data:`build_error_response` for the exact schema.
        """
        if not self.api_key:
            return build_error_response(
                provider=self.name,
                error="OpenAI API key not configured (set OPENAI_API_KEY)",
                status=401,
            )

        target_model = model or self.default_model
        payload: dict[str, Any] = {
            "model": target_model,
            "messages": messages,
        }
        # Reasoning models (o1/o3) reject ``temperature`` and use a
        # different token-limit parameter. Branch accordingly.
        if self._is_reasoning_model(target_model):
            payload["max_completion_tokens"] = int(max_tokens)
        else:
            payload["temperature"] = float(temperature)
            payload["max_tokens"] = int(max_tokens)

        # Forward a curated subset of extra kwargs to avoid leaking
        # internal call-site arguments into the request body.
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
            "logit_bias",
            "n",
            "parallel_tool_calls",
        )
        for key in passthrough_keys:
            if key in kwargs and kwargs[key] is not None:
                payload[key] = kwargs[key]

        # Streaming: collect chunks into a single payload for the
        # unified response shape. Callers needing true streaming
        # should bypass this method.
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
        """Return a curated list of well-known OpenAI models.

        Performs a best-effort ``GET /models`` probe; on failure the
        static fallback list is returned.
        """
        fallback = [
            "gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4",
            "gpt-3.5-turbo", "o1", "o1-mini", "o1-preview",
            "o3-mini", "o4-mini",
        ]
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
        except Exception:  # pragma: no cover - defensive
            return fallback

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


# Register on import so the runtime can discover the provider via the
# registry without needing an explicit ``import`` from call sites.
register_provider("openai", OpenAIProvider)


__all__ = ["OpenAIProvider"]
