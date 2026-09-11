"""Local OpenAI-compatible server authentication.

Targets the OpenAI-compatible REST surface exposed by local inference
servers (LM Studio, llama.cpp ``/v1``, ollama with the OpenAI shim,
vLLM, text-generation-webui, etc.).  By default these servers do not
require authentication; some deployments enable an optional bearer
token which is honoured when present.

Key resolution
--------------

1. ``api_key`` keyword argument.
2. ``LOCAL_API_KEY`` environment variable.
3. ``client_id`` (convenience for callers using the base class).

Because local servers have no concept of a user account, the OAuth
methods raise :class:`AuthConfigError` and :meth:`is_authenticated`
always returns ``True`` when no API key is required.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from zeloo_cli.auth.base import AuthConfigError, AuthError, BaseAuth, TokenResponse, UserInfo
from zeloo_cli.auth.registry import register_auth

logger = logging.getLogger(__name__)


class LocalAuth(BaseAuth):
    """Authenticate with a local OpenAI-compatible server (LM Studio, etc.)."""

    provider_name: str = "local"

    DEFAULT_API_BASE = "http://localhost:1234/v1"

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        api_key: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(client_id=client_id, client_secret=client_secret, **kwargs)
        self.api_key: str = (
            api_key
            or os.environ.get("LOCAL_API_KEY", "")
            or client_id
            or client_secret
        )
        self.api_base: str = self.config.get("api_base", self.DEFAULT_API_BASE)
        self.require_auth: bool = bool(self.config.get("require_auth", False))

    def _resolved_api_key(self) -> str:
        """Return the bearer token or ``""`` when the server allows anonymous calls."""
        if self.api_key:
            return self.api_key
        from zeloo_cli.auth.token_store import TokenStore

        stored = TokenStore().load(self.provider_name)
        if stored and stored.get("access_token"):
            return str(stored["access_token"])
        return ""

    def is_authenticated(self) -> bool:
        """Local servers are always considered authenticated.

        A bearer token is optional; when ``require_auth`` is set the
        caller should still verify a key has been configured separately.
        """
        if self.require_auth and not self._resolved_api_key():
            return False
        return True

    def get_auth_url(
        self,
        redirect_uri: str,
        state: str = "",
        **kwargs: Any,
    ) -> str:
        """Local servers have no OAuth flow."""
        raise AuthConfigError(
            "Local inference servers do not support OAuth. "
            "If your server is protected, set LOCAL_API_KEY (or `api_key` "
            "in config) and `require_auth: true`."
        )

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenResponse:
        """OAuth is not applicable to local inference servers."""
        raise AuthConfigError(
            "Local inference servers do not support authorization-code exchange."
        )

    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        """Refresh tokens are not applicable to local inference servers."""
        raise AuthConfigError(
            "Local inference servers do not support refresh tokens. "
            "Set a static LOCAL_API_KEY if the server requires authentication."
        )

    async def get_user_info(self, access_token: str) -> UserInfo:
        """Return a placeholder user profile for the local server."""
        return UserInfo(
            provider=self.provider_name,
            user_id="local-user",
            email=None,
            name="Local User",
            username="local",
            avatar_url=None,
            raw={"api_base": self.api_base},
        )

    async def call_api(
        self,
        path: str,
        method: str = "POST",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Convenience helper to make an HTTP call to the local server."""
        import httpx

        api_key = self._resolved_api_key()
        url = f"{self.api_base.rstrip('/')}{path}"
        headers = dict(kwargs.pop("headers", {}))
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        headers.setdefault("Content-Type", "application/json")
        timeout = kwargs.pop("timeout", 60.0)
        # Local servers occasionally hang on cold model loads — bump
        # the default connect timeout slightly above the read timeout
        # so transient network setup does not surface as a hard error.
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(method, url, headers=headers, **kwargs)
        if resp.status_code >= 400:
            raise AuthError(
                f"Local API error: HTTP {resp.status_code}: {resp.text[:200]}"
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise AuthError("Local API returned non-JSON") from exc


register_auth("local", LocalAuth)


__all__ = ["LocalAuth"]
