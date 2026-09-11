"""Configuration for delegated tasks: timeout, resource limits, allowed tools."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DelegateConfig:
    """Configuration for delegated task execution.

    Attributes:
        timeout: Maximum execution time in seconds.
        max_memory_mb: Maximum memory usage in megabytes.
        max_cpu_percent: Maximum CPU usage percentage (0-100).
        allowed_tools: List of tool names that can be used. None means all allowed.
        blocked_tools: List of tool names that are blocked. None means none blocked.
        environment: Environment variables to pass to the task.
        working_dir: Working directory for the task execution.
        user: Optional user to run as (Unix only).
    """

    timeout: int = 300
    max_memory_mb: int = 512
    max_cpu_percent: int = 80
    allowed_tools: list[str] | None = None
    blocked_tools: list[str] | None = None
    environment: dict[str, str] | None = None
    working_dir: Path | None = None
    user: str | None = None

    def is_tool_allowed(self, tool_name: str) -> bool:
        """Check if a tool is allowed to execute.

        Args:
            tool_name: Name of the tool to check.

        Returns:
            True if the tool is allowed, False otherwise.
        """
        if self.blocked_tools and tool_name in self.blocked_tools:
            return False
        if self.allowed_tools is not None and tool_name not in self.allowed_tools:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        """Convert config to a dictionary.

        Returns:
            Dictionary representation of the config.
        """
        return {
            "timeout": self.timeout,
            "max_memory_mb": self.max_memory_mb,
            "max_cpu_percent": self.max_cpu_percent,
            "allowed_tools": self.allowed_tools,
            "blocked_tools": self.blocked_tools,
            "environment": self.environment,
            "working_dir": str(self.working_dir) if self.working_dir else None,
            "user": self.user,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DelegateConfig:
        """Create config from a dictionary.

        Args:
            data: Dictionary with config values.

        Returns:
            DelegateConfig instance.
        """
        working_dir = data.get("working_dir")
        if working_dir and isinstance(working_dir, str):
            working_dir = Path(working_dir)

        return cls(
            timeout=data.get("timeout", 300),
            max_memory_mb=data.get("max_memory_mb", 512),
            max_cpu_percent=data.get("max_cpu_percent", 80),
            allowed_tools=data.get("allowed_tools"),
            blocked_tools=data.get("blocked_tools"),
            environment=data.get("environment"),
            working_dir=working_dir,
            user=data.get("user"),
        )


class DelegateConfigManager:
    """Manage delegation configurations for different task types."""

    DEFAULT_CONFIGS: dict[str, DelegateConfig] = {}

    def __init__(self):
        self._configs: dict[str, DelegateConfig] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register default configurations for common task types."""
        self._configs["code_generation"] = DelegateConfig(
            timeout=180,
            max_memory_mb=256,
            max_cpu_percent=50,
            blocked_tools=["shell_exec", "file_delete"],
        )
        self._configs["code_review"] = DelegateConfig(
            timeout=300,
            max_memory_mb=512,
            max_cpu_percent=80,
            allowed_tools=["read_file", "search_codebase"],
        )
        self._configs["data_processing"] = DelegateConfig(
            timeout=600,
            max_memory_mb=1024,
            max_cpu_percent=90,
            allowed_tools=["read_file", "write_file"],
        )
        self._configs["web_scraping"] = DelegateConfig(
            timeout=120,
            max_memory_mb=256,
            max_cpu_percent=40,
            blocked_tools=["shell_exec", "code_exec"],
        )
        self._configs["test_execution"] = DelegateConfig(
            timeout=600,
            max_memory_mb=512,
            max_cpu_percent=80,
            blocked_tools=["browser_navigate", "browser_screenshot"],
        )

    def get(self, task_type: str) -> DelegateConfig:
        """Get configuration for a task type.

        Args:
            task_type: The type of task to get config for.

        Returns:
            DelegateConfig for the task type, or a default config if not found.
        """
        return self._configs.get(task_type, DelegateConfig())

    def set(self, task_type: str, config: DelegateConfig) -> None:
        """Set configuration for a task type.

        Args:
            task_type: The type of task to configure.
            config: The configuration to apply.
        """
        self._configs[task_type] = config
        logger.info("Registered config for task type: %s", task_type)

    def list_types(self) -> list[str]:
        """List all registered task types.

        Returns:
            List of task type names.
        """
        return list(self._configs.keys())

    def merge(self, task_type: str, overrides: dict[str, Any]) -> DelegateConfig:
        """Get config with overrides applied.

        Args:
            task_type: Base task type.
            overrides: Configuration values to override.

        Returns:
            Merged DelegateConfig.
        """
        base = self.get(task_type)
        merged_dict = base.to_dict()
        merged_dict.update(overrides)
        return DelegateConfig.from_dict(merged_dict)

    def remove(self, task_type: str) -> bool:
        """Remove a task type configuration.

        Args:
            task_type: The task type to remove.

        Returns:
            True if removed, False if not found.
        """
        if task_type in self._configs:
            del self._configs[task_type]
            return True
        return False

    def reset(self) -> None:
        """Reset all configs to defaults."""
        self._configs.clear()
        self._register_defaults()
        logger.info("Reset all task configurations to defaults")
