"""Zeloo ``plugins`` subcommand — plugin management."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from zeloo_cli.subcommands import Subcommand, subcommand


@subcommand("plugins")
class PluginsCmd(Subcommand):
    name = "plugins"
    help = "Manage plugins (list, install, remove, enable, disable)"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        sub = parser.add_subparsers(dest="plugins_action", help="Plugins action")

        list_p = sub.add_parser("list", help="List installed plugins")
        list_p.add_argument(
            "--json", action="store_true",
            help="Output as machine-readable JSON",
        )
        list_p.add_argument(
            "--all", action="store_true",
            help="Include built-in and disabled plugins",
        )

        install_p = sub.add_parser("install", help="Install a plugin (placeholder)")
        install_p.add_argument(
            "identifier", nargs="?", default=None,
            help="Plugin identifier, name, or URL",
        )
        install_p.add_argument(
            "--from", dest="install_from", default=None,
            help="Install from specific source",
        )

        remove_p = sub.add_parser("remove", help="Remove a plugin")
        remove_p.add_argument(
            "plugin_name", help="Plugin name to remove",
        )
        remove_p.add_argument(
            "--force", action="store_true",
            help="Skip confirmation prompt",
        )

        enable_p = sub.add_parser("enable", help="Enable a disabled plugin")
        enable_p.add_argument(
            "plugin_name", help="Plugin name to enable",
        )

        disable_p = sub.add_parser("disable", help="Disable a plugin")
        disable_p.add_argument(
            "plugin_name", help="Plugin name to disable",
        )

    def run(self, args: argparse.Namespace) -> int:
        action = getattr(args, "plugins_action", None)
        if action == "list":
            return self._list(
                getattr(args, "json", False),
                getattr(args, "all", False),
            )
        if action == "install":
            return self._install(
                getattr(args, "identifier", None),
                getattr(args, "install_from", None),
            )
        if action == "remove":
            return self._remove(
                getattr(args, "plugin_name", ""),
                getattr(args, "force", False),
            )
        if action == "enable":
            return self._enable(getattr(args, "plugin_name", ""))
        if action == "disable":
            return self._disable(getattr(args, "plugin_name", ""))
        print("Usage: zeloo plugins [list|install|remove|enable|disable]")
        return 1

    def _get_zeloo_home(self) -> Path:
        val = os.environ.get("ZELOO_HOME", "").strip()
        if val:
            return Path(val)
        if sys.platform == "win32":
            local = os.environ.get("LOCALAPPDATA", "").strip()
            base = Path(local) if local else Path.home() / "AppData" / "Local"
            return base / "Zeloo"
        return Path.home() / ".Zeloo"

    def _get_plugins_dir(self) -> Path:
        return self._get_zeloo_home() / "plugins"

    def _get_plugins_json_path(self) -> Path:
        return self._get_zeloo_home() / "plugins.json"

    def _load_plugins_json(self) -> dict[str, Any]:
        path = self._get_plugins_json_path()
        if not path.exists():
            return {"plugins": {}}
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"plugins": {}}

    def _save_plugins_json(self, data: dict[str, Any]) -> None:
        path = self._get_plugins_json_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as exc:
            print(f"Failed to save plugins.json: {exc}", file=sys.stderr)

    def _discover_plugins(self) -> list[dict[str, Any]]:
        plugins: list[dict[str, Any]] = []
        plugins_dir = self._get_plugins_dir()

        if not plugins_dir.exists():
            return []

        plugins_json = self._load_plugins_json()
        disabled = plugins_json.get("plugins", {}).get("disabled", [])

        skip_names = {"__init__", "manager", "base", "hooks"}

        for entry in sorted(plugins_dir.iterdir()):
            if entry.name.startswith("_") or entry.name.startswith("."):
                continue
            if entry.name in skip_names:
                continue

            info: dict[str, Any] = {
                "name": entry.stem if entry.suffix == ".py" else entry.name,
                "path": str(entry),
                "type": "file" if entry.is_file() else "directory",
                "enabled": entry.stem not in disabled and entry.name not in disabled,
            }

            if entry.is_dir() and (entry / "__init__.py").exists():
                info["type"] = "package"
                manifest = entry / "manifest.json"
                if manifest.exists():
                    try:
                        with open(manifest, encoding="utf-8") as f:
                            info.update(json.load(f))
                    except Exception:
                        pass
            elif entry.is_file() and entry.suffix == ".py":
                doc = entry.read_text(encoding="utf-8", errors="ignore")[:500]
                if '"""' in doc:
                    lines = doc.split("\n")
                    for i, line in enumerate(lines):
                        if '"""' in line:
                            desc_start = line.index('"""') + 3
                            desc_end = line.index('"""', desc_start) if '"""' in line[desc_start:] else None
                            if desc_end:
                                info["description"] = line[desc_start:desc_end].strip()
                            break

            plugins.append(info)

        return plugins

    def _list(self, as_json: bool, include_all: bool) -> int:
        plugins = self._discover_plugins()
        plugins_json = self._load_plugins_json()
        disabled = plugins_json.get("plugins", {}).get("disabled", [])

        if as_json:
            data = {
                "plugins": plugins,
                "disabled": disabled,
                "total": len(plugins),
            }
            print(json.dumps(data, indent=2, ensure_ascii=False))
            return 0

        print("Zeloo Plugins")
        print("=" * 50)

        if not plugins:
            print("  No plugins found.")
            print()
            print("  Plugins directory: " + str(self._get_plugins_dir()))
            print("  Add plugin .py files or directories to this location.")
            return 0

        print(f"  Total: {len(plugins)} plugin(s)")
        print(f"  Disabled: {len(disabled)}")
        print()
        print("  Name              Type         Status    Description")
        print("  " + "-" * 55)

        for p in plugins:
            name = p.get("name", "?")
            ptype = p.get("type", "?")
            enabled = p.get("enabled", True)
            desc = p.get("description", "")[:25]
            status = "enabled " if enabled else "disabled"
            print(f"  {name:<17} {ptype:<10} {status:<9} {desc}")

        if disabled:
            print()
            print(f"  Disabled plugins: {', '.join(disabled)}")

        return 0

    def _install(self, identifier: str | None, _from: str | None) -> int:
        print("Plugin installation is not yet implemented.")
        print()
        print("To install a plugin manually:")
        print(f"  1. Place the plugin in: {self._get_plugins_dir()}")
        print("  2. Ensure it has a proper structure (module or package)")
        print("  3. It will be discovered on next run")
        print()
        if identifier:
            print(f"Requested plugin: {identifier}")
        return 0

    def _remove(self, plugin_name: str, force: bool) -> int:
        plugins_dir = self._get_plugins_dir()

        plugin_path_file = plugins_dir / f"{plugin_name}.py"
        plugin_path_dir = plugins_dir / plugin_name

        target: Path | None = None
        if plugin_path_file.exists():
            target = plugin_path_file
        elif plugin_path_dir.exists():
            target = plugin_path_dir

        if target is None:
            print(f"Plugin '{plugin_name}' not found.")
            return 1

        if not force:
            print(f"Remove plugin: {plugin_name}")
            print(f"  Path: {target}")
            response = input("This will delete the plugin. Proceed? [y/N] ").strip().lower()
            if response != "y":
                print("Cancelled.")
                return 0

        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            print(f"Removed plugin: {plugin_name}")

            plugins_json = self._load_plugins_json()
            disabled = plugins_json.get("plugins", {}).get("disabled", [])
            if plugin_name in disabled:
                disabled.remove(plugin_name)
                plugins_json["plugins"]["disabled"] = disabled
                self._save_plugins_json(plugins_json)

        except Exception as exc:
            print(f"Failed to remove plugin: {exc}", file=sys.stderr)
            return 1

        return 0

    def _enable(self, plugin_name: str) -> int:
        plugins_json = self._load_plugins_json()
        disabled = plugins_json.get("plugins", {}).get("disabled", [])

        if plugin_name not in disabled:
            print(f"Plugin '{plugin_name}' is not disabled.")
            return 0

        disabled.remove(plugin_name)
        plugins_json["plugins"]["disabled"] = disabled
        self._save_plugins_json(plugins_json)
        print(f"Enabled plugin: {plugin_name}")
        return 0

    def _disable(self, plugin_name: str) -> int:
        plugins = self._discover_plugins()
        plugin_names = {p.get("name", "") for p in plugins}

        if plugin_name not in plugin_names:
            print(f"Plugin '{plugin_name}' not found. Use 'plugins list' to see available plugins.")
            return 1

        plugins_json = self._load_plugins_json()
        disabled = plugins_json.get("plugins", {}).get("disabled", [])

        if plugin_name in disabled:
            print(f"Plugin '{plugin_name}' is already disabled.")
            return 0

        disabled.append(plugin_name)
        plugins_json["plugins"]["disabled"] = disabled
        self._save_plugins_json(plugins_json)
        print(f"Disabled plugin: {plugin_name}")
        return 0
