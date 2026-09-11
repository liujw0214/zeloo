#!/usr/bin/env python3
"""Zeloo self-repair — diagnose and fix common installation issues."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path


def check_python_version() -> bool:
    print(f"Python {sys.version_info.major}.{sys.version_info.minor}... ", end="")
    if sys.version_info < (3, 11):  # noqa: UP036
        print("FAIL (need 3.11+)")
        return False
    print("OK")
    return True


def check_dependencies() -> bool:
    print("Core dependencies...")
    required = ["pydantic", "httpx", "openai", "anthropic", "pytest", "ruff"]
    all_ok = True
    for name in required:
        try:
            importlib.import_module(name.replace("-", "_"))
            print(f"  {name}: OK")
        except ImportError:
            print(f"  {name}: MISSING")
            all_ok = False
    return all_ok


def check_api_keys() -> bool:
    print("Environment variables...")
    keys = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"]
    found = [k for k in keys if os.environ.get(k)]
    if found:
        for k in found:
            print(f"  {k}: set")
    else:
        print("  No API keys detected (LLM calls will fail without keys)")
    return True


def check_zeloo_home() -> bool:
    home = os.environ.get("zeloo_HOME") or os.path.expanduser("~/.Zeloo")
    path = Path(home)
    print(f"zeloo_HOME={home}...")
    if path.exists():
        print(f"  {path}: OK")
    else:
        print(f"  {path}: not yet created (will be created on first run)")
    return True


def check_git_repo() -> bool:
    root = Path(__file__).resolve().parents[1]
    if not (root / ".git").exists():
        return True
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    print(f"Git repo: {root.name}")
    if result.returncode == 0:
        print(f"  HEAD: {result.stdout[:8]}")
        return True
    print("  git status check: FAIL")
    return False


def fix_permissions() -> bool:
    script = Path(__file__).resolve()
    try:
        script.chmod(0o755)
        print(f"Fixed +x on {script.name}")
        return True
    except OSError:
        print(f"Could not chmod {script} (try sudo)")
        return False


def main() -> int:
    print("=== Zeloo self-repair ===\n")
    checks = [
        check_python_version(),
        check_dependencies(),
        check_api_keys(),
        check_zeloo_home(),
        check_git_repo(),
    ]
    print()
    fix_permissions()
    print()
    if all(checks):
        print("All checks passed.")
        return 0
    print("Some checks failed — run: pip install -e .")
    return 1


if __name__ == "__main__":
    sys.exit(main())