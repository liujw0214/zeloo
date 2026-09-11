"""Zeloo init subcommand — bootstrap a project with Zeloo configuration.

Creates a ``.zeloo/`` directory in the current working directory
containing:

* ``config.yaml`` — minimal provider/model defaults.
* ``memory/``    — empty long-term memory directory.
* ``skills/``    — empty skills directory.

Flags:

* ``--provider``  — default provider (e.g. ``openai``).
* ``--model``     — default model (e.g. ``gpt-4o-mini``).
* ``--workspace`` — also create a ``workspace/`` directory.
* ``--template``  — use a named template (free-form hook for future
  extension).
* ``--yes``       — skip interactive confirmation.
* ``--force``     — overwrite an existing ``.zeloo/`` directory.
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from zeloo_cli.rich_render import make_console, make_table
from zeloo_cli.subcommands import Subcommand, subcommand

logger = logging.getLogger(__name__)


@subcommand("init")
class InitCommand(Subcommand):
    """Subcommand entry point for bootstrapping a Zeloo project."""

    name = "init"
    help = "Initialize Zeloo configuration in the current directory"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Attach init flags to *parser*."""
        parser.add_argument("--provider", default=None, help="Default provider name")
        parser.add_argument("--model", default=None, help="Default model name")
        parser.add_argument(
            "--workspace", action="store_true",
            help="Also create a workspace/ directory",
        )
        parser.add_argument(
            "--template", default=None,
            help="Template name (free-form hook)",
        )
        parser.add_argument("--yes", action="store_true", help="Skip prompts")
        parser.add_argument(
            "--force", action="store_true",
            help="Overwrite an existing .zeloo/ directory",
        )
        parser.add_argument(
            "--target", default=".",
            help="Target directory (defaults to current working directory)",
        )

    def run(self, args: argparse.Namespace) -> int:
        """Create ``.zeloo/`` and write a minimal ``config.yaml``."""
        target_dir = Path(args.target).expanduser().resolve()
        zeloo_dir = target_dir / ".zeloo"

        console = make_console()
        if zeloo_dir.exists() and not args.force:
            console.print(
                f"[yellow]Note:[/yellow] '{zeloo_dir}' already exists. "
                "Re-run with --force to overwrite."
            )
            return 1

        if not args.yes and not _confirm(
            f"Initialize Zeloo in '{target_dir}'?",
        ):
            console.print("[yellow]Aborted by user.[/yellow]")
            return 1

        zeloo_dir.mkdir(parents=True, exist_ok=True)
        (zeloo_dir / "memory").mkdir(exist_ok=True)
        (zeloo_dir / "skills").mkdir(exist_ok=True)

        config = _build_config(
            provider=args.provider,
            model=args.model,
            template=args.template,
        )
        _write_yaml(zeloo_dir / "config.yaml", config)

        if args.workspace:
            (target_dir / "workspace").mkdir(exist_ok=True)

        table = make_table(
            title=f"Initialized Zeloo in {target_dir}",
            columns=[("Path", "bold cyan"), ("Kind", "white")],
        )
        table.add_row(".zeloo/", "directory")
        table.add_row(".zeloo/config.yaml", "file")
        table.add_row(".zeloo/memory/", "directory")
        table.add_row(".zeloo/skills/", "directory")
        if args.workspace:
            table.add_row("workspace/", "directory")
        console.print(table)
        console.print("[green]✓[/green] Run [bold]Zeloo doctor[/bold] to verify.")
        return 0


def _confirm(prompt: str) -> bool:
    """Prompt the user for a yes/no confirmation."""
    try:
        answer = input(f"{prompt} [y/N] ").strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}


def _build_config(
    *,
    provider: str | None,
    model: str | None,
    template: str | None,
) -> dict[str, Any]:
    """Build the minimal config dict for a fresh ``.zeloo/config.yaml``."""
    config: dict[str, Any] = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": provider or "openai",
        "model": model or "gpt-4o-mini",
        "memory": {"path": "memory/"},
        "skills": {"path": "skills/"},
    }
    if template:
        config["template"] = template
    return config


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Serialize *data* as YAML to *path*, falling back to JSON if needed."""
    try:
        import yaml  # type: ignore[import-untyped]
        serialized = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    except ImportError:
        import json
        logger.warning("PyYAML not installed; serializing config as JSON")
        serialized = json.dumps(data, indent=2, ensure_ascii=False)
    path.write_text(serialized, encoding="utf-8")


def run(args: argparse.Namespace) -> int:  # pragma: no cover - thin wrapper
    """Programmatic entry point for the ``init`` subcommand."""
    return InitCommand().run(args)


__all__ = ["InitCommand", "run"]