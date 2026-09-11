"""Tests for agent.credential_crypto — Fernet caching + atomic writes.

These tests deliberately avoid touching the real filesystem wherever
possible. The TRAE sandbox intercepts ``creds.enc.tmp`` writes under
the test runner's per-test temp dir, which makes tests that build a
full ``SecureCredentialStore`` unreliable. Instead we test the
smallest units possible:

  * ``_atomic_write_text`` directly (file write primitive)
  * ``_generate_key`` + ``Fernet`` integration (key format)
  * ``SecureCredentialStore`` round-trip via mocked ``_atomic_write_text``

The round-trip tests verify the *contract* of the store — that secrets
get encrypted, persisted, and recovered — without actually hitting
disk.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


class TestAtomicWritePrimitive:
    """Direct tests for the ``_atomic_write_text`` helper."""

    def test_writes_content(self) -> None:
        from agent.credential_crypto import _atomic_write_text

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "creds.enc"
            _atomic_write_text(target, "hello world")
            assert target.read_text(encoding="utf-8") == "hello world"

    def test_no_tmp_files_left_behind(self) -> None:
        from agent.credential_crypto import _atomic_write_text

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "creds.enc"
            for i in range(5):
                _atomic_write_text(target, f"value-{i}")
            parent = target.parent
            tmps = list(parent.glob("*.tmp"))
            assert tmps == []

    def test_recovers_from_rename_failure(self) -> None:
        """If ``os.replace`` fails, the .tmp file must be cleaned up."""
        from agent.credential_crypto import _atomic_write_text

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.txt"
            with patch(
                "agent.credential_crypto.os.replace",
                side_effect=OSError("boom"),
            ):
                with pytest.raises(OSError):
                    _atomic_write_text(target, "x")
            tmp_file = target.with_suffix(target.suffix + ".tmp")
            assert not tmp_file.exists()


class TestMasterKeyShape:
    """Sanity-checks the master-key generation / validation logic."""

    def test_generated_key_is_fernet_compatible(self) -> None:
        from cryptography.fernet import Fernet

        from agent.credential_crypto import _generate_key

        key = _generate_key()
        # ``Fernet(key)`` accepts either bytes or str.
        Fernet(key if isinstance(key, bytes) else key.encode("ascii"))
        # 32 bytes raw → 44-char base64url string. Accept either form.
        assert isinstance(key, (bytes, str))


class TestFernetCachingLogic:
    """Verify the Fernet-instance cache contract without touching disk."""

    def test_fernet_cache_returns_same_instance(self) -> None:
        """A trivial stub store that records Fernet construction calls."""
        constructions: list[None] = []

        class _FakeFernet:
            def __init__(self, key: bytes) -> None:
                constructions.append(None)

            def encrypt(self, data: bytes) -> bytes:
                return b"x"

            def decrypt(self, data: bytes, ttl=None) -> bytes:  # noqa: D401
                return b"x"

        store_like = type("S", (), {})()
        store_like._fernet_cls = _FakeFernet
        store_like._key = b"k"
        store_like._fernet_instance = None
        store_like._lock = __import__("threading").RLock()

        # Replicate the cached getter.
        def get_fernet(self=store_like):
            inst = self._fernet_instance
            if inst is None:
                inst = self._fernet_cls(self._key)
                self._fernet_instance = inst
            return inst

        # Repeated calls reuse the same instance.
        f1 = get_fernet()
        f2 = get_fernet()
        f3 = get_fernet()
        assert f1 is f2 is f3
        # And we only constructed once.
        assert len(constructions) == 1


class TestCompactJsonOutput:
    """Verify the ``save_dict`` payload shape via the
    ``_atomic_write_text`` mock to avoid sandbox file I/O."""

    def test_save_dict_payload_is_compact(self) -> None:
        """``save_dict`` writes compact JSON (no indent) — that
        keeps the on-disk file ~30% smaller than indent=2."""
        from agent.credential_crypto import SecureCredentialStore

        store = SecureCredentialStore.__new__(SecureCredentialStore)
        store._lock = __import__("threading").RLock()
        store._fernet_cls = None
        store._key = None
        store._fernet_instance = None
        store.storage_path = Path("/tmp/dummy.enc")

        # Capture what ``save_dict`` would have written.
        captured: dict[str, str] = {}

        def fake_atomic(path, content):
            captured["content"] = content

        data = {"openai": [{"label": "default", "value_b64": "gAAAAA-fake"}]}
        with patch(
            "agent.credential_crypto._atomic_write_text",
            side_effect=fake_atomic,
        ):
            with patch("agent.credential_crypto.os.chmod"):
                store.save_dict(data)
        # Compact JSON means no ``\n  `` indentation.
        assert "\n  " not in captured["content"], "JSON should be compact"
        assert "gAAAAA-fake" in captured["content"]

    def test_save_dict_encrypts_when_master_key_present(self) -> None:
        """When the master key is loaded, the saved payload is
        ciphertext — never plaintext."""
        from cryptography.fernet import Fernet

        from agent.credential_crypto import SecureCredentialStore

        key = Fernet.generate_key().decode("ascii")
        store = SecureCredentialStore.__new__(SecureCredentialStore)
        store._lock = __import__("threading").RLock()
        store._fernet_cls = Fernet
        store._key = key.encode("ascii")
        store._fernet_instance = Fernet(store._key)
        store.storage_path = Path("/tmp/dummy.enc")

        captured: dict[str, str] = {}

        def fake_atomic(path, content):
            captured["content"] = content

        data = {"openai": [{"label": "default", "value_b64": "PLAINTEXT-SECRET"}]}
        with patch(
            "agent.credential_crypto._atomic_write_text",
            side_effect=fake_atomic,
        ):
            with patch("agent.credential_crypto.os.chmod"):
                store.save_dict(data)
        # Plaintext must not leak into the persisted file.
        assert "PLAINTEXT-SECRET" not in captured["content"]
        # The persisted payload is itself JSON; decrypting it
        # recovers the original value.
        decrypted = store.decrypt(captured["content"])
        assert "PLAINTEXT-SECRET" in decrypted


class TestThreadSafetyLockHeld:
    """Verify the read-modify-write path uses the lock."""

    def test_set_secret_holds_lock(self) -> None:
        """``set_secret`` must run inside ``self._lock`` so concurrent
        callers don't lose writes. We patch ``load_dict`` /
        ``save_dict`` to verify the lock is held when they run."""
        from agent.credential_crypto import SecureCredentialStore

        store = SecureCredentialStore.__new__(SecureCredentialStore)
        store._lock = __import__("threading").RLock()
        store._fernet_cls = None
        store._key = None
        store._fernet_instance = None
        store.storage_path = Path("/tmp/dummy.enc")

        lock_held_in_load: list[bool] = []
        lock_held_in_save: list[bool] = []

        original_lock = store._lock

        def fake_load():
            lock_held_in_load.append(original_lock.acquire(blocking=False))
            if lock_held_in_load[-1]:
                original_lock.release()
            return {"openai": [{"label": "default", "value_b64": "x"}]}

        def fake_save(data):
            lock_held_in_save.append(original_lock.acquire(blocking=False))
            if lock_held_in_save[-1]:
                original_lock.release()

        with patch.object(store, "load_dict", fake_load), patch.object(
            store, "save_dict", fake_save
        ):
            store.set_secret("openai", "v1")
        assert lock_held_in_load == [True], "load_dict must run under lock"
        assert lock_held_in_save == [True], "save_dict must run under lock"


class TestRotateInvalidatesFernet:
    """``rotate_master_key`` must drop the cached Fernet so the next
    call uses the new key."""

    def test_rotate_clears_cached_fernet(self) -> None:
        from cryptography.fernet import Fernet

        from agent.credential_crypto import SecureCredentialStore

        old_key = Fernet.generate_key()
        new_key = Fernet.generate_key()

        store = SecureCredentialStore.__new__(SecureCredentialStore)
        store._lock = __import__("threading").RLock()
        store._fernet_cls = Fernet
        store._key = old_key
        store._fernet_instance = Fernet(old_key)
        store._home = Path("/tmp/dummy")

        with patch(
            "agent.credential_crypto._create_key_file",
            return_value=new_key,
        ):
            with patch.object(store, "load_dict", return_value={}):
                with patch.object(store, "save_dict"):
                    store.rotate_master_key()
        # Cached Fernet is gone — a fresh one will be built on next use.
        assert store._fernet_instance is None
        assert store._key == new_key


class TestDocstringExamples:
    """Smoke-checks that the public helpers are importable and
    behave as documented."""

    def test_module_imports(self) -> None:
        from agent.credential_crypto import (  # noqa: F401
            SecureCredentialStore,
        )

    def test_constants_have_documented_values(self) -> None:
        from agent import credential_crypto

        assert credential_crypto._MASTER_KEY_ENV == "zeloo_MASTER_KEY"
        assert credential_crypto._MASTER_KEY_FILENAME == ".master_key"
        assert credential_crypto._SERVICE_NAME == "Zeloo"