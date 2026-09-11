"""Credential pool — centralized management of API keys and secrets.

This module provides:
- Multiple API keys per provider with round-robin rotation
- Automatic key removal on authentication failures (401/403)
- Circuit-breaker style key cooldown after repeated failures
- Fernet AES encrypted on-disk storage (ZELOO_CREDENTIAL_MASTER_KEY env var)
- Environment variable fallback

Usage::

    from agent.credential_pool import CredentialPool

    pool = CredentialPool()
    pool.add_key("openai", "sk-...", label="primary")
    key = pool.get_key("openai")  # round-robin
    pool.report_failure("openai", key, status_code=401)  # removes bad key
    pool.report_success("openai", new_key)  # resets cooldown
"""
from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from cryptography.fernet import Fernet as _Fernet  # noqa: PLC0415
    FERNET = _Fernet
except ImportError:
    FERNET = None

logger = logging.getLogger(__name__)


@dataclass
class Credential:
    value: str
    label: str = "default"
    provider: str = ""
    created_at: float = field(default_factory=time.time)
    last_used: float = 0.0
    failure_count: int = 0
    cooldown_until: float = 0.0
    disabled: bool = False

    @property
    def is_available(self) -> bool:
        if self.disabled:
            return False
        if self.cooldown_until and time.time() < self.cooldown_until:
            return False
        return True

    def mark_used(self) -> None:
        self.last_used = time.time()

    def mark_failure(self, cooldown_seconds: float = 300.0) -> None:
        self.failure_count += 1
        if cooldown_seconds > 0:
            self.cooldown_until = time.time() + cooldown_seconds

    def mark_success(self) -> None:
        self.failure_count = 0
        self.cooldown_until = 0.0
        self.disabled = False


