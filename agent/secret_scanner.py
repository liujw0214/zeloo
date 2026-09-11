"""Secret scanner — detect and redact leaked credentials in text.

LLM-driven agents frequently read tool output, log files, and HTTP
responses that may contain credentials. Without scanning, a leaked key
ends up in the prompt, the trajectory database, and downstream logs —
turning a single mistake into a full-blown data breach.

This module provides a small, dependency-free scanner with three layers:

  * :class:`SecretCategory` — what kind of credential was found.
  * :class:`SecretFinding` — one match (category, severity, span, sample).
  * :class:`SecretScanner` — applies a configurable rule pack to a
    string and returns findings.
  * :func:`scan_text` — convenience wrapper for one-off scans.
  * :func:`redact_text` — replaces matches with a redaction placeholder
    while preserving the surrounding context length (so model token
    counts stay roughly stable).

Rule packs are bundled (common provider formats + private keys + JWTs).
Custom rules can be added at runtime via :meth:`SecretScanner.add_rule`.

Severity tiers:

  * ``critical`` — private keys, cloud account keys, signing tokens.
    These are almost always credentials. Default action: redact.
  * ``high`` — provider API keys (OpenAI / Anthropic / GitHub / GitLab /
    Stripe / Slack / AWS access keys). Almost always credentials.
    Default action: redact.
  * ``medium`` — JWT tokens, Slack webhooks. Default action: redact.
  * ``low`` — heuristic matches (e.g. ``password = ...``). Higher
    false-positive rate. Default action: flag (no auto-redact).

Design notes:

  * Rules use bounded quantifiers (``{20,}`` for OpenAI keys, etc.) so
    false positives on prose are minimized.
  * ``allow_list`` lets users exclude e.g. their own test fixtures
    (``sk-test-...``) or known-safe sample values.
  * The scanner is **stateless and pure** — no I/O, no globals, safe to
    call from any thread.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class SecretSeverity(StrEnum):
    """How sensitive a match is."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# ── Categories ───────────────────────────────────────────────────


class SecretCategory(StrEnum):
    """Coarse classification of leaked secrets."""

    OPENAI_API_KEY = "openai_api_key"
    ANTHROPIC_API_KEY = "anthropic_api_key"
    GOOGLE_API_KEY = "google_api_key"
    GITHUB_TOKEN = "github_token"
    GITLAB_TOKEN = "gitlab_token"
    SLACK_TOKEN = "slack_token"
    STRIPE_KEY = "stripe_key"
    AWS_ACCESS_KEY = "aws_access_key"
    PRIVATE_KEY = "private_key"
    JWT = "jwt"
    GENERIC_API_KEY = "generic_api_key"
    PASSWORD_ASSIGNMENT = "password_assignment"


# ── Built-in rules ───────────────────────────────────────────────


@dataclass(frozen=True)
class SecretRule:
    """One detector rule."""

    category: SecretCategory
    severity: SecretSeverity
    pattern: re.Pattern[str]
    description: str
    auto_redact: bool = True


def _compile(
    rules: list[tuple[SecretCategory, SecretSeverity, str, str, bool]],
) -> list[SecretRule]:
    return [
        SecretRule(
            category=cat,
            severity=sev,
            pattern=re.compile(pat, flags=re.MULTILINE),
            description=desc,
            auto_redact=auto,
        )
        for cat, sev, pat, desc, auto in rules
    ]


