"""Encrypted credential storage.

Provides a :class:`SecureCredentialStore` that encrypts credential values
before writing to disk using **Fernet (AES-128-CBC + HMAC-SHA256)**, so
on-disk files never contain plaintext API keys.

The master encryption key is derived from one of the following sources
(in priority order):

1. ``zeloo_MASTER_KEY`` environment variable (base64url-encoded 32-byte key)
2. The OS keyring (via the optional ``keyring`` package)
3. A local file ``~/.Zeloo/.master_key`` (created on first use, mode 0600)

When no source is available, :meth:`SecureCredentialStore.ensure_key`
generates a fresh 32-byte key and persists it via source (1) or (3).

If neither ``keyring`` nor ``cryptography`` is installed, the store
falls back to plaintext but emits a loud warning — callers should
install at least one of them for production use.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MASTER_KEY_ENV = "zeloo_MASTER_KEY"
_MASTER_KEY_FILENAME = ".master_key"
_SERVICE_NAME = "Zeloo"


def _try_import_cryptography() -> tuple[Any, Any]:
    """Import and return ``(Fernet, InvalidToken)`` from cryptography.

    Returns (None, None) if the package is missing.
    """
    try:
        from cryptography.fernet import Fernet, InvalidToken  # type: ignore[import-untyped]

        return Fernet, InvalidToken
    except ImportError:
        return None, None


def _try_import_keyring() -> Any:
    """Try importing the ``keyring`` package."""
    try:
        import keyring  # type: ignore[import-untyped]

        return keyring
    except ImportError:
        return None


def _generate_key() -> bytes:
        """Generate a fresh Fernet master key (base64url-encoded 32 bytes).

        Fernet expects a *base64url-encoded* 32-byte key, *not* the raw
        bytes. We return the encoded string here so the rest of the
        module can pass it straight into ``Fernet(key)``.
        """
        Fernet, _ = _try_import_cryptography()
        if Fernet is None:
            raise RuntimeError(
                "cryptography package required for encrypted credential storage. "
                "Install with: pip install cryptography"
            )
        return Fernet.generate_key()


def _load_or_create_key(storage_dir: Path) -> bytes | None:
    """Resolve a master key from env / keyring / local file.

    Returns ``None`` if no keyring backend is available and the local
    file does not yet exist (caller should call
    :func:`_create_key_file`).

    The returned value is the *base64url-encoded* string the Fernet
    library expects — the on-disk file and the env var both store
    the encoded form, so we do not decode here.
    """
    env_key = os.environ.get(_MASTER_KEY_ENV)
    if env_key:
        # The env var holds the encoded string Fernet expects; verify
        # it's well-formed by attempting a Fernet construction in a
        # throwaway object — this catches typos without surfacing a
        # later ValueError on first encrypt/decrypt.
        try:
            Fernet, _ = _try_import_cryptography()
            if Fernet is not None:
                Fernet(env_key.encode("ascii"))
            return env_key
        except Exception:
            logger.warning("%s is invalid; ignoring", _MASTER_KEY_ENV)

    keyring_mod = _try_import_keyring()
    if keyring_mod is not None:
        try:
            stored = keyring_mod.get_password(_SERVICE_NAME, "master_key")
            if stored:
                Fernet, _ = _try_import_cryptography()
                if Fernet is not None:
                    Fernet(stored.encode("ascii"))
                return stored
        except Exception:
            logger.debug("keyring backend unavailable; falling back to file")

    key_path = storage_dir / _MASTER_KEY_FILENAME
    if key_path.is_file():
        try:
            stored = key_path.read_text(encoding="utf-8").strip()
            Fernet, _ = _try_import_cryptography()
            if Fernet is not None:
                Fernet(stored.encode("ascii"))
            return stored
        except Exception as exc:
            logger.warning("Failed to read master key file: %s", exc)

    return None


def _persist_key(key_bytes: bytes, storage_dir: Path) -> None:
        """Persist a newly generated key via keyring or local file."""
        encoded = base64.urlsafe_b64encode(key_bytes).decode("ascii")

        keyring_mod = _try_import_keyring()
        if keyring_mod is not None:
            try:
                keyring_mod.set_password(_SERVICE_NAME, "master_key", encoded)
                logger.info("Master key stored in OS keyring")
                return
            except Exception:
                logger.debug("keyring set failed; using local file")

        key_path = storage_dir / _MASTER_KEY_FILENAME
        key_path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: tmp + rename. The master key file is the root
        # of trust — a half-written key would lock the user out.
        tmp = key_path.with_suffix(key_path.suffix + ".tmp")
        try:
            tmp.write_text(encoded, encoding="utf-8")
            os.replace(tmp, key_path)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
        try:
            os.chmod(key_path, 0o600)
        except OSError:
            pass
        logger.info("Master key written to %s (mode 0600)", key_path)


def _create_key_file(storage_dir: Path) -> bytes:
        """Generate a fresh key and persist it. Returns the raw key bytes."""
        key = _generate_key()
        _persist_key(key, storage_dir)
        return key


def _atomic_write_text(path: Path, content: str) -> None:
        """Write *content* to *path* atomically (tmp + rename).

        ``os.fsync`` is best-effort: some filesystems (network mounts,
        certain Windows configurations) reject ``fsync`` with EIO /
        EINVAL. We swallow those errors so a transient FS quirk
        doesn't block the whole write path.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    # Ignore fsync errors on filesystems that
                    # don't support it — the rename is still atomic.
                    pass
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass


