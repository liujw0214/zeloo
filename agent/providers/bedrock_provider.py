"""AWS Bedrock provider.

Uses AWS SigV4 signing for authentication.
Provides access to foundation models on AWS Bedrock including
Amazon Titan, Claude, Llama, Mistral, and other providers.

Configuration keys (in ``config`` dict):

* ``aws_region`` (str) — AWS region, e.g. ``us-east-1``. Falls back
  to ``AWS_REGION`` or ``AWS_DEFAULT_REGION``.
* ``aws_access_key_id`` (str) — AWS access key ID. Falls back to
  ``AWS_ACCESS_KEY_ID``.
* ``aws_secret_access_key`` (str) — AWS secret access key. Falls back
  to ``AWS_SECRET_ACCESS_KEY``.
* ``aws_session_token`` (str) — Optional session token for temporary
  credentials. Falls back to ``AWS_SESSION_TOKEN``.
* ``default_model`` (str) — Defaults to ``anthropic.claude-3-5-sonnet-20241022-v2:0``.
* ``timeout`` (float) — Request timeout in seconds.

The provider registers itself as ``"bedrock"`` on import.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import json
import logging
import os
from typing import Any

from agent.providers._http import (
    async_post_json,
    build_error_response,
    build_success_response,
)
from agent.providers.base import BaseProvider
from agent.providers.registry import register_provider

logger = logging.getLogger(__name__)


_DEFAULT_REGION = "us-east-1"
_DEFAULT_MODEL = "anthropic.claude-3-5-sonnet-20241022-v2:0"

BedrockKnownModels = tuple[str, ...]
_KNOWN_BEDROCK_MODELS: BedrockKnownModels = (
    "anthropic.claude-3-5-sonnet-20241022-v2:0",
    "anthropic.claude-3-5-sonnet-20240620-v1:0",
    "anthropic.claude-3-opus-20240229-v1:0",
    "anthropic.claude-3-sonnet-20240229-v1:0",
    "anthropic.claude-3-haiku-20240307-v1:0",
    "anthropic.claude-2.1",
    "anthropic.claude-2",
    "amazon.titan-text-premier-v1:0",
    "amazon.titan-text-express-v1",
    "amazon.titan-text-lite-v1",
    "meta.llama3-1-70b-instruct-v1:0",
    "meta.llama3-1-8b-instruct-v1:0",
    "meta.llama3-70b-instruct-v1:0",
    "meta.llama3-8b-instruct-v1:0",
    "mistral.mistral-large-2407-v1:0",
    "mistral.mistral-7b-instruct-v0:2",
    "mistral.mixtral-8x7b-instruct-v0:1",
    "ai21.jamba-1-5-mini-v1:0",
    "ai21.jamba-1-5-large-v1:0",
    "cohere.command-r-plus-v1:0",
    "cohere.command-r-v1:0",
    "stability.stable-diffusion-xl-fast",
    "stability.stable-diffusion-xl-v1",
)


class BedrockProvider(BaseProvider):
    """AWS Bedrock provider.

    Provides access to foundation models on AWS Bedrock using AWS
    SigV4 authentication. Supports Claude, Llama, Mistral, Titan,
    and other models available on Bedrock.
    """

    name = "bedrock"
    default_model = _DEFAULT_MODEL
    supports_vision = True
    supports_function_calling = True
    supports_streaming = True

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        if not self.config.get("aws_region"):
            self.config["aws_region"] = (
                os.environ.get("AWS_REGION")
                or os.environ.get("AWS_DEFAULT_REGION")
                or _DEFAULT_REGION
            )
        if not self.config.get("aws_access_key_id"):
            self.config["aws_access_key_id"] = os.environ.get("AWS_ACCESS_KEY_ID", "")
        if not self.config.get("aws_secret_access_key"):
            self.config["aws_secret_access_key"] = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
        if not self.config.get("aws_session_token"):
            self.config["aws_session_token"] = os.environ.get("AWS_SESSION_TOKEN", "")

    @property
    def aws_region(self) -> str:
        return str(self.config.get("aws_region") or _DEFAULT_REGION)

    @property
    def aws_access_key_id(self) -> str:
        return str(self.config.get("aws_access_key_id") or "")

    @property
    def aws_secret_access_key(self) -> str:
        return str(self.config.get("aws_secret_access_key") or "")

    @property
    def aws_session_token(self) -> str:
        return str(self.config.get("aws_session_token") or "")

    def _get_credentials(self) -> tuple[str, str, str]:
        access_key = self.aws_access_key_id
        secret_key = self.aws_secret_access_key
        session_token = self.aws_session_token
        return access_key, secret_key, session_token

    def _sign(
        self,
        key: bytes,
        msg: str,
    ) -> bytes:
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    def _get_signature_key(
        self,
        secret_key: str,
        date_stamp: str,
        region: str,
        service: str,
    ) -> bytes:
        k_date = self._sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
        k_region = self._sign(k_date, region)
        k_service = self._sign(k_region, service)
        k_signing = self._sign(k_service, "aws4_request")
        return k_signing

    def _aws_sigv4_headers(
        self,
        method: str,
        url: str,
        body: str,
        service: str = "bedrock",
    ) -> dict[str, str]:
        access_key, secret_key, session_token = self._get_credentials()
        if not access_key or not secret_key:
            return {}

        parsed = self._parse_url(url)
        host = parsed["host"]
        uri = parsed["uri"]
        querystring = parsed["querystring"]

        t = datetime.datetime.utcnow()
        amz_date = t.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = t.strftime("%Y%m%d")

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Host": host,
            "X-Amz-Date": amz_date,
        }
        if session_token:
            headers["X-Amz-Security-Token"] = session_token

        payload_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        headers["X-Amz-Content-Sha256"] = payload_hash

        signed_headers = "content-type;host;x-amz-content-sha256;x-amz-date"
        if session_token:
            signed_headers += ";x-amz-security-token"

        algorithm = "AWS4-HMAC-SHA256"
        credential_scope = f"{date_stamp}/{self.aws_region}/{service}/aws4_request"
        canonical_querystring = querystring

        canonical_headers = (
            f"content-type:{headers['Content-Type']}\n"
            f"host:{host}\n"
            f"x-amz-content-sha256:{payload_hash}\n"
            f"x-amz-date:{amz_date}\n"
        )
        if session_token:
            canonical_headers += f"x-amz-security-token:{session_token}\n"

        canonical_request = (
            f"{method}\n{uri}\n{canonical_querystring}\n"
            f"{canonical_headers}\n{signed_headers}\n{payload_hash}"
        )
        string_to_sign = (
            f"{algorithm}\n{amz_date}\n{credential_scope}\n"
            f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
        )
        signing_key = self._get_signature_key(
            secret_key, date_stamp, self.aws_region, service
        )
        signature = hmac.new(
            signing_key,
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        auth_header = (
            f"{algorithm} Credential={access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        headers["Authorization"] = auth_header
        return headers

    @staticmethod
    def _parse_url(url: str) -> dict[str, str]:
        import re
        match = re.match(r"https?://([^/]+)(/[^?]*)(\?.*)?", url)
        if match:
            host = match.group(1)
            uri = match.group(2) or "/"
            querystring = match.group(3) or ""
            if querystring:
                querystring = querystring.lstrip("?")
            return {"host": host, "uri": uri, "querystring": querystring}
        return {"host": "", "uri": "/", "querystring": ""}

    def _get_endpoint(self) -> str:
        return f"https://bedrock.{self.aws_region}.amazonaws.com"

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        access_key, secret_key, _ = self._get_credentials()
        if not access_key or not secret_key:
            return build_error_response(
                provider=self.name,
                error="AWS credentials not configured (set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY)",
                status=401,
            )

        target_model = model or self.default_model
        payload: dict[str, Any] = {
            "messages": messages,
            "anthropic_version": "bedrock-2023-05-31",
        }

        is_claude = target_model.startswith("anthropic.")
        if is_claude:
            payload["max_tokens"] = int(max_tokens)
            if temperature > 0:
                payload["temperature"] = float(temperature)
        else:
            payload["max_tokens"] = int(max_tokens)
            payload["temperature"] = float(temperature)

        passthrough_keys = (
            "top_p",
            "top_k",
            "stop_sequences",
            "system",
        )
        for key in passthrough_keys:
            if key in kwargs and kwargs[key] is not None:
                payload[key] = kwargs[key]

        body_str = json.dumps(payload)
        endpoint = self._get_endpoint()
        url = f"{endpoint}/model/{target_model}/invoke"
        if stream:
            url = f"{endpoint}/model/{target_model}/invoke-with-response-stream"

        headers = self._aws_sigv4_headers("POST", url, body_str)
        if not headers:
            return build_error_response(
                provider=self.name,
                error="Failed to generate AWS signature",
                status=401,
            )

        result = await async_post_json(
            url,
            headers=headers,
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
        content = ""
        finish_reason = "stop"
        usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        tool_calls: list[dict[str, Any]] = []

        if is_claude:
            stop_reason = body.get("stop_reason", "end_turn")
            finish_reason = stop_reason if stop_reason else "stop"
            output_blocks = body.get("content", []) or []
            text_parts = []
            for block in output_blocks:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(str(block.get("text", "")))
                    elif block.get("type") == "tool_use":
                        tool_calls.append({
                            "id": str(block.get("id", "")),
                            "type": "function",
                            "function": {
                                "name": str(block.get("name", "")),
                                "arguments": json.dumps(block.get("input", {})),
                            },
                        })
            content = "".join(text_parts)
            usage_meta = body.get("usage", {}) or {}
            usage = {
                "prompt_tokens": int(usage_meta.get("input_tokens", 0) or 0),
                "completion_tokens": int(usage_meta.get("output_tokens", 0) or 0),
                "total_tokens": int(
                    (usage_meta.get("input_tokens", 0) or 0)
                    + (usage_meta.get("output_tokens", 0) or 0)
                ),
            }
        else:
            choices = body.get("choices", []) or []
            if choices:
                choice = choices[0]
                message = choice.get("message", {}) or {}
                content = str(message.get("content", ""))
                finish_reason = str(choice.get("finish_reason", "stop") or "stop")
                tool_calls = message.get("tool_calls", []) or []
            usage_raw = body.get("usage", {}) or {}
            usage = {
                "prompt_tokens": int(usage_raw.get("prompt_tokens", 0) or 0),
                "completion_tokens": int(usage_raw.get("completion_tokens", 0) or 0),
                "total_tokens": int(usage_raw.get("total_tokens", 0) or 0),
            }

        return build_success_response(
            provider=self.name,
            content=content,
            model=target_model,
            finish_reason=finish_reason,
            usage=usage,
            raw=body,
            tool_calls=tool_calls if isinstance(tool_calls, list) else [],
        )

    def list_models(self) -> list[str]:
        return list(_KNOWN_BEDROCK_MODELS)

    def is_available(self) -> bool:
        access_key, secret_key, _ = self._get_credentials()
        if not access_key or not secret_key:
            return False
        return True


register_provider("bedrock", BedrockProvider)


__all__ = ["BedrockProvider"]
