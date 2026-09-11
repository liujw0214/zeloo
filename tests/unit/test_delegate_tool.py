"""Tests for delegate_tool."""

from __future__ import annotations

import json

from tools.delegate_tool import (
    AgentRole,
    DelegateConfig,
    DelegateTool,
    delegate_task,
)


class TestAgentRole:
    def test_roles_exist(self) -> None:
        assert AgentRole.LEAF.value == "leaf"
        assert AgentRole.ORCHESTRATOR.value == "orchestrator"


class TestDelegateTool:
    def test_execute_invalid_role(self) -> None:
        tool = DelegateTool()
        result = tool.execute(goal="test", role="invalid_role")
        data = json.loads(result)
        assert data["status"] == "error"
        assert "Invalid role" in data["error"]

    def test_execute_minimal(self) -> None:
        tool = DelegateTool()
        result = tool.execute(goal="Say hello in one word", timeout_seconds=5)
        assert isinstance(result, str)
        data = json.loads(result)
        assert "task_id" in data
        assert data["status"] in ("completed", "error", "timeout")

    def test_execute_orchestrator_role(self) -> None:
        tool = DelegateTool()
        result = tool.execute(
            goal="List files in current directory",
            role="orchestrator",
            timeout_seconds=5,
        )
        data = json.loads(result)
        assert data["task_id"]

    def test_execute_timeout(self) -> None:
        tool = DelegateTool()
        result = tool.execute(
            goal="Count to a billion",
            timeout_seconds=1,
        )
        data = json.loads(result)
        assert data["status"] in ("completed", "timeout", "error")

    def test_execute_returns_valid_json(self) -> None:
        tool = DelegateTool()
        result = tool.execute(goal="Return the word OK", timeout_seconds=5)
        data = json.loads(result)
        assert "task_id" in data
        assert "status" in data
        assert "duration_seconds" in data


class TestDelegateTask:
    def test_delegate_task_convenience_wrapper(self) -> None:
        result = delegate_task(
            goal="What is 2+2?",
            timeout_seconds=5,
        )
        data = json.loads(result)
        assert "task_id" in data


class TestDelegateConfig:
    def test_default_config(self) -> None:
        cfg = DelegateConfig()
        assert cfg.role == AgentRole.LEAF
        assert cfg.max_iterations == 10
        assert cfg.timeout_seconds == 300
        assert cfg.max_nested_depth == 2

    def test_custom_config(self) -> None:
        cfg = DelegateConfig(
            role=AgentRole.ORCHESTRATOR,
            max_iterations=20,
            timeout_seconds=600,
            injected_context_files=["/path/to/context.md"],
        )
        assert cfg.role == AgentRole.ORCHESTRATOR
        assert cfg.max_iterations == 20
        assert cfg.timeout_seconds == 600
        assert "/path/to/context.md" in cfg.injected_context_files
