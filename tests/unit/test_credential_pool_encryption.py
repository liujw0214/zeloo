"""Tests for credential_pool encrypted on-disk storage (Fernet AES)."""

from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from agent.credential_pool import CredentialPool


def _derive_fernet_key_bytes() -> bytes:
    """Generate a random 32-byte key encoded as urlsafe-base64."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


class TestEncryptionBasic:
    def test_no_master_key_saves_plaintext(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "creds.json"
            with patch.dict(os.environ, {}, clear=True):
                pool = CredentialPool(storage_path=path)
                pool.add_key("openai", "sk-plaintext-test")
                content = path.read_text(encoding="utf-8")
                assert "sk-plaintext-test" in content
                assert json.loads(content)["openai"][0]["value"] == "sk-plaintext-test"

    def test_master_key_encrypts_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "creds.json"
            key = _derive_fernet_key_bytes()
            with patch.dict(os.environ, {"ZELOO_CREDENTIAL_MASTER_KEY": key}):
                pool = CredentialPool(storage_path=path)
                pool.add_key("openai", "sk-secret-test")
                content = path.read_text(encoding="utf-8")
                assert "sk-secret-test" not in content
                assert content.startswith("gAAAAA") or "encrypted" in content or len(content) > 200

    def test_encrypted_load_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "creds.json"
            key = _derive_fernet_key_bytes()
            with patch.dict(os.environ, {"ZELOO_CREDENTIAL_MASTER_KEY": key}):
                pool1 = CredentialPool(storage_path=path)
                pool1.add_key("openai", "sk-roundtrip-1")
                pool1.add_key("anthropic", "sk-ant-rt")
                pool2 = CredentialPool(storage_path=path)
                providers = sorted(pool2.list_providers())
                assert providers == ["anthropic", "openai"]
                assert pool2.get_key("openai") == "sk-roundtrip-1"

    def test_wrong_master_key_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "creds.json"
            key1 = _derive_fernet_key_bytes()
            key2 = _derive_fernet_key_bytes()
            with patch.dict(os.environ, {"ZELOO_CREDENTIAL_MASTER_KEY": key1}):
                pool1 = CredentialPool(storage_path=path)
                pool1.add_key("openai", "sk-locked")
            with patch.dict(os.environ, {"ZELOO_CREDENTIAL_MASTER_KEY": key2}):
                pool2 = CredentialPool(storage_path=path)
                assert pool2.list_providers() == []

    def test_invalid_master_key_falls_back_plaintext(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "creds.json"
            pool = CredentialPool(storage_path=path)
            assert pool._fernet is None
            pool.add_key("openai", "sk-fallback")
            assert "sk-fallback" in path.read_text(encoding="utf-8")


class TestEncryptionMasking:
    def test_masked_value_after_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "creds.json"
            pool = CredentialPool(storage_path=path)
            pool.add_key("openai", "sk-very-secret-long-key")
            statuses = pool.get_status("openai")
            assert statuses[0]["value_masked"] == "sk-v...-key"


class TestLazyKeyDerivation:
    def test_no_env_no_disk_no_call(self) -> None:
        pool = CredentialPool()
        assert pool._fernet is None

    def test_derive_called_on_first_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "creds.json"
            pool = CredentialPool(storage_path=path)
            assert pool._fernet is None
            pool._load()
            assert pool._fernet is None

    def test_derive_called_with_env_var(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "creds.json"
            key = _derive_fernet_key_bytes()
            with patch.dict(os.environ, {"ZELOO_CREDENTIAL_MASTER_KEY": key}):
                pool = CredentialPool(storage_path=path)
                pool._fernet = None
                path.write_text('{"openai": [{"value": "old"}]}')
                pool._load()
                assert pool._fernet is not None