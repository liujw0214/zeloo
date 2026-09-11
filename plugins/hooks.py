"""Plugin lifecycle hooks — extension points for the agent runtime.

Plugins can register callbacks that fire at key points in the agent
lifecycle: before/after tool calls, before/after LLM calls, and at
session start/end. Hooks allow plugins to observe, modify, or block
operations without changing core code.

Hook types and signatures::

    pre_tool_call(tool_name: str, args: dict) -> dict | None
        Called before a tool executes. Return a modified args dict to
        override, or None to proceed with original args. Raise to block.

    post_tool_call(tool_name: str, args: dict, result: Any) -> Any
        Called after a tool executes. Return a modified result, or None
        to keep the original.

    pre_llm_call(messages: list, tools: list) -> tuple[list, list] | None
        Called before each LLM API call. Return (messages, tools) to
        override, or None to proceed.

    post_llm_call(response: dict) -> dict | None
        Called after each LLM API call. Return a modified response dict,
        or None to keep the original.

    on_session_start(session_id: str) -> None
        Called when a new session begins.

    on_session_end(session_id: str) -> None
        Called when a session ends.

    transform_llm_output(content: str) -> str | None
        Called on the final assistant text output. Return modified text
        or None to keep original.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class HookType(StrEnum):
    """Enumeration of supported plugin hook types."""

    PRE_TOOL_CALL = "pre_tool_call"
    POST_TOOL_CALL = "post_tool_call"
    PRE_LLM_CALL = "pre_llm_call"
    POST_LLM_CALL = "post_llm_call"
    ON_SESSION_START = "on_session_start"
    ON_SESSION_END = "on_session_end"
    TRANSFORM_LLM_OUTPUT = "transform_llm_output"


@dataclass
class HookRegistry:
    """Central registry for plugin lifecycle hooks.

    Plugins call :meth:`register` to attach callbacks. The agent runtime
    calls :meth:`fire` at the corresponding lifecycle points.
    """

    _hooks: dict[HookType, list[tuple[str, Callable[..., Any]]]] = field(
        default_factory=dict
    )

    def register(
        self,
        hook_type: HookType,
        callback: Callable[..., Any],
        plugin_name: str = "anonymous",
    ) -> None:
        """Register a callback for a hook type.

        Args:
            hook_type: The lifecycle point to hook into.
            callback: A function matching the hook's signature.
            plugin_name: Name of the registering plugin (for logging).
        """
        self._hooks.setdefault(hook_type, []).append((plugin_name, callback))
        logger.debug(
            "Hook registered: %s by plugin '%s'", hook_type.value, plugin_name
        )

    def unregister(self, hook_type: HookType, plugin_name: str) -> int:
        """Remove all callbacks registered by *plugin_name* for *hook_type*.

        Returns the number of callbacks removed.
        """
        if hook_type not in self._hooks:
            return 0
        before = len(self._hooks[hook_type])
        self._hooks[hook_type] = [
            (name, cb)
            for name, cb in self._hooks[hook_type]
            if name != plugin_name
        ]
        return before - len(self._hooks[hook_type])

    def clear(self) -> None:
        """Remove all registered hooks."""
        self._hooks.clear()

    def fire(
        self,
        hook_type: HookType,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Fire all registered callbacks for *hook_type* in order.

        Each callback receives *args and **kwargs. The return value of
        the last callback that returns a non-None value is returned to
        the caller. If no callback returns non-None, None is returned.

        Exceptions in callbacks are logged and ignored so a faulty
        plugin cannot break the agent runtime.
        """
        callbacks = self._hooks.get(hook_type, [])
        last_result: Any = None
        for plugin_name, callback in callbacks:
            try:
                result = callback(*args, **kwargs)
                if result is not None:
                    last_result = result
            except Exception:
                logger.exception(
                    "Hook %s from plugin '%s' raised an exception",
                    hook_type.value,
                    plugin_name,
                )
        return last_result

    def fire_chain(
        self,
        hook_type: HookType,
        value: Any,
        *extra_args: Any,
    ) -> Any:
        """Fire hooks in a chain, passing each callback's output to the next.

        Useful for ``post_tool_call`` and ``transform_llm_output`` where
        each hook can transform the value. The first callback receives
        *value*; subsequent callbacks receive the previous callback's
        return value (or *value* if it returned None).

        Returns the final transformed value.
        """
        callbacks = self._hooks.get(hook_type, [])
        current = value
        for plugin_name, callback in callbacks:
            try:
                result = callback(current, *extra_args)
                if result is not None:
                    current = result
            except Exception:
                logger.exception(
                    "Hook %s from plugin '%s' raised an exception",
                    hook_type.value,
                    plugin_name,
                )
        return current

    @property
    def hook_count(self) -> int:
        """Total number of registered callbacks across all hook types."""
        return sum(len(callbacks) for callbacks in self._hooks.values())


# Global singleton registry
_global_hooks = HookRegistry()


def get_hook_registry() -> HookRegistry:
    """Return the global hook registry singleton."""
    return _global_hooks
