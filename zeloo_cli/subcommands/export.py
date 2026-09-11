"""Zeloo export subcommand — dump workspace state to a JSON file.

Collects one or more workspace components and writes them to a
single JSON document:

* ``--config``    — ``config.yaml`` (parsed into a dict).
* ``--sessions``  — every ``sessions/*.json`` transcript.
* ``--memory``    — ``memory/MEMORY.md`` and ``memory/USER.md``.
* ``--all``       — export every supported component.

The output is a JSON object with one top-level key per exported
component. ``--pretty`` enables indented JSON for human readability.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from zeloo_cli.rich_render import make_console, make_table
from zeloo_cli.subcommands import Subcommand, subcommand

logger = logging.getLogger(__name__)


@subcommand("export")
class ExportCommand(Subcommand):
    """Subcommand entry point for exporting workspace data."""

    name = "export"
    help = "Export configuration/sessions/memory to a JSON file"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Attach export flags to *parser*."""
        parser.add_argument("output", help="Output file path (JSON)")
        parser.add_argument("--config", action="store_true", help="Export config")
        parser.add_argument("--sessions", action="store_true", help="Export sessions")
        parser.add_argument("--memory", action="store_true", help="Export memory")
        parser.add_argument("--all", action="store_true", help="Export everything")
        parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
        parser.add_argument(
            "--zeloo-home", default=None,
            help="Override ZELOO_HOME directory",
        )

    def run(self, args: argparse.Namespace) -> int:
        """Collect the requested sections and write the export file."""
        select_all = args.all
        want_config = select_all or args.config
        want_sessions = select_all or args.sessions
        want_memory = select_all or args.memory

        if not (want_config or want_sessions or want_memory):
            console = make_console()
            console.print(
                "[yellow]Usage:[/yellow] Zeloo export <output> "
                "[--config|--sessions|--memory|--all]"
            )
            return 1

        home = _zeloo_home(args)
        payload: dict[str, Any] = {
            "meta": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "zeloo_home": str(home),
                "version": _zeloo_version(),
            },
        }

        if want_config:
            payload["config"] = _read_yaml(home / "config.yaml")
        if want_sessions:
            payload["sessions"] = _collect_sessions(home / "sessions")
        if want_memory:
            payload["memory"] = _collect_memory(home / "memory")

        target = Path(args.output).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        indent = 2 if args.pretty else None
        target.write_text(json.dumps(payload, indent=indent, ensure_ascii=False), encoding="utf-8")

        console = make_console()
        table = make_table(
            title=f"Export → {target.name}",
            columns=[("Component", "bold cyan"), ("Records", "white")],
        )
        for key, value in payload.items():
            if key == "meta":
                continue
            count = len(value) if isinstance(value, (list, dict)) else 1
            table.add_row(key, str(count))
        console.print(table)
        console.print(f"[green]✓[/green] Wrote [bold]{target}[/bold]")
        return 0


def _zeloo_home(args: argparse.Namespace) -> Path:
    """Resolve the Zeloo home directory from ``args.zeloo_home`` or env."""
    import os

    raw = getattr(args, "zeloo_home", None) or os.environ.get("ZELOO_HOME")
    return Path(raw).expanduser() if raw else Path.home() / ".zeloo"


def _zeloo_version() -> str:
    """Best-effort lookup of the Zeloo runtime version."""
    try:
        from zeloo import __version__  # type: ignore[attr-defined]
        return str(__version__)
    except Exception:  # noqa: BLE001
        return "unknown"


def _read_yaml(path: Path) -> dict[str, Any]:
    """Parse a YAML file into a dict, returning ``{}`` on failure."""
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("PyYAML not installed; skipping %s", path)
        return {"_error": "PyYAML not installed"}
    try:
        with path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("Could not parse %s: %s", path, exc)
        return {"_error": str(exc)}
    return loaded if isinstance(loaded, dict) else {"_value": loaded}


def _collect_sessions(folder: Path) -> list[dict[str, Any]]:
    """Read every ``*.json`` session under *folder* into a list."""
    if not folder.exists():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.json")):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Bad session file %s: %s", path, exc)
            out.append({"_file": str(path), "_error": str(exc)})
    return out


def _collect_memory(folder: Path) -> dict[str, str]:
    """Read the canonical ``MEMORY.md`` / ``USER.md`` files if present."""
    if not folder.exists():
        return {}
    out: dict[str, str] = {}
    for name in ("MEMORY.md", "USER.md"):
        path = folder / name
        if path.exists():
            out[name] = path.read_text(encoding="utf-8")
    return out


def run(args: argparse.Namespace) -> int:  # pragma: no cover - thin wrapper
    """Programmatic entry point for the ``export`` subcommand."""
    return ExportCommand().run(args)


__all__ = ["ExportCommand", "run"]