"""Tests for ContextEngine, CompressionFacade, ContextCompressor,
ConversationCompressor, AgentCoordinator, and Pipeline."""

import time
from unittest.mock import MagicMock

from agent.agents_workflow import AgentCoordinator, TaskStatus
from agent.agents_workflow.pipeline import Pipeline, PipelineStage
from agent.compression_facade import (
    CompressionFacade,
    CompressionMode,
    CompressionResult,
)
from agent.context_breakdown import breakdown_by_tokens, breakdown_by_turns
from agent.context_compressor import CompressionStrategy, ContextCompressor, Message
from agent.context_engine import ContextConfig, ContextEngine
from agent.conversation_compression import ConversationCompressor

# ── ContextCompressor ────────────────────────────────────────────

class TestContextCompressor:
    def test_init_default(self):
        c = ContextCompressor()
        assert c.max_tokens == 128000

    def test_init_custom(self):
        c = ContextCompressor(max_tokens=60000, reserved_tokens=2048)
        assert c.max_tokens == 60000
        assert c.reserved_tokens == 2048


# ── ConversationCompressor ────────────────────────────────────────

class TestConversationCompressor:
    def test_init_default(self):
        c = ConversationCompressor()
        assert c.min_recent_turns == 3

    def test_init_custom(self):
        c = ConversationCompressor(min_recent_turns=5)
        assert c.min_recent_turns == 5

    def test_preserve_recent_turns(self):
        c = ConversationCompressor(min_recent_turns=2)
        msgs = [
            {"role": "user", "content": "turn 1"},
            {"role": "assistant", "content": "reply 1"},
            {"role": "user", "content": "turn 2"},
            {"role": "assistant", "content": "reply 2"},
            {"role": "user", "content": "turn 3"},
            {"role": "assistant", "content": "reply 3"},
        ]
        older, recent = c.preserve_recent_turns(msgs, min_recent_turns=2)
        assert len(older) == 2
        assert len(recent) == 4

    def test_compress_for_model_returns_list(self):
        c = ConversationCompressor()
        msgs = [{"role": "user", "content": "hello"}] * 5
        result = c.compress_for_model(msgs, model="gpt-4o")
        assert isinstance(result, list)

    def test_extract_tool_call_patterns(self):
        c = ConversationCompressor()
        msgs = [
            {"role": "assistant", "content": "<tool_call><name>web_search</name><args>{\"query\":\"x\"}</args></tool_call>"},  # noqa: E501
            {"role": "tool", "name": "web_search", "content": "result"},
            {"role": "assistant", "content": "<tool_call><name>file_read</name><args>{\"path\":\"/a\"}</args></tool_call>"},  # noqa: E501
        ]
        patterns = c.extract_tool_call_patterns(msgs)
        assert any("web_search" in p for p in patterns)
        assert any("file_read" in p for p in patterns)


# ── CompressionFacade ─────────────────────────────────────────────

class TestCompressionFacade:
    def test_init_defaults(self):
        f = CompressionFacade()
        assert f.default_mode == CompressionMode.AUTO
        assert f._stats["total_compressions"] == 0

    def test_compress_empty(self):
        f = CompressionFacade()
        result = f.compress([])
        assert result == []

    def test_compress_disabled_mode(self):
        f = CompressionFacade(default_mode=CompressionMode.DISABLED)
        msgs = [{"role": "user", "content": "x"}] * 50
        result = f.compress(msgs, mode=CompressionMode.DISABLED)
        assert len(result) == len(msgs)

    def test_compress_returns_list(self):
        f = CompressionFacade()
        msgs = [{"role": "user", "content": "hello"}] * 10
        result = f.compress(msgs, mode=CompressionMode.TRUNCATE)
        assert isinstance(result, list)

    def test_set_strategy(self):
        f = CompressionFacade()
        f.set_strategy(CompressionStrategy.SUMMARIZE)
        assert f._override_strategy == CompressionStrategy.SUMMARIZE

    def test_reset_strategy(self):
        f = CompressionFacade()
        f.set_strategy(CompressionStrategy.TRUNCATE)
        f.reset_strategy()
        assert f._override_strategy is None

    def test_estimate_savings_empty(self):
        f = CompressionFacade()
        assert f.estimate_savings([]) == 0.0

    def test_estimate_savings_nonempty(self):
        f = CompressionFacade()
        msgs = [{"role": "user", "content": "x"}] * 10
        savings = f.estimate_savings(msgs)
        assert isinstance(savings, float)
        assert 0.0 <= savings <= 1.0

    def test_get_stats(self):
        f = CompressionFacade()
        stats = f.get_stats()
        assert "total_compressions" in stats
        assert "total_tokens_saved" in stats

    def test_compress_from_objects(self):
        f = CompressionFacade()
        msgs = [Message(role="user", content="hello", token_count=2)]
        result = f.compress_from_objects(msgs)
        assert isinstance(result, list)


