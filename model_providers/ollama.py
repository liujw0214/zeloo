"""Ollama provider — local/self-hosted LLM inference."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from model_providers.base import ChatResponse, ProviderProfile


@dataclass
class OllamaProvider(ProviderProfile):
    """Ollama local inference provider.

    Connects to a local or remote Ollama server for self-hosted inference.
    Supports thousands of open-source models (Llama, Mistral, Phi, Gemma, etc.).
    """

    name: str = "ollama"
    base_url: str = "http://localhost:11434"
    default_model: str = "llama3.3"
    supports_vision: bool = True
    supports_function_calling: bool = False
    supports_streaming: bool = True

    MODELS = {
        "llama3.3": "llama3.3",
        "llama3.1": "llama3.1",
        "llama3.2": "llama3.2",
        "mistral": "mistral",
        "mixtral": "mixtral",
        "phi3": "phi3",
        "gemma2": "gemma2",
        "qwen2.5": "qwen2.5",
        "codellama": "codellama",
        "deepseek-coder": "deepseek-coder",
    }

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        base_url = os.environ.get("OLLAMA_BASE_URL", self.base_url)
        model = model or self.default_model

        formatted_messages = []
        for msg in messages:
            formatted_messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
            })

        body: dict[str, Any] = {
            "model": model,
            "messages": formatted_messages,
            "stream": kwargs.get("stream", False),
        }
        if kwargs.get("temperature"):
            body["temperature"] = kwargs["temperature"]
        if kwargs.get("max_tokens"):
            body["options"] = {"num_predict": kwargs["max_tokens"]}
        if kwargs.get("system"):
            body["system"] = kwargs["system"]

        endpoint = f"{base_url}/api/chat"

        with httpx.Client(timeout=300.0) as client:
            response = client.post(endpoint, json=body)
            response.raise_for_status()
            data = response.json()

        content = data.get("message", {}).get("content", "")
        eval_count = data.get("eval_count", 0)
        prompt_count = data.get("prompt_eval_count", 0)

        return ChatResponse(
            content=content,
            model=data.get("model", model),
            provider=self.name,
            usage={
                "prompt_tokens": prompt_count,
                "completion_tokens": eval_count,
                "total_tokens": prompt_count + eval_count,
            },
            raw=data,
        )

    def validate_credentials(self) -> bool:
        base_url = os.environ.get("OLLAMA_BASE_URL", self.base_url)
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return 0.0

    def list_models(self) -> list[str]:
        base_url = os.environ.get("OLLAMA_BASE_URL", self.base_url)
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(f"{base_url}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []
