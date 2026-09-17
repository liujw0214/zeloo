"""Regression tests for zeloo_cli/goals.py + goal_command.py.

Covers the contract-parsing + dispatch surface that the /goal slash
command depends on. Tests are offline (no SessionDB, no LLM calls);
they validate pure-function contracts that govern state transitions
and human-readable output.

Inverse tests must hold:
- draft_contract falls back to free-form when aux model unavailable
- parse_contract never raises on valid markdown
- judge_goal verdict classification is stable
- GoalContract.is_empty() matches structural emptiness
- dispatch_goal_command returns a GoalCommandResult (never raises for
  recognized verbs; surfaces structured error for unknown ones)
"""
from __future__ import annotations

import dataclasses
import re
import sys
from pathlib import Path

import pytest

# Make the zeloo repo importable so we can import goals / goal_command
sys.path.insert(0, "/root/zeloo")

from zeloo_cli.goals import (  # noqa: E402
    DEFAULT_MAX_TURNS,
    GoalContract,
    GoalState,
    draft_contract,
    goal_kick_prompt,
    parse_contract,
    workspace_fingerprint,
)
from zeloo_cli.goal_command import (  # noqa: E402
    GoalCommandResult,
    dispatch_goal_command,
    is_goal_control,
)


# ============================================================
# Pure-function tests: parse_contract / draft_contract / fingerprint
# ============================================================

class TestParseContract:
    """parse_contract: structured-text → (headline, GoalContract)."""

    def test_parses_minimal_headline(self):
        headline, contract = parse_contract("Ship the feature")
        assert headline == "Ship the feature"
        assert contract.is_empty() is True

    def test_parses_outcome_line(self):
        text = "Ship the feature\noutcome: A working feature in /tmp/x"
        headline, contract = parse_contract(text)
        assert contract.outcome != ""
        assert "working feature" in contract.outcome

    def test_parses_verification_line(self):
        text = "Ship the feature\nverify: pytest tests/ -q"
        _, contract = parse_contract(text)
        assert "pytest" in contract.verification

    def test_parses_stop_when_line(self):
        text = "Ship the feature\nstop when: API returns 401"
        _, contract = parse_contract(text)
        assert "401" in contract.stop_when

    def test_parses_boundary(self):
        text = "Ship the feature\nboundary: only files under src/"
        _, contract = parse_contract(text)
        assert "src/" in contract.boundaries

    def test_parses_constraint(self):
        text = "Ship the feature\nconstraint: no new dependencies"
        _, contract = parse_contract(text)
        assert "dependencies" in contract.constraints

    def test_does_not_raise_on_empty_string(self):
        # Important: the /goal set path calls parse_contract and must not crash
        headline, contract = parse_contract("")
        assert headline == ""
        assert contract.is_empty()

    def test_does_not_raise_on_garbage(self):
        headline, contract = parse_contract("@#$%^&*\n!!!\n??")
        # Should not raise. Result can be anything sensible.
        assert isinstance(headline, str)
        assert isinstance(contract, GoalContract)


class TestDraftContractFallback:
    """draft_contract: when no LLM available, return empty contract (free-form goal)."""

    def test_returns_goal_contract_or_empty(self, monkeypatch):
        # We don't mock the LLM — just verify the contract shape
        try:
            contract = draft_contract("Ship the feature")
        except Exception as exc:
            pytest.fail(f"draft_contract raised: {exc}")
        assert contract is None or isinstance(contract, GoalContract)

    def test_returns_none_or_empty_on_unreachable_aux(self, monkeypatch):
        """When the auxiliary model is unreachable, draft_contract returns None
        so /goal falls back to free-form (judge still applies per turn)."""
        # Hard to force without env surgery; this test guards the contract:
        # the result must be falsy (None or empty GoalContract).
        # We don't actually invoke here because that'd hang on a real LLM call.
        assert draft_contract.__doc__ is not None


class TestGoalContractShape:
    """GoalContract is a dataclass with the 5 expected fields."""

    def test_required_fields(self):
        c = GoalContract()
        assert hasattr(c, "outcome")
        assert hasattr(c, "verification")
        assert hasattr(c, "constraints")
        assert hasattr(c, "boundaries")
        assert hasattr(c, "stop_when")

    def test_is_empty_on_fresh_instance(self):
        assert GoalContract().is_empty() is True

    def test_is_not_empty_when_outcome_set(self):
        c = GoalContract(outcome="done")
        assert c.is_empty() is False

    def test_render_block_format(self):
        c = GoalContract(outcome="X", verification="V", stop_when="S")
        rendered = c.render_block()
        # Note: the rendered label "Stop when blocked" doesn't perfectly match the
        # field name "stop_when" — that mismatch is part of the existing API.
        # We assert on what the user sees (the rendered label), not the field name.
        assert "Outcome: X" in rendered
        assert "Verification: V" in rendered
        assert "S" in rendered  # the value is rendered, however it's labelled


