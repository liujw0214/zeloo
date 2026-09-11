"""Zeloo version metadata — borrowed from Hermes Agent's ``__about__.py``.

Single source of truth for the package version. ``zeloo --version``
and the setup wizard both read from here.
"""
from __future__ import annotations

__version__ = "0.16.0"

# Hermes Agent v0.16.0 parity: also expose the codename and a short
# description string so the TUI / Web dashboard can render them.
__codename__ = "The Surface Release"
__description__ = (
    "Zeloo Agent — a self-hosted, self-evolving AI Agent runtime. "
    "Hermes Agent v0.16.0 feature parity."
)