class SecureCredentialStore:
    """Fernet-encrypted JSON credential store.

    Format on disk::

        {
            "openai": [{"label": "...", "value_b64": "<Fernet ciphertext>"}, ...],
            "anthropic": [...]
        }

    Use :meth:`load_dict` / :meth:`save_dict` to read and write the
    encrypted file. Helper methods :meth:`set_secret` and
    :meth:`get_secret` provide a per-provider key/value interface.

    Args:
        storage_path: Path to the encrypted JSON file. ``None`` picks
            ``$zeloo_HOME/credentials.enc`` (or
            ``~/.Zeloo/credentials.enc``).
    """

    def __init__(self, storage_path: str | Path | None = None) -> None:
        from agent.zeloo_constants import get_zeloo_home

        self._home = get_zeloo_home()
        if storage_path:
            self.storage_path = Path(storage_path)
        else:
            self.storage_path = self._home / "credentials.enc"

        self._fernet_cls, self._invalid_token = _try_import_cryptography()
        self._key: bytes | None = None
        # Cached Fernet instance — constructing one re-derives the HMAC
        # key, which costs ~5-10 µs per call. For a long session with
        # many set_secret / get_secret operations the savings add up.
        # The instance is invalidated whenever the master key changes.
        self._fernet_instance: Any | None = None
        self._lock = threading.Lock()

        if self._fernet_cls is None:
            logger.warning(
                "cryptography not available — credential storage falls back to "
                "plaintext. Install: pip install cryptography"
            )

    @property
    def is_encrypted(self) -> bool:
        """Return True if encryption is available and active."""
        return self._fernet_cls is not None and self._key is not None

    def ensure_key(self) -> bytes:
        """Resolve or generate a master key and cache it.

        Returns the raw 32-byte key, or raises ``RuntimeError`` if
        neither ``cryptography`` nor a key source is available.
        """
        if self._fernet_cls is None:
            raise RuntimeError("cryptography package is required for encryption")

        if self._key is not None:
            return self._key

        with self._lock:
            if self._key is not None:
                return self._key

            existing = _load_or_create_key(self._home)
            if existing is None:
                existing = _create_key_file(self._home)
            self._key = existing
            return existing

    def _get_fernet(self) -> Any:
        """Return the cached Fernet instance, creating one on first use."""
        self.ensure_key()
        fernet = self._fernet_instance
        if fernet is None:
            fernet = self._fernet_cls(self._key)
            self._fernet_instance = fernet
        return fernet

    def encrypt(self, plaintext: str) -> str:
        """Encrypt *plaintext* and return a URL-safe base64 string."""
        token = self._get_fernet().encrypt(plaintext.encode("utf-8"))
        return token.decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a ciphertext produced by :meth:`encrypt`.

        Raises ``ValueError`` if the token is invalid or tampered with.
        """
        try:
            return self._get_fernet().decrypt(
                ciphertext.encode("ascii"), ttl=None
            ).decode("utf-8")
        except self._invalid_token:
            raise ValueError("Invalid or tampered ciphertext") from None

    def load_dict(self) -> dict[str, list[dict[str, Any]]]:
        """Load and decrypt credentials from disk.

        Returns an empty dict if the file does not exist or is empty.
        """
        if not self.storage_path.is_file():
            return {}
        try:
            raw = self.storage_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.warning("Failed to read credentials: %s", exc)
            return {}

        if not raw:
            return {}

        if self.is_encrypted:
            try:
                decrypted = self.decrypt(raw)
                return json.loads(decrypted)
            except (ValueError, json.JSONDecodeError) as exc:
                logger.error("Failed to decrypt credentials: %s", exc)
                return {}
        else:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {}

    def save_dict(self, data: dict[str, list[dict[str, Any]]]) -> None:
        """Encrypt and write *data* to disk. Creates parent dirs as needed."""
        # Compact JSON (no indent) — the file is machine-written and
        # saves ~30% bytes vs indent=2.
        serialised = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

        if self.is_encrypted:
            serialised = self.encrypt(serialised)

        # Atomic write: tmp + rename + fsync. A crash mid-write would
        # leave a half-encrypted file that decrypt() rejects — locking
        # the user out of all credentials until manual recovery.
        #
        # We serialise concurrent save_dict calls on Windows where
        # ``os.replace`` cannot atomically swap a file that another
        # thread is also touching.
        with self._lock:
            _atomic_write_text(self.storage_path, serialised)
        try:
            os.chmod(self.storage_path, 0o600)
        except OSError:
            pass

    def set_secret(
        self,
        provider: str,
        value: str,
        label: str = "default",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add or replace a secret for *provider*."""
        with self._lock:
            data = self.load_dict()
            records = data.setdefault(provider, [])
            existing = next(
                (r for r in records if r.get("label") == label),
                None,
            )
            new_record: dict[str, Any] = {
                "label": label,
                "value_b64": self.encrypt(value) if self.is_encrypted else value,
            }
            if metadata:
                new_record["metadata"] = metadata
            if existing:
                existing.update(new_record)
            else:
                records.append(new_record)
            self.save_dict(data)

    def get_secret(self, provider: str, label: str = "default") -> str | None:
        """Retrieve a secret by *provider* and *label*, or ``None``."""
        with self._lock:
            data = self.load_dict()
        for record in data.get(provider, []):
            if record.get("label") == label:
                value = record.get("value_b64", "")
                if self.is_encrypted:
                    try:
                        return self.decrypt(value)
                    except ValueError:
                        return None
                return value
        return None

    def list_providers(self) -> list[str]:
        """Return provider names that have at least one secret."""
        with self._lock:
            return sorted(self.load_dict().keys())

    def delete_secret(self, provider: str, label: str = "default") -> bool:
        """Delete a secret. Returns True if something was removed."""
        with self._lock:
            data = self.load_dict()
            records = data.get(provider, [])
            new_records = [r for r in records if r.get("label") != label]
            if len(new_records) == len(records):
                return False
            if new_records:
                data[provider] = new_records
            else:
                data.pop(provider, None)
            self.save_dict(data)
            return True

    def rotate_master_key(self) -> bytes:
        """Generate a fresh master key and re-encrypt all existing data."""
        with self._lock:
            old_data = self.load_dict()
            new_key = _create_key_file(self._home)
            self._key = new_key
            # Drop the cached Fernet — it was built from the old key.
            self._fernet_instance = None
            # Re-encrypt plaintext values that may have been stored.
            re_encrypted: dict[str, list[dict[str, Any]]] = {}
            for provider, records in old_data.items():
                new_records: list[dict[str, Any]] = []
                for rec in records:
                    val = rec.get("value_b64", "")
                    if val and not val.startswith("gAAAAA"):
                        val = self.encrypt(val)
                    new_records.append({**rec, "value_b64": val})
                re_encrypted[provider] = new_records
            self.save_dict(re_encrypted)
            return new_key