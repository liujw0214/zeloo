"""Zeloo CLI subcommands — pluggable command registry.

Provides an abstract base class :class:`Subcommand` and a decorator-based
registry so each subcommand can be developed and registered independently.
"""

from __future__ import annotations

import argparse
import logging
from abc import ABC, abstractmethod
from typing import ClassVar

logger = logging.getLogger(__name__)

_SUBCOMMANDS: dict[str, type[Subcommand]] = {}


def subcommand(name: str | None = None) -> type[Subcommand]:
    """Class decorator that registers a :class:`Subcommand` subclass.

    Use as::

        @subcommand("install")
        class InstallCmd(Subcommand):
            ...
    """

    def _decorator(cls: type[Subcommand]) -> type[Subcommand]:
        key = name or cls.name
        _SUBCOMMANDS[key] = cls
        return cls

    return _decorator


def register_subcommands(parser: argparse.ArgumentParser) -> None:
    """Add all registered subcommands as sub-parsers of *parser*."""
    subparsers = parser.add_subparsers(dest="subcommand", help="Available commands")
    for name, cls in sorted(_SUBCOMMANDS.items()):
        sub = subparsers.add_parser(name, help=cls.help)
        cls.configure_parser(sub)


class Subcommand(ABC):
    """Abstract base for CLI subcommands."""

    name: ClassVar[str] = "base"
    help: ClassVar[str] = ""

    @abstractmethod
    def run(self, args: argparse.Namespace) -> int:
        """Execute the subcommand. Return 0 for success, non-zero for failure."""

    @classmethod
    @abstractmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Add subcommand-specific arguments to *parser*."""


def _load_subcommands() -> None:
    """Eagerly import all subcommand modules so the decorator fires."""
    import zeloo_cli.subcommands.auth  # noqa: F401
    import zeloo_cli.subcommands.backup  # noqa: F401
    import zeloo_cli.subcommands.browser  # noqa: F401
    import zeloo_cli.subcommands.config  # noqa: F401
    import zeloo_cli.subcommands.doctor  # noqa: F401
    import zeloo_cli.subcommands.dump  # noqa: F401
    import zeloo_cli.subcommands.export  # noqa: F401
    import zeloo_cli.subcommands.import_cmd  # noqa: F401
    import zeloo_cli.subcommands.init  # noqa: F401
    import zeloo_cli.subcommands.install  # noqa: F401
    import zeloo_cli.subcommands.login  # noqa: F401
    import zeloo_cli.subcommands.logout  # noqa: F401
    import zeloo_cli.subcommands.logs  # noqa: F401
    import zeloo_cli.subcommands.mcp  # noqa: F401
    import zeloo_cli.subcommands.memory  # noqa: F401
    import zeloo_cli.subcommands.model  # noqa: F401
    import zeloo_cli.subcommands.profile  # noqa: F401
    import zeloo_cli.subcommands.repair  # noqa: F401
    import zeloo_cli.subcommands.reset  # noqa: F401
    import zeloo_cli.subcommands.run  # noqa: F401
    import zeloo_cli.subcommands.secrets  # noqa: F401
    import zeloo_cli.subcommands.serve  # noqa: F401
    import zeloo_cli.subcommands.session  # noqa: F401
    import zeloo_cli.subcommands.sessions  # noqa: F401
    import zeloo_cli.subcommands.skills  # noqa: F401
    import zeloo_cli.subcommands.status  # noqa: F401
    import zeloo_cli.subcommands.sync  # noqa: F401
    import zeloo_cli.subcommands.tools  # noqa: F401
    import zeloo_cli.subcommands.uninstall  # noqa: F401
    import zeloo_cli.subcommands.update  # noqa: F401
    import zeloo_cli.subcommands.usage  # noqa: F401
    import zeloo_cli.subcommands.verify  # noqa: F401
    import zeloo_cli.subcommands.worktree  # noqa: F401
    import zeloo_cli.subcommands.worktree_cleanup  # noqa: F401
    import zeloo_cli.subcommands.workspace  # noqa: F401
    import zeloo_cli.subcommands.z  # noqa: F401


def run_subcommand(name: str, args: argparse.Namespace) -> int:
    """Dispatch to the named subcommand's :meth:`run` method."""
    _load_subcommands()
    cls = _SUBCOMMANDS.get(name)
    if cls is None:
        logger.error("Unknown subcommand: %s", name)
        return 1
    return cls().run(args)
