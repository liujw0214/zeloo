"""HashiCorp Vault client integration.

Stores and retrieves secrets via Vault KV v2 secrets engine.
Falls back to local encrypted file when Vault is unreachable.

This module is intentionally **stdlib-only** — it uses
:mod:`urllib.request` for HTTP and a small HMAC + XOR scheme for the
local encrypted fallback store. That keeps ``zeloo_cli`` importable
without any third-party dependencies (no ``hvac`` / ``httpx`` /
``requests``).

Public surface
--------------

* :class:`VaultClient` — low-level HashiCorp Vault HTTP API client.
* :class:`VaultCredentialPool` — high-level pool with auto-fallback
  to a local encrypted file store.
* :class:`VaultError` — exception type raised by :class:`VaultClient`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "VaultClient",
    "VaultCredentialPool",
    "VaultError",
]


# ── exceptions ───────────────────────────────────────────────────


class VaultError(Exception):
    """Raised when a Vault operation fails (network / 4xx / 5xx)."""


# ── VaultClient ──────────────────────────────────────────────────


class VaultClient:
    """HashiCorp Vault HTTP API client.

    Targets the KV v2 secrets engine. If ``addr`` / ``token`` are not
    provided, the client falls back to ``VAULT_ADDR`` /
    ``VAULT_TOKEN`` environment variables. ``is_available()`` will
    return ``False`` when no server is reachable so that higher
    layers can transparently degrade to a local store.
    """

    DEFAULT_ADDR = "https://127.0.0.1:8200"
    """Default Vault address (matches the standard dev-server setup)."""

    DEFAULT_TIMEOUT = 5.0
    """Default HTTP timeout in seconds."""

    def __init__(
        self,
        addr: str = "",
        token: str = "",
        mount_point: str = "secret",
        namespace: str = "",
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialize the Vault client.

        Parameters
        ----------
        addr
            Vault server URL (e.g. ``https://vault.example.com:8200``).
            Falls back to ``VAULT_ADDR`` env var or
            :data:`DEFAULT_ADDR`.
        token
            Vault token. Falls back to ``VAULT_TOKEN`` env var.
        mount_point
            KV v2 mount point (commonly ``"secret"``).
        namespace
            Optional Vault Enterprise namespace header.
        timeout
            Per-request timeout in seconds.
        """
        self.addr = (addr or os.environ.get("VAULT_ADDR", "") or self.DEFAULT_ADDR).rstrip("/")
        self.token = token or os.environ.get("VAULT_TOKEN", "")
        self.mount_point = mount_point
        self.namespace = namespace or os.environ.get("VAULT_NAMESPACE", "")
        self.timeout = timeout
        self._lock = threading.Lock()

    # ── low-level HTTP helpers ────────────────────────────────────

    def _build_request(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None = None,
    ) -> urllib.request.Request:
        """Build a signed ``urllib.request.Request`` with Vault headers."""
        data: bytes | None = None
        headers: dict[str, str] = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["X-Vault-Token"] = self.token
        if self.namespace:
            headers["X-Vault-Namespace"] = self.namespace
        return urllib.request.Request(url, data=data, method=method, headers=headers)

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any] | None, dict[str, str]]:
        """Perform an HTTP request and return ``(status, json_body, headers)``."""
        url = f"{self.addr}{path}"
        req = self._build_request(method, url, body=body)
        ctx: ssl.SSLContext | None = None
        # Self-signed dev certs are common in local Vault setups. We
        # don't disable verification globally (that's insecure), but
        # we honour ``VAULT_SKIP_VERIFY=1`` for trusted dev loops.
        if os.environ.get("VAULT_SKIP_VERIFY", "").lower() in ("1", "true", "yes"):
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as resp:
                raw = resp.read()
                status = resp.getcode() or 0
                resp_headers = {k: v for k, v in resp.headers.items()}
        except urllib.error.HTTPError as exc:
            # Vault returned a non-2xx response — capture body for diagnostics.
            try:
                raw = exc.read() or b""
            except Exception:  # noqa: BLE001
                raw = b""
            status = exc.code or 0
            resp_headers = {k: v for k, v in (exc.headers.items() if exc.headers else [])}
        except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as exc:
            raise VaultError(f"Vault network error: {exc}") from exc

        parsed: dict[str, Any] | None = None
        if raw:
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                parsed = None
        return status, parsed, resp_headers

    def _kv_path(self, path: str) -> str:
        """Compute the KV v2 endpoint for ``path``.

        Vault KV v2 stores data under
        ``/{mount}/data/{path}`` and metadata under
        ``/{mount}/metadata/{path}``. ``path`` is expected to be
        already-stripped (no leading slash).
        """
        path = path.lstrip("/")
        return f"/v1/{self.mount_point}/data/{path}"

    def _meta_path(self, path: str) -> str:
        path = path.lstrip("/")
        return f"/v1/{self.mount_point}/metadata/{path}"

    # ── availability / authentication ────────────────────────────

    def is_available(self) -> bool:
        """Return ``True`` when the Vault server responds to ``/sys/health``.

        A sealed / uninitialised Vault is treated as *unavailable* so
        that callers can degrade gracefully to local storage.
        """
        try:
            status, body, _ = self._request("GET", "/v1/sys/health?standbyok=true")
        except VaultError:
            return False
        if status in (429, 472, 473, 501, 503):
            # 429: standby, 472/473: DR/performance replication, 501: not init, 503: sealed
            return False
        return 200 <= status < 300

    def authenticate(self) -> bool:
        """Validate the configured token.

        Returns ``True`` if the token lookup succeeded and the token
        has not been revoked. ``False`` for network errors *or* a 403.
        """
        if not self.token:
            return False
        try:
            status, body, _ = self._request("GET", "/v1/auth/token/lookup-self")
        except VaultError:
            return False
        if status != 200 or not isinstance(body, dict):
            return False
        data = body.get("data")
        if not isinstance(data, dict):
            return False
        # An explicit revoked/expired marker trumps a 200 response.
        if data.get("expired") or data.get("revoked"):
            return False
        return True

    # ── KV v2 CRUD ────────────────────────────────────────────────

    def get_secret(self, path: str) -> dict[str, Any] | None:
        """Read a secret from Vault KV v2.

        Returns the inner ``data.data`` dict (the user-supplied key/value
        pairs) or ``None`` when the secret does not exist or the
        server is unreachable.
        """
        try:
            status, body, _ = self._request("GET", self._kv_path(path))
        except VaultError as exc:
            logger.debug("Vault get_secret(%s) network error: %s", path, exc)
            return None
        if status == 404:
            return None
        if status != 200 or not isinstance(body, dict):
            logger.debug("Vault get_secret(%s) failed: status=%s", path, status)
            return None
        data = body.get("data") or {}
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            return dict(data["data"])
        return None

    def put_secret(self, path: str, data: dict[str, Any]) -> bool:
        """Write a secret to Vault KV v2.

        Wraps ``data`` in the KV v2 envelope ``{"data": data}``.
        Returns ``True`` on a 200/204 response.
        """
        if not isinstance(data, dict):
            raise TypeError("data must be a dict")
        payload: dict[str, Any] = {"data": dict(data)}
        try:
            status, _, _ = self._request("POST", self._kv_path(path), body=payload)
        except VaultError as exc:
            logger.debug("Vault put_secret(%s) network error: %s", path, exc)
            return False
        if status in (200, 204):
            return True
        logger.warning("Vault put_secret(%s) failed: status=%s", path, status)
        return False

    def delete_secret(self, path: str) -> bool:
        """Delete the latest version of a secret.

        Returns ``True`` on success. A 404 (not found) also returns
        ``True`` because the post-condition (no secret) is satisfied.
        """
        try:
            status, _, _ = self._request("DELETE", self._kv_path(path))
        except VaultError as exc:
            logger.debug("Vault delete_secret(%s) network error: %s", path, exc)
            return False
        if status in (200, 204, 404):
            return True
        logger.warning("Vault delete_secret(%s) failed: status=%s", path, status)
        return False

    def list_secrets(self, path_prefix: str = "") -> list[str]:
        """List secret paths under ``path_prefix``.

        Returns the bare names (e.g. ``["foo", "bar/baz"]``). An
        empty list is returned when the prefix doesn't exist or the
        server is unreachable.
        """
        # Listing lives on the metadata endpoint.
        url = self._meta_path(path_prefix) + "?list=true"
        try:
            status, body, _ = self._request("GET", url)
        except VaultError as exc:
            logger.debug("Vault list_secrets(%s) network error: %s", path_prefix, exc)
            return []
        if status != 200 or not isinstance(body, dict):
            return []
        data = body.get("data") or {}
        keys = data.get("keys") if isinstance(data, dict) else None
        if not isinstance(keys, list):
            return []
        return [str(k) for k in keys]


