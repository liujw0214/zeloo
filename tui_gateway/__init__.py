"""TUI Gateway — event routing, Agent callbacks, billing view, change watcher."""

from __future__ import annotations

from .agent_callbacks import (
    AgentEvent,
    AgentEventType,
    CallbackRegistry,
    emit_cancelled,
    emit_error,
    emit_finish,
    emit_start,
    emit_think,
    emit_tool_call,
    emit_tool_result,
    get_registry,
)
from .billing_view import BillingSnapshot, BillingView
from .change_watcher import ChangeWatcher, WatchEvent
from .compute_host import ComputeHost, HostInfo, get_host, list_hosts, register_host

__all__ = [
    "AgentEvent",
    "AgentEventType",
    "BillingSnapshot",
    "BillingView",
    "CallbackRegistry",
    "ChangeWatcher",
    "ComputeHost",
    "HostInfo",
    "WatchEvent",
    "emit_cancelled",
    "emit_error",
    "emit_finish",
    "emit_start",
    "emit_think",
    "emit_tool_call",
    "emit_tool_result",
    "get_host",
    "get_registry",
    "list_hosts",
    "register_host",
]
