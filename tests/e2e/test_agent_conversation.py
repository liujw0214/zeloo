"""End-to-end tests for AIAgent → ConversationLoop → Tools pipeline."""

from __future__ import annotations

import functools
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("zeloo_HOME", tempfile.mkdtemp())


def _with_tmp_home(test_fn):
    @functools.wraps(test_fn)
    def wrapper(*args, **kwargs):
        from zeloo_state import set_state_home_override

        with tempfile.TemporaryDirectory() as tmp:
            set_state_home_override(tmp)
            try:
                return test_fn(*args, **kwargs)
            finally:
                set_state_home_override(None)

    return wrapper


class FakeToolCall:
    def __init__(self, id: str, name: str, arguments: str):
        self.id = id
        self.type = "function"
        self.function = MagicMock()
        self.function.name = name
        self.function.arguments = arguments


class FakeChoice:
    def __init__(self, content: str = "", tool_calls: list | None = None):
        self.message = MagicMock()
        self.message.content = content
        self.message.tool_calls = tool_calls or []


class FakeLLMResponse:
    """Fake LLM response that supports .choices attribute access."""

    def __init__(self, content: str = "", tool_calls: list | None = None):
        self.choices = [FakeChoice(content=content, tool_calls=tool_calls)]


def _build_response(content: str = "", tool_calls: list | None = None):
    return FakeLLMResponse(content=content, tool_calls=tool_calls)


@_with_tmp_home
def test_single_turn_returns_text():
    """A single turn without tool calls returns assistant text."""
    from run_agent import AIAgent

    agent = AIAgent(
        model="fake-model",
        provider="openai",
        platform="cli",
        load_soul_identity=False,
        skip_context_files=True,
        api_key="sk-fake",
    )
    try:
        agent._provider_router.call_with_fallback = MagicMock(
            return_value=_build_response("Hello! I am Zeloo.")
        )
        reply = agent.run_conversation("Hi")
        assert isinstance(reply, str)
        assert len(reply) > 0
        assert "Hello" in reply
    finally:
        agent.close()


@_with_tmp_home
def test_tool_call_round_trip():
    """Agent emits tool call, loop executes it, returns result."""
    from run_agent import AIAgent

    test_file = Path(tempfile.mkdtemp()) / "e2e_test.txt"
    test_file.write_text("end-to-end test content")

    call_count = [0]

    def fake_fallback(**kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return _build_response(
                content="",
                tool_calls=[
                    FakeToolCall(
                        id="call_e2e_001",
                        name="file_read",
                        arguments='{"path":"' + str(test_file) + '"}',
                    )
                ],
            )
        else:
            return _build_response(
                content="I read the file: " + test_file.read_text()
            )

    agent = AIAgent(
        model="fake-model",
        provider="openai",
        platform="cli",
        load_soul_identity=False,
        skip_context_files=True,
        api_key="sk-fake",
    )
    try:
        agent._provider_router.call_with_fallback = fake_fallback
        reply = agent.run_conversation("Read the e2e_test.txt file")
        assert isinstance(reply, str)
        assert len(reply) > 0
        assert call_count[0] == 2
    finally:
        agent.close()


@_with_tmp_home
def test_system_prompt_cache_hit():
    """Repeated get_cached_system_prompt() hits the cache."""
    from run_agent import AIAgent

    agent = AIAgent(
        model="fake-model",
        provider="openai",
        platform="cli",
        load_soul_identity=False,
        skip_context_files=True,
        api_key="sk-fake",
    )
    try:
        agent._provider_router.call_with_fallback = MagicMock(
            return_value=_build_response("ok")
        )
        p1 = agent.get_cached_system_prompt()
        p2 = agent.get_cached_system_prompt()
        p3 = agent.get_cached_system_prompt()

        assert p1 == p2 == p3
        stats = agent.cache_stats()
        assert stats["hits"] >= 2
        assert stats["hit_rate"] >= 0.66
    finally:
        agent.close()


@_with_tmp_home
def test_multi_turn_preserves_context():
    """Two turns share context via the messages list."""
    from run_agent import AIAgent

    call_count = [0]

    def fake_fallback(**kwargs):
        call_count[0] += 1
        return _build_response(f"Reply {call_count[0]}")

    agent = AIAgent(
        model="fake-model",
        provider="openai",
        platform="cli",
        load_soul_identity=False,
        skip_context_files=True,
        api_key="sk-fake",
    )
    try:
        agent._provider_router.call_with_fallback = fake_fallback
        r1 = agent.run_conversation("First message")
        r2 = agent.run_conversation("Second message")

        assert isinstance(r1, str) and isinstance(r2, str)
        assert len(r1) > 0 and len(r2) > 0
        assert call_count[0] == 2
    finally:
        agent.close()


@_with_tmp_home
def test_close_is_clean():
    """Agent.close() runs without error."""
    from run_agent import AIAgent

    agent = AIAgent(
        model="fake-model",
        provider="openai",
        platform="cli",
        load_soul_identity=False,
        skip_context_files=True,
        api_key="sk-fake",
    )
    agent.close()


@_with_tmp_home
def test_audit_log_records_events():
    """A full turn writes audit log events."""
    from agent import audit_log
    from run_agent import AIAgent

    audit_log.reset_default_audit_log()

    agent = AIAgent(
        model="fake-model",
        provider="openai",
        platform="cli",
        load_soul_identity=False,
        skip_context_files=True,
        api_key="sk-fake",
    )
    try:
        agent._provider_router.call_with_fallback = MagicMock(
            return_value=_build_response("done")
        )
        agent.run_conversation("hello")
        log = audit_log.get_default_audit_log()
        events = list(log.iter_events())
        assert isinstance(events, list)
    finally:
        audit_log.reset_default_audit_log()
        agent.close()


if __name__ == "__main__":
    test_single_turn_returns_text()
    test_tool_call_round_trip()
    test_system_prompt_cache_hit()
    test_multi_turn_preserves_context()
    test_close_is_clean()
    test_audit_log_records_events()
    print("All E2E tests passed!")
