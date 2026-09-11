"""Unified security scanning orchestrator (secret + threat + output)."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Literal


class ScanSeverity(Enum):
    """Normalised severity for any scanner."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @classmethod
    def from_string(cls, value: str) -> ScanSeverity:
        """Best-effort parse, falling back to :attr:`INFO`."""
        if not value:
            return cls.INFO
        try:
            return cls(value.lower())
        except ValueError:
            return cls.INFO


def _severity_rank(sev: ScanSeverity) -> int:
    return {
        ScanSeverity.INFO: 0,
        ScanSeverity.LOW: 1,
        ScanSeverity.MEDIUM: 2,
        ScanSeverity.HIGH: 3,
        ScanSeverity.CRITICAL: 4,
    }.get(sev, 0)


@dataclass
class ScanFinding:
    """A single security finding produced by any of the scanners."""

    scanner: str  # "secret", "threat", "output"
    severity: ScanSeverity
    title: str
    description: str
    location: str
    suggestion: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dict."""
        data = asdict(self)
        data["severity"] = self.severity.value
        return data


@dataclass
class ScanReport:
    """Aggregate scan report for one or many files / inputs."""

    started_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    finished_at: datetime | None = None
    findings: list[ScanFinding] = field(default_factory=list)
    files_scanned: int = 0
    lines_scanned: int = 0
    target: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def add(self, finding: ScanFinding) -> None:
        """Append a finding and keep the list sorted by severity."""
        self.findings.append(finding)
        self.findings.sort(
            key=lambda f: (-_severity_rank(f.severity), f.location, f.title)
        )

    def finish(self) -> None:
        """Mark the report as complete and stamp ``finished_at``."""
        self.finished_at = datetime.now(tz=timezone.utc)

    def duration_ms(self) -> float:
        """Return wall-clock scan duration in milliseconds."""
        end = self.finished_at or datetime.now(tz=timezone.utc)
        return (end - self.started_at).total_seconds() * 1000

    def get_by_severity(self, severity: ScanSeverity) -> list[ScanFinding]:
        """Return findings at the given severity."""
        return [f for f in self.findings if f.severity == severity]

    def get_by_scanner(self, scanner: str) -> list[ScanFinding]:
        """Return findings emitted by *scanner*."""
        return [f for f in self.findings if f.scanner == scanner]

    def summary(self) -> dict[str, int]:
        """Return ``{severity.value: count}`` including zero buckets."""
        counts = {s.value: 0 for s in ScanSeverity}
        for f in self.findings:
            counts[f.severity.value] += 1
        counts["total"] = len(self.findings)
        return counts

    def has_critical(self) -> bool:
        """Return ``True`` if any finding is :attr:`ScanSeverity.CRITICAL`."""
        return any(f.severity == ScanSeverity.CRITICAL for f in self.findings)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "target": self.target,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_ms": round(self.duration_ms(), 3),
            "files_scanned": self.files_scanned,
            "lines_scanned": self.lines_scanned,
            "summary": self.summary(),
            "metadata": self.metadata,
            "findings": [f.to_dict() for f in self.findings],
        }

    def to_json(self, indent: int | None = 2) -> str:
        """Return ``to_dict()`` encoded as JSON."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# Heuristic max bytes per file — prevent runaway memory on huge logs.
_MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MiB

_DEFAULT_SCAN_EXTENSIONS: tuple[str, ...] = (
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".env",
    ".md", ".txt", ".sh", ".bash", ".zsh", ".html", ".css", ".scss", ".sql",
)

_CRITICAL_THREATS: frozenset[str] = frozenset({
    "instruction-override",
    "role-hijack",
    "system-prompt-leak-attempt",
    "system-tag-injection",
})


