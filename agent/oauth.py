"""OAuth support for LLM providers that require interactive authorization.

Some providers (e.g. OpenAI Codex, Nous) do not issue static API keys and
instead require an OAuth 2.0 device-authorization flow. This module
implements that flow and persists the resulting access/refresh tokens so
that the provider router can inject them as bearer tokens.

Token storage: ``~/.Zeloo/oauth_tokens.json`` (mode 0600 on Unix).
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _token_store_path() -> Path:
    """Return the path to the OAuth token store file."""
    from agent.zeloo_constants import get_zeloo_home

    return get_zeloo_home() / "oauth_tokens.json"


@dataclass
class OAuthToken:
    """An OAuth 2.0 token pair for a single provider."""

    provider: str
    access_token: str
    refresh_token: str | None = None
    expires_at: float = 0.0  # Unix timestamp; 0 = unknown/never
    token_type: str = "Bearer"
    scope: str = ""

    @property
    def is_expired(self) -> bool:
        """Return True if the access token has expired (or is close to)."""
        if self.expires_at <= 0:
            return False
        # Refresh 60 seconds before actual expiry to avoid race conditions.
        return time.time() >= (self.expires_at - 60)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OAuthToken:
        return cls(
            provider=data["provider"],
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=float(data.get("expires_at", 0)),
            token_type=data.get("token_type", "Bearer"),
            scope=data.get("scope", ""),
        )


@dataclass
class OAuthProviderConfig:
    """OAuth endpoints and client credentials for a provider."""

    name: str
    authorization_url: str  # device authorization endpoint
    token_url: str           # token endpoint
    client_id: str
    scope: str = ""
    audience: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OAuthProviderConfig:
        return cls(
            name=data["name"],
            authorization_url=data["authorization_url"],
            token_url=data["token_url"],
            client_id=data["client_id"],
            scope=data.get("scope", ""),
            audience=data.get("audience"),
        )


# ── Built-in OAuth provider configurations ───────────────────────────

# These are public client IDs for well-known OAuth-requiring providers.
# Users can override via config.yaml `oauth.providers.<name>`.
_BUILTIN_OAUTH_PROVIDERS: dict[str, OAuthProviderConfig] = {
    # OpenAI Codex uses the standard OpenAI OAuth device flow.
    "codex": OAuthProviderConfig(
        name="codex",
        authorization_url="https://auth.openai.com/authorize",
        token_url="https://auth.openai.com/oauth/token",
        client_id="auth0-openai-client",
        scope="openid profile email offline_access",
        audience="https://api.openai.com/v1",
    ),
    # Nous Research uses an Auth0-backed device flow.
    "nous": OAuthProviderConfig(
        name="nous",
        authorization_url="https://nousresearch.auth0.com/oauth/device/code",
        token_url="https://nousresearch.auth0.com/oauth/token",
        client_id="nous-cli",
        scope="offline_access",
    ),
}


def get_oauth_provider_config(provider_name: str) -> OAuthProviderConfig | None:
    """Return the OAuth config for *provider_name*, or None if unknown.

    Checks the user's ``config.yaml`` ``oauth.providers`` section first,
    then falls back to built-in defaults.
    """
    try:
        from zeloo_cli.config import load_config

        cfg = load_config()
        providers = (
            cfg.get("oauth", {}).get("providers", {})
            if isinstance(cfg, dict)
            else {}
        )
        if provider_name in providers and isinstance(providers[provider_name], dict):
            data = providers[provider_name]
            data.setdefault("name", provider_name)
            return OAuthProviderConfig.from_dict(data)
    except Exception:
        pass
    return _BUILTIN_OAUTH_PROVIDERS.get(provider_name)


# ── Token store ───────────────────────────────────────────────────────


class OAuthTokenStore:
    """Persists OAuth tokens to ``~/.Zeloo/oauth_tokens.json``."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _token_store_path()

    def _load(self) -> dict[str, OAuthToken]:
        if not self._path.is_file():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return {
                name: OAuthToken.from_dict(token)
                for name, token in data.items()
                if isinstance(token, dict)
            }
        except Exception:
            logger.exception("Failed to load OAuth token store")
            return {}

    def _save(self, tokens: dict[str, OAuthToken]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {name: token.to_dict() for name, token in tokens.items()}
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            pass  # Windows doesn't support POSIX permissions

    def get(self, provider: str) -> OAuthToken | None:
        """Return the stored token for *provider*, or None."""
        return self._load().get(provider)

    def save(self, token: OAuthToken) -> None:
        """Save (overwrite) the token for *token.provider*."""
        tokens = self._load()
        tokens[token.provider] = token
        self._save(tokens)
        logger.info("Saved OAuth token for provider '%s'", token.provider)

    def delete(self, provider: str) -> None:
        """Remove the stored token for *provider*."""
        tokens = self._load()
        if provider in tokens:
            del tokens[provider]
            self._save(tokens)
            logger.info("Deleted OAuth token for provider '%s'", provider)

    def list_providers(self) -> list[str]:
        """Return the names of all providers with stored tokens."""
        return sorted(self._load().keys())


# ── Device authorization flow ────────────────────────────────────────


def _http_post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST JSON and return the parsed JSON response."""
    import urllib.error
    import urllib.request

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} from {url}: {body}") from e


class DeviceFlowResult:
    """Holds the device-code challenge details for the user to act on."""

    def __init__(
        self,
        verification_uri: str,
        user_code: str,
        device_code: str,
        interval: int,
        expires_in: int,
    ) -> None:
        self.verification_uri = verification_uri
        self.user_code = user_code
        self.device_code = device_code
        self.interval = interval
        self.expires_in = expires_in


def start_device_flow(config: OAuthProviderConfig) -> DeviceFlowResult:
    """Initiate the OAuth device-authorization flow.

    Returns a :class:`DeviceFlowResult` containing the URL and code the
    user must enter in their browser. Call :func:`poll_for_token` to
    complete the flow.
    """
    payload: dict[str, Any] = {
        "client_id": config.client_id,
        "scope": config.scope,
    }
    if config.audience:
        payload["audience"] = config.audience

    resp = _http_post_json(config.authorization_url, payload)
    return DeviceFlowResult(
        verification_uri=resp.get("verification_uri_complete") or resp["verification_uri"],
        user_code=resp["user_code"],
        device_code=resp["device_code"],
        interval=int(resp.get("interval", 5)),
        expires_in=int(resp.get("expires_in", 600)),
    )


def poll_for_token(
    config: OAuthProviderConfig,
    flow: DeviceFlowResult,
    timeout: int = 600,
) -> OAuthToken:
    """Poll the token endpoint until the user authorizes or times out.

    Returns the resulting :class:`OAuthToken`. Raises ``TimeoutError``
    if the user does not authorize within *timeout* seconds.
    """
    deadline = time.time() + min(timeout, flow.expires_in)
    while time.time() < deadline:
        payload: dict[str, Any] = {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": flow.device_code,
            "client_id": config.client_id,
        }
        try:
            resp = _http_post_json(config.token_url, payload)
        except RuntimeError as exc:
            # "authorization_pending" / "slow_down" are expected while waiting.
            msg = str(exc).lower()
            if "authorization_pending" in msg:
                time.sleep(flow.interval)
                continue
            if "slow_down" in msg:
                time.sleep(flow.interval + 2)
                continue
            raise
        expires_in = int(resp.get("expires_in", 3600))
        return OAuthToken(
            provider=config.name,
            access_token=resp["access_token"],
            refresh_token=resp.get("refresh_token"),
            expires_at=time.time() + expires_in,
            token_type=resp.get("token_type", "Bearer"),
            scope=resp.get("scope", config.scope),
        )
    raise TimeoutError(
        f"OAuth device flow timed out after {timeout}s for provider '{config.name}'"
    )


def refresh_token(
    config: OAuthProviderConfig, token: OAuthToken
) -> OAuthToken:
    """Use the refresh token to obtain a new access token.

    Returns a new :class:`OAuthToken`. Raises ``RuntimeError`` if the
    provider has no refresh token or the refresh fails.
    """
    if not token.refresh_token:
        raise RuntimeError(
            f"Provider '{config.name}' has no refresh token; re-authenticate."
        )
    resp = _http_post_json(config.token_url, {
        "grant_type": "refresh_token",
        "refresh_token": token.refresh_token,
        "client_id": config.client_id,
    })
    expires_in = int(resp.get("expires_in", 3600))
    return OAuthToken(
        provider=config.name,
        access_token=resp["access_token"],
        refresh_token=resp.get("refresh_token", token.refresh_token),
        expires_at=time.time() + expires_in,
        token_type=resp.get("token_type", "Bearer"),
        scope=resp.get("scope", token.scope),
    )


def login(provider_name: str) -> OAuthToken:
    """Run the full device-code login flow for *provider_name*.

    Prints the verification URL/code to stdout, polls for authorization,
    saves the token to the store, and returns it.
    """
    config = get_oauth_provider_config(provider_name)
    if config is None:
        raise ValueError(
            f"No OAuth configuration found for provider '{provider_name}'. "
            f"Add it under `oauth.providers.{provider_name}` in config.yaml."
        )

    flow = start_device_flow(config)
    print(f"\nTo authorize Zeloo for '{provider_name}':")
    print(f"  1. Open: {flow.verification_uri}")
    print(f"  2. Enter code: {flow.user_code}")
    print(f"Waiting for authorization (timeout {flow.expires_in}s)...\n")

    token = poll_for_token(config, flow)
    OAuthTokenStore().save(token)
    print(f"Successfully logged in to '{provider_name}'.")
    return token


def get_access_token(provider_name: str) -> str | None:
    """Return a valid access token for *provider_name*, or None.

    If the stored token has expired and a refresh token is available,
    this attempts to refresh it. Returns None if no token exists or
    refresh fails.
    """
    store = OAuthTokenStore()
    token = store.get(provider_name)
    if token is None:
        return None
    if token.is_expired:
        config = get_oauth_provider_config(provider_name)
        if config is not None:
            try:
                token = refresh_token(config, token)
                store.save(token)
            except Exception:
                logger.warning("Failed to refresh OAuth token for '%s'", provider_name)
                return None
        else:
            return None
    return token.access_token
