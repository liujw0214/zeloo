"""OAuth authentication abstract base classes.

This module defines the contract every Zeloo OAuth provider must
implement.  Sub-classes typically live in dedicated modules
(``openai_auth``, ``google_auth``, …) and are registered into
:data:`zeloo_cli.auth.registry.AUTH_REGISTRY` via the
:func:`register_auth` decorator.

Design goals
------------

* **Async-first** — token exchanges and user-info fetches are network
  bound; sub-classes provide ``async`` methods so they can be awaited
  from the CLI or an event loop without blocking.
* **Provider-agnostic token shape** — :class:`TokenResponse` and
  :class:`UserInfo` are simple dataclasses that can be serialised
  into the encrypted :class:`TokenStore` without provider-specific
  adapters.
* **Fail loudly** — :class:`AuthError` is the single root exception
  every provider should raise on protocol violations (bad status
  code, missing fields, revoked token).  Callers can catch one type
  instead of many.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any


class AuthError(Exception):
    """Raised when an OAuth flow fails for any reason.

    Sub-classes or instances may carry additional ``metadata`` (HTTP
    status, provider error code, …) for diagnostics.  The CLI surfaces
    these to users without leaking secrets.
    """


class AuthConfigError(AuthError):
    """Raised when provider configuration is missing or invalid."""


class AuthHTTPError(AuthError):
    """Raised on non-2xx HTTP responses from provider endpoints."""

    def __init__(self, status_code: int, body: str, url: str = "") -> None:
        self.status_code = status_code
        self.body = body
        self.url = url
        super().__init__(f"HTTP {status_code} from {url or 'provider'}: {body[:200]}")


@dataclass
class TokenResponse:
    """A normalized OAuth 2.0 token response.

    Provider-specific fields (e.g. Google's ``id_token``) live in
    ``extras`` so the base type stays portable.
    """

    access_token: str
    token_type: str = "Bearer"
    refresh_token: str | None = None
    expires_in: int | None = None  # seconds; ``None`` = unknown
    scope: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def expires_at(self) -> float | None:
        """Return the wall-clock expiry as a Unix timestamp, or ``None``."""
        if self.expires_in is None:
            return None
        import time

        return time.time() + int(self.expires_in)


@dataclass
class UserInfo:
    """A normalized user profile returned by an OAuth provider.

    Provider-specific fields are kept in ``raw`` so callers that need
    them (e.g. ``avatar_url``, ``html_url``) can still access them.
    """

    provider: str
    user_id: str
    email: str | None = None
    name: str | None = None
    username: str | None = None
    avatar_url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BaseAuth(ABC):
    """Abstract OAuth provider base class.

    Sub-classes must implement the four core flow methods.  Default
    implementations for ``is_authenticated`` and ``logout`` rely on a
    :class:`TokenStore` instance — sub-classes are free to override
    those if they have a different persistence model.
    """

    provider_name: str = ""

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        **kwargs: Any,
    ) -> None:
        """Store credentials and provider-specific configuration.

        Args:
            client_id: OAuth client ID.  May be empty if the provider
                uses bearer tokens / bot tokens instead.
            client_secret: OAuth client secret.  Same caveat as above.
            **kwargs: Provider-specific options (redirect URI, scope,
                audience, …).  Stored verbatim on ``self.config``.
        """
        self.client_id: str = client_id
        self.client_secret: str = client_secret
        # Sub-classes can read free-form options via ``self.config``.
        self.config: dict[str, Any] = dict(kwargs)

    # ── Core flow ────────────────────────────────────────────────

    @abstractmethod
    def get_auth_url(
        self,
        redirect_uri: str,
        state: str = "",
        **kwargs: Any,
    ) -> str:
        """Build the provider's authorization URL.

        Args:
            redirect_uri: Where the provider should redirect after
                successful authorization.
            state: CSRF state token.  Sub-classes should echo this
                back to the caller when the redirect is received.
            **kwargs: Provider-specific query parameters.

        Returns:
            A fully formed URL the user must open in a browser.
        """

    @abstractmethod
    async def exchange_code(self, code: str, redirect_uri: str) -> TokenResponse:
        """Exchange an authorization code for an access token.

        Args:
            code: The ``code`` query parameter from the redirect.
            redirect_uri: The same redirect URI used in
                :meth:`get_auth_url`.  Providers require exact match.

        Returns:
            A populated :class:`TokenResponse`.

        Raises:
            AuthError: On protocol violation or HTTP failure.
        """

    @abstractmethod
    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        """Refresh an expired access token.

        Args:
            refresh_token: The refresh token issued alongside the
                original access token.

        Returns:
            A new :class:`TokenResponse`.  Sub-classes should carry
            forward ``refresh_token`` if the provider does not return
            a new one (Google's behaviour).

        Raises:
            AuthError: If the provider has no refresh-token support
                or the refresh fails.
        """

    @abstractmethod
    async def get_user_info(self, access_token: str) -> UserInfo:
        """Fetch the authenticated user's profile.

        Args:
            access_token: A valid access token for this provider.

        Returns:
            A normalized :class:`UserInfo`.

        Raises:
            AuthError: If the access token is invalid or the user-info
                endpoint fails.
        """

    # ── Convenience helpers ─────────────────────────────────────

    def is_authenticated(self) -> bool:
        """Return True if a valid token is present in the local store.

        Sub-classes that use a different persistence layer may
        override this.  The default implementation lazily instantiates
        a :class:`TokenStore` keyed by ``provider_name``.
        """
        from zeloo_cli.auth.token_store import TokenStore

        if not self.provider_name:
            return False
        token = TokenStore().load(self.provider_name)
        if not token:
            return False
        # ``expires_at`` is optional.  When present, treat as expired
        # one minute early to avoid races.
        expires_at = token.get("expires_at")
        if expires_at:
            import time

            try:
                if time.time() >= float(expires_at) - 60:
                    return False
            except (TypeError, ValueError):
                # Defensive: a malformed timestamp is treated as
                # "not authenticated" rather than crashing the CLI.
                return False
        return True

    def logout(self) -> bool:
        """Delete any locally stored token.  Returns True if removed."""
        from zeloo_cli.auth.token_store import TokenStore

        if not self.provider_name:
            return False
        store = TokenStore()
        if store.load(self.provider_name) is None:
            return False
        store.delete(self.provider_name)
        return True

    def save_token(self, token: TokenResponse, user: UserInfo | None = None) -> None:
        """Persist *token* (and optionally *user*) into the token store.

        Convenience wrapper that hides the :class:`TokenStore` API
        from sub-classes.
        """
        from zeloo_cli.auth.token_store import TokenStore

        payload: dict[str, Any] = {
            "access_token": token.access_token,
            "token_type": token.token_type,
            "refresh_token": token.refresh_token,
            "expires_at": token.expires_at,
            "scope": token.scope,
            "extras": token.extras,
        }
        if user is not None:
            payload["user"] = user.to_dict()
        TokenStore().save(self.provider_name, payload)

    # ── HTTP helpers ─────────────────────────────────────────────

    async def _post_form(
        self,
        url: str,
        data: dict[str, Any],
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """POST ``application/x-www-form-urlencoded`` and parse JSON.

        Used by most providers' token endpoints.  Raises
        :class:`AuthHTTPError` on non-2xx status.
        """
        import httpx

        merged: dict[str, str] = {"Accept": "application/json"}
        if headers:
            merged.update(headers)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                resp = await client.post(url, data=data, headers=merged)
            except httpx.HTTPError as exc:
                raise AuthError(f"Network error contacting {url}: {exc}") from exc
        if resp.status_code >= 400:
            raise AuthHTTPError(resp.status_code, resp.text, url)
        try:
            return resp.json()
        except ValueError as exc:
            raise AuthError(
                f"Provider returned non-JSON response from {url}"
            ) from exc

    async def _get_json(
        self,
        url: str,
        bearer: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """GET a JSON resource, optionally with a bearer token."""
        import httpx

        merged: dict[str, str] = {"Accept": "application/json"}
        if bearer:
            merged["Authorization"] = f"Bearer {bearer}"
        if headers:
            merged.update(headers)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                resp = await client.get(url, headers=merged)
            except httpx.HTTPError as exc:
                raise AuthError(f"Network error contacting {url}: {exc}") from exc
        if resp.status_code >= 400:
            raise AuthHTTPError(resp.status_code, resp.text, url)
        try:
            return resp.json()
        except ValueError as exc:
            raise AuthError(
                f"Provider returned non-JSON response from {url}"
            ) from exc


__all__ = [
    "AuthConfigError",
    "AuthError",
    "AuthHTTPError",
    "BaseAuth",
    "TokenResponse",
    "UserInfo",
]