# ── ContextBreakdown ───────────────────────────────────────────────

class TestContextBreakdown:
    def test_breakdown_by_tokens(self):
        text = " ".join(["word"] * 100)
        chunks = breakdown_by_tokens(text, chunk_size=10)
        assert len(chunks) > 1
        assert all(isinstance(c, str) for c in chunks)

    def test_breakdown_by_tokens_empty(self):
        chunks = breakdown_by_tokens("")
        assert chunks == []

    def test_breakdown_by_turns(self):
        msgs = [
            Message(role="user", content="q1", token_count=1),
            Message(role="assistant", content="a1", token_count=1),
            Message(role="user", content="q2", token_count=1),
            Message(role="assistant", content="a2", token_count=1),
        ]
        groups = breakdown_by_turns(msgs, chunk_turns=2)
        assert isinstance(groups, list)
        assert all(isinstance(g, list) for g in groups)

    def test_breakdown_by_turns_single(self):
        msgs = [Message(role="user", content="hi", token_count=1)]
        groups = breakdown_by_turns(msgs, chunk_turns=2)
        assert len(groups) == 1


# ── ContextEngine ─────────────────────────────────────────────────

class TestContextEngine:
    def test_init_default(self):
        ce = ContextEngine()
        assert ce.config.model == "gpt-4o"
        assert ce.config.max_context_tokens == 128000
        assert ce.config.compression_mode == "auto"
        assert ce.config.preserve_recent_turns == 3

    def test_init_custom_config(self):
        cfg = ContextConfig(model="claude-3-5-sonnet", max_context_tokens=200000)
        ce = ContextEngine(config=cfg)
        assert ce.config.model == "claude-3-5-sonnet"
        assert ce.config.max_context_tokens == 200000

    def test_add_message(self):
        ce = ContextEngine()
        ce.add_message({"role": "user", "content": "hello"})
        assert len(ce._message_cache) == 1

    def test_add_messages(self):
        ce = ContextEngine()
        ce.add_messages([
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hey"},
        ])
        assert len(ce._message_cache) == 2

    def test_get_messages_returns_list(self):
        ce = ContextEngine()
        ce.add_message({"role": "user", "content": "hello"})
        msgs = ce.get_messages()
        assert isinstance(msgs, list)
        assert len(msgs) == 1

    def test_get_messages_compressed_false(self):
        ce = ContextEngine()
        ce.add_message({"role": "user", "content": "hello"})
        msgs = ce.get_messages(compressed=False)
        assert isinstance(msgs, list)

    def test_force_compress(self):
        ce = ContextEngine()
        for i in range(20):
            ce.add_message({"role": "user", "content": f"message {i}"})
        result = ce.force_compress()
        assert isinstance(result, CompressionResult)
        assert result.original_count >= result.compressed_count

    def test_get_token_budget(self):
        ce = ContextEngine()
        budget = ce.get_token_budget()
        assert "budget_total" in budget
        assert "budget_used" in budget
        assert "budget_remaining" in budget
        assert "utilization" in budget
        assert budget["budget_total"] == 128000

    def test_clear(self):
        ce = ContextEngine()
        ce.add_message({"role": "user", "content": "hi"})
        ce.clear()
        assert len(ce._message_cache) == 0

    def test_get_stats(self):
        ce = ContextEngine()
        stats = ce.get_stats()
        assert "message_count" in stats
        assert "compression_stats" in stats
        assert "token_budget" in stats

    def test_set_model(self):
        ce = ContextEngine()
        ce.set_model("claude-3-5-sonnet")
        assert ce.config.model == "claude-3-5-sonnet"
        assert ce.config.max_context_tokens == 200000

    def test_set_compression_mode(self):
        ce = ContextEngine()
        ce.set_compression_mode("hybrid")
        assert ce.config.compression_mode == "hybrid"

    def test_get_message_groups(self):
        ce = ContextEngine()
        for i in range(6):
            ce.add_message({"role": "user", "content": f"q{i}"})
            ce.add_message({"role": "assistant", "content": f"a{i}"})
        groups = ce.get_message_groups()
        assert isinstance(groups, list)


