"""Zeloo import subcommand — restore data from an export file.

Inverse of ``export``. Reads a JSON document produced by
``Zeloo export`` and writes the requested sections back to the
active Zeloo home directory.

Components: ``--config`` (write ``config.yaml``),
``--sessions`` (restore ``sessions/*.json``), ``--memory``
(restore ``MEMORY.md`` / ``USER.md``). ``--merge`` keeps existing
files; ``--replace`` first wipes the destination. ``--yes`` skips
the interactive confirmation prompt.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from zeloo_cli.rich_render import make_console, make_table
from zeloo_cli.subcommands import Subcommand, subcommand

logger = logging.getLogger(__name__)


@subcommand("import")
class ImportCommand(Subcommand):
    """Subcommand entry point for restoring workspace data."""

    name = "import"
    help = "Import data from a Zeloo export file"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Attach import flags to *parser*."""
        parser.add_argument("input", help="Input file path (JSON)")
        parser.add_argument("--config", action="store_true", help="Import config")
        parser.add_argument("--sessions", action="store_true", help="Import sessions")
        parser.add_argument("--memory", action="store_true", help="Import memory")
        parser.add_argument("--merge", action="store_true", help="Merge with existing data")
        parser.add_argument("--replace", action="store_true", help="Replace existing data")
        parser.add_argument("--yes", action="store_true", help="Skip confirmation")
        parser.add_argument(
            "--zeloo-home", default=None,
            help="Override ZELOO_HOME directory",
        )

    def run(self, args: argparse.Namespace) -> int:
        """Load the export file and restore the requested components."""
        source = Path(args.input).expanduser().resolve()
        console = make_console()
        if not source.exists():
            console.print(f"[red]Error:[/red] input file '{source}' not found")
            return 1
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            console.print(f"[red]Error:[/red] invalid JSON: {exc}")
            return 1
        if not isinstance(payload, dict):
            console.print("[red]Error:[/red] export payload must be a JSON object")
            return 1

        select_all = not (args.config or args.sessions or args.memory)
        want_config = select_all or args.config
        want_sessions = select_all or args.sessions
        want_memory = select_all or args.memory

        if args.merge and args.replace:
            console.print("[red]Error:[/red] --merge and --replace are mutually exclusive")
            return 1
        if not args.yes and (args.replace or args.sessions) and not _confirm(
            f"Apply import from '{source.name}'?",
        ):
            console.print("[yellow]Aborted by user.[/yellow]")
            return 1

        home = _zeloo_home(args)
        summary: list[tuple[str, int]] = []
        if want_config and "config" in payload:
            summary.append(("config", _write_config(home / "config.yaml", payload["config"], args.replace)))
        if want_sessions and "sessions" in payload:
            summary.append(("sessions", _write_sessions(home / "sessions", payload["sessions"], args.replace)))
        if want_memory and "memory" in payload:
            summary.append(("memory", _write_memory(home / "memory", payload["memory"], args.replace)))

        if not summary:
            console.print("[yellow]Nothing imported — no matching components.[/yellow]")
            return 0
        table = make_table(
            title=f"Import ← {source.name}",
            columns=[("Component", "bold cyan"), ("Records", "white")],
        )
        for name, count in summary:
            table.add_row(name, str(count))
        console.print(table)
        console.print("[green]✓[/green] Import complete.")
        return 0


def _zeloo_home(args: argparse.Namespace) -> Path:
    """Resolve the Zeloo home directory from ``args.zeloo_home`` or env."""
    import os

    raw = getattr(args, "zeloo_home", None) or os.environ.get("ZELOO_HOME")
    return Path(raw).expanduser() if raw else Path.home() / ".zeloo"


def _confirm(prompt: str) -> bool:
    """Prompt the user for a yes/no confirmation."""
    try:
        answer = input(f"{prompt} [y/N] ").strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}


def _write_config(path: Path, data: Any, replace: bool) -> int:
    """Persist *data* to *path* as YAML, returning the number of keys written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and replace:
        path.unlink()
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("PyYAML not installed; cannot restore config")
        return 0
    try:
        path.write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    except (OSError, yaml.YAMLError) as exc:
        logger.error("Could not write %s: %s", path, exc)
        return 0
    return len(data) if isinstance(data, dict) else 1


def _write_sessions(folder: Path, data: list[dict[str, Any]], replace: bool) -> int:
    """Write each session dict to a numbered JSON file under *folder*."""
    if not isinstance(data, list):
        logger.warning("'sessions' payload is not a list; skipping")
        return 0
    folder.mkdir(parents=True, exist_ok=True)
    if replace:
        for existing in folder.glob("*.json"):
            try:
                existing.unlink()
            except OSError:
                pass
    written = 0
    for index, session in enumerate(data):
        target = folder / f"imported_{index:04d}.json"
        try:
            target.write_text(
                json.dumps(session, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Could not write %s: %s", target, exc)
            continue
        written += 1
    return written


def _write_memory(folder: Path, data: dict[str, str], replace: bool) -> int:
    """Write each ``memory/*.md`` entry back to disk."""
    if not isinstance(data, dict):
        logger.warning("'memory' payload is not a dict; skipping")
        return 0
    folder.mkdir(parents=True, exist_ok=True)
    written = 0
    for name, content in data.items():
        if not name.endswith(".md"):
            continue
        target = folder / name
        if target.exists() and not replace:
            continue
        try:
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not write %s: %s", target, exc)
            continue
        written += 1
    return written


def run(args: argparse.Namespace) -> int:  # pragma: no cover - thin wrapper
    """Programmatic entry point for the ``import`` subcommand."""
    return ImportCommand().run(args)


__all__ = ["ImportCommand", "run"]