class SecurityScanner:
    """Orchestrate secret / threat / output scanners behind one API."""

    SUPPORTED_SCANNERS: tuple[str, ...] = ("secret", "threat", "output")

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize the orchestrator (see class docstring for config keys)."""
        self._config: dict[str, Any] = dict(config or {})
        self._lock = threading.Lock()
        self._custom_rules: dict[str, list[dict[str, Any]]] = {
            "secret": [], "threat": [], "output": [],
        }
        self._secret_scanner: Any = None
        self._secret_scanner_failed = False
        self._threat_scan: Any = None
        self._threat_scan_failed = False
        self._resolve_backends()

    @property
    def min_severity(self) -> ScanSeverity:
        """Return the configured minimum severity."""
        raw = self._config.get("min_severity", "info")
        if isinstance(raw, ScanSeverity):
            return raw
        return ScanSeverity.from_string(str(raw))

    def enabled_scanners(self) -> list[str]:
        """Return scanner names that should run."""
        wanted = self._config.get("scanners") or list(self.SUPPORTED_SCANNERS)
        return [s for s in wanted if s in self.SUPPORTED_SCANNERS]

    def get_available_scanners(self) -> list[str]:
        """Return names of scanners that successfully imported."""
        available: list[str] = []
        if not self._secret_scanner_failed and self._secret_scanner is not None:
            available.append("secret")
        if not self._threat_scan_failed and self._threat_scan is not None:
            available.append("threat")
        available.append("output")
        return available

    def add_custom_rule(self, scanner: str, rule: dict[str, Any]) -> None:
        """Register a custom rule for *scanner* (see module docstring)."""
        if scanner not in self.SUPPORTED_SCANNERS:
            raise ValueError(
                f"Unknown scanner {scanner!r}; expected one of "
                f"{', '.join(self.SUPPORTED_SCANNERS)}"
            )
        with self._lock:
            self._custom_rules[scanner].append(dict(rule))

    def scan_content(
        self,
        content: str,
        scanner: Literal["all", "secret", "threat", "output"] = "all",
        *,
        location: str = "<inline>",
        tool_name: str | None = None,
    ) -> list[ScanFinding]:
        """Run *content* through the requested scanner(s)."""
        if not content:
            return []
        scanners = (
            list(self.SUPPORTED_SCANNERS) if scanner == "all" else [scanner]
        )
        findings: list[ScanFinding] = []
        for name in scanners:
            if name == "secret":
                findings.extend(self._run_secret_scan(content, location))
            elif name == "threat":
                findings.extend(self._run_threat_scan(content, location))
            elif name == "output":
                findings.extend(
                    self._run_output_scan(content, location, tool_name)
                )
        return findings

    def scan_files(self, paths: list[Path]) -> ScanReport:
        """Scan an explicit list of files."""
        report = ScanReport(target=f"{len(paths)} file(s)")
        for path in paths:
            self._scan_one_file(path, report)
        report.finish()
        return report

    def scan_path(
        self,
        path: Path,
        scanners: list[str] | None = None,
    ) -> ScanReport:
        """Scan a single file or recursively scan a directory."""
        path = Path(path)
        report = ScanReport(target=str(path))
        if scanners is not None:
            self._config["scanners"] = scanners
        try:
            if path.is_file():
                self._scan_one_file(path, report)
            elif path.is_dir():
                extensions = self._config.get(
                    "extensions", _DEFAULT_SCAN_EXTENSIONS
                )
                for file in sorted(_walk_files(path, extensions)):
                    self._scan_one_file(file, report)
            else:
                report.metadata["warning"] = f"path not found: {path}"
        finally:
            if scanners is not None:
                self._config.pop("scanners", None)
        report.finish()
        return report

    def _scan_one_file(self, path: Path, report: ScanReport) -> None:
        max_bytes = int(self._config.get("max_bytes", _MAX_FILE_BYTES))
        try:
            if path.stat().st_size > max_bytes:
                report.metadata.setdefault("skipped", []).append(
                    {"path": str(path), "reason": "too large"}
                )
                return
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            report.metadata.setdefault("errors", []).append(
                {"path": str(path), "error": str(exc)}
            )
            return
        report.files_scanned += 1
        report.lines_scanned += content.count("\n") + (1 if content else 0)
        scanners = self.enabled_scanners()
        for line_no, line in enumerate(content.splitlines(), start=1):
            if not line.strip():
                continue
            for finding in self.scan_content(
                line, scanner="all", location=f"{path}:{line_no}"
            ):
                if _severity_rank(finding.severity) < _severity_rank(
                    self.min_severity
                ):
                    continue
                if finding.scanner not in scanners:
                    continue
                report.add(finding)

    def _run_secret_scan(
        self, content: str, location: str
    ) -> list[ScanFinding]:
        scanner = self._secret_scanner
        if scanner is None:
            return []
        try:
            result = scanner.scan(content)
        except Exception:  # noqa: BLE001 — never break the orchestrator
            return []
        findings: list[ScanFinding] = []
        for f in result.findings:
            severity = ScanSeverity.from_string(str(f.severity.value))
            if _severity_rank(severity) < _severity_rank(self.min_severity):
                continue
            findings.append(ScanFinding(
                scanner="secret",
                severity=severity,
                title=f"Secret match: {f.category.value}",
                description=f.description,
                location=location,
                suggestion=(
                    "Rotate the credential, then store the new value "
                    "in your secret manager."
                ),
                metadata={
                    "category": f.category.value,
                    "sample": f.sample,
                    "auto_redact": f.auto_redact,
                    "start": f.start,
                    "end": f.end,
                },
            ))
        return findings

    def _run_threat_scan(
        self, content: str, location: str
    ) -> list[ScanFinding]:
        fn = self._threat_scan
        if fn is None:
            return []
        try:
            threats = fn(content, scope="context")
        except Exception:  # noqa: BLE001
            return []
        findings: list[ScanFinding] = []
        for name in threats:
            sev = (
                ScanSeverity.CRITICAL
                if name in _CRITICAL_THREATS else ScanSeverity.HIGH
            )
            if _severity_rank(sev) < _severity_rank(self.min_severity):
                continue
            findings.append(ScanFinding(
                scanner="threat",
                severity=sev,
                title=f"Threat pattern: {name}",
                description="Prompt-injection or jailbreak heuristic match.",
                location=location,
                suggestion=(
                    "Reject the input or sanitise before adding it to the "
                    "LLM context."
                ),
                metadata={"pattern": name},
            ))
        return findings

    def _run_output_scan(
        self, content: str, location: str, tool_name: str | None
    ) -> list[ScanFinding]:
        scanner = self._secret_scanner
        if scanner is None:
            return []
        try:
            result = scanner.scan(content)
        except Exception:  # noqa: BLE001
            return []
        findings: list[ScanFinding] = []
        for f in result.findings:
            if not f.auto_redact:
                continue
            severity = ScanSeverity.from_string(str(f.severity.value))
            if _severity_rank(severity) < _severity_rank(self.min_severity):
                continue
            findings.append(ScanFinding(
                scanner="output",
                severity=severity,
                title=f"Tool output leaked {f.category.value}",
                description=(
                    f.description
                    + (f" (tool={tool_name})" if tool_name else "")
                ),
                location=location,
                suggestion=(
                    "Redact before forwarding to the model; consider "
                    "tightening tool permissions."
                ),
                metadata={
                    "category": f.category.value,
                    "tool": tool_name,
                    "sample": f.sample,
                },
            ))
        return findings

    def _resolve_backends(self) -> None:
        """Import the upstream scanner modules lazily."""
        try:
            from agent.secret_scanner import SecretScanner  # type: ignore
            self._secret_scanner = SecretScanner()
        except Exception:  # noqa: BLE001
            self._secret_scanner_failed = True
            if self._config.get("fail_on_missing_scanner", False):
                raise
        try:
            from tools.threat_patterns import scan_for_threats  # type: ignore
            self._threat_scan = scan_for_threats
        except Exception:  # noqa: BLE001
            self._threat_scan_failed = True
            if self._config.get("fail_on_missing_scanner", False):
                raise


def _walk_files(root: Path, extensions: Iterable[str]) -> Iterable[Path]:
    """Yield non-hidden files under *root* with one of *extensions*."""
    ext_set = {e.lower() for e in extensions}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part.startswith(".") for part in path.parts):
            continue
        if path.suffix.lower() not in ext_set:
            continue
        yield path


def scan_text(
    text: str,
    *,
    scanner: Literal["all", "secret", "threat", "output"] = "all",
    location: str = "<inline>",
) -> list[ScanFinding]:
    """One-shot helper that runs the default orchestrator on *text*."""
    return SecurityScanner().scan_content(
        text, scanner=scanner, location=location
    )


__all__ = ["ScanFinding", "ScanReport", "ScanSeverity", "SecurityScanner", "scan_text"]
