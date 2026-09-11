"""Terminal display utilities — formatted output for TUI and CLI."""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
    from rich.syntax import Syntax
    from rich.table import Table
    from rich.tree import Tree

    _RICH_AVAILABLE = True
except ImportError:
    _RICH_AVAILABLE = False


class DisplayStyle(str, Enum):  # noqa: UP042
    """Display style presets."""

    PLAIN = "plain"
    MINIMAL = "minimal"
    RICH = "rich"
    MARKDOWN = "markdown"
    JSON = "json"


@dataclass
class DisplayConfig:
    """Configuration for display output."""

    style: DisplayStyle = DisplayStyle.PLAIN
    width: int = 100
    show_timestamps: bool = True
    show_tokens: bool = False
    color_output: bool = True
    max_content_width: int = 2000


class TerminalDisplay:
    """Terminal display with multiple output styles.

    Supports plain text, markdown, rich (with colors/tables), and JSON output.
    Falls back gracefully when rich is not installed.
    """

    def __init__(self, config: DisplayConfig | None = None):
        self.config = config or DisplayConfig()
        self._console: Any = None
        self._start_time = time.time()

    def _get_console(self) -> Any:
        """Lazily initialize the rich console."""
        if not _RICH_AVAILABLE:
            return None
        if self._console is None:
            self._console = Console(
                width=self.config.width,
                force_terminal=self.config.color_output,
            )
        return self._console

    def print_message(
        self,
        role: str,
        content: str,
        timestamp: float | None = None,
        tokens: int | None = None,
    ) -> None:
        """Print a chat message with optional styling.

        Args:
            role: Message role ("user", "assistant", "system", "tool").
            content: Message content.
            timestamp: Optional message timestamp.
            tokens: Optional token count.
        """
        prefix = self._format_prefix(role, timestamp, tokens)
        styled_role = self._style_role(role)

        if self.config.style == DisplayStyle.MARKDOWN and role == "assistant":
            self.print_markdown(content, prefix=prefix)
        elif self.config.style == DisplayStyle.RICH and _RICH_AVAILABLE:
            self._print_rich_message(styled_role, content, prefix)
        else:
            self.print_plain(f"{prefix}{styled_role}: {content}")

    def print_plain(self, text: str) -> None:
        """Print plain text."""
        print(text, file=sys.stdout)

    def print_markdown(self, content: str, prefix: str = "") -> None:
        """Print markdown-formatted content."""
        if _RICH_AVAILABLE:
            console = self._get_console()
            if console:
                md = Markdown(content, code_theme="monokai")
                console.print(md)
                return
        if prefix:
            print(prefix, file=sys.stdout)
        print(content, file=sys.stdout)

    def print_error(self, message: str, details: str | None = None) -> None:
        """Print an error message.

        Args:
            message: Error summary.
            details: Optional detailed error information.
        """
        if self.config.style == DisplayStyle.RICH and _RICH_AVAILABLE:
            console = self._get_console()
            if console:
                console.print(f"[bold red]Error:[/bold red] {message}")
                if details:
                    console.print(f"[dim]{details}[/dim]")
                return

        print(f"Error: {message}", file=sys.stderr)
        if details:
            print(f"  {details}", file=sys.stderr)

    def print_warning(self, message: str) -> None:
        """Print a warning message."""
        if self.config.style == DisplayStyle.RICH and _RICH_AVAILABLE:
            console = self._get_console()
            if console:
                console.print(f"[bold yellow]Warning:[/bold yellow] {message}")
                return
        print(f"Warning: {message}", file=sys.stdout)

    def print_success(self, message: str) -> None:
        """Print a success message."""
        if self.config.style == DisplayStyle.RICH and _RICH_AVAILABLE:
            console = self._get_console()
            if console:
                console.print(f"[bold green]Success:[/bold green] {message}")
                return
        print(f"Success: {message}", file=sys.stdout)

    def print_info(self, message: str) -> None:
        """Print an informational message."""
        if self.config.style == DisplayStyle.RICH and _RICH_AVAILABLE:
            console = self._get_console()
            if console:
                console.print(f"[bold cyan]Info:[/bold cyan] {message}")
                return
        print(f"Info: {message}", file=sys.stdout)

    def print_table(self, data: list[dict[str, Any]], title: str = "") -> None:
        """Print data as a formatted table."""
        if not data:
            return

        if self.config.style == DisplayStyle.RICH and _RICH_AVAILABLE:
            console = self._get_console()
            if console:
                table = Table(title=title if title else None)
                for col in data[0].keys():
                    table.add_column(str(col))
                for row in data:
                    table.add_row(*[str(v) for v in row.values()])
                console.print(table)
                return

        col_widths = {k: max(len(k), max(len(str(r.get(k, ""))) for r in data)) for k in data[0]}
        header = "  ".join(k.ljust(col_widths[k]) for k in data[0])
        separator = "  ".join("-" * col_widths[k] for k in data[0])
        print(header, file=sys.stdout)
        print(separator, file=sys.stdout)
        for row in data:
            row_str = "  ".join(
                str(row.get(k, "")).ljust(col_widths[k]) for k in data[0]
            )
            print(row_str, file=sys.stdout)

    def print_code(
        self,
        code: str,
        language: str = "python",
        title: str = "",
    ) -> None:
        """Print syntax-highlighted code.

        Args:
            code: Source code string.
            language: Programming language name.
            title: Optional code block title.
        """
        if self.config.style == DisplayStyle.RICH and _RICH_AVAILABLE:
            console = self._get_console()
            if console:
                syntax = Syntax(code, language, theme="monokai", line_numbers=True)
                if title:
                    panel = Panel(syntax, title=title)
                    console.print(panel)
                else:
                    console.print(syntax)
                return

        lines = code.split("\n")
        for i, line in enumerate(lines, 1):
            print(f"{i:4d} │ {line}", file=sys.stdout)

    def print_tree(self, data: dict[str, Any], title: str = "") -> None:
        """Print hierarchical data as a tree."""
        if self.config.style == DisplayStyle.RICH and _RICH_AVAILABLE:
            console = self._get_console()
            if console:
                tree = Tree(title or "Data")
                self._build_rich_tree(tree, data)
                console.print(tree)
                return

        self._print_dict_tree(data, indent=0)

    def print_progress(
        self,
        description: str,
        total: int | None = None,
    ) -> Progress | None:
        """Start a progress display.

        Returns a progress context manager if rich is available.
        """
        if _RICH_AVAILABLE:
            console = self._get_console()
            if console:
                return Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    TimeElapsedColumn(),
                    console=console,
                )
        return None

    def print_separator(self, char: str = "-", width: int | None = None) -> None:
        """Print a horizontal separator line."""
        w = width or self.config.width
        print(char * w, file=sys.stdout)

    def print_elapsed(self) -> None:
        """Print elapsed time since display initialization."""
        elapsed = time.time() - self._start_time
        print(f"Elapsed: {elapsed:.1f}s", file=sys.stdout)

    def _format_prefix(
        self,
        role: str,
        timestamp: float | None,
        tokens: int | None,
    ) -> str:
        """Build message prefix string."""
        parts: list[str] = []
        if self.config.show_timestamps and timestamp:
            import datetime
            dt = datetime.datetime.fromtimestamp(timestamp)
            parts.append(dt.strftime("%H:%M:%S"))
        if self.config.show_tokens and tokens is not None:
            parts.append(f"t:{tokens}")
        if parts:
            return f"[{' '.join(parts)}] "
        return ""

    def _style_role(self, role: str) -> str:
        """Apply ANSI color styling to a role name."""
        colors: dict[str, str] = {
            "user": "\033[94m",     # blue
            "assistant": "\033[92m", # green
            "system": "\033[93m",    # yellow
            "tool": "\033[96m",      # cyan
            "error": "\033[91m",     # red
        }
        reset = "\033[0m"
        color = colors.get(role.lower(), "")
        return f"{color}{role}{reset}"

    def _print_rich_message(
        self,
        role: str,
        content: str,
        prefix: str,
    ) -> None:
        """Print a message using rich formatting."""
        console = self._get_console()
        if not console:
            return

        role_colors: dict[str, str] = {
            "user": "blue",
            "assistant": "green",
            "system": "yellow",
            "tool": "cyan",
        }
        color = role_colors.get(role.lower(), "white")

        prefix_text = prefix if prefix else ""
        console.print(f"{prefix_text}[bold {color}]{role}:[/bold {color}] {content}")

    def _build_rich_tree(self, tree: Any, data: Any) -> None:
        """Recursively build a rich Tree from dict/list data."""
        if isinstance(data, dict):
            for key, value in data.items():
                branch = tree.add(f"[bold]{key}[/bold]")
                self._build_rich_tree(branch, value)
        elif isinstance(data, list):
            for item in data:
                self._build_rich_tree(tree, f"- {item}")
        else:
            tree.add(str(data))

    def _print_dict_tree(
        self,
        data: Any,
        indent: int = 0,
        prefix: str = "",
    ) -> None:
        """Print a dict as an indented tree (plain text fallback)."""
        ind = "  " * indent
        if isinstance(data, dict):
            for key, value in data.items():
                print(f"{ind}{prefix}{key}:", file=sys.stdout)
                self._print_dict_tree(value, indent + 1, "")
        elif isinstance(data, list):
            for item in data:
                print(f"{ind}{prefix}- {item}", file=sys.stdout)
        else:
            print(f"{ind}{prefix}{data}", file=sys.stdout)
