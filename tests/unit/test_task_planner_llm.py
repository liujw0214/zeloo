"""Tests for agent/task_planner.py — LLM-based task decomposition."""

from __future__ import annotations

from agent.task_planner import TaskPlanner


class TestLLMDecompositionBasics:
    def test_no_caller_falls_back_to_heuristic(self) -> None:
        planner = TaskPlanner()
        tasks = planner._decompose_with_llm("test goal", None, llm_caller=None)
        assert len(tasks) > 0
        assert any(t.task_id == "analyze_goal" for t in tasks)

    def test_explicit_caller_returns_heuristic_fallback(self) -> None:
        def failing_caller(messages):
            raise RuntimeError("LLM unavailable")

        planner = TaskPlanner()
        tasks = planner._decompose_with_llm("goal", None, llm_caller=failing_caller)
        assert len(tasks) > 0

    def test_json_response_parsed_correctly(self) -> None:
        json_response = (
            '[{"task_id": "step1", "description": "First step", "tool_hint": "reasoning", '
            '"dependencies": [], "estimated_complexity": 3}, '
            '{"task_id": "step2", "description": "Second step", "tool_hint": "execute", '
            '"dependencies": ["step1"], "estimated_complexity": 5}]'
        )

        def fake_caller(messages):
            return {"content": json_response}

        planner = TaskPlanner()
        tasks = planner._decompose_with_llm("test", None, llm_caller=fake_caller)
        assert len(tasks) == 2
        assert tasks[0].task_id == "step1"
        assert tasks[1].dependencies == ["step1"]
        assert tasks[1].estimated_complexity == 5

    def test_invalid_json_falls_back(self) -> None:
        def bad_caller(messages):
            return {"content": "this is not json at all"}

        planner = TaskPlanner()
        tasks = planner._decompose_with_llm("test", None, llm_caller=bad_caller)
        assert len(tasks) > 0

    def test_llm_response_with_prose_extracted(self) -> None:
        def prose_caller(messages):
            return {
            "content": (
                "Here is the plan:\n"
                '[{"task_id": "a", "description": "task A", "tool_hint": "reasoning"}]\n'
                "Let me know if you need more."
            )
            }

        planner = TaskPlanner()
        tasks = planner._decompose_with_llm("test", None, llm_caller=prose_caller)
        assert len(tasks) == 1
        assert tasks[0].task_id == "a"

    def test_empty_llm_response_falls_back(self) -> None:
        def empty_caller(messages):
            return {"content": ""}

        planner = TaskPlanner()
        tasks = planner._decompose_with_llm("test", None, llm_caller=empty_caller)
        assert len(tasks) > 0

    def test_complexity_clamped_to_range(self) -> None:
        def caller(messages):
            return {
            "content": '[{"task_id": "x", "description": "test", "estimated_complexity": 99}]'
            }

        planner = TaskPlanner()
        tasks = planner._decompose_with_llm("test", None, llm_caller=caller)
        assert tasks[0].estimated_complexity == 10

    def test_invalid_dependencies_dropped(self) -> None:
        def caller(messages):
            return {
            "content": '[{"task_id": "a", "description": "x", "dependencies": ["nonexistent"]}]'
            }

        planner = TaskPlanner()
        tasks = planner._decompose_with_llm("test", None, llm_caller=caller)
        assert tasks[0].dependencies == []

    def test_missing_required_fields_skipped(self) -> None:
        def caller(messages):
            return {
            "content": (
                '[{"task_id": "valid", "description": "ok"},'
                ' {"task_id": "", "description": "no id"},'
                ' {"task_id": "no_desc"}]'
            )
            }

        planner = TaskPlanner()
        tasks = planner._decompose_with_llm("test", None, llm_caller=caller)
        assert len(tasks) == 1
        assert tasks[0].task_id == "valid"


class TestBuildPrompt:
    def test_prompt_includes_goal(self) -> None:
        planner = TaskPlanner()
        prompt = planner._build_decomposition_prompt("Build a website", {})
        assert "Build a website" in prompt
        assert "JSON" in prompt
        assert "task_id" in prompt

    def test_prompt_includes_context(self) -> None:
        planner = TaskPlanner()
        prompt = planner._build_decomposition_prompt(
            "test", {"language": "python", "framework": "django"}
        )
        assert "language" in prompt
        assert "python" in prompt
        assert "django" in prompt

    def test_prompt_handles_empty_context(self) -> None:
        planner = TaskPlanner()
        prompt = planner._build_decomposition_prompt("test", {})
        assert "(no context)" in prompt


class TestLLMCallerContract:
    def test_response_must_be_dict(self) -> None:
        def string_caller(messages):
            return "string response"

        planner = TaskPlanner()
        tasks = planner._decompose_with_llm("test", None, llm_caller=string_caller)
        assert len(tasks) > 0

    def test_response_without_content_key(self) -> None:
        def no_content_caller(messages):
            return {"tool_calls": []}

        planner = TaskPlanner()
        tasks = planner._decompose_with_llm("test", None, llm_caller=no_content_caller)
        assert len(tasks) > 0