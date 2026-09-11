"""Threat pattern detection — prompt-injection scanning for inputs and context.

Provides :func:`scan_for_threats`, a lightweight regex-based scanner that
flags common prompt-injection patterns. Two scopes are supported:

* ``"input"`` — user-entered text. Critical patterns are flagged but the
  text is allowed through (the caller decides how to react).
* ``"context"`` — files loaded into the system prompt. Any match is
  treated as a hard block because the content would otherwise enter the
  prompt verbatim.

This module intentionally has zero third-party dependencies.
"""

from __future__ import annotations

import re
from typing import Literal

ThreatScope = Literal["input", "context"]

# Critical injection patterns — these attempt to override instructions or
# leak the system prompt.
_CRITICAL_PATTERNS: list[tuple[str, str]] = [
    (
        r"(?i)(ignore|disregard|forget)\s+(all\s+)?(previous|above|prior|system)\s+(instructions?|prompts?)",
        "instruction-override",
    ),
    (
        r"(?i)(you\s+are\s+now|act\s+as|pretend\s+to\s+be)\s+(a|an|the)\s+(DAN|jailbreak|unrestricted|admin|root)",
        "role-hijack",
    ),
    (
        r"(?i)(print|reveal|show|output|display|repeat)\s+(the\s+)?(system\s+)?(prompt|instructions?)",
        "system-prompt-leak-attempt",
    ),
    (
        r"(?i)<\s*system\s*>",
        "system-tag-injection",
    ),
]

# Suspicious (non-critical) patterns — flagged for awareness.
_SUSPICIOUS_PATTERNS: list[tuple[str, str]] = [
    (
        r"(?i)(prompt\s+injection|jailbreak|ignore\s+rules)",
        "suspicious-keyword",
    ),
    (
        r"(?i)from\s+now\s+on",
        "persona-reset-attempt",
    ),
]


def scan_for_threats(text: str, scope: ThreatScope = "input") -> list[str]:
    """Scan *text* for prompt-injection threat patterns.

    Args:
        text: The text to scan.
        scope: ``"input"`` (user text) or ``"context"`` (system-prompt file).
               In ``"context"`` scope, suspicious patterns are also treated
               as findings because the content enters the prompt verbatim.

    Returns:
        A list of matched threat names. Empty means clean.
    """
    if not text:
        return []

    findings: list[str] = []
    seen: set[str] = set()

    for pattern, name in _CRITICAL_PATTERNS:
        if name in seen:
            continue
        if re.search(pattern, text):
            findings.append(name)
            seen.add(name)

    if scope == "context":
        for pattern, name in _SUSPICIOUS_PATTERNS:
            if name in seen:
                continue
            if re.search(pattern, text):
                findings.append(name)
                seen.add(name)

    return findings


def is_blocked_for_context(text: str) -> bool:
    """Return True if *text* contains any pattern that blocks context loading.

    In ``context`` scope, *any* match (critical or suspicious) blocks the
    file from being injected into the system prompt.
    """
    return bool(scan_for_threats(text, scope="context"))
