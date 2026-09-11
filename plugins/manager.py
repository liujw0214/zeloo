"""Plugin system for Zeloo — discover, load, and register extensions.

Plugins are Python modules/packages that expose a ``register`` callable.
At startup, :class:`PluginManager` scans configured directories, imports
each plugin module, and calls its ``register`` entry point with access
to the tool registry, skills manager, and hook registry.

A plugin module looks like::

    from tools.base import tool
    from plugins.hooks import HookType

    @tool(name="my_plugin_tool", description="...", toolset="plugins")
    def my_plugin_tool(arg: str) -> str:
        return f"hello {arg}"

    def register(registry, skills_manager, hooks):
        # Tools are auto-registered via the @tool decorator on import.
        # Optionally register skills and lifecycle hooks here.
        hooks.register(HookType.PRE_TOOL_CALL, my_pre_hook, "my_plugin")
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from plugins.hooks import HookRegistry, get_hook_registry

logger = logging.getLogger(__name__)


@dataclass
class PluginInfo:
    """Metadata about a loaded plugin."""

    name: str
    path: str
    enabled: bool = True
    error: str | None = None
    tools_added: list[str] = field(default_factory=list)
    hooks_registered: int = 0


class PluginManager:
    """Discovers and loads plugins from configured directories."""

    def __init__(
        self,
        plugin_dirs: list[str | Path] | None = None,
        hooks: HookRegistry | None = None,
    ) -> None:
        self._plugin_dirs: list[Path] = [Path(p) for p in (plugin_dirs or [])]
        self._plugins: dict[str, PluginInfo] = {}
        self._hooks: HookRegistry = hooks or get_hook_registry()

    def add_dir(self, path: str | Path) -> None:
        """Add a directory to scan for plugins."""
        p = Path(path)
        if p.is_dir():
            self._plugin_dirs.append(p)
        else:
            logger.warning("Plugin directory does not exist: %s", p)

    def discover(self) -> list[Path]:
        """Return all candidate plugin module paths from configured dirs."""
        skip_names = {"__init__", "manager", "base"}
        candidates: list[Path] = []
        for d in self._plugin_dirs:
            if not d.is_dir():
                continue
            for entry in sorted(d.iterdir()):
                if entry.name.startswith("_") or entry.name.startswith("."):
                    continue
                if entry.suffix == ".py" and entry.stem not in skip_names:
                    candidates.append(entry)
                elif (
                    entry.is_dir()
                    and entry.name not in skip_names
                    and (entry / "__init__.py").is_file()
                ):
                    candidates.append(entry)
        return candidates

    def load_all(self) -> dict[str, PluginInfo]:
        """Discover and load all plugins. Returns the plugin info map."""
        for candidate in self.discover():
            name = candidate.stem if candidate.is_file() else candidate.name
            if name in self._plugins:
                continue
            self._load_one(name, candidate)
        return dict(self._plugins)

    def _load_one(self, name: str, path: Path) -> PluginInfo:
        """Load a single plugin module."""
        info = PluginInfo(name=name, path=str(path))
        before_tools = self._get_tool_names()
        before_hooks = self._hooks.hook_count

        try:
            spec = importlib.util.spec_from_file_location(f"zeloo_plugin_{name}", path)
            if spec is None or spec.loader is None:
                raise ImportError(f"Cannot create module spec for {path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)

            # Call the optional register() entry point
            # Signature: register(registry, skills_manager, hooks)
            # Backward compatible with 2-arg register(registry, skills_manager).
            register_fn: Callable[..., Any] | None = getattr(module, "register", None)
            if callable(register_fn):
                import inspect

                from agent.skill_utils import SkillRegistrar
                from tools.base import get_registry

                sig = inspect.signature(register_fn)
                if len(sig.parameters) >= 3:
                    register_fn(get_registry(), SkillRegistrar(), self._hooks)
                else:
                    register_fn(get_registry(), SkillRegistrar())

            after_tools = self._get_tool_names()
            info.tools_added = sorted(after_tools - before_tools)
            info.hooks_registered = self._hooks.hook_count - before_hooks
            # Demote plugin load messages to DEBUG so the default INFO
            # log stays clean; the summary is still visible with -v.
            logger.debug(
                "Plugin '%s' loaded (added %d tool(s), %d hook(s))",
                name,
                len(info.tools_added),
                info.hooks_registered,
            )
        except Exception as e:
            info.enabled = False
            info.error = str(e)
            logger.exception("Failed to load plugin '%s'", name)

        self._plugins[name] = info
        return info

    @property
    def hooks(self) -> HookRegistry:
        """Return the hook registry used by this manager."""
        return self._hooks

    @staticmethod
    def _get_tool_names() -> set[str]:
        from tools.base import get_registry

        return get_registry().get_names()

    def get_plugins(self) -> list[PluginInfo]:
        """Return info for all discovered plugins."""
        return list(self._plugins.values())
