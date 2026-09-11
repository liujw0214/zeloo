"""AWS Bedrock transport adapter."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime
from typing import Any

import httpx

from agent.transports.base import (
    AuthenticationError,
    RateLimitError,
    Response,
    TransportAdapter,
    TransportError,
)

logger = logging.getLogger(__name__)

BEDROCK_BASE_URL = "https://bedrock.{region}.amazonaws.com"


class BedrockAdapter(TransportAdapter):
    """Transport adapter for AWS Bedrock (Claude via AWS)."""

    name = "bedrock"
    supports_streaming = True
    supports_vision = True
    supports_tools = True
    max_context_tokens = 200000

    def __init__(
        self,
        aws_access_key: str,
        aws_secret_key: str,
        aws_region: str = "us-east-1",
        session_token: str | None = None,
        timeout: float = 60.0,
    ):
        self.aws_access_key = aws_access_key
        self.aws_secret_key = aws_secret_key
        self.aws_region = aws_region
        self.session_token = session_token
        self.timeout = timeout
        self._base_url = BEDROCK_BASE_URL.format(region=aws_region)

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str = "anthropic.claude-3-5-sonnet-20241022-v1:0",
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> Response:
        payload = self._build_payload(messages, model, tools, **kwargs)
        try:
            raw = self._post(model, payload)
            return self._parse_response(raw, model)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise AuthenticationError("Invalid AWS credentials") from e
            if e.response.status_code == 429:
                raise RateLimitError("Bedrock rate limit exceeded") from e
            raise TransportError(f"Bedrock API error: {e}") from e

    def validate_credentials(self) -> bool:
        try:
            import importlib.util
            spec = importlib.util.find_spec("botocore")
            return spec is not None
        except Exception:
            logger.warning("boto3/botocore not installed - skipping AWS validation")
            return True

    def get_default_model(self) -> str:
        return "anthropic.claude-3-5-sonnet-20241022-v1:0"

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        from agent.transports.anthropic_adapter import AnthropicAdapter

        base = AnthropicAdapter.__new__(AnthropicAdapter)
        base.api_key = ""
        base.base_url = ""
        converted_messages = base._convert_messages(messages)

        payload: dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "messages": converted_messages,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.0),
        }
        if tools:
            converted_tools = [
                {
                    "name": f.get("name", ""),
                    "description": f.get("description", ""),
                    "input_schema": f.get("parameters", {"type": "object", "properties": {}}),
                }
                for tool in tools
                for f in [tool.get("function", {})]
            ]
            payload["tools"] = converted_tools
        return payload

    def _parse_response(self, raw: dict[str, Any], model: str) -> Response:
        content = ""
        tool_calls: list[dict[str, Any]] = []
        finish_reason = raw.get("stop_reason", "")
        usage = raw.get("usage", {})

        for block in raw.get("content", []):
            if block.get("type") == "text":
                content += block.get("text", "")
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {})),
                    },
                })

        return Response(
            content=content,
            raw=raw,
            model=model,
            finish_reason=finish_reason,
            usage_in=usage.get("input_tokens", 0),
            usage_out=usage.get("output_tokens", 0),
            tool_calls=tool_calls,
        )

    def _post(self, model: str, payload: dict[str, Any]) -> dict[str, Any]:
        from agent.transports.anthropic_adapter import AnthropicAdapter

        base = AnthropicAdapter.__new__(AnthropicAdapter)
        base.api_key = ""
        base.base_url = ""
        converted = base._convert_messages([{"role": "user", "content": "ping"}])
        body = json.dumps({"messages": converted, "max_tokens": 1}).encode()
        url = f"{self._base_url}/model/{model}/invoke"
        signed = self._sign_request("POST", url, body)
        headers = {
            "content-type": "application/json",
            "x-amz-date": signed["x-amz-date"],
            "Authorization": signed["Authorization"],
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, content=body, headers=headers)
            resp.raise_for_status()
            return json.loads(resp.text)

    def _sign_request(
        self, method: str, url: str, body: bytes
    ) -> dict[str, str]:
        now = datetime.utcnow()
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        region = self.aws_region

        def _sha256(data: str | bytes) -> str:
            return hashlib.sha256(
                data.encode() if isinstance(data, str) else data
            ).hexdigest()

        credential_scope = f"{date_stamp}/{region}/bedrock-ai/invoke/aws4_request"
        headers = {"host": url.split("/")[2]}
        signed_headers_str = ";".join(sorted(headers.keys()))
        payload_hash = _sha256(body)
        canonical_uri = url.split(".amazonaws.com")[1]
        canonical_querystring = ""

        canonical_headers_part = "\n".join(
            f"{k}:{v}" for k, v in sorted(headers.items())
        ) + "\n"
        canonical_request = (
            f"{method}\n{canonical_uri}\n{canonical_querystring}\n"
            f"{canonical_headers_part}{signed_headers_str}\n{payload_hash}"
        )
        string_to_sign = (
            f"AWS4-HMAC-SHA256\n{amz_date}\n{credential_scope}\n"
            f"{_sha256(canonical_request)}"
        )

        def _hmac_sha256(key: bytes, data: str) -> bytes:
            return hmac.new(key, data.encode(), hashlib.sha256).digest()

        k_date = _hmac_sha256(f"AWS4{self.aws_secret_key}".encode(), date_stamp)
        k_region = _hmac_sha256(k_date, region)
        k_service = _hmac_sha256(k_region, "bedrock-ai")
        k_signing = _hmac_sha256(k_service, "aws4_request")
        signature = _hmac_sha256(k_signing, string_to_sign).hex()

        authorization = (
            f"AWS4-HMAC-SHA256 "
            f"Credential={self.aws_access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers_str}, Signature={signature}"
        )
        return {"x-amz-date": amz_date, "Authorization": authorization}
