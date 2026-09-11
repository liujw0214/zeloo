"""Security Skills — dependency scanning, secrets detection, and threat analysis."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["dependency_audit", "secret_detection", "threat_analysis"]


def dependency_audit(
    requirements_path: str | Path | None = None,
    lock_content: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Audit Python dependencies for known vulnerabilities.

    Args:
        requirements_path: Path to requirements.txt or pyproject.toml.
        lock_content: Raw file content if no path.

    Returns:
        A dict with 'vulnerabilities' (list) and 'summary'.
    """
    packages: list[str] = []

    content = ""
    if lock_content:
        content = lock_content
    elif requirements_path:
        p = Path(requirements_path)
        if p.exists():
            content = p.read_text(encoding="utf-8")

    if p := Path("requirements.txt"):
        if p.exists():
            lines = p.read_text(encoding="utf-8").splitlines()
            packages = [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]

    if not packages:
        if "pyproject" in content:
            for line in content.splitlines():
                m = re.match(r'\s*"([^"]+)"', line)
                if m:
                    packages.append(m.group(1))

    if not packages:
        return {
            "vulnerabilities": [],
            "scanned_packages": 0,
            "summary": "No packages found to audit",
        }

    vulnerabilities: list[dict[str, Any]] = []

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--format=json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            installed = {item["name"].lower(): item["version"] for item in json.loads(result.stdout)}
            for pkg_name, version in installed.items():
                if any(pkg_name in p.lower() for p in packages if isinstance(p, str)):
                    vulnerabilities.append({
                        "package": pkg_name,
                        "version": version,
                        "severity": "info",
                        "description": "Package found in environment",
                    })
    except Exception as exc:
        vulnerabilities.append({
            "package": "pip",
            "severity": "warn",
            "description": f"Could not list installed packages: {exc}",
        })

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "audit", "--format=json"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0 and result.stdout:
            data = json.loads(result.stdout)
            for vuln in data.get("vulnerabilities", []):
                vulnerabilities.append({
                    "package": vuln.get("name", "?"),
                    "version": vuln.get("version", "?"),
                    "severity": vuln.get("fix_version", "current"),
                    "description": vuln.get("vulns", [{}])[0].get("description", ""),
                })
    except FileNotFoundError:
        vulnerabilities.append({
            "package": "pip-audit",
            "severity": "info",
            "description": "pip-audit not installed. Run: pip install pip-audit",
        })
    except subprocess.TimeoutExpired:
        vulnerabilities.append({
            "package": "pip-audit",
            "severity": "warn",
            "description": "pip-audit timed out",
        })
    except json.JSONDecodeError:
        pass

    return {
        "vulnerabilities": vulnerabilities,
        "scanned_packages": len(packages),
        "summary": f"{len(vulnerabilities)} finding(s) for {len(packages)} package(s)",
    }


