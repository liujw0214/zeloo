"""Unit tests for `scripts/_install_repair.py`."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

SCRIPTS_DIR = PROJECT_ROOT + "/scripts"
SCRIPT_PATH = Path(SCRIPTS_DIR) / "_install_repair.py"


def _load_module():
    """Load scripts/_install_repair.py as a module."""
    spec = importlib.util.spec_from_file_location("_install_repair", str(SCRIPT_PATH))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_check_python_version_passes():
    """Python version check passes on the runtime version."""
    importlib.reload(_load_module()) if False else None
    module = _load_module()
    assert module.check_python_version() is True


def test_check_dependencies_runs():
    """Dependency check runs without raising; result depends on environment."""
    module = _load_module()
    rc = module.check_dependencies()
    assert isinstance(rc, bool)


def test_check_api_keys_warns_when_missing(monkeypatch, capsys):
    """Missing API keys should print a warning but still return True."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    module = _load_module()
    rc = module.check_api_keys()
    out = capsys.readouterr().out
    assert rc is True
    assert "No API keys" in out


def test_check_api_keys_detects_openai(monkeypatch, capsys):
    """OPENAI_API_KEY in env should be reported."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    module = _load_module()
    module.check_api_keys()
    out = capsys.readouterr().out
    assert "OPENAI_API_KEY" in out


def test_check_zeloo_home_creates_missing(tmp_path, monkeypatch, capsys):
    """Missing zeloo_HOME is reported but does not fail."""
    monkeypatch.setenv("zeloo_HOME", str(tmp_path / "_missing_home"))
    module = _load_module()
    rc = module.check_zeloo_home()
    out = capsys.readouterr().out
    assert rc is True
    assert "not yet created" in out or "zeloo_HOME" in out


def test_check_zeloo_home_detects_existing(tmp_path, monkeypatch):
    """Existing zeloo_HOME is reported as OK."""
    monkeypatch.setenv("zeloo_HOME", str(tmp_path))
    module = _load_module()
    rc = module.check_zeloo_home()
    assert rc is True


def test_check_git_repo_returns_true():
    """check_git_repo returns True (whether or not it's a git repo)."""
    module = _load_module()
    assert module.check_git_repo() is True


def test_fix_permissions_runs():
    """fix_permissions returns True when chmod succeeds."""
    module = _load_module()
    rc = module.fix_permissions()
    assert rc is True


def test_main_returns_zero_or_one():
    """main() returns 0 or 1 depending on environment (always exits cleanly)."""
    import contextlib
    import io

    module = _load_module()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = module.main()
    assert rc in (0, 1)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))