# ── AgentCoordinator ─────────────────────────────────────────────

class TestAgentCoordinator:
    def test_init_empty(self):
        coord = AgentCoordinator()
        assert coord.agents == {}
        assert coord._tasks == {}

    def test_add_agent(self):
        coord = AgentCoordinator()
        mock_agent = MagicMock()
        coord.add_agent("worker1", mock_agent)
        assert "worker1" in coord.agents
        assert coord.agents["worker1"] is mock_agent

    def test_create_task(self):
        coord = AgentCoordinator()
        task_id = coord.create_task("do something", assignee="worker1")
        assert task_id.startswith("task-")
        task = coord.get_task(task_id)
        assert task is not None
        assert task.description == "do something"
        assert task.assignee == "worker1"
        assert task.status == TaskStatus.PENDING

    def test_create_task_with_dependency(self):
        coord = AgentCoordinator()
        id1 = coord.create_task("step 1", assignee="a")
        id2 = coord.create_task("step 2", assignee="b", depends_on=[id1])
        task2 = coord.get_task(id2)
        assert id1 in task2.metadata["depends_on"]

    def test_run_task_not_found(self):
        coord = AgentCoordinator()
        result = coord.run_task("nonexistent")
        assert result.success is False
        assert "not found" in result.error.lower()

    def test_run_task_agent_not_found(self):
        coord = AgentCoordinator()
        coord.create_task("task", assignee="ghost")
        result = coord.run_task("task-0")
        assert result.success is False

    def test_run_task_success(self):
        coord = AgentCoordinator()
        mock_agent = MagicMock()
        mock_agent.run_conversation.return_value = "Hello!"
        coord.add_agent("bot", mock_agent)
        coord.create_task("greet", assignee="bot")
        result = coord.run_task("task-0")
        assert result.success is True
        assert result.output == "Hello!"
        mock_agent.run_conversation.assert_called_once_with("greet")

    def test_run_task_exception(self):
        coord = AgentCoordinator()
        mock_agent = MagicMock()
        mock_agent.run_conversation.side_effect = RuntimeError("boom")
        coord.add_agent("bad", mock_agent)
        coord.create_task("fail", assignee="bad")
        result = coord.run_task("task-0")
        assert result.success is False
        assert "boom" in result.error

    def test_run_all_parallel(self):
        coord = AgentCoordinator()
        results_store = {}

        def make_agent(name):
            agent = MagicMock()
            def run(msg):
                results_store[name] = msg
                time.sleep(0.05)
                return f"done:{name}"
            agent.run_conversation.side_effect = run
            return agent

        coord.add_agent("w1", make_agent("w1"))
        coord.add_agent("w2", make_agent("w2"))
        coord.create_task("job1", assignee="w1")
        coord.create_task("job2", assignee="w2")
        results = coord.run_all(ordered=False)
        assert len(results) == 2
        assert all(r.success for r in results.values())

    def test_run_all_ordered(self):
        coord = AgentCoordinator()
        order = []

        def make_agent(name):
            agent = MagicMock()
            def run(msg):
                order.append(name)
                return f"done:{name}"
            agent.run_conversation.side_effect = run
            return agent

        coord.add_agent("first", make_agent("first"))
        coord.add_agent("second", make_agent("second"))
        coord.create_task("a", assignee="first")
        coord.create_task("b", assignee="second")
        coord.run_all(ordered=True)
        assert order == ["first", "second"]

    def test_summarize_empty(self):
        coord = AgentCoordinator()
        s = coord.summarize()
        assert s["total"] == 0
        assert s["completed"] == 0
        assert s["pending"] == 0

    def test_summarize_with_tasks(self):
        coord = AgentCoordinator()
        coord.create_task("t1", assignee="a")
        coord.create_task("t2", assignee="b")
        s = coord.summarize()
        assert s["total"] == 2
        assert s["pending"] == 2

    def test_get_results_empty(self):
        coord = AgentCoordinator()
        assert coord.get_results() == {}


