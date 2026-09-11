"""Anthropic model provider.

Native Anthropic API (Claude 3.5 Sonnet, Claude 3 Opus, Claude 3 Haiku,
etc.) via https://api.anthropic.com/v1/messages.

Differences from OpenAI-compatible providers:
- ``system`` message must be extracted and passed separately as top-level field.
- The ``messages`` array must not contain a ``system`` role.
- Content blocks can be string or list-of-dicts (for vision).
- Response shape is different (``content[]`` instead of ``choices[0].message.content``).

Cost estimates (USD, per 1M tokens):
- claude-3-5-sonnet-latest: input $3.00, output $15.00
- claude-3-opus-20240229:   input $15.00, output $75.00
- claude-3-haiku-20240307:   input $0.25, output $1.25
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

_ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
_ANTHROPIC_DEFAULT_MODEL = "claude-3-5-sonnet-latest"
_ANTHROPIC_MODELS = (
    "claude-3-5-sonnet-latest",
    "claude-3-5-sonnet-20241022",
    "claude-3-opus-20240229",
    "claude-3-haiku-20240307",
    "claude-3-5-haiku-latest",
)

# Cost in USD per 1,000,000 tokens (input, output).
_RATES: dict[str, tuple[float, float]] = {
    "claude-3-5-sonnet-latest": (3.00, 15.00),
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
    "claude-3-5-sonnet-20240620": (3.00, 15.00),
    "claude-3-opus-20240229": (15.00, 75.00),
    "claude-3-haiku-20240307": (0.25, 1.25),
    "claude-3-5-haiku-latest": (1.00, 5.00),
}


class AnthropicProvider(ProviderProfile):
    """Provider implementation for native Anthropic API."""

    name = "anthropic"
    base_url = _ANTHROPIC_BASE_URL
    default_model = _ANTHROPIC_DEFAULT_MODEL
    supports_streaming = True
    supports_vision = True
    supports_function_calling = True

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(api_key, **kwargs)
        if self.api_key is None:
            self.api_key = os.environ.get("ANTHROPIC_API_KEY")

    def _split_messages(
        self, messages: list[dict[str, Any]]
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """Extract system message and return (system, messages_without_system)."""
        system_parts: list[str] = []
        rest: list[dict[str, Any]] = []
        for m in messages:
            if m.get("role") == "system":
                content = m.get("content", "")
                if isinstance(content, str):
                    system_parts.append(content)
            else:
                rest.append(m)
        return ("\n\n".join(system_parts) if system_parts else None, rest)

    def _convert_tools(self, tools: Any) -> list[dict[str, Any]]:
        """Convert OpenAI-style tool schema to Anthropic tool schema.

        OpenAI: {"type": "function", "function": {"name", "description", "parameters"}}
        Anthropic: {"name", "description", "input_schema"}
        """
        out: list[dict[str, Any]] = []
        if not tools:
            return out
        for t in tools:
            if isinstance(t, dict) and t.get("type") == "function":
                fn = t.get("function", {})
                out.append({
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                })
            elif isinstance(t, dict) and "name" in t:
                out.append(t)
        return out

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """Call the Anthropic messages endpoint."""
        if not self.api_key:
            raise RuntimeError(
                "Anthropic API key not set. Provide api_key or set ANTHROPIC_API_KEY."
            )

        target_model = model or self.default_model
        system_text, conv_messages = self._split_messages(messages)

        payload: dict[str, Any] = {
            "model": target_model,
            "messages": conv_messages,
            "max_tokens": int(kwargs.pop("max_tokens", 1024)),
        }
        if system_text:
            payload["system"] = system_text
        for key in ("temperature", "top_p", "stop_sequences"):
            if key in kwargs:
                payload[key] = kwargs[key]
        if "tools" in kwargs:
            payload["tools"] = self._convert_tools(kwargs["tools"])

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/messages",
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")[:200]
            raise RuntimeError(f"Anthropic API error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Anthropic connection error: {exc.reason}") from exc

        # Anthropic content is an array of blocks
        content_blocks = data.get("content", [])
        text_parts: list[str] = []
        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text", ""))
        content = "".join(text_parts)

        usage = data.get("usage", {})
        prompt_tokens = int(usage.get("input_tokens", 0))
        completion_tokens = int(usage.get("output_tokens", 0))
        total_tokens = prompt_tokens + completion_tokens
        cost = self.estimate_cost(prompt_tokens, completion_tokens, target_model)

        stop_reason = data.get("stop_reason", "end_turn")
        return ChatResponse(
            content=content,
            model=target_model,
            provider=self.name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            finish_reason=stop_reason,
            raw=data,
            cost_usd=cost,
        )

    def validate_credentials(self) -> bool:
        """Send a minimal messages request to verify the API key works."""
        try:
            self.chat_completion(
                [{"role": "user", "content": "ping"}],
                model=self.default_model,
                max_tokens=1,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.debug("Anthropic credential validation failed: %s", exc)
            return False

    def estimate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str | None = None,
    ) -> float:
        """Return USD cost estimate using Anthropic pricing."""
        target = (model or self.default_model).lower()
        rate_in, rate_out = _RATES.get(target, (3.00, 15.00))
        in_cost = prompt_tokens / 1_000_000 * rate_in
        out_cost = completion_tokens / 1_000_000 * rate_out
        return round(in_cost + out_cost, 8)
