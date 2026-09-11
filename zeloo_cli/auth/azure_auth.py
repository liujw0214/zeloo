"""Azure OpenAI / Azure AI Foundry authentication.

Azure exposes the OpenAI REST contract (``/chat/completions``, etc.)
under three distinct authentication flavours.  This module picks the
right one at construction time so that downstream callers can use a
single :meth:`call_api` regardless of the deployment's auth model.

Authentication modes
--------------------

1. **API Key** — ``AZURE_OPENAI_API_KEY`` environment variable or the
   ``api_key`` keyword.  Sent in the ``api-key`` header (OpenAI
   style).  This is the default for most self-hosted deployments.
2. **Azure AD OAuth (client credentials)** — ``AZURE_TENANT_ID`` plus
   ``client_id`` / ``client_secret``.  Acquires a bearer token from
   ``https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token``.
3. **Managed Identity** — auto-detected when ``AZURE_CLIENT_ID`` is
   set and the IMDS endpoint (``169.254.169.254``) is reachable.
   Returns an OAuth token from the identity provider without
   requiring secrets on the host.

URL shape
---------

``{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={version}``

Both ``endpoint`` and ``deployment`` are user-configured per
provider instance.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlencode

from zeloo_cli.auth.base import AuthConfigError, AuthError, BaseAuth, TokenResponse, UserInfo
from zeloo_cli.auth.registry import register_auth

logger = logging.getLogger(__name__)


class AzureAuth(BaseAuth):
    """Authenticate with Azure OpenAI / Azure AI Foundry."""

    provider_name: str = "azure"

    DEFAULT_AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
    DEFAULT_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    DEFAULT_API_BASE = ""  # Azure requires an explicit endpoint per resource

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
            or os.environ.get("AZURE_OPENAI_API_KEY", "")
            or client_secret
        )
        self.tenant_id: str = (
            self.config.get("tenant_id", "")
            or os.environ.get("AZURE_TENANT_ID", "")
        )
        self.endpoint: str = (
            self.config.get("endpoint", "")
            or os.environ.get("AZURE_OPENAI_ENDPOINT", "")
        )
        self.deployment: str = (
            self.config.get("deployment", "")
            or os.environ.get("AZURE_OPENAI_DEPLOYMENT", "")
        )
        self.api_version: str = (
            self.config.get("api_version", "")
            or os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01")
        )
        self.scope: str = self.config.get(
            "scope", "https://cognitiveservices.azure.com/.default"
        )
        self.managed_identity_client: str = os.environ.get("AZURE_CLIENT_ID", "")
        # ``auth_mode`` is resolved lazily by :meth:`_resolve_auth_mode`
        # so that managed-identity probing only runs when the caller
        # actually tries to use the client.
        self._auth_mode: str | None = None

    def _resolve_auth_mode(self) -> str:
        """Decide which auth flavour this instance should use."""
        if self._auth_mode:
            return self._auth_mode
        if self.api_key:
            self._auth_mode = "api_key"
        elif self.managed_identity_client:
            self._auth_mode = "managed_identity"
        elif self.client_id and self.client_secret and self.tenant_id:
            self._auth_mode = "azure_ad"
        else:
            raise AuthConfigError(
                "Azure credentials not configured. "
                "Set AZURE_OPENAI_API_KEY (API Key), or AZURE_TENANT_ID + "
                "client_id/client_secret (Azure AD), or AZURE_CLIENT_ID "
                "(Managed Identity)."
            )
        return self._auth_mode

    def is_authenticated(self) -> bool:
        if self.api_key:
            return True
        return super().is_authenticated()

    def get_auth_url(
        self,
        redirect_uri: str,
        state: str = "",
        **kwargs: Any,
    ) -> str:
        """Build the Azure AD OAuth authorization URL (delegated flow)."""
        if not self.client_id or not self.tenant_id:
            raise AuthConfigError(
                "Azure AD delegated flow requires client_id and tenant_id. "
                "Set `auth.providers.azure.client_id` and tenant_id."
            )
        params: dict[str, str] = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": kwargs.pop("scope", self.scope),
        }
        if state:
            params["state"] = state
        params.update({k: str(v) for k, v in kwargs.items()})
        tenant = self.tenant_id
        url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?{urlencode(params)}"
        return url

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenResponse:
        """Exchange an Azure AD authorization code for a bearer token."""
        if not self.client_id or not self.tenant_id:
            raise AuthConfigError("client_id and tenant_id are required for the OAuth flow")
        token_url = self.DEFAULT_TOKEN_URL.format(tenant=self.tenant_id)
        data = await self._post_form(
            token_url,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": self.scope,
            },
        )
        return self._parse_token_response(data)

    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        """Refresh an Azure AD bearer token."""
        if not self.client_id or not self.tenant_id:
            raise AuthConfigError("client_id and tenant_id are required for the OAuth flow")
        token_url = self.DEFAULT_TOKEN_URL.format(tenant=self.tenant_id)
        data = await self._post_form(
            token_url,
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": self.scope,
            },
        )
        return self._parse_token_response(data)

    async def _acquire_ad_token(self) -> str:
        """Fetch a client-credentials token for Azure Cognitive Services."""
        if not (self.client_id and self.client_secret and self.tenant_id):
            raise AuthConfigError("Azure AD client credentials are incomplete")
        token_url = self.DEFAULT_TOKEN_URL.format(tenant=self.tenant_id)
        data = await self._post_form(
            token_url,
            {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": self.scope,
            },
        )
        access = data.get("access_token")
        if not access:
            raise AuthError(f"Azure AD token response missing access_token: {data}")
        return str(access)

    async def _acquire_managed_identity_token(self) -> str:
        """Fetch a token from the Azure Instance Metadata Service (IMDS)."""
        import httpx

        url = "http://169.254.169.254/metadata/identity/oauth2/token"
        params = {"api-version": "2018-02-01", "resource": "https://cognitiveservices.azure.com"}
        if self.managed_identity_client:
            params["client_id"] = self.managed_identity_client
        headers = {"Metadata": "true"}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise AuthError(f"Managed Identity unreachable: {exc}") from exc
        if resp.status_code >= 400:
            raise AuthError(
                f"Managed Identity returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
        try:
            data = resp.json()
        except ValueError as exc:
            raise AuthError("Managed Identity returned non-JSON") from exc
        access = data.get("access_token")
        if not access:
            raise AuthError(f"Managed Identity token response missing access_token: {data}")
        return str(access)

    async def _resolve_bearer(self) -> str:
        """Return an Azure bearer token, acquiring it if necessary."""
        mode = self._resolve_auth_mode()
        if mode == "api_key":
            return self.api_key
        if mode == "azure_ad":
            return await self._acquire_ad_token()
        return await self._acquire_managed_identity_token()

    async def get_user_info(self, access_token: str) -> UserInfo:
        """Return a minimal Azure user profile.

        Azure does not expose a generic ``/me`` endpoint across
        services, so we surface only the provider name and a placeholder
        user_id.  Callers needing richer data should query Microsoft
        Graph separately.
        """
        return UserInfo(
            provider=self.provider_name,
            user_id="azure-user",
            email=None,
            name=None,
            username=None,
            avatar_url=None,
            raw={"mode": self._resolve_auth_mode()},
        )

    async def call_api(
        self,
        path: str,
        method: str = "POST",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Make an authenticated call to an Azure OpenAI deployment.

        The URL is rewritten to include the deployment and
        ``api-version`` query string when the caller supplies a
        relative path (e.g. ``/chat/completions``).
        """
        import httpx

        if not self.endpoint:
            raise AuthConfigError(
                "Azure endpoint is not configured. Set `auth.providers.azure.endpoint` "
                "or AZURE_OPENAI_ENDPOINT."
            )
        bearer = await self._resolve_bearer()
        base = self.endpoint.rstrip("/")
        url = f"{base}{path}"
        if self.deployment and "deployments/" not in path:
            url = f"{base}/openai/deployments/{self.deployment}{path}"
        if "api-version" not in url:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}api-version={self.api_version}"
        headers = dict(kwargs.pop("headers", {}))
        if self._resolve_auth_mode() == "api_key":
            headers["api-key"] = bearer
        else:
            headers["Authorization"] = f"Bearer {bearer}"
        headers.setdefault("Content-Type", "application/json")
        async with httpx.AsyncClient(timeout=kwargs.pop("timeout", 60.0)) as client:
            resp = await client.request(method, url, headers=headers, **kwargs)
        if resp.status_code >= 400:
            raise AuthError(f"Azure API error: HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()
        except ValueError as exc:
            raise AuthError("Azure API returned non-JSON") from exc

    def _parse_token_response(self, data: dict[str, Any]) -> TokenResponse:
        access = data.get("access_token")
        if not access:
            raise AuthError(f"Azure token response missing access_token: {data}")
        expires_in = data.get("expires_in")
        return TokenResponse(
            access_token=access,
            token_type=data.get("token_type", "Bearer"),
            refresh_token=data.get("refresh_token"),
            expires_in=int(expires_in) if expires_in is not None else None,
            scope=data.get("scope", ""),
            extras={
                k: v
                for k, v in data.items()
                if k
                not in {
                    "access_token",
                    "token_type",
                    "refresh_token",
                    "expires_in",
                    "scope",
                }
            },
        )


register_auth("azure", AzureAuth)


__all__ = ["AzureAuth"]
