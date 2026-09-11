"""Tests for the 5 new external memory provider backends.

Covers fallback behaviour (to LocalFileProvider when credentials/SDKs are
missing), the ``get_memory_provider`` factory function, and ``max_chars``
truncation. All tests are hermetic — no network calls are made.
"""

# ruff: noqa: E402
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)
import os

os.environ.setdefault("zeloo_HOME", tempfile.mkdtemp())

from agent.memory_providers import (
    ByteroverProvider,
    HindsightProvider,
    HolographicProvider,
    LocalFileProvider,
    OpenVikingProvider,
    RetainDBProvider,
    SupermemoryProvider,
    get_memory_provider,
)

# ── SupermemoryProvider ─────────────────────────────────────────────


def test_supermemory_fallback_without_api_key() -> None:
    """SupermemoryProvider falls back to LocalFileProvider without api_key."""
    provider = SupermemoryProvider(api_key="", user_id="u1")
    assert provider._fallback is not None
    assert isinstance(provider._fallback, LocalFileProvider)
    provider.write("memory", "hello supermemory")
    assert provider.read("memory") == "hello supermemory"


def test_supermemory_with_api_key_skips_fallback() -> None:
    """When api_key is set, the fallback is not configured."""
    provider = SupermemoryProvider(api_key="sk-test", user_id="u1")
    assert provider._fallback is None


def test_supermemory_truncates_long_content() -> None:
    """Writes exceeding max_chars are truncated (via the fallback)."""
    provider = SupermemoryProvider(api_key="", user_id="u1", max_chars=10)
    provider.write("memory", "x" * 100)
    assert len(provider.read("memory")) == 10


# ── OpenVikingProvider ───────────────────────────────────────────────


def test_openviking_fallback_without_base_url() -> None:
    """OpenVikingProvider falls back to LocalFileProvider without base_url."""
    provider = OpenVikingProvider(base_url="", user_id="u1")
    assert provider._fallback is not None
    assert isinstance(provider._fallback, LocalFileProvider)
    provider.write("memory", "hello openviking")
    assert provider.read("memory") == "hello openviking"


def test_openviking_with_base_url_skips_fallback() -> None:
    """When base_url is set, the fallback is not configured."""
    provider = OpenVikingProvider(base_url="https://example.com", user_id="u1")
    assert provider._fallback is None


def test_openviking_truncates_long_content() -> None:
    provider = OpenVikingProvider(base_url="", user_id="u1", max_chars=10)
    provider.write("memory", "x" * 100)
    assert len(provider.read("memory")) == 10


# ── ByteroverProvider ─────────────────────────────────────────────────


def test_byterover_fallback_without_api_key() -> None:
    """ByteroverProvider falls back to LocalFileProvider without api_key."""
    provider = ByteroverProvider(api_key="", user_id="u1")
    assert provider._fallback is not None
    assert isinstance(provider._fallback, LocalFileProvider)
    provider.write("memory", "hello byterover")
    assert provider.read("memory") == "hello byterover"


def test_byterover_with_api_key_skips_fallback() -> None:
    """When api_key is set, the fallback is not configured."""
    provider = ByteroverProvider(api_key="sk-test", user_id="u1")
    assert provider._fallback is None


def test_byterover_truncates_long_content() -> None:
    provider = ByteroverProvider(api_key="", user_id="u1", max_chars=10)
    provider.write("memory", "x" * 100)
    assert len(provider.read("memory")) == 10


# ── HindsightProvider ────────────────────────────────────────────────


def test_hindsight_fallback_without_sdk() -> None:
    """HindsightProvider falls back to LocalFileProvider when SDK unavailable."""
    provider = HindsightProvider(api_key="sk-test", user_id="u1")
    # The hindsight package is not installed in the test env, so the
    # constructor must catch ImportError and install the fallback.
    assert provider._fallback is not None
    assert isinstance(provider._fallback, LocalFileProvider)
    provider.write("memory", "hello hindsight")
    assert provider.read("memory") == "hello hindsight"


def test_hindsight_truncates_long_content() -> None:
    provider = HindsightProvider(api_key="sk-test", user_id="u1", max_chars=10)
    provider.write("memory", "x" * 100)
    assert len(provider.read("memory")) == 10


# ── HolographicProvider ──────────────────────────────────────────────


def test_holographic_fallback_without_sdk() -> None:
    """HolographicProvider falls back to LocalFileProvider when SDK unavailable."""
    provider = HolographicProvider(api_key="sk-test", user_id="u1")
    assert provider._fallback is not None
    assert isinstance(provider._fallback, LocalFileProvider)
    provider.write("memory", "hello holographic")
    assert provider.read("memory") == "hello holographic"


