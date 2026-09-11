"""Delegate task to a sub-agent.

Implements the sub-agent delegation pattern: the parent agent spawns a
sub-agent with a specific goal, receiving results back. Sub-agents are
zero-knowledge isolated (no access to parent memory/context unless explicitly
injected).
"""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from tools.base import Tool, get_registry

logger = logging.getLogger(__name__)


class AgentRole(StrEnum):
    """Sub-agent role determines its capabilities."""

    LEAF = "leaf"
    ORCHESTRATOR = "orchestrator"


@dataclass
class DelegateConfig:
    """Configuration for a delegated sub-agent."""

    role: AgentRole = AgentRole.LEAF
    max_iterations: int = 10
    timeout_seconds: int = 300
    max_nested_depth: int = 2
    model: str = ""
    system_prompt: str = ""
    injected_context_files: list[str] = field(default_factory=list)
    memory_backend: str = "local"
    tags: list[str] = field(default_factory=list)


@dataclass
class DelegateResult:
    """Result returned by a delegated sub-agent."""

    task_id: str
    status: str
    result: str
    iterations_used: int = 0
    token_usage: dict[str, int] | None = None
    error: str | None = None
    duration_seconds: float = 0.0


_sub_agent_pool = ThreadPoolExecutor(max_workers=3)


def _run_sub_agent(
    task_id: str,
    goal: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Execute sub-agent in a thread. Runs in the thread pool."""
    import time

    start = time.monotonic()
    try:
        from agent.auxiliary_client import AuxiliaryAIAgent
    except ImportError:
        return {
            "task_id": task_id,
            "status": "error",
            "result": "",
            "iterations_used": 0,
            "error": "AIAgent not available in this environment",
            "duration_seconds": time.monotonic() - start,
        }

    agent_config = {
        "model": config.get("model", ""),
        "max_iterations": config.get("max_iterations", 10),
        "system_prompt": config.get("system_prompt", ""),
        "role": config.get("role", AgentRole.LEAF.value),
    }

    agent = AuxiliaryAIAgent(**agent_config)
    result = agent.run(goal)

    return {
        "task_id": task_id,
        "status": "completed",
        "result": result,
        "iterations_used": agent.iteration_count,
        "token_usage": getattr(agent, "last_usage", None),
        "error": None,
        "duration_seconds": time.monotonic() - start,
    }


class DelegateTool:
    """Tool for delegating tasks to sub-agents."""

    name = "delegate_task"
    description = (
        "Delegate a task to a specialized sub-agent. "
        "The sub-agent runs independently and returns its result. "
        "Supports role-based isolation (leaf/orchestrator) and timeout control."
    )
    dangerous = False

    def execute(
        self,
        goal: str,
        role: str = "leaf",
        max_iterations: int = 10,
        timeout_seconds: int = 300,
        model: str = "",
        system_prompt: str = "",
    ) -> str:
        """Execute a delegated sub-agent task.

        Args:
            goal: The task description for the sub-agent.
            role: Sub-agent role — "leaf" (no delegation) or "orchestrator" (can further delegate).
            max_iterations: Max tool-call iterations for the sub-agent.
            timeout_seconds: Hard timeout for sub-agent execution.
            model: Optional model override for the sub-agent.
            system_prompt: Optional system prompt override.

        Returns:
            JSON string with task_id, status, result, iterations_used, duration_seconds.
        """
        task_id = str(uuid.uuid4())

        if role not in (AgentRole.LEAF.value, AgentRole.ORCHESTRATOR.value):
            return f'{{"task_id": "{task_id}", "status": "error", "error": "Invalid role: {role}"}}'

        config: dict[str, Any] = {
            "role": role,
            "max_iterations": max_iterations,
            "model": model,
            "system_prompt": system_prompt,
        }

        future = _sub_agent_pool.submit(_run_sub_agent, task_id, goal, config)

        try:
            result = future.result(timeout=timeout_seconds)
        except FuturesTimeoutError:
            future.cancel()
            return f'{{"task_id": "{task_id}", "status": "timeout", "error": "Task exceeded {timeout_seconds}s timeout"}}'  # noqa: E501
        except Exception as exc:
            logger.error("Sub-agent %s failed: %s", task_id, exc)
            return f'{{"task_id": "{task_id}", "status": "error", "error": "{exc}"}}'

        import json
        return json.dumps(result, ensure_ascii=False)

    def clarify(self, question: str) -> str:
        """Ask the parent agent a clarifying question.

        Only available to orchestrator-role sub-agents.
        """
        return f"[clarify from sub-agent]: {question}"


def delegate_task(
    goal: str,
    role: str = "leaf",
    max_iterations: int = 10,
    timeout_seconds: int = 300,
    model: str = "",
) -> str:
    """Convenience wrapper for the DelegateTool."""
    return DelegateTool().execute(
        goal=goal,
        role=role,
        max_iterations=max_iterations,
        timeout_seconds=timeout_seconds,
        model=model,
    )


def clarify(question: str) -> str:
    """Sub-agent asks the parent agent a clarifying question."""
    return f"[clarify]: {question}"


_registry = get_registry()
for _func, _name, _desc in [
    (delegate_task, "delegate_task", "Delegate a task to a sub-agent with zero-knowledge isolation."),  # noqa: E501
    (clarify, "clarify", "Sub-agent asks a clarifying question."),
]:
    _registry.register(
        Tool(
            name=_name,
            description=_desc,
            parameters={},
            execute=_func,
            dangerous=True,
            toolset="delegation",
        )
    )