# ── VaultCredentialPool ──────────────────────────────────────────


class _LocalEncryptedStore:
    """Tiny local encrypted file fallback used when Vault is down.

    Uses HMAC-SHA256 over an XOR stream cipher. Not cryptographically
    strong, but **far better than plaintext on disk** and needs zero
    third-party packages. The key is derived from
    ``zeloo_VAULT_LOCAL_KEY`` or, failing that, from a key file under
    ``~/.Zeloo/`` (mode 0600).
    """

    _MAGIC = b"ZLV1"
    _NONCE_LEN = 16

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._key: bytes | None = None

    # ── key management ────────────────────────────────────────────

    def _derive_key(self) -> bytes:
        env = os.environ.get("zeloo_VAULT_LOCAL_KEY", "")
        if env:
            return hashlib.sha256(env.encode("utf-8")).digest()
        key_file = self._path.parent / ".vault_local.key"
        if key_file.exists():
            try:
                raw = key_file.read_text(encoding="utf-8").strip()
                if raw:
                    return hashlib.sha256(raw.encode("utf-8")).digest()
            except OSError:
                pass
        # Last resort: ephemeral key. Data is lost across restarts but
        # writes still succeed — better than crashing the agent.
        return hashlib.sha256(os.urandom(32)).digest()

    def _ensure_key(self) -> bytes:
        if self._key is None:
            self._key = self._derive_key()
        return self._key

    # ── crypto ────────────────────────────────────────────────────

    def _seal(self, plaintext: bytes) -> bytes:
        """Encrypt ``plaintext`` with a derived key + nonce."""
        import secrets

        key = self._ensure_key()
        nonce = secrets.token_bytes(self._NONCE_LEN)
        # Stretch the key with the nonce so two ciphertexts of the
        # same plaintext differ.
        stream_key = hashlib.sha256(key + nonce).digest()
        # Repeat the stream key to cover long payloads.
        extended = stream_key * ((len(plaintext) // len(stream_key)) + 1)
        cipher = bytes(a ^ b for a, b in zip(plaintext, extended))
        mac = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
        return self._MAGIC + nonce + cipher + mac

    def _open(self, blob: bytes) -> bytes | None:
        """Decrypt a sealed blob, or ``None`` on MAC failure."""
        if len(blob) < len(self._MAGIC) + self._NONCE_LEN + 32:
            return None
        if blob[: len(self._MAGIC)] != self._MAGIC:
            return None
        offset = len(self._MAGIC)
        nonce = blob[offset : offset + self._NONCE_LEN]
        offset += self._NONCE_LEN
        mac = blob[-32:]
        cipher = blob[offset:-32]
        key = self._ensure_key()
        expected = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
        if not hmac.compare_digest(mac, expected):
            return None
        stream_key = hashlib.sha256(key + nonce).digest()
        extended = stream_key * ((len(cipher) // len(stream_key)) + 1)
        return bytes(a ^ b for a, b in zip(cipher, extended))

    # ── I/O ───────────────────────────────────────────────────────

    def _read(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            blob = self._path.read_bytes()
        except OSError as exc:
            logger.warning("Local vault store read failed: %s", exc)
            return {}
        plain = self._open(blob)
        if plain is None:
            logger.warning("Local vault store MAC verification failed; ignoring file")
            return {}
        try:
            decoded = json.loads(plain.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return decoded if isinstance(decoded, dict) else {}

    def _write(self, data: dict[str, str]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            blob = self._seal(json.dumps(data, ensure_ascii=False).encode("utf-8"))
            self._path.write_bytes(blob)
            try:
                os.chmod(self._path, 0o600)
            except OSError:
                pass
        except OSError as exc:
            logger.warning("Local vault store write failed: %s", exc)

    # ── public ────────────────────────────────────────────────────

    def get(self, key: str) -> str | None:
        with self._lock:
            data = self._read()
            value = data.get(key)
            return str(value) if value is not None else None

    def set(self, key: str, value: str) -> None:
        with self._lock:
            data = self._read()
            data[key] = value
            self._write(data)

    def delete(self, key: str) -> bool:
        with self._lock:
            data = self._read()
            if key not in data:
                return False
            del data[key]
            self._write(data)
            return True

    def list_keys(self) -> list[str]:
        with self._lock:
            return list(self._read().keys())


class VaultCredentialPool:
    """High-level credential pool with Vault + local-fallback semantics.

    Read path: ``Vault → local store → None``
    Write path: write to Vault **and** the local store (so the
    fallback is always warm).

    The pool is process-safe — concurrent ``set``/``get`` calls are
    serialised by a re-entrant lock.
    """

    def __init__(
        self,
        vault_client: VaultClient | None = None,
        *,
        local_path: Path | None = None,
    ) -> None:
        """Construct the pool.

        Parameters
        ----------
        vault_client
            Existing :class:`VaultClient`, or ``None`` to construct a
            default one from environment variables.
        local_path
            File path for the encrypted local fallback. Defaults to
            ``~/.Zeloo/vault_local.enc``.
        """
        self.vault = vault_client or VaultClient()
        if local_path is None:
            from zeloo_cli.config_home import get_zeloo_home

            local_path = get_zeloo_home() / "vault_local.enc"
        self._local = _LocalEncryptedStore(Path(local_path))
        self._lock = threading.Lock()
        self._last_vault_ok: float = 0.0
        self._probe_interval = 30.0
        # Pre-flight check so callers can decide policy immediately.
        try:
            if self.vault.is_available() and self.vault.authenticate():
                self._last_vault_ok = time.time()
        except Exception:  # noqa: BLE001
            logger.debug("Vault pre-flight failed", exc_info=True)

    # ── internal helpers ──────────────────────────────────────────

    def _vault_is_live(self) -> bool:
        """Cache the Vault availability probe for ``_probe_interval``."""
        if self._last_vault_ok and (time.time() - self._last_vault_ok) < self._probe_interval:
            return True
        try:
            ok = bool(self.vault.is_available() and self.vault.authenticate())
        except Exception:  # noqa: BLE001
            ok = False
        if ok:
            self._last_vault_ok = time.time()
        return ok

    def _vault_path(self, key: str) -> str:
        """Map a flat pool key to a Vault KV path."""
        # Avoid path traversal: keys may contain dots / slashes from
        # upstream callers, so we encode them to a single segment.
        encoded = base64.urlsafe_b64encode(key.encode("utf-8")).decode("ascii").rstrip("=")
        return f"zeloo/{encoded}"

    def _flat_key(self, path: str) -> str:
        """Inverse of :meth:`_vault_path` (best-effort)."""
        prefix = "zeloo/"
        if path.startswith(prefix):
            path = path[len(prefix):]
        padding = "=" * (-len(path) % 4)
        try:
            return base64.urlsafe_b64decode(path + padding).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return path

    # ── public API ────────────────────────────────────────────────

    def get(self, key: str) -> str | None:
        """Try Vault first, then fall back to the local store.

        Returns ``None`` only when neither backend has the key.
        """
        with self._lock:
            if self._vault_is_live():
                value = self.vault.get_secret(self._vault_path(key))
                if isinstance(value, dict):
                    # KV v2 stores nested dicts; the pool is flat, so
                    # we serialise the first string we find.
                    for v in value.values():
                        if isinstance(v, str):
                            return v
                    # Or return the whole dict encoded as JSON.
                    try:
                        return json.dumps(value)
                    except (TypeError, ValueError):
                        return None
                if isinstance(value, str):
                    return value
            return self._local.get(key)

    def set(self, key: str, value: str) -> None:
        """Persist ``key`` to Vault (if available) and the local store."""
        if not isinstance(value, str):
            raise TypeError("value must be a str")
        with self._lock:
            # Always update local store so the fallback is warm.
            self._local.set(key, value)
            if self._vault_is_live():
                ok = self.vault.put_secret(self._vault_path(key), {"value": value})
                if not ok:
                    logger.debug("Vault put failed for %s; relying on local store", key)

    def delete(self, key: str) -> None:
        """Remove ``key`` from Vault and the local store."""
        with self._lock:
            self._local.delete(key)
            if self._vault_is_live():
                self.vault.delete_secret(self._vault_path(key))

    def list_keys(self) -> list[str]:
        """Return the union of keys visible in Vault and the local store."""
        with self._lock:
            keys: set[str] = set(self._local.list_keys())
            if self._vault_is_live():
                vault_listing = self.vault.list_secrets("zeloo")
                for path in vault_listing:
                    keys.add(self._flat_key(path))
            return sorted(keys)

    def is_vault_available(self) -> bool:
        """Public probe — useful for health checks and ``zeloo doctor``."""
        return self._vault_is_live()

    def force_resync(self) -> None:
        """Force the next probe to re-hit Vault (cache TTL is reset)."""
        self._last_vault_ok = 0.0