"""Dashboard authentication providers for Zeloo CLI."""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "AuthProvider",
    "AuthResult",
    "TokenInfo",
    "BasicAuthProvider",
    "NousAuthProvider",
    "SelfHostedOAuthProvider",
    "AuthError",
]


@dataclass
class AuthResult:
    success: bool
    message: str = ""
    token: str | None = None
    user_id: str | None = None
    username: str | None = None
    expires_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TokenInfo:
    token: str
    user_id: str
    username: str | None
    expires_at: float | None
    scopes: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


class AuthError(Exception):
    pass


class InvalidCredentialsError(AuthError):
    pass


class TokenExpiredError(AuthError):
    pass


class AuthProvider(ABC):
    """Abstract base class for authentication providers."""

    name: str = "base"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._tokens: dict[str, TokenInfo] = {}

    @abstractmethod
    def authenticate(self, credentials: dict[str, Any]) -> AuthResult:
        """Authenticate user with given credentials.

        Args:
            credentials: Provider-specific credential dict.

        Returns:
            AuthResult with success status and token on success.
        """
        ...

    @abstractmethod
    def validate_token(self, token: str) -> TokenInfo | None:
        """Validate a token and return TokenInfo if valid.

        Args:
            token: The token to validate.

        Returns:
            TokenInfo if token is valid, None otherwise.
        """
        ...

    @abstractmethod
    def revoke_token(self, token: str) -> bool:
        """Revoke a token.

        Args:
            token: The token to revoke.

        Returns:
            True if revoked, False if token not found.
        """
        ...

    def _store_token(self, token: str, info: TokenInfo) -> None:
        self._tokens[token] = info

    def _generate_token(self, length: int = 32) -> str:
        return secrets.token_urlsafe(length)

    def _hash_password(self, password: str, salt: str | None = None) -> tuple[str, str]:
        if salt is None:
            salt = secrets.token_hex(16)
        hashed = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), 100000, dklen=32
        )
        return hashed.hex(), salt

    def _verify_password(self, password: str, hashed: str, salt: str) -> bool:
        computed, _ = self._hash_password(password, salt)
        return secrets.compare_digest(computed, hashed)


class BasicAuthProvider(AuthProvider):
    """Username + password authentication provider.

    Supports file-based user store for self-hosted deployments.
    """

    name: str = "basic"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.users_file = Path(self.config.get("users_file", "~/.Zeloo/auth/users.json"))
        self._users: dict[str, dict[str, str]] = {}

    def authenticate(self, credentials: dict[str, Any]) -> AuthResult:
        username = credentials.get("username", "")
        password = credentials.get("password", "")

        if not username or not password:
            return AuthResult(success=False, message="Username and password required")

        self._load_users()
        user = self._users.get(username)
        if user is None:
            logger.warning("Login attempt for unknown user: %s", username)
            return AuthResult(success=False, message="Invalid credentials")

        if not self._verify_password(password, user["hash"], user["salt"]):
            logger.warning("Failed login for user: %s", username)
            return AuthResult(success=False, message="Invalid credentials")

        token = self._generate_token()
        expires = time.time() + self.config.get("token_ttl", 86400)
        info = TokenInfo(token=token, user_id=user["id"], username=username, expires_at=expires)
        self._store_token(token, info)

        logger.info("User %s logged in successfully", username)
        return AuthResult(
            success=True,
            message="Login successful",
            token=token,
            user_id=user["id"],
            username=username,
            expires_at=expires,
        )

    def validate_token(self, token: str) -> TokenInfo | None:
        info = self._tokens.get(token)
        if info is None:
            return None
        if info.expires_at is not None and time.time() > info.expires_at:
            del self._tokens[token]
            return None
        return info

    def revoke_token(self, token: str) -> bool:
        if token in self._tokens:
            del self._tokens[token]
            return True
        return False

    def _load_users(self) -> None:
        import json

        path = self.users_file.expanduser()
        if path.exists():
            try:
                self._users = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.warning("Failed to load users file: %s", path)
                self._users = {}

    def add_user(self, username: str, password: str, user_id: str | None = None) -> bool:
        import json

        self._load_users()
        if username in self._users:
            return False

        hashed, salt = self._hash_password(password)
        self._users[username] = {
            "id": user_id or username,
            "hash": hashed,
            "salt": salt,
        }

        path = self.users_file.expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._users, indent=2, ensure_ascii=False), encoding="utf-8")
        return True


