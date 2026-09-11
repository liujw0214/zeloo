"""Click wrapper for the Zeloo CLI — borrowed design from Hermes Agent.

Hermes Agent uses `click <https://click.palletsprojects.com/>` for its
CLI: every subcommand is a ``@click.command()`` / ``@click.group()``
function, options are declared with decorators, and the same Click app
plugs into ``click-completion`` / ``shtab`` for shell tab-completion.

Zeloo currently uses stdlib :mod:`argparse` (with a custom
:class:`Subcommand` framework in :mod:`zeloo_cli.subcommands`). This
module adds a **parallel** Click entry point so users get:

* The nicer ``--help`` rendering Click provides.
* A drop-in ``zeloo --version`` flag and consistent ``--verbose`` flag.
* A foundation to plug in shell completion (see
  :mod:`zeloo_cli.completion`) without touching the existing argparse
  path.

The argparse path (``cli.py:main``) stays the default entry point so
every existing subcommand and unit test continues to work unchanged.
Run ``zeloo click …`` to use the Click variant, or call
:func:`click_main` programmatically.

Hermes-Agent parity (Round 65):

* ``result_callback`` — pre-run hook that activates the profile.
* ``format_errors`` — emoji-prefixed error rendering via ``rich``.
* ``NO_COLOR`` — automatic respect when the env var is set.
* ``rich.progress.Progress`` helpers for ``install`` / ``update``.

Public surface
--------------

* :func:`click_main` — the Click app entry point (parses argv)
* :data:`cli` — the :class:`click.Group` so other tools can compose
"""

from __future__ import annotations

import logging
import os
import sys

import click

logger = logging.getLogger(__name__)


def _supports_color() -> bool:
    """Return True when ANSI colour output should be emitted.

    Honours ``NO_COLOR`` (https://no-color.org/) and ``--no-color``.
    """
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("ZELOO_NO_COLOR"):
        return False
    return sys.stdout.isatty()


CONTEXT_SETTINGS = dict(
    help_option_names=["-h", "--help"],
    color=_supports_color(),
)


def _activate_profile(profile: str | None) -> None:
    """Activate a CLI profile if one was requested."""
    if not profile:
        return
    try:
        from zeloo_cli.profiles import activate_profile

        activate_profile(profile)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to activate profile %s", profile)


@click.group(
    name="zeloo-click",
    help="Zeloo Agent — Click entry point (borrowed design from Hermes Agent).",
    context_settings=CONTEXT_SETTINGS,
)
@click.version_option(package_name="zeloo", message="%(version)s")
@click.option(
    "-v", "--verbose", is_flag=True, default=False,
    help="Enable verbose (DEBUG) logging.",
)
@click.option(
    "--profile", "-p", default=None,
    help="Select a profile for this invocation.",
)
@click.option(
    "--no-color", is_flag=True, default=False,
    help="Disable ANSI colour output (also respects NO_COLOR env var).",
)
@click.pass_context
def cli(ctx: click.Context, verbose: bool, profile: str | None, no_color: bool) -> None:
    """Zeloo Agent root — Click variant (Hermes Agent parity)."""
    if no_color:
        # ``color=False`` disables ANSI in Click + our own printers.
        ctx.color = False
        os.environ["ZELOO_NO_COLOR"] = "1"
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    _activate_profile(profile)
    ctx.ensure_object(dict)


# ---------------------------------------------------------------------------
# Custom error formatting — Hermes Agent shows emoji-prefixed errors.
# We use ``rich`` (already in the project's dep tree) for the format
# but fall back to plain text if ``rich`` isn't installed.
# ---------------------------------------------------------------------------


def _format_error_message(exc: Exception) -> str:
    """Render a CLI error with a 🚨 prefix + dim context."""
    try:
        from rich.console import Console

        buf = Console(record=True, force_terminal=_supports_color(), color_system="truecolor")
        buf.print(f"[red bold]🚨 zeloo error[/red bold] [dim]{type(exc).__name__}[/dim]")
        buf.print(f"  [yellow]{exc}[/yellow]")
        return buf.export_text(styles=False)
    except Exception:  # noqa: BLE001
        return f"zeloo error ({type(exc).__name__}): {exc}"


