"""Performance benchmarks for the Zeloo agent runtime.

These tests assert basic performance budgets. Thresholds are intentionally
generous so they pass on slow CI runners while still catching gross
regressions.
"""

# ruff: noqa: E402
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

import os

os.environ.setdefault("zeloo_HOME", tempfile.mkdtemp())


def test_system_prompt_cold_build_under_2s():
    """A cold system-prompt build should complete in under 2 seconds."""
    from run_agent import AIAgent

    agent = AIAgent(model="gpt-4o", platform="cli")
    start = time.perf_counter()
    prompt = agent.get_cached_system_prompt()
    elapsed = time.perf_counter() - start

    assert len(prompt) > 1000
    assert elapsed < 2.0, f"Cold build took {elapsed:.3f}s"
    agent.close()


def test_system_prompt_cache_hit_rate_above_80():
    """Repeated calls should hit the cache > 80% of the time."""
    from run_agent import AIAgent

    agent = AIAgent(model="gpt-4o", platform="cli")
    for _ in range(10):
        agent.get_cached_system_prompt()

    stats = agent.cache_stats()
    assert stats["hit_rate"] >= 0.8, f"Cache hit rate too low: {stats}"
    agent.close()


def test_tool_discovery_under_1s():
    """Discovering all built-in tools should complete in under 1 second."""
    from tools.base import discover_builtin_tools, get_registry

    start = time.perf_counter()
    discover_builtin_tools()
    elapsed = time.perf_counter() - start

    assert len(get_registry().get_names()) >= 20
    assert elapsed < 1.0, f"Tool discovery took {elapsed:.3f}s"


def test_cache_hit_returns_same_object():
    """Cache hits must return the exact same string (no rebuild)."""
    from run_agent import AIAgent

    agent = AIAgent(model="gpt-4o", platform="cli")
    first = agent.get_cached_system_prompt()
    second = agent.get_cached_system_prompt()
    assert first is second
    agent.close()


def test_invalidate_causes_miss():
    """After invalidation, the next call must be a cache miss."""
    from run_agent import AIAgent

    agent = AIAgent(model="gpt-4o", platform="cli")
    agent.get_cached_system_prompt()  # miss
    agent.get_cached_system_prompt()  # hit
    agent.invalidate_system_prompt()
    agent.get_cached_system_prompt()  # miss

    stats = agent.cache_stats()
    assert stats["misses"] == 2
    assert stats["hits"] == 1
    agent.close()


if __name__ == "__main__":
    test_system_prompt_cold_build_under_2s()
    test_system_prompt_cache_hit_rate_above_80()
    test_tool_discovery_under_1s()
    test_cache_hit_returns_same_object()
    test_invalidate_causes_miss()
    print("All performance tests passed!")
