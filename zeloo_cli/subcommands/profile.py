"""Zeloo ``profile`` subcommand — multi-profile management."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from zeloo_cli.subcommands import Subcommand, subcommand


@subcommand("profile")
class ProfileCmd(Subcommand):
    name = "profile"
    help = "Manage Zeloo profiles"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        sub = parser.add_subparsers(dest="profile_action", help="Profile action")

        sub.add_parser("list", help="List all profiles")
        sub.add_parser("show", help="Show active profile details")

        use_p = sub.add_parser("use", help="Activate a profile")
        use_p.add_argument("profile_name", help="Profile name to activate")

        create_p = sub.add_parser("create", help="Create a new profile")
        create_p.add_argument("profile_name", help="New profile name")
        create_p.add_argument("--copy-from", dest="copy_from", default=None, help="Copy config from existing profile")

        delete_p = sub.add_parser("delete", help="Delete a profile")
        delete_p.add_argument("profile_name", help="Profile name to delete")
        delete_p.add_argument("--force", action="store_true", help="Skip confirmation prompt")

    def run(self, args: argparse.Namespace) -> int:
        action = getattr(args, "profile_action", None)
        if action == "list":
            return self._list()
        if action == "show":
            return self._show()
        if action == "use":
            return self._use(args)
        if action == "create":
            return self._create(args)
        if action == "delete":
            return self._delete(args)
        print("Usage: zeloo profile [list|show|use|create|delete]")
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

    def _list(self) -> int:
        from zeloo_cli.profiles import get_active_profile_name, list_profiles

        profiles = list_profiles()
        active = get_active_profile_name()

        print("Available profiles:")
        for p in profiles:
            marker = " [active]" if p == active else ""
            print(f"  - {p}{marker}")
        return 0

    def _show(self) -> int:
        from zeloo_cli.profiles import get_active_profile_name, get_profile_dir, list_profiles

        profiles = list_profiles()
        active = get_active_profile_name()
        active_dir = get_profile_dir(active)

        print(f"Active profile: {active}")
        print(f"Profile path:   {active_dir}")

        print("\nProfile contents:")
        if active_dir.exists() and active_dir.is_dir():
            for item in sorted(active_dir.iterdir()):
                print(f"  {item.name}/" if item.is_dir() else f"  {item.name}")
        else:
            print("  (profile directory not found)")

        print("\nAll profiles:")
        for p in profiles:
            marker = " [active]" if p == active else ""
            print(f"  - {p}{marker}")

        return 0

    def _use(self, args: argparse.Namespace) -> int:
        from zeloo_cli.profiles import activate_profile, get_active_profile_name, get_profile_dir

        name = getattr(args, "profile_name", None)
        if not name:
            print("Error: profile name required")
            return 1

        try:
            activate_profile(name)
            print(f"Activated profile: {name}")
            print(f"Profile path: {get_profile_dir(name)}")
            print(f"\nNote: Use 'export ZELOO_HOME=\"{get_profile_dir(name)}\"' in your shell")
            print(f"      for persistent activation across sessions.")
        except FileNotFoundError:
            print(f"Error: Profile '{name}' not found")
            return 1
        except Exception as exc:
            print(f"Error activating profile: {exc}")
            return 1

        return 0

    def _create(self, args: argparse.Namespace) -> int:
        from zeloo_cli.profiles import create_profile, get_profile_dir, list_profiles

        name = getattr(args, "profile_name", None)
        if not name:
            print("Error: profile name required")
            return 1

        copy_from = getattr(args, "copy_from", None)
        if copy_from and copy_from not in list_profiles():
            print(f"Error: source profile '{copy_from}' not found")
            return 1

        try:
            path = create_profile(name, copy_from=copy_from)
            print(f"Created profile: {name}")
            print(f"Profile path: {path}")
        except ValueError as exc:
            print(f"Error: {exc}")
            return 1
        except FileExistsError:
            print(f"Error: Profile '{name}' already exists")
            return 1
        except Exception as exc:
            print(f"Error creating profile: {exc}")
            return 1

        return 0

    def _delete(self, args: argparse.Namespace) -> int:
        from zeloo_cli.profiles import delete_profile, get_active_profile_name, list_profiles

        name = getattr(args, "profile_name", None)
        if not name:
            print("Error: profile name required")
            return 1

        if name == "default":
            print("Error: Cannot delete the 'default' profile")
            return 1

        if name not in list_profiles():
            print(f"Error: Profile '{name}' not found")
            return 1

        active = get_active_profile_name()
        if name == active:
            print(f"Error: Cannot delete the active profile '{name}'")
            print("Switch to another profile first with 'zeloo profile use <name>'")
            return 1

        force = getattr(args, "force", False)
        if not force:
            confirm = input(f"Delete profile '{name}'? This cannot be undone. [y/N] ")
            if confirm.lower() != "y":
                print("Cancelled.")
                return 0

        try:
            delete_profile(name)
            print(f"Deleted profile: {name}")
        except Exception as exc:
            print(f"Error deleting profile: {exc}")
            return 1

        return 0
