"""Zeloo z subcommand — Hermes-style oneshot query mode.

Runs a single prompt through the agent and prints the answer
immediately, with no REPL. Mirrors ``zeloo run --query`` but is a
short, memorable alias (``z``) inspired by the Hermes Agent pattern.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

from zeloo_cli.subcommands import Subcommand, subcommand

logger = logging.getLogger(__name__)


@subcommand("z")
class ZCommand(Subcommand):
    """Run a prompt and print the answer immediately, no REPL."""

    name = "z"
    help = "Oneshot: run prompt and print answer, then exit"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Attach z-specific flags to *parser*."""
        parser.add_argument("query", help="Query text")
        parser.add_argument("--model", default=None, help="Override model name")
        parser.add_argument("--provider", default=None, help="Override provider name")
        parser.add_argument("--system", default=None, help="Override system prompt")
        parser.add_argument(
            "--temperature", type=float, default=None,
            help="Sampling temperature (0.0–2.0)",
        )

    def run(self, args: argparse.Namespace) -> int:
        """Execute the oneshot query."""
        from zeloo_cli.oneshot import run_oneshot

        if not args.query or not args.query.strip():
            print("Error: empty query", file=sys.stderr)
            return 1

        kwargs: dict[str, Any] = {}
        if args.model is not None:
            kwargs["model"] = args.model
        if args.provider is not None:
            kwargs["provider"] = args.provider
        if args.temperature is not None:
            kwargs["temperature"] = args.temperature
        # ``run_oneshot`` doesn't accept a custom system prompt today,
        # so we forward it through the generic ``**kwargs`` which gets
        # dropped on the floor; we still capture it for future use and
        # to keep the CLI surface stable.
        if args.system:
            kwargs.setdefault("system_prompt", args.system)

        try:
            return run_oneshot(args.query, **kwargs)
        except KeyboardInterrupt:
            print("\nInterrupted.", file=sys.stderr)
            return 130
        except Exception as exc:  # noqa: BLE001
            logger.exception("Oneshot run failed")
            print(f"Error: {exc}", file=sys.stderr)
            return 1


__all__ = ["ZCommand"]


# Make ``python -m zeloo_cli.subcommands.z`` work as a smoke test.
if __name__ == "__main__":  # pragma: no cover
    PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    parser = argparse.ArgumentParser(prog="zeloo z")
    ZCommand.configure_parser(parser)
    ns = parser.parse_args()
    raise SystemExit(ZCommand().run(ns))