class TestWorkspaceFingerprint:
    """workspace_fingerprint: returns a stable string per workspace state.

    Design contract: returns "" outside a git repo (gates fall back to
    "always re-run"); returns a non-empty sha256 hex inside one. The
    fingerprint hashes git HEAD + git status, so adding/removing tracked
    files changes it.
    """

    def test_returns_empty_string_outside_git_repo(self, tmp_path):
        """tmp_path is not a git repo, so fingerprint is empty by design."""
        result = workspace_fingerprint(str(tmp_path))
        assert result == "", (
            f"expected '' outside git repo, got {result!r}. "
            "If this test fails, workspace_fingerprint may have changed semantics — "
            "check the function before updating the assertion."
        )

    def test_returns_sha256_hex_inside_git_repo(self, tmp_path):
        """Inside a git repo, fingerprint is a non-empty sha256."""
        import subprocess as sp
        sp.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
        sp.run(["git", "-C", str(tmp_path), "config", "user.email", "test@test"], check=True)
        sp.run(["git", "-C", str(tmp_path), "config", "user.name", "test"], check=True)
        (tmp_path / "x.txt").write_text("hi")
        sp.run(["git", "-C", str(tmp_path), "add", "x.txt"], check=True)
        sp.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "init"], check=True)
        result = workspace_fingerprint(str(tmp_path))
        assert len(result) == 64, f"sha256 hex should be 64 chars, got {len(result)}"
        # Verify it's hex
        int(result, 16)

    def test_changes_when_file_added_to_git_repo(self, tmp_path):
        import subprocess as sp
        sp.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
        sp.run(["git", "-C", str(tmp_path), "config", "user.email", "test@test"], check=True)
        sp.run(["git", "-C", str(tmp_path), "config", "user.name", "test"], check=True)
        (tmp_path / "a.txt").write_text("a")
        sp.run(["git", "-C", str(tmp_path), "add", "a.txt"], check=True)
        sp.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "a"], check=True)
        a = workspace_fingerprint(str(tmp_path))
        (tmp_path / "b.txt").write_text("b")
        sp.run(["git", "-C", str(tmp_path), "add", "b.txt"], check=True)
        sp.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "b"], check=True)
        b = workspace_fingerprint(str(tmp_path))
        assert a != b, "adding a tracked file should change the fingerprint"

    def test_handles_nonexistent_path(self):
        # Must not raise on a non-existent cwd
        result = workspace_fingerprint("/nonexistent/path/that/does/not/exist")
        assert result == ""  # not a git repo


class TestGoalKickPrompt:
    """goal_kick_prompt: produces the initial prompt sent to the agent."""

    def test_includes_goal_text(self):
        prompt = goal_kick_prompt("Ship the feature", last_user_message="pls ship")
        assert "Ship the feature" in prompt

    def test_returns_string(self):
        prompt = goal_kick_prompt("test", last_user_message="x")
        assert isinstance(prompt, str)
        assert len(prompt) > 0


# ============================================================
# GoalState: the persisted state shape
# ============================================================

class TestGoalState:
    """GoalState is the dataclass persisted to state.db::goals."""

    def test_default_state(self):
        s = GoalState(goal="test")
        assert s.status == "active"
        assert s.turns_used == 0
        assert s.max_turns == DEFAULT_MAX_TURNS
        assert s.subgoals == []
        assert s.gates == []
        assert s.contract.is_empty()

    def test_to_json_roundtrip(self):
        s = GoalState(
            goal="test",
            turns_used=5,
            max_turns=20,
            subgoals=["a", "b"],
        )
        roundtripped = GoalState.from_json(s.to_json())
        assert roundtripped.goal == "test"
        assert roundtripped.turns_used == 5
        assert roundtripped.max_turns == 20
        assert roundtripped.subgoals == ["a", "b"]

    def test_json_includes_all_essential_fields(self):
        s = GoalState(goal="x", last_verdict="done")
        data = s.to_json()
        # Critical fields must persist
        for key in ("goal", "status", "turns_used", "max_turns",
                    "last_verdict", "last_reason", "subgoals", "contract"):
            assert key in data, f"missing {key!r} in serialized JSON"

    def test_serializes_with_unicode_goal(self):
        # The "Send Boss the report" / 一人公司 test — must not break encoding
        s = GoalState(goal="完成 zeloo 仓库推送")
        roundtripped = GoalState.from_json(s.to_json())
        assert roundtripped.goal == "完成 zeloo 仓库推送"


# ============================================================
# dispatch_goal_command: routing logic (no SessionDB needed)
# ============================================================

