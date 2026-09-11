"""Zeloo fallback subcommand — manage provider fallback chains.

Wraps :class:`agent.fallback_config.FallbackConfigManager` with a
human-friendly CLI surface. The subcommand supports five actions:

* ``list``     — render every chain and model-pattern binding as a
  rich table.
* ``add``      — create a new chain from a comma-separated provider list.
* ``remove``   — delete an existing chain by name.
* ``set-model`` — bind a model-pattern (e.g. ``gpt-4*``) to a chain.
* ``validate`` — sanity-check every chain against the registered
  provider catalogue.

Examples::

    Zeloo fallback list
    Zeloo fallback add fast groq,openai,deepseek
    Zeloo fallback set-model "gpt-4*" default
    Zeloo fallback validate
"""

from __future__ import annotations

import argparse
import fnmatch
import logging
from pathlib import Path
from typing import Any

from zeloo_cli.rich_render import make_console, make_table
from zeloo_cli.subcommands import Subcommand, subcommand

logger = logging.getLogger(__name__)


@subcommand("fallback")
class FallbackCommand(Subcommand):
    """Subcommand entry point for provider fallback chain management."""

    name = "fallback"
    help = "Manage provider fallback chains (list/add/remove/set-model/validate)"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Attach the five sub-actions to *parser*."""
        sub = parser.add_subparsers(dest="fallback_action", help="Fallback action")

        sub.add_parser("list", help="List all configured fallback chains")

        add_p = sub.add_parser(
            "add", help="Add a new fallback chain",
        )
        add_p.add_argument("name", help="Chain name (e.g. 'fast', 'cheap')")
        add_p.add_argument(
            "providers",
            help="Comma-separated ordered list of providers (highest priority first)",
        )
        add_p.add_argument(
            "--conditions", default=None,
            help="Optional conditions, key=value pairs separated by commas",
        )

        rm_p = sub.add_parser("remove", help="Remove an existing fallback chain")
        rm_p.add_argument("name", help="Chain name to remove")

        set_p = sub.add_parser(
            "set-model", help="Bind a model pattern to a chain",
        )
        set_p.add_argument("model_pattern", help="Model name or glob pattern")
        set_p.add_argument("chain_name", help="Chain name to associate")
        set_p.add_argument("--retry-count", type=int, default=2)
        set_p.add_argument("--retry-delay", type=float, default=1.0)

        sub.add_parser("validate", help="Validate every chain against known providers")

    def run(self, args: argparse.Namespace) -> int:
        """Dispatch to the action-specific handler."""
        action = getattr(args, "fallback_action", None)
        if action == "list":
            return self._list()
        if action == "add":
            conditions = self._parse_conditions(getattr(args, "conditions", None))
            return self._add(args.name, args.providers, conditions)
        if action == "remove":
            return self._remove(args.name)
        if action == "set-model":
            return self._set_model(
                args.model_pattern, args.chain_name,
                retry_count=args.retry_count, retry_delay=args.retry_delay,
            )
        if action == "validate":
            return self._validate()
        console = make_console()
        console.print(
            "[yellow]Usage:[/yellow] Zeloo fallback "
            "[list|add <name> <providers>|remove <name>|set-model <pattern> <chain>|validate]"
        )
        return 1

    # ----- action handlers ---------------------------------------------

    def _list(self) -> int:
        """Render every chain + model binding as a rich table."""
        manager = self._get_manager()
        manager.load()
        console = make_console()

        chains = manager._chains  # noqa: SLF001 — read-only display helper
        if not chains:
            console.print("[yellow]No fallback chains configured.[/yellow]")
            return 0

        table = make_table(
            title=f"Fallback Chains ({len(chains)})",
            columns=[
                ("Name", "bold cyan"),
                ("Providers", "white"),
                ("Enabled", "green"),
                ("Conditions", "magenta"),
            ],
        )
        for name, chain in sorted(chains.items()):
            table.add_row(
                name,
                " → ".join(chain.providers) if chain.providers else "(empty)",
                "yes" if chain.enabled else "no",
                _format_conditions(chain.conditions),
            )
        console.print(table)

        bindings = manager._model_configs  # noqa: SLF001
        if bindings:
            btable = make_table(
                title=f"Model Bindings ({len(bindings)})",
                columns=[
                    ("Pattern", "bold cyan"),
                    ("Chain", "white"),
                    ("Retries", "green"),
                    ("Delay (s)", "magenta"),
                ],
            )
            for pattern, conf in sorted(bindings.items()):
                btable.add_row(
                    conf.model_pattern, conf.chain_name,
                    str(conf.retry_count), f"{conf.retry_delay:g}",
                )
            console.print(btable)
        return 0

    def _add(self, name: str, providers: str, conditions: dict[str, Any]) -> int:
        """Add a new chain (or replace an existing one)."""
        from agent.fallback_config import FallbackChain

        manager = self._get_manager()
        manager.load()
        provider_list = [p.strip() for p in providers.split(",") if p.strip()]
        if not provider_list:
            console = make_console()
            console.print("[red]Error:[/red] providers must be a non-empty list")
            return 1

        chain = FallbackChain(
            name=name, providers=provider_list, enabled=True, conditions=conditions,
        )
        try:
            manager.add_chain(chain)
        except ValueError as exc:
            console = make_console()
            console.print(f"[red]Error:[/red] {exc}")
            return 1
        manager.save()
        console = make_console()
        console.print(
            f"[green]✓[/green] Added chain '[bold]{name}[/bold]' "
            f"({' → '.join(provider_list)})"
        )
        return 0

    def _remove(self, name: str) -> int:
        """Remove an existing chain by name."""
        manager = self._get_manager()
        manager.load()
        try:
            manager.remove_chain(name)
        except (KeyError, ValueError) as exc:
            console = make_console()
            console.print(f"[red]Error:[/red] {exc}")
            return 1
        manager.save()
        console = make_console()
        console.print(f"[green]✓[/green] Removed chain '[bold]{name}[/bold]'")
        return 0

    def _set_model(
        self,
        pattern: str,
        chain_name: str,
        *,
        retry_count: int,
        retry_delay: float,
    ) -> int:
        """Bind *pattern* to *chain_name*."""
        from agent.fallback_config import ModelFallbackConfig

        manager = self._get_manager()
        manager.load()
        if chain_name not in manager._chains:  # noqa: SLF001
            console = make_console()
            console.print(
                f"[red]Error:[/red] chain '{chain_name}' does not exist. "
                f"Run 'Zeloo fallback list' to see available chains."
            )
            return 1

        # ``add_model_config`` overwrites an existing entry, so this works
        # both for new bindings and for updating retry knobs.
        manager._model_configs[pattern] = ModelFallbackConfig(  # noqa: SLF001
            model_pattern=pattern,
            chain_name=chain_name,
            retry_count=retry_count,
            retry_delay=retry_delay,
        )
        manager.save()
        console = make_console()
        console.print(
            f"[green]✓[/green] Bound '[bold]{pattern}[/bold]' "
            f"→ chain '[bold]{chain_name}[/bold]'"
        )
        return 0

    def _validate(self) -> int:
        """Verify that every chain's providers are reachable/registered."""
        manager = self._get_manager()
        manager.load()
        console = make_console()
        known = self._known_providers()
        chains = manager._chains  # noqa: SLF001

        problems: list[str] = []
        table = make_table(
            title="Fallback Validation",
            columns=[
                ("Chain", "bold cyan"),
                ("Provider", "white"),
                ("Status", "green"),
                ("Notes", "magenta"),
            ],
        )
        for name, chain in sorted(chains.items()):
            if not chain.providers:
                table.add_row(name, "(none)", "[red]FAIL[/red]", "empty provider list")
                problems.append(f"{name}: empty provider list")
                continue
            for provider in chain.providers:
                status, notes = self._validate_provider(provider, known)
                colour = "green" if status == "ok" else "red"
                table.add_row(
                    name, provider, f"[{colour}]{status.upper()}[/{colour}]", notes,
                )
                if status != "ok":
                    problems.append(f"{name}/{provider}: {notes}")

        # Also validate bindings reference real chains.
        for pattern, conf in manager._model_configs.items():  # noqa: SLF001
            if conf.chain_name not in chains:
                problems.append(
                    f"model pattern '{pattern}' references missing chain '{conf.chain_name}'"
                )

        console.print(table)
        if problems:
            console.print(f"\n[red]✗ {len(problems)} problem(s) found:[/red]")
            for issue in problems:
                console.print(f"  • {issue}")
            return 1
        console.print("\n[green]✓ All fallback chains look healthy.[/green]")
        return 0

    # ----- helpers -----------------------------------------------------

    @staticmethod
    def _parse_conditions(raw: str | None) -> dict[str, Any]:
        """Parse ``key=value,key2=value2`` into a typed dictionary."""
        if not raw:
            return {}
        out: dict[str, Any] = {}
        for pair in raw.split(","):
            pair = pair.strip()
            if not pair or "=" not in pair:
                continue
            key, _, value = pair.partition("=")
            key = key.strip()
            value = value.strip()
            try:
                out[key] = int(value)
            except ValueError:
                try:
                    out[key] = float(value)
                except ValueError:
                    lowered = value.lower()
                    if lowered in {"true", "false"}:
                        out[key] = lowered == "true"
                    else:
                        out[key] = value
        return out

    @staticmethod
    def _known_providers() -> set[str]:
        """Return the names of every provider registered in the runtime."""
        try:
            from agent.providers import list_providers
            return set(list_providers())
        except Exception:  # noqa: BLE001
            # Fallback to a static known set.
            return {
                "openai", "anthropic", "google", "groq", "mistral",
                "deepseek", "openrouter", "xai", "ollama", "azure",
                "fireworks", "together", "bedrock",
            }

    @staticmethod
    def _validate_provider(
        provider: str,
        known: set[str],
    ) -> tuple[str, str]:
        """Return ``(status, notes)`` for a single provider reference."""
        if not provider:
            return "warn", "empty provider name"
        if provider not in known:
            return "warn", "not registered"
        return "ok", "registered"

    @staticmethod
    def _get_manager() -> Any:
        """Late-bound import to avoid pulling config dependencies at CLI load."""
        from agent.fallback_config import FallbackConfigManager
        return FallbackConfigManager()


def _format_conditions(conditions: dict[str, Any]) -> str:
    """Render a compact ``k=v`` representation of a conditions dict."""
    if not conditions:
        return "—"
    return ", ".join(f"{k}={v}" for k, v in sorted(conditions.items()))


# Useful for tests / scripted invocation outside the CLI surface.
def run(args: argparse.Namespace) -> int:  # pragma: no cover - thin wrapper
    """Direct programmatic entry point for the ``fallback`` subcommand."""
    return FallbackCommand().run(args)


# Helpful when chaining pattern matching from external scripts.
def resolve_pattern(model: str, patterns: dict[str, str]) -> str | None:
    """Pick the first chain whose glob pattern matches *model*."""
    for pattern, chain in patterns.items():
        if fnmatch.fnmatch(model, pattern):
            return chain
    return None


__all__ = [
    "FallbackCommand",
    "run",
    "resolve_pattern",
]


def _ensure_runtime_path() -> None:  # pragma: no cover - convenience
    """Best-effort sys.path tweak so the module can run via ``python -m``."""
    import sys
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
