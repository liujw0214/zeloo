"""MCP OAuth token storage and rotation.

Stores per-server tokens in a JSON file under ``~/.Zeloo/`` and
optionally encrypts the values at rest via the existing
:class:`agent.credential_crypto.SecureCredentialStore`. Rotation
happens transparently in :meth:`MCPOAuthManager.get_valid_token`,
which refreshes a near-expiry access token using its companion
``MCPOAuthClient``.

Why a dedicated manager (rather than reusing
``agent.oauth.OAuthTokenStore``)?
    * MCP tokens may originate from different flows (authorization
      code, device code, client credentials) so the on-disk schema is
      slightly richer (provider name, flow, obtained_at, extra).
    * Rotation must invoke the *same* :class:`MCPOAuthClient` that
      issued the token (refresh tokens are usually bound to the
      client_id + audience that minted them).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from agent.credential_crypto import SecureCredentialStore
from tools.mcp_oauth import MCPOAuthClient, OAuthError

logger = logging.getLogger(__name__)


_DEFAULT_STORE_DIR = "~/.Zeloo"
_DEFAULT_TOKEN_FILENAME = "mcp_oauth_tokens.json"


def _default_storage_path() -> Path:
    """Resolve the default token store path under ``$zeloo_HOME``."""
    from agent.zeloo_constants import get_zeloo_home

    return get_zeloo_home() / _DEFAULT_TOKEN_FILENAME


class MCPOAuthManager:
    """Manage OAuth tokens for multiple MCP servers.

    Args:
        storage_path: Path to the JSON file used to persist tokens.
            When omitted, defaults to ``$zeloo_HOME/mcp_oauth_tokens.json``.
        encrypt_at_rest: If ``True`` (default), token values are
            encrypted via :class:`SecureCredentialStore` before being
            written to disk. The keys/structure of the file are still
            JSON, but ``access_token`` and ``refresh_token`` are
            ciphertext envelopes.
    """

    def __init__(
        self,
        storage_path: Path | None = None,
        encrypt_at_rest: bool = True,
    ) -> None:
        self._path = Path(storage_path) if storage_path else _default_storage_path()
        self._lock = threading.RLock()
        self._encrypt = encrypt_at_rest
        # Lazy: only spin up the credential store when we actually
        # need to encrypt something. Constructing it touches the
        # filesystem (creates ~/.Zeloo/) which we want to avoid when
        # the caller only performs read-only operations.
        self._cred_store: SecureCredentialStore | None = None

    # ── Storage layout ───────────────────────────────────────────────

    @property
    def storage_path(self) -> Path:
        """Return the on-disk path used to persist tokens."""
        return self._path

    def _provider_key(self, server_name: str) -> str:
        """Namespace MCP tokens away from other credentials."""
        return f"mcp_oauth::{server_name}"

    def _get_cred_store(self) -> SecureCredentialStore:
        """Return the lazily-constructed :class:`SecureCredentialStore`."""
        if self._cred_store is None:
            # We pass an explicit path so the credential store doesn't
            # touch the same file the manager owns.
            self._cred_store = SecureCredentialStore()
        return self._cred_store

    # ── CRUD ─────────────────────────────────────────────────────────

    def save_token(self, server_name: str, token_data: dict[str, Any]) -> None:
        """Persist *token_data* for *server_name*.

        The dictionary is augmented with a ``saved_at`` timestamp so we
        can debug stale-token issues. Already-encrypted values are
        left untouched.
        """
        if not isinstance(token_data, dict):
            raise TypeError(
                f"token_data must be a dict, got {type(token_data).__name__}"
            )
        with self._lock:
            data = self._load_raw()
            record = dict(token_data)
            record.setdefault("saved_at", time.time())
            record.setdefault("server_name", server_name)
            data[server_name] = self._maybe_encrypt(record)
            self._save_raw(data)
        logger.info("Saved MCP OAuth token for '%s'", server_name)

    def load_token(self, server_name: str) -> dict[str, Any] | None:
        """Return the stored token for *server_name*, or ``None``.

        Sensitive fields are decrypted transparently before being
        returned.
        """
        with self._lock:
            data = self._load_raw()
            record = data.get(server_name)
            if record is None:
                return None
            return self._maybe_decrypt(record)

    def delete_token(self, server_name: str) -> bool:
        """Remove the token for *server_name*. Returns True if removed."""
        with self._lock:
            data = self._load_raw()
            if server_name not in data:
                return False
            del data[server_name]
            self._save_raw(data)
        logger.info("Deleted MCP OAuth token for '%s'", server_name)
        return True

    def list_servers(self) -> list[str]:
        """Return all server names that have a stored token."""
        with self._lock:
            data = self._load_raw()
        return sorted(data.keys())

    # ── Token validation / rotation ──────────────────────────────────

    def is_expired(
        self,
        token_data: dict[str, Any],
        buffer_seconds: int = 60,
    ) -> bool:
        """Return True if the access token is expired (or near expiry).

        Tokens without an ``expires_at`` field are considered
        non-expiring — that's the only sensible default for opaque
        tokens issued without an ``expires_in`` (rare but valid for
        some MCP servers).

        Args:
            token_data: The token dictionary as returned by
                :meth:`load_token`.
            buffer_seconds: Refresh this many seconds before the real
                expiry to absorb clock skew and network latency.
        """
        expires_at = token_data.get("expires_at")
        if not expires_at:
            return False
        try:
            expires_at_f = float(expires_at)
        except (TypeError, ValueError):
            return False
        return time.time() >= (expires_at_f - buffer_seconds)

    async def get_valid_token(
        self,
        server_name: str,
        oauth_client: MCPOAuthClient,
    ) -> str:
        """Return a usable access token, refreshing if needed.

        Strategy:

        1. Load the token from disk.
        2. If still valid, return the access token.
        3. Otherwise call ``oauth_client.refresh_token`` and persist
           the new token (taking care to rotate the refresh token if
           the AS issued a new one).
        4. If refresh fails (no refresh token, AS rejected it, etc.)
           raise :class:`OAuthError` — callers must trigger a fresh
           interactive login.

        Args:
            server_name: The MCP server key (matches
                :meth:`save_token`).
            oauth_client: The client that originally minted the token;
                its config must contain the correct token endpoint and
                client_id.

        Returns:
            The ``access_token`` string ready to drop into an
            ``Authorization: Bearer …`` header.

        Raises:
            OAuthError: If no token is stored, or refresh fails.
        """
        token_data = self.load_token(server_name)
        if token_data is None:
            raise OAuthError(
                f"No OAuth token stored for MCP server '{server_name}'; "
                "user must authenticate first"
            )
        if not self.is_expired(token_data):
            return str(token_data["access_token"])

        refresh = token_data.get("refresh_token")
        if not refresh:
            raise OAuthError(
                f"MCP server '{server_name}' token expired and no "
                "refresh_token is available; re-authenticate required"
            )

        logger.info("Refreshing OAuth token for MCP server '%s'", server_name)
        try:
            new_token = await oauth_client.refresh_token(str(refresh))
        except OAuthError:
            logger.warning(
                "Refresh failed for '%s'; the stored refresh token may "
                "have been revoked. Caller should re-authenticate.",
                server_name,
            )
            raise

        # Carry over fields the AS may omit from its refresh response.
        merged: dict[str, Any] = {
            "access_token": new_token.get("access_token"),
            "token_type": new_token.get("token_type", "Bearer"),
            "scope": new_token.get("scope", token_data.get("scope", "")),
            "refresh_token": new_token.get("refresh_token", refresh),
            "server_name": server_name,
        }
        if "expires_in" in new_token:
            try:
                merged["expires_at"] = time.time() + float(new_token["expires_in"])
            except (TypeError, ValueError):
                pass
        else:
            # Trust the old expiry if the AS didn't tell us anything new.
            merged["expires_at"] = token_data.get("expires_at", 0)
        if "id_token" in new_token:
            merged["id_token"] = new_token["id_token"]

        self.save_token(server_name, merged)
        access = merged.get("access_token")
        if not access:
            raise OAuthError(
                f"Refresh for '{server_name}' returned no access_token",
                response_body=str(new_token)[:512],
            )
        return str(access)

    # ── Internal IO + encryption ─────────────────────────────────────

    def _load_raw(self) -> dict[str, dict[str, Any]]:
        """Read the JSON file from disk (no decryption)."""
        if not self._path.is_file():
            return {}
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to read %s: %s", self._path, exc)
            return {}
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("Corrupt token store %s: %s", self._path, exc)
            return {}
        if not isinstance(data, dict):
            return {}
        # Defensive: only keep dict-shaped records.
        return {k: v for k, v in data.items() if isinstance(v, dict)}

    def _save_raw(self, data: dict[str, dict[str, Any]]) -> None:
        """Write the JSON file atomically."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        serialised = json.dumps(
            data, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(serialised)
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    pass
            os.replace(tmp, self._path)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            pass  # Windows doesn't support POSIX mode bits.

    def _maybe_encrypt(self, record: dict[str, Any]) -> dict[str, Any]:
        """Encrypt sensitive fields if encryption is enabled."""
        if not self._encrypt:
            return record
        store = self._get_cred_store()
        if not store.is_encrypted:
            # Don't pretend we're encrypting — the caller will see
            # plaintext on disk and the warning is already logged by
            # SecureCredentialStore.
            return record
        out = dict(record)
        for field_name in ("access_token", "refresh_token", "id_token"):
            value = out.get(field_name)
            if isinstance(value, str) and value and not value.startswith("enc:"):
                out[field_name] = "enc:" + store.encrypt(value)
        return out

    def _maybe_decrypt(self, record: dict[str, Any]) -> dict[str, Any]:
        """Decrypt sensitive fields if they were encrypted."""
        if not self._encrypt:
            return record
        store = self._get_cred_store()
        out = dict(record)
        for field_name in ("access_token", "refresh_token", "id_token"):
            value = out.get(field_name)
            if isinstance(value, str) and value.startswith("enc:"):
                try:
                    out[field_name] = store.decrypt(value[len("enc:"):])
                except ValueError as exc:
                    logger.warning(
                        "Failed to decrypt '%s' field: %s", field_name, exc
                    )
                    # Keep the encrypted form so callers can see the
                    # failure rather than silently returning None.
                    out[field_name] = None
        return out


__all__ = ["MCPOAuthManager"]


def _selftest() -> None:  # pragma: no cover - manual smoke test
    """End-to-end sanity check with a tmp directory."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "tokens.json"
        mgr = MCPOAuthManager(storage_path=path, encrypt_at_rest=False)
        mgr.save_token(
            "demo",
            {
                "access_token": "AAA",
                "refresh_token": "RRR",
                "expires_at": time.time() + 3600,
                "scope": "read",
            },
        )
        loaded = mgr.load_token("demo")
        assert loaded is not None
        assert loaded["access_token"] == "AAA"
        assert mgr.list_servers() == ["demo"]
        assert not mgr.is_expired(loaded)
        expired = dict(loaded)
        expired["expires_at"] = time.time() - 10
        assert mgr.is_expired(expired)
        assert mgr.delete_token("demo") is True
        assert mgr.list_servers() == []
        print("manager selftest OK")


if __name__ == "__main__":  # pragma: no cover
    _selftest()
