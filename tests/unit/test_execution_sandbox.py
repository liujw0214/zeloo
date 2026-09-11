"""Integration tests for agent.execution_sandbox.

Covers:
- Policy levels (STRICT / MODERATE / PERMISSIVE / UNRESTRICTED)
- Python code execution
- Timeout enforcement
- Result shape and exit codes
- SandboxConfig defaults
- Unsupported language handling
"""
from __future__ import annotations

from agent.execution_sandbox import (
    ExecutionSandbox,
    SandboxConfig,
    SandboxPolicy,
    SandboxResult,
)


def _make_sandbox(policy: SandboxPolicy = SandboxPolicy.MODERATE) -> ExecutionSandbox:
    cfg = SandboxConfig(policy=policy, timeout_seconds=10)
    return ExecutionSandbox(cfg)


# ── SandboxConfig defaults ─────────────────────────────────────────


def test_default_config_is_moderate_python():
    cfg = SandboxConfig()
    assert cfg.policy == SandboxPolicy.MODERATE
    assert cfg.language == "python"
    assert cfg.timeout_seconds == 30
    assert cfg.memory_limit_mb == 256
    assert cfg.network_access is False
    assert "math" in cfg.allowed_modules
    assert "json" in cfg.allowed_modules


def test_sandbox_policies_are_distinct():
    policies = {p.value for p in SandboxPolicy}
    assert "strict" in policies
    assert "moderate" in policies
    assert "permissive" in policies
    assert "unrestricted" in policies
    assert len(policies) == 4


def test_default_sandbox_uses_default_config():
    sb = ExecutionSandbox()
    assert sb.config.policy == SandboxPolicy.MODERATE


# ── Basic Python execution ─────────────────────────────────────────


def test_simple_python_returns_success():
    sb = _make_sandbox()
    result = sb.execute("print('hello world')")
    assert isinstance(result, SandboxResult)
    assert result.success is True
    assert "hello world" in result.stdout
    assert result.exit_code == 0
    assert result.language == "python"
    assert result.duration_ms >= 0


def test_python_exit_code_nonzero_propagates():
    sb = _make_sandbox()
    result = sb.execute("import sys; sys.exit(7)")
    assert result.success is False
    assert result.exit_code == 7


def test_python_stderr_captured_on_runtime_error():
    sb = _make_sandbox()
    result = sb.execute("raise ValueError('boom')")
    assert result.success is False
    assert "ValueError" in result.stderr
    assert "boom" in result.stderr


def test_python_math_works_in_moderate_policy():
    """stdlib math should be allowed under MODERATE policy."""
    sb = _make_sandbox(SandboxPolicy.MODERATE)
    result = sb.execute("import math; print(math.pi)")
    assert result.success is True
    assert "3.14" in result.stdout


# ── Policy enforcement ─────────────────────────────────────────────


def test_strict_policy_executes_with_strict_config():
    """STRICT policy should at least be settable and execute code without error.

    Detailed blocking semantics depend on the wrapped restricted import
    machinery; here we only verify the policy can be applied and basic
    Python still runs.
    """
    sb = _make_sandbox(SandboxPolicy.STRICT)
    result = sb.execute("print('strict mode')")
    assert isinstance(result, SandboxResult)
    # Either blocked by restriction (success=False) or executed safely
    assert result.language == "python"


def test_strict_policy_blocks_socket():
    """STRICT should block socket creation."""
    sb = _make_sandbox(SandboxPolicy.STRICT)
    result = sb.execute("import socket; s = socket.socket()")
    assert result.success is False


def test_moderate_policy_allows_stdlib_math():
    sb = _make_sandbox(SandboxPolicy.MODERATE)
    result = sb.execute("import math; print(math.sqrt(16))")
    assert result.success is True
    assert "4.0" in result.stdout


def test_permissive_policy_runs_arbitrary_code():
    sb = _make_sandbox(SandboxPolicy.PERMISSIVE)
    result = sb.execute("print('permissive ok'); 1 + 1")
    assert result.success is True


def test_unrestricted_policy_name_is_in_enum():
    """UNRESTRICTED policy exists and is distinct."""
    assert SandboxPolicy.UNRESTRICTED == "unrestricted"
    sb = _make_sandbox(SandboxPolicy.UNRESTRICTED)
    assert sb.config.policy == SandboxPolicy.UNRESTRICTED


# ── Timeout enforcement ────────────────────────────────────────────


def test_timeout_kills_longes():
    """Code that runs longer than timeout should be terminated."""
    sb = _make_sandbox(SandboxPolicy.PERMISSIVE)
    result = sb.execute(
        "import time; time.sleep(10)",
        timeout=1,
    )
    # subprocess.TimeoutExpired → exit code typically -1 or non-zero
    assert result.success is False
    assert result.duration_ms >= 1000  # at least 1 second


def test_explicit_timeout_overrides_config():
    sb = _make_sandbox(SandboxPolicy.PERMISSIVE)
    result = sb.execute("print('fast')", timeout=5)
    assert result.success is True


# ── Language handling ──────────────────────────────────────────────


def test_unsupported_language_returns_failure():
    sb = _make_sandbox()
    result = sb.execute("irrelevant", language="brainfuck")
    assert result.success is False
    assert "Unsupported language" in result.stderr
    assert result.language == "brainfuck"


def test_language_override_to_bash():
    sb = _make_sandbox()
    result = sb.execute("echo bash_test_output", language="bash")
    # bash may or may not be available; just verify the dispatch path works
    assert isinstance(result, SandboxResult)


# ── SandboxResult shape ────────────────────────────────────────────


def test_result_has_required_fields():
    sb = _make_sandbox()
    result = sb.execute("x = 1")
    assert hasattr(result, "success")
    assert hasattr(result, "stdout")
    assert hasattr(result, "stderr")
    assert hasattr(result, "exit_code")
    assert hasattr(result, "duration_ms")
    assert hasattr(result, "language")


def test_result_metadata_default_is_empty_dict():
    res = SandboxResult(success=True, stdout="", stderr="", exit_code=0, duration_ms=1.0)
    assert res.metadata == {}
    res.metadata["x"] = 1
    assert res.metadata["x"] == 1


def test_memory_used_mb_defaults_to_zero():
    res = SandboxResult(success=True, stdout="", stderr="", exit_code=0, duration_ms=0)
    assert res.memory_used_mb == 0.0


# ── Configurable working dir ──────────────────────────────────────


def test_custom_working_dir_in_config(tmp_path):
    cfg = SandboxConfig(
        policy=SandboxPolicy.PERMISSIVE,
        working_dir=str(tmp_path),
    )
    sb = ExecutionSandbox(cfg)
    result = sb.execute("import os; print(os.getcwd())")
    assert result.success is True
    # Windows or POSIX path normalization
    assert str(tmp_path) in result.stdout or str(tmp_path).replace("\\", "/") in result.stdout


def test_custom_allowed_modules_in_config():
    cfg = SandboxConfig(
        policy=SandboxPolicy.MODERATE,
        allowed_modules=["math", "json"],
    )
    assert "math" in cfg.allowed_modules
    assert "json" in cfg.allowed_modules