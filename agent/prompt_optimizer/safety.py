"""Prompt safety validator — detect injection and unsafe content."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum

logger = logging.getLogger(__name__)


class ThreatLevel(StrEnum):
    """Threat severity levels."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class SafetyFinding:
    """A single safety concern found in a prompt."""

    category: str
    level: ThreatLevel
    pattern: str
    location: str
    description: str
    recommendation: str = ""


@dataclass
class SafetyReport:
    """Complete safety analysis of a prompt."""

    is_safe: bool
    threat_level: ThreatLevel
    findings: list[SafetyFinding] = field(default_factory=list)
    sanitized_prompt: str = ""
    blocked_patterns: list[str] = field(default_factory=list)


class PromptSafetyValidator:
    """Validate prompts against injection and unsafe content patterns.

    Categories of threats detected:
    - Prompt injection attacks (instruction override, role hijacking)
    - Jailbreak attempts (DAN, "ignore previous instructions")
    - Data exfiltration attempts
    - Harmful content requests
    - Sensitive information disclosure
    - Suspicious encoding/obfuscation
    """

    INJECTION_PATTERNS: dict[str, list[str]] = {
        "instruction_override": [
            r"ignore\s+(all\s+)?previous\s+instructions?",
            r"disregard\s+(all\s+)?(prior|previous)\s+(instructions?|rules?)",
            r"forget\s+(everything|all)\s+(you|about)",
            r"do\s+not\s+follow\s+(any\s+)?rules?",
            r"new\s+instructions?\s*:",
        ],
        "role_hijacking": [
            r"you\s+are\s+now\s+",
            r"pretend\s+to\s+be\s+",
            r"act\s+as\s+(a\s+|an\s+)?(?!assistant)",
            r"system\s*prompt\s*[:=]",
            r"<\|.*?\|>",  # ChatML special tokens
        ],
        "jailbreak": [
            r"\bdan\b.*?mode",
            r"developer\s+mode",
            r"jailbreak",
            r"bypass\s+(safety|filter)",
            r"without\s+(any\s+)?(restrictions?|limitations?)",
        ],
        "data_exfiltration": [
            r"(system|secret)\s+(prompt|password|key)",
            r"reveal\s+(your|the)\s+(prompt|instructions?)",
            r"output\s+(your|the)\s+(initial|system)\s+prompt",
            r"print\s+.*?prompt",
        ],
        "harmful_content": [
            r"how\s+to\s+(make|create|build)\s+(a\s+)?(bomb|weapon|virus)",
            r"hack\s+into\s+",
            r"steal\s+.*?credentials?",
        ],
        "encoding_obfuscation": [
            r"base64\s*[:=]",
            r"\\x[0-9a-fA-F]{2}",
            r"\\u[0-9a-fA-F]{4}",
            r"&#\d+;",
        ],
    }

    SENSITIVE_DATA_PATTERNS: list[str] = [
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # email
        r"\b\d{3}-\d{2}-\d{4}\b",  # SSN
        r"\b\d{16}\b",  # credit card
        r"\b(?:sk-|api[_-]?key)[\w-]{20,}\b",  # API keys
    ]

    def __init__(
        self,
        strict_mode: bool = False,
        custom_patterns: dict[str, list[str]] | None = None,
    ) -> None:
        self.strict_mode = strict_mode
        self.patterns = dict(self.INJECTION_PATTERNS)
        if custom_patterns:
            for category, pats in custom_patterns.items():
                self.patterns.setdefault(category, []).extend(pats)

    def validate(self, prompt: str) -> SafetyReport:
        """Run full safety validation on a prompt."""
        findings: list[SafetyFinding] = []
        blocked: list[str] = []

        for category, patterns in self.patterns.items():
            for pattern in patterns:
                for match in re.finditer(pattern, prompt, re.IGNORECASE | re.MULTILINE):
                    findings.append(
                        SafetyFinding(
                            category=category,
                            level=self._severity_for(category),
                            pattern=pattern,
                            location=self._find_location(prompt, match.start()),
                            description=f"Potential {category} pattern detected",
                            recommendation=self._recommend(category),
                        )
                    )
                    blocked.append(match.group(0))
                    logger.warning(
                        "Safety finding: %s in prompt at position %d",
                        category, match.start(),
                    )

        for pattern in self.SENSITIVE_DATA_PATTERNS:
            for match in re.finditer(pattern, prompt):
                findings.append(
                    SafetyFinding(
                        category="sensitive_data",
                        level=ThreatLevel.MEDIUM,
                        pattern=pattern,
                        location=self._find_location(prompt, match.start()),
                        description="Possible sensitive data detected",
                        recommendation="Redact or remove sensitive data",
                    )
                )

        threat_level = self._max_threat(findings)
        sanitized = self._sanitize(prompt, blocked) if blocked else prompt
        is_safe = threat_level in (ThreatLevel.NONE, ThreatLevel.LOW)

        if self.strict_mode and not is_safe:
            is_safe = False

        return SafetyReport(
            is_safe=is_safe,
            threat_level=threat_level,
            findings=findings,
            sanitized_prompt=sanitized,
            blocked_patterns=blocked,
        )

    def _severity_for(self, category: str) -> ThreatLevel:
        severity_map: dict[str, ThreatLevel] = {
            "instruction_override": ThreatLevel.HIGH,
            "role_hijacking": ThreatLevel.HIGH,
            "jailbreak": ThreatLevel.CRITICAL,
            "data_exfiltration": ThreatLevel.HIGH,
            "harmful_content": ThreatLevel.CRITICAL,
            "encoding_obfuscation": ThreatLevel.MEDIUM,
            "sensitive_data": ThreatLevel.MEDIUM,
        }
        return severity_map.get(category, ThreatLevel.LOW)

    def _find_location(self, text: str, pos: int) -> str:
        line = text[:pos].count("\n") + 1
        col = pos - (text[:pos].rfind("\n") + 1) + 1
        return f"line {line}, col {col}"

    def _recommend(self, category: str) -> str:
        recommendations = {
            "instruction_override": "Remove or rephrase instruction-override attempts",
            "role_hijacking": "Avoid role-play hijacking; clarify scope",
            "jailbreak": "Reject this prompt — likely jailbreak attempt",
            "data_exfiltration": "Remove system prompt extraction attempts",
            "harmful_content": "Reject harmful content request",
            "encoding_obfuscation": "Decode and inspect encoded content carefully",
        }
        return recommendations.get(category, "Review content carefully")

    def _max_threat(self, findings: list[SafetyFinding]) -> ThreatLevel:
        if not findings:
            return ThreatLevel.NONE
        severity_order = [
            ThreatLevel.NONE, ThreatLevel.LOW, ThreatLevel.MEDIUM,
            ThreatLevel.HIGH, ThreatLevel.CRITICAL,
        ]
        max_level = ThreatLevel.NONE
        for f in findings:
            if f.level not in severity_order:
                continue
            if severity_order.index(f.level) > severity_order.index(max_level):
                max_level = f.level
        return max_level

    def _sanitize(self, prompt: str, blocked: list[str]) -> str:
        sanitized = prompt
        for blocked_str in blocked:
            sanitized = sanitized.replace(blocked_str, "[REDACTED]")
        return sanitized


__all__ = [
    "ThreatLevel",
    "SafetyFinding",
    "SafetyReport",
    "PromptSafetyValidator",
]