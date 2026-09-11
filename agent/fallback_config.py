"""Provider Fallback Chain 用户友好配置系统.

提供 YAML 配置文件支持、动态更新能力、每个模型的 fallback 配置，
并与现有的 ProviderRouter 无缝集成。

Configuration sources (in priority order):
1. YAML 配置文件 (``~/.Zeloo/fallback.yaml``)
2. 环境变量 ``zeloo_FALLBACK_PROVIDERS`` (向后兼容)

Example usage:
    >>> from agent.fallback_config import FallbackConfigManager
    >>> manager = FallbackConfigManager()
    >>> manager.load()
    >>> providers = manager.resolve_provider_for_call("gpt-4o", preferred="openai")
"""

from __future__ import annotations

import fnmatch
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path.home() / ".Zeloo" / "fallback.yaml"
CONFIG_VERSION = 1

_CHAINS: FallbackConfigManager | None = None


def _get_default_config_path() -> Path:
    """Return the default fallback config path."""
    config_path = os.environ.get("zeloo_FALLBACK_CONFIG_PATH")
    if config_path:
        return Path(config_path)
    return DEFAULT_CONFIG_PATH


def _ensure_config_dir(config_path: Path) -> None:
    """Ensure the config directory exists."""
    config_path.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class FallbackChain:
    """A fallback chain of providers.

    Attributes:
        name: Chain identifier (e.g., "default", "fast", "reliable").
        providers: Ordered list of provider names, highest priority first.
        enabled: Whether this chain is active.
        conditions: Optional conditions for chain selection
            (e.g., {"max_latency_ms": 2000, "requires_vision": true}).
    """

    name: str
    providers: list[str]
    enabled: bool = True
    conditions: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        result: dict[str, Any] = {
            "enabled": self.enabled,
            "providers": self.providers,
        }
        if self.conditions:
            result["conditions"] = self.conditions
        return result

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> FallbackChain:
        """Create a FallbackChain from a dictionary."""
        return cls(
            name=name,
            providers=data.get("providers", []),
            enabled=data.get("enabled", True),
            conditions=data.get("conditions", {}),
        )


@dataclass
class ModelFallbackConfig:
    """Configuration for a specific model's fallback behavior.

    Attributes:
        model_pattern: Model name pattern with optional wildcards (e.g., "gpt-4*").
        chain_name: Name of the FallbackChain to use.
        retry_count: Number of retries before moving to next provider.
        retry_delay: Delay in seconds between retries.
    """

    model_pattern: str
    chain_name: str
    retry_count: int = 2
    retry_delay: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        result: dict[str, Any] = {
            "chain": self.chain_name,
            "retry_count": self.retry_count,
            "retry_delay": self.retry_delay,
        }
        return result

    @classmethod
    def from_dict(cls, model_pattern: str, data: dict[str, Any]) -> ModelFallbackConfig:
        """Create a ModelFallbackConfig from a dictionary."""
        return cls(
            model_pattern=model_pattern,
            chain_name=data.get("chain", "default"),
            retry_count=data.get("retry_count", 2),
            retry_delay=data.get("retry_delay", 1.0),
        )