_BUILTIN_RULES: list[SecretRule] = _compile(
    [
        # CRITICAL — always treat as a real credential.
        (
            SecretCategory.PRIVATE_KEY,
            SecretSeverity.CRITICAL,
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----",
            "PEM private key block",
            True,
        ),
        (
            SecretCategory.AWS_ACCESS_KEY,
            SecretSeverity.CRITICAL,
            r"\bAKIA[0-9A-Z]{16}\b",
            "AWS access key id",
            True,
        ),
        # HIGH — provider API keys.
        (
            SecretCategory.OPENAI_API_KEY,
            SecretSeverity.HIGH,
            r"\bsk-[A-Za-z0-9_-]{20,}\b",
            "OpenAI / OpenAI-compatible secret key",
            True,
        ),
        (
            SecretCategory.OPENAI_API_KEY,
            SecretSeverity.HIGH,
            r"\bsk-proj-[A-Za-z0-9_-]{20,}\b",
            "OpenAI project key",
            True,
        ),
        (
            SecretCategory.ANTHROPIC_API_KEY,
            SecretSeverity.HIGH,
            r"\bsk-ant-[A-Za-z0-9_-]{20,}\b",
            "Anthropic secret key",
            True,
        ),
        (
            SecretCategory.GITHUB_TOKEN,
            SecretSeverity.HIGH,
            r"\bghp_[A-Za-z0-9]{30,}\b",
            "GitHub personal access token",
            True,
        ),
        (
            SecretCategory.GITHUB_TOKEN,
            SecretSeverity.HIGH,
            r"\bgithub_pat_[A-Za-z0-9_]{50,}\b",
            "GitHub fine-grained PAT",
            True,
        ),
        (
            SecretCategory.GITHUB_TOKEN,
            SecretSeverity.HIGH,
            r"\bgho_[A-Za-z0-9]{30,}\b",
            "GitHub OAuth token",
            True,
        ),
        (
            SecretCategory.GITLAB_TOKEN,
            SecretSeverity.HIGH,
            r"\bglpat-[A-Za-z0-9_\-]{20,}\b",
            "GitLab personal access token",
            True,
        ),
        (
            SecretCategory.SLACK_TOKEN,
            SecretSeverity.HIGH,
            r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b",
            "Slack token",
            True,
        ),
        (
            SecretCategory.STRIPE_KEY,
            SecretSeverity.HIGH,
            r"\bsk_live_[A-Za-z0-9]{20,}\b",
            "Stripe live secret key",
            True,
        ),
        (
            SecretCategory.STRIPE_KEY,
            SecretSeverity.HIGH,
            r"\brk_live_[A-Za-z0-9]{20,}\b",
            "Stripe live restricted key",
            True,
        ),
        (
            SecretCategory.GOOGLE_API_KEY,
            SecretSeverity.HIGH,
            r"\bAIza[0-9A-Za-z_\-]{35}\b",
            "Google API key",
            True,
        ),
        # MEDIUM — tokens with weaker structure.
        (
            SecretCategory.JWT,
            SecretSeverity.MEDIUM,
            r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b",
            "JSON Web Token",
            True,
        ),
        # LOW — heuristic; high false-positive rate.
        (
            SecretCategory.PASSWORD_ASSIGNMENT,
            SecretSeverity.LOW,
            r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|token)\s*[=:]\s*['\"]?([^\s'\"]{6,})",
            "key=value assignment with credential-looking RHS",
            False,
        ),
        (
            SecretCategory.GENERIC_API_KEY,
            SecretSeverity.LOW,
            r"(?i)\b(?:bearer)\s+[A-Za-z0-9_\-\.=]{20,}",
            "Bearer token (Authorization header)",
            False,
        ),
    ]
)


# ── Result types ─────────────────────────────────────────────────


@dataclass(frozen=True)
class SecretFinding:
    """A single secret match in some scanned text."""

    category: SecretCategory
    severity: SecretSeverity
    description: str
    start: int
    end: int
    sample: str  # first 4 + last 4 chars, rest masked
    auto_redact: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "severity": self.severity.value,
            "description": self.description,
            "start": self.start,
            "end": self.end,
            "sample": self.sample,
            "auto_redact": self.auto_redact,
        }


@dataclass
class SecretScanResult:
    """Aggregate result for one scan."""

    findings: list[SecretFinding] = field(default_factory=list)
    redacted_text: str | None = None

    @property
    def has_findings(self) -> bool:
        return bool(self.findings)

    @property
    def by_severity(self) -> dict[str, int]:
        counts: dict[str, int] = {s.value: 0 for s in SecretSeverity}
        for f in self.findings:
            counts[f.severity.value] += 1
        return counts

    @property
    def categories(self) -> set[str]:
        return {f.category.value for f in self.findings}

    def to_dict(self) -> dict[str, Any]:
        return {
            "findings": [f.to_dict() for f in self.findings],
            "counts_by_severity": self.by_severity,
            "categories": sorted(self.categories),
        }


# ── Scanner ──────────────────────────────────────────────────────


