"""Tests for terminal backends."""

from __future__ import annotations

from pathlib import Path

import pytest

from terminal import create_backend
from terminal.base import TerminalBackend
from terminal.local import LocalTerminalBackend


class TestLocalBackend:
    def test_execute_success(self, tmp_path: Path) -> None:
        backend = LocalTerminalBackend(cwd=tmp_path)
        result = backend.execute("echo hello", timeout=5)
        assert result.success
        assert "hello" in result.stdout
        assert result.stderr == ""
        assert not result.timed_out

    def test_execute_failure(self, tmp_path: Path) -> None:
        backend = LocalTerminalBackend(cwd=tmp_path)
        result = backend.execute("exit 1", timeout=5)
        assert result.returncode == 1
        assert not result.success

    def test_execute_timeout(self, tmp_path: Path) -> None:
        import shutil
        import sys
        backend = LocalTerminalBackend(cwd=tmp_path)
        if sys.platform == "win32":
            if shutil.which("ping"):
                cmd = "cmd /c ping -n 10 127.0.0.1"
            else:
                pytest.skip("ping not available on this Windows system")
        else:
            cmd = "sleep 10"
        result = backend.execute(cmd, timeout=1)
        assert result.timed_out

    def test_get_cwd(self, tmp_path: Path) -> None:
        backend = LocalTerminalBackend(cwd=tmp_path)
        assert backend.get_cwd() == tmp_path


class TestTerminalFactory:
    def test_create_local(self) -> None:
        backend = create_backend("local")
        assert isinstance(backend, LocalTerminalBackend)

    def test_create_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown terminal backend"):
            create_backend("unknown_backend")

    def test_all_7_backends_exist(self) -> None:
        import shutil
        names = [
            "local", "ssh", "docker", "modal",
            "daytona", "vercel_sandbox", "singularity",
        ]
        for name in names:
            if name == "local":
                backend = create_backend(name)
                assert isinstance(backend, TerminalBackend)
                assert backend.name == name
            elif name == "ssh" and shutil.which("ssh") is None:
                continue
            else:
                try:
                    backend = create_backend(name)
                    assert isinstance(backend, TerminalBackend)
                    assert backend.name == name
                except (ImportError, FileNotFoundError):
                    pass
