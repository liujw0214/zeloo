"""Tests for the TurnFinalizer self-evolution hooks."""

# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from agent.turn_finalizer import (
    SKILL_WORTHY_MIN_DISTINCT_TOOLS,
    SKILL_WORTHY_MIN_TOOL_CALLS,
    TurnFinalizer,
    TurnResult,
    build_nudge_prompt,
)


class FakeSessionDB:
    """Minimal session DB that records trajectory calls."""

    def __init__(self) -> None:
        self.saved: list[tuple[str, int, dict]] = []

    def save_trajectory(self, session_id: str, turn_id: int, data: dict) -> None:
        self.saved.append((session_id, turn_id, data))


class FakeAgent:
    """Minimal agent with nudge flags and session DB."""

    def __init__(self) -> None:
        self.session_id = "test-session"
        self._memory_nudge = False
        self._skill_nudge = False
        self._session_db = FakeSessionDB()
        self._agent_home_path = "/tmp/Zeloo-test"


def _make_tool_calls(names: list[str]) -> list[dict]:
    return [
        {"function": {"name": name, "arguments": "{}"}, "id": f"call_{i}"}
        for i, name in enumerate(names)
    ]


def test_memory_nudge_arms_on_preference_keyword():
    agent = FakeAgent()
    finalizer = TurnFinalizer()
    turn = TurnResult(
        session_id="s",
        turn_id=1,
        user_message="I prefer using pytest over unittest for my projects",
        assistant_response="Noted.",
    )
    finalizer.finalize(agent, turn)
    assert agent._memory_nudge is True


def test_memory_nudge_not_armed_on_plain_question():
    agent = FakeAgent()
    finalizer = TurnFinalizer()
    turn = TurnResult(
        session_id="s",
        turn_id=1,
        user_message="What is the capital of France?",
        assistant_response="Paris.",
    )
    finalizer.finalize(agent, turn)
    assert agent._memory_nudge is False


def test_skill_nudge_arms_on_complex_workflow():
    agent = FakeAgent()
    finalizer = TurnFinalizer()
    names = ["file_read", "shell", "file_write", "shell", "file_read"]
    turn = TurnResult(
        session_id="s",
        turn_id=1,
        user_message="Fix the bug",
        assistant_response="Done.",
        tool_calls=_make_tool_calls(names),
    )
    finalizer.finalize(agent, turn)
    assert agent._skill_nudge is True
    assert turn.tool_call_count >= SKILL_WORTHY_MIN_TOOL_CALLS
    assert len(turn.distinct_tool_names) >= SKILL_WORTHY_MIN_DISTINCT_TOOLS


def test_skill_nudge_not_armed_on_simple_task():
    agent = FakeAgent()
    finalizer = TurnFinalizer()
    turn = TurnResult(
        session_id="s",
        turn_id=1,
        user_message="Read this file",
        assistant_response="Here it is.",
        tool_calls=_make_tool_calls(["file_read"]),
    )
    finalizer.finalize(agent, turn)
    assert agent._skill_nudge is False


def test_trajectory_saved_to_session_db():
    agent = FakeAgent()
    finalizer = TurnFinalizer()
    turn = TurnResult(
        session_id="sess-1",
        turn_id=3,
        user_message="hello",
        assistant_response="hi",
        tool_calls=_make_tool_calls(["shell"]),
    )
    finalizer.finalize(agent, turn)

    assert len(agent._session_db.saved) == 1
    sid, tid, data = agent._session_db.saved[0]
    assert sid == "sess-1"
    assert tid == 3
    assert data["user_message"] == "hello"
    assert data["tool_call_count"] == 1


def test_build_nudge_prompt_consumes_flags():
    agent = FakeAgent()
    agent._memory_nudge = True
    agent._skill_nudge = True

    prompt = build_nudge_prompt(agent)
    assert "Memory Nudge" in prompt
    assert "Skill Nudge" in prompt
    # Flags should be consumed
    assert agent._memory_nudge is False
    assert agent._skill_nudge is False


def test_build_nudge_prompt_empty_when_no_flags():
    agent = FakeAgent()
    assert build_nudge_prompt(agent) == ""


def test_finalizer_never_raises_without_session_db():
    agent = FakeAgent()
    agent._session_db = None
    finalizer = TurnFinalizer()
    turn = TurnResult(
        session_id="s",
        turn_id=1,
        user_message="I prefer vim",
        assistant_response="ok",
    )
    # Should not raise
    finalizer.finalize(agent, turn)
    assert agent._memory_nudge is True