def secret_detection(
    target: str | Path,
    patterns: list[str] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Scan source code for embedded secrets (API keys, tokens, passwords).

    Args:
        target: File or directory to scan.
        patterns: Optional custom regex patterns to match.

    Returns:
        A dict with 'findings' (list of secret detections) and 'summary'.
    """
    default_patterns: list[tuple[str, str]] = [
        (r"sk-[0-9A-Za-z]{20,}", "OpenAI API key"),
        (r"sk-ant-[0-9A-Za-z]{20,}", "Anthropic API key"),
        (r"ghp_[0-9A-Za-z]{36}", "GitHub Personal Access Token"),
        (r"gho_[0-9A-Za-z]{36}", "GitHub OAuth Token"),
        (r"xox[baprs]-[0-9A-Za-z]{10,}", "Slack Token"),
        (r"sq0csp-[0-9A-Za-z_-]{43}", "Square OAuth Secret"),
        (r"(?i)password\s*[=:]\s*['\"][^'\"]{4,}['\"]", "Hardcoded password"),
        (r"(?i)api[_-]?key\s*[=:]\s*['\"][^'\"]{8,}['\"]", "Generic API key"),
        (r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", "Private key block"),
        (r"AIza[0-9A-Za-z_-]{35}", "Google API key"),
        (r"AKIA[0-9A-Z]{16}", "AWS Access Key ID"),
        (r"(?i)bearer\s+[A-Za-z0-9_-]{20,}", "Bearer token"),
    ]

    if patterns:
        custom = [(p, f"custom:{i}") for i, p in enumerate(patterns)]
        default_patterns.extend(custom)

    findings: list[dict[str, Any]] = []
    target_path = Path(target)

    if target_path.is_file():
        files = [target_path]
    elif target_path.is_dir():
        files = list(target_path.rglob("*.py")) + list(target_path.rglob("*.yaml")) + \
            list(target_path.rglob("*.json")) + list(target_path.rglob("*.env"))
    else:
        return {"findings": [], "summary": f"Target not found: {target}"}

    skip_dirs = {".venv", "node_modules", "__pycache__", ".git", ".pytest_cache"}

    for f in files:
        if any(part in f.parts for part in skip_dirs):
            continue

        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        for pattern, label in default_patterns:
            for match in re.finditer(pattern, content):
                line_num = content[: match.start()].count("\n") + 1
                line_text = content.splitlines()[line_num - 1] if line_num <= len(content.splitlines()) else ""

                findings.append({
                    "file": str(f.relative_to(target_path) if target_path.is_dir() else f.name),
                    "line": line_num,
                    "type": label,
                    "match": match.group(0)[:60] + ("..." if len(match.group(0)) > 60 else ""),
                    "context": line_text.strip()[:100],
                })

    secrets_found = [f for f in findings if f["type"] not in ("Private key block",)]
    critical = sum(1 for f in secrets_found if any(t in f["type"].lower() for t in ["token", "api key", "password", "secret"]))
    medium = len(secrets_found) - critical

    return {
        "findings": findings,
        "summary": f"{len(findings)} secret(s): {critical} critical, {medium} medium",
    }


def threat_analysis(
    code_or_config: str,
    target_type: str = "code",
    **kwargs: Any,
) -> dict[str, Any]:
    """Perform security threat analysis on code or configuration.

    Args:
        code_or_config: Source code or config text to analyze.
        target_type: 'code' or 'config'.

    Returns:
        A dict with 'threats', 'risk_score' (0-10), and 'summary'.
    """
    threats: list[dict[str, Any]] = []
    score = 0

    if target_type == "code":
        checks = [
            (r"eval\s*\(", "code_injection", "Use of eval() — potential code injection", 8),
            (r"exec\s*\(", "code_injection", "Use of exec() — potential code injection", 8),
            (r"os\.system\s*\(", "shell_injection", "os.system() — potential shell injection", 7),
            (r"subprocess\.call\s*\([^,]+,\s*shell\s*=\s*True", "shell_injection", "subprocess with shell=True — command injection risk", 7),
            (r"password\s*=\s*['\"][^'\"]{0,8}['\"]", "weak_crypto", "Short or plaintext password", 6),
            (r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "binary_data", "Binary/control characters in string", 3),
            (r"base64\.b64decode", "obfuscation", "Base64 decoding — possible obfuscation", 4),
            (r"hashlib\.(md5|sha1)\s*\(", "weak_hash", "Weak hash algorithm (MD5/SHA1)", 5),
            (r"random\.random\(\)", "weak_random", "random.random() — not cryptographically secure", 4),
            (r"Fernet\s*\(\s*\)", "empty_key", "Fernet() with no key — generates predictable key", 7),
        ]
    else:
        checks = [
            (r'"permissions":\s*"0777"', "overly_permissive", "File permissions 0777 — too permissive", 7),
            (r'"bind":\s*"0\.0\.0\.0"', "wide_binding", "Binding to 0.0.0.0 — accessible from all interfaces", 5),
            (r'"ssl":\s*false', "no_ssl", "SSL/TLS disabled", 8),
            (r'("|\')admin("|\'):\s*("|\')true("|\')', "hardcoded_admin", "Hardcoded admin account", 6),
            (r"debug\s*=\s*true", "debug_enabled", "Debug mode enabled in production", 5),
        ]

    for pattern, threat_type, description, severity in checks:
        matches = list(re.finditer(pattern, code_or_config, re.IGNORECASE))
        if matches:
            for m in matches:
                line_num = code_or_config[:m.start()].count("\n") + 1
                threats.append({
                    "type": threat_type,
                    "severity": severity,
                    "description": description,
                    "line": line_num,
                    "match": m.group(0)[:60],
                })
                score += severity

    risk_score = min(round(score / 10, 1), 10)
    risk_level = "critical" if risk_score >= 7 else "high" if risk_score >= 4 else "medium" if risk_score >= 2 else "low"

    return {
        "threats": threats,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "summary": f"Risk score: {risk_score}/10 ({risk_level}), {len(threats)} threat(s)",
    }