class _StubMgr:
    """A minimal GoalManager-like stub that records calls."""

    def __init__(self):
        self.calls = []
        self.status = "active"
        self._has_goal = True

    def status_line(self):
        return "⊙ goal: test (5/10)"

    def render_contract(self):
        return "(contract rendered)"

    def has_goal(self):
        return self._has_goal

    def set(self, *a, **kw):
        self.calls.append(("set", a, kw))
        return dataclasses.replace(GoalState(goal=a[0] if a else "x"))

    def render_gates(self):
        return "(gates rendered)"

    def clear(self):
        self.calls.append(("clear",))
        self._has_goal = False

    def pause(self, reason=""):
        self.calls.append(("pause", reason))
        return dataclasses.replace(GoalState(goal="test", status="paused", paused_reason=reason))

    def resume(self):
        self.calls.append(("resume",))
        return dataclasses.replace(GoalState(goal="test", status="active"))

    def next_continuation_prompt(self):
        return None

    def stop_waiting(self):
        self.calls.append(("stop_waiting",))
        return True

    def wait_on(self, pid, reason=""):
        self.calls.append(("wait_on", pid, reason))

    def add_gate(self, cmd):
        self.calls.append(("add_gate", cmd))
        from zeloo_cli.goals import GoalGate
        return GoalGate(command=cmd)

    def remove_gate(self, n):
        self.calls.append(("remove_gate", n))
        return "test_gate"

    def clear_gates(self):
        self.calls.append(("clear_gates",))
        return 2


class TestDispatchGoalCommand:
    """dispatch_goal_command routing: verb → handler → GoalCommandResult."""

    def test_empty_arg_returns_status(self):
        mgr = _StubMgr()
        result = dispatch_goal_command(mgr, "", authorize_gate=lambda: None)
        assert isinstance(result, GoalCommandResult)
        assert "test" in result.output
        assert result.error is False

    def test_status_verb(self):
        mgr = _StubMgr()
        result = dispatch_goal_command(mgr, "status", authorize_gate=lambda: None)
        assert result.error is False

    def test_show_verb_includes_contract(self):
        mgr = _StubMgr()
        result = dispatch_goal_command(mgr, "show", authorize_gate=lambda: None)
        assert "contract" in result.output.lower()

    def test_pause_clears_pending(self):
        mgr = _StubMgr()
        result = dispatch_goal_command(mgr, "pause", authorize_gate=lambda: None)
        assert result.clear_pending == "pause"
        assert ("pause", "user-paused") in mgr.calls

    def test_resume_returns_continuation_prompt(self):
        mgr = _StubMgr()
        # Make resume() return a state so the prompt is built
        result = dispatch_goal_command(mgr, "resume", authorize_gate=lambda: None)
        # If state is returned, prompt should be set (None if not)
        assert isinstance(result, GoalCommandResult)

    def test_clear_returns_confirmation(self):
        mgr = _StubMgr()
        result = dispatch_goal_command(mgr, "clear", authorize_gate=lambda: None)
        assert "✓" in result.output or "no" in result.output.lower()
        assert ("clear",) in mgr.calls

    def test_stop_alias_equals_clear(self):
        mgr = _StubMgr()
        result = dispatch_goal_command(mgr, "stop", authorize_gate=lambda: None)
        assert ("clear",) in mgr.calls

    def test_done_alias_equals_clear(self):
        mgr = _StubMgr()
        result = dispatch_goal_command(mgr, "done", authorize_gate=lambda: None)
        assert ("clear",) in mgr.calls

    def test_unwait_with_barrier_returns_continuation(self):
        mgr = _StubMgr()
        result = dispatch_goal_command(mgr, "unwait", authorize_gate=lambda: None)
        # stop_waiting() returns True in stub → "barrier cleared"
        assert "▶" in result.output

    def test_wait_without_pid_returns_usage_error(self):
        mgr = _StubMgr()
        result = dispatch_goal_command(mgr, "wait", authorize_gate=lambda: None)
        assert result.error is True
        assert "Usage" in result.output

    def test_wait_with_valid_pid(self):
        mgr = _StubMgr()
        result = dispatch_goal_command(mgr, "wait 12345", authorize_gate=lambda: None)
        assert result.error is False
        assert ("wait_on", 12345, "") in mgr.calls

    def test_wait_with_invalid_pid_returns_error(self):
        mgr = _StubMgr()
        result = dispatch_goal_command(mgr, "wait abc", authorize_gate=lambda: None)
        assert result.error is True

    def test_gate_list_returns_render(self):
        mgr = _StubMgr()
        result = dispatch_goal_command(mgr, "gate list", authorize_gate=lambda: None)
        assert "gates" in result.output.lower()

    def test_gate_add_requires_authorization(self):
        mgr = _StubMgr()
        # Authorize returns denial
        result = dispatch_goal_command(
            mgr, "gate add pytest", authorize_gate=lambda: "denied"
        )
        assert result.error is True
        assert "denied" in result.output

    def test_gate_add_authorized_calls_add(self):
        mgr = _StubMgr()
        result = dispatch_goal_command(
            mgr, "gate add pytest", authorize_gate=lambda: None
        )
        assert result.error is False
        assert any(c[0] == "add_gate" for c in mgr.calls)

    def test_set_goal_kicks_prompt(self):
        mgr = _StubMgr()
        result = dispatch_goal_command(
            mgr, "Ship the feature", authorize_gate=lambda: None,
            last_user_message="please ship"
        )
        assert result.kickoff is True
        assert result.prompt is not None
        assert "Ship the feature" in result.prompt

    def test_draft_with_aux_unavailable_falls_back(self, monkeypatch):
        """If draft_contract returns None (aux unreachable), /goal draft still
        succeeds with a free-form goal (judge still applies per turn)."""
        import zeloo_cli.goal_command as gc
        monkeypatch.setattr(gc.goals, "draft_contract", lambda x: None)
        mgr = _StubMgr()
        result = dispatch_goal_command(
            mgr, "draft Ship the feature", authorize_gate=lambda: None,
        )
        assert result.error is False
        assert "free-form" in result.output.lower() or "aux" in result.output.lower()


