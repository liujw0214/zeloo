"""Zeloo ``logout`` subcommand — clear authentication credentials."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from zeloo_cli.subcommands import Subcommand, subcommand


@subcommand("logout")
class LogoutCmd(Subcommand):
    name = "logout"
    help = "Clear authentication credentials"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--provider",
            default=None,
            help="Clear credentials for a specific provider only",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Skip confirmation prompt",
        )

    def run(self, args: argparse.Namespace) -> int:
        provider = getattr(args, "provider", None)
        force = getattr(args, "force", False)

        auth_file = self._get_auth_file()
        env_file = self._get_env_file()

        has_auth = auth_file.exists()
        has_env = env_file.exists()

        if not has_auth and not has_env:
            print("No authentication credentials found.")
            return 0

        if not force:
            print("This will clear authentication credentials from:")
            if has_auth:
                print(f"  - {auth_file}")
            if has_env:
                print(f"  - {env_file}")
            confirm = input("\nProceed? [y/N] ")
            if confirm.lower() != "y":
                print("Cancelled.")
                return 0

        errors = []

        if has_auth:
            try:
                if provider:
                    auth_data = json.loads(auth_file.read_text(encoding="utf-8"))
                    if provider in auth_data:
                        del auth_data[provider]
                        auth_file.write_text(json.dumps(auth_data, indent=2, ensure_ascii=False), encoding="utf-8")
                        print(f"Cleared credentials for provider: {provider}")
                    else:
                        print(f"No credentials found for provider: {provider}")
                else:
                    auth_file.unlink()
                    print(f"Cleared: {auth_file}")
            except Exception as exc:
                errors.append(f"auth.json: {exc}")

        if has_env:
            try:
                env_content = env_file.read_text(encoding="utf-8")
                lines = env_content.splitlines()
                keys_to_remove = ["API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]
                if provider:
                    keys_to_remove = [f"{provider.upper()}_API_KEY"]

                new_lines = []
                removed_keys = []
                for line in lines:
                    stripped = line.strip()
                    key_part = stripped.split("=")[0] if "=" in stripped else ""
                    should_remove = any(key_part == key for key in keys_to_remove)
                    if not should_remove and stripped:
                        new_lines.append(line)
                    elif should_remove:
                        removed_keys.append(key_part)

                if removed_keys:
                    env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                    print(f"Cleared from .env: {', '.join(removed_keys)}")
                elif not provider:
                    env_file.unlink()
                    print(f"Cleared: {env_file}")
            except Exception as exc:
                errors.append(f".env: {exc}")

        if errors:
            print("\nWarnings:")
            for err in errors:
                print(f"  - {err}")
            return 1

        print("\nLogout complete.")
        return 0

    def _get_zeloo_home(self) -> Path:
        val = os.environ.get("ZELOO_HOME", "").strip()
        if val:
            return Path(val)
        if sys.platform == "win32":
            local = os.environ.get("LOCALAPPDATA", "").strip()
            base = Path(local) if local else Path.home() / "AppData" / "Local"
            return base / "Zeloo"
        return Path.home() / ".Zeloo"

    def _get_auth_file(self) -> Path:
        return self._get_zeloo_home() / "auth.json"

    def _get_env_file(self) -> Path:
        return self._get_zeloo_home() / ".env"
