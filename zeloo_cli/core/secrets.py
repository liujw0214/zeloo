"""Secrets management — secure credential storage and rotation."""

from __future__ import annotations

import base64
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class Secret:
    """A stored secret value."""

    key: str
    value: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    expires_at: float | None = None
    rotation_count: int = 0
    access_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class SecretManager:
    """Manage secrets with encryption, rotation, and access tracking.

    Uses base64 encoding (not strong encryption, but safe for
    transport and stored config). For production use, integrate
    with proper KMS / vault (Vault, AWS Secrets Manager, etc.).
    """

    def __init__(self, encryption_key: str | None = None) -> None:
        self._secrets: dict[str, Secret] = {}
        self._encryption_key = encryption_key or os.environ.get(
            "zeloo_SECRET_KEY", "default-key-change-me"
        )
        self._lock = threading.Lock()
        self._audit_log: list[dict[str, Any]] = []
        self._max_audit = 1000

    def set(
        self,
        key: str,
        value: str,
        expires_at: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Store or update a secret."""
        encoded = self._encode(value)
        with self._lock:
            existing = self._secrets.get(key)
            rotation_count = 0 if existing is None else existing.rotation_count + 1
            self._secrets[key] = Secret(
                key=key,
                value=encoded,
                expires_at=expires_at,
                rotation_count=rotation_count,
                metadata=metadata or {},
            )
            self._audit("set", key)

    def get(self, key: str) -> str | None:
        """Retrieve and decode a secret."""
        with self._lock:
            secret = self._secrets.get(key)
            if secret is None:
                self._audit("miss", key)
                return None
            if secret.expires_at is not None and time.time() > secret.expires_at:
                self._audit("expired", key)
                return None
            secret.access_count += 1
            self._audit("get", key)
            return self._decode(secret.value)

    def rotate(self, key: str, new_value: str) -> bool:
        """Rotate a secret to a new value."""
        with self._lock:
            secret = self._secrets.get(key)
            if secret is None:
                return False
            secret.value = self._encode(new_value)
            secret.updated_at = time.time()
            secret.rotation_count += 1
            secret.access_count = 0
            self._audit("rotate", key)
        return True

    def delete(self, key: str) -> bool:
        with self._lock:
            deleted = self._secrets.pop(key, None) is not None
            if deleted:
                self._audit("delete", key)
        return deleted

    def list_keys(self) -> list[str]:
        with self._lock:
            return list(self._secrets.keys())

    def audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._audit_log[-limit:])

    def _encode(self, value: str) -> str:
        if not self._encryption_key:
            return value
        key_bytes = self._encryption_key.encode("utf-8")
        value_bytes = value.encode("utf-8")
        key_len = len(key_bytes)
        encoded = bytes(
            v ^ key_bytes[i % key_len] for i, v in enumerate(value_bytes)
        )
        return base64.b64encode(encoded).decode("utf-8")

    def _decode(self, encoded: str) -> str:
        if not self._encryption_key:
            return encoded
        try:
            key_bytes = self._encryption_key.encode("utf-8")
            encoded_bytes = base64.b64decode(encoded.encode("utf-8"))
            key_len = len(key_bytes)
            decoded = bytes(
                v ^ key_bytes[i % key_len] for i, v in enumerate(encoded_bytes)
            )
            return decoded.decode("utf-8")
        except Exception:
            return encoded

    def _audit(self, action: str, key: str) -> None:
        self._audit_log.append({
            "action": action,
            "key": key,
            "timestamp": time.time(),
        })
        if len(self._audit_log) > self._max_audit:
            self._audit_log = self._audit_log[-self._max_audit:]


__all__ = ["Secret", "SecretManager"]