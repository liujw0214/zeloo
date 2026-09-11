"""Tests for video_gen registry provider instance caching."""

from __future__ import annotations

from video_gen import clear_cache, get_provider
from video_gen.registry import _CACHE


def test_cached_instance_returned_when_api_key_provided():
    """Same (name, api_key) pair returns the same object (identity)."""
    clear_cache()
    p1 = get_provider("deepinfra_video", api_key="x" * 16)
    p2 = get_provider("deepinfra_video", api_key="x" * 16)
    assert p1 is p2


def test_different_api_keys_return_different_instances():
    """Different API keys produce different provider instances."""
    clear_cache()
    p1 = get_provider("deepinfra_video", api_key="key1" + "x" * 8)
    p2 = get_provider("deepinfra_video", api_key="key2" + "x" * 8)
    assert p1 is not p2


def test_different_providers_return_different_classes():
    """Different provider names return different types."""
    clear_cache()
    p_di = get_provider("deepinfra_video", api_key="x" * 16)
    p_fal = get_provider("fal_video", api_key="x" * 32)
    assert type(p_di) is not type(p_fal)


def test_no_api_key_returns_fresh_instance():
    """Without api_key, each call returns a new instance (not cached)."""
    clear_cache()
    p1 = get_provider("deepinfra_video")
    p2 = get_provider("deepinfra_video")
    assert p1 is not p2


def test_clear_cache_removes_all_entries():
    """clear_cache() empties the cache and returns the count removed."""
    clear_cache()
    get_provider("deepinfra_video", api_key="x" * 16)
    get_provider("fal_video", api_key="x" * 32)
    assert len(_CACHE) == 2
    removed = clear_cache()
    assert removed == 2
    assert len(_CACHE) == 0


def test_clear_cache_returns_zero_when_empty():
    """clear_cache() on empty cache returns 0."""
    clear_cache()
    assert clear_cache() == 0


def test_unknown_provider_returns_none():
    """Unknown provider name returns None (no caching involved)."""
    result = get_provider("nonexistent_video")
    assert result is None
