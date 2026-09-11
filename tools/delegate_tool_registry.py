"""Registry of all available delegated task types and their schemas."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class TaskType:
    """Definition of a task type with schema and handler."""

    name: str
    schema: dict[str, Any]
    handler: Callable[..., Any]
    description: str = ""
    category: str = "general"
    tags: list[str] = field(default_factory=list)

    def validate_params(self, params: dict[str, Any]) -> tuple[bool, str]:
        """Validate parameters against schema.

        Args:
            params: Parameters to validate.

        Returns:
            Tuple of (is_valid, error_message).
        """
        required_fields = self.schema.get("required", [])
        for field_name in required_fields:
            if field_name not in params:
                return False, f"Missing required field: {field_name}"

        properties = self.schema.get("properties", {})
        for field_name, value in params.items():
            if field_name not in properties:
                return False, f"Unknown field: {field_name}"

            expected_type = properties[field_name].get("type")
            if expected_type:
                if not self._check_type(value, expected_type):
                    return False, f"Invalid type for {field_name}: expected {expected_type}"

        return True, ""

    @staticmethod
    def _check_type(value: Any, expected_type: str) -> bool:
        """Check if value matches expected JSON schema type.

        Args:
            value: Value to check.
            expected_type: Expected JSON schema type.

        Returns:
            True if type matches.
        """
        type_map = {
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
            "array": list,
            "object": dict,
            "null": type(None),
        }
        expected_python_type = type_map.get(expected_type)
        if expected_python_type is None:
            return True
        return isinstance(value, expected_python_type)


class TaskRegistry:
    """Registry of delegated task types."""

    def __init__(self):
        self.task_types: dict[str, TaskType] = {}
        self._register_builtin_types()

    def _register_builtin_types(self) -> None:
        """Register built-in task types."""
        self.register(
            "shell_command",
            schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds"},
                    "env": {"type": "object", "description": "Environment variables"},
                },
                "required": ["command"],
            },
            handler=self._default_handler,
            description="Execute a shell command in an isolated subprocess",
            category="execution",
            tags=["shell", "exec"],
        )

        self.register(
            "code_generation",
            schema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Generation prompt"},
                    "language": {"type": "string", "description": "Target language"},
                    "framework": {"type": "string", "description": "Target framework"},
                },
                "required": ["prompt"],
            },
            handler=self._default_handler,
            description="Generate code based on a prompt",
            category="generation",
            tags=["code", "ai"],
        )

        self.register(
            "file_operation",
            schema={
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["read", "write", "delete", "copy", "move"],
                    },
                    "path": {"type": "string", "description": "File path"},
                    "content": {"type": "string", "description": "Content for write operations"},
                },
                "required": ["operation", "path"],
            },
            handler=self._default_handler,
            description="Perform file system operations",
            category="filesystem",
            tags=["file", "io"],
        )

        self.register(
            "web_request",
            schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Target URL"},
                    "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE"]},
                    "headers": {"type": "object", "description": "HTTP headers"},
                    "body": {"type": "string", "description": "Request body"},
                },
                "required": ["url"],
            },
            handler=self._default_handler,
            description="Make HTTP requests",
            category="network",
            tags=["http", "web"],
        )

    @staticmethod
    def _default_handler(params: dict[str, Any]) -> dict[str, Any]:
        """Default handler for unregistered operations.

        Args:
            params: Handler parameters.

        Returns:
            Result dictionary.
        """
        return {"status": "ok", "params": params}

    def register(
        self,
        task_type: str,
        schema: dict[str, Any],
        handler: Callable[..., Any],
        description: str = "",
        category: str = "general",
        tags: list[str] | None = None,
    ) -> None:
        """Register a new task type.

        Args:
            task_type: Unique name for the task type.
            schema: JSON schema for task parameters.
            handler: Function to handle task execution.
            description: Human-readable description.
            category: Category for grouping tasks.
            tags: Optional tags for filtering.
        """
        task_def = TaskType(
            name=task_type,
            schema=schema,
            handler=handler,
            description=description,
            category=category,
            tags=tags or [],
        )
        self.task_types[task_type] = task_def
        logger.info("Registered task type: %s", task_type)

    def unregister(self, task_type: str) -> bool:
        """Unregister a task type.

        Args:
            task_type: The task type to remove.

        Returns:
            True if removed, False if not found.
        """
        if task_type in self.task_types:
            del self.task_types[task_type]
            logger.info("Unregistered task type: %s", task_type)
            return True
        return False

    def get_schema(self, task_type: str) -> dict[str, Any] | None:
        """Get the schema for a task type.

        Args:
            task_type: The task type to look up.

        Returns:
            Schema dictionary or None if not found.
        """
        task_def = self.task_types.get(task_type)
        return task_def.schema if task_def else None

    def get_handler(self, task_type: str) -> Callable[..., Any] | None:
        """Get the handler for a task type.

        Args:
            task_type: The task type to look up.

        Returns:
            Handler function or None if not found.
        """
        task_def = self.task_types.get(task_type)
        return task_def.handler if task_def else None

    def get_task_type(self, task_type: str) -> TaskType | None:
        """Get the full TaskType definition.

        Args:
            task_type: The task type to look up.

        Returns:
            TaskType object or None if not found.
        """
        return self.task_types.get(task_type)

    def list_types(self, category: str | None = None, tags: list[str] | None = None) -> list[str]:
        """List registered task types.

        Args:
            category: Filter by category.
            tags: Filter by required tags (all must match).

        Returns:
            List of task type names.
        """
        result = []
        for name, task_def in self.task_types.items():
            if category and task_def.category != category:
                continue
            if tags:
                if not all(tag in task_def.tags for tag in tags):
                    continue
            result.append(name)
        return result

    def list_categories(self) -> list[str]:
        """List all unique categories.

        Returns:
            List of category names.
        """
        return list(set(t.category for t in self.task_types.values()))

    def validate(self, task_type: str, params: dict[str, Any]) -> tuple[bool, str]:
        """Validate parameters against a task type schema.

        Args:
            task_type: The task type to validate against.
            params: Parameters to validate.

        Returns:
            Tuple of (is_valid, error_message).
        """
        task_def = self.task_types.get(task_type)
        if not task_def:
            return False, f"Unknown task type: {task_type}"
        return task_def.validate_params(params)

    def get_all_schemas(self) -> dict[str, dict[str, Any]]:
        """Get schemas for all registered task types.

        Returns:
            Dictionary mapping task type names to schemas.
        """
        return {name: tt.schema for name, tt in self.task_types.items()}
