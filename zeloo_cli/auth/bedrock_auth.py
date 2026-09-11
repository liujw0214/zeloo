"""AWS Bedrock authentication via SigV4 request signing.

Bedrock uses AWS Signature Version 4 (``AWS4-HMAC-SHA256``) rather
than bearer tokens or API keys.  This module reads the standard AWS
environment variables, builds the canonical request, and emits the
``Authorization`` header expected by ``bedrock-runtime``.

Credential resolution
---------------------

* ``AWS_ACCESS_KEY_ID``  → ``client_id``
* ``AWS_SECRET_ACCESS_KEY`` → ``client_secret``
* ``AWS_SESSION_TOKEN``  → ``api_key`` (for STS / role-assumed creds)

The signing region is taken from ``AWS_REGION`` (falling back to
``AWS_DEFAULT_REGION``) and may be overridden via ``config.region``.
The service name is hard-coded to ``bedrock`` because every Bedrock
runtime call uses the same signing key.

SigV4 reference: https://docs.aws.amazon.com/general/latest/gr/sigv4_signing.html
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlparse

from zeloo_cli.auth.base import AuthConfigError, AuthError, BaseAuth, TokenResponse, UserInfo
from zeloo_cli.auth.registry import register_auth

logger = logging.getLogger(__name__)


class BedrockAuth(BaseAuth):
    """Authenticate with AWS Bedrock using SigV4."""

    provider_name: str = "bedrock"

    DEFAULT_API_BASE = "https://bedrock-runtime.us-east-1.amazonaws.com"
    SERVICE_NAME = "bedrock"
    ALGORITHM = "AWS4-HMAC-SHA256"

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        api_key: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(client_id=client_id, client_secret=client_secret, **kwargs)
        self.access_key: str = (
            client_id or os.environ.get("AWS_ACCESS_KEY_ID", "")
        )
        self.secret_key: str = (
            client_secret or os.environ.get("AWS_SECRET_ACCESS_KEY", "")
        )
        self.session_token: str = (
            api_key or os.environ.get("AWS_SESSION_TOKEN", "")
        )
        self.region: str = (
            self.config.get("region", "")
            or os.environ.get("AWS_REGION", "")
            or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        )
        self.api_base: str = self.config.get("api_base", self.DEFAULT_API_BASE)
        self.model_id: str = self.config.get("model_id", "")

    def is_authenticated(self) -> bool:
        """A Bedrock caller is authenticated if both key id and secret are set."""
        return bool(self.access_key and self.secret_key)

    def get_auth_url(
        self,
        redirect_uri: str,
        state: str = "",
        **kwargs: Any,
    ) -> str:
        """Bedrock does not have a user-facing OAuth flow."""
        raise AuthConfigError(
            "AWS Bedrock uses IAM credentials, not OAuth. "
            "Configure AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (and "
            "optionally AWS_SESSION_TOKEN) instead."
        )

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenResponse:
        """OAuth is not applicable to Bedrock."""
        raise AuthConfigError(
            "AWS Bedrock does not support authorization-code exchange. "
            "Use IAM credentials (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY)."
        )

    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        """AWS handles credential rotation via STS — not via OAuth refresh."""
        raise AuthConfigError(
            "AWS Bedrock does not support OAuth refresh tokens. "
            "Re-fetch credentials from your identity provider (STS, SSO, "
            "etc.) and re-instantiate the provider."
        )

    async def get_user_info(self, access_token: str) -> UserInfo:
        """Return a placeholder user profile based on the IAM principal."""
        return UserInfo(
            provider=self.provider_name,
            user_id=self.access_key or "bedrock-principal",
            email=None,
            name=None,
            username=self.access_key or None,
            avatar_url=None,
            raw={"region": self.region, "service": self.SERVICE_NAME},
        )

    # ── SigV4 helpers ─────────────────────────────────────────────

    @staticmethod
    def _sha256_hex(data: bytes | str) -> str:
        if isinstance(data, str):
            data = data.encode("utf-8")
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _hmac_sha256(key: bytes, data: bytes | str) -> bytes:
        if isinstance(data, str):
            data = data.encode("utf-8")
        return hmac.new(key, data, hashlib.sha256).digest()

    def _derive_signing_key(self, date_stamp: str) -> bytes:
        """Build the SigV4 signing key from the secret access key."""
        k_date = self._hmac_sha256(f"AWS4{self.secret_key}".encode("utf-8"), date_stamp)
        k_region = self._hmac_sha256(k_date, self.region)
        k_service = self._hmac_sha256(k_region, self.SERVICE_NAME)
        k_signing = self._hmac_sha256(k_service, "aws4_request")
        return k_signing

    def _sign_request(
        self,
        method: str,
        url: str,
        body: str = "",
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Compute SigV4 headers for a Bedrock request.

        Args:
            method: HTTP verb (``POST`` for InvokeModel).
            url: Full URL including query string.
            body: Raw request body (must match what is sent on the wire).
            extra_headers: Caller-supplied headers to include in the
                signature (kept verbatim; values are trimmed).

        Returns:
            A dictionary of headers to send with the request.
        """
        if not (self.access_key and self.secret_key):
            raise AuthConfigError(
                "AWS Bedrock credentials missing. "
                "Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY."
            )

        parsed = urlparse(url)
        host = parsed.netloc
        path = parsed.path or "/"
        canonical_querystring = self._canonical_query(parsed.query)

        now = datetime.now(timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")

        content_hash = self._sha256_hex(body)

        headers: dict[str, str] = {
            "host": host,
            "x-amz-date": amz_date,
            "x-amz-content-sha256": content_hash,
        }
        if self.session_token:
            headers["x-amz-security-token"] = self.session_token
        if extra_headers:
            for key, value in extra_headers.items():
                headers[key.lower()] = value.strip() if isinstance(value, str) else str(value)
            if "content-type" not in {k.lower() for k in extra_headers}:
                pass

        signed_headers_list = sorted(headers.items())
        signed_headers = ";".join(name for name, _ in signed_headers_list)

        canonical_headers = "".join(f"{name}:{value}\n" for name, value in signed_headers_list)

        canonical_request = "\n".join(
            [
                method.upper(),
                quote(path, safe="/~"),
                canonical_querystring,
                canonical_headers,
                signed_headers,
                content_hash,
            ]
        )

        credential_scope = f"{date_stamp}/{self.region}/{self.SERVICE_NAME}/aws4_request"
        string_to_sign = "\n".join(
            [
                self.ALGORITHM,
                amz_date,
                credential_scope,
                self._sha256_hex(canonical_request),
            ]
        )

        signing_key = self._derive_signing_key(date_stamp)
        signature = hmac.new(
            signing_key, string_to_sign.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        authorization = (
            f"{self.ALGORITHM} "
            f"Credential={self.access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, "
            f"Signature={signature}"
        )

        result: dict[str, str] = {
            "Authorization": authorization,
            "X-Amz-Date": amz_date,
            "X-Amz-Content-Sha256": content_hash,
            "Host": host,
        }
        if self.session_token:
            result["X-Amz-Security-Token"] = self.session_token
        return result

    @staticmethod
    def _canonical_query(raw_query: str) -> str:
        """Return a SigV4-style canonicalised query string."""
        if not raw_query:
            return ""
        pairs: list[tuple[str, str]] = []
        for chunk in raw_query.split("&"):
            if not chunk:
                continue
            if "=" in chunk:
                k, v = chunk.split("=", 1)
            else:
                k, v = chunk, ""
            pairs.append((quote(k, safe="~"), quote(v, safe="~")))
        pairs.sort()
        return "&".join(f"{k}={v}" for k, v in pairs)

    async def call_api(
        self,
        path: str,
        method: str = "POST",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Make a SigV4-signed Bedrock InvokeModel-style request."""
        import httpx

        base = self.api_base.rstrip("/")
        url = f"{base}{path}"
        body = kwargs.pop("content", "")
        extra_headers = kwargs.pop("headers", None) or {}
        extra_headers.setdefault("Content-Type", "application/json")
        signed = self._sign_request(method, url, body, extra_headers)
        merged = dict(extra_headers)
        merged.update(signed)
        async with httpx.AsyncClient(timeout=kwargs.pop("timeout", 60.0)) as client:
            resp = await client.request(method, url, headers=merged, content=body, **kwargs)
        if resp.status_code >= 400:
            raise AuthError(
                f"Bedrock API error: HTTP {resp.status_code}: {resp.text[:200]}"
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise AuthError("Bedrock API returned non-JSON") from exc


register_auth("bedrock", BedrockAuth)


__all__ = ["BedrockAuth"]
