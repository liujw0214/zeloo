"""AI Horde provider — distributed open AI inference."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from model_providers.base import ChatResponse, ProviderProfile


@dataclass
class AIHordeProvider(ProviderProfile):
    """AI Horde distributed inference provider.

    Provides free distributed inference via the AI Horde network.
    KoboldCPP-compatible API format.
    """

    name: str = "ai-horde"
    base_url: str = "https://horde.ai/api/v2"
    default_model: str = "koboldcpp-llama"
    supports_vision: bool = False
    supports_function_calling: bool = False
    supports_streaming: bool = True

    MODELS = {
        "koboldcpp-llama": "koboldcpp-llama",
        "koboldcpp-mistral": "koboldcpp-mistral",
        "llama-3.1-70b": "llama-3.1-70b",
        "llama-3.1-8b": "llama-3.1-8b",
    }

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        api_key = os.environ.get("AI_HORDE_API_KEY", "0000000000")
        model = model or self.default_model

        prompt = self._build_prompt(messages)

        endpoint = f"{self.base_url}/text/async"

        body: dict[str, Any] = {
            "prompt": prompt,
            "models": [model],
            "api_key": api_key,
        }
        if kwargs.get("temperature"):
            body["temperature"] = kwargs["temperature"]
        if kwargs.get("max_tokens"):
            body["max_length"] = kwargs["max_tokens"]

        headers = {"Content-Type": "application/json"}

        with httpx.Client(timeout=300.0) as client:
            response = client.post(endpoint, json=body, headers=headers)
            response.raise_for_status()
            data = response.json()

        job_id = data.get("id", "")
        poll_url = f"{self.base_url}/text/status/{job_id}"

        for _ in range(60):
            with httpx.Client(timeout=10.0) as poll_client:
                poll_resp = poll_client.get(poll_url, headers=headers)
                poll_resp.raise_for_status()
                status = poll_resp.json()
                if status.get("done"):
                    generations = status.get("generations", [])
                    content = generations[0].get("text", "") if generations else ""
                    return ChatResponse(
                        content=content,
                        model=model,
                        provider=self.name,
                        usage={
                            "prompt_tokens": status.get("prompt_count", 0),
                            "completion_tokens": status.get("gen_first", 0),
                            "total_tokens": 0,
                        },
                        raw=status,
                    )
            import time
            time.sleep(2)

        return ChatResponse(
            content="Request timed out",
            model=model,
            provider=self.name,
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            raw={},
        )

    def _build_prompt(self, messages: list[dict[str, Any]]) -> str:
        parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                parts.append(f"<|user|>\n{content}")
            elif role == "assistant":
                parts.append(f"<|assistant|>\n{content}")
            elif role == "system":
                parts.append(f"<|system|>\n{content}")
        parts.append("<|assistant|>")
        return "\n".join(parts)

    def validate_credentials(self) -> bool:
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(f"{self.base_url}/status/models")
                return resp.status_code == 200
        except Exception:
            return False

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return 0.0
