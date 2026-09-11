"""Google Provider — Gemini Pro, Flash, and Vision via the Generative AI API.

Talks to the Google ``generativelanguage.googleapis.com`` REST API
directly (no Vertex AI). Supports text + image inputs, function
calling via ``tools``, configurable safety settings, and streaming
through ``stream=True``.

Configuration keys:

* ``api_key`` (str) — Google API key. Falls back to ``GEMINI_API_KEY``
  or ``GOOGLE_API_KEY``.
* ``base_url`` (str) — Defaults to
  ``https://generativelanguage.googleapis.com``.
* ``default_model`` (str) — Defaults to ``gemini-2.5-pro``.
* ``timeout`` (float) — Request timeout in seconds.
* ``safety_settings`` (list) — Optional safety configuration.

The provider registers itself as ``"google"`` *and* ``"gemini"`` on
import for compatibility with the existing :mod:`model_providers`
registry.
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


_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"
_DEFAULT_MODEL = "gemini-2.5-pro"
_KEY_ENVS: tuple[str, ...] = ("GEMINI_API_KEY", "GOOGLE_API_KEY")

_KNOWN_GEMINI_MODELS: tuple[str, ...] = (
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-pro",
    "gemini-2.0-flash",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
)


class GoogleProvider(BaseProvider):
    """Google Generative AI (Gemini) provider."""

    name = "google"
    default_model = _DEFAULT_MODEL
    base_url = _DEFAULT_BASE_URL
    supports_vision = True
    supports_function_calling = True
    supports_streaming = True

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        if not self.api_key:
            for env_name in _KEY_ENVS:
                key = os.environ.get(env_name)
                if key:
                    self.config["api_key"] = key
                    break
        if not self.base_url:
            self.config["base_url"] = _DEFAULT_BASE_URL

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}

    def _convert_messages(
        self,
        messages: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
        """Split OpenAI-style messages into Gemini ``contents`` and ``systemInstruction``.

        Gemini's API represents the conversation as an ordered list of
        ``contents`` alternating between ``user`` and ``model`` roles.
        System messages become a top-level ``systemInstruction`` field.
        """
        system_parts: list[dict[str, Any]] = []
        contents: list[dict[str, Any]] = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            content = msg.get("content")
            if role == "system":
                text = content if isinstance(content, str) else self._flatten_text(content)
                if text:
                    system_parts.append({"text": text})
                continue
            if role in {"user", "human"}:
                g_role = "user"
            elif role in {"assistant", "model", "ai"}:
                g_role = "model"
            elif role == "tool":
                # Tool responses map to ``functionResponse`` parts.
                parts = self._convert_tool_response(content)
                if parts:
                    contents.append({"role": "function", "parts": parts})
                continue
            else:
                g_role = "user"
            parts = self._convert_content_to_parts(content)
            contents.append({"role": g_role, "parts": parts})

        system_instruction = {"parts": system_parts} if system_parts else None
        return contents, system_instruction

    @staticmethod
    def _flatten_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return str(content)
        chunks: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                chunks.append(str(block.get("text", "")))
        return "".join(chunks)

    def _convert_content_to_parts(self, content: Any) -> list[dict[str, Any]]:
        """Translate OpenAI-style content blocks to Gemini ``parts``."""
        if isinstance(content, str):
            return [{"text": content}] if content else []
        if not isinstance(content, list):
            return [{"text": str(content)}]
        parts: list[dict[str, Any]] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                parts.append({"text": str(block.get("text", ""))})
            elif btype in {"image_url", "image"}:
                url_obj = block.get("image_url") or block.get("source") or {}
                url = url_obj.get("url") if isinstance(url_obj, dict) else None
                if not url:
                    continue
                if url.startswith("data:"):
                    try:
                        header, b64 = url.split(",", 1)
                        media_type = header.split(";")[0].split(":", 1)[-1] or "image/png"
                        parts.append({
                            "inline_data": {
                                "mime_type": media_type,
                                "data": b64,
                            }
                        })
                    except ValueError:
                        continue
                else:
                    parts.append({"file_data": {"file_uri": url}})
            elif btype == "inline_data" and isinstance(block.get("inline_data"), dict):
                parts.append({"inline_data": block["inline_data"]})
            else:
                # Unknown block — fall back to text so we don't drop data.
                text_val = block.get("text") or block.get("content")
                if isinstance(text_val, str):
                    parts.append({"text": text_val})
        return parts or [{"text": ""}]

    def _convert_tool_response(self, content: Any) -> list[dict[str, Any]]:
        """Convert an OpenAI-style tool message into Gemini functionResponse parts."""
        if isinstance(content, str):
            return [{"functionResponse": {"name": "tool", "response": {"result": content}}}]
        if not isinstance(content, list):
            return []
        parts: list[dict[str, Any]] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                parts.append({
                    "functionResponse": {
                        "name": str(block.get("name", "tool")),
                        "response": block.get("content", {}),
                    }
                })
        return parts

    def _convert_tools(
        self,
        tools: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        declarations: list[dict[str, Any]] = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
                fn = tool["function"]
                declarations.append({
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
                })
        if not declarations:
            return None
        return [{"function_declarations": declarations}]

    def _default_safety_settings(self) -> list[dict[str, Any]]:
        """Return a permissive default safety policy."""
        return [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_ONLY_HIGH"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_ONLY_HIGH"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_ONLY_HIGH"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_ONLY_HIGH"},
        ]

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
        """Call Gemini's ``generateContent`` endpoint.

        Args:
            messages: OpenAI-style message list.
            model: Gemini model identifier (e.g. ``"gemini-2.5-pro"``).
            temperature: Sampling temperature (0.0-2.0).
            max_tokens: Maximum tokens to generate. Mapped to
                ``generationConfig.maxOutputTokens``.
            stream: If True, use the server stream protocol.
            **kwargs: Forwarded. Recognised keys: ``tools``,
                ``safety_settings``, ``top_p``, ``top_k``,
                ``stop_sequences``, ``response_schema``,
                ``response_mime_type``.

        Returns:
            A standardized response dict.
        """
        if not self.api_key:
            return build_error_response(
                provider=self.name,
                error="Google API key not configured (set GEMINI_API_KEY)",
                status=401,
            )

        target_model = model or self.default_model
        contents, system_instruction = self._convert_messages(messages)

        generation_config: dict[str, Any] = {
            "temperature": float(temperature),
            "maxOutputTokens": int(max_tokens),
        }
        if "top_p" in kwargs and kwargs["top_p"] is not None:
            generation_config["topP"] = kwargs["top_p"]
        if "top_k" in kwargs and kwargs["top_k"] is not None:
            generation_config["topK"] = kwargs["top_k"]
        if "stop_sequences" in kwargs and kwargs["stop_sequences"]:
            generation_config["stopSequences"] = kwargs["stop_sequences"]
        if "response_mime_type" in kwargs and kwargs["response_mime_type"]:
            generation_config["responseMimeType"] = kwargs["response_mime_type"]
        if "response_schema" in kwargs and kwargs["response_schema"]:
            generation_config["responseSchema"] = kwargs["response_schema"]

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": generation_config,
        }
        if system_instruction:
            payload["systemInstruction"] = system_instruction
        safety = kwargs.get("safety_settings") or self._default_safety_settings()
        if safety:
            payload["safetySettings"] = safety
        tools_payload = self._convert_tools(kwargs.get("tools"))
        if tools_payload:
            payload["tools"] = tools_payload
        if "tool_config" in kwargs and kwargs["tool_config"]:
            payload["toolConfig"] = kwargs["tool_config"]

        if stream:
            payload_alt = dict(payload)
            payload_alt["stream"] = True
            payload = payload_alt

        url = (
            f"{self.base_url.rstrip('/')}/v1beta/models/"
            f"{target_model}:generateContent?key={self.api_key}"
        )
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
        candidates: list[dict[str, Any]] = body.get("candidates") or []
        first: dict[str, Any] = candidates[0] if candidates else {}
        gemini_content = first.get("content", {}) if isinstance(first, dict) else {}
        parts: list[dict[str, Any]] = gemini_content.get("parts", []) if isinstance(gemini_content, dict) else []
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            if "text" in part and isinstance(part["text"], str):
                text_parts.append(part["text"])
            fc = part.get("functionCall")
            if isinstance(fc, dict):
                tool_calls.append({
                    "id": f"call_{len(tool_calls)}",
                    "type": "function",
                    "function": {
                        "name": fc.get("name", ""),
                        "arguments": fc.get("args", {}),
                    },
                })
        usage = body.get("usageMetadata", {}) or {}
        finish_reason = str(first.get("finishReason", "STOP")) if isinstance(first, dict) else "STOP"
        return build_success_response(
            provider=self.name,
            content="".join(text_parts),
            model=target_model,
            finish_reason=finish_reason.lower(),
            usage={
                "prompt_tokens": int(usage.get("promptTokenCount", 0) or 0),
                "completion_tokens": int(usage.get("candidatesTokenCount", 0) or 0),
                "total_tokens": int(usage.get("totalTokenCount", 0) or 0),
            },
            raw=body,
            tool_calls=tool_calls,
        )

    def list_models(self) -> list[str]:
        """Return the curated list of known Gemini model identifiers."""
        return list(_KNOWN_GEMINI_MODELS)

    def is_available(self) -> bool:
        """Return True when the configured key can reach ``/v1beta/models``."""
        if not self.api_key:
            return False
        try:
            url = f"{self.base_url.rstrip('/')}/v1beta/models?key={self.api_key}"
            result = sync_get_json(
                url,
                headers=self._headers(),
                timeout=min(self.timeout, 5.0),
            )
            return bool(result.get("ok"))
        except Exception:
            return False


register_provider("google", GoogleProvider)
# Alias used by other registries / configuration snippets.
register_provider("gemini", GoogleProvider)


__all__ = ["GoogleProvider"]