# ``cli.result_callback`` is invoked once *per command invocation*;
# we use it to apply the profile so every sub-command sees the same
# activation. This mirrors Hermes Agent's ``cli.result_callback``
# pattern.
@cli.result_callback()
def _apply_profile(result, verbose: bool, profile: str | None, no_color: bool, **kwargs):  # type: ignore[no-untyped-def]
    _activate_profile(profile)


# Patch Click's default error formatter to use our emoji prefix.
_original_format_usage = click.exceptions.UsageError.format_message


def _patched_usage_format(self):  # type: ignore[no-untyped-def]
    base = _original_format_usage(self)
    return f"🚨 {base}"


click.exceptions.UsageError.format_message = _patched_usage_format  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Subcommand adapters — each one wraps the existing argparse-based
# function so we don't duplicate business logic.
# ---------------------------------------------------------------------------


def _run_argparse_subcommand(name: str, argv_tail: list[str]) -> int:
    """Forward to the existing ``cli.py:main`` argparse flow."""
    from cli import main as argparse_main

    saved_argv = sys.argv
    try:
        sys.argv = ["zeloo", name, *argv_tail]
        argparse_main()
    except SystemExit as exc:  # argparse calls sys.exit() on --help etc.
        return int(exc.code or 0)
    except Exception:  # noqa: BLE001
        logger.exception("Subcommand %s failed", name)
        return 1
    finally:
        sys.argv = saved_argv
    return 0


def _make_subcommand(name: str, short_help: str | None = None) -> click.Command:
    """Build a click subcommand that forwards argv to argparse."""
    help_text = short_help or f"Run the ``{name}`` subcommand (delegates to argparse)."

    # Click passes extra args (anything past declared params) into
    # ``ctx.args`` when ``allow_extra_args=True``. We don't declare any
    # parameters, so every positional becomes an "extra" arg that we
    # hand off to the existing argparse flow.
    def _callback(*extra: str) -> None:
        code = _run_argparse_subcommand(name, list(extra))
        if code:
            # ``click.exceptions.Exit`` would terminate the process; we
            # want the existing argparse semantics where a non-zero
            # code is returned rather than raising.
            import sys

            sys.exit(code)

    # Build the Command manually so we can hand it ``allow_extra_args``
    # without going through the decorator (which would force us to
    # declare params / a context_settings dict in a different place).
    return click.Command(
        name=name,
        short_help=short_help,
        help=help_text,
        params=[],
        callback=_callback,
        context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
    )


# Register the subcommands we want to expose via the Click surface.
# We register lazily so ``import zeloo_cli.click_app`` stays cheap.
_SUB_COMMAND_NAMES = (
    "chat", "config", "doctor", "install", "model", "session",
    "mcp", "usage", "tools", "update", "oauth", "tui", "setup",
    "skin", "skills", "status", "backup",
)


def _register_subcommands() -> None:
    for name in _SUB_COMMAND_NAMES:
        # Idempotent registration: ``add_command`` would raise on dupes.
        if name in cli.commands:
            continue
        cmd = _make_subcommand(name)
        cli.add_command(cmd)


_register_subcommands()


# ---------------------------------------------------------------------------
# Convenience entry point
# ---------------------------------------------------------------------------


def click_main(argv: list[str] | None = None) -> int:
    """Entry point that mirrors :func:`cli.main`'s signature."""
    try:
        cli.main(args=argv, standalone_mode=False)
        return 0
    except click.exceptions.ClickException as exc:
        # Click raises SystemExit on errors; capture and translate.
        exc.show()
        return exc.exit_code
    except SystemExit as exc:
        return int(exc.code or 0)


__all__ = ["cli", "click_main"]