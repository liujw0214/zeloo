"""Zeloo tools subcommand — tool discovery, inspection and validation."""

from __future__ import annotations

import argparse
import sys

from zeloo_cli.subcommands import Subcommand, subcommand


@subcommand("tools")
class ToolsCmd(Subcommand):
    name = "tools"
    help = "List, inspect and validate available tools"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        sub = parser.add_subparsers(dest="tools_action", help="Tools action")

        list_p = sub.add_parser("list", help="List all available tools")
        list_p.add_argument(
            "--category", "-c", default=None,
            help="Filter by category (file, web, system, memory, skill)",
        )
        list_p.add_argument(
            "--json", action="store_true", dest="as_json",
            help="Output as machine-readable JSON",
        )

        show_p = sub.add_parser("show", help="Show detailed info for a tool")
        show_p.add_argument("tool_name", help="Name of the tool")

        sub.add_parser("validate", help="Validate tool configuration and registration")

    def run(self, args: argparse.Namespace) -> int:
        action = getattr(args, "tools_action", None)
        if action == "list":
            return self._list(
                getattr(args, "category", None),
                getattr(args, "as_json", False),
            )
        if action == "show":
            return self._show(args.tool_name)
        if action == "validate":
            return self._validate()
        print("Usage: zeloo tools [list|show|validate]")
        return 1

    def _list(self, category: str | None, as_json: bool) -> int:
        try:
            from tools.base import discover_builtin_tools, get_registry
        except Exception as exc:  # noqa: BLE001
            print(f"(tools registry not available: {exc})")
            return 0

        # Trigger @tool decorator registration for every tool module.
        discover_builtin_tools()
        registry = get_registry().get_all()
        tools = list(registry.values())
        if category:
            tools = [
                t for t in tools
                if getattr(t, "category", None) == category
                or getattr(t, "toolset", None) == category
            ]

        if as_json:
            import json
            output = [
                {
                    "name": t.name,
                    "category": getattr(t, "toolset", None) or "unknown",
                }
                for t in tools
            ]
            print(json.dumps(output, indent=2))
            return 0

        # Rich-rendered table (Hermes Agent parity).
        from zeloo_cli.rich_render import make_console, make_table

        console = make_console()
        title = f"Available tools ({len(tools)})"
        if category:
            title += f"  — filtered: {category}"
        table = make_table(
            title=title,
            columns=[
                ("NAME", "bold cyan"),
                ("CATEGORY", "yellow"),
                ("DESCRIPTION", "white"),
            ],
        )
        for t in tools:
            table.add_row(
                t.name,
                getattr(t, "toolset", None) or "unknown",
                (getattr(t, "description", "") or "")[:80],
            )
        console.print(table)
        return 0

    def _show(self, tool_name: str) -> int:
        try:
            from tools.base import discover_builtin_tools, get_registry
        except Exception:  # noqa: BLE001
            print("(tools registry not available)")
            return 1

        discover_builtin_tools()
        tool = get_registry().get(tool_name)
        if tool is None:
            print(f"Tool not found: {tool_name}")
            return 1

        # Rich-rendered key/value pairs (Hermes Agent parity).
        from zeloo_cli.rich_render import render_keyvalue

        params = getattr(tool, "parameters", None)
        pairs = [
            ("Name", tool.name),
            ("Category", getattr(tool, "category", "unknown")),
            ("Description", getattr(tool, "description", "(no description)")),
        ]
        if params:
            pairs.append(("Parameters", str(params)))
        render_keyvalue(pairs)
        return 0

    def _validate(self) -> int:
        try:
            from tools.base import discover_builtin_tools, get_registry
        except Exception as exc:
            print(f"Error: tools registry not available: {exc}")
            return 1

        discover_builtin_tools()
        registry = get_registry()
        all_tools = registry.get_all()
        tools = list(all_tools.values())

        if not tools:
            print("No tools registered.")
            return 1

        results: list[tuple[str, str, str]] = []
        errors = 0

        for tool in tools:
            name = tool.name
            if not name:
                results.append(("error", "unnamed", "Tool has no name"))
                errors += 1
                continue

            if not getattr(tool, "description", ""):
                results.append(("warn", name, "Missing description"))
                continue

            if not getattr(tool, "execute", None):
                results.append(("error", name, "No execute function"))
                errors += 1
                continue

            params = getattr(tool, "parameters", None)
            if params:
                if not isinstance(params, dict):
                    results.append(("warn", name, "Invalid parameters schema"))
                elif "properties" not in params:
                    results.append(("warn", name, "Parameters missing 'properties'"))
                else:
                    results.append(("ok", name, "Valid"))
            else:
                results.append(("ok", name, "Valid (no parameters)"))

        try:
            from zeloo_cli.rich_render import make_console, make_table
            console = make_console()
            table = make_table(
                title=f"Tool validation ({len(results)} tools)",
                columns=[
                    ("STATUS", "bold"),
                    ("TOOL", "cyan"),
                    ("MESSAGE", "white"),
                ],
            )
            for status, name, msg in results:
                style = {"ok": "green", "warn": "yellow", "error": "red"}.get(status, "")
                table.add_row(status.upper(), name, msg)
            console.print(table)
        except Exception:
            print(f"{'STATUS':<8} {'TOOL':<30} {'MESSAGE'}")
            print("-" * 70)
            for status, name, msg in results:
                print(f"{status.upper():<8} {name:<30} {msg}")

        print(f"\nValidation complete: {errors} error(s), "
              f"{sum(1 for s, _, _ in results if s == 'warn')} warning(s), "
              f"{sum(1 for s, _, _ in results if s == 'ok')} ok")
        return 0 if errors == 0 else 1
