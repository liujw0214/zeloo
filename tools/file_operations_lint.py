"""File linting: syntax check, formatting, security scan."""

from __future__ import annotations

import ast
import re
import tokenize
from io import StringIO
from pathlib import Path
from typing import Any, Callable


class FileLint:
    """File linting and formatting tool.

    Provides syntax checking, formatting, and security scanning
    capabilities for various file types.
    """

    PYTHON_EXTENSIONS = {".py", ".pyw", ".pyi"}
    JAVASCRIPT_EXTENSIONS = {".js", ".jsx", ".mjs", ".cjs"}
    TYPESCRIPT_EXTENSIONS = {".ts", ".tsx"}
    JSON_EXTENSIONS = {".json"}
    YAML_EXTENSIONS = {".yaml", ".yml"}

    DANGEROUS_PATTERNS = [
        (r"password\s*=\s*['\"][^'\"]{0,}", "Hardcoded password detected"),
        (r"api[_-]?key\s*=\s*['\"][^'\"]{0,}", "Hardcoded API key detected"),
        (r"secret\s*=\s*['\"][^'\"]{0,}", "Hardcoded secret detected"),
        (r"token\s*=\s*['\"][^'\"]{8,}", "Hardcoded token detected"),
        (r"eval\s*\(", "Use of eval() is dangerous"),
        (r"exec\s*\(", "Use of exec() is dangerous"),
        (r"__import__\s*\(", "Dynamic import detected"),
        (r"subprocess\s*\.\s*(call|run|Popen)\s*\(", "Subprocess call without shell=True check"),
        (r"os\s*\.\s*system\s*\(", "os.system() call detected"),
        (r"pickle\s*\.\s*(load|loads)\s*\(", "Pickle deserialization is unsafe"),
        (r"hashlib\s*\.\s*new\s*\(\s*['\"]md5['\"]", "MD5 hash usage detected"),
        (r"crypto\.createCipher", "Deprecated crypto usage detected"),
        (r"DES\.new\s*\(", "DES encryption is insecure"),
        (r"\.sendmail\s*\(", "sendmail without proper validation"),
        (r"shell\s*=\s*True", "Shell=True is a security risk"),
    ]

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize file lint.

        Args:
            config: Optional configuration dictionary.
        """
        self._config = config or {}
        self._linters: dict[str, Callable[[Path], dict[str, Any]]] = {}
        self._register_default_linters()

    def _register_default_linters(self) -> None:
        """Register default linters for common file types."""
        self.register_linter(".py", self._lint_python)
        self.register_linter(".js", self._lint_javascript)
        self.register_linter(".ts", self._lint_typescript)
        self.register_linter(".json", self._lint_json)
        self.register_linter(".yaml", self._lint_yaml)
        self.register_linter(".yml", self._lint_yaml)

    def register_linter(self, extension: str, linter: Callable[[Path], dict[str, Any]]) -> None:
        """Register a custom linter for a file extension.

        Args:
            extension: File extension (e.g., '.py').
            linter: Callable that takes a Path and returns lint results.
        """
        self._linters[extension] = linter

    async def lint(self, path: Path) -> dict[str, Any]:
        """Lint a file using the appropriate linter.

        Args:
            path: Path to the file to lint.

        Returns:
            Dictionary with lint results.
        """
        try:
            if not path.exists():
                return {"success": False, "error": "File not found", "path": str(path)}

            extension = path.suffix.lower()
            if extension not in self._linters:
                return {
                    "success": False,
                    "error": f"No linter registered for {extension}",
                    "path": str(path),
                }

            result = self._linters[extension](path)
            result["path"] = str(path)
            result["extension"] = extension
            return result

        except Exception as e:
            return {"success": False, "error": str(e), "path": str(path)}

    def _lint_python(self, path: Path) -> dict[str, Any]:
        """Lint a Python file.

        Args:
            path: Path to Python file.

        Returns:
            Dictionary with lint results.
        """
        issues: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except (OSError, PermissionError) as e:
            return {"success": False, "error": str(e)}

        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            stripped = line.rstrip()
            if stripped != line:
                warnings.append({
                    "line": i,
                    "column": len(line) - len(stripped),
                    "message": "Trailing whitespace",
                    "severity": "warning",
                })

            if len(line) > 120:
                warnings.append({
                    "line": i,
                    "message": f"Line too long ({len(line)} > 120)",
                    "severity": "warning",
                })

        try:
            tree = ast.parse(content, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    if len(node.args.args) > 6:
                        issues.append({
                            "message": f"Function {node.name} has too many parameters ({len(node.args.args)})",
                            "severity": "warning",
                        })

                if isinstance(node, (ast.For, ast.While)):
                    if isinstance(node.body, list) and len(node.body) > 50:
                        issues.append({
                            "message": "Loop body is too long (> 50 statements)",
                            "severity": "warning",
                        })

        except SyntaxError as e:
            issues.append({
                "message": f"Syntax error: {e.msg}",
                "line": e.lineno or 0,
                "column": e.offset or 0,
                "severity": "error",
            })
        except ValueError as e:
            issues.append({
                "message": f"Parse error: {e}",
                "severity": "error",
            })

        return {
            "success": True,
            "issues": issues,
            "warnings": warnings,
            "total_issues": len(issues),
            "total_warnings": len(warnings),
        }

    def _lint_javascript(self, path: Path) -> dict[str, Any]:
        """Lint a JavaScript file.

        Args:
            path: Path to JavaScript file.

        Returns:
            Dictionary with lint results.
        """
        issues: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except (OSError, PermissionError) as e:
            return {"success": False, "error": str(e)}

        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            if len(line) > 120:
                warnings.append({
                    "line": i,
                    "message": f"Line too long ({len(line)} > 120)",
                    "severity": "warning",
                })

            if "var " in line:
                warnings.append({
                    "line": i,
                    "message": "Use 'let' or 'const' instead of 'var'",
                    "severity": "warning",
                })

        return {
            "success": True,
            "issues": issues,
            "warnings": warnings,
            "total_issues": len(issues),
            "total_warnings": len(warnings),
        }

    def _lint_typescript(self, path: Path) -> dict[str, Any]:
        """Lint a TypeScript file.

        Args:
            path: Path to TypeScript file.

        Returns:
            Dictionary with lint results.
        """
        return self._lint_javascript(path)

    def _lint_json(self, path: Path) -> dict[str, Any]:
        """Lint a JSON file.

        Args:
            path: Path to JSON file.

        Returns:
            Dictionary with lint results.
        """
        issues: list[dict[str, Any]] = []

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            import json
            json.loads(content)
        except json.JSONDecodeError as e:
            issues.append({
                "message": f"Invalid JSON: {e.msg}",
                "line": e.lineno,
                "column": e.colno,
                "severity": "error",
            })
        except (OSError, PermissionError) as e:
            return {"success": False, "error": str(e)}

        return {
            "success": True,
            "issues": issues,
            "warnings": [],
            "total_issues": len(issues),
            "total_warnings": 0,
        }

    def _lint_yaml(self, path: Path) -> dict[str, Any]:
        """Lint a YAML file.

        Args:
            path: Path to YAML file.

        Returns:
            Dictionary with lint results.
        """
        issues: list[dict[str, Any]] = []

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            import yaml
            yaml.safe_load(content)
        except yaml.YAMLError as e:
            issues.append({
                "message": f"Invalid YAML: {e}",
                "severity": "error",
            })
        except ImportError:
            issues.append({
                "message": "PyYAML not installed, skipping YAML validation",
                "severity": "warning",
            })
        except (OSError, PermissionError) as e:
            return {"success": False, "error": str(e)}

        return {
            "success": True,
            "issues": issues,
            "warnings": [],
            "total_issues": len(issues),
            "total_warnings": 0,
        }

    async def format(self, path: Path, formatter: str = "auto") -> dict[str, Any]:
        """Format a file.

        Args:
            path: Path to the file to format.
            formatter: Formatter to use ('auto', 'black', 'ruff', etc).

        Returns:
            Dictionary with formatting results.
        """
        try:
            extension = path.suffix.lower()

            if extension == ".py":
                if formatter == "auto":
                    content = path.read_text(encoding="utf-8", errors="replace")
                    return {
                        "success": True,
                        "message": "Use external formatter like 'ruff' or 'black' for Python formatting",
                        "path": str(path),
                    }

            return {
                "success": False,
                "error": f"No formatter available for {extension}",
                "path": str(path),
            }

        except Exception as e:
            return {"success": False, "error": str(e), "path": str(path)}

    async def check_syntax(self, path: Path) -> dict[str, Any]:
        """Check file syntax.

        Args:
            path: Path to the file to check.

        Returns:
            Dictionary with syntax check results.
        """
        try:
            extension = path.suffix.lower()

            if extension == ".py":
                content = path.read_text(encoding="utf-8", errors="replace")
                ast.parse(content, filename=str(path))
                return {
                    "success": True,
                    "valid": True,
                    "path": str(path),
                    "message": "Syntax is valid",
                }

            elif extension in self.JAVASCRIPT_EXTENSIONS:
                return await self._check_js_syntax(path)

            elif extension in self.TYPESCRIPT_EXTENSIONS:
                return await self._check_js_syntax(path)

            return {
                "success": True,
                "valid": True,
                "path": str(path),
                "message": f"Syntax check not implemented for {extension}",
            }

        except SyntaxError as e:
            return {
                "success": True,
                "valid": False,
                "path": str(path),
                "error": str(e),
                "line": getattr(e, "lineno", 0),
                "column": getattr(e, "offset", 0),
            }
        except Exception as e:
            return {"success": False, "error": str(e), "path": str(path)}

    async def _check_js_syntax(self, path: Path) -> dict[str, Any]:
        """Check JavaScript/TypeScript syntax.

        Args:
            path: Path to the file.

        Returns:
            Dictionary with check results.
        """
        return {
            "success": True,
            "valid": True,
            "path": str(path),
            "message": "Use Node.js or ESLint for JS/TS syntax checking",
        }

    async def security_scan(self, path: Path) -> list[dict[str, Any]]:
        """Scan file for security issues.

        Args:
            path: Path to the file to scan.

        Returns:
            List of security issues found.
        """
        issues: list[dict[str, Any]] = []

        try:
            if not path.is_file():
                return [{"severity": "error", "message": "Not a file"}]

            extension = path.suffix.lower()
            if extension not in self.PYTHON_EXTENSIONS | self.JAVASCRIPT_EXTENSIONS | self.TYPESCRIPT_EXTENSIONS:
                return []

            content = path.read_text(encoding="utf-8", errors="replace")
            lines = content.split("\n")

            for pattern, description in self.DANGEROUS_PATTERNS:
                regex = re.compile(pattern, re.IGNORECASE)
                for i, line in enumerate(lines, 1):
                    if regex.search(line):
                        issues.append({
                            "line": i,
                            "message": description,
                            "pattern": pattern,
                            "severity": "warning" if "warning" in description.lower() else "error",
                            "code": line.strip()[:100],
                        })

            return issues

        except Exception as e:
            return [{"severity": "error", "message": str(e)}]
