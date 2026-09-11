"""Zeloo update subcommand — self-upgrade and dependency update."""

from __future__ import annotations

import argparse
import subprocess
import sys

from zeloo_cli.subcommands import Subcommand, subcommand
from zeloo_cli.update_checker import (
    UpdateChannel,
    check_latest_version,
    get_update_command,
    get_version_info,
)


def cmd_update_check(channel: UpdateChannel | None = None) -> int:
    """Check for newer versions without installing.

    Prints a friendly single-line message and always returns ``0`` so
    the background ``cli._background_version_check`` subprocess can rely
    on a non-zero exit code meaning "something went wrong", not "you're
    out of date".
    """
    current, latest, used_channel = check_latest_version(channel)
    channel_label = f" [{used_channel} channel]" if used_channel != "stable" else ""

    if latest is None:
        print(f"Already up to date ({current}){channel_label} [check skipped: no network]")
        return 0

    if latest != current:
        version_info = get_version_info(latest, used_channel)
        print(f"New version available: {latest} (current: {current}){channel_label}")
        if version_info and version_info.release_date:
            print(f"  Released: {version_info.release_date[:10]}")
        cmd = get_update_command(latest)
        print(f"  To update: {cmd}")
        return 0

    print(f"Already up to date ({current}){channel_label}")
    return 0


@subcommand("update")
class UpdateCmd(Subcommand):
    name = "update"
    help = "Check for and install updates to Zeloo"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--check", action="store_true",
            help="Only check for updates, do not install",
        )
        parser.add_argument(
            "--pip", action="store_true",
            help="Also update pip and core dependencies",
        )
        parser.add_argument(
            "--channel",
            choices=["stable", "beta"],
            default=None,
            help="Release channel (default: from ZELOO_UPDATE_CHANNEL env, or stable)",
        )
        parser.add_argument(
            "--json", action="store_true",
            help="Output as JSON (--check only)",
        )

    def run(self, args: argparse.Namespace) -> int:
        channel: UpdateChannel | None = getattr(args, "channel", None)

        if args.check:
            if args.json:
                import json as _json
                current, latest, used_channel = check_latest_version(channel)
                version_info = get_version_info(latest, used_channel) if latest else None
                output = {
                    "current_version": current,
                    "latest_version": latest,
                    "channel": used_channel,
                    "update_available": latest is not None and latest != current,
                    "release_date": version_info.release_date[:10] if version_info and version_info.release_date else None,
                    "is_prerelease": version_info.is_prerelease if version_info else False,
                    "update_command": get_update_command(latest) if latest else None,
                }
                print(_json.dumps(output, indent=2))
                return 0
            return cmd_update_check(channel)

        print("Checking for updates...")

        result = subprocess.run(
            [
                sys.executable, "-m", "pip", "index", "versions", "Zeloo",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and "Unable to find" in result.stdout:
            print("Zeloo is installed from a local package (not PyPI).")
            print("To update: git pull && pip install -e .")
            return 0

        result = subprocess.run(
            [
                sys.executable, "-m", "pip", "install", "--dry-run",
                "--upgrade", "Zeloo",
            ],
            capture_output=True,
            text=True,
        )
        if "Would upgrade" in result.stdout or "Would not" not in result.stdout:
            lines = [
                line.strip()
                for line in result.stdout.splitlines()
                if "Zeloo" in line.lower()
            ]
            if lines:
                print(f"Update available: {lines[0]}")
            else:
                print(result.stdout[:200])
        else:
            print("Zeloo is already up to date.")

        if args.check:
            return 0

        print("\nInstalling update...")
        res = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "Zeloo"],
        )
        if res.returncode == 0:
            print("Update complete!")
            return 0
        print("Update failed. Try manually: pip install --upgrade Zeloo")
        return 1