import tempfile  # noqa: E402  (used by file_read output-scanning fixtures below)


@pytest.fixture
def permissive_policy():
    """Mirror the permissive policy fixture from test_file_tools.py."""
    from tools import file_tools
    from tools.path_safety import PathSafetyPolicy

    policy = PathSafetyPolicy(
        allowed_roots=[Path(tempfile.gettempdir()).resolve(), Path.cwd().resolve()],
        denied_patterns=(),
    )
    file_tools.set_path_safety_policy(policy)
    file_tools.enable_path_safety()
    yield policy
    file_tools.set_path_safety_policy(None)
    file_tools.enable_path_safety()


# ── Secret scanning ──────────────────────────────────────────────


def test_secret_alert_arms_agent_on_high_severity():
    agent = FakeAgent()
    finalizer = TurnFinalizer()
    turn = TurnResult(
        session_id="s",
        turn_id=1,
        user_message="what is my key?",
        assistant_response="Here it is: sk-abcdefghijklmnopqrstuvwxyz1234567890",
    )
    finalizer.finalize(agent, turn)
    alert = getattr(agent, "_secret_alert", None)
    assert alert is not None
    assert alert["count"] >= 1
    assert "openai_api_key" in alert["categories"]


def test_secret_alert_not_armed_on_clean_response():
    agent = FakeAgent()
    finalizer = TurnFinalizer()
    turn = TurnResult(
        session_id="s",
        turn_id=1,
        user_message="tell me a joke",
        assistant_response="Why did the chicken cross the road?",
    )
    finalizer.finalize(agent, turn)
    assert getattr(agent, "_secret_alert", None) is None


def test_secret_alert_threshold_is_configurable():
    agent = FakeAgent()
    finalizer = TurnFinalizer(secret_alert_min_severity="critical")
    # LOW-severity password=... is below critical threshold.
    turn = TurnResult(
        session_id="s",
        turn_id=1,
        user_message="x",
        assistant_response="password=hunter2hunter2abc",
    )
    finalizer.finalize(agent, turn)
    assert getattr(agent, "_secret_alert", None) is None

    agent2 = FakeAgent()
    finalizer2 = TurnFinalizer(secret_alert_min_severity="low")
    turn2 = TurnResult(
        session_id="s",
        turn_id=1,
        user_message="x",
        assistant_response="password=hunter2hunter2abc",
    )
    finalizer2.finalize(agent2, turn2)
    assert getattr(agent2, "_secret_alert", None) is not None


def test_secret_scan_can_be_disabled():
    agent = FakeAgent()
    finalizer = TurnFinalizer(secret_scan_enabled=False)
    turn = TurnResult(
        session_id="s",
        turn_id=1,
        user_message="x",
        assistant_response="sk-abcdefghijklmnopqrstuvwxyz1234567890",
    )
    finalizer.finalize(agent, turn)
    assert getattr(agent, "_secret_alert", None) is None


def test_secret_alert_nudge_appears_in_prompt():
    agent = FakeAgent()
    agent._secret_alert = {
        "session_id": "s",
        "turn_id": 5,
        "count": 2,
        "categories": ["openai_api_key", "github_token"],
        "summary": "high(2)",
    }
    prompt = build_nudge_prompt(agent)
    assert "Secret Leak Warning" in prompt
    assert "turn 5" in prompt
    # Alert must be consumed.
    assert getattr(agent, "_secret_alert", None) is None


def test_secret_scan_does_not_break_finalize_when_scanner_fails(monkeypatch):
    agent = FakeAgent()
    finalizer = TurnFinalizer()

    # Force the underlying SecretScanner().scan() to blow up.
    from agent import secret_scanner

    class _Boom:
        def scan(self, *_a, **_kw):
            raise RuntimeError("scanner crashed")

        def scan_and_redact(self, *_a, **_kw):
            raise RuntimeError("scanner crashed")

    monkeypatch.setattr(secret_scanner, "SecretScanner", _Boom)
    turn = TurnResult(
        session_id="s",
        turn_id=1,
        user_message="x",
        assistant_response="sk-abcdefghijklmnopqrstuvwxyz1234567890",
    )
    # Must not raise — finalize swallows scanner errors.
    finalizer.finalize(agent, turn)
    assert getattr(agent, "_secret_alert", None) is None


