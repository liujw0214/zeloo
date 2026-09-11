"""Zeloo config subcommand — configuration management."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from zeloo_cli.subcommands import Subcommand, subcommand


@subcommand("config")
class ConfigCmd(Subcommand):
    name = "config"
    help = "Show, get, set, list or edit configuration"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        sub = parser.add_subparsers(dest="config_action", help="Config action")

        get_p = sub.add_parser("get", help="Get a configuration value")
        get_p.add_argument("key", help="Configuration key (dot-notation, e.g. model)")

        set_p = sub.add_parser("set", help="Set a configuration value")
        set_p.add_argument("key", help="Configuration key (dot-notation, e.g. model)")
        set_p.add_argument("value", help="Value to set")

        sub.add_parser("list", help="List all configuration values")

        sub.add_parser("edit", help="Open configuration in editor")

    def run(self, args: argparse.Namespace) -> int:
        action = getattr(args, "config_action", None)

        if action == "get":
            return self._get(args.key)
        if action == "set":
            return self._set(args.key, args.value)
        if action == "list":
            return self._list()
        if action == "edit":
            return self._edit()

        print("Usage: Zeloo config [get|set|list|edit]")
        return 1

    def _get_config_path(self) -> Path:
        from agent.zeloo_constants import get_zeloo_home
        return get_zeloo_home() / "config.yaml"

    def _load_config(self) -> dict:
        import yaml
        path = self._get_config_path()
        if not path.exists():
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    def _save_config(self, config: dict) -> None:
        import yaml
        path = self._get_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    def _get_nested(self, cfg: dict, key: str) -> object:
        parts = key.split(".")
        cur: object = cfg
        for part in parts:
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return None
        return cur

    def _set_nested(self, cfg: dict, key: str, value: str) -> None:
        parts = key.split(".")
        cur = cfg
        for part in parts[:-1]:
            if part not in cur or not isinstance(cur[part], dict):
                cur[part] = {}
            cur = cur[part]
        parsed: object = value
        if value.lower() in ("true", "false"):
            parsed = value.lower() == "true"
        else:
            try:
                parsed = int(value)
            except ValueError:
                try:
                    parsed = float(value)
                except ValueError:
                    parsed = value
        cur[parts[-1]] = parsed

    def _get(self, key: str) -> int:
        cfg = self._load_config()
        value = self._get_nested(cfg, key)
        if value is not None:
            print(value)
            return 0
        print(f"(not set: {key})")
        return 1

    def _set(self, key: str, value: str) -> int:
        cfg = self._load_config()
        self._set_nested(cfg, key, value)
        self._save_config(cfg)
        print(f"Set {key} = {value}")
        print(f"Config saved to: {self._get_config_path()}")
        return 0

    def _list(self) -> int:
        cfg = self._load_config()
        if not cfg:
            print("(no configuration found)")
            return 0

        import yaml
        print(yaml.dump(cfg, default_flow_style=False, sort_keys=False))
        return 0

    def _edit(self) -> int:
        path = self._get_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("# Zeloo Configuration\n", encoding="utf-8")

        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
        if not editor:
            if sys.platform == "win32":
                editor = "notepad"
            else:
                editor = "vi"

        try:
            result = subprocess.run(
                [editor, str(path)],
                stdin=sys.stdin,
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
            return result.returncode
        except FileNotFoundError:
            print(f"Editor '{editor}' not found. Set $EDITOR to choose an editor.")
            return 1
        except Exception as exc:
            print(f"Failed to open editor: {exc}")
            return 1
