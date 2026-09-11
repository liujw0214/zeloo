"""Encryption layer for WAL segments and snapshot backups.

The :class:`SegmentCipher` wraps Fernet (AES-128-CBC + HMAC-SHA256) so that
``PITREngine.archive_segment()`` can produce at-rest ciphertext when
shipping WAL frames off-host.

Key material
============

The cipher shares the master-key resolution pipeline with
``agent.credential_crypto.SecureCredentialStore``:

1. ``zeloo_MASTER_KEY`` env var (base64url-encoded Fernet key)
2. OS keyring (via the optional ``keyring`` package)
3. ``~/.Zeloo/.master_key`` (mode 0600, generated on first use)

Reusing the existing master key means we never have two secrets to
back up — the credentials file and the WAL archive both encrypt under
the same key. Operators only need to remember one passphrase / key
backup.

On-disk format
==============

Encrypted segments extend the existing header (see
``zeloo_state.pitr``) with a small envelope::

    ┌────────────────────────────────────────────────────────┐
    │  Header (24 bytes)                                      │
    │  ├─ magic "ZWAL" (4B)                                   │
    │  ├─ version uint32 LE (4B)                              │
    │  ├─ start_ts int64 LE (8B)                              │
    │  └─ end_ts int64 LE (8B)                                │
    ├────────────────────────────────────────────────────────┤
    │  Cipher envelope (variable)                             │
    │  ├─ flags uint8 (0x01 = encrypted, 0x00 = plaintext)   │
    │  ├─ ciphertext length uint32 BE (4B, when encrypted)   │
    │  └─ ciphertext bytes (Fernet token, URL-safe b64)      │
    └────────────────────────────────────────────────────────┘

The ``flags`` byte lets the engine transparently read both
encrypted and legacy plaintext segments — important when rolling
forward: an upgrade must not invalidate the archive dir. The
length prefix lets us read the ciphertext in O(1) without scanning
for a delimiter.

Security notes
==============

* **Authenticated encryption.** Fernet already includes
  AES-128-CBC + HMAC-SHA256 + a per-message random IV. Any bit
  flip in transit causes decryption to fail loudly.
* **No key in segment file.** Only the ciphertext lives on disk.
  The master key is in the operator's keyring / env / config.
* **No per-segment keys.** A single Fernet key protects every
  segment. Rotation is handled at the master-key layer; we don't
  embed per-segment keys (would defeat the purpose — they'd have
  to live next to the ciphertext).
"""

from __future__ import annotations

import logging
import os
import struct
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── on-disk envelope ──────────────────────────────────────────────────


#: Flag byte indicating the segment payload is encrypted.
FLAG_ENCRYPTED: int = 0x01

#: Flag byte indicating plaintext (legacy format).
FLAG_PLAINTEXT: int = 0x00

#: Length-prefix struct (uint32 big-endian). The big-endian choice
#: matches the typical network-byte-order convention and keeps the
#: format explicit when packet-captured.
_LENGTH_STRUCT = struct.Struct(">I")


def _try_import_cryptography() -> tuple[Any, Any]:
    """Return ``(Fernet, InvalidToken)`` or ``(None, None)``."""
    try:
        from cryptography.fernet import Fernet, InvalidToken  # type: ignore[import-untyped]

        return Fernet, InvalidToken
    except ImportError:
        return None, None


# ── key resolution ─────────────────────────────────────────────────────


_MASTER_KEY_ENV = "zeloo_MASTER_KEY"
_MASTER_KEY_FILENAME = ".master_key"


def _find_zeloo_home() -> Path:
    """Locate ``~/.Zeloo`` (or ``$zeloo_HOME``)."""
    env_home = os.environ.get("zeloo_HOME")
    if env_home:
        return Path(env_home)
    return Path.home() / ".Zeloo"


