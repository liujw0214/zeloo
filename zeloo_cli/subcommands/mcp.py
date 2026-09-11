"""``zeloo mcp`` subcommand — Hermes-style MCP server management.

Sub-actions:
* ``mcp list`` — show configured MCP servers
* ``mcp add <name> <command> [args...]`` — add a server
* ``mcp remove <name>`` — remove a server
* ``mcp test <name>`` — probe a server's stdio handshake
* ``mcp serve`` — run Zeloo as an MCP server (exposes tools to other agents)
* ``mcp enable/disable <name>`` — toggle servers

Storage: ``~/.zeloo/config.yaml`` under ``mcp_servers:``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from agent.zeloo_constants import get_zeloo_home

logger = logging.getLogger(__name__)


def _config_path(home: Path | str | None = None) -> Path:
    if isinstance(home, str):
        home = Path(home)
    base = home or get_zeloo_home()
    return base / "config.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml

        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        return {}


def _save_yaml(path: Path, data: dict[str, Any]) -> None:
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(
            data, fh, default_flow_style=False, sort_keys=False, allow_unicode=True
        )


def _get_servers(home: Path | str | None = None) -> dict[str, Any]:
    cfg = _load_yaml(_config_path(home))
    return cfg.get("mcp_servers", {})


def cmd_mcp_list(args: argparse.Namespace) -> int:
    """``zeloo mcp list``."""
    home = getattr(args, "home", None)
    servers = _get_servers(home)
    verbose = getattr(args, "verbose", False)
    json_output = getattr(args, "json", False)

    if json_output:
        print(json.dumps(servers, indent=2))
        return 0

    if not servers:
        print("No MCP servers configured.")
        print("Add servers with `zeloo mcp add <name> <command> [args...]`")
        return 0

    print(f"Configured MCP servers ({len(servers)}):")
    for name, cfg_item in sorted(servers.items()):
        if isinstance(cfg_item, dict):
            cmd = cfg_item.get("command", "?")
            srv_args = " ".join(cfg_item.get("args", []))
            status = "enabled" if cfg_item.get("enabled", True) else "disabled"
        else:
            cmd = str(cfg_item)
            srv_args = ""
            status = "enabled"
        detail = f"{cmd} {srv_args}" if verbose else ""
        print(f"  {name}: {status} {detail}")
    return 0


def cmd_mcp_add(args: argparse.Namespace) -> int:
    """``zeloo mcp add <name> [--command CMD --args ARGS]``."""
    name = getattr(args, "name", None)
    if not name:
        print("Usage: zeloo mcp add <name> --command CMD [--args ARGS...]")
        return 1

    command = getattr(args, "mcp_command", None) or getattr(args, "command", None)
    args_list = getattr(args, "args", []) or []

    if not command:
        print("Error: --command is required (e.g. --command 'npx')")
        return 1

    home = getattr(args, "home", None)
    cfg_path = _config_path(home)
    cfg = _load_yaml(cfg_path)
    servers = cfg.setdefault("mcp_servers", {})
    servers[name] = {
        "command": command,
        "args": args_list,
        "enabled": True,
    }
    _save_yaml(cfg_path, cfg)
    print(
        f"Added MCP server {name!r}: {command} {' '.join(args_list)}"
    )
    return 0


def cmd_mcp_remove(args: argparse.Namespace) -> int:
    """``zeloo mcp remove <name>``."""
    name = getattr(args, "name", None)
    if not name:
        print("Usage: zeloo mcp remove <name>")
        return 1
    home = getattr(args, "home", None)
    cfg_path = _config_path(home)
    cfg = _load_yaml(cfg_path)
    servers = cfg.get("mcp_servers", {})
    if name not in servers:
        print(f"Server {name!r} not found.")
        return 1
    del servers[name]
    cfg["mcp_servers"] = servers
    _save_yaml(cfg_path, cfg)
    print(f"Removed MCP server {name!r}.")
    return 0


def cmd_mcp_test(args: argparse.Namespace) -> int:
    """``zeloo mcp test <name>`` — probe server by launching it briefly."""
    name = getattr(args, "name", None)
    if not name:
        print("Usage: zeloo mcp test <name>")
        return 1
    servers = _get_servers(getattr(args, "home", None))
    cfg_item = servers.get(name)
    if cfg_item is None:
        print(f"Server {name!r} not found.")
        return 1
    if not isinstance(cfg_item, dict):
        print(f"Server {name!r} is not a dict config.")
        return 1

    command = cfg_item.get("command")
    args_list = cfg_item.get("args", [])
    if not command:
        print(f"Server {name!r} has no command.")
        return 1

    if not shutil.which(command):
        print(f"Command {command!r} not found in PATH.")
        return 1

    print(f"Testing MCP server {name!r}: {command} {' '.join(args_list)}")
    try:
        proc = subprocess.Popen(
            [command, *args_list],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = proc.communicate(input='{"jsonrpc":"2.0","method":"ping","id":1}\n', timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            print(f"  Server started but did not respond to ping within 5s.")
            print(f"  This is normal for stdio MCP servers waiting for input.")
            print(f"  Status: reachable")
            return 0

        if proc.returncode == 0:
            print(f"  Status: reachable (returned 0)")
        else:
            print(f"  Status: exited with code {proc.returncode}")
            if stderr.strip():
                print(f"  stderr: {stderr.strip()[:200]}")
        return 0 if proc.returncode == 0 else 1
    except FileNotFoundError:
        print(f"  Status: command not found")
        return 1
    except Exception as exc:
        print(f"  Status: error — {exc}")
        return 1


def cmd_mcp_enable(args: argparse.Namespace) -> int:
    """``zeloo mcp enable <name>``."""
    name = getattr(args, "name", None)
    if not name:
        print("Usage: zeloo mcp enable <name>")
        return 1
    home = getattr(args, "home", None)
    cfg_path = _config_path(home)
    cfg = _load_yaml(cfg_path)
    servers = cfg.get("mcp_servers", {})
    if name not in servers:
        print(f"Server {name!r} not found.")
        return 1
    if isinstance(servers[name], dict):
        servers[name]["enabled"] = True
    _save_yaml(cfg_path, cfg)
    print(f"Enabled MCP server {name!r}.")
    return 0


def cmd_mcp_disable(args: argparse.Namespace) -> int:
    """``zeloo mcp disable <name>``."""
    name = getattr(args, "name", None)
    if not name:
        print("Usage: zeloo mcp disable <name>")
        return 1
    home = getattr(args, "home", None)
    cfg_path = _config_path(home)
    cfg = _load_yaml(cfg_path)
    servers = cfg.get("mcp_servers", {})
    if name not in servers:
        print(f"Server {name!r} not found.")
        return 1
    if isinstance(servers[name], dict):
        servers[name]["enabled"] = False
    _save_yaml(cfg_path, cfg)
    print(f"Disabled MCP server {name!r}.")
    return 0


def cmd_mcp_serve(args: argparse.Namespace) -> int:
    """``zeloo mcp serve`` — run Zeloo as an MCP server.

    Exposes Zeloo's tools (file/shell/web/etc.) over the Model Context
    Protocol so other agents (Claude Desktop, etc.) can use them.
    """
    verbose = getattr(args, "verbose", False)
    if verbose:
        logger.setLevel(logging.DEBUG)
    print("Starting Zeloo MCP server on stdio...")
    print("Exposing tools: file_read, file_write, shell, web_search, etc.")
    try:
        from zeloo_cli.mcp_server import serve_stdio

        return serve_stdio()
    except ImportError:
        print("MCP server module not available.")
        print("Install with: uv pip install mcp")
        return 1


def cmd_mcp(args: argparse.Namespace) -> int:
    """Top-level dispatcher for ``zeloo mcp``."""
    action = getattr(args, "mcp_action", None)
    if action is None:
        return cmd_mcp_list(args)
    handler = {
        "list": cmd_mcp_list,
        "add": cmd_mcp_add,
        "remove": cmd_mcp_remove,
        "rm": cmd_mcp_remove,
        "test": cmd_mcp_test,
        "serve": cmd_mcp_serve,
        "enable": cmd_mcp_enable,
        "disable": cmd_mcp_disable,
    }.get(action)
    if handler is None:
        print(f"Unknown mcp action: {action}")
        return 1
    return handler(args)


def build_mcp_parser(subparsers: Any, *, cmd_mcp_handler: Any) -> None:
    """Attach the Hermes-style ``mcp`` subparser."""
    mcp_parser = subparsers.add_parser(
        "mcp",
        help="Manage MCP servers and run Zeloo as an MCP server",
        description="Manage MCP server connections and run Zeloo as an MCP server.",
    )
    sub = mcp_parser.add_subparsers(dest="mcp_action")

    list_p = sub.add_parser("list", help="List configured MCP servers")
    list_p.add_argument("--verbose", "-v", action="store_true")
    list_p.add_argument("--json", action="store_true")

    add_p = sub.add_parser("add", help="Add an MCP server")
    add_p.add_argument("name", help="Server name")
    add_p.add_argument(
        "--command",
        dest="mcp_command",
        help="Stdio command (e.g. 'npx', 'uvx')",
    )
    add_p.add_argument(
        "--args",
        nargs="*",
        default=[],
        help="Arguments for stdio command",
    )

    rm_p = sub.add_parser(
        "remove", aliases=["rm"], help="Remove an MCP server"
    )
    rm_p.add_argument("name", help="Server name")

    test_p = sub.add_parser("test", help="Test an MCP server connection")
    test_p.add_argument("name", help="Server name")

    enable_p = sub.add_parser("enable", help="Enable an MCP server")
    enable_p.add_argument("name", help="Server name")
    disable_p = sub.add_parser("disable", help="Disable an MCP server")
    disable_p.add_argument("name", help="Server name")

    serve_p = sub.add_parser(
        "serve", help="Run Zeloo as an MCP server (stdio)"
    )
    serve_p.add_argument("--verbose", "-v", action="store_true")

    mcp_parser.set_defaults(func=cmd_mcp_handler)