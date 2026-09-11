"""Zeloo ``hooks`` subcommand — inspect and manage shell-script hooks."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from zeloo_cli.subcommands import Subcommand, subcommand


@subcommand("hooks")
class HooksCmd(Subcommand):
    name = "hooks"
    help = "Inspect and manage shell-script hooks"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        sub = parser.add_subparsers(dest="hooks_action", help="Hooks action")

        list_p = sub.add_parser("list", help="List configured hooks")
        list_p.add_argument(
            "--json", action="store_true",
            help="Output as machine-readable JSON",
        )

        test_p = sub.add_parser("test", help="Test hook scripts with synthetic payload")
        test_p.add_argument(
            "hook_name", nargs="?", default=None,
            help="Specific hook name to test (default: all)",
        )
        test_p.add_argument(
            "--payload", default=None,
            help="Custom JSON payload file to use",
        )

        revoke_p = sub.add_parser("revoke", help="Remove a hook from the allowlist")
        revoke_p.add_argument(
            "hook_path", help="Path or pattern of hook to revoke",
        )
        revoke_p.add_argument(
            "--force", action="store_true",
            help="Skip confirmation prompt",
        )

        doctor_p = sub.add_parser("doctor", help="Check hook script executability")

    def run(self, args: argparse.Namespace) -> int:
        action = getattr(args, "hooks_action", None)
        if action == "list":
            return self._list(getattr(args, "json", False))
        if action == "test":
            return self._test(
                getattr(args, "hook_name", None),
                getattr(args, "payload", None),
            )
        if action == "revoke":
            return self._revoke(
                getattr(args, "hook_path", ""),
                getattr(args, "force", False),
            )
        if action == "doctor":
            return self._doctor()
        print("Usage: zeloo hooks [list|test|revoke|doctor]")
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

    def _load_hooks_config(self) -> dict[str, Any]:
        config_path = self._get_zeloo_home() / "config.yaml"
        if not config_path.exists():
            return {}
        try:
            import yaml
            with open(config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return data.get("hooks", {})
        except Exception:
            return {}

    def _load_allowlist(self) -> list[dict[str, str]]:
        allowlist_path = self._get_zeloo_home() / "hooks_allowlist.json"
        if not allowlist_path.exists():
            return []
        try:
            with open(allowlist_path, encoding="utf-8") as f:
                return json.load(f).get("hooks", [])
        except Exception:
            return []

    def _save_allowlist(self, hooks: list[dict[str, str]]) -> None:
        allowlist_path = self._get_zeloo_home() / "hooks_allowlist.json"
        try:
            with open(allowlist_path, "w", encoding="utf-8") as f:
                json.dump({"hooks": hooks, "version": 1}, f, indent=2)
        except Exception as exc:
            print(f"Failed to save allowlist: {exc}", file=sys.stderr)

    def _list(self, as_json: bool) -> int:
        hooks_config = self._load_hooks_config()
        allowlist = self._load_allowlist()
        allowlist_paths = {h.get("path", "") for h in allowlist}

        if as_json:
            data = {
                "configured": hooks_config,
                "allowlist": allowlist,
            }
            print(json.dumps(data, indent=2, ensure_ascii=False))
            return 0

        print("Zeloo Hooks Configuration")
        print("=" * 50)

        if not hooks_config:
            print("  No hooks configured in config.yaml")
            print()
            print("  Add hooks configuration to ~/.Zeloo/config.yaml:")
            print("  hooks:")
            print("    pre_task:")
            print("      - /path/to/pre_task_hook.sh")
            print("    post_task:")
            print("      - /path/to/post_task_hook.sh")
        else:
            print("  Configured hooks:")
            for hook_type, paths in hooks_config.items():
                if isinstance(paths, list):
                    for path in paths:
                        status = " [allowed]" if path in allowlist_paths else " [not allowed]"
                        print(f"    {hook_type}: {path}{status}")
                elif paths:
                    status = " [allowed]" if paths in allowlist_paths else " [not allowed]"
                    print(f"    {hook_type}: {paths}{status}")

        print()
        print(f"  Allowlist entries: {len(allowlist)}")
        for h in allowlist:
            print(f"    - {h.get('path', '?')} (added: {h.get('added_at', 'unknown')})")

        return 0

    def _test(self, hook_name: str | None, payload_file: str | None) -> int:
        hooks_config = self._load_hooks_config()

        if not hooks_config:
            print("No hooks configured. Nothing to test.")
            return 0

        if hook_name and hook_name not in hooks_config:
            print(f"Hook '{hook_name}' not found in configuration.")
            return 1

        if payload_file:
            try:
                with open(payload_file, encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception as exc:
                print(f"Failed to load payload file: {exc}", file=sys.stderr)
                return 1
        else:
            payload = {
                "event": "test",
                "timestamp": str(Path(__file__).stat().st_mtime),
                "session_id": "test_session_001",
                "tool_name": "test_tool",
                "args": {"test": True},
            }

        print("Testing hooks with synthetic payload...")
        print(f"Payload: {json.dumps(payload, indent=2)[:200]}...")
        print()

        targets = {hook_name: hooks_config[hook_name]} if hook_name else hooks_config
        results: list[dict[str, Any]] = []

        for name, paths in targets.items():
            if isinstance(paths, str):
                paths = [paths]

            for path in paths:
                path_obj = Path(path)
                result: dict[str, Any] = {
                    "hook": name,
                    "path": path,
                    "exists": path_obj.exists(),
                    "executable": False,
                    "ran": False,
                    "exit_code": None,
                    "output": "",
                    "error": "",
                }

                if result["exists"]:
                    try:
                        result["executable"] = os.access(path_obj, os.X_OK)
                    except Exception:
                        result["executable"] = False

                    if result["executable"]:
                        try:
                            proc = subprocess.run(
                                [str(path_obj)],
                                input=json.dumps(payload),
                                capture_output=True,
                                text=True,
                                timeout=10,
                                cwd=self._get_zeloo_home(),
                                env={**os.environ, "ZELOO_HOOK_PAYLOAD": json.dumps(payload)},
                            )
                            result["ran"] = True
                            result["exit_code"] = proc.returncode
                            result["output"] = proc.stdout[:500]
                            result["error"] = proc.stderr[:500]
                        except subprocess.TimeoutExpired:
                            result["error"] = "Timeout (>10s)"
                        except Exception as exc:
                            result["error"] = str(exc)
                    else:
                        result["error"] = "Not executable (add execute permission)"
                else:
                    result["error"] = "File not found"

                results.append(result)

                status_icon = "OK" if result["exit_code"] == 0 else "FAIL"
                print(f"  [{status_icon}] {name}: {path}")
                if result["error"]:
                    print(f"        Error: {result['error']}")
                if result["output"]:
                    print(f"        Output: {result['output'][:100]}")

        failed = sum(1 for r in results if not r["ran"] or r["exit_code"] != 0)
        print()
        print(f"Test results: {len(results)} hook(s), {failed} failure(s)")
        return 0 if failed == 0 else 1

    def _revoke(self, hook_path: str, force: bool) -> int:
        allowlist = self._load_allowlist()
        original_count = len(allowlist)

        allowlist = [h for h in allowlist if hook_path not in h.get("path", "")]

        if len(allowlist) == original_count:
            print(f"Hook path '{hook_path}' not found in allowlist.")
            return 1

        if not force:
            print(f"Remove allowlist entry for: {hook_path}")
            response = input("Proceed? [y/N] ").strip().lower()
            if response != "y":
                print("Cancelled.")
                return 0

        self._save_allowlist(allowlist)
        removed = original_count - len(allowlist)
        print(f"Revoked {removed} allowlist entry(ies).")
        return 0

    def _doctor(self) -> int:
        print("Running hook diagnostics...")
        print()

        issues: list[str] = []
        warnings: list[str] = []

        hooks_config = self._load_hooks_config()
        if not hooks_config:
            warnings.append("No hooks configured in config.yaml")

        allowlist = self._load_allowlist()
        allowlist_paths = {h.get("path", "") for h in allowlist}

        for name, paths in hooks_config.items():
            if isinstance(paths, str):
                paths = [paths]

            for path in paths:
                path_obj = Path(path)

                if not path_obj.exists():
                    issues.append(f"{name}: File not found: {path}")
                    continue

                if not os.access(path_obj, os.R_OK):
                    issues.append(f"{name}: Not readable: {path}")
                    continue

                if not os.access(path_obj, os.X_OK):
                    issues.append(f"{name}: Not executable: {path} (run: chmod +x {path})")

                if path not in allowlist_paths:
                    warnings.append(f"{name}: Not in allowlist: {path}")

        print("Diagnostics:")
        print(f"  Configured hooks: {len(hooks_config)}")
        print(f"  Allowlist entries: {len(allowlist)}")
        print(f"  Issues: {len(issues)}")
        print(f"  Warnings: {len(warnings)}")

        if issues:
            print()
            print("Issues (must fix):")
            for issue in issues:
                print(f"  [FAIL] {issue}")

        if warnings:
            print()
            print("Warnings:")
            for warning in warnings:
                print(f"  [WARN] {warning}")

        if not issues and not warnings:
            print()
            print("All hooks look healthy!")

        return 1 if issues else 0
