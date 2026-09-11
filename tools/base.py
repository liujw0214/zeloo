"""Tool base classes and registry — auto-discovery via @tool decorator."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


class BaseTool:
    """Base class for class-based tools.

    Subclasses must define ``name``, ``description``, and ``execute``.
    The ``execute`` method is registered via the ``@tool`` decorator.

    Example::

        class MyTool(BaseTool):
            name = "my_tool"
            description = "Does something useful"

            @tool(toolset="my_tools")
            def execute(self, arg1: str) -> str:
                return f"Hello, {arg1}"
    """

    name: str = ""
    description: str = ""
    dangerous: bool = False
    requires_confirmation: bool = False

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError(f"{self.__class__.__name__}.execute() not implemented")


@dataclass
class Tool:
    """A registered tool with its schema and executor."""

    name: str
    description: str
    parameters: dict[str, Any]
    execute: Callable[..., Any]
    dangerous: bool = False
    confirmation_required: bool = False
    toolset: str = ""

    def to_openai_schema(self) -> dict[str, Any]:
        """Convert to OpenAI function-calling schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Global registry of available tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool.

        If a tool with the same name already exists, the existing entry is
        overwritten silently — duplicate registrations are common when a
        module is imported via multiple paths (e.g. plugin auto-discovery
        alongside the built-in discovery loop). The existing tool's
        executor is replaced when the new instance differs (different
        qualname or file), so legitimate re-registrations are logged at
        DEBUG and accidental same-name collisions still surface as a
        WARNING.
        """
        existing = self._tools.get(tool.name)
        if existing is not None:
            existing_qname = getattr(existing.execute, "__qualname__", "")
            new_qname = getattr(tool.execute, "__qualname__", "")
            if existing_qname and existing_qname == new_qname:
                # Same function re-registering (e.g. via re-import); no-op.
                logger.debug("Tool %s re-registered from same source", tool.name)
                return
            logger.warning("Tool %s already registered, overwriting", tool.name)
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_all(self) -> dict[str, Tool]:
        """Get all registered tools."""
        return dict(self._tools)

    def get_names(self) -> set[str]:
        """Get all registered tool names."""
        return set(self._tools.keys())

    def get_schemas(self) -> list[dict[str, Any]]:
        """Get OpenAI schemas for all tools."""
        return [t.to_openai_schema() for t in self._tools.values()]


# Global registry instance
_registry = ToolRegistry()


def get_registry() -> ToolRegistry:
    """Return the global tool registry."""
    return _registry


def tool(
    name: str | None = None,
    description: str = "",
    dangerous: bool = False,
    confirmation_required: bool = False,
    toolset: str = "",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator to register a function as a tool.

    The function's signature and docstring are used to generate the JSON Schema.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        # When the decorator is applied to a BaseTool subclass' ``execute``
        # method, prefer the class-level ``name`` attribute so multiple
        # subclass tools don't all register as "execute" and silently
        # overwrite each other.
        resolved_name = name or func.__name__
        if resolved_name in {"execute", ""}:
            qualname = getattr(func, "__qualname__", "")
            if "." in qualname:
                cls_qualname = qualname.rsplit(".", 1)[0]
                try:
                    import sys

                    mod_name = getattr(func, "__module__", "")
                    mod = sys.modules.get(mod_name)
                    if mod is not None:
                        for v in vars(mod).values():
                            if (
                                isinstance(v, type)
                                and getattr(v, "__qualname__", None) == cls_qualname
                            ):
                                cls_name = getattr(v, "name", "") or ""
                                if cls_name:
                                    resolved_name = cls_name
                                break
                except Exception:  # noqa: BLE001
                    pass
        tool_name = resolved_name
        sig = inspect.signature(func)

        # Build JSON Schema from signature
        properties: dict[str, Any] = {}
        required: list[str] = []

        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue
            prop: dict[str, Any] = {}

            # Type mapping
            annotation = param.annotation
            if annotation is str or annotation == "str":
                prop["type"] = "string"
            elif annotation is int or annotation == "int":
                prop["type"] = "integer"
            elif annotation is bool or annotation == "bool":
                prop["type"] = "boolean"
            elif annotation is float or annotation == "float":
                prop["type"] = "number"
            else:
                prop["type"] = "string"

            # Default value
            if param.default is inspect.Parameter.empty:
                required.append(param_name)
            else:
                prop["default"] = param.default

            properties[param_name] = prop

        parameters = {
            "type": "object",
            "properties": properties,
            "required": required,
        }

        # Use docstring as description if not provided
        desc = description or (func.__doc__ or "").strip().split("\n")[0]

        tool_obj = Tool(
            name=tool_name,
            description=desc,
            parameters=parameters,
            execute=func,
            dangerous=dangerous,
            confirmation_required=confirmation_required,
            toolset=toolset,
        )
        _registry.register(tool_obj)

        return func

    return decorator


def discover_builtin_tools() -> None:
    """Import all built-in tool modules to trigger registration."""
    import importlib
    import pkgutil

    import tools

    for module_info in pkgutil.iter_modules(tools.__path__):
        if module_info.name.startswith("_"):
            continue
        if module_info.name == "base":
            continue
        try:
            importlib.import_module(f"tools.{module_info.name}")
        except Exception:
            logger.exception("Failed to import tool module %s", module_info.name)
