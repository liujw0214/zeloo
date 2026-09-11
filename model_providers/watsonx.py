"""IBM Watsonx.ai provider — enterprise AI from IBM."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from model_providers.base import ChatResponse, ProviderProfile


@dataclass
class WatsonxProvider(ProviderProfile):
    """IBM Watsonx.ai inference provider.

    Provides access to IBM Granite and Llama models
    via Watsonx.ai enterprise platform.
    """

    name: str = "watsonx"
    base_url: str = "https://us-south.ml.cloud.ibm.com"
    default_model: str = "ibm/granite-34b-code-instruct"
    supports_vision: bool = False
    supports_function_calling: bool = True
    supports_streaming: bool = True

    MODELS = {
        "ibm/granite-34b-code-instruct": "ibm/granite-34b-code-instruct",
        "ibm/granite-8b-code-instruct": "ibm/granite-8b-code-instruct",
        "meta-llama/llama-3-3-70b-instruct": "meta-llama/llama-3-3-70b-instruct",
        "meta-llama/llama-3-1-8b-instruct": "meta-llama/llama-3-1-8b-instruct",
    }

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        api_key = os.environ.get("WATSONX_API_KEY", "")
        project_id = os.environ.get("WATSONX_PROJECT_ID", "")
        if not api_key or not project_id:
            raise ValueError(
                "WATSONX_API_KEY and WATSONX_PROJECT_ID "
                "environment variables must be set"
            )

        token_url = "https://iam.cloud.ibm.com/identity/token"
        token_resp = httpx.post(
            token_url,
            data={
                "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                "apikey": api_key,
            },
            timeout=10.0,
        )
        token_resp.raise_for_status()
        token = token_resp.json()["access_token"]

        endpoint = "https://us-south.ml.cloud.ibm.com/ml/v1/text/generation"
        model = model or self.default_model

        body: dict[str, Any] = {
            "model_id": model,
            "project_id": project_id,
            "messages": messages,
        }
        if kwargs.get("temperature"):
            body["parameters"] = {"temperature": kwargs["temperature"]}
        if kwargs.get("max_tokens"):
            body.setdefault("parameters", {})["max_new_tokens"] = kwargs["max_tokens"]

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=120.0) as client:
            response = client.post(endpoint, json=body, headers=headers)
            response.raise_for_status()
            data = response.json()

        results = data.get("results", [])
        content = results[0].get("generated_text", "") if results else ""

        return ChatResponse(
            content=content,
            model=model,
            provider=self.name,
            usage={
                "prompt_tokens": data.get("usage", {}).get("prompt_tokens", 0),
                "completion_tokens": data.get("usage", {}).get("completion_tokens", 0),
                "total_tokens": data.get("usage", {}).get("total_tokens", 0),
            },
            raw=data,
        )

    def validate_credentials(self) -> bool:
        api_key = os.environ.get("WATSONX_API_KEY", "")
        if not api_key:
            return False
        try:
            token_url = "https://iam.cloud.ibm.com/identity/token"
            resp = httpx.post(
                token_url,
                data={
                    "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                    "apikey": api_key,
                },
                timeout=10.0,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (prompt_tokens * 0.00015 + completion_tokens * 0.0006) / 1000.0
