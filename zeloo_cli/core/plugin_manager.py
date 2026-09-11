"""Plugin manager — dynamic plugin loading and lifecycle."""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class PluginState(StrEnum):
    """Plugin lifecycle states."""

    DISCOVERED = "discovered"
    LOADED = "loaded"
    INITIALIZED = "initialized"
    ACTIVATED = "activated"
    DEACTIVATED = "deactivated"
    ERROR = "error"


@dataclass
class PluginInfo:
    """Information about a loaded plugin."""

    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    source: str = ""  # Path or module name
    state: PluginState = PluginState.DISCOVERED
    loaded_at: float = 0.0
    instance: Any = None
    hooks: dict[str, Callable] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class PluginManager:
    """Manage dynamic plugin loading from file paths or modules.

    Supports:
    - Loading from file system paths
    - Loading from installed Python modules
    - Plugin lifecycle management
    - Hook registration and dispatch
    """

    def __init__(self) -> None:
        self._plugins: dict[str, PluginInfo] = {}
        self._lock = threading.Lock()
        self._global_hooks: dict[str, list[Callable]] = {}

    def discover_directory(
        self, directory: str, pattern: str = "plugin_*.py"
    ) -> list[str]:
        """Discover plugin files in a directory."""
        discovered: list[str] = []
        path = Path(directory)
        if not path.exists():
            return discovered
        for plugin_file in path.glob(pattern):
            discovered.append(str(plugin_file))
        return discovered

    def load_from_path(self, path: str, name: str = "") -> PluginInfo:
        """Load a plugin from a Python file path."""
        path_obj = Path(path)
        if not path_obj.exists():
            raise FileNotFoundError(f"Plugin file not found: {path}")

        plugin_name = name or path_obj.stem

        spec = importlib.util.spec_from_file_location(plugin_name, path_obj)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load plugin from {path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[plugin_name] = module
        spec.loader.exec_module(module)

        plugin_info = PluginInfo(
            name=plugin_name,
            version=getattr(module, "__version__", "1.0.0"),
            description=getattr(module, "__description__", ""),
            author=getattr(module, "__author__", ""),
            source=str(path_obj),
            state=PluginState.LOADED,
            loaded_at=time.time(),
            instance=module,
        )

        if hasattr(module, "register_hooks"):
            try:
                hooks = module.register_hooks()
                plugin_info.hooks = hooks or {}
            except Exception as e:
                logger.exception("Hook registration failed: %s", e)

        with self._lock:
            self._plugins[plugin_name] = plugin_info
            for hook_name, hook_func in plugin_info.hooks.items():
                self._global_hooks.setdefault(hook_name, []).append(hook_func)

        logger.info("Loaded plugin %s from %s", plugin_name, path)
        return plugin_info

    def load_from_module(self, module_name: str) -> PluginInfo:
        """Load a plugin from an installed Python module."""
        module = importlib.import_module(module_name)

        plugin_info = PluginInfo(
            name=module_name,
            version=getattr(module, "__version__", "1.0.0"),
            description=getattr(module, "__description__", ""),
            author=getattr(module, "__author__", ""),
            source=module_name,
            state=PluginState.LOADED,
            loaded_at=time.time(),
            instance=module,
        )

        if hasattr(module, "register_hooks"):
            try:
                hooks = module.register_hooks()
                plugin_info.hooks = hooks or {}
            except Exception as e:
                logger.exception("Hook registration failed: %s", e)

        with self._lock:
            self._plugins[module_name] = plugin_info
            for hook_name, hook_func in plugin_info.hooks.items():
                self._global_hooks.setdefault(hook_name, []).append(hook_func)

        logger.info("Loaded plugin %s", module_name)
        return plugin_info

    def initialize(self, name: str) -> bool:
        """Call plugin's initialize() function if present."""
        with self._lock:
            plugin = self._plugins.get(name)
            if plugin is None:
                return False
            if plugin.state == PluginState.ERROR:
                return False
        instance = plugin.instance
        try:
            if hasattr(instance, "initialize"):
                instance.initialize()
            plugin.state = PluginState.INITIALIZED
            return True
        except Exception as e:
            logger.exception("Plugin init failed: %s", e)
            plugin.state = PluginState.ERROR
            return False

    def activate(self, name: str) -> bool:
        """Activate a plugin (calls activate() if defined)."""
        with self._lock:
            plugin = self._plugins.get(name)
            if plugin is None:
                return False
        instance = plugin.instance
        try:
            if hasattr(instance, "activate"):
                instance.activate()
            plugin.state = PluginState.ACTIVATED
            return True
        except Exception as e:
            logger.exception("Plugin activation failed: %s", e)
            plugin.state = PluginState.ERROR
            return False

    def deactivate(self, name: str) -> bool:
        """Deactivate a plugin (calls deactivate() if defined)."""
        with self._lock:
            plugin = self._plugins.get(name)
            if plugin is None:
                return False
        instance = plugin.instance
        try:
            if hasattr(instance, "deactivate"):
                instance.deactivate()
            plugin.state = PluginState.DEACTIVATED
            return True
        except Exception as e:
            logger.exception("Plugin deactivation failed: %s", e)
            return False

    def trigger_hook(self, hook_name: str, *args: Any, **kwargs: Any) -> list[Any]:
        """Trigger all registered callbacks for a hook."""
        results: list[Any] = []
        for callback in self._global_hooks.get(hook_name, []):
            try:
                result = callback(*args, **kwargs)
                results.append(result)
            except Exception as e:
                logger.exception(
                    "Hook %s callback error: %s\n%s",
                    hook_name, e, traceback.format_exc(),
                )
        return results

    def list_plugins(self) -> list[PluginInfo]:
        with self._lock:
            return list(self._plugins.values())

    def get_plugin(self, name: str) -> PluginInfo | None:
        return self._plugins.get(name)

    def unload(self, name: str) -> bool:
        with self._lock:
            plugin = self._plugins.pop(name, None)
            if plugin is None:
                return False
            for hook_name in plugin.hooks:
                if hook_name in self._global_hooks:
                    try:
                        self._global_hooks[hook_name].remove(
                            plugin.hooks[hook_name]
                        )
                    except ValueError:
                        pass
            if name in sys.modules:
                del sys.modules[name]
        return True


__all__ = ["PluginManager", "PluginInfo", "PluginState"]