# ── Pipeline ─────────────────────────────────────────────────────

class TestPipelineStage:
    def test_process_no_processor(self):
        stage = PipelineStage(name="test", agent_name="a")
        assert stage.process("input") == "input"

    def test_process_with_processor(self):
        stage = PipelineStage(
            name="double", agent_name="a",
            processor=lambda x: x * 2,
        )
        assert stage.process(5) == 10

    def test_should_run_no_condition(self):
        stage = PipelineStage(name="test", agent_name="a")
        assert stage.should_run({}) is True

    def test_should_run_with_condition(self):
        stage = PipelineStage(
            name="test", agent_name="a",
            condition=lambda ctx: ctx.get("flag") is True,
        )
        assert stage.should_run({"flag": True}) is True
        assert stage.should_run({"flag": False}) is False

    def test_should_run_condition_exception(self):
        stage = PipelineStage(name="test", agent_name="a", condition=lambda ctx: 1 / 0)
        assert stage.should_run({}) is True  # falls through on error


class TestPipeline:
    def test_init(self):
        p = Pipeline(name="test")
        assert p.name == "test"
        assert p.stages == []

    def test_add_stage(self):
        p = Pipeline(name="test")
        p.add_stage("s1", "agent1")
        assert len(p.stages) == 1
        assert p.stages[0].name == "s1"

    def test_add_stage_returns_pipeline(self):
        p = Pipeline(name="test")
        result = p.add_stage("s1", "a")
        assert result is p  # fluent interface

    def test_execute_no_stages(self):
        p = Pipeline(name="empty")
        agents = {}
        result = p.execute(agents, {"data": 42})
        assert result["final_output"] == {"data": 42}

    def test_execute_single_stage(self):
        p = Pipeline(name="test")
        p.add_stage("double", "a", processor=lambda x: {"data": x["data"] * 2})
        mock_agent = MagicMock()
        mock_agent.run_conversation.return_value = "done"
        result = p.execute({"a": mock_agent}, {"data": 5})
        assert result["final_output"] == "done"
        assert result["stage_outputs"] == ["done"]

    def test_execute_with_condition_skip(self):
        p = Pipeline(name="test")
        p.add_stage("double", "a", processor=lambda x: {"data": x["data"] * 2})
        p.add_stage("+10", "b", processor=lambda x: {"data": x.get("data", 0) + 10},
                    condition=lambda ctx: ctx.get("skip") is True)
        mock_agent = MagicMock()
        mock_agent.run_conversation.return_value = "ok"
        result = p.execute({"a": mock_agent, "b": mock_agent}, {"data": 3})
        assert len(result["stage_outputs"]) == 1

    def test_execute_with_agent_not_found(self):
        p = Pipeline(name="test")
        p.add_stage("s1", "ghost", processor=lambda x: x)
        result = p.execute({}, {"data": 1})
        assert "error" in result["s1"]

    def test_pipeline_stage_uses_agent(self):
        p = Pipeline(name="test")
        p.add_stage("ask", "bot", processor=lambda x: {"data": x})
        mock_agent = MagicMock()
        mock_agent.run_conversation.return_value = "answer"
        _ = p.execute({"bot": mock_agent}, "question")
        mock_agent.run_conversation.assert_called_once_with({"data": "question"})
