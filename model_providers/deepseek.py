"""DeepSeek model provider.

DeepSeek offers an OpenAI-compatible HTTP API at
``https://api.deepseek.com/v1``. This provider wraps it behind the
:class:`ProviderProfile` interface.

Cost estimates (USD, per 1M tokens):
  * deepseek-chat / deepseek-coder: input $0.27, output $1.10
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

_DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
_DEEPSEEK_MODELS = ("deepseek-chat", "deepseek-coder")

# Cost in USD per 1,000,000 tokens (input, output).
_RATES: dict[str, tuple[float, float]] = {
    "deepseek-chat": (0.27, 1.10),
    "deepseek-coder": (0.27, 1.10),
    "deepseek-reasoner": (0.27, 1.10),
}


class DeepSeekProvider(ProviderProfile):
    """Provider implementation for DeepSeek API."""

    name = "deepseek"
    base_url = _DEEPSEEK_BASE_URL
    default_model = "deepseek-chat"
    supports_streaming = True
    supports_vision = False
    supports_function_calling = True

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(api_key, **kwargs)
        if self.api_key is None:
            self.api_key = os.environ.get("DEEPSEEK_API_KEY")

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """Call the DeepSeek chat completions endpoint."""
        if not self.api_key:
            raise RuntimeError(
                "DeepSeek API key not set. Provide api_key or set DEEPSEEK_API_KEY."
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
            raise RuntimeError(f"DeepSeek API error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"DeepSeek connection error: {exc.reason}") from exc

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
        except Exception as exc:  # noqa: BLE001 — any failure means invalid creds
            logger.debug("DeepSeek credential validation failed: %s", exc)
            return False

    def estimate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str | None = None,
    ) -> float:
        """Return USD cost estimate using DeepSeek pricing."""
        target = (model or self.default_model).lower()
        rate_in, rate_out = _RATES.get(target, (0.27, 1.10))
        in_cost = prompt_tokens / 1_000_000 * rate_in
        out_cost = completion_tokens / 1_000_000 * rate_out
        return round(in_cost + out_cost, 8)
