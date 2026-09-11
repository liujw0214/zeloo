"""DeepSeek Provider — DeepSeek-V3, R1 reasoning, and Coder.

Talks to DeepSeek's OpenAI-compatible API. The provider exposes
both chat completions and the reasoning ``reasoning_effort`` knob used
by DeepSeek-R1.

Configuration keys:

* ``api_key`` (str) — DeepSeek API key. Falls back to ``DEEPSEEK_API_KEY``.
* ``base_url`` (str) — Defaults to ``https://api.deepseek.com/v1``.
* ``default_model`` (str) — Defaults to ``deepseek-chat``.
* ``timeout`` (float) — Request timeout in seconds.

The provider registers itself as ``"deepseek"`` on import.
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


_DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
_DEFAULT_MODEL = "deepseek-chat"
_KEY_ENV = "DEEPSEEK_API_KEY"

_KNOWN_DEEPSEEK_MODELS: tuple[str, ...] = (
    "deepseek-chat",
    "deepseek-reasoner",
    "deepseek-coder",
    "deepseek-v3",
    "deepseek-r1",
    "deepseek-r1-lite-preview",
)


class DeepSeekProvider(BaseProvider):
    """DeepSeek provider (OpenAI-compatible)."""

    name = "deepseek"
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

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def _is_reasoning_model(self, model: str) -> bool:
        m = (model or "").lower()
        return "reason" in m or "r1" in m

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Call DeepSeek's ``/chat/completions`` endpoint.

        DeepSeek-R1 (``deepseek-reasoner``) surfaces its chain-of-thought
        in the ``reasoning_content`` field of the assistant message.
        This implementation exposes the reasoning text in the response
        ``raw`` payload so callers that care about CoT can inspect it.
        """
        if not self.api_key:
            return build_error_response(
                provider=self.name,
                error="DeepSeek API key not configured (set DEEPSEEK_API_KEY)",
                status=401,
            )
        target_model = model or self.default_model
        payload: dict[str, Any] = {
            "model": target_model,
            "messages": messages,
            "max_tokens": int(max_tokens),
            "stream": bool(stream),
        }
        # The R1 reasoning model does not honour ``temperature``.
        if not self._is_reasoning_model(target_model):
            payload["temperature"] = float(temperature)
        else:
            payload["temperature"] = 1.0

        for key in (
            "tools", "tool_choice", "top_p", "frequency_penalty",
            "presence_penalty", "stop", "user", "seed", "response_format",
            "n",
        ):
            if key in kwargs and kwargs[key] is not None:
                payload[key] = kwargs[key]

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
        """Return the curated list of known DeepSeek models."""
        if not self.api_key:
            return list(_KNOWN_DEEPSEEK_MODELS)
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
                return ids or list(_KNOWN_DEEPSEEK_MODELS)
        except Exception:  # pragma: no cover
            pass
        return list(_KNOWN_DEEPSEEK_MODELS)

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


register_provider("deepseek", DeepSeekProvider)


__all__ = ["DeepSeekProvider"]
