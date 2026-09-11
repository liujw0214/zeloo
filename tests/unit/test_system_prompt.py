"""Tests for the system prompt three-tier architecture."""

# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path FIRST to avoid importing hermes-agent's agent package
PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from agent.system_prompt import build_system_prompt_parts, invalidate_system_prompt


class FakeAgent:
    """Minimal agent for testing system prompt assembly."""

    def __init__(self) -> None:
        self.session_id = "20260907_120000_test1234"
        self.model = "gpt-4o"
        self.provider = "openai"
        self.platform = "cli"
        self.valid_tool_names = {"file_read", "memory", "skill_manage"}
        self.available_toolsets = {"file", "memory", "skills"}
        self.load_soul_identity = True
        self.skip_context_files = False
        self._memory_enabled = True
        self._user_profile_enabled = True
        self._memory_store = None
        self._session_db = None
        self._cached_system_prompt = None
        self._cached_system_prompt_static = None


def test_three_tiers_built():
    """System prompt should be built in three distinct tiers."""
    agent = FakeAgent()
    parts = build_system_prompt_parts(agent)

    assert "stable" in parts
    assert "context" in parts
    assert "volatile" in parts
    assert parts["stable"], "stable tier should not be empty"


def test_stable_contains_identity():
    """Stable tier should contain the agent identity."""
    agent = FakeAgent()
    parts = build_system_prompt_parts(agent)

    assert "Zeloo Agent" in parts["stable"]


def test_volatile_contains_timestamp():
    """Volatile tier should contain the timestamp line."""
    agent = FakeAgent()
    parts = build_system_prompt_parts(agent)

    assert "Conversation started:" in parts["volatile"]
    assert "Model: gpt-4o" in parts["volatile"]


def test_invalidate_clears_cache():
    """Invalidate should clear the cached system prompt."""
    agent = FakeAgent()
    agent._cached_system_prompt = "cached"
    agent._cached_system_prompt_static = "static"

    invalidate_system_prompt(agent)

    assert agent._cached_system_prompt is None
    assert agent._cached_system_prompt_static is None


if __name__ == "__main__":
    test_three_tiers_built()
    test_stable_contains_identity()
    test_volatile_contains_timestamp()
    test_invalidate_clears_cache()
    print("All system_prompt tests passed!")
