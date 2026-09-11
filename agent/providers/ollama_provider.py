"""Ollama Provider — local LLMs served by the Ollama runtime.

Talks to the Ollama HTTP API at ``http://localhost:11434`` by default.
The provider supports:

* Standard chat completions (``POST /api/chat``),
* Generation (``POST /api/generate``),
* Model listing (``GET /api/tags``),
* Vision through base64 image inputs (Llama 3.2 Vision, Qwen-VL, etc.).

Configuration keys:

* ``base_url`` (str) — Defaults to ``http://localhost:11434``.
  The provider tries common alternatives (``127.0.0.1``, host
  ``host.docker.internal``) when the default is unreachable.
* ``default_model`` (str) — Defaults to ``llama3.1``.
* ``timeout`` (float) — Request timeout in seconds.
* ``api_key`` — Optional; Ollama does not require authentication but
  some hosted variants (e.g. Ollama Cloud) do.

The provider registers itself as ``"ollama"`` on import.
"""

from __future__ import annotations

import logging
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


_DEFAULT_BASE_URL = "http://localhost:11434"
_DEFAULT_MODEL = "llama3.1"

# Candidate base URLs probed in order. The first reachable one wins.
_BASE_URL_CANDIDATES: tuple[str, ...] = (
    "http://localhost:11434",
    "http://127.0.0.1:11434",
    "http://host.docker.internal:11434",
)

# Common Ollama model identifiers used as a curated fallback list.
_KNOWN_OLLAMA_MODELS: tuple[str, ...] = (
    "llama3.3",
    "llama3.2",
    "llama3.1",
    "llama3.1:70b",
    "llama3.1:8b",
    "llama3.2-vision",
    "llama3.2-vision:11b",
    "qwen2.5",
    "qwen2.5:72b",
    "qwen2.5:32b",
    "qwen2.5-coder",
    "qwen2-vl",
    "mistral",
    "mistral-nemo",
    "mixtral",
    "gemma2",
    "gemma2:27b",
    "phi3",
    "phi3:14b",
    "codellama",
    "deepseek-coder-v2",
    "command-r",
    "command-r-plus",
)


class OllamaProvider(BaseProvider):
    """Ollama local LLM provider.

    The provider attempts to auto-detect a reachable Ollama server at
    construction time when no explicit ``base_url`` is configured. If
    no server can be reached, :meth:`is_available` returns ``False``
    but :meth:`chat_completion` still works when the user later
    configures a remote URL.
    """

    name = "ollama"
    default_model = _DEFAULT_MODEL
    base_url = _DEFAULT_BASE_URL
    supports_vision = True
    supports_function_calling = False
    supports_streaming = True

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        if not self.base_url:
            self.config["base_url"] = self._detect_base_url() or _DEFAULT_BASE_URL

    def _detect_base_url(self) -> str | None:
        """Return the first Ollama URL that responds to ``/api/tags``."""
        for candidate in _BASE_URL_CANDIDATES:
            try:
                result = sync_get_json(
                    f"{candidate.rstrip('/')}/api/tags",
                    timeout=2.0,
                )
                if result.get("ok"):
                    return candidate
            except Exception:
                continue
        return None

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _convert_messages(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Convert OpenAI-style messages to Ollama's chat shape.

        Ollama accepts ``{"role": "user|assistant|system", "content": ...,
        "images": [...]}`` where ``images`` is a list of base64-encoded
        image strings (without the ``data:`` prefix).
        """
        converted: list[dict[str, Any]] = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            if role not in {"system", "user", "assistant"}:
                # Tool messages are mapped to user turns with the
                # tool content as text so the local model can react.
                role = "user"
            content = msg.get("content")
            new_msg: dict[str, Any] = {"role": role}
            images: list[str] = []
            if isinstance(content, str):
                new_msg["content"] = content
            elif isinstance(content, list):
                text_parts: list[str] = []
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type")
                    if btype == "text":
                        text_parts.append(str(block.get("text", "")))
                    elif btype in {"image_url", "image"}:
                        url_obj = block.get("image_url") or block.get("source") or {}
                        url = url_obj.get("url") if isinstance(url_obj, dict) else None
                        if isinstance(url, str) and url.startswith("data:"):
                            try:
                                _, b64 = url.split(",", 1)
                                images.append(b64)
                            except ValueError:
                                continue
                new_msg["content"] = "".join(text_parts)
            else:
                new_msg["content"] = "" if content is None else str(content)
            if images:
                new_msg["images"] = images
            converted.append(new_msg)
        return converted

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Call Ollama's ``/api/chat`` endpoint.

        Ollama returns the response in ``message.content``. The
        ``done_reason`` field is mapped to the unified ``finish_reason``.
        Token counts are returned in ``prompt_eval_count`` and
        ``eval_count`` and are surfaced through the standard ``usage``
        dict.
        """
        target_model = model or self.default_model
        converted = self._convert_messages(messages)
        payload: dict[str, Any] = {
            "model": target_model,
            "messages": converted,
            "stream": bool(stream),
            "options": {
                "temperature": float(temperature),
                "num_predict": int(max_tokens),
            },
        }
        for key in ("format", "keep_alive", "tools"):
            if key in kwargs and kwargs[key] is not None:
                payload[key] = kwargs[key]

        url = f"{self.base_url.rstrip('/')}/api/chat"
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
        message = body.get("message", {}) if isinstance(body, dict) else {}
        content = str(message.get("content") or "")
        prompt_tokens = int(body.get("prompt_eval_count", 0) or 0)
        completion_tokens = int(body.get("eval_count", 0) or 0)
        done = bool(body.get("done"))
        finish_reason = "stop" if done else "length"
        return build_success_response(
            provider=self.name,
            content=content,
            model=str(body.get("model", target_model)),
            finish_reason=finish_reason,
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            raw=body,
        )

    def list_models(self) -> list[str]:
        """Return the locally installed Ollama models.

        Performs ``GET /api/tags``; falls back to the curated list when
        the server is unreachable so the UI still has something to show.
        """
        try:
            result = sync_get_json(
                f"{self.base_url.rstrip('/')}/api/tags",
                headers=self._headers(),
                timeout=min(self.timeout, 5.0),
            )
            if result.get("ok"):
                data = result.get("data", {})
                models = data.get("models", []) if isinstance(data, dict) else []
                names = sorted(
                    m.get("name") for m in models if isinstance(m, dict) and m.get("name")
                )
                return names or list(_KNOWN_OLLAMA_MODELS)
        except Exception:  # pragma: no cover
            pass
        return list(_KNOWN_OLLAMA_MODELS)

    def is_available(self) -> bool:
        """Return True when the Ollama server responds to ``/api/tags``."""
        try:
            result = sync_get_json(
                f"{self.base_url.rstrip('/')}/api/tags",
                headers=self._headers(),
                timeout=min(self.timeout, 3.0),
            )
            return bool(result.get("ok"))
        except Exception:
            return False


register_provider("ollama", OllamaProvider)


__all__ = ["OllamaProvider"]
