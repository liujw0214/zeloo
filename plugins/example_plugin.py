"""Example plugin — demonstrates the plugin pattern.

This plugin registers a single tool, ``example_hello``, and a skill.
Copy this file as a starting point for your own plugins.
"""

from __future__ import annotations

from typing import Any

from tools.base import tool


@tool(name="example_hello", description="Greet someone", toolset="plugins")
def example_hello(name: str) -> str:
    """Return a friendly greeting.

    Args:
        name: The name of the person to greet.
    """
    return f"Hello, {name}! This is the example plugin."


def register(registry: Any, skills_manager: Any) -> None:
    """Plugin entry point — called once at startup.

    Tools decorated with @tool are already registered on import.
    Use this function for additional setup (e.g. registering skills,
    initializing clients).
    """
    # Example: register a skill programmatically
    if skills_manager is not None:
        pass  # skills_manager.register_skill(...)
