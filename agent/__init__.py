"""Zeloo Agent core modules."""
from __future__ import annotations

from agent.agent_analytics import AgentAnalytics, AgentMetrics
from agent.agent_init import AgentConfig, AgentInit, quick_start
from agent.checkpoint import Checkpoint, CheckpointManager
from agent.execution_sandbox import ExecutionSandbox, SandboxConfig, SandboxPolicy, SandboxResult
from agent.memory_consolidator import MemoryConsolidator, MemoryEntry, MemoryType
from agent.memory_manager import MemoryManager
from agent.prompt_optimizer import (
    MetaPromptEngine,
    OptimizationReport,
    PromptCompressor,
    PromptOptimizer,
    PromptOptimizerV2,
    PromptSafetyValidator,
    PromptTemplate,
    PromptTemplateLibrary,
)
from agent.provider_router import ProviderConfig, ProviderRouter, SmartModelRouter
from agent.replay import ReplayMode, ReplayResult, TrajectoryReplay
from agent.system_prompt import build_system_prompt, invalidate_system_prompt
from agent.task_planner import Plan, PlanTask, TaskPlanner, TaskStatus
from agent.tool_recommender import ToolRecommendation, ToolRecommender, ToolScore
from agent.transports.base import (
    AuthenticationError,
    ModelUnavailableError,
    RateLimitError,
    Response,
    TransportAdapter,
)
from agent.turn_finalizer import TurnFinalizer, TurnResult
from plugins.hooks import HookRegistry

_lazy_imports = {
    "AIAgent": "run_agent",
    "ConversationLoop": "agent.conversation_loop",
}
def __getattr__(name: str) -> object:
    if name in _lazy_imports:
        import importlib
        module_path = _lazy_imports[name]
        module = importlib.import_module(module_path)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
__all__ = [
    "AIAgent",
    "AgentConfig",
    "AgentInit",
    "ConversationLoop",
    "HookRegistry",
    "MemoryManager",
    "ProviderConfig",
    "ProviderRouter",
    "PromptOptimizer",
    "PromptOptimizerV2",
    "PromptCompressor",
    "PromptTemplate",
    "PromptTemplateLibrary",
    "PromptSafetyValidator",
    "MetaPromptEngine",
    "OptimizationReport",
    "SmartModelRouter",
    "TurnFinalizer",
    "TurnResult",
    "AuthenticationError",
    "ModelUnavailableError",
    "RateLimitError",
    "Response",
    "TransportAdapter",
    "build_system_prompt",
    "invalidate_system_prompt",
    "quick_start",
    "Checkpoint",
    "CheckpointManager",
    "TrajectoryReplay",
    "ReplayMode",
    "ReplayResult",
    "ExecutionSandbox",
    "SandboxConfig",
    "SandboxResult",
    "SandboxPolicy",
    "TaskPlanner",
    "Plan",
    "PlanTask",
    "TaskStatus",
    "MemoryConsolidator",
    "MemoryEntry",
    "MemoryType",
    "ToolRecommender",
    "ToolRecommendation",
    "ToolScore",
    "AgentAnalytics",
    "AgentMetrics",
]
