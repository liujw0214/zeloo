"""Tests for agent/conversation_loop.py — boundary conditions & edge cases."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

if TYPE_CHECKING:
    pass


from agent.conversation_loop import ConversationLoop


class MockAgent:
    def __init__(self) -> None:
        self.tool_schemas: list[dict] = []
        self._call_count = 0
        self._responses: list[dict] = []
        self._tools: dict[str, callable] = {}

    def get_cached_system_prompt(self) -> str:
        return "system prompt"

    def invalidate_system_prompt(self) -> None:
        pass

    def call_llm(self, messages: list[dict]) -> dict:
        self._call_count += 1
        if self._responses:
            return self._responses.pop(0)
        return {"content": "done", "tool_calls": None}

    def call_llm_stream(self, messages: list[dict], on_token: Any) -> dict:
        return self.call_llm(messages)

    def execute_tool(self, name: str, args: dict) -> str:
        if name in self._tools:
            return self._tools[name](args)
        return f"executed {name}"


def make_tool_schema(name: str, params: dict) -> dict:
    return {"function": {"name": name, "parameters": params}}


def make_tool_call(tool_id: str, name: str, arguments: dict) -> dict:
    return {
        "id": tool_id,
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


class TestConversationLoopBasics:
    def test_instantiation_defaults(self) -> None:
        agent = MockAgent()
        loop = ConversationLoop(agent)
        assert loop.max_iterations == 90
        assert loop.max_workers == 8
        assert loop.llm_max_retries == 3
        assert loop.iteration_budget_remaining == 90
        assert loop._interrupt_requested is False

    def test_instantiation_custom_params(self) -> None:
        agent = MockAgent()
        loop = ConversationLoop(agent, max_iterations=5, max_workers=2, llm_max_retries=1)
        assert loop.max_iterations == 5
        assert loop.max_workers == 2
        assert loop.llm_max_retries == 1
        assert loop.iteration_budget_remaining == 5


class TestIterationBudget:
    def test_budget_grace_call_allows_final_wrap_up(self) -> None:
        agent = MockAgent()
        agent._responses = [
            {"content": "step 1", "tool_calls": [make_tool_call("tc1", "noop", {})]},
            {"content": "step 2", "tool_calls": [make_tool_call("tc2", "noop", {})]},
            {"content": "final answer", "tool_calls": None},
        ]
        agent._tools = {"noop": lambda _: "ok"}
        loop = ConversationLoop(agent, max_iterations=2)
        messages = [{"role": "user", "content": "do two things"}]
        result = loop.run(messages)
        assert agent._call_count == 3
        assert "final answer" in result

    def test_max_iterations_reached_returns_partial(self) -> None:
        agent = MockAgent()
        agent._responses = [
            {"content": "", "tool_calls": [make_tool_call("tc1", "noop", {})]}
            for _ in range(20)
        ]
        agent._tools = {"noop": lambda _: "ok"}
        loop = ConversationLoop(agent, max_iterations=2)
        messages = [{"role": "user", "content": "do many things"}]
        result = loop.run(messages)
        assert agent._call_count == 3
        assert "[Task max_iterations]" in result

    def test_api_call_count_increments(self) -> None:
        agent = MockAgent()
        agent._responses = [
            {"content": "response 1", "tool_calls": None},
        ]
        loop = ConversationLoop(agent, max_iterations=10)
        loop.run([{"role": "user", "content": "hello"}])
        assert loop.api_call_count == 1

    def test_iteration_budget_decrements(self) -> None:
        agent = MockAgent()
        agent._responses = [
            {"content": "", "tool_calls": [make_tool_call("tc1", "noop", {})]}
            for _ in range(5)
        ]
        agent._tools = {"noop": lambda _: "ok"}
        loop = ConversationLoop(agent, max_iterations=5)
        loop.run([{"role": "user", "content": "hi"}])
        assert loop.iteration_budget_remaining == 0


class TestInterrupt:
    def test_interrupt_stops_loop_early(self) -> None:
        agent = MockAgent()
        agent._responses = [
            {"content": "", "tool_calls": [make_tool_call("tc1", "noop", {})]}
            for _ in range(20)
        ]
        agent._tools = {"noop": lambda _: "ok"}
        loop = ConversationLoop(agent, max_iterations=20)

        def interrupt_delayed():
            import time
            time.sleep(0.01)
            loop.request_interrupt()

        import threading
        t = threading.Thread(target=interrupt_delayed)
        t.start()
        messages = [{"role": "user", "content": "interrupt me"}]
        loop.run(messages)
        t.join()
        assert loop.api_call_count >= 1
        assert loop._interrupt_requested is True

    def test_interrupt_during_tool_execution_cancels_pending(self) -> None:
        agent = MockAgent()
        slow_calls = 0

        def slow_tool(_):
            nonlocal slow_calls
            slow_calls += 1
            import time
            time.sleep(0.05)
            return "done"

        agent._tools = {"slow": slow_tool}
        agent._responses = [
            {"content": "", "tool_calls": [make_tool_call("tc1", "slow", {})]},
            {"content": "final", "tool_calls": None},
        ]

        loop = ConversationLoop(agent, max_iterations=2, max_workers=2)

        def interrupt_after_start():
            import time
            time.sleep(0.01)
            loop.request_interrupt()

        import threading
        t = threading.Thread(target=interrupt_after_start)
        t.start()
        messages = [{"role": "user", "content": "interrupt me"}]
        loop.run(messages)
        t.join()
        assert loop.api_call_count >= 1


class TestLLMRetry:
    def test_llm_returns_none_when_unavailable_after_retries(self) -> None:
        agent = MockAgent()
        call_count = 0

        def failing_llm(messages):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("rate limit exceeded")

        agent.call_llm = failing_llm
        loop = ConversationLoop(agent, llm_max_retries=2, llm_retry_base_delay=0.01)
        result = loop.run([{"role": "user", "content": "hello"}])
        assert call_count == 3
        assert result == "[LLM unavailable after retries]"

    def test_non_transient_error_fails_immediately(self) -> None:
        agent = MockAgent()

        def failing_llm(messages):
            raise RuntimeError("invalid request: bad api key")

        agent.call_llm = failing_llm
        loop = ConversationLoop(agent, llm_max_retries=2, llm_retry_base_delay=0.01)
        result = loop.run([{"role": "user", "content": "hello"}])
        assert result == "[LLM unavailable after retries]"


class TestTransientErrorDetection:
    def test_transient_error_markers(self) -> None:
        markers = [
            "rate limit exceeded",
            "rate_limit error",
            "429 Too Many Requests",
            "connection timeout",
            "timed out",
            "server overloaded 503",
            "500 internal error",
        ]
        for text in markers:
            assert ConversationLoop._is_transient_error(text) is True, f"Should detect: {text}"

    def test_non_transient_error_not_flagged(self) -> None:
        non_transient = [
            "invalid api key",
            "model not found",
            "unauthorized access",
            "content policy violation",
            "invalid parameter",
        ]
        for text in non_transient:
            assert ConversationLoop._is_transient_error(text) is False, f"Should not flag: {text}"


class TestContextCompression:
    def test_no_compression_when_under_threshold(self) -> None:
        agent = MockAgent()
        agent._responses = [{"content": "short", "tool_calls": None}]
        loop = ConversationLoop(agent)
        messages = [{"role": "user", "content": "hi"}] * 5
        with patch("agent.conversation_loop.count_message_tokens", return_value=100):
            with patch.object(loop, "_maybe_compress_context", wraps=loop._maybe_compress_context) as mock:
                loop.run(messages)
                assert mock.call_count == 1

    def test_compression_reduces_message_count(self) -> None:
        agent = MockAgent()
        agent._responses = [{"content": "done", "tool_calls": None}]
        agent._tools = {}
        loop = ConversationLoop(agent)
        messages = [{"role": "user", "content": "test"}] * 50
        with patch("agent.conversation_loop.count_message_tokens", return_value=200000):
            loop.run(messages)
            assert len(messages) < 50

    def test_compression_keeps_first_and_recent_messages(self) -> None:
        agent = MockAgent()
        agent._responses = [{"content": "done", "tool_calls": None}]
        loop = ConversationLoop(agent)
        messages = [{"role": "user", "content": f"msg{i}"} for i in range(60)]
        original_first = messages[0]["content"]
        original_last = messages[-1]["content"]
        with patch("agent.conversation_loop.count_message_tokens", return_value=200000):
            loop.run(messages)
        assert messages[0]["content"] == original_first
        assert any(m["content"] == original_last for m in messages[-5:])


class TestToolArgumentValidation:
    def test_validate_missing_required_argument(self) -> None:
        agent = MockAgent()
        agent.tool_schemas = [
            make_tool_schema("greet", {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            })
        ]
        loop = ConversationLoop(agent)
        error = loop._validate_tool_args("greet", {})
        assert error is not None
        assert "name" in error

    def test_validate_wrong_type_argument(self) -> None:
        agent = MockAgent()
        agent.tool_schemas = [
            make_tool_schema("add", {
                "type": "object",
                "properties": {"x": {"type": "integer"}},
                "required": ["x"],
            })
        ]
        loop = ConversationLoop(agent)
        error = loop._validate_tool_args("add", {"x": "not_an_int"})
        assert error is not None
        assert "integer" in error

    def test_validate_extra_args_allowed(self) -> None:
        agent = MockAgent()
        agent.tool_schemas = [
            make_tool_schema("echo", {
                "type": "object",
                "properties": {"msg": {"type": "string"}},
                "required": [],
            })
        ]
        loop = ConversationLoop(agent)
        error = loop._validate_tool_args("echo", {"msg": "hi", "extra": 123})
        assert error is None

    def test_validate_unknown_tool_passes(self) -> None:
        agent = MockAgent()
        loop = ConversationLoop(agent)
        error = loop._validate_tool_args("unknown_tool", {"arg": 1})
        assert error is None


class TestTypeChecking:
    def test_check_type_string(self) -> None:
        assert ConversationLoop._check_type("hello", "string") is True
        assert ConversationLoop._check_type(123, "string") is False

    def test_check_type_integer(self) -> None:
        assert ConversationLoop._check_type(42, "integer") is True
        assert ConversationLoop._check_type(3.14, "integer") is False
        assert ConversationLoop._check_type(True, "integer") is False

    def test_check_type_boolean(self) -> None:
        assert ConversationLoop._check_type(True, "boolean") is True
        assert ConversationLoop._check_type(False, "boolean") is True
        assert ConversationLoop._check_type(1, "boolean") is False

    def test_check_type_array(self) -> None:
        assert ConversationLoop._check_type([1, 2, 3], "array") is True
        assert ConversationLoop._check_type("abc", "array") is False

    def test_check_type_object(self) -> None:
        assert ConversationLoop._check_type({"a": 1}, "object") is True
        assert ConversationLoop._check_type("{}", "object") is False

    def test_check_type_unknown_schema_type(self) -> None:
        assert ConversationLoop._check_type("anything", "unknown_type") is True


class TestPartialResponse:
    def test_partial_response_returns_last_assistant_content(self) -> None:
        agent = MockAgent()
        loop = ConversationLoop(agent)
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        result = loop._partial_response(messages)
        assert result == "hi there"

    def test_partial_response_empty_messages(self) -> None:
        agent = MockAgent()
        loop = ConversationLoop(agent)
        result = loop._partial_response([], reason="budget_exhausted")
        assert result == "[Task budget_exhausted]"

    def test_partial_response_skips_tool_messages(self) -> None:
        agent = MockAgent()
        loop = ConversationLoop(agent)
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": None, "tool_calls": []},
            {"role": "tool", "content": "tool result"},
            {"role": "assistant", "content": "final answer"},
        ]
        result = loop._partial_response(messages)
        assert result == "final answer"


class TestSanitizeResult:
    def test_sanitize_truncates_long_result(self) -> None:
        agent = MockAgent()
        agent._tools = {"long_tool": lambda _: "x" * 10000}
        agent._responses = [
            {"content": "", "tool_calls": [make_tool_call("tc1", "long_tool", {})]},
            {"content": "done", "tool_calls": None},
        ]
        loop = ConversationLoop(agent)
        messages = [{"role": "user", "content": "run long tool"}]
        with patch("agent.zeloo_constants.MAX_TOOL_RESULT_LENGTH", 100):
            loop.run(messages)
        tool_msg = next((m for m in messages if m.get("role") == "tool"), None)
        assert tool_msg is not None
        assert len(tool_msg["content"]) <= 115


class TestParallelToolExecution:
    def test_tools_execute_in_parallel(self) -> None:
        agent = MockAgent()
        start_times: list[float] = []

        def timing_tool(args):
            import time
            start_times.append(time.time())
            time.sleep(0.05)
            return "done"

        agent._tools = {"t1": timing_tool, "t2": timing_tool}
        agent._responses = [
            {
                "content": "",
                "tool_calls": [
                    make_tool_call("tc1", "t1", {}),
                    make_tool_call("tc2", "t2", {}),
                ],
            },
            {"content": "final", "tool_calls": None},
        ]
        loop = ConversationLoop(agent, max_workers=4)
        loop.run([{"role": "user", "content": "run both"}])
        assert len(start_times) == 2
        time_diff = abs(start_times[0] - start_times[1])
        assert time_diff < 0.03


class TestESTOP:
    def test_estop_aborts_loop(self) -> None:
        from agent.estop import estop

        agent = MockAgent()
        agent._responses = [
            {"content": "", "tool_calls": [make_tool_call("tc1", "noop", {})]}
            for _ in range(10)
        ]
        agent._tools = {"noop": lambda _: "ok"}
        loop = ConversationLoop(agent, max_iterations=10)
        estop.trigger("test reason")
        try:
            result = loop.run([{"role": "user", "content": "test"}])
            assert loop.api_call_count == 0
            assert "[emergency stop: test reason]" in result
        finally:
            estop.reset()


class TestGraceCallStreaming:
    def test_grace_call_condition_with_on_token(self) -> None:
        agent = MockAgent()
        agent._responses = [
            {"content": "", "tool_calls": [make_tool_call("tc1", "noop", {})]},
            {"content": "wrapped up", "tool_calls": None},
        ]
        agent._tools = {"noop": lambda _: "ok"}
        loop = ConversationLoop(agent, max_iterations=2)
        messages = [{"role": "user", "content": "test"}]
        result = loop.run(messages, on_token=lambda x: None)
        assert loop.api_call_count == 2
        assert "wrapped up" in result


class TestMessageAccumulation:
    def test_assistant_and_tool_messages_accumulate(self) -> None:
        agent = MockAgent()
        agent._responses = [
            {"content": "", "tool_calls": [make_tool_call("tc1", "noop", {})]},
            {"content": "final answer", "tool_calls": None},
        ]
        agent._tools = {"noop": lambda _: "tool result"}
        loop = ConversationLoop(agent, max_iterations=2)
        messages = [{"role": "user", "content": "test"}]
        loop.run(messages)
        roles = [m["role"] for m in messages]
        assert roles.count("assistant") == 2
        assert roles.count("tool") == 1
        assert roles.count("user") == 1


class TestEmptyToolCalls:
    def test_empty_tool_calls_returns_content(self) -> None:
        agent = MockAgent()
        agent._responses = [{"content": "direct response", "tool_calls": []}]
        loop = ConversationLoop(agent, max_iterations=5)
        result = loop.run([{"role": "user", "content": "hello"}])
        assert result == "direct response"
        assert agent._call_count == 1
