"""AWS Bedrock provider — Amazon Bedrock managed inference."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from model_providers.base import ChatResponse, ProviderProfile


@dataclass
class BedrockProvider(ProviderProfile):
    """AWS Bedrock managed inference provider.

    Provides access to Claude, Llama, Mistral, and other models
    via AWS Bedrock with pay-per-token pricing.
    """

    name: str = "bedrock"
    base_url: str = "https://bedrock-runtime.us-east-1.amazonaws.com"
    default_model: str = "anthropic.claude-3-5-sonnet-20240620-v1:0"
    supports_vision: bool = True
    supports_function_calling: bool = True
    supports_streaming: bool = True

    MODELS = {
        "anthropic.claude-3-5-sonnet-20240620-v1:0": "anthropic.claude-3-5-sonnet-20240620-v1:0",
        "anthropic.claude-3-opus-20240229-v1:0": "anthropic.claude-3-opus-20240229-v1:0",
        "anthropic.claude-3-sonnet-20240229-v1:0": "anthropic.claude-3-sonnet-20240229-v1:0",
        "meta.llama3-3-70b-instruct-v1:0": "meta.llama3-3-70b-instruct-v1:0",
        "mistral.mistral-large-2407-v1:0": "mistral.mistral-large-2407-v1:0",
        "amazon.titan-text-premier-v1:0": "amazon.titan-text-premier-v1:0",
    }

    def __post_init__(self) -> None:
        region = os.environ.get("AWS_REGION", "us-east-1")
        self.base_url = f"https://bedrock-runtime.{region}.amazonaws.com"

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        region = os.environ.get("AWS_REGION", "us-east-1")

        try:
            import boto3
            session = boto3.Session(region_name=region)
            credentials = session.get_credentials()
            aws_access_key = credentials.access_key
            aws_secret_key = credentials.secret_key
            aws_session_token = credentials.token
        except Exception:
            aws_access_key = os.environ.get("AWS_ACCESS_KEY_ID", "")
            aws_secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
            aws_session_token = os.environ.get("AWS_SESSION_TOKEN", "")

        if not aws_access_key or not aws_secret_key:
            raise ValueError("AWS credentials not configured")

        model = model or self.default_model
        endpoint = f"{self.base_url}/model/{model}/invoke"

        body: dict[str, Any] = {
            "messages": messages,
        }
        if kwargs.get("temperature"):
            body["temperature"] = kwargs["temperature"]
        if kwargs.get("max_tokens"):
            body["max_tokens"] = kwargs["max_tokens"]

        import json
        headers = {"Content-Type": "application/json"}

        signed = self._sign_request(
            method="POST",
            url=endpoint,
            headers=headers,
            body=json.dumps(body),
            access_key=aws_access_key,
            secret_key=aws_secret_key,
            session_token=aws_session_token,
            region=region,
        )

        with httpx.Client(timeout=120.0) as client:
            response = client.post(endpoint, json=body, headers=signed)
            response.raise_for_status()
            data = response.json()

        return ChatResponse(
            content=data.get("content", [{}])[0].get("text", ""),
            model=model,
            provider=self.name,
            usage={
                "prompt_tokens": data.get("usage", {}).get("input_tokens", 0),
                "completion_tokens": data.get("usage", {}).get("output_tokens", 0),
                "total_tokens": data.get("usage", {}).get("input_tokens", 0)
                + data.get("usage", {}).get("output_tokens", 0),
            },
            raw=data,
        )

    def _sign_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: str,
        access_key: str,
        secret_key: str,
        session_token: str,
        region: str,
    ) -> dict[str, str]:
        import datetime
        import hashlib
        import hmac

        now = datetime.datetime.utcnow()
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        host = url.split("/")[2]

        headers["x-amz-date"] = amz_date
        if session_token:
            headers["x-amz-security-token"] = session_token
        headers["x-amz-content-sha256"] = hashlib.sha256(body.encode()).hexdigest()

        signed_headers = ";".join(sorted(headers.keys()))
        payload_hash = hashlib.sha256(body.encode()).hexdigest()

        canonical_uri = "/" + "/".join(url.split("/")[3:])
        canonical_querystring = ""
        canonical_headers = f"content-type:{headers['content-type']}\nhost:{host}\nx-amz-content-sha256:{headers['x-amz-content-sha256']}\nx-amz-date:{amz_date}\n"
        if session_token:
            canonical_headers += f"x-amz-security-token:{session_token}\n"

        canonical_request = f"{method}\n{canonical_uri}\n{canonical_querystring}\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
        algorithm = "AWS4-HMAC-SHA256"
        credential_scope = f"{date_stamp}/{region}/bedrock/aws4_request"
        string_to_sign = f"{algorithm}\n{amz_date}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode()).hexdigest()}"

        k_date = hmac.new(
            ("AWS4" + secret_key).encode(), date_stamp.encode(), hashlib.sha256
        ).digest()
        k_region = hmac.new(k_date, region.encode(), hashlib.sha256).digest()
        k_service = hmac.new(k_region, b"bedrock", hashlib.sha256).digest()
        k_signing = hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()
        signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()

        auth_header = (
            f"{algorithm} Credential={access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        headers["Authorization"] = auth_header
        return headers

    def validate_credentials(self) -> bool:
        try:
            import boto3
            region = os.environ.get("AWS_REGION", "us-east-1")
            client = boto3.client("bedrock", region_name=region)
            client.list_foundation_models()
            return True
        except Exception:
            return False

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (prompt_tokens * 0.003 + completion_tokens * 0.015) / 1000.0
