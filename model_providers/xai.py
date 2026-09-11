"""xAI (Grok) model provider.

xAI exposes an OpenAI-compatible chat completions endpoint at
``https://api.x.ai/v1``. This provider wraps it behind the
:class:`ProviderProfile` interface.

Cost estimates (USD, per 1M tokens):
- grok-2-latest:        input $5.00, output $15.00
- grok-2-vision-latest: input $5.00, output $15.00
- grok-beta:            input $5.00, output $15.00
- grok-vision-beta:     input $5.00, output $15.00
- grok-3:               input $3.00, output $15.00
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

_XAI_BASE_URL = "https://api.x.ai/v1"
_XAI_DEFAULT_MODEL = "grok-2-latest"
_XAI_MODELS = (
    "grok-2-latest",
    "grok-2-vision-latest",
    "grok-beta",
    "grok-vision-beta",
    "grok-3",
    "grok-3-mini",
)

# Cost in USD per 1,000,000 tokens (input, output).
_RATES: dict[str, tuple[float, float]] = {
    "grok-2-latest": (5.00, 15.00),
    "grok-2-vision-latest": (5.00, 15.00),
    "grok-beta": (5.00, 15.00),
    "grok-vision-beta": (5.00, 15.00),
    "grok-3": (3.00, 15.00),
    "grok-3-mini": (0.30, 0.50),
}


class XAIProvider(ProviderProfile):
    """Provider implementation for xAI (Grok) API.

    The xAI chat completions endpoint follows the OpenAI schema exactly,
    so we reuse the same request/response shape.
    """

    name = "xai"
    base_url = _XAI_BASE_URL
    default_model = _XAI_DEFAULT_MODEL
    supports_streaming = True
    supports_vision = True
    supports_function_calling = True

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(api_key, **kwargs)
        if self.api_key is None:
            self.api_key = os.environ.get("XAI_API_KEY")

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """Call the xAI chat completions endpoint."""
        if not self.api_key:
            raise RuntimeError(
                "xAI API key not set. Provide api_key or set XAI_API_KEY."
            )

        target_model = model or self.default_model
        payload: dict[str, Any] = {
            "model": target_model,
            "messages": messages,
        }
        for key in ("temperature", "max_tokens", "top_p", "frequency_penalty", "tools"):
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
            raise RuntimeError(f"xAI API error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"xAI connection error: {exc.reason}") from exc

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
            logger.debug("xAI credential validation failed: %s", exc)
            return False

    def estimate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str | None = None,
    ) -> float:
        """Return USD cost estimate using xAI pricing."""
        target = (model or self.default_model).lower()
        rate_in, rate_out = _RATES.get(target, (5.00, 15.00))
        in_cost = prompt_tokens / 1_000_000 * rate_in
        out_cost = completion_tokens / 1_000_000 * rate_out
        return round(in_cost + out_cost, 8)
