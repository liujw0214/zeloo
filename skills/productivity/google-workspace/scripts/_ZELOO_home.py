"""Resolve ZELOO_HOME for standalone skill scripts.

Skill scripts may run outside the Zeloo process (e.g. system Python,
nix env, CI) where ``zeloo_constants`` is not importable.  This module
provides the same ``get_zeloo_home()`` and ``display_zeloo_home()``
contracts as ``zeloo_constants`` without requiring it on ``sys.path``.

When ``zeloo_constants`` IS available it is used directly so that any
future enhancements (profile resolution, Docker detection, etc.) are
picked up automatically.  The fallback path replicates the core logic
from ``zeloo_constants.py`` using only the stdlib.

All scripts under ``google-workspace/scripts/`` should import from here
instead of duplicating the ``ZELOO_HOME = Path(os.getenv(...))`` pattern.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from zeloo_constants import display_zeloo_home as display_zeloo_home
    from zeloo_constants import get_zeloo_home as get_zeloo_home
except (ModuleNotFoundError, ImportError):

    def get_zeloo_home() -> Path:
        """Return the Zeloo home directory (default: ~/.Zeloo).

        Mirrors ``zeloo_constants.get_zeloo_home()``."""
        val = os.environ.get("ZELOO_HOME", "").strip()
        return Path(val) if val else Path.home() / ".Zeloo"

    def display_zeloo_home() -> str:
        """Return a user-friendly ``~/``-shortened display string.

        Mirrors ``zeloo_constants.display_zeloo_home()``."""
        home = get_zeloo_home()
        try:
            return "~/" + home.relative_to(Path.home()).as_posix()
        except ValueError:
            return str(home)