def _load_master_key(home: Path) -> bytes | None:
    """Return the base64url-encoded Fernet key, or None if absent.

    Tries env → keyring → file, in that order.
    """
    env_key = os.environ.get(_MASTER_KEY_ENV)
    if env_key:
        Fernet, _ = _try_import_cryptography()
        if Fernet is not None:
            try:
                Fernet(env_key.encode("ascii"))
            except Exception:
                logger.warning("%s is malformed; ignoring", _MASTER_KEY_ENV)
                # Fall through to keyring / file — don't lock out the
                # operator just because one source is corrupt.
                env_key = None
        if env_key:
            return env_key.encode("ascii") if isinstance(env_key, str) else env_key

    try:
        import keyring  # type: ignore[import-untyped]

        stored = keyring.get_password("Zeloo", "master_key")
        if stored:
            Fernet, _ = _try_import_cryptography()
            if Fernet is not None:
                Fernet(stored.encode("ascii"))
            return stored.encode("ascii")
    except Exception:
        logger.debug("keyring backend unavailable")

    key_path = home / _MASTER_KEY_FILENAME
    if key_path.is_file():
        try:
            stored = key_path.read_text(encoding="utf-8").strip()
            Fernet, _ = _try_import_cryptography()
            if Fernet is not None:
                Fernet(stored.encode("ascii"))
            return stored.encode("ascii")
        except Exception as exc:
            logger.warning("Failed to read master key file: %s", exc)

    return None


def _persist_master_key(key_bytes: bytes, home: Path) -> None:
    """Write the Fernet key to ``$HOME/.Zeloo/.master_key`` with 0600.

    ``key_bytes`` is the *base64url-encoded* form returned by
    :meth:`Fernet.generate_key` — Fernet expects exactly that string
    when constructed, so we write it as-is (no re-encoding).

    We don't try the keyring here — that's the credential_crypto
    module's concern. The cipher is happy to fall back to the file.
    """
    # Fernet.generate_key() already returns base64url-encoded bytes.
    encoded = key_bytes.decode("ascii") if isinstance(key_bytes, bytes) else key_bytes
    key_path = home / _MASTER_KEY_FILENAME
    key_path.parent.mkdir(parents=True, exist_ok=True)
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


def _generate_master_key() -> bytes:
    """Return a fresh Fernet key (base64url-encoded 32-byte string)."""
    Fernet, _ = _try_import_cryptography()
    if Fernet is None:
        raise RuntimeError(
            "cryptography package required for segment encryption. "
            "Install with: pip install cryptography"
        )
    return Fernet.generate_key()


# ── cipher ────────────────────────────────────────────────────────────


