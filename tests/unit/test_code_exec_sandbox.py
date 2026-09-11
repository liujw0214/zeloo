"""Tests for the execute_code sandbox hardening — preflight, env strip, isolation."""

# ruff: noqa: E402
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

import pytest

from tools.code_exec import (
    _BLOCKED_MODULES,
    _preflight_check,
    _strip_env,
    execute_code,
)

# ── _preflight_check tests ───────────────────────────────────────────


def test_preflight_allows_safe_code() -> None:
    """Normal Python code passes the preflight check."""
    code = "x = 1 + 2\nprint(x)\n"
    assert _preflight_check(code) is None


def test_preflight_blocks_socket_import() -> None:
    """`import socket` is blocked."""
    assert _preflight_check("import socket\n") is not None


def test_preflight_blocks_from_socket() -> None:
    """`from socket import *` is blocked."""
    assert _preflight_check("from socket import socket\n") is not None


def test_preflight_blocks_subprocess_import() -> None:
    """`import subprocess` is blocked."""
    assert _preflight_check("import subprocess\n") is not None


def test_preflight_blocks_ctypes() -> None:
    """`import ctypes` is blocked."""
    assert _preflight_check("import ctypes\n") is not None


def test_preflight_blocks_multiprocessing() -> None:
    """`import multiprocessing` is blocked."""
    assert _preflight_check("import multiprocessing\n") is not None


def test_preflight_blocks_threading() -> None:
    """`import threading` is blocked."""
    assert _preflight_check("import threading\n") is not None


def test_preflight_blocks_os_system() -> None:
    """`os.system(...)` is blocked by pattern."""
    assert _preflight_check("import os\nos.system('ls')\n") is not None


def test_preflight_blocks_os_popen() -> None:
    """`os.popen(...)` is blocked by pattern."""
    assert _preflight_check("import os\nos.popen('ls')\n") is not None


def test_preflight_blocks_os_exec() -> None:
    """`os.exec*` is blocked by pattern."""
    assert _preflight_check("import os\nos.execvp('ls', [])\n") is not None


def test_preflight_blocks_dunder_import_subprocess() -> None:
    """`__import__('subprocess')` is blocked."""
    assert _preflight_check("__import__('subprocess')\n") is not None


def test_preflight_blocks_dunder_import_socket() -> None:
    """`__import__('socket')` is blocked."""
    assert _preflight_check("__import__('socket')\n") is not None


def test_preflight_allows_similar_module_names() -> None:
    """Modules that merely contain a blocked name as substring are allowed."""
    # `socketserver` is not the same as `socket`
    assert _preflight_check("import socketserver\n") is None
    # `os` itself is fine (only os.system/popen/exec are blocked)
    assert _preflight_check("import os\nprint(os.getcwd())\n") is None


def test_all_blocked_modules_are_covered() -> None:
    """Every module in _BLOCKED_MODULES is actually blocked by preflight."""
    for mod in _BLOCKED_MODULES:
        assert _preflight_check(f"import {mod}\n") is not None, mod
        assert _preflight_check(f"from {mod} import x\n") is not None, mod


# ── _strip_env tests ─────────────────────────────────────────────────


def test_strip_env_removes_api_keys() -> None:
    """Variables starting with sensitive prefixes are removed."""
    os.environ["OPENAI_API_KEY"] = "sk-secret"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "aws-secret"
    os.environ["zeloo_HOME"] = "/home/user"
    try:
        clean = _strip_env()
        assert "OPENAI_API_KEY" not in clean
        assert "AWS_SECRET_ACCESS_KEY" not in clean
        assert "zeloo_HOME" not in clean
    finally:
        del os.environ["OPENAI_API_KEY"]
        del os.environ["AWS_SECRET_ACCESS_KEY"]
        del os.environ["zeloo_HOME"]


