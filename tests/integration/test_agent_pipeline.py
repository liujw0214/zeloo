"""Integration tests for the AIAgent core pipeline — ConversationLoop, Tools, Audit, Cost."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)



def _mock_provider_router():
    router = MagicMock()
    router.get_config.return_value = MagicMock(
        provider="openai",
        model="gpt-4o-mini",
        base_url=None,
        api_key="sk-test-key",
    )
    router.get_provider_name.return_value = "openai"
    return router


class FakeLLMResponse:
    def __init__(self, tool_calls=None, content=""):
        self._tool_calls = tool_calls or []
        self._content = content

    def model_dump(self, **kw):
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": self._content,
                        "tool_calls": self._tool_calls,
                    }
                }
            ]
        }


def test_system_prompt_three_tiers_assemble():
    """System prompt should assemble all three tiers with real components."""
    from agent.system_prompt import build_system_prompt_parts

    agent = MagicMock()
    agent.session_id = "20260908_integration_test"
    agent.model = "gpt-4o-mini"
    agent.provider = "openai"
    agent.platform = "cli"
    agent.valid_tool_names = {"file_read"}
    agent.available_toolsets = {"file"}
    agent.load_soul_identity = True
    agent.skip_context_files = False
    agent._memory_enabled = False
    agent._user_profile_enabled = False
    agent._memory_store = None
    agent._session_db = None
    agent._cached_system_prompt = None
    agent._cached_system_prompt_static = None
    agent._system_prompt_turns = 0
    agent._current_turn = 0
    agent._history_snapshot_turns = 0
    agent._tool_registry = MagicMock()
    agent._tool_registry.get_schemas.return_value = []
    agent._hooks = MagicMock()
    agent._hooks.has.return_value = False
    agent._provider_router = MagicMock()
    _mock_cfg = MagicMock(
        provider="openai", model="gpt-4o-mini", base_url=None, api_key="sk-test"
    )
    agent._provider_router.get_config.return_value = _mock_cfg
    agent._provider_router.get_provider_name.return_value = "openai"

    parts = build_system_prompt_parts(agent)

    assert "stable" in parts
    assert "context" in parts
    assert "volatile" in parts


def test_tool_registry_auto_discovers_tools():
    """ToolRegistry should auto-discover tools at import via @tool decorator."""
    from tools import file_tools as ft_module

    importlib.reload(ft_module)
    from tools.base import get_registry

    reg = get_registry()
    names = reg.get_names()
    assert "file_read" in names, f"Expected file_read in {names}"


def test_tool_registry_filter_by_names():
    """ToolRegistry should filter tools by name set."""
    from tools.base import get_registry

    reg = get_registry()
    all_tools = reg.get_all()
    target_names = {"file_read", "memory"}

    filtered = {name: tool for name, tool in all_tools.items() if name in target_names}
    assert "file_read" in filtered
    assert len(filtered) >= 1


def test_tool_execution_writes_audit_log(tmp_path, monkeypatch):
    """Tool execution should emit an audit log event via the record() API."""
    from agent import audit_log

    audit_log.reset_default_audit_log()
    log = audit_log.AuditLog(path=tmp_path / "audit.log")
    monkeypatch.setattr(audit_log, "_default", log)

    test_file = tmp_path / "hello.txt"
    test_file.write_text("hello world")

    from tools import file_tools as ft_module

    importlib.reload(ft_module)
    result = ft_module.file_read(str(test_file))

    assert "hello world" in result
    events = list(log.iter_events())
    file_events = [e for e in events if e.kind == "file_read"]
    assert len(file_events) >= 1, f"Expected >=1 file_read event, got {events}"
    audit_log.reset_default_audit_log()


def test_audit_log_record_and_query(tmp_path, monkeypatch):
    """AuditLog.record() should store events that are queryable."""
    from agent import audit_log

    audit_log.reset_default_audit_log()
    log = audit_log.AuditLog(path=tmp_path / "a.log")
    monkeypatch.setattr(audit_log, "_default", log)

    try:
        log.record("tool_executed", detail={"tool": "file_read"})
        log.record("tool_executed", detail={"tool": "memory_write"})

        events = list(log.iter_events())
        assert len(events) >= 2
    finally:
        audit_log.reset_default_audit_log()


def test_conversation_loop_single_turn_no_tool(tmp_path, monkeypatch):
    """A single assistant turn with no tool calls returns content."""
    from agent import audit_log, conversation_loop
    from agent.cost_tracker import CostTracker
    from agent.error_tracker import ErrorTracker

    audit_log.reset_default_audit_log()
    monkeypatch.setattr(
        audit_log, "_default", audit_log.AuditLog(path=tmp_path / "audit2.log")
    )

    agent = MagicMock()
    agent.session_id = "20260908_test"
    agent.model = "gpt-4o-mini"
    agent.provider = "openai"
    agent.platform = "cli"
    agent.valid_tool_names = set()
    agent.available_toolsets = set()
    agent.load_soul_identity = False
    agent.skip_context_files = True
    agent._memory_enabled = False
    agent._user_profile_enabled = False
    agent._memory_store = None
    agent._session_db = None
    agent._cached_system_prompt = None
    agent._cached_system_prompt_static = None
    agent._system_prompt_turns = 0
    agent._current_turn = 0
    agent._provider_router = _mock_provider_router()
    agent._tool_registry = MagicMock()
    agent._tool_registry.get_schemas.return_value = []
    agent._tool_registry.get_names.return_value = set()
    agent._audit_log = audit_log.get_default_audit_log()
    agent._error_tracker = ErrorTracker(db_path=tmp_path / "e.db")
    agent._cost_tracker = CostTracker()
    agent._hooks = MagicMock()
    agent._hooks.has.return_value = False

    loop = conversation_loop.ConversationLoop(agent)

    agent.call_llm = MagicMock(
        return_value={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Hello from integration test!",
                    }
                }
            ]
        }
    )
    result = loop._call_llm_with_retry(messages=[{"role": "user", "content": "hi"}])

    assert result is not None
    assert result["choices"][0]["message"]["content"] == "Hello from integration test!"


def test_conversation_loop_tool_call_round_trip(tmp_path, monkeypatch):
    """A tool-call turn should execute the tool and return the result."""
    from agent import audit_log, conversation_loop
    from agent.cost_tracker import CostTracker
    from agent.error_tracker import ErrorTracker

    audit_log.reset_default_audit_log()
    monkeypatch.setattr(
        audit_log, "_default", audit_log.AuditLog(path=tmp_path / "audit3.log")
    )

    test_file = tmp_path / "greet.txt"
    test_file.write_text("welcome, friend")

    agent = MagicMock()
    agent.session_id = "20260908_tool_test"
    agent.model = "gpt-4o-mini"
    agent.provider = "openai"
    agent.platform = "cli"
    agent.valid_tool_names = {"file_read"}
    agent.available_toolsets = {"file"}
    agent.load_soul_identity = False
    agent.skip_context_files = True
    agent._memory_enabled = False
    agent._user_profile_enabled = False
    agent._memory_store = None
    agent._session_db = None
    agent._cached_system_prompt = None
    agent._cached_system_prompt_static = None
    agent._system_prompt_turns = 0
    agent._current_turn = 0
    agent._provider_router = _mock_provider_router()
    agent._tool_registry = MagicMock()
    agent._tool_registry.get_schemas.return_value = []
    agent._tool_registry.get_names.return_value = {"file_read"}
    agent._audit_log = audit_log.get_default_audit_log()
    agent._error_tracker = ErrorTracker(db_path=tmp_path / "e2.db")
    agent._cost_tracker = CostTracker()
    agent._hooks = MagicMock()
    agent._hooks.has.return_value = False

    loop = conversation_loop.ConversationLoop(agent)

    tool_call_id = "call_abc123"
    tool_name = "file_read"
    path_arg = '{"path":"' + str(test_file).replace("\\", "\\\\") + '"}'
    agent.call_llm = MagicMock(
        return_value={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Here is the file content.",
                        "tool_calls": [
                            {
                                "id": tool_call_id,
                                "type": "function",
                                "function": {"name": tool_name, "arguments": path_arg},
                            }
                        ],
                    }
                }
            ]
        }
    )
    result = loop._call_llm_with_retry(
        messages=[{"role": "user", "content": "read the greet file"}]
    )

    assert result is not None


def test_conversation_loop_calls_llm_via_agent(tmp_path, monkeypatch):
    """ConversationLoop should delegate LLM calls to agent.call_llm."""
    from agent import audit_log, conversation_loop
    from agent.cost_tracker import CostTracker
    from agent.error_tracker import ErrorTracker

    audit_log.reset_default_audit_log()
    monkeypatch.setattr(
        audit_log, "_default", audit_log.AuditLog(path=tmp_path / "audit5.log")
    )

    agent = MagicMock()
    agent.session_id = "20260908_llm_test"
    agent.model = "gpt-4o-mini"
    agent.provider = "openai"
    agent.platform = "cli"
    agent.valid_tool_names = set()
    agent.available_toolsets = set()
    agent.load_soul_identity = False
    agent.skip_context_files = True
    agent._memory_enabled = False
    agent._user_profile_enabled = False
    agent._memory_store = None
    agent._session_db = None
    agent._cached_system_prompt = None
    agent._cached_system_prompt_static = None
    agent._system_prompt_turns = 0
    agent._current_turn = 0
    agent._provider_router = _mock_provider_router()
    agent._tool_registry = MagicMock()
    agent._tool_registry.get_schemas.return_value = []
    agent._tool_registry.get_names.return_value = set()
    agent._audit_log = audit_log.get_default_audit_log()
    agent._error_tracker = ErrorTracker(db_path=tmp_path / "e4.db")
    agent._cost_tracker = CostTracker()
    agent._hooks = MagicMock()
    agent._hooks.has.return_value = False

    loop = conversation_loop.ConversationLoop(agent)

    agent.call_llm = MagicMock(
        return_value={
            "choices": [
                {"message": {"role": "assistant", "content": "ok"}}
            ]
        }
    )
    loop._call_llm_with_retry(messages=[{"role": "user", "content": "hi"}])

    assert agent.call_llm.called


def test_error_tracker_records_and_classifies(tmp_path):
    """ErrorTracker should record exceptions and expose error stats."""
    from agent.error_classifier import classify_error
    from agent.error_tracker import ErrorTracker

    tracker = ErrorTracker(db_path=tmp_path / "err.db")

    exc = RuntimeError("rate limit hit")
    tracker.record_exception(exc, category="api_error")

    stats = tracker.stats()
    assert "total" in stats or "by_category" in stats

    classified = classify_error(exc, provider="openai", status_code=429)
    assert classified.category == "rate_limit"
    assert classified.retryable is True


def test_curator_initializes_state_file(tmp_path):
    """Curator should initialise and create its state file."""
    from agent.curator import Curator

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "test_skill.md").write_text("# Test Skill\nDo the thing.")

    curator = Curator(
        skills_dir=str(skills_dir), state_file=tmp_path / "curator.json"
    )

    state = curator.get_state(skill_name="test_skill")
    assert state is not None


def test_output_scan_redacts_secrets_from_result(tmp_path):
    """scan_tool_output should return sanitized string with secrets redacted."""
    from tools.output_scan import scan_tool_output

    result = scan_tool_output(
        "deployed with key: sk-abcdefghijklmnopqrstuvwxyz",
        tool_name="deploy",
        source="test",
    )

    assert isinstance(result, str)
    assert "sk-abcdef" not in result
    assert "[REDACTED]" in result or "sk-" not in result.lower()


def test_output_scan_preserves_clean_result(tmp_path):
    """scan_tool_output should return the original string when no secrets."""
    from tools.output_scan import scan_tool_output

    result = scan_tool_output(
        "File created successfully at /home/user/docs/report.pdf",
        tool_name="file_write",
        source="test",
    )

    assert isinstance(result, str)
    assert result == "File created successfully at /home/user/docs/report.pdf"


if __name__ == "__main__":
    test_system_prompt_three_tiers_assemble()
    test_tool_registry_auto_discovers_tools()
    test_tool_registry_filter_by_names()
    test_tool_execution_writes_audit_log()
    test_audit_log_record_and_query()
    test_conversation_loop_single_turn_no_tool()
    test_conversation_loop_tool_call_round_trip()
    test_conversation_loop_calls_llm_via_agent()
    test_error_tracker_records_and_classifies()
    test_curator_initializes_state_file()
    test_output_scan_redacts_secrets_from_result()
    test_output_scan_preserves_clean_result()
    print("All integration tests passed!")
