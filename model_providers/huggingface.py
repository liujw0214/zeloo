"""HuggingFace Inference API model provider — open-source models via HF inference endpoint."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from model_providers.base import ChatResponse, ProviderProfile

logger = logging.getLogger(__name__)

_HF_BASE_URL = "https://api-inference.huggingface.co/models"

_RATES: dict[str, tuple[float, float]] = {
    "meta-llama/Llama-3.3-70B-Instruct": (0.20, 0.20),
    "meta-llama/Llama-3.1-8B-Instruct": (0.20, 0.20),
    "mistralai/Mistral-Nemo-Instruct": (0.20, 0.20),
    "mistralai/Mistral-7B-Instruct": (0.20, 0.20),
    "Qwen/Qwen2.5-72B-Instruct": (0.20, 0.20),
    "deepseek-ai/DeepSeek-V3": (0.20, 0.20),
}

_DEFAULT_RATE = (0.20, 0.20)


class HuggingFaceProvider(ProviderProfile):
    """HuggingFace Inference API provider.

    Supports open-source models via the Hugging Face Inference API.
    Set ``HUGGINGFACE_TOKEN`` environment variable or pass ``api_key``.
    """

    name = "huggingface"
    base_url = _HF_BASE_URL
    default_model = "meta-llama/Llama-3.3-70B-Instruct"
    supports_vision = False
    supports_function_calling = False
    supports_streaming = True

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(api_key or os.environ.get("HUGGINGFACE_TOKEN", ""), **kwargs)
        if not self.api_key:
            self.api_key = os.environ.get("HUGGINGFACE_TOKEN", "")

    def validate_credentials(self) -> bool:
        if not self.api_key:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    f"https://huggingface.co/api/models/{self.default_model}",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                return resp.status_code < 500
        except httpx.RequestError:
            return False

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        rates = _RATES.get(model, _DEFAULT_RATE)
        return input_tokens * rates[0] / 1_000_000 + output_tokens * rates[1] / 1_000_000

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        if not self.api_key:
            raise RuntimeError(
                "HuggingFace token not set. Set HUGGINGFACE_TOKEN in environment or pass api_key."
            )
        target_model = model or self.default_model
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
            "inputs": self._format_conversation(messages),
            "parameters": {
                "max_new_tokens": kwargs.get("max_tokens", 512),
                "temperature": kwargs.get("temperature", 0.7),
                "return_full_text": False,
            },
        }

        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                f"{_HF_BASE_URL}/{target_model}",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        if isinstance(data, list):
            data = data[0]
        generated_text = data.get("generated_text", "")
        input_len = data.get("estimate", {}).get("input_length", 0)
        output_len = data.get("estimate", {}).get("output_length", len(generated_text) // 4)

        return ChatResponse(
            content=generated_text,
            model=target_model,
            provider=self.name,
            prompt_tokens=input_len,
            completion_tokens=output_len,
            total_tokens=input_len + output_len,
            raw=data,
            finish_reason=data.get("finish_reason", "stop"),
            cost_usd=self.estimate_cost(input_len, output_len, target_model),
        )

    @staticmethod
    def _format_conversation(messages: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            lines.append(f"<|{role}|>\n{content}<|endoftext|>")
        lines.append("<|assistant|>")
        return "\n".join(lines)