def test_secret_alert_writes_audit_event(tmp_path, monkeypatch):
    from agent import audit_log

    audit_log.reset_default_audit_log()
    monkeypatch.setattr(audit_log, "_default", audit_log.AuditLog(path=tmp_path / "a.log"))
    try:
        agent = FakeAgent()
        finalizer = TurnFinalizer()
        turn = TurnResult(
            session_id="audit-sess",
            turn_id=2,
            user_message="x",
            assistant_response=(
                "Here's my key: sk-abcdefghijklmnopqrstuvwxyz1234567890"
            ),
        )
        finalizer.finalize(agent, turn)
        events = list(audit_log.get_default_audit_log().iter_events())
        kinds = [e.kind for e in events]
        assert "llm_output_secret_alert" in kinds
    finally:
        audit_log.reset_default_audit_log()


def test_low_severity_writes_flagged_audit_only(tmp_path, monkeypatch):
    from agent import audit_log

    audit_log.reset_default_audit_log()
    monkeypatch.setattr(audit_log, "_default", audit_log.AuditLog(path=tmp_path / "a.log"))
    try:
        agent = FakeAgent()
        finalizer = TurnFinalizer(secret_alert_min_severity="critical")
        turn = TurnResult(
            session_id="flag-sess",
            turn_id=1,
            user_message="x",
            assistant_response="password=hunter2hunter2abc",
        )
        finalizer.finalize(agent, turn)
        events = list(audit_log.get_default_audit_log().iter_events())
        assert any(e.kind == "llm_output_secret_flagged" for e in events)
        assert not any(e.kind == "llm_output_secret_alert" for e in events)
    finally:
        audit_log.reset_default_audit_log()


# ── Output scanning (file_read integration) ─────────────────────


def test_file_read_redacts_secret_and_appends_header(tmp_path, permissive_policy):
    from tools import file_tools

    target = tmp_path / "leaked.txt"
    target.write_text(
        "config:\n  api_key: sk-abcdefghijklmnopqrstuvwxyz1234567890\n",
        encoding="utf-8",
    )
    out = file_tools.file_read(str(target))
    assert "sk-abcdef" not in out
    assert "[REDACTED]" in out
    assert "redacted" in out.lower()  # header marker


def test_file_read_leaves_clean_content_alone(tmp_path, permissive_policy):
    from tools import file_tools

    target = tmp_path / "clean.txt"
    target.write_text("just a plain log file with no secrets", encoding="utf-8")
    out = file_tools.file_read(str(target))
    assert out == "just a plain log file with no secrets"


def test_file_read_scan_can_be_disabled(tmp_path, permissive_policy):
    from tools import file_tools

    target = tmp_path / "leaked.txt"
    raw = "sk-abcdefghijklmnopqrstuvwxyz1234567890"
    target.write_text(raw, encoding="utf-8")

    file_tools.set_output_scan_enabled(False)
    try:
        out = file_tools.file_read(str(target))
        assert raw in out  # scan was off, secret intact
    finally:
        file_tools.set_output_scan_enabled(True)


def test_file_read_scan_writes_audit_event(tmp_path, permissive_policy, monkeypatch):
    from agent import audit_log
    from tools import file_tools

    audit_log.reset_default_audit_log()
    monkeypatch.setattr(audit_log, "_default", audit_log.AuditLog(path=tmp_path / "a.log"))
    try:
        target = tmp_path / "leaked.txt"
        target.write_text("sk-abcdefghijklmnopqrstuvwxyz1234567890", encoding="utf-8")
        file_tools.file_read(str(target))
        events = list(audit_log.get_default_audit_log().iter_events())
        assert any(e.kind == "tool_output_secret_found" for e in events)
    finally:
        audit_log.reset_default_audit_log()


if __name__ == "__main__":
    test_memory_nudge_arms_on_preference_keyword()
    test_memory_nudge_not_armed_on_plain_question()
    test_skill_nudge_arms_on_complex_workflow()
    test_skill_nudge_not_armed_on_simple_task()
    test_trajectory_saved_to_session_db()
    test_build_nudge_prompt_consumes_flags()
    test_build_nudge_prompt_empty_when_no_flags()
    test_finalizer_never_raises_without_session_db()
    print("All turn_finalizer tests passed!")
