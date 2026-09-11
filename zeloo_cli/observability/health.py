"""Health checks for Zeloo CLI components."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class HealthStatus(StrEnum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass
class HealthResult:
    component: str
    status: HealthStatus
    message: str
    details: dict | None = None


def check_python_version() -> HealthResult:
    import sys
    v = sys.version_info
    if v >= (3, 11):
        return HealthResult(
            component="python",
            status=HealthStatus.OK,
            message=f"Python {v.major}.{v.minor}.{v.micro} (>= 3.11)",
        )
    return HealthResult(
        component="python",
        status=HealthStatus.ERROR,
        message=f"Python {v.major}.{v.minor} too old (need >= 3.11)",
    )


def check_dependencies() -> HealthResult:
    import importlib.util
    core = ["pydantic", "httpx", "openai", "anthropic", "pytest", "ruff"]
    missing = []
    for name in core:
        if importlib.util.find_spec(name) is None:
            missing.append(name)
    if not missing:
        return HealthResult(
            component="dependencies",
            status=HealthStatus.OK,
            message=f"All core dependencies present: {', '.join(core)}",
        )
    return HealthResult(
        component="dependencies",
        status=HealthStatus.ERROR,
        message=f"Missing: {', '.join(missing)}",
        details={"missing": missing},
    )


def check_zeloo_home() -> HealthResult:
    import os
    home = os.environ.get("zeloo_HOME") or str(Path.home() / ".Zeloo")
    p = Path(home)
    if p.exists():
        if p.is_dir():
            return HealthResult(
                component="zeloo_home",
                status=HealthStatus.OK,
                message=f"zeloo_HOME exists: {home}",
            )
        return HealthResult(
            component="zeloo_home",
            status=HealthStatus.WARNING,
            message=f"zeloo_HOME exists but is not a directory: {home}",
        )
    return HealthResult(
        component="zeloo_home",
        status=HealthStatus.WARNING,
        message=f"zeloo_HOME does not exist yet (will be created on first run): {home}",
    )


def check_api_keys() -> HealthResult:
    import os
    required = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"]
    missing = [k for k in required if not os.environ.get(k)]
    if not missing:
        return HealthResult(
            component="api_keys",
            status=HealthStatus.OK,
            message="All required API keys present",
        )
    return HealthResult(
        component="api_keys",
        status=HealthStatus.WARNING,
        message=f"Missing keys: {', '.join(missing)}",
        details={"missing": missing},
    )


def check_git_repo() -> HealthResult:
    import subprocess
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )
        if result.returncode == 0 and result.stdout.strip() == "true":
            return HealthResult(
                component="git_repo",
                status=HealthStatus.OK,
                message="Git repository detected",
            )
        return HealthResult(
            component="git_repo",
            status=HealthStatus.WARNING,
            message="Not a git repository",
        )
    except FileNotFoundError:
        return HealthResult(
            component="git_repo",
            status=HealthStatus.WARNING,
            message="Git not available",
        )


def check_all() -> list[HealthResult]:
    """Run all health checks and return results."""
    return [
        check_python_version(),
        check_dependencies(),
        check_zeloo_home(),
        check_api_keys(),
        check_git_repo(),
    ]


class HealthChecker:
    def check_all(self) -> list[HealthResult]:
        return check_all()

    def get_status(self) -> HealthStatus:
        results = self.check_all()
        if any(r.status == HealthStatus.ERROR for r in results):
            return HealthStatus.ERROR
        if any(r.status == HealthStatus.WARNING for r in results):
            return HealthStatus.WARNING
        return HealthStatus.OK