class NousAuthProvider(AuthProvider):
    """Nous official account authentication provider.

    Authenticates against the Nous platform API.
    """

    name: str = "nous"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.api_base = self.config.get("api_base", "https://api.nous-meshery.net")
        self.api_key = self.config.get("api_key", "")

    def authenticate(self, credentials: dict[str, Any]) -> AuthResult:
        token = credentials.get("api_token", "")

        if not token:
            return AuthResult(success=False, message="API token required")

        if not self.api_key:
            logger.warning("NousAuthProvider: NOUS_API_KEY not configured")
            return AuthResult(success=False, message="Authentication not configured")

        import httpx

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    f"{self.api_base}/auth/verify",
                    headers={"Authorization": f"Bearer {token}"},
                )
        except httpx.RequestError as exc:
            logger.error("Nous API request failed: %s", exc)
            return AuthResult(success=False, message=f"Connection error: {exc}")

        if resp.status_code == 401:
            return AuthResult(success=False, message="Invalid API token")
        if resp.status_code != 200:
            return AuthResult(success=False, message=f"Auth failed: {resp.status_code}")

        data = resp.json()
        user_id = data.get("user_id", "")
        username = data.get("username", "")

        session_token = self._generate_token()
        expires = time.time() + self.config.get("token_ttl", 86400)
        info = TokenInfo(
            token=session_token,
            user_id=user_id,
            username=username,
            expires_at=expires,
            scopes=data.get("scopes", []),
        )
        self._store_token(session_token, info)

        return AuthResult(
            success=True,
            message="Login successful",
            token=session_token,
            user_id=user_id,
            username=username,
            expires_at=expires,
            metadata=data,
        )

    def validate_token(self, token: str) -> TokenInfo | None:
        info = self._tokens.get(token)
        if info is None:
            return None
        if info.expires_at is not None and time.time() > info.expires_at:
            del self._tokens[token]
            return None
        return info

    def revoke_token(self, token: str) -> bool:
        if token in self._tokens:
            del self._tokens[token]
            return True
        return False


class SelfHostedOAuthProvider(AuthProvider):
    """Self-hosted OAuth2 authentication provider.

    Supports generic OAuth2 authorization code flow for enterprise intranets.
    """

    name: str = "self_hosted"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.client_id = self.config.get("client_id", "")
        self.client_secret = self.config.get("client_secret", "")
        self.authorize_url = self.config.get("authorize_url", "")
        self.token_url = self.config.get("token_url", "")
        self.userinfo_url = self.config.get("userinfo_url", "")
        self.redirect_uri = self.config.get("redirect_uri", "http://localhost:8080/auth/callback")
        self._pending_states: dict[str, float] = {}

    def authenticate(self, credentials: dict[str, Any]) -> AuthResult:
        auth_code = credentials.get("code", "")
        state = credentials.get("state", "")

        if not auth_code:
            auth_url = self._build_auth_url()
            return AuthResult(
                success=False,
                message="Authorization required",
                metadata={"auth_url": auth_url},
            )

        if not self._verify_state(state):
            return AuthResult(success=False, message="Invalid state parameter")

        import httpx

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    self.token_url,
                    data={
                        "grant_type": "authorization_code",
                        "code": auth_code,
                        "redirect_uri": self.redirect_uri,
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                    },
                )
        except httpx.RequestError as exc:
            logger.error("Token endpoint request failed: %s", exc)
            return AuthResult(success=False, message=f"Connection error: {exc}")

        if resp.status_code != 200:
            logger.error("Token request failed: %s", resp.text)
            return AuthResult(success=False, message=f"Token exchange failed: {resp.status_code}")

        data = resp.json()
        access_token = data.get("access_token", "")
        expires_in = data.get("expires_in", 3600)

        userinfo = self._fetch_userinfo(access_token)
        if userinfo is None:
            return AuthResult(success=False, message="Failed to fetch user info")

        session_token = self._generate_token()
        expires = time.time() + expires_in
        info = TokenInfo(
            token=session_token,
            user_id=userinfo.get("sub", ""),
            username=userinfo.get("name"),
            expires_at=expires,
            scopes=data.get("scope", "").split(),
        )
        self._store_token(session_token, info)

        return AuthResult(
            success=True,
            message="Login successful",
            token=session_token,
            user_id=userinfo.get("sub"),
            username=userinfo.get("name"),
            expires_at=expires,
        )

    def validate_token(self, token: str) -> TokenInfo | None:
        info = self._tokens.get(token)
        if info is None:
            return None
        if info.expires_at is not None and time.time() > info.expires_at:
            del self._tokens[token]
            return None
        return info

    def revoke_token(self, token: str) -> bool:
        if token in self._tokens:
            del self._tokens[token]
            return True
        return False

    def _build_auth_url(self) -> str:
        import urllib.parse

        state = self._generate_token()
        self._pending_states[state] = time.time() + 600

        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": self.config.get("scope", "openid profile email"),
            "state": state,
        }
        return f"{self.authorize_url}?{urllib.parse.urlencode(params)}"

    def _verify_state(self, state: str) -> bool:
        expiry = self._pending_states.pop(state, 0)
        if expiry == 0:
            return False
        return time.time() < expiry

    def _fetch_userinfo(self, access_token: str) -> dict[str, Any] | None:
        import httpx

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    self.userinfo_url,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
        except httpx.RequestError:
            return None

        if resp.status_code == 200:
            return resp.json()
        return None