def test_holographic_truncates_long_content() -> None:
    provider = HolographicProvider(api_key="sk-test", user_id="u1", max_chars=10)
    provider.write("memory", "x" * 100)
    assert len(provider.read("memory")) == 10


# ── get_memory_provider factory ──────────────────────────────────────


def test_factory_default_returns_local() -> None:
    provider = get_memory_provider({})
    assert isinstance(provider, LocalFileProvider)


def test_factory_returns_supermemory() -> None:
    provider = get_memory_provider(
        {"memory": {"provider": "supermemory", "supermemory": {"api_key": "k"}}}
    )
    assert isinstance(provider, SupermemoryProvider)


def test_factory_returns_openviking() -> None:
    provider = get_memory_provider(
        {"memory": {"provider": "openviking", "openviking": {"base_url": "https://x.com"}}}
    )
    assert isinstance(provider, OpenVikingProvider)


def test_factory_returns_byterover() -> None:
    provider = get_memory_provider(
        {"memory": {"provider": "byterover", "byterover": {"api_key": "k"}}}
    )
    assert isinstance(provider, ByteroverProvider)


def test_factory_returns_hindsight() -> None:
    provider = get_memory_provider(
        {"memory": {"provider": "hindsight", "hindsight": {"api_key": "k"}}}
    )
    assert isinstance(provider, HindsightProvider)


def test_factory_returns_holographic() -> None:
    provider = get_memory_provider(
        {"memory": {"provider": "holographic", "holographic": {"api_key": "k"}}}
    )
    assert isinstance(provider, HolographicProvider)


# ── RetainDBProvider ──────────────────────────────────────────────────


def test_retaindb_write_and_read() -> None:
    """RetainDB stores and retrieves content via SQLite."""
    db_path = str(Path(tempfile.mkdtemp()) / "test_retain.db")
    provider = RetainDBProvider(db_path=db_path, user_id="u1")
    assert provider._fallback is None
    provider.write("memory", "hello retaindb")
    assert provider.read("memory") == "hello retaindb"


def test_retaindb_overwrite() -> None:
    """RetainDB upserts (INSERT OR REPLACE) on repeated writes."""
    db_path = str(Path(tempfile.mkdtemp()) / "test_retain2.db")
    provider = RetainDBProvider(db_path=db_path, user_id="u1")
    provider.write("memory", "first")
    provider.write("memory", "second")
    assert provider.read("memory") == "second"


def test_retaindb_empty_read() -> None:
    """Reading a non-existent key returns empty string."""
    db_path = str(Path(tempfile.mkdtemp()) / "test_retain3.db")
    provider = RetainDBProvider(db_path=db_path, user_id="u1")
    assert provider.read("nonexistent") == ""


def test_retaindb_truncates_long_content() -> None:
    """Writes exceeding max_chars are truncated."""
    db_path = str(Path(tempfile.mkdtemp()) / "test_retain4.db")
    provider = RetainDBProvider(db_path=db_path, user_id="u1", max_chars=10)
    provider.write("memory", "x" * 100)
    assert len(provider.read("memory")) == 10


def test_factory_returns_retaindb() -> None:
    """Factory returns RetainDBProvider when provider='retaindb'."""
    db_path = str(Path(tempfile.mkdtemp()) / "factory_retain.db")
    provider = get_memory_provider(
        {"memory": {"provider": "retaindb", "retaindb": {"db_path": db_path}}}
    )
    assert isinstance(provider, RetainDBProvider)


if __name__ == "__main__":
    test_supermemory_fallback_without_api_key()
    test_supermemory_with_api_key_skips_fallback()
    test_supermemory_truncates_long_content()
    test_openviking_fallback_without_base_url()
    test_openviking_with_base_url_skips_fallback()
    test_openviking_truncates_long_content()
    test_byterover_fallback_without_api_key()
    test_byterover_with_api_key_skips_fallback()
    test_byterover_truncates_long_content()
    test_hindsight_fallback_without_sdk()
    test_hindsight_truncates_long_content()
    test_holographic_fallback_without_sdk()
    test_holographic_truncates_long_content()
    test_factory_default_returns_local()
    test_factory_returns_supermemory()
    test_factory_returns_openviking()
    test_factory_returns_byterover()
    test_factory_returns_hindsight()
    test_factory_returns_holographic()
    test_retaindb_write_and_read()
    test_retaindb_overwrite()
    test_retaindb_empty_read()
    test_retaindb_truncates_long_content()
    test_factory_returns_retaindb()
    print("All memory provider tests passed!")
