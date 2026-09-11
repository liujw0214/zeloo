"""Tests for the estop emergency stop, i18n, insights, credential_pool,
error_classifier, and hooks modules."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")


# ── estop ────────────────────────────────────────────────────────

def test_estop_trigger_and_reset():
    from agent.estop import estop

    estop.reset()
    assert not estop.is_stopped()
    estop.trigger("test")
    assert estop.is_stopped()
    state = estop.get_state()
    assert state.reason == "test"
    estop.reset()
    assert not estop.is_stopped()


# ── i18n ─────────────────────────────────────────────────────────

def test_i18n_basic():
    from agent.i18n import gettext, set_language

    set_language("en")
    assert gettext("hello_world") == "Hello, world"
    set_language("zh-CN")
    assert gettext("hello_world") == "你好，世界"


def test_i18n_placeholder():
    from agent.i18n import gettext, set_language

    set_language("en")
    assert "file_read" in gettext("tool_call_failed", tool="file_read")


def test_i18n_fallback():
    from agent.i18n import gettext, set_language

    set_language("en")
    # Key not in any locale → return key itself
    assert gettext("nonexistent_key_xyz") == "nonexistent_key_xyz"


# ── insights ─────────────────────────────────────────────────────

def test_insights_tool_call():
    from agent.insights import InsightsEngine

    with tempfile.TemporaryDirectory() as td:
        eng = InsightsEngine(storage_path=Path(td) / "insights.json")
        eng.record_tool_call("file_read", 0.05)
        report = eng.generate_report()
        assert report["summary"]["tools_used"] >= 1
        assert report["top_tools"][0]["name"] == "file_read"


def test_insights_error_recording():
    from agent.insights import InsightsEngine

    with tempfile.TemporaryDirectory() as td:
        eng = InsightsEngine(storage_path=Path(td) / "insights.json")
        eng.record_error("rate_limit")
        eng.record_error("rate_limit")
        eng.record_error("auth")
        report = eng.generate_report()
        errors = {e["category"]: e["count"] for e in report["top_errors"]}
        assert errors.get("rate_limit") == 2


# ── credential_pool ──────────────────────────────────────────────

def test_credential_pool_round_robin():
    from agent.credential_pool import CredentialPool

    pool = CredentialPool()
    pool.add_key("openai", "sk-aaaaaaaaaaaaaaaa", "k1")
    pool.add_key("openai", "sk-bbbbbbbbbbbbbbbb", "k2")
    k1 = pool.get_key("openai")
    k2 = pool.get_key("openai")
    assert k1 != k2


def test_credential_pool_auth_disable():
    from agent.credential_pool import CredentialPool

    pool = CredentialPool()
    pool.add_key("openai", "sk-cccccccccccccccc", "bad")
    pool.add_key("openai", "sk-dddddddddddddddd", "good")
    bad_key = pool.get_key("openai")
    pool.report_failure("openai", bad_key, status_code=401)
    # The bad key should be disabled, only good key remains
    available = pool.get_status("openai")
    disabled = [k for k in available if k["disabled"]]
    assert len(disabled) == 1


# ── error_classifier ─────────────────────────────────────────────

def test_error_classifier_auth():
    from agent.error_classifier import ErrorCategory, classify_error

    r = classify_error("Invalid API key", status_code=401)
    assert r.category == ErrorCategory.AUTH
    assert r.retryable is False
    assert r.should_fallback_provider is True


def test_error_classifier_rate_limit():
    from agent.error_classifier import ErrorCategory, classify_error

    r = classify_error("Rate limit exceeded", status_code=429)
    assert r.category == ErrorCategory.RATE_LIMIT
    assert r.retryable is True


def test_error_classifier_context_overflow():
    from agent.error_classifier import ErrorCategory, classify_error

    r = classify_error("context length exceeded", status_code=400)
    assert r.category == ErrorCategory.CONTEXT_OVERFLOW


# ── hooks ────────────────────────────────────────────────────────

def test_hooks_fire():
    from plugins.hooks import HookRegistry, HookType

    hr = HookRegistry()
    calls = []

    def hook(name, args):
        calls.append(name)
        return None

    hr.register(HookType.PRE_TOOL_CALL, hook, "test")
    result = hr.fire(HookType.PRE_TOOL_CALL, "file_read", {"path": "/x"})
    assert calls == ["file_read"]
    assert result is None


def test_hooks_fire_chain():
    from plugins.hooks import HookRegistry, HookType

    hr = HookRegistry()
    hr.register(HookType.POST_TOOL_CALL, lambda v, *a: v.upper(), "upper")
    hr.register(HookType.POST_TOOL_CALL, lambda v, *a: v + "!", "bang")
    result = hr.fire_chain(HookType.POST_TOOL_CALL, "hello")
    assert result == "HELLO!"


def test_hooks_exception_isolated():
    from plugins.hooks import HookRegistry, HookType

    hr = HookRegistry()

    def bad_hook(*a):
        raise RuntimeError("boom")

    hr.register(HookType.PRE_TOOL_CALL, bad_hook, "bad")
    # Should not raise — exception is caught
    result = hr.fire(HookType.PRE_TOOL_CALL, "x", {})
    assert result is None


if __name__ == "__main__":
    tests = [
        test_estop_trigger_and_reset,
        test_i18n_basic,
        test_i18n_placeholder,
        test_i18n_fallback,
        test_insights_tool_call,
        test_insights_error_recording,
        test_credential_pool_round_robin,
        test_credential_pool_auth_disable,
        test_error_classifier_auth,
        test_error_classifier_rate_limit,
        test_error_classifier_context_overflow,
        test_hooks_fire,
        test_hooks_fire_chain,
        test_hooks_exception_isolated,
    ]
    for t in tests:
        t()
    print("All new module tests passed!")
