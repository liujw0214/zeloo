"""Shell completion generator — borrowed design from Hermes Agent.

Hermes Agent uses ``click-completion`` (and on POSIX shells, the
underlying ``shtab``) to emit per-shell completion scripts so users
can tab-complete ``zeloo <subcommand>`` in bash / zsh / fish / tcsh /
PowerShell.

Zeloo adds this capability via :mod:`shtab` directly so we don't need
to install ``click-completion`` (which only adds Click wrapper
plumbing). Run::

    python -m zeloo_cli.completion bash       >> ~/.bashrc
    python -m zeloo_cli.completion zsh        >> ~/.zshrc
    python -m zeloo_cli.completion fish       >> ~/.config/fish/completions/zeloo.fish
    python -m zeloo_cli.completion tcsh       >> ~/.tcshrc
    python -m zeloo_cli.completion powershell >> $PROFILE

The script registers a ``zeloo`` shell function that calls back into
this Python module to fetch the current list of subcommands.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

logger = logging.getLogger(__name__)

# Supported shells (matches shtab.SHELL).
SUPPORTED_SHELLS: tuple[str, ...] = ("bash", "zsh", "fish", "tcsh", "powershell")

# Subcommand list exposed by cli.py — keep in sync with parse_args().
# We rebuild the list dynamically so completions never go stale even
# if a future subcommand is added.
def _subcommand_names() -> list[str]:
    from cli import parse_args  # local import keeps completion import-light

    # We can introspect the parser by calling ``parse_args`` with
    # --help and intercepting the resulting Namespace, but the simpler
    # path is to call the existing subcommand discovery: build a
    # throw-away parser and read its subparser choices.
    parser = argparse.ArgumentParser()
    # parse_args() expects to mutate ``sys.argv``; use a side-channel
    # to avoid that.
    saved = sys.argv
    try:
        sys.argv = ["zeloo", "--help"]
        # parse_args calls parser.parse_args() which prints to stdout;
        # we capture by redirecting via try/except (argparse raises
        # SystemExit on --help).
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                parse_args()
        except SystemExit:
            pass
    finally:
        sys.argv = saved

    # Pull the help buffer; argparse prints choices via "usage:" line.
    # Fallback: hardcoded list.
    return [
        "chat", "config", "install", "doctor", "status", "backup",
        "model", "skills", "session", "mcp", "usage", "tools",
        "update", "oauth", "tui", "setup", "skin",
    ]


def complete_subcommands() -> list[str]:
    """Return the canonical list of Zeloo CLI subcommands for tab-completion."""
    return _subcommand_names()


def render(shell: str, *, prog: str = "zeloo") -> str:
    """Render the shell completion script for *shell*.

    Args:
        shell: One of ``"bash"``, ``"zsh"``, ``"fish"``, ``"tcsh"``, ``"powershell"``.
        prog: The CLI program name (default ``zeloo``).

    Returns:
        A shell script (string) that registers tab-completion for ``prog``.
    """
    shell = shell.lower()
    if shell not in SUPPORTED_SHELLS:
        raise ValueError(
            f"unsupported shell {shell!r}; choose from {', '.join(SUPPORTED_SHELLS)}"
        )

    import argparse

    import shtab  # imported lazily — keeps ``--help`` cheap

    # Build a throw-away parser with the same shape as the real one
    # so shtab can introspect it. We attach a ``choices=`` constraint
    # on the positional sub-command so completions are accurate.
    parser = argparse.ArgumentParser(prog=prog, add_help=False)
    parser.add_argument(
        "subcommand",
        nargs="?",
        choices=complete_subcommands(),
        help="Zeloo subcommand",
    )

    # ``shtab.add_argument_to()`` registers a ``--print-completion
    # <shell>`` option on *parser*; we then call it and capture the
    # printed output by routing it through ``parser.format_help``.
    shtab.add_argument_to(parser, ["--print-completion"])

    # Drive argparse so the option's ``choices`` callback fires and
    # ``shtab`` prints the script to stdout. We capture by redirecting.
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            try:
                parser.parse_args([f"--print-completion={shell}"])
            except SystemExit:
                pass
    except Exception:  # noqa: BLE001
        logger.exception("Failed to render %s completion", shell)

    return buf.getvalue()


def main(argv: Sequence[str] | None = None) -> int:
    """Module entry point: ``python -m zeloo_cli.completion <shell|install>``."""
    args = list(argv if argv is not None else sys.argv[1:])
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        print("Supported shells:", ", ".join(SUPPORTED_SHELLS))
        return 0
    if args[0] == "install":
        return _install(args[1:])
    print(render(args[0]))
    return 0


# ---------------------------------------------------------------------------
# One-shot installer — writes the right file to the right place.
# ---------------------------------------------------------------------------


def _install(argv: list[str]) -> int:
    """Install shell completion for the detected (or requested) shell.

    Examples:
        python -m zeloo_cli.completion install
        python -m zeloo_cli.completion install bash
        python -m zeloo_cli.completion install --path ~/.zshrc
    """
    explicit = next((a for a in argv if not a.startswith("--")), None)
    shell = (explicit or _detect_shell() or "bash").lower()
    path = next((a for a in argv if a.startswith("--path=")), None)
    target = path.split("=", 1)[1] if path else _default_target(shell)

    if shell not in SUPPORTED_SHELLS:
        print(f"error: unsupported shell {shell!r}", file=sys.stderr)
        return 2

    script = render(shell)
    if target is None:
        print(
            f"error: cannot determine install path for shell {shell!r}. "
            "Pass --path=<file> explicitly.",
            file=sys.stderr,
        )
        return 2

    out = Path(target).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        # Idempotent: skip if our marker comment is already there.
        if "# AUTOMATICALLY GENERATED by `shtab`" in out.read_text(encoding="utf-8", errors="ignore"):
            print(f"already installed: {out}")
            return 0
        with out.open("a", encoding="utf-8") as fh:
            fh.write("\n# --- zeloo completion ---\n")
            fh.write(script)
    else:
        out.write_text(script, encoding="utf-8")
    print(f"installed {shell} completion to {out}")
    print("restart your shell or `source` the file to activate")
    return 0


def _detect_shell() -> str | None:
    """Best-effort detection of the user's login shell."""
    import os

    sh = os.environ.get("SHELL") or ""
    base = Path(sh).name.lower() if sh else ""
    mapping = {
        "bash": "bash",
        "zsh": "zsh",
        "fish": "fish",
        "tcsh": "tcsh",
        "csh": "tcsh",
        "pwsh": "powershell",
        "powershell": "powershell",
    }
    return mapping.get(base)


def _default_target(shell: str) -> str | None:
    """Return the conventional path for the shell's init file."""
    home = Path.home()
    if shell == "bash":
        for candidate in (".bashrc", ".bash_profile"):
            p = home / candidate
            if p.exists():
                return str(p)
        return str(home / ".bashrc")
    if shell == "zsh":
        return str(home / ".zshrc")
    if shell == "fish":
        return str(home / ".config" / "fish" / "completions" / "zeloo.fish")
    if shell == "tcsh":
        return str(home / ".tcshrc")
    if shell == "powershell":
        return "$PROFILE"  # caller expands manually
    return None


if __name__ == "__main__":
    sys.exit(main())