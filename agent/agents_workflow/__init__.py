"""Multi-agent workflow orchestration.

Enables coordination of multiple AI agents working together on complex tasks.
Each sub-package contains its own AGENTS.md defining that agent's role.
"""

from agent.agents_workflow.coordinator import AgentCoordinator, Task, TaskResult, TaskStatus
from agent.agents_workflow.pipeline import Pipeline, PipelineStage

__all__ = [
    "AgentCoordinator",
    "Task",
    "TaskStatus",
    "TaskResult",
    "Pipeline",
    "PipelineStage",
]
