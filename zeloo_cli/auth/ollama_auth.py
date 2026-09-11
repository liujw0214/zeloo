"""Ollama authentication.

Ollama is a self-hosted inference server that traditionally requires
no authentication.  Enterprise deployments and reverse proxies may
gate the API behind an API key, so this provider treats the API key
as **optional**.

When no key is configured the provider still exposes ``call_api`` —
callers can reach a local Ollama instance anonymously.  OAuth
methods are not applicable for Ollama and raise :class:`AuthError`.

Key resolution
--------------

1. ``api_key`` keyword argument.
2. ``OLLAMA_API_KEY`` environment variable.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlencode

from zeloo_cli.auth.base import (
    AuthConfigError,
    AuthError,
    BaseAuth,
    TokenResponse,
    UserInfo,
)
from zeloo_cli.auth.registry import register_auth

logger = logging.getLogger(__name__)


class OllamaAuth(BaseAuth):
    """Authenticate with a (local) Ollama server; API key is optional."""

    provider_name: str = "ollama"

    DEFAULT_API_BASE = "http://localhost:11434/v1"

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        api_key: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Store the optional Ollama API key and base URL.

        Args:
            client_id: Unused; accepted for API uniformity.
            client_secret: Unused; accepted for API uniformity.
            api_key: Optional API key for protected Ollama deployments.
                Falls back to ``OLLAMA_API_KEY`` when ``None``.
            **kwargs: Forwarded to :class:`BaseAuth``.  Recognised keys:
                ``api_base`` (default ``http://localhost:11434/v1``).
        """
        super().__init__(client_id=client_id, client_secret=client_secret, **kwargs)
        self.api_key: str = api_key or os.environ.get("OLLAMA_API_KEY", "")
        self.api_base: str = self.config.get("api_base", self.DEFAULT_API_BASE)

    def _resolved_api_key(self) -> str:
        # Ollama allows anonymous access; we only return the key when
        # one is explicitly configured.  ``call_api`` handles the
        # empty-string case by omitting the Authorization header.
        return self.api_key

    def is_authenticated(self) -> bool:
        # Ollama is "always authenticated" in the sense that the
        # local server is reachable without credentials.  This lets
        # the CLI's status command render a green check without
        # demanding a token first.
        return True

    def get_auth_url(
        self,
        redirect_uri: str,
        state: str = "",
        **kwargs: Any,
    ) -> str:
        """Return a placeholder URL — Ollama does not support OAuth."""
        params: dict[str, str] = {"redirect_uri": redirect_uri}
        if state:
            params["state"] = state
        return f"{self.api_base.rstrip('/')}/auth?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenResponse:
        """OAuth is not applicable for Ollama; return an empty token."""
        return TokenResponse(
            access_token="",
            token_type="Bearer",
            refresh_token=None,
            expires_in=None,
            scope="",
            extras={"stub": True, "code": code, "redirect_uri": redirect_uri},
        )

    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        """OAuth is not applicable for Ollama; raise :class:`AuthError`."""
        raise AuthError("Ollama does not support OAuth refresh tokens")

    async def get_user_info(self, access_token: str) -> UserInfo:
        """Return a minimal local user record for Ollama."""
        return UserInfo(
            provider=self.provider_name,
            user_id="ollama-local",
            email=None,
            name="Ollama Local User",
            username=None,
            avatar_url=None,
            raw={"api_base": self.api_base},
        )

    async def call_api(
        self,
        path: str,
        method: str = "POST",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Convenience helper to call the Ollama HTTP API.

        The ``Authorization`` header is only attached when an API key
        is configured, so anonymous local Ollama deployments keep
        working out of the box.
        """
        import httpx

        url = f"{self.api_base.rstrip('/')}{path}"
        headers = dict(kwargs.pop("headers", {}))
        api_key = self._resolved_api_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        headers.setdefault("Content-Type", "application/json")
        headers.setdefault("Accept", "application/json")
        async with httpx.AsyncClient(timeout=kwargs.pop("timeout", 120.0)) as client:
            resp = await client.request(method, url, headers=headers, **kwargs)
        if resp.status_code >= 400:
            raise AuthError(
                f"Ollama API error: HTTP {resp.status_code}: {resp.text[:200]}"
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise AuthError("Ollama API returned non-JSON") from exc


register_auth("ollama", OllamaAuth)


__all__ = ["OllamaAuth"]