class FallbackConfigManager:
    """Manages fallback chain configurations with YAML persistence.

    Supports loading/saving configurations, chain CRUD operations,
    model-specific fallback configurations, and integration with
    ProviderRouter.

    Example:
        >>> manager = FallbackConfigManager()
        >>> manager.load()
        >>> chain = manager.get_chain("fast")
        >>> providers = manager.resolve_provider_for_call("gpt-4o")
    """

    def __init__(self, config_path: Path | None = None) -> None:
        """Initialize the FallbackConfigManager.

        Args:
            config_path: Optional custom config path. Defaults to ~/.Zeloo/fallback.yaml.
        """
        self._config_path = config_path or _get_default_config_path()
        self._chains: dict[str, FallbackChain] = {}
        self._model_configs: dict[str, ModelFallbackConfig] = {}
        self._default_chain: str = "default"
        self._version: int = CONFIG_VERSION
        self._loaded: bool = False

    @property
    def config_path(self) -> Path:
        """Return the config file path."""
        return self._config_path

    def load(self) -> None:
        """Load configuration from YAML file.

        Creates a default config file if none exists.
        """
        if not self._config_path.exists():
            logger.info("No fallback config found, creating default at %s", self._config_path)
            self._create_default_config()
            self.save()

        try:
            with open(self._config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            self._version = data.get("version", CONFIG_VERSION)
            self._default_chain = data.get("default_chain", "default")

            self._chains.clear()
            chains_data = data.get("chains", {})
            for name, chain_data in chains_data.items():
                self._chains[name] = FallbackChain.from_dict(name, chain_data)

            self._model_configs.clear()
            models_data = data.get("models", {})
            for pattern, model_data in models_data.items():
                self._model_configs[pattern] = ModelFallbackConfig.from_dict(pattern, model_data)

            self._loaded = True
            logger.info(
                "Loaded %d fallback chains and %d model configs from %s",
                len(self._chains),
                len(self._model_configs),
                self._config_path,
            )
        except Exception as e:
            logger.error("Failed to load fallback config: %s", e)
            self._create_default_config()
            self._loaded = True

    def save(self) -> None:
        """Save current configuration to YAML file."""
        _ensure_config_dir(self._config_path)

        chains_dict: dict[str, Any] = {}
        for name, chain in self._chains.items():
            chains_dict[name] = chain.to_dict()

        models_dict: dict[str, Any] = {}
        for pattern, config in self._model_configs.items():
            models_dict[pattern] = config.to_dict()

        data: dict[str, Any] = {
            "version": self._version,
            "default_chain": self._default_chain,
            "chains": chains_dict,
            "models": models_dict,
        }

        with open(self._config_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        logger.info("Saved fallback config to %s", self._config_path)

    def _create_default_config(self) -> None:
        """Create a default fallback configuration."""
        self._chains = {
            "default": FallbackChain(
                name="default",
                providers=["openai", "anthropic", "deepseek"],
                enabled=True,
                conditions={"max_latency_ms": 5000, "retry_count": 3},
            ),
            "fast": FallbackChain(
                name="fast",
                providers=["groq", "openai", "deepseek"],
                enabled=True,
                conditions={"max_latency_ms": 2000},
            ),
            "reliable": FallbackChain(
                name="reliable",
                providers=["anthropic", "openai", "azure"],
                enabled=True,
            ),
            "vision": FallbackChain(
                name="vision",
                providers=["anthropic", "openai"],
                enabled=True,
                conditions={"requires_vision": True},
            ),
            "cheap": FallbackChain(
                name="cheap",
                providers=["deepseek", "groq", "openai"],
                enabled=True,
            ),
            "local": FallbackChain(
                name="local",
                providers=["ollama", "local"],
                enabled=True,
                conditions={"offline_ok": True},
            ),
            "reasoning": FallbackChain(
                name="reasoning",
                providers=["deepseek", "anthropic", "openai"],
                enabled=True,
            ),
        }

        self._model_configs = {
            "gpt-4o*": ModelFallbackConfig(model_pattern="gpt-4o*", chain_name="default", retry_count=2),
            "gpt-4-turbo*": ModelFallbackConfig(
                model_pattern="gpt-4-turbo*", chain_name="fast", retry_count=3
            ),
            "claude-3*": ModelFallbackConfig(
                model_pattern="claude-3*", chain_name="vision", retry_count=2
            ),
            "claude-sonnet*": ModelFallbackConfig(
                model_pattern="claude-sonnet*", chain_name="fast", retry_count=2
            ),
            "deepseek-chat": ModelFallbackConfig(
                model_pattern="deepseek-chat", chain_name="cheap", retry_count=3
            ),
            "deepseek-reasoner": ModelFallbackConfig(
                model_pattern="deepseek-reasoner", chain_name="reasoning", retry_count=2
            ),
            "o1-*": ModelFallbackConfig(
                model_pattern="o1-*", chain_name="reasoning", retry_count=1, retry_delay=5.0
            ),
            "llama-3*": ModelFallbackConfig(
                model_pattern="llama-3*", chain_name="local", retry_count=2
            ),
        }

        self._default_chain = "default"

    def add_chain(self, chain: FallbackChain) -> None:
        """Add a new fallback chain.

        Args:
            chain: The FallbackChain to add.

        Raises:
            ValueError: If a chain with the same name already exists.
        """
        if chain.name in self._chains:
            raise ValueError(f"Chain '{chain.name}' already exists")
        self._chains[chain.name] = chain
        logger.info("Added fallback chain: %s", chain.name)

    def remove_chain(self, name: str) -> bool:
        """Remove a fallback chain by name.

        Args:
            name: Name of the chain to remove.

        Returns:
            True if removed, False if not found.
        """
        if name not in self._chains:
            return False
        del self._chains[name]
        logger.info("Removed fallback chain: %s", name)
        return True

    def get_chain(self, name: str) -> FallbackChain | None:
        """Get a fallback chain by name.

        Args:
            name: Name of the chain.

        Returns:
            The FallbackChain if found, None otherwise.
        """
        return self._chains.get(name)

    def list_chains(self) -> list[FallbackChain]:
        """List all configured fallback chains.

        Returns:
            List of all FallbackChain objects.
        """
        return list(self._chains.values())

    def update_chain(self, name: str, **kwargs: Any) -> FallbackChain:
        """Update a fallback chain's properties.

        Args:
            name: Name of the chain to update.
            **kwargs: Properties to update (providers, enabled, conditions).

        Returns:
            The updated FallbackChain.

        Raises:
            ValueError: If the chain is not found.
        """
        chain = self._chains.get(name)
        if chain is None:
            raise ValueError(f"Chain '{name}' not found")

        if "providers" in kwargs:
            chain.providers = kwargs["providers"]
        if "enabled" in kwargs:
            chain.enabled = kwargs["enabled"]
        if "conditions" in kwargs:
            chain.conditions = kwargs["conditions"]

        logger.info("Updated fallback chain: %s", name)
        return chain

    def add_model_config(self, config: ModelFallbackConfig) -> None:
        """Add a model-specific fallback configuration.

        Args:
            config: The ModelFallbackConfig to add.
        """
        self._model_configs[config.model_pattern] = config
        logger.info("Added model config: %s -> %s", config.model_pattern, config.chain_name)

    def get_model_config(self, model: str) -> ModelFallbackConfig | None:
        """Get model-specific config for a given model.

        Uses fnmatch pattern matching to find the best match.

        Args:
            model: The model name to look up.

        Returns:
            The matching ModelFallbackConfig if found, None otherwise.
        """
        for pattern, config in self._model_configs.items():
            if fnmatch.fnmatch(model, pattern):
                return config
        return None

    def list_model_configs(self) -> list[ModelFallbackConfig]:
        """List all model-specific configurations.

        Returns:
            List of all ModelFallbackConfig objects.
        """
        return list(self._model_configs.values())

    def remove_model_config(self, model_pattern: str) -> bool:
        """Remove a model-specific configuration.

        Args:
            model_pattern: The model pattern to remove.

        Returns:
            True if removed, False if not found.
        """
        if model_pattern not in self._model_configs:
            return False
        del self._model_configs[model_pattern]
        logger.info("Removed model config: %s", model_pattern)
        return True

    def resolve_chain(self, model: str) -> FallbackChain | None:
        """Resolve the appropriate chain for a model.

        First checks for model-specific config, then falls back to default chain.

        Args:
            model: The model name.

        Returns:
            The resolved FallbackChain, or None if no chain is available.
        """
        model_config = self.get_model_config(model)
        if model_config:
            chain = self._chains.get(model_config.chain_name)
            if chain and chain.enabled:
                return chain

        default_chain = self._chains.get(self._default_chain)
        if default_chain and default_chain.enabled:
            return default_chain

        for chain in self._chains.values():
            if chain.enabled:
                return chain

        return None

    def resolve_provider_for_call(
        self, model: str, preferred: str | None = None
    ) -> list[str]:
        """Resolve the ordered provider list for a model call.

        Args:
            model: The model name.
            preferred: Optional preferred provider to prioritize.

        Returns:
            Ordered list of provider names for fallback.
        """
        chain = self.resolve_chain(model)
        if not chain:
            return []

        providers = list(chain.providers)
        if preferred and preferred in providers:
            providers.remove(preferred)
            providers.insert(0, preferred)

        return providers

    def validate_chain(self, chain: FallbackChain) -> list[str]:
        """Validate a fallback chain configuration.

        Args:
            chain: The FallbackChain to validate.

        Returns:
            List of validation error messages (empty if valid).
        """
        errors: list[str] = []

        if not chain.name:
            errors.append("Chain name cannot be empty")

        if not chain.providers:
            errors.append(f"Chain '{chain.name}' has no providers")

        if len(chain.providers) != len(set(chain.providers)):
            errors.append(f"Chain '{chain.name}' has duplicate providers")

        if not all(isinstance(p, str) and p.strip() for p in chain.providers):
            errors.append(f"Chain '{chain.name}' contains invalid provider names")

        return errors

    def validate_all(self) -> dict[str, Any]:
        """Validate all configuration data.

        Returns:
            Dictionary with validation results:
            - valid: bool
            - errors: list of error messages
            - warnings: list of warning messages
            - chain_count: int
            - model_config_count: int
        """
        errors: list[str] = []
        warnings: list[str] = []

        if not self._chains:
            errors.append("No fallback chains configured")

        for name, chain in self._chains.items():
            chain_errors = self.validate_chain(chain)
            errors.extend(f"[chain:{name}] {e}" for e in chain_errors)

        if not self._model_configs:
            warnings.append("No model-specific configurations")

        for pattern in self._model_configs:
            chain_name = self._model_configs[pattern].chain_name
            if chain_name not in self._chains:
                errors.append(f"Model pattern '{pattern}' references non-existent chain '{chain_name}'")

        if self._default_chain not in self._chains:
            warnings.append(f"Default chain '{self._default_chain}' is not defined")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "chain_count": len(self._chains),
            "model_config_count": len(self._model_configs),
        }

    def get_env_fallback_string(self) -> str:
        """Generate the zeloo_FALLBACK_PROVIDERS environment variable string.

        Returns:
            Comma-separated list of provider names from the default chain.
        """
        chain = self._chains.get(self._default_chain)
        if not chain:
            return ""
        return ",".join(chain.providers[1:] if len(chain.providers) > 1 else [])


def _get_manager() -> FallbackConfigManager:
    """Get or create the global FallbackConfigManager instance."""
    global _CHAINS
    if _CHAINS is None:
        _CHAINS = FallbackConfigManager()
        _CHAINS.load()
    return _CHAINS


def get_fallback_chain(model: str) -> list[str]:
    """Get the fallback provider list for a model.

    Args:
        model: The model name.

    Returns:
        Ordered list of provider names for fallback.
    """
    manager = _get_manager()
    return manager.resolve_provider_for_call(model)


def list_fallback_chains() -> dict[str, Any]:
    """List all configured fallback chains.

    Returns:
        Dictionary mapping chain names to their configurations.
    """
    manager = _get_manager()
    chains = manager.list_chains()
    return {chain.name: chain.to_dict() for chain in chains}


def add_fallback_chain(name: str, providers: list[str], **kwargs: Any) -> dict[str, Any]:
    """Add a new fallback chain.

    Args:
        name: Chain name.
        providers: List of provider names.
        **kwargs: Additional chain properties (enabled, conditions).

    Returns:
        Result dictionary with success status and chain info.
    """
    manager = _get_manager()
    chain = FallbackChain(
        name=name,
        providers=providers,
        enabled=kwargs.get("enabled", True),
        conditions=kwargs.get("conditions", {}),
    )

    errors = manager.validate_chain(chain)
    if errors:
        manager.save()
        return {"success": False, "errors": errors}

    try:
        manager.add_chain(chain)
        manager.save()
        return {"success": True, "chain": chain.to_dict()}
    except ValueError as e:
        return {"success": False, "errors": [str(e)]}


def remove_fallback_chain(name: str) -> dict[str, Any]:
    """Remove a fallback chain.

    Args:
        name: Chain name to remove.

    Returns:
        Result dictionary with success status.
    """
    manager = _get_manager()
    removed = manager.remove_chain(name)
    if removed:
        manager.save()
        return {"success": True, "removed": name}
    return {"success": False, "errors": [f"Chain '{name}' not found"]}


def set_model_chain(
    model_pattern: str, chain_name: str, **kwargs: Any
) -> dict[str, Any]:
    """Set or update the fallback chain for a model pattern.

    Args:
        model_pattern: Model name pattern (supports * and ? wildcards).
        chain_name: Name of the chain to use.
        **kwargs: Additional config (retry_count, retry_delay).

    Returns:
        Result dictionary with success status.
    """
    manager = _get_manager()

    if chain_name not in manager._chains:
        return {"success": False, "errors": [f"Chain '{chain_name}' not found"]}

    config = ModelFallbackConfig(
        model_pattern=model_pattern,
        chain_name=chain_name,
        retry_count=kwargs.get("retry_count", 2),
        retry_delay=kwargs.get("retry_delay", 1.0),
    )

    manager.add_model_config(config)
    manager.save()
    return {"success": True, "config": config.to_dict()}


def validate_fallback_config() -> dict[str, Any]:
    """Validate the current fallback configuration.

    Returns:
        Validation result dictionary.
    """
    manager = _get_manager()
    return manager.validate_all()


def configure_router_from_file(router: Any) -> None:
    """Configure a ProviderRouter from the fallback config file.

    This function updates the router's fallback providers based on the
    configured default chain. It respects the router's primary provider
    and adds remaining providers as fallbacks.

    Args:
        router: A ProviderRouter instance to configure.
    """
    from agent.provider_router import ProviderConfig

    manager = _get_manager()
    chain = manager._chains.get(manager._default_chain)

    if not chain or not chain.enabled:
        logger.warning("No enabled default chain found for router configuration")
        return

    primary_name = router.primary.name if router.primary else None
    fallback_providers = [
        p for p in chain.providers if p != primary_name
    ]

    for i, name in enumerate(fallback_providers, start=1):
        model = chain.conditions.get(f"{name}_model", "gpt-4o-mini")
        router.add_provider(
            ProviderConfig(name=name, model=model, priority=i)
        )

    env_string = manager.get_env_fallback_string()
    if env_string:
        os.environ["zeloo_FALLBACK_PROVIDERS"] = env_string

    logger.info(
        "Configured router with %d fallback providers from chain '%s'",
        len(fallback_providers),
        manager._default_chain,
    )
