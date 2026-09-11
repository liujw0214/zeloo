"""Rich-based rendering helpers — Hermes Agent parity for CLI output.

Borrowed design from Hermes Agent's ``rich_console.py`` (the
project renders tables, progress bars, and tagged status lines
through rich). Zeloo's CLI currently emits ``print()`` strings, which
works but is harder to parse visually. This module exposes thin
wrappers so we can adopt rich rendering incrementally without
breaking existing string output.
"""

from __future__ import annotations

import os
from typing import Any, Iterable

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

# Honor NO_COLOR / our internal ZELOO_NO_COLOR.
_NO_COLOR = bool(os.environ.get("NO_COLOR") or os.environ.get("ZELOO_NO_COLOR"))


def make_console(*, file: Any = None) -> Console:
    """Return a configured :class:`rich.console.Console`.

    Honors ``NO_COLOR`` / ``ZELOO_NO_COLOR`` env vars and forces
    terminal output when stdout is not a TTY (so CI logs still see
    ANSI when explicitly enabled).
    """
    return Console(
        file=file,
        force_terminal=not _NO_COLOR,
        color_system="truecolor",
    )


def make_progress(*, transient: bool = True) -> Progress:
    """Return a configured :class:`rich.progress.Progress`.

    Hermes Agent uses the same column layout for ``install`` / ``update``:
    spinner + text + bar + time-elapsed.
    """
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        transient=transient,
        console=make_console(),
    )


def make_table(
    title: str | None = None,
    columns: Iterable[tuple[str, str]] | None = None,
    *,
    show_lines: bool = False,
) -> Table:
    """Return a configured :class:`rich.table.Table`.

    ``columns`` is an iterable of ``(header, style_or_justify)`` tuples
    — same convention Hermes Agent uses for table renderers.
    """
    table = Table(title=title, show_lines=show_lines, header_style="bold")
    for header, style in columns or []:
        table.add_column(header, style=style)
    return table


def render_keyvalue(pairs: Iterable[tuple[str, str]]) -> None:
    """Render a key/value list as a rich table (Hermes Agent style)."""
    table = make_table(columns=[("Key", "bold cyan"), ("Value", "white")])
    for key, value in pairs:
        table.add_row(key, value)
    make_console().print(table)


__all__ = [
    "make_console",
    "make_progress",
    "make_table",
    "render_keyvalue",
]