class SegmentCipher:
    """Authenticated encryption for WAL segments and snapshots.

    The cipher is *passive* — it does not own a key file. It
    resolves the master key lazily on first encrypt/decrypt and
    caches the Fernet instance for reuse.

    Args:
        home: Directory used to resolve ``.master_key``. Defaults
            to ``~/.Zeloo`` (or ``$zeloo_HOME``).
        auto_generate: When True, generate and persist a fresh key
            if none is found. When False (default), fail with
            ``RuntimeError`` instead. CLI / production code should
            leave this off and rely on the operator having bootstrapped
            the key via ``zeloo init`` or the credential crypto path.
    """

    def __init__(self, *, home: Path | None = None, auto_generate: bool = False) -> None:
        self.home = Path(home if home is not None else _find_zeloo_home())
        self._fernet_cls, self._invalid_token = _try_import_cryptography()
        self._key: bytes | None = None
        self._fernet_instance: Any | None = None
        self._auto_generate = auto_generate
        if self._fernet_cls is None:
            logger.warning(
                "cryptography not available; SegmentCipher will refuse to "
                "encrypt or decrypt. Install: pip install cryptography"
            )

    @property
    def is_available(self) -> bool:
        """True if the cryptography library is importable."""
        return self._fernet_cls is not None

    @property
    def is_ready(self) -> bool:
        """True if a master key has been resolved."""
        return self._key is not None

    def ensure_key(self) -> bytes:
        """Resolve (and optionally generate) the master key."""
        if self._key is not None:
            return self._key
        if self._fernet_cls is None:
            raise RuntimeError("cryptography package is required for encryption")

        key = _load_master_key(self.home)
        if key is None:
            if not self._auto_generate:
                raise RuntimeError(
                    f"No master key found under {self.home}. Set "
                    f"{_MASTER_KEY_ENV} or initialise via SecureCredentialStore."
                )
            key = _generate_master_key()
            _persist_master_key(key, self.home)
            logger.info("Generated new master key at %s", self.home / _MASTER_KEY_FILENAME)
        self._key = key
        return key

    def _fernet(self) -> Any:
        """Return the cached Fernet instance."""
        if self._fernet_instance is None:
            self.ensure_key()
            self._fernet_instance = self._fernet_cls(self._key)
        return self._fernet_instance

    # ── public API ──────────────────────────────────────────────

    def encrypt(self, plaintext: bytes) -> bytes:
        """Encrypt *plaintext*, return the wire format envelope.

        Wire format::

            0x01 │ len(ciphertext) BE uint32 │ ciphertext

        ``len(ciphertext)`` is the byte length of the Fernet token,
        included so callers can read the envelope without scanning.
        """
        if not self.is_available:
            raise RuntimeError("cryptography package is required for encryption")
        token = self._fernet().encrypt(plaintext)
        return (
            bytes([FLAG_ENCRYPTED])
            + _LENGTH_STRUCT.pack(len(token))
            + token
        )

    def decrypt(self, envelope: bytes) -> bytes:
        """Decrypt an envelope produced by :meth:`encrypt`.

        Raises ``ValueError`` if the envelope is malformed, the
        ciphertext has been tampered with, or the master key has
        changed since encryption.
        """
        if not self.is_available:
            raise RuntimeError("cryptography package is required for decryption")
        if not envelope:
            raise ValueError("empty envelope")
        flag = envelope[0]
        if flag == FLAG_PLAINTEXT:
            # Defensive: callers should branch on the flag themselves,
            # but accepting plaintext here keeps the API symmetric.
            return envelope[1:]
        if flag != FLAG_ENCRYPTED:
            raise ValueError(f"unknown cipher flag: {flag:#x}")
        if len(envelope) < 1 + _LENGTH_STRUCT.size:
            raise ValueError("envelope too short for length prefix")
        (length,) = _LENGTH_STRUCT.unpack_from(envelope, 1)
        payload = envelope[1 + _LENGTH_STRUCT.size :]
        if len(payload) != length:
            raise ValueError(
                f"envelope length mismatch: header says {length}, "
                f"got {len(payload)}"
            )
        try:
            return self._fernet().decrypt(payload)
        except self._invalid_token as exc:
            raise ValueError("ciphertext tampered or wrong master key") from exc

    # ── header-only helpers ─────────────────────────────────────

    def encrypt_payload(self, plaintext: bytes, header: bytes) -> bytes:
        """Build a complete segment file: ``header + envelope(plaintext)``.

        Convenience wrapper used by :meth:`PITREngine.archive_segment`
        when encryption is enabled.
        """
        return header + self.encrypt(plaintext)

    def decrypt_payload(self, raw: bytes, header_size: int) -> bytes:
        """Read a segment file and return the plaintext payload.

        ``header_size`` is the size of the *outer* (non-cipher)
        header — typically 24 bytes from :mod:`zeloo_state.pitr`.
        Returns plaintext regardless of whether the segment was
        encrypted or written in legacy plaintext mode.
        """
        if len(raw) <= header_size:
            raise ValueError("segment too short to contain a payload")
        envelope = raw[header_size:]
        flag = envelope[0] if envelope else FLAG_PLAINTEXT
        if flag == FLAG_ENCRYPTED:
            return self.decrypt(envelope)
        return envelope  # legacy plaintext

    def is_encrypted_segment(self, raw: bytes, header_size: int) -> bool:
        """Inspect a segment file and return True iff it's encrypted.

        Used by :meth:`PITREngine.list_segments` and the restore path
        so we can log the encryption status without decrypting.
        """
        if len(raw) <= header_size:
            return False
        flag = raw[header_size]
        return flag == FLAG_ENCRYPTED


__all__ = [
    "SegmentCipher",
    "FLAG_ENCRYPTED",
    "FLAG_PLAINTEXT",
]