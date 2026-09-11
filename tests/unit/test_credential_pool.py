"""Tests for agent/credential_pool.py — credential pool, round-robin, circuit breaking."""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path

import pytest

from agent.credential_pool import Credential, CredentialPool


class TestCredential:
    def test_instantiation(self) -> None:
        cred = Credential(value="sk-test-123", label="primary", provider="openai")
        assert cred.value == "sk-test-123"
        assert cred.label == "primary"
        assert cred.provider == "openai"
        assert cred.failure_count == 0
        assert cred.disabled is False
        assert cred.is_available is True

    def test_is_available_disabled(self) -> None:
        cred = Credential(value="sk-test", disabled=True)
        assert cred.is_available is False

    def test_is_available_on_cooldown(self) -> None:
        cred = Credential(value="sk-test")
        cred.cooldown_until = time.time() + 3600
        assert cred.is_available is False

    def test_is_available_cooldown_expired(self) -> None:
        cred = Credential(value="sk-test")
        cred.cooldown_until = time.time() - 1
        assert cred.is_available is True

    def test_mark_used_updates_timestamp(self) -> None:
        cred = Credential(value="sk-test")
        time.sleep(0.01)
        before = cred.last_used
        cred.mark_used()
        assert cred.last_used > before

    def test_mark_failure_increments_count(self) -> None:
        cred = Credential(value="sk-test")
        assert cred.failure_count == 0
        cred.mark_failure()
        assert cred.failure_count == 1
        cred.mark_failure()
        assert cred.failure_count == 2

    def test_mark_failure_sets_cooldown(self) -> None:
        cred = Credential(value="sk-test")
        assert cred.cooldown_until == 0.0
        cred.mark_failure(cooldown_seconds=60.0)
        assert cred.cooldown_until > time.time()

    def test_mark_failure_with_zero_cooldown(self) -> None:
        cred = Credential(value="sk-test")
        cred.mark_failure(cooldown_seconds=0.0)
        assert cred.cooldown_until == 0.0


class TestCredentialPoolBasics:
    def test_empty_pool_returns_none(self) -> None:
        pool = CredentialPool()
        assert pool.get_key("openai") is None

    def test_add_key(self) -> None:
        pool = CredentialPool()
        pool.add_key("openai", "sk-key1", label="primary")
        assert pool.get_key("openai") == "sk-key1"

    def test_remove_key(self) -> None:
        pool = CredentialPool()
        pool.add_key("openai", "sk-key1", label="primary")
        pool.add_key("openai", "sk-key2", label="secondary")
        assert pool.remove_key("openai", "primary") is True
        assert pool.get_key("openai") == "sk-key2"

    def test_remove_nonexistent_returns_false(self) -> None:
        pool = CredentialPool()
        pool.add_key("openai", "sk-key1")
        assert pool.remove_key("openai", "nonexistent") is False

    def test_list_providers(self) -> None:
        pool = CredentialPool()
        pool.add_key("openai", "sk-key1")
        pool.add_key("anthropic", "sk-ant-key")
        assert sorted(pool.list_providers()) == ["anthropic", "openai"]

    def test_clear(self) -> None:
        pool = CredentialPool()
        pool.add_key("openai", "sk-key1")
        pool.add_key("anthropic", "sk-ant-key")
        pool.clear()
        assert pool.list_providers() == []
        assert pool.get_key("openai") is None


class TestRoundRobin:
    def test_round_robin_rotation(self) -> None:
        pool = CredentialPool()
        pool.add_key("openai", "key1", label="k1")
        pool.add_key("openai", "key2", label="k2")
        pool.add_key("openai", "key3", label="k3")
        seen = [pool.get_key("openai") for _ in range(6)]
        assert seen == ["key1", "key2", "key3", "key1", "key2", "key3"]

    def test_round_robin_skips_disabled(self) -> None:
        pool = CredentialPool(cooldown_seconds=0.0, max_failures=1)
        pool.add_key("openai", "key1", label="k1")
        pool.add_key("openai", "key2", label="k2")
        pool.report_failure("openai", "key1", status_code=500)
        keys = [pool.get_key("openai") for _ in range(4)]
        assert all(k == "key2" for k in keys)


class TestAuthFailure:
    def test_auth_failure_disables_permanently(self) -> None:
        pool = CredentialPool()
        pool.add_key("openai", "sk-bad-key")
        pool.report_failure("openai", "sk-bad-key", status_code=401)
        assert pool.get_key("openai") is None

    def test_auth_failure_only_affects_matching_key(self) -> None:
        pool = CredentialPool()
        pool.add_key("openai", "sk-bad")
        pool.add_key("openai", "sk-good")
        pool.report_failure("openai", "sk-bad", status_code=403)
        assert pool.get_key("openai") == "sk-good"


class TestCooldownCircuitBreaking:
    def test_failure_puts_key_on_cooldown(self) -> None:
        pool = CredentialPool(cooldown_seconds=60.0, max_failures=99)
        pool.add_key("openai", "sk-key1")
        pool.report_failure("openai", "sk-key1", status_code=500)
        key_after = pool.get_key("openai")
        assert key_after is None

    def test_cooldown_expires(self) -> None:
        pool = CredentialPool(cooldown_seconds=0.01, max_failures=99)
        pool.add_key("openai", "sk-key1")
        pool.report_failure("openai", "sk-key1", status_code=500)
        assert pool.get_key("openai") is None
        time.sleep(0.02)
        assert pool.get_key("openai") == "sk-key1"

    def test_max_failures_disables_key(self) -> None:
        pool = CredentialPool(cooldown_seconds=3600.0, max_failures=3)
        pool.add_key("openai", "sk-key1")
        for _ in range(3):
            pool.report_failure("openai", "sk-key1", status_code=500)
        assert pool.get_key("openai") is None

    def test_success_resets_failure_count(self) -> None:
        pool = CredentialPool(cooldown_seconds=0.001, max_failures=3)
        pool.add_key("openai", "sk-key1")
        pool.report_failure("openai", "sk-key1", status_code=500)
        pool.report_failure("openai", "sk-key1", status_code=500)
        pool.report_success("openai", "sk-key1")
        time.sleep(0.005)
        pool.report_failure("openai", "sk-key1", status_code=500)
        pool.report_failure("openai", "sk-key1", status_code=500)
        time.sleep(0.005)
        assert pool.get_key("openai") == "sk-key1"


class TestEnvVarFallback:
    def test_fallback_to_env_var(self) -> None:
        pool = CredentialPool()
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("ZELOO_OPENAI_API_KEY", "env-key-123")
            key = pool.get_key("openai")
            assert key == "env-key-123"


class TestGetStatus:
    def test_get_status_masks_values(self) -> None:
        pool = CredentialPool()
        pool.add_key("openai", "sk-abcdefghijklmnop")
        statuses = pool.get_status("openai")
        assert len(statuses) == 1
        assert statuses[0]["value_masked"] == "sk-a...mnop"

    def test_get_status_shows_failure_count(self) -> None:
        pool = CredentialPool(max_failures=3)
        pool.add_key("openai", "sk-key1")
        pool.report_failure("openai", "sk-key1", status_code=500)
        pool.report_failure("openai", "sk-key1", status_code=500)
        statuses = pool.get_status("openai")
        assert statuses[0]["failure_count"] == 2

    def test_get_status_nonexistent_provider(self) -> None:
        pool = CredentialPool()
        assert pool.get_status("nonexistent") == []


class TestPersistence:
    def test_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "creds.json"
            pool1 = CredentialPool(storage_path=path)
            pool1.add_key("openai", "sk-persist-key1")
            pool1.add_key("anthropic", "sk-ant-persist")
            pool2 = CredentialPool(storage_path=path)
            pool2.get_key("openai")
            providers = pool2.list_providers()
            assert sorted(providers) == ["anthropic", "openai"]


class TestConcurrency:
    def test_concurrent_get_key(self) -> None:
        pool = CredentialPool()
        for i in range(4):
            pool.add_key("openai", f"key{i}")
        results: list[str] = []
        lock = threading.Lock()

        def fetch():
            for _ in range(10):
                key = pool.get_key("openai")
                if key:
                    with lock:
                        results.append(key)

        threads = [threading.Thread(target=fetch) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(results) == 40
        assert all(k.startswith("key") for k in results)

    def test_concurrent_add_and_get(self) -> None:
        pool = CredentialPool()
        errors: list[BaseException] = []

        def add_keys():
            try:
                for i in range(20):
                    pool.add_key("openai", f"new-key-{i}")
            except Exception as e:
                errors.append(e)

        def get_keys():
            try:
                for _ in range(20):
                    pool.get_key("openai")
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=add_keys)
        t2 = threading.Thread(target=get_keys)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        assert len(errors) == 0


class TestMasking:
    def test_mask_short_value(self) -> None:
        from agent.credential_pool import _mask_value
        assert _mask_value("abc") == "****"
        assert _mask_value("abcdefgh") == "****"

    def test_mask_long_value(self) -> None:
        from agent.credential_pool import _mask_value
        assert _mask_value("sk-abcdefghijklmnop") == "sk-a...mnop"
        assert _mask_value("12345678901234567890") == "1234...7890"