class SecretScanner:
    """Rule-based detector for leaked credentials in text.

    Example::

        scanner = SecretScanner()
        result = scanner.scan("Authorization: Bearer sk-abcdefghijklmnopqrstuv")
        assert result.has_findings
        clean = scanner.redact("sk-abcdefghijklmnopqrstuv")
    """

    def __init__(
        self,
        extra_rules: Iterable[SecretRule] | None = None,
        allow_list: Iterable[str] | None = None,
        min_severity: SecretSeverity = SecretSeverity.LOW,
    ) -> None:
        """Initialize the scanner.

        Args:
            extra_rules: Additional :class:`SecretRule` instances.
            allow_list: String literals to ignore (exact substring match).
                Useful for known-safe test fixtures like ``"sk-test-XXXX"``.
            min_severity: Findings below this severity are dropped.
        """
        self._rules: list[SecretRule] = list(_BUILTIN_RULES)
        for r in extra_rules or ():
            self._rules.append(r)
        self._allow = tuple(allow_list or ())
        self._min_severity = min_severity

    # ── Configuration ────────────────────────────────────────────

    def add_rule(self, rule: SecretRule) -> None:
        """Append a rule to the scanner."""
        self._rules.append(rule)

    def rules(self) -> list[SecretRule]:
        """Return the current rule list (read-only copy)."""
        return list(self._rules)

    def add_allow(self, literal: str) -> None:
        """Add a literal substring that should never trigger a finding."""
        if literal and literal not in self._allow:
            self._allow = self._allow + (literal,)

    def set_min_severity(self, severity: SecretSeverity) -> None:
        """Drop findings below *severity*."""
        self._min_severity = severity

    # ── Core ─────────────────────────────────────────────────────

    def _is_allowed(self, text: str, start: int, end: int) -> bool:
        for lit in self._allow:
            if not lit:
                continue
            # Substring overlap check.
            if lit in text[start:end]:
                return True
        return False

    def scan(self, text: str) -> SecretScanResult:
        """Return all findings in *text* (no redaction)."""
        if not text:
            return SecretScanResult()

        findings: list[SecretFinding] = []
        # Sort rules by descending severity so criticals surface first
        # when callers iterate.
        ordered = sorted(
            self._rules,
            key=lambda r: _severity_rank(r.severity),
            reverse=True,
        )
        min_rank = _severity_rank(self._min_severity)
        for rule in ordered:
            if _severity_rank(rule.severity) < min_rank:
                continue
            for m in rule.pattern.finditer(text):
                if self._is_allowed(text, m.start(), m.end()):
                    continue
                findings.append(
                    SecretFinding(
                        category=rule.category,
                        severity=rule.severity,
                        description=rule.description,
                        start=m.start(),
                        end=m.end(),
                        sample=_mask(m.group(0)),
                        auto_redact=rule.auto_redact,
                    )
                )
        # Stable ordering: severity → start offset.
        findings.sort(key=lambda f: (-_severity_rank(f.severity), f.start))
        return SecretScanResult(findings=findings)

    def redact(self, text: str, placeholder: str = "[REDACTED]") -> str:
        """Return *text* with auto-redact findings replaced by *placeholder*.

        Low-severity rules (``auto_redact=False``) are left in place —
        callers that want to redact everything should call :meth:`scan`
        and replace manually.
        """
        if not text:
            return text
        result = self.scan(text)
        if not result.findings:
            return text
        # Apply replacements right-to-left so offsets remain valid.
        out = text
        for f in sorted(result.findings, key=lambda x: x.start, reverse=True):
            if not f.auto_redact:
                continue
            out = out[: f.start] + placeholder + out[f.end :]
        return out

    def scan_and_redact(self, text: str, placeholder: str = "[REDACTED]") -> SecretScanResult:
        """One-shot: scan, then redact auto-redactable findings.

        The :attr:`SecretScanResult.redacted_text` field is populated.
        """
        result = self.scan(text)
        result.redacted_text = self.redact(text, placeholder=placeholder)
        return result


# ── Helpers ──────────────────────────────────────────────────────


def _severity_rank(sev: SecretSeverity) -> int:
    return {
        SecretSeverity.LOW: 1,
        SecretSeverity.MEDIUM: 2,
        SecretSeverity.HIGH: 3,
        SecretSeverity.CRITICAL: 4,
    }.get(sev, 0)


def _mask(s: str) -> str:
    """Return ``abcd…wxyz`` style sample for *s*."""
    if len(s) <= 8:
        return "*" * len(s)
    return f"{s[:4]}…{s[-4:]}"


def scan_text(text: str, **kwargs: Any) -> SecretScanResult:
    """One-off scan with a fresh :class:`SecretScanner`."""
    return SecretScanner(**kwargs).scan(text)


def redact_text(text: str, **kwargs: Any) -> str:
    """One-off redact with a fresh :class:`SecretScanner`."""
    return SecretScanner(**kwargs).redact(text)


__all__ = [
    "SecretCategory",
    "SecretFinding",
    "SecretRule",
    "SecretScanResult",
    "SecretScanner",
    "SecretSeverity",
    "redact_text",
    "scan_text",
    "severity_rank",
]


def severity_rank(sev: SecretSeverity) -> int:
    """Public alias for :func:`_severity_rank` (int 1-4)."""
    return _severity_rank(sev)
