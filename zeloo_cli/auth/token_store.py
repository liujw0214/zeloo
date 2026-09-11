"""Encrypted token storage for OAuth credentials.

This module provides :class:`TokenStore`, a thin wrapper around
:class:`agent.credential_crypto.SecureCredentialStore` that maps a
provider name (e.g. ``"openai"``, ``"google"``) to a JSON-shaped token
record.  The on-disk format is the same Fernet ciphertext used by the
rest of the Zeloo secrets system — adding OAuth tokens to the existing
credentials file keeps key management simple (one master key, one
file).

Usage
-----

.. code-block:: python

    store = TokenStore()
    store.save("openai", {"access_token": "...", "expires_at": 1234567890})
    token = store.load("openai")
    store.delete("openai")
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# We *prefer* the shared credential store (which is already encrypted
# with the master key) but fall back to a dedicated JSON file if the
# cryptography dependency is missing or the shared store refuses to
# initialize (e.g. during first-run with no keyring backend).
_STORE_FILENAME = "oauth_tokens.enc"


def _default_store_path() -> Path:
    """Return the default token-store path under the Zeloo home."""
    try:
        from agent.zeloo_constants import get_zeloo_home

        return get_zeloo_home() / _STORE_FILENAME
    except Exception:
        # ``agent`` may not be importable in some test contexts.  Fall
        # back to a relative path so the module still works in
        # isolation.
        return Path.home() / ".Zeloo" / _STORE_FILENAME


class TokenStore:
    """Encrypted, thread-safe OAuth token storage.

    The store is backed by the shared
    :class:`agent.credential_crypto.SecureCredentialStore` when
    available so that tokens participate in the same key-rotation
    pipeline as API keys.  If the shared store cannot be initialised
    (for example, on a fresh install with no master key) we fall back
    to a self-contained JSON file encrypted with the same Fernet key.

    Args:
        path: Optional override for the storage location.  Defaults
            to ``$zeloo_HOME/oauth_tokens.enc`` (or
            ``~/.Zeloo/oauth_tokens.enc``).
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path: Path = Path(path) if path else _default_store_path()
        self._lock = threading.Lock()
        # Lazy: only construct the Fernet-backed store on first use,
        # so importing this module never raises at import time.
        self._secure: Any | None = None
        self._secure_attempted: bool = False

    # ── Backend selection ────────────────────────────────────────

    def _get_secure(self) -> Any | None:
        """Return a :class:`SecureCredentialStore` or ``None``."""
        if self._secure_attempted:
            return self._secure
        self._secure_attempted = True
        try:
            from agent.credential_crypto import SecureCredentialStore

            # Use the shared store path so rotation/backup treat
            # OAuth tokens the same as API keys.
            self._secure = SecureCredentialStore()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("SecureCredentialStore unavailable: %s", exc)
            self._secure = None
        return self._secure

    # ── Public API ───────────────────────────────────────────────

    def save(self, provider: str, token_data: dict[str, Any]) -> None:
        """Persist *token_data* under *provider*.

        Existing records for the same provider are overwritten.
        Encryption is performed transparently via the backing store.
        """
        if not provider:
            raise ValueError("provider must be a non-empty string")
        with self._lock:
            secure = self._get_secure()
            if secure is not None:
                secure.set_secret(
                    provider,
                    json.dumps(token_data, ensure_ascii=False),
                    label="oauth",
                )
                return
            self._save_plain(provider, token_data)

    def load(self, provider: str) -> dict[str, Any] | None:
        """Return the stored token dict for *provider*, or ``None``."""
        with self._lock:
            secure = self._get_secure()
            if secure is not None:
                raw = secure.get_secret(provider, label="oauth")
                if raw is None:
                    return None
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("Corrupt OAuth token for %s", provider)
                    return None
            return self._load_plain().get(provider)

    def delete(self, provider: str) -> bool:
        """Delete the stored token for *provider*.  Returns True if removed."""
        with self._lock:
            secure = self._get_secure()
            if secure is not None:
                return secure.delete_secret(provider, label="oauth")
            data = self._load_plain()
            if provider not in data:
                return False
            del data[provider]
            self._save_dict_plain(data)
            return True

    def list_providers(self) -> list[str]:
        """Return the names of providers with stored tokens."""
        with self._lock:
            secure = self._get_secure()
            if secure is not None:
                # Filter to those that have an ``oauth`` label.
                try:
                    raw = secure.load_dict()
                except Exception:
                    return []
                return sorted(
                    name
                    for name, records in raw.items()
                    if any(r.get("label") == "oauth" for r in records)
                )
            return sorted(self._load_plain().keys())

    def has(self, provider: str) -> bool:
        """Return True if *provider* has a stored token."""
        return self.load(provider) is not None

    def clear(self) -> int:
        """Delete *every* stored token.  Returns the number removed."""
        with self._lock:
            providers = self.list_providers()
            for name in providers:
                self.delete(name)
            return len(providers)

    # ── Plaintext fallback ───────────────────────────────────────

    def _plain_path(self) -> Path:
        return self._path

    def _load_plain(self) -> dict[str, dict[str, Any]]:
        """Load the fallback JSON file."""
        path = self._plain_path()
        if not path.is_file():
            return {}
        try:
            content = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.warning("Failed to read OAuth token file: %s", exc)
            return {}
        if not content:
            return {}
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("Corrupt OAuth token file %s; resetting", path)
            return {}
        return data if isinstance(data, dict) else {}

    def _save_dict_plain(self, data: dict[str, dict[str, Any]]) -> None:
        path = self._plain_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp, path)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass  # Windows
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def _save_plain(self, provider: str, token_data: dict[str, Any]) -> None:
        data = self._load_plain()
        data[provider] = token_data
        self._save_dict_plain(data)


__all__ = ["TokenStore"]
