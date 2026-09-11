"""MCP OAuth 2.0/2.1 client.

Implements RFC 6749 (OAuth 2.0) + RFC 8414 (Authorization Server Metadata)
with PKCE (RFC 7636) support. This client is used to authenticate MCP
(Model Context Protocol) servers that require user authorization before
exposing tools to Zeloo.

Three grant types are supported:

* ``authorization_code`` — standard browser-based flow with PKCE.
* ``client_credentials`` — machine-to-machine grant (no user interaction).
* ``device_code`` — RFC 8628 device authorization grant (see
  :mod:`tools.mcp_oauth_device`).

The class deliberately keeps zero hard dependency on a specific HTTP
client implementation beyond ``httpx`` (already a Zeloo dependency) and
the Python standard library. Errors are surfaced as ``OAuthError`` so
callers can distinguish protocol failures from network glitches.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import secrets
import urllib.parse
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class OAuthGrantType(str, Enum):
    """Supported OAuth 2.0 grant types."""

    AUTHORIZATION_CODE = "authorization_code"
    CLIENT_CREDENTIALS = "client_credentials"
    DEVICE_CODE = "urn:ietf:params:oauth:grant-type:device_code"
    REFRESH_TOKEN = "refresh_token"


@dataclass
class OAuthConfig:
    """OAuth client configuration for a single MCP server.

    Attributes:
        client_id: Public client identifier registered with the AS.
        client_secret: Confidential client secret (``None`` for public
            clients using PKCE).
        authorization_endpoint: Where to send the user for consent.
        token_endpoint: Where to exchange codes / refresh tokens.
        scope: Space-separated scope string (per RFC 6749 §3.3).
        redirect_uri: Loopback URI registered with the AS. MCP servers
            typically use ``http://localhost:<port>/callback``.
        audience: Optional ``audience`` parameter for Auth0-style APIs.
        use_pkce: When ``True`` (default for public clients), every
            authorization-code request includes a PKCE pair.
    """

    client_id: str
    client_secret: str | None = None
    authorization_endpoint: str = ""
    token_endpoint: str = ""
    scope: str = ""
    redirect_uri: str = "http://localhost:8080/callback"
    audience: str | None = None
    use_pkce: bool = True
    extra_params: dict[str, str] = field(default_factory=dict)


@dataclass
class OAuthError(RuntimeError):
    """Raised when an OAuth protocol exchange fails.

    The optional ``error_code`` follows RFC 6749 §5.2 (e.g.
    ``invalid_grant``, ``invalid_client``) when the AS returns one.
    """

    message: str
    error_code: str | None = None
    status_code: int | None = None
    response_body: str | None = None

    def __str__(self) -> str:  # pragma: no cover - trivial
        if self.error_code:
            return f"{self.message} (error={self.error_code})"
        return self.message


class MCPOAuthClient:
    """OAuth client for MCP server authentication.

    The client is stateless — it caches nothing more than the
    configuration. Token persistence is delegated to
    :class:`tools.mcp_oauth_manager.MCPOAuthManager`.

    Example::

        cfg = OAuthConfig(client_id="my-mcp", token_endpoint="...")
        client = MCPOAuthClient(cfg, server_name="my-mcp")
        verifier, challenge = client.generate_pkce_pair()
        url = client.get_authorization_url(state="abc", code_challenge=challenge)
        # ... user visits URL, returns with code ...
        token = await client.exchange_code(code, verifier)
    """

    _WELL_KNOWN_PATHS: tuple[str, ...] = (
        "/.well-known/oauth-authorization-server",
        "/.well-known/openid-configuration",
    )

    def __init__(
        self,
        config: OAuthConfig,
        server_name: str = "",
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.config = config
        self.server_name = server_name or config.client_id
        self._timeout = timeout
        # We keep an optional external client for connection pooling;
        # if absent we create per-call clients (still cheap thanks to
        # keep-alive). The class never silently mutates a caller-owned
        # client.
        self._external_client = http_client
        self._owns_client = http_client is None

    # ── Context manager support ──────────────────────────────────────

    async def __aenter__(self) -> MCPOAuthClient:
        if self._external_client is None:
            self._external_client = httpx.AsyncClient(timeout=self._timeout)
            self._owns_client = True
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the internal ``httpx`` client if we own it."""
        if self._owns_client and self._external_client is not None:
            await self._external_client.aclose()
            self._external_client = None

    # ── Discovery ────────────────────────────────────────────────────

    async def discover_metadata(self, server_url: str) -> dict[str, Any]:
        """RFC 8414: Discover ``/.well-known/oauth-authorization-server``.

        Args:
            server_url: Root URL of the authorization server (e.g.
                ``https://auth.example.com``).

        Returns:
            The parsed JSON metadata document. Populates
            ``self.config.authorization_endpoint`` and
            ``self.config.token_endpoint`` if found.

        Raises:
            OAuthError: If neither ``oauth-authorization-server`` nor
                ``openid-configuration`` returns a usable document.
        """
        base = server_url.rstrip("/")
        last_error: Exception | None = None
        async with self._client() as client:
            for path in self._WELL_KNOWN_PATHS:
                url = f"{base}{path}"
                try:
                    resp = await client.get(url)
                except httpx.HTTPError as exc:
                    last_error = exc
                    logger.debug("Metadata fetch failed for %s: %s", url, exc)
                    continue
                if resp.status_code == 200:
                    try:
                        meta = resp.json()
                    except ValueError as exc:
                        raise OAuthError(
                            f"Invalid metadata JSON at {url}: {exc}",
                            status_code=resp.status_code,
                            response_body=resp.text[:512],
                        ) from exc
                    self._apply_metadata(meta)
                    return meta
                last_error = OAuthError(
                    f"Metadata discovery failed: HTTP {resp.status_code}",
                    status_code=resp.status_code,
                    response_body=resp.text[:512],
                )
        raise OAuthError(
            f"OAuth metadata discovery failed for {server_url}: {last_error}"
        )

    def _apply_metadata(self, meta: dict[str, Any]) -> None:
        """Fill in any config fields exposed by the AS metadata doc."""
        if not self.config.authorization_endpoint:
            self.config.authorization_endpoint = meta.get(
                "authorization_endpoint", ""
            )
        if not self.config.token_endpoint:
            self.config.token_endpoint = meta.get("token_endpoint", "")
        if not self.config.scope and meta.get("scopes_supported"):
            # Pick the first supported scope as a reasonable default;
            # callers can override by passing an explicit scope.
            supported = meta["scopes_supported"]
            if isinstance(supported, list) and supported:
                self.config.scope = " ".join(str(s) for s in supported)

    # ── PKCE ─────────────────────────────────────────────────────────

    @staticmethod
    def generate_pkce_pair() -> tuple[str, str]:
        """Generate a ``(code_verifier, code_challenge)`` PKCE pair.

        Uses the ``S256`` challenge method per RFC 7636 §4.2:
        ``BASE64URL(SHA256(verifier))``. ``code_verifier`` length is
        64 bytes (within the 43..128 spec range) yielding a 256-bit
        security margin.
        """
        # 64 random bytes -> base64url-encoded verifier (86 chars).
        verifier_bytes = secrets.token_bytes(64)
        verifier = base64.urlsafe_b64encode(verifier_bytes).decode("ascii").rstrip("=")
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
            .decode("ascii")
            .rstrip("=")
        )
        return verifier, challenge

    # ── Authorization URL ────────────────────────────────────────────

    def get_authorization_url(
        self,
        state: str = "",
        code_challenge: str | None = None,
        code_challenge_method: str = "S256",
        **extra: Any,
    ) -> str:
        """Build the user-facing authorization URL.

        Args:
            state: Opaque value echoed back on the callback. Used to
                defeat CSRF; callers should validate it matches.
            code_challenge: PKCE challenge. Required when
                ``config.use_pkce`` is True — pass the value from
                :meth:`generate_pkce_pair`.
            code_challenge_method: ``S256`` (default) or ``plain``.
            **extra: Additional query parameters (e.g. ``prompt``,
                ``login_hint``).

        Returns:
            A fully-formed URL the user can open in a browser.
        """
        if not self.config.authorization_endpoint:
            raise OAuthError("authorization_endpoint not configured")
        if not self.config.client_id:
            raise OAuthError("client_id not configured")
        params: dict[str, str] = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
        }
        if self.config.scope:
            params["scope"] = self.config.scope
        if self.config.audience:
            params["audience"] = self.config.audience
        if state:
            params["state"] = state
        if self.config.use_pkce:
            if not code_challenge:
                raise OAuthError(
                    "code_challenge required when use_pkce=True "
                    "(call generate_pkce_pair())"
                )
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = code_challenge_method
        # Merge extras last so callers can override defaults if needed.
        for key, value in extra.items():
            params[str(key)] = str(value)
        # Always merge extra config params last too.
        params.update(self.config.extra_params)
        query = urllib.parse.urlencode(params)
        sep = "&" if "?" in self.config.authorization_endpoint else "?"
        return f"{self.config.authorization_endpoint}{sep}{query}"

    # ── Token exchange ───────────────────────────────────────────────

    async def exchange_code(
        self,
        code: str,
        code_verifier: str,
        redirect_uri: str = "",
    ) -> dict[str, Any]:
        """Exchange an authorization code for an access token.

        Args:
            code: The ``code`` query parameter from the AS callback.
            code_verifier: PKCE verifier paired with the challenge
                sent in the authorization request.
            redirect_uri: Must match the value used in the
                authorization request.

        Returns:
            Parsed token response — typically contains
            ``access_token``, ``token_type``, ``expires_in``, and
            optionally ``refresh_token`` / ``scope``.
        """
        if not self.config.token_endpoint:
            raise OAuthError("token_endpoint not configured")
        data: dict[str, str] = {
            "grant_type": OAuthGrantType.AUTHORIZATION_CODE.value,
            "code": code,
            "client_id": self.config.client_id,
            "redirect_uri": redirect_uri or self.config.redirect_uri,
            "code_verifier": code_verifier,
        }
        return await self._post_token(data)

    async def refresh_token(self, refresh_token: str) -> dict[str, Any]:
        """Use a refresh token to obtain a fresh access token.

        Per RFC 6749 §6 the AS may rotate ``refresh_token``; we always
        return the full response so the caller can persist whatever
        the AS sends.
        """
        if not self.config.token_endpoint:
            raise OAuthError("token_endpoint not configured")
        data: dict[str, str] = {
            "grant_type": OAuthGrantType.REFRESH_TOKEN.value,
            "refresh_token": refresh_token,
            "client_id": self.config.client_id,
        }
        return await self._post_token(data)

    async def client_credentials_grant(self, scope: str = "") -> dict[str, Any]:
        """OAuth 2.0 §4.4 — client credentials grant (machine-to-machine).

        Requires ``client_secret`` to be configured. The ``scope``
        parameter, if provided, overrides ``config.scope`` for this
        single request (some ASes reject unknown scopes silently).
        """
        if not self.config.token_endpoint:
            raise OAuthError("token_endpoint not configured")
        if not self.config.client_secret:
            raise OAuthError(
                "client_credentials grant requires client_secret; "
                "configure OAuthConfig.client_secret"
            )
        data: dict[str, str] = {
            "grant_type": OAuthGrantType.CLIENT_CREDENTIALS.value,
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
        }
        effective_scope = scope or self.config.scope
        if effective_scope:
            data["scope"] = effective_scope
        return await self._post_token(data)

    # ── HTTP helpers ─────────────────────────────────────────────────

    def _client(self) -> httpx.AsyncClient:
        """Return the active ``httpx`` client, creating one if needed."""
        if self._external_client is None:
            # Self-cleaning client used only for the duration of the
            # with-block. Lightweight enough for one-shot calls.
            return httpx.AsyncClient(timeout=self._timeout)
        return self._external_client

    async def _post_token(self, data: dict[str, str]) -> dict[str, Any]:
        """POST to the token endpoint and parse the JSON response.

        Wraps the response handling so all grant flows share the same
        error-translation logic.
        """
        owns = self._external_client is None
        client = self._client()
        try:
            try:
                resp = await client.post(
                    self.config.token_endpoint,
                    data=data,
                    headers={"Accept": "application/json"},
                )
            except httpx.HTTPError as exc:
                raise OAuthError(f"Token request failed: {exc}") from exc
            body_text = resp.text
            try:
                payload = resp.json()
            except ValueError:
                payload = {}
            if resp.status_code >= 400 or "error" in payload:
                raise OAuthError(
                    payload.get("error_description")
                    or payload.get("error")
                    or f"Token endpoint returned HTTP {resp.status_code}",
                    error_code=payload.get("error"),
                    status_code=resp.status_code,
                    response_body=body_text[:512],
                )
            if "access_token" not in payload:
                raise OAuthError(
                    "Token response missing 'access_token'",
                    status_code=resp.status_code,
                    response_body=body_text[:512],
                )
            return payload
        finally:
            if owns and isinstance(client, httpx.AsyncClient):
                await client.aclose()


__all__ = [
    "OAuthGrantType",
    "OAuthConfig",
    "OAuthError",
    "MCPOAuthClient",
]


async def _selftest() -> None:  # pragma: no cover - manual smoke test
    """Quick sanity check: build an authorization URL and a PKCE pair."""
    cfg = OAuthConfig(
        client_id="demo",
        authorization_endpoint="https://auth.example.com/authorize",
        token_endpoint="https://auth.example.com/token",
        scope="read write",
    )
    client = MCPOAuthClient(cfg)
    verifier, challenge = client.generate_pkce_pair()
    assert len(verifier) >= 43 and len(verifier) <= 128
    url = client.get_authorization_url(state="xyz", code_challenge=challenge)
    assert "code_challenge=" in url
    assert "state=xyz" in url
    print("selftest OK:", url)


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_selftest())
