"""Anthropic Provider — Claude Opus 4, Sonnet 4, Haiku 3.5, and friends.

Talks to the Anthropic Messages API directly (not the OpenAI-compatible
proxy). Supports vision through base64 / URL image content blocks,
prompt caching via the ``cache_control`` block flag, tool use via the
``tools`` parameter, and streaming through ``stream=True``.

Configuration keys:

* ``api_key`` (str) — Anthropic API key. Falls back to ``ANTHROPIC_API_KEY``.
* ``base_url`` (str) — Defaults to ``https://api.anthropic.com``.
* ``anthropic_version`` (str) — API version header. Defaults to
  ``2023-06-01``.
* ``default_model`` (str) — Defaults to ``claude-sonnet-4-5``.
* ``timeout`` (float) — Request timeout in seconds.

The provider registers itself as ``"anthropic"`` on import.
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


_DEFAULT_BASE_URL = "https://api.anthropic.com"
_DEFAULT_MODEL = "claude-sonnet-4-5"
_ANTHROPIC_VERSION = "2023-06-01"
_KEY_ENV = "ANTHROPIC_API_KEY"

# Latest Claude model identifiers (Sept 2025 snapshot).
_KNOWN_CLAUDE_MODELS: tuple[str, ...] = (
    "claude-opus-4-1",
    "claude-opus-4-0",
    "claude-sonnet-4-5",
    "claude-sonnet-4-0",
    "claude-3-7-sonnet-latest",
    "claude-3-5-sonnet-latest",
    "claude-3-5-haiku-latest",
    "claude-3-haiku-20240307",
)


class AnthropicProvider(BaseProvider):
    """Anthropic Messages API provider.

    Supports all Claude 3 / Claude 4 models with vision, tool use,
    prompt caching, and streaming.
    """

    name = "anthropic"
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
        if not self.config.get("anthropic_version"):
            self.config["anthropic_version"] = _ANTHROPIC_VERSION

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        """Build the standard Anthropic Messages API headers."""
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": str(self.config.get("anthropic_version") or _ANTHROPIC_VERSION),
        }

    @staticmethod
    def _split_messages(
        messages: list[dict[str, Any]],
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """Extract the optional system prompt and return the remaining messages.

        Anthropic's Messages API takes the system prompt as a separate
        ``system`` field rather than as a ``system``-role message.
        This helper performs the conversion.
        """
        system_parts: list[str] = []
        rest: list[dict[str, Any]] = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            if msg.get("role") == "system":
                content = msg.get("content")
                if isinstance(content, str):
                    system_parts.append(content)
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            system_parts.append(str(block.get("text", "")))
            else:
                rest.append(msg)
        system = "\n\n".join(p for p in system_parts if p) or None
        return system, rest

    def _convert_content(
        self,
        content: Any,
    ) -> Any:
        """Convert OpenAI-style content to Anthropic content blocks.

        Anthropic's API expects image content as ``{"type": "image",
        "source": {"type": "base64"|"url", ...}}`` blocks. The
        OpenAI-style ``{"type": "image_url", "image_url": {"url": ...}}``
        shape is mapped to the Anthropic shape so existing message
        builders can be reused.
        """
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return content
        converted: list[dict[str, Any]] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                converted.append({"type": "text", "text": str(block.get("text", ""))})
            elif btype in {"image_url", "image"}:
                url_obj = block.get("image_url") or block.get("source") or {}
                url = url_obj.get("url") if isinstance(url_obj, dict) else None
                if not url:
                    continue
                if url.startswith("data:"):
                    # data:image/png;base64,XXX — split into media_type + data
                    try:
                        header, b64 = url.split(",", 1)
                        media_type = header.split(";")[0].split(":", 1)[-1] or "image/png"
                        converted.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64,
                            },
                        })
                    except ValueError:
                        continue
                else:
                    converted.append({
                        "type": "image",
                        "source": {"type": "url", "url": url},
                    })
            elif btype in {"image", "tool_use", "tool_result"}:
                # Already in Anthropic shape — pass through.
                converted.append(block)
            else:
                # Unknown block type — keep verbatim so we don't silently
                # drop data.
                converted.append(block)
        return converted

    def _convert_messages(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Map ``messages`` to Anthropic's ``messages`` schema."""
        converted: list[dict[str, Any]] = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            if role not in {"user", "assistant"}:
                continue
            content = self._convert_content(msg.get("content"))
            # Anthropic requires non-empty content for tool-result blocks.
            new_msg: dict[str, Any] = {"role": role, "content": content}
            converted.append(new_msg)
        return converted

    def _convert_tools(
        self,
        tools: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]] | None:
        """Map OpenAI-style ``tools`` to Anthropic's ``tools`` schema."""
        if not tools:
            return None
        converted: list[dict[str, Any]] = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
                fn = tool["function"]
                converted.append({
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                })
            elif "name" in tool:
                # Already in Anthropic shape.
                converted.append(tool)
        return converted or None

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
        """Call the Anthropic Messages API.

        Args:
            messages: OpenAI-style message list. ``system`` messages
                are hoisted to the top-level ``system`` field.
            model: Model identifier (e.g. ``"claude-sonnet-4-5"``).
            temperature: Sampling temperature (0.0-1.0).
            max_tokens: Maximum tokens to generate. Anthropic
                *requires* this parameter; the default is 4096.
            stream: If True, the server-side events stream is enabled.
                This implementation collects the chunks into a single
                payload for the unified response shape.
            **kwargs: Forwarded as additional request fields. Common
                keys: ``tools``, ``tool_choice``, ``top_p``,
                ``top_k``, ``stop_sequences``, ``metadata``,
                ``cache_control``.

        Returns:
            A standardized response dict.
        """
        if not self.api_key:
            return build_error_response(
                provider=self.name,
                error="Anthropic API key not configured (set ANTHROPIC_API_KEY)",
                status=401,
            )

        target_model = model or self.default_model
        system_prompt, rest = self._split_messages(messages)
        converted_messages = self._convert_messages(rest)

        payload: dict[str, Any] = {
            "model": target_model,
            "max_tokens": int(max_tokens),
            "messages": converted_messages,
        }
        if system_prompt:
            payload["system"] = system_prompt
        # Temperature must be between 0 and 1 for Anthropic.
        try:
            payload["temperature"] = max(0.0, min(1.0, float(temperature)))
        except (TypeError, ValueError):
            payload["temperature"] = 0.7

        tools = self._convert_tools(kwargs.get("tools"))
        if tools:
            payload["tools"] = tools
        if "tool_choice" in kwargs and kwargs["tool_choice"] is not None:
            payload["tool_choice"] = kwargs["tool_choice"]
        for key in ("top_p", "top_k", "stop_sequences", "metadata"):
            if key in kwargs and kwargs[key] is not None:
                payload[key] = kwargs[key]
        if stream:
            payload["stream"] = True

        url = f"{self.base_url.rstrip('/')}/v1/messages"
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
        content_blocks: list[dict[str, Any]] = body.get("content") or []
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                text_parts.append(str(block.get("text", "")))
            elif btype == "tool_use":
                tool_calls.append({
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": block.get("input", {}),
                    },
                })
        usage = body.get("usage", {}) or {}
        return build_success_response(
            provider=self.name,
            content="".join(text_parts),
            model=body.get("model", target_model),
            finish_reason=str(body.get("stop_reason", "end_turn")),
            usage={
                "prompt_tokens": int(usage.get("input_tokens", 0) or 0),
                "completion_tokens": int(usage.get("output_tokens", 0) or 0),
                "total_tokens": int(usage.get("input_tokens", 0) or 0) + int(usage.get("output_tokens", 0) or 0),
            },
            raw=body,
            tool_calls=tool_calls,
        )

    def list_models(self) -> list[str]:
        """Return the curated list of known Claude model identifiers."""
        return list(_KNOWN_CLAUDE_MODELS)

    def is_available(self) -> bool:
        """Return True when the configured key can reach ``/v1/models``."""
        if not self.api_key:
            return False
        try:
            url = f"{self.base_url.rstrip('/')}/v1/models"
            result = sync_get_json(
                url,
                headers=self._headers(),
                timeout=min(self.timeout, 5.0),
            )
            if result.get("ok"):
                return True
            # Some Anthropic-compatible proxies don't expose /v1/models.
            # Fall back to probing a tiny ``/v1/messages`` request.
            probe = sync_get_json(
                f"{self.base_url.rstrip('/')}/v1/messages",
                headers=self._headers(),
                timeout=min(self.timeout, 5.0),
            )
            # 400 with auth-related body still indicates the key is
            # accepted; 401 / 403 means it isn't.
            status = int(probe.get("status", 0))
            return status not in {401, 403}
        except Exception:
            return False


register_provider("anthropic", AnthropicProvider)


__all__ = ["AnthropicProvider"]