def test_strip_env_keeps_path_and_python() -> None:
    """PATH and PYTHON* variables are kept so the interpreter works."""
    os.environ["PATH"] = "/usr/bin"
    os.environ["PYTHONPATH"] = "/lib/python"
    try:
        clean = _strip_env()
        assert clean.get("PATH") == "/usr/bin"
        assert clean.get("PYTHONPATH") == "/lib/python"
    finally:
        del os.environ["PATH"]
        del os.environ["PYTHONPATH"]


def test_strip_env_sets_path_default() -> None:
    """PATH is always present even if not in the original env."""
    if "PATH" in os.environ:
        old_path = os.environ.pop("PATH")
    else:
        old_path = None
    try:
        clean = _strip_env()
        assert "PATH" in clean
    finally:
        if old_path is not None:
            os.environ["PATH"] = old_path


# ── execute_code integration tests ───────────────────────────────────


@pytest.mark.slow
def test_execute_code_blocks_socket_in_subprocess() -> None:
    """The preflight check prevents socket import from running."""
    result = execute_code("import socket\nprint('should not run')")
    assert "blocked" in result.lower() or "socket" in result.lower()


@pytest.mark.slow
def test_execute_code_runs_in_temp_dir() -> None:
    """Code runs in a temp directory, not the project root."""
    result = execute_code("import os\nprint(os.getcwd())")
    # The cwd should be a temp directory, not the project root
    cwd_line = result.strip().split("\n")[0]
    assert "primus" not in cwd_line
    assert "Zeloo-sandbox" in cwd_line or "tmp" in cwd_line.lower() or "Temp" in cwd_line


@pytest.mark.slow
def test_execute_code_cannot_read_project_files() -> None:
    """Code cannot read project files via relative paths from temp cwd."""
    # config.yaml.example exists in the project root but should not be
    # accessible from the sandbox's temp working directory.
    result = execute_code(
        "import os\nprint(os.path.exists('config.yaml.example'))"
    )
    assert "False" in result


@pytest.mark.slow
def test_execute_code_env_vars_stripped() -> None:
    """Sensitive env vars are not visible inside the sandbox."""
    os.environ["SECRET_TEST_VAR"] = "super-secret-value"
    try:
        result = execute_code("import os\nprint(os.environ.get('SECRET_TEST_VAR', 'NOT_FOUND'))")
        assert "NOT_FOUND" in result
        assert "super-secret-value" not in result
    finally:
        del os.environ["SECRET_TEST_VAR"]


@pytest.mark.slow
def test_execute_code_returns_output_for_simple_code() -> None:
    """Simple arithmetic code returns correct output."""
    result = execute_code("print(2 + 2)")
    assert "4" in result


@pytest.mark.slow
def test_execute_code_truncates_long_output() -> None:
    """Output longer than DEFAULT_MAX_OUTPUT is truncated."""
    result = execute_code("print('x' * 20000)")
    assert "[truncated]" in result
    assert len(result) < 20000


if __name__ == "__main__":
    test_preflight_allows_safe_code()
    test_preflight_blocks_socket_import()
    test_preflight_blocks_from_socket()
    test_preflight_blocks_subprocess_import()
    test_preflight_blocks_ctypes()
    test_preflight_blocks_multiprocessing()
    test_preflight_blocks_threading()
    test_preflight_blocks_os_system()
    test_preflight_blocks_os_popen()
    test_preflight_blocks_os_exec()
    test_preflight_blocks_dunder_import_subprocess()
    test_preflight_blocks_dunder_import_socket()
    test_preflight_allows_similar_module_names()
    test_all_blocked_modules_are_covered()
    test_strip_env_removes_api_keys()
    test_strip_env_keeps_path_and_python()
    test_strip_env_sets_path_default()
    test_execute_code_blocks_socket_in_subprocess()
    test_execute_code_runs_in_temp_dir()
    test_execute_code_cannot_read_project_files()
    test_execute_code_env_vars_stripped()
    test_execute_code_returns_output_for_simple_code()
    test_execute_code_truncates_long_output()
    print("All code_exec sandbox tests passed!")
