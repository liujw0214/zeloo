"""Tests for the SmartModelRouter."""

# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from agent.provider_router import SmartModelRouter, SmartRoutingConfig


def _router(**kwargs) -> SmartModelRouter:
    defaults = dict(
        enabled=True,
        max_simple_chars=160,
        max_simple_words=28,
        cheap_provider="openai",
        cheap_model="gpt-4o-mini",
    )
    defaults.update(kwargs)
    return SmartModelRouter(SmartRoutingConfig(**defaults))


# ── is_simple ────────────────────────────────────────────────────────


def test_disabled_router_never_routes():
    r = _router(enabled=False)
    assert r.is_simple("hello") is False


def test_empty_input_is_not_simple():
    r = _router()
    assert r.is_simple("") is False


def test_short_greeting_is_simple():
    r = _router()
    assert r.is_simple("hello there") is True


def test_too_many_chars_is_not_simple():
    r = _router(max_simple_chars=10)
    assert r.is_simple("this is more than ten chars") is False


def test_too_many_words_is_not_simple():
    r = _router(max_simple_words=3)
    assert r.is_simple("one two three four") is False


def test_complex_keyword_is_not_simple():
    r = _router()
    for kw in ["fix", "debug", "sql", "implement", "refactor", "security", "docker"]:
        assert r.is_simple(f"please {kw} this") is False, kw


def test_case_insensitive_keyword_match():
    r = _router()
    assert r.is_simple("Please FIX the bug") is False


# ── select ───────────────────────────────────────────────────────────


def test_select_routes_simple_to_cheap_model():
    r = _router()
    provider, model = r.select("hello", "openai", "gpt-4o")
    assert provider == "openai"
    assert model == "gpt-4o-mini"


def test_select_keeps_complex_on_primary():
    r = _router()
    provider, model = r.select("fix the bug in the code", "openai", "gpt-4o")
    assert provider == "openai"
    assert model == "gpt-4o"


def test_select_no_change_when_cheap_equals_primary():
    r = _router(cheap_provider="openai", cheap_model="gpt-4o")
    provider, model = r.select("hello", "openai", "gpt-4o")
    assert provider == "openai"
    assert model == "gpt-4o"


def test_select_can_route_to_different_provider():
    r = _router(cheap_provider="deepseek", cheap_model="deepseek-chat")
    provider, model = r.select("hi", "openai", "gpt-4o")
    assert provider == "deepseek"
    assert model == "deepseek-chat"


# ── from_config ──────────────────────────────────────────────────────


def test_from_config_disabled_by_default():
    r = SmartModelRouter.from_config({})
    assert r.is_simple("hello") is False


def test_from_config_reads_section():
    r = SmartModelRouter.from_config({
        "smart_model_routing": {
            "enabled": True,
            "cheap_model": "gpt-4o-mini",
        }
    })
    assert r.is_simple("hi") is True


def test_from_config_handles_none():
    r = SmartModelRouter.from_config(None)
    assert r.is_simple("hi") is False


def test_from_config_handles_invalid_section():
    r = SmartModelRouter.from_config({"smart_model_routing": "not-a-dict"})
    assert r.config.enabled is False


if __name__ == "__main__":
    test_disabled_router_never_routes()
    test_empty_input_is_not_simple()
    test_short_greeting_is_simple()
    test_too_many_chars_is_not_simple()
    test_too_many_words_is_not_simple()
    test_complex_keyword_is_not_simple()
    test_case_insensitive_keyword_match()
    test_select_routes_simple_to_cheap_model()
    test_select_keeps_complex_on_primary()
    test_select_no_change_when_cheap_equals_primary()
    test_select_can_route_to_different_provider()
    test_from_config_disabled_by_default()
    test_from_config_reads_section()
    test_from_config_handles_none()
    test_from_config_handles_invalid_section()
    print("All smart_model_router tests passed!")
