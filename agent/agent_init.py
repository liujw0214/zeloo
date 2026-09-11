"""Agent initialization — bootstrap logic for AIAgent and ConversationLoop."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from run_agent import AIAgent

from agent.agent_runtime_helpers import resolve_model_config
from agent.credential_pool import CredentialPool
from agent.memory_manager import MemoryManager
from agent.prompt_optimizer import PromptOptimizer
from agent.provider_router import ProviderConfig, ProviderRouter
from agent.system_prompt import SystemPromptBuilder
from plugins.hooks import HookRegistry
from tools.base import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    """Complete agent configuration dataclass."""

    provider: str = "openai"
    model: str = "gpt-4o"
    base_url: str | None = None
    max_iterations: int = 90
    max_workers: int = 8
    temperature: float = 0.7
    timeout: float = 120.0
    memory_backend: str = "localfile"
    toolsets: list[str] = field(default_factory=lambda: ["cli"])
    prompt_optimizer_enabled: bool = True
    prompt_optimizer_cot: bool = True
    prompt_optimizer_few_shot: bool = True
    prompt_optimizer_tuning: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


class AgentInit:
    """Agent initialization orchestrator.

    Handles the full bootstrap sequence:
    1. Config resolution (env / file / defaults)
    2. Credential setup
    3. Tool registration
    4. Memory initialization
    5. Provider router setup
    6. System prompt assembly
    7. Hook manager initialization
    """

    def __init__(self, config: AgentConfig | None = None):
        self.config = config or AgentConfig()
        self.credential_pool: CredentialPool | None = None
        self.provider_router: ProviderRouter | None = None
        self.memory_manager: MemoryManager | None = None
        self.system_prompt_builder: SystemPromptBuilder | None = None
        self.hook_manager: HookRegistry | None = None
        self._tools: list[Any] = []

    def resolve_config(
        self,
        provider: str | None = None,
        model: str | None = None,
        config_file: Path | None = None,
    ) -> AgentConfig:
        """Resolve agent configuration from all sources.

        Priority: constructor args > config_file > environment > defaults.

        Args:
            provider: Explicit provider name.
            model: Explicit model name.
            config_file: Optional YAML/JSON config file path.

        Returns:
            Resolved AgentConfig.
        """
        cfg = AgentConfig(**self.config.__dict__)

        if config_file and config_file.exists():
            cfg = self._merge_file_config(cfg, config_file)

        cfg = self._merge_env_config(cfg)

        if provider:
            cfg.provider = provider
        if model:
            cfg.model = model

        return cfg

    def setup_credentials(self, config: AgentConfig) -> CredentialPool:
        """Set up the credential pool from environment.

        Args:
            config: Resolved agent config.

        Returns:
            Initialized CredentialPool.
        """
        pool = CredentialPool()
        self.credential_pool = pool
        return pool

    def load_tools(self, toolset_list: list[str] | None = None) -> list[Any]:
        """Load and register tools from the tool registry.

        Args:
            toolset_list: List of toolset names to load. Defaults to config.toolsets.

        Returns:
            List of instantiated tool objects.
        """
        if not toolset_list:
            toolset_list = self.config.toolsets

        registry = ToolRegistry()
        all_tools = list(registry.get_all().values())

        if toolset_list:
            self._tools = [t for t in all_tools if t.toolset in toolset_list]
        else:
            self._tools = all_tools

        logger.info("Loaded %d tools across %d toolsets", len(self._tools), len(toolset_list))
        return self._tools

    def init_memory(self, config: AgentConfig) -> MemoryManager:
        """Initialize the memory manager with the configured backend.

        Args:
            config: Agent configuration.

        Returns:
            Initialized MemoryManager.
        """
        self.memory_manager = MemoryManager()
        return self.memory_manager

    def init_provider_router(self, config: AgentConfig) -> ProviderRouter:
        """Initialize the LLM provider router.

        Args:
            config: Agent configuration.

        Returns:
            Configured ProviderRouter.
        """
        self.provider_router = ProviderRouter(
            [
                ProviderConfig(
                    name=config.provider,
                    model=config.model,
                    base_url=config.base_url,
                    priority=0,
                )
            ]
        )
        return self.provider_router

    def build_system_prompt(
        self,
        config: AgentConfig,
        workspace_path: Path | None = None,
    ) -> SystemPromptBuilder:
        """Build the layered system prompt.

        Args:
            config: Agent configuration.
            workspace_path: Optional workspace directory for context injection.

        Returns:
            Configured SystemPromptBuilder.
        """
        self.system_prompt_builder = SystemPromptBuilder(
            tools=self._tools,
            workspace_path=workspace_path,
        )
        return self.system_prompt_builder

    def init_hooks(self) -> HookRegistry:
        """Initialize the plugin hook registry.

        Returns:
            Configured HookRegistry.
        """
        self.hook_manager = HookRegistry()
        return self.hook_manager

    def init_prompt_optimizer(
        self,
        enable_cot: bool = True,
        enable_few_shot: bool = True,
        enable_tuning: bool = True,
    ) -> PromptOptimizer:
        """Initialize the prompt optimizer.

        Args:
            enable_cot: Enable Chain-of-Thought guidance injection.
            enable_few_shot: Enable few-shot example selection.
            enable_tuning: Enable auto-tuning of generation parameters.

        Returns:
            Initialized PromptOptimizer.
        """
        optimizer = PromptOptimizer(
            enable_cot=enable_cot,
            enable_few_shot=enable_few_shot,
            enable_tuning=enable_tuning,
        )
        logger.info(
            "PromptOptimizer initialized (CoT=%s, few_shot=%s, tuning=%s)",
            enable_cot,
            enable_few_shot,
            enable_tuning,
        )
        return optimizer

    def create_agent(
        self,
        provider: str | None = None,
        model: str | None = None,
        config_file: Path | None = None,
        workspace_path: Path | None = None,
    ) -> dict[str, Any]:
        """Full agent creation pipeline.

        Args:
            provider: Explicit provider name.
            model: Explicit model name.
            config_file: Optional config file path.
            workspace_path: Optional workspace directory.

        Returns:
            Dict containing all initialized components:
            {
                "config": AgentConfig,
                "provider_router": ProviderRouter,
                "memory_manager": MemoryManager,
                "system_prompt_builder": SystemPromptBuilder,
                "hook_manager": HookRegistry,
                "prompt_optimizer": PromptOptimizer,
                "tools": list[Any],
                "model_config": ModelConfig,
            }
        """
        config = self.resolve_config(provider, model, config_file)

        self.setup_credentials(config)
        self.load_tools(config.toolsets)
        self.init_memory(config)
        self.init_provider_router(config)
        self.build_system_prompt(config, workspace_path)
        self.init_hooks()

        if config.prompt_optimizer_enabled:
            self._prompt_optimizer = self.init_prompt_optimizer(
                enable_cot=config.prompt_optimizer_cot,
                enable_few_shot=config.prompt_optimizer_few_shot,
                enable_tuning=config.prompt_optimizer_tuning,
            )
        else:
            self._prompt_optimizer = None

        model_cfg = resolve_model_config(self)

        logger.info(
            "Agent initialized: provider=%s model=%s tools=%d prompt_optimizer=%s",
            config.provider,
            config.model,
            len(self._tools),
            config.prompt_optimizer_enabled,
        )

        return {
            "config": config,
            "provider_router": self.provider_router,
            "memory_manager": self.memory_manager,
            "system_prompt_builder": self.system_prompt_builder,
            "hook_manager": self.hook_manager,
            "prompt_optimizer": self._prompt_optimizer,
            "tools": self._tools,
            "model_config": model_cfg,
        }

    def _merge_file_config(
        self, cfg: AgentConfig, path: Path
    ) -> AgentConfig:
        """Merge configuration from a YAML/JSON file."""
        import json

        try:
            import yaml
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except ImportError:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)

        if not data:
            return cfg

        merged = cfg.__dict__.copy()
        merged.update({k: v for k, v in data.items() if v is not None})
        return AgentConfig(**merged)

    def _merge_env_config(self, cfg: AgentConfig) -> AgentConfig:
        """Merge configuration from environment variables."""
        import os

        if os.environ.get("zeloo_PROVIDER"):
            cfg.provider = os.environ["zeloo_PROVIDER"]
        if os.environ.get("zeloo_MODEL"):
            cfg.model = os.environ["zeloo_MODEL"]
        if os.environ.get("zeloo_BASE_URL"):
            cfg.base_url = os.environ["zeloo_BASE_URL"]
        if os.environ.get("zeloo_MAX_ITERATIONS"):
            cfg.max_iterations = int(os.environ["zeloo_MAX_ITERATIONS"])

        return cfg


def quick_start(
    provider: str = "openai",
    model: str = "gpt-4o",
) -> AIAgent:  # type: ignore[valid-type]
    """One-liner agent creation for simple use cases.

    Args:
        provider: LLM provider name.
        model: Model name.

    Returns:
        Fully initialized AIAgent instance ready for conversation.
    """
    from run_agent import AIAgent

    init = AgentInit(AgentConfig(provider=provider, model=model))
    result = init.create_agent()
    return AIAgent.from_agent_init(result)
