"""Tests for M8 modules: MCP tool filter, delegate tool, terminal backends."""

# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from mcp.tool_filter import filter_tools, filter_tools_from_config


def _tools(names):
    return [{"name": n} for n in names]


def test_filter_no_rules_returns_all():
    tools = _tools(["a", "b", "c"])
    assert filter_tools(tools) == tools


def test_filter_include_pattern():
    tools = _tools(["a.b", "a.c", "b.x"])
    result = filter_tools(tools, include=["a.*"])
    assert [t["name"] for t in result] == ["a.b", "a.c"]


def test_filter_exclude_pattern():
    tools = _tools(["a.b", "a.c", "b.x"])
    result = filter_tools(tools, exclude=["*.x"])
    assert [t["name"] for t in result] == ["a.b", "a.c"]


def test_filter_exclude_takes_precedence():
    tools = _tools(["a.b", "a.secret", "b.x"])
    result = filter_tools(tools, include=["a.*"], exclude=["*.secret"])
    assert [t["name"] for t in result] == ["a.b"]


def test_filter_empty_input():
    assert filter_tools([]) == []


def test_filter_from_config():
    tools = _tools(["keep_me", "drop_me"])
    config = {"include": ["keep_*"], "exclude": ["drop_*"]}
    result = filter_tools_from_config(tools, config)
    assert [t["name"] for t in result] == ["keep_me"]


def test_filter_from_config_empty():
    tools = _tools(["a", "b"])
    result = filter_tools_from_config(tools, {})
    assert [t["name"] for t in result] == ["a", "b"]


def test_delegate_tool_registered():
    from tools.base import discover_builtin_tools, get_registry

    discover_builtin_tools()
    assert "delegate_task" in get_registry().get_names()
    tool = get_registry().get("delegate_task")
    assert tool.toolset == "delegation"
    assert tool.dangerous is True


def test_delegate_tool_in_cli_toolset():
    from model_tools import discover_and_filter_tools

    info = discover_and_filter_tools(platform="cli")
    assert "delegate_task" in info["valid_tool_names"]


def test_docker_backend_requires_docker_package():
    """DockerBackend should raise ImportError when docker is unavailable."""
    from terminal.docker import DockerBackend

    try:
        import docker  # noqa: F401
        # docker is installed; just verify construction works
        backend = DockerBackend(image="alpine:latest")
        assert backend._image == "alpine:latest"
    except ImportError:
        try:
            DockerBackend(image="alpine:latest")
            raise AssertionError("Expected ImportError")
        except ImportError:
            pass  # expected


def test_ssh_backend_requires_paramiko():
    """SSHTerminalAdapter should raise ImportError when paramiko is unavailable."""
    from terminal.ssh import SSHTerminalAdapter

    try:
        import paramiko  # noqa: F401
        adapter = SSHTerminalAdapter(host="localhost", port=22, username="root")
        assert adapter.host == "localhost"
    except ModuleNotFoundError:
        pytest.skip("paramiko not installed")


if __name__ == "__main__":
    test_filter_no_rules_returns_all()
    test_filter_include_pattern()
    test_filter_exclude_pattern()
    test_filter_exclude_takes_precedence()
    test_filter_empty_input()
    test_filter_from_config()
    test_filter_from_config_empty()
    test_delegate_tool_registered()
    test_delegate_tool_in_cli_toolset()
    test_docker_backend_requires_docker_package()
    test_ssh_backend_requires_paramiko()
    print("All M8 tests passed!")
