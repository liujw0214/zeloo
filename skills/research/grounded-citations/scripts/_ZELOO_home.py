"""Resolve ZELOO_HOME for standalone skill scripts.

Skill scripts may run outside the Zeloo process (system Python, nix env,
CI) where ``zeloo_constants`` is not importable.  This module provides the
same ``get_zeloo_home()`` contract without requiring it on ``sys.path``.

When ``zeloo_constants`` IS available it is used directly so profile
resolution and any future enhancements are picked up automatically.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from zeloo_constants import get_zeloo_home as get_zeloo_home
except (ModuleNotFoundError, ImportError):

    def get_zeloo_home() -> Path:
        """Return the Zeloo home directory (default: ``~/.Zeloo``)."""
        val = os.environ.get("ZELOO_HOME", "").strip()
        return Path(val) if val else Path.home() / ".Zeloo"