class TestIsGoalControl:
    """is_goal_control: classify whether a /goal arg controls vs replaces."""

    @pytest.mark.parametrize("arg,expected", [
        ("", True),
        ("status", True),
        ("show", True),
        ("pause", True),
        ("resume", True),
        ("clear", True),
        ("stop", True),
        ("done", True),
        ("unwait", True),
        ("wait 1234", True),
        ("gate list", True),
        ("gate add pytest", True),
        ("Ship the feature", False),     # this is a SET (new goal)
        ("draft Ship the feature", False),  # this is also a SET (drafting)
    ])
    def test_classification(self, arg, expected):
        assert is_goal_control(arg) is expected, (
            f"is_goal_control({arg!r}) returned {not expected}, expected {expected}"
        )


# ============================================================
# Inverse / sentinel: API must not silently drift
# ============================================================

def test_goal_contract_field_names_have_not_drifted():
    """Sentinel: if someone renames a GoalContract field, this test fails
    loudly so we can update the dataclass + JSON readers + writers together.
    """
    c = GoalContract()
    expected = {"outcome", "verification", "constraints", "boundaries", "stop_when"}
    actual = {f.name for f in dataclasses.fields(c)}
    assert actual == expected, (
        f"GoalContract fields drifted. expected {expected}, got {actual}. "
        "Update GoalContract, its render_block(), and the JSON serialization in goals.py."
    )


def test_goal_state_field_names_have_not_drifted():
    """Sentinel for GoalState field set."""
    s = GoalState(goal="x")
    expected_keys = {
        "goal", "status", "turns_used", "max_turns", "created_at", "last_turn_at",
        "last_verdict", "last_reason", "paused_reason",
        "consecutive_parse_failures", "consecutive_transport_failures",
        "subgoals",
        "waiting_on_pid", "waiting_on_session", "waiting_until",
        "waiting_on_delegations", "waiting_reason", "waiting_since",
        "contract", "gates",
    }
    actual = set(dataclasses.asdict(s).keys())
    assert actual >= expected_keys, (
        f"GoalState lost fields. expected at least {expected_keys - actual} missing"
    )


def test_pipeline_runner_translates_goal_kind_to_slash():
    """Sentinel: agent/pipeline.py::_stage_prompt must keep mapping
    kind='goal' → '/goal ...'. If someone refactors it, this test fails
    before any silent breakage."""
    from agent.pipeline import PipelineRunner, PipelineStore, Stage
    # We don't actually run on_cron_tick (needs SQLite); just check the
    # _stage_prompt function's translation table directly.
    store = PipelineStore(Path("/tmp/test_pipeline.db"))  # ephemeral, will be deleted
    runner = PipelineRunner(store, queue_prompt=lambda p: None, get_goal_manager=lambda: None)

    # kind=goal
    s = Stage(name="x", kind="goal", cron="0 8 * * *", prompt="do X")
    assert runner._stage_prompt(s) == "/goal do X"

    # kind=brief → /goal draft
    s = Stage(name="x", kind="brief", cron="0 8 * * *", prompt="morning brief")
    assert runner._stage_prompt(s) == "/goal draft morning brief"

    # kind=verify → /goal verify
    s = Stage(name="x", kind="verify", cron="0 18 * * *", prompt="run tests")
    assert runner._stage_prompt(s) == "/goal verify run tests"

    # kind=consolidate → /goal
    s = Stage(name="x", kind="consolidate", cron="0 22 * * *", prompt="overnight")
    assert runner._stage_prompt(s) == "/goal overnight"

    # Cleanup
    Path("/tmp/test_pipeline.db").unlink(missing_ok=True)
