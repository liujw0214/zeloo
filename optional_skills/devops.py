"""DevOps Skills — CI/CD pipeline analysis and infrastructure diagnostics."""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["cicd_analysis", "docker_diagnostics", "k8s_health"]


def cicd_analysis(
    config_path: str | Path | None = None,
    config_content: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Analyze a CI/CD pipeline configuration and suggest optimizations.

    Args:
        config_path: Path to a GitHub Actions YAML file.
        config_content: Raw YAML content if no path is available.

    Returns:
        A dict with 'issues', 'suggestions', and 'summary'.
    """
    content = ""
    if config_content:
        content = config_content
    elif config_path:
        p = Path(config_path)
        if p.exists():
            content = p.read_text(encoding="utf-8")
        else:
            return {"issues": [], "suggestions": [], "summary": f"File not found: {config_path}"}

    suggestions: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    if "cache" not in content.lower() and "restore-cache" not in content.lower():
        suggestions.append({
            "priority": "high",
            "rule": "Caching",
            "description": "No caching configured. Add cache actions to speed up pipelines.",
            "example": "  - uses: actions/cache@v4\n    with:\n      path: ~/.cache/pip",
        })

    if "timeout-minutes" not in content:
        suggestions.append({
            "priority": "medium",
            "rule": "Timeouts",
            "description": "No timeout-minutes set. Jobs may run indefinitely.",
        })

    if content.count("run:") > 10:
        suggestions.append({
            "priority": "medium",
            "rule": "Step consolidation",
            "description": f"Detected {content.count('run:')} run steps. Consider consolidating shell commands.",
        })

    uses_count = len(re.findall(r"uses:", content))
    if uses_count > 15:
        suggestions.append({
            "priority": "low",
            "rule": "Action count",
            "description": f"{uses_count} 'uses:' steps found. Pin to specific SHA versions for reproducibility.",
        })

    if "on: [push]" in content or "on: push" in content:
        issues.append({
            "severity": "medium",
            "rule": "Trigger scope",
            "description": "Pipeline triggers on all push events. Consider limiting to specific branches.",
        })

    return {
        "issues": issues,
        "suggestions": suggestions,
        "summary": f"{len(issues)} issue(s), {len(suggestions)} suggestion(s)",
    }


def docker_diagnostics(
    image: str | None = None,
    compose_path: str | Path | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run Docker health and configuration diagnostics.

    Args:
        image: Docker image name to inspect.
        compose_path: Path to docker-compose.yml.

    Returns:
        A dict with 'checks' (per-check status list) and 'summary'.
    """
    checks: list[dict[str, Any]] = []

    try:
        result = subprocess.run(
            ["docker", "--version"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            checks.append({
                "check": "docker_installed",
                "status": "ok",
                "detail": result.stdout.strip(),
            })
        else:
            checks.append({
                "check": "docker_installed",
                "status": "fail",
                "detail": result.stderr.strip()[:100],
            })
    except FileNotFoundError:
        checks.append({
            "check": "docker_installed",
            "status": "fail",
            "detail": "docker command not found in PATH",
        })
    except subprocess.TimeoutExpired:
        checks.append({
            "check": "docker_installed",
            "status": "warn",
            "detail": "docker check timed out",
        })

    if compose_path:
        p = Path(compose_path)
        if p.is_file():
            content = p.read_text(encoding="utf-8")
            if "restart:" not in content:
                checks.append({
                    "check": "restart_policy",
                    "status": "warn",
                    "detail": "No restart policy found in docker-compose.yml",
                })
            if "healthcheck:" not in content:
                checks.append({
                    "check": "healthcheck",
                    "status": "warn",
                    "detail": "No healthcheck defined — containers won't be auto-restarted on crash",
                })
            else:
                checks.append({
                    "check": "healthcheck",
                    "status": "ok",
                    "detail": "Healthcheck configured",
                })
        else:
            checks.append({
                "check": "compose_file",
                "status": "warn",
                "detail": f"File not found: {compose_path}",
            })

    if image:
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", image],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                checks.append({
                    "check": "image_exists",
                    "status": "ok",
                    "detail": f"Image {image} found",
                })
            else:
                checks.append({
                    "check": "image_exists",
                    "status": "warn",
                    "detail": f"Image {image} not found locally",
                })
        except subprocess.TimeoutExpired:
            checks.append({
                "check": "image_exists",
                "status": "warn",
                "detail": "Image inspection timed out",
            })

    ok = sum(1 for c in checks if c["status"] == "ok")
    fail = sum(1 for c in checks if c["status"] == "fail")
    warn = sum(1 for c in checks if c["status"] == "warn")

    return {
        "checks": checks,
        "summary": f"{len(checks)} checks: {ok} ok, {fail} fail, {warn} warn",
    }


def k8s_health(
    namespace: str = "default",
    context: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run Kubernetes cluster health checks via kubectl.

    Args:
        namespace: Kubernetes namespace to inspect.
        context: kubectl context override.

    Returns:
        A dict with 'components' status list and 'summary'.
    """
    components: list[dict[str, Any]] = []

    cmd_base = ["kubectl"]
    if context:
        cmd_base.extend(["--context", context])
    cmd_base.extend(["-n", namespace])

    checks = [
        ("nodes", "kubectl get nodes"),
        ("pods", "kubectl get pods"),
        ("services", "kubectl get svc"),
    ]

    for name, _ in checks:
        cmd = cmd_base + (["get", name, "-o", "wide"] if name != "pods" else ["get", "pods"])
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                lines = result.stdout.strip().splitlines()
                components.append({
                    "component": name,
                    "status": "ok",
                    "count": len(lines) - 1,
                    "detail": f"{len(lines) - 1} resource(s)",
                })
            else:
                components.append({
                    "component": name,
                    "status": "fail",
                    "detail": result.stderr.strip()[:150],
                })
        except FileNotFoundError:
            components.append({
                "component": name,
                "status": "fail",
                "detail": "kubectl not found in PATH",
            })
            break
        except subprocess.TimeoutExpired:
            components.append({
                "component": name,
                "status": "warn",
                "detail": "kubectl command timed out",
            })

    ok = sum(1 for c in components if c["status"] == "ok")
    fail = sum(1 for c in components if c["status"] == "fail")

    return {
        "components": components,
        "summary": f"{ok} ok, {fail} failing",
    }