class CredentialPool:
    _fernet: Any | None

    def __init__(
        self,
        storage_path: str | Path | None = None,
        cooldown_seconds: float = 300.0,
        max_failures: int = 3,
    ) -> None:
        self._storage_path = Path(storage_path) if storage_path else None
        self._cooldown_seconds = cooldown_seconds
        self._max_failures = max_failures
        self._fernet: Any | None = None
        self._lock = threading.Lock()
        self._credentials: dict[str, list[Credential]] = {}
        self._rr_index: dict[str, int] = {}
        self._load()

    def _derive_key(self) -> Any | None:
        master_b64 = os.environ.get("ZELOO_CREDENTIAL_MASTER_KEY", "")
        if not master_b64:
            return None
        if FERNET is None:
            return None
        try:
            key_bytes = base64.urlsafe_b64decode(master_b64.encode())
            if len(key_bytes) != 32:
                key_bytes = key_bytes.ljust(32, b"\x00")[:32]
            return FERNET(base64.urlsafe_b64encode(key_bytes))
        except Exception:  # noqa: BLE001
            logger.warning("ZELOO_CREDENTIAL_MASTER_KEY invalid — credentials NOT encrypted")
            return None

    def _load(self) -> None:
        if self._fernet is None:
            self._fernet = self._derive_key()
        if not self._storage_path or not self._storage_path.exists():
            return
        try:
            cipher_text = self._storage_path.read_text(encoding="utf-8")
            plain = cipher_text
            if self._fernet:
                try:
                    plain = self._fernet.decrypt(cipher_text.encode()).decode()
                except Exception:  # noqa: BLE001
                    pass
            data = json.loads(plain)
            for provider, creds in data.items():
                for c in creds:
                    cred = Credential(
                        value=c["value"],
                        label=c.get("label", "default"),
                        provider=provider,
                        created_at=c.get("created_at", time.time()),
                        last_used=c.get("last_used", 0.0),
                        failure_count=c.get("failure_count", 0),
                        cooldown_until=c.get("cooldown_until", 0.0),
                        disabled=c.get("disabled", False),
                    )
                    self._credentials.setdefault(provider, []).append(cred)
            logger.info("Loaded credentials for %d provider(s)", len(self._credentials))
        except Exception:
            logger.exception("Failed to load credentials from %s", self._storage_path)

    def _save(self) -> None:
        if self._fernet is None:
            self._fernet = self._derive_key()
        if not self._storage_path:
            return
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            data: dict[str, list[dict[str, Any]]] = {}
            for provider, creds in self._credentials.items():
                data[provider] = [
                    {
                        "value": c.value,
                        "label": c.label,
                        "created_at": c.created_at,
                        "last_used": c.last_used,
                        "failure_count": c.failure_count,
                        "cooldown_until": c.cooldown_until,
                        "disabled": c.disabled,
                    }
                    for c in creds
                ]
            plain = json.dumps(data, indent=2)
            if self._fernet:
                plain = self._fernet.encrypt(plain.encode()).decode()
            self._storage_path.write_text(plain, encoding="utf-8")
            try:
                os.chmod(self._storage_path, 0o600)
            except OSError:
                pass
        except Exception:
            logger.exception("Failed to save credentials to %s", self._storage_path)

    def add_key(
        self,
        provider: str,
        value: str,
        label: str = "default",
    ) -> None:
        with self._lock:
            cred = Credential(value=value, label=label, provider=provider)
            self._credentials.setdefault(provider, []).append(cred)
            self._save()
            logger.info("Added credential '%s' for '%s'", label, provider)

    def remove_key(self, provider: str, label: str) -> bool:
        with self._lock:
            creds = self._credentials.get(provider, [])
            original = len(creds)
            self._credentials[provider] = [c for c in creds if c.label != label]
            removed = len(self._credentials[provider]) < original
            if removed:
                self._save()
                logger.info("Removed credential '%s' from '%s'", label, provider)
            return removed

    def get_key(self, provider: str) -> str | None:
        with self._lock:
            creds = self._credentials.get(provider, [])
            available = [c for c in creds if c.is_available]
            if not available:
                env_val = os.environ.get(f"ZELOO_{provider.upper()}_API_KEY", "")
                if env_val:
                    return env_val
                return None
            idx = self._rr_index.get(provider, 0) % len(available)
            cred = available[idx]
            self._rr_index[provider] = idx + 1
            cred.mark_used()
            return cred.value

    def report_failure(
        self,
        provider: str,
        key_value: str,
        status_code: int | None = None,
    ) -> None:
        with self._lock:
            for cred in self._credentials.get(provider, []):
                if cred.value != key_value:
                    continue
                if status_code in (401, 403):
                    cred.disabled = True
                    logger.warning(
                        "Credential '%s' for '%s' PERMABANNED (auth failure %s)",
                        cred.label,
                        provider,
                        status_code,
                    )
                else:
                    cred.mark_failure(self._cooldown_seconds)
                    if cred.failure_count >= self._max_failures:
                        cred.disabled = True
                        logger.warning(
                            "Credential '%s' for '%s' circuit-broken after %d failures",
                            cred.label,
                            provider,
                            cred.failure_count,
                        )
                self._save()
                break

    def report_success(self, provider: str, key_value: str) -> None:
        with self._lock:
            for cred in self._credentials.get(provider, []):
                if cred.value == key_value:
                    cred.mark_success()
                    self._save()
                    break

    def list_providers(self) -> list[str]:
        with self._lock:
            return sorted(self._credentials.keys())

    def get_status(self, provider: str) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "label": c.label,
                    "available": c.is_available,
                    "failure_count": c.failure_count,
                    "cooldown_until": c.cooldown_until,
                    "disabled": c.disabled,
                    "value_masked": _mask_value(c.value),
                }
                for c in self._credentials.get(provider, [])
            ]

    def clear(self) -> None:
        with self._lock:
            self._credentials.clear()
            self._rr_index.clear()
            self._save()


def _mask_value(value: str) -> str:
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"
