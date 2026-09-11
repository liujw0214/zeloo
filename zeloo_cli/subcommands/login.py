"""Zeloo ``login`` subcommand — deprecated login command."""

from __future__ import annotations

import argparse
import sys

from zeloo_cli.subcommands import Subcommand, subcommand


@subcommand("login")
class LoginCmd(Subcommand):
    name = "login"
    help = "Interactive login (deprecated — use auth login)"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, args: argparse.Namespace) -> int:
        print("=" * 60)
        print("  DEPRECATED: 'zeloo login' is deprecated")
        print("=" * 60)
        print()
        print("  This command will be removed in a future version.")
        print()
        print("  Instead, use one of the following:")
        print()
        print("    zeloo auth login     # Interactive authentication")
        print("    zeloo setup          # First-time setup wizard")
        print()
        print("  For manual API key configuration:")
        print("    1. Edit ~/.Zeloo/.env")
        print("    2. Add: API_KEY=your_api_key_here")
        print()
        print("=" * 60)
        return 1
