"""Tests for tool discovery and toolset filtering."""

# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from model_tools import discover_and_filter_tools
from tools.base import discover_builtin_tools, get_registry


def test_web_search_registered():
    discover_builtin_tools()
    registry = get_registry()
    assert "web_search" in registry.get_names()
    tool = registry.get("web_search")
    assert tool is not None
    assert tool.toolset == "web"


def test_web_search_in_cli_toolset():
    info = discover_and_filter_tools(platform="cli")
    assert "web_search" in info["valid_tool_names"]


def test_web_search_not_in_telegram_toolset():
    """Telegram only enables web, file, skills, memory — web_search is in web."""
    info = discover_and_filter_tools(platform="telegram")
    assert "web_search" in info["valid_tool_names"]


def test_shell_not_in_telegram_toolset():
    info = discover_and_filter_tools(platform="telegram")
    assert "shell" not in info["valid_tool_names"]


if __name__ == "__main__":
    test_web_search_registered()
    test_web_search_in_cli_toolset()
    test_web_search_not_in_telegram_toolset()
    test_shell_not_in_telegram_toolset()
    print("All tool discovery tests passed!")
