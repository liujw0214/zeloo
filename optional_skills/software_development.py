"""Software Development Skills — code review, refactoring, and analysis."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["code_review", "refactor", "generate_tests"]


def code_review(
    code: str,
    language: str | None = None,
    ruff: bool = True,
    pylint: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """Perform automated code review on provided code."""
    import tempfile

    ext_map = {
        "python": ".py",
        "javascript": ".js",
        "typescript": ".ts",
        "rust": ".rs",
        "go": ".go",
        "java": ".java",
    }
    ext = ext_map.get(language or "python", ".txt")
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False, mode="w") as tmp:
        tmp.write(code)
        tmp_path = Path(tmp.name)

    issues: list[dict[str, Any]] = []

    if ruff:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "ruff", "check", str(tmp_path), "--output-format=text"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            for line in result.stdout.splitlines():
                if ":" in line:
                    parts = line.split(":", 3)
                    if len(parts) >= 3:
                        issues.append({
                            "tool": "ruff",
                            "line": parts[1],
                            "col": parts[2] if len(parts) > 2 else "0",
                            "message": parts[3] if len(parts) > 3 else "",
                            "severity": "error" if "error" in line.lower() else "warning",
                        })
            if result.returncode != 0 and not issues:
                issues.append({"tool": "ruff", "message": result.stdout[:200], "severity": "info"})
        except FileNotFoundError:
            issues.append({"tool": "ruff", "message": "ruff not installed", "severity": "info"})
        except subprocess.TimeoutExpired:
            issues.append({"tool": "ruff", "message": "ruff timed out", "severity": "info"})

    tmp_path.unlink(missing_ok=True)

    severity_counts = {"error": 0, "warning": 0, "info": 0}
    for issue in issues:
        sev = issue.get("severity", "info")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    if issues:
        summary = f"{len(issues)} issue(s) found"
    else:
        summary = "No issues found"

    return {"issues": issues, "summary": summary, "severity_counts": severity_counts}


def refactor(
    code: str,
    target: str,
    language: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Suggest refactorings for the provided code."""
    suggestions: list[dict[str, Any]] = []
    summary = ""

    if not code or len(code.strip()) < 10:
        return {"suggestions": [], "summary": "Code too short to refactor."}

    lines = code.splitlines()

    if target == "extract_function":
        function_like = any(kw in code for kw in ["def ", "function ", "fn ", "func "])
        if function_like and len(lines) > 20:
            suggestions.append({
                "type": "extract_function",
                "priority": "high",
                "description": "Large function detected. Consider splitting into smaller units.",
                "rule": "Functions should do one thing well (Single Responsibility Principle).",
            })
        summary = f"{len(suggestions)} extraction suggestion(s)"

    elif target == "simplify_conditionals":
        base_indent = lines[0].count("    ") if lines else 0
        deep_nesting = max(
            max(0, line.count("    ") - base_indent) for line in lines
        )
        if deep_nesting >= 4:
            suggestions.append({
                "type": "simplify_conditionals",
                "priority": "high",
                "description": f"Code has {deep_nesting} levels of nesting. "
                "Consider extracting helper functions or using early returns.",
            })
        summary = f"{len(suggestions)} simplification suggestion(s)"

    elif target == "remove_duplication":
        seen: dict[str, int] = {}
        for line in lines:
            stripped = line.strip()
            if len(stripped) > 30:
                seen[stripped] = seen.get(stripped, 0) + 1
        dupes = [(v, k) for k, v in seen.items() if v >= 2]
        for count, text in sorted(dupes, reverse=True):
            suggestions.append({
                "type": "remove_duplication",
                "priority": "medium",
                "description": f"Duplicate line found {count} times",
                "code": text[:80],
            })
        summary = f"{len(suggestions)} duplication issue(s)"

    elif target == "improve_naming":
        for line in lines:
            if any(kw in line for kw in ["def ", "class ", "function "]):
                if any(w.islower() and len(w) <= 2 for w in line.split()):
                    suggestions.append({
                        "type": "improve_naming",
                        "priority": "low",
                        "description": "Line may use unclear variable names",
                        "line": line.strip()[:80],
                    })
        summary = f"{len(suggestions)} naming suggestion(s)"

    else:
        summary = f"Unknown refactoring target: {target}"

    return {"suggestions": suggestions, "summary": summary}


def generate_tests(
    code: str,
    framework: str = "pytest",
    language: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Generate unit tests for the provided code."""
    if not code or len(code.strip()) < 5:
        return {"test_code": "", "summary": "Code too short to generate tests."}

    code_lines = [ln for ln in code.splitlines() if ln.strip() and not ln.strip().startswith("#")]

    functions: list[str] = []
    for line in code_lines:
        stripped = line.strip()
        if stripped.startswith("def "):
            name = stripped.split("(")[0].replace("def ", "").strip()
            functions.append(name)

    test_lines: list[str] = []
    if framework == "pytest":
        test_lines.append("import pytest")
        test_lines.append("")
        for fn in functions:
            cls_name = fn.title().replace("_", "")
            test_lines.append(f"class Test{cls_name}:")
            test_lines.append(f"    def test_{fn}(self):")
            test_lines.append(f"        # TODO: implement test for {fn}")
            test_lines.append("        pass")
            test_lines.append("")
    else:
        test_lines.append("import unittest")
        test_lines.append("")
        for fn in functions:
            cls_name = fn.title().replace("_", "")
            test_lines.append(f"class Test{cls_name}(unittest.TestCase):")
            test_lines.append(f"    def test_{fn}(self):")
            test_lines.append(f"        # TODO: implement test for {fn}")
            test_lines.append("        pass")
            test_lines.append("")

    return {
        "test_code": "\n".join(test_lines),
        "summary": f"Generated {len(functions)} test(s) using {framework}",
    }
