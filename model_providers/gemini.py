"""Gemini model provider.

Gemini exposes an OpenAI-compatible endpoint at
``https://generativelanguage.googleapis.com/v1beta/openai/``. This
provider wraps it behind the :class:`ProviderProfile` interface.

Cost estimates (USD, per 1M tokens) depend on the model tier:
  * gemini-2.0-flash:    input $0.10, output $0.40
  * gemini-1.5-flash:    input $0.035, output $0.14
  * gemini-1.5-pro:      input $1.25, output $5.00
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

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"

# Cost in USD per 1,000,000 tokens (input, output).
_RATES: dict[str, tuple[float, float]] = {
    "gemini-2.5-pro": (1.25, 5.00),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-1.5-pro": (1.25, 5.00),
    "gemini-1.5-flash": (0.035, 0.14),
    "gemini-1.0-pro": (0.50, 1.50),
}


class GeminiProvider(ProviderProfile):
    """Provider implementation for Google Gemini API."""

    name = "gemini"
    base_url = _GEMINI_BASE_URL
    default_model = "gemini-2.0-flash"
    supports_streaming = True
    supports_vision = True
    supports_function_calling = True

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(api_key, **kwargs)
        if self.api_key is None:
            self.api_key = os.environ.get("GEMINI_API_KEY")

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """Call the Gemini OpenAI-compatible chat completions endpoint."""
        if not self.api_key:
            raise RuntimeError(
                "Gemini API key not set. Provide api_key or set GEMINI_API_KEY."
            )

        target_model = model or self.default_model
        payload: dict[str, Any] = {
            "model": target_model,
            "messages": messages,
        }
        for key in ("temperature", "max_tokens", "top_p", "frequency_penalty"):
            if key in kwargs:
                payload[key] = kwargs[key]

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")[:200]
            raise RuntimeError(f"Gemini API error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Gemini connection error: {exc.reason}") from exc

        choice = data.get("choices", [{}])[0]
        usage = data.get("usage", {})
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))
        total_tokens = int(usage.get("total_tokens", prompt_tokens + completion_tokens))
        cost = self.estimate_cost(prompt_tokens, completion_tokens, target_model)

        return ChatResponse(
            content=choice.get("message", {}).get("content", ""),
            model=target_model,
            provider=self.name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            finish_reason=choice.get("finish_reason", "stop"),
            raw=data,
            cost_usd=cost,
        )

    def validate_credentials(self) -> bool:
        """Send a minimal chat request to verify the API key works."""
        try:
            self.chat_completion(
                [{"role": "user", "content": "ping"}],
                model=self.default_model,
                max_tokens=1,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.debug("Gemini credential validation failed: %s", exc)
            return False

    def estimate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str | None = None,
    ) -> float:
        """Return USD cost estimate using Gemini pricing."""
        target = (model or self.default_model).lower()
        rate_in, rate_out = _RATES.get(target, (0.10, 0.40))
        in_cost = prompt_tokens / 1_000_000 * rate_in
        out_cost = completion_tokens / 1_000_000 * rate_out
        return round(in_cost + out_cost, 8)
