"""Zeloo repair subcommand — repair a Zeloo installation in place.

Provides four repair primitives plus an ``--all`` convenience flag:

* ``--venv``         — recreate the ``.venv`` virtual environment.
* ``--deps``         — reinstall every pinned dependency from the lock.
* ``--permissions``  — normalize file permissions on ``~/.zeloo`` and
  the active workspace.
* ``--config``       — regenerate ``config.yaml`` from the bundled
  defaults while preserving user values when possible.
* ``--all``          — run all four in order.

Each step reports its outcome via rich and never raises — failures are
recorded and bubble back as a non-zero exit code so the caller can act
on them.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

from zeloo_cli.rich_render import make_console, make_table
from zeloo_cli.subcommands import Subcommand, subcommand

logger = logging.getLogger(__name__)


@subcommand("repair")
class RepairCommand(Subcommand):
    """Subcommand entry point for installation repair."""

    name = "repair"
    help = "Repair Zeloo installation (venv, deps, permissions, config)"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Attach repair flags to *parser*."""
        parser.add_argument("--venv", action="store_true", help="Repair virtual environment")
        parser.add_argument("--deps", action="store_true", help="Reinstall dependencies")
        parser.add_argument(
            "--permissions", action="store_true", help="Fix file permissions",
        )
        parser.add_argument("--config", action="store_true", help="Reset config")
        parser.add_argument("--all", action="store_true", help="Run every repair")
        parser.add_argument("--dry-run", action="store_true", help="Preview only")
        parser.add_argument(
            "--zeloo-home", default=None,
            help="Override ZELOO_HOME directory",
        )

    def run(self, args: argparse.Namespace) -> int:
        """Execute the requested repair steps in a fixed, safe order."""
        steps: list[tuple[str, Callable[[], bool]]] = []
        if args.all or args.venv:
            steps.append(("venv", lambda: self._repair_venv(args)))
        if args.all or args.deps:
            steps.append(("deps", lambda: self._repair_deps(args)))
        if args.all or args.permissions:
            steps.append(("permissions", lambda: self._repair_permissions(args)))
        if args.all or args.config:
            steps.append(("config", lambda: self._repair_config(args)))

        if not steps:
            console = make_console()
            console.print(
                "[yellow]Usage:[/yellow] Zeloo repair "
                "[--venv|--deps|--permissions|--config|--all]"
            )
            return 1

        console = make_console()
        console.print(
            f"[bold]Running {len(steps)} repair step(s)[/bold]"
            + (" [yellow](dry-run)[/yellow]" if args.dry_run else "")
        )

        failures = 0
        for label, fn in steps:
            console.print(f"  → [cyan]{label}[/cyan] ...", end=" ")
            try:
                ok = fn()
            except Exception as exc:  # noqa: BLE001
                logger.exception("Repair step %s crashed", label)
                console.print(f"[red]crashed: {exc}[/red]")
                failures += 1
                continue
            console.print("[green]ok[/green]" if ok else "[red]failed[/red]")
            if not ok:
                failures += 1

        if failures:
            console.print(f"[red]✗ {failures} step(s) failed.[/red]")
            return 1
        console.print("[green]✓ All repair steps completed.[/green]")
        return 0

    # ----- repair primitives ------------------------------------------

    def _repair_venv(self, args: argparse.Namespace) -> bool:
        """Recreate ``.venv`` next to the active workspace."""
        target = _zeloo_home(args) / ".venv"
        if args.dry_run:
            return True
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        cmd = [sys.executable, "-m", "venv", str(target)]
        return _run(cmd)

    def _repair_deps(self, args: argparse.Namespace) -> bool:
        """Reinstall every pinned dependency using the active ``pip``."""
        if args.dry_run:
            return True
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "-r", "requirements.lock"]
        return _run(cmd)

    def _repair_permissions(self, args: argparse.Namespace) -> bool:
        """Normalize file permissions under ``zeloo_home``."""
        home = _zeloo_home(args)
        if not home.exists():
            return True
        if args.dry_run:
            return True
        for path in home.rglob("*"):
            try:
                if path.is_file():
                    path.chmod(0o644)
                elif path.is_dir():
                    path.chmod(0o755)
            except OSError as exc:
                logger.warning("Could not chmod %s: %s", path, exc)
        return True

    def _repair_config(self, args: argparse.Namespace) -> bool:
        """Regenerate ``config.yaml`` from defaults (preserving values)."""
        from zeloo_cli.subcommands.config import ConfigCommand  # noqa: WPS433
        cfg_path = _zeloo_home(args) / "config.yaml"
        if args.dry_run:
            return True
        if not cfg_path.exists():
            # Nothing to repair — fresh install will produce defaults.
            return True
        # Trigger the existing ``config init`` flow.
        return ConfigCommand().run(
            argparse.Namespace(config_action="init", config_path=str(cfg_path)),
        )


def _zeloo_home(args: argparse.Namespace) -> Path:
    """Resolve the Zeloo home directory from ``args.zeloo_home`` or env."""
    import os

    raw = getattr(args, "zeloo_home", None) or os.environ.get("ZELOO_HOME")
    return Path(raw).expanduser() if raw else Path.home() / ".zeloo"


def _run(cmd: list[str]) -> bool:
    """Run *cmd* and return True iff it exited with status 0."""
    try:
        completed = subprocess.run(cmd, check=False)
    except FileNotFoundError as exc:
        logger.error("Command not found: %s (%s)", cmd, exc)
        return False
    return completed.returncode == 0


def run(args: argparse.Namespace) -> int:  # pragma: no cover - thin wrapper
    """Programmatic entry point for the ``repair`` subcommand."""
    return RepairCommand().run(args)


__all__ = ["RepairCommand", "run"]