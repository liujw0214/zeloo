"""Zeloo reset subcommand — reset workspace component state.

Provides per-component reset primitives plus an ``--all`` convenience
flag. Each primitive removes the corresponding state under the active
Zeloo home (``config/`, `cache/`, `memory/`, `sessions/``) and
optionally takes a backup first via ``--backup``.

Supported components:

* ``--config``    — drop ``config.yaml`` (the user is re-prompted on
  the next launch).
* ``--cache``     — purge ``cache/`` (compiled artefacts, HTTP caches).
* ``--memory``    — drop ``memory/`` (long-term knowledge store).
* ``--sessions``  — drop ``sessions/`` (interactive session transcripts).
* ``--all``       — reset every component above.

``--yes`` skips the confirmation prompt; ``--backup`` writes a
timestamped ``.tar.zst`` snapshot before removing anything.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
import shutil
import tarfile
from pathlib import Path
from typing import Callable

from zeloo_cli.rich_render import make_console, make_table
from zeloo_cli.subcommands import Subcommand, subcommand

logger = logging.getLogger(__name__)


@subcommand("reset")
class ResetCommand(Subcommand):
    """Subcommand entry point for workspace state reset."""

    name = "reset"
    help = "Reset Zeloo workspace state (config/cache/memory/sessions/all)"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Attach reset flags to *parser*."""
        parser.add_argument("--config", action="store_true", help="Reset config")
        parser.add_argument("--cache", action="store_true", help="Purge cache")
        parser.add_argument("--memory", action="store_true", help="Reset memory")
        parser.add_argument("--sessions", action="store_true", help="Drop sessions")
        parser.add_argument("--all", action="store_true", help="Reset every component")
        parser.add_argument("--yes", action="store_true", help="Skip confirmation")
        parser.add_argument(
            "--backup", action="store_true",
            help="Snapshot components into a .tar.zst archive before reset",
        )
        parser.add_argument(
            "--zeloo-home", default=None,
            help="Override ZELOO_HOME directory",
        )

    def run(self, args: argparse.Namespace) -> int:
        """Confirm (unless ``--yes``) and execute the selected resets."""
        components: list[tuple[str, Callable[[], None]]] = []
        if args.all or args.config:
            components.append(("config", lambda: _reset_dir(_zeloo_home(args) / "config")))
        if args.all or args.cache:
            components.append(("cache", lambda: _reset_dir(_zeloo_home(args) / "cache")))
        if args.all or args.memory:
            components.append(("memory", lambda: _reset_dir(_zeloo_home(args) / "memory")))
        if args.all or args.sessions:
            components.append(("sessions", lambda: _reset_dir(_zeloo_home(args) / "sessions")))

        if not components:
            console = make_console()
            console.print(
                "[yellow]Usage:[/yellow] Zeloo reset "
                "[--config|--cache|--memory|--sessions|--all]"
            )
            return 1

        console = make_console()
        console.print(
            f"[bold]Reset plan:[/bold] {len(components)} component(s)"
        )
        for label, _ in components:
            console.print(f"  • [cyan]{label}[/cyan]")

        if not args.yes and not _confirm("Proceed with reset?"):
            console.print("[yellow]Aborted by user.[/yellow]")
            return 1

        if args.backup:
            archive = _backup_components(args, [name for name, _ in components])
            if archive is not None:
                console.print(f"[green]✓[/green] Backed up to [bold]{archive}[/bold]")
            else:
                console.print("[yellow]Nothing to back up.[/yellow]")

        failures = 0
        for label, fn in components:
            try:
                fn()
            except OSError as exc:
                logger.error("Reset of %s failed: %s", label, exc)
                failures += 1
                continue
            console.print(f"[green]✓[/green] Reset [bold]{label}[/bold]")

        if failures:
            console.print(f"[red]✗ {failures} component(s) failed.[/red]")
            return 1
        console.print("[green]✓ Reset complete.[/green]")
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


def _reset_dir(path: Path) -> None:
    """Delete *path* if it exists, then recreate it empty."""
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _backup_components(args: argparse.Namespace, components: list[str]) -> Path | None:
    """Snapshot the requested components into a single ``.tar.zst`` archive."""
    home = _zeloo_home(args)
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = home / f"archive" / f"reset_{stamp}.tar.gz"

    sources = [home / name for name in components if (home / name).exists()]
    if not sources:
        return None

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "w:gz") as tar:
        for source in sources:
            tar.add(source, arcname=source.name)
    return archive_path


def run(args: argparse.Namespace) -> int:  # pragma: no cover - thin wrapper
    """Programmatic entry point for the ``reset`` subcommand."""
    return ResetCommand().run(args)


__all__ = ["ResetCommand", "run"]