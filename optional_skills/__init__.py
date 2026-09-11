"""Optional skills — specialized agent capabilities.

Each skill is a self-contained module with pure functions.

These are automatically exposed as Agent tools via
``tools/optional_skill_tools.py`` (18 @tool-decorated wrappers) and
registered in ``toolsets.py`` under 6 optional_skill:* toolsets.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

__all__ = [
    "skill_loader",
    "software_development",
    "devops",
    "data_science",
    "mlops",
    "research",
    "security",
]
