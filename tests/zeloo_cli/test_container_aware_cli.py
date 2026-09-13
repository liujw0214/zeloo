"""Tests for container-aware CLI routing (NixOS container mode).

When container.enable = true in the NixOS module, the activation script
writes a .container-mode metadata file. The host CLI detects this and
execs into the container instead of running locally.
"""
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from zeloo_cli.config import (
    get_container_exec_info,
)


# =============================================================================
# get_container_exec_info
# =============================================================================


@pytest.fixture
def container_env(tmp_path, monkeypatch):
    """Set up a fake ZELOO_HOME with .container-mode file."""
    zeloo_home = tmp_path / ".Zeloo"
    zeloo_home.mkdir()
    monkeypatch.setenv("ZELOO_HOME", str(zeloo_home))
    monkeypatch.delenv("ZELOO_DEV", raising=False)

    container_mode = zeloo_home / ".container-mode"
    container_mode.write_text(
        "# Written by NixOS activation script. Do not edit manually.\n"
        "backend=podman\n"
        "container_name=Zeloo-agent\n"
        "exec_user=Zeloo\n"
        "zeloo_bin=/data/current-package/bin/Zeloo\n"
    )
    return zeloo_home


def test_get_container_exec_info_returns_metadata(container_env):
    """Reads .container-mode and returns all fields including exec_user."""
    with patch("zeloo_constants.is_container", return_value=False):
        info = get_container_exec_info()

    assert info is not None
    assert info["backend"] == "podman"
    assert info["container_name"] == "Zeloo-agent"
    assert info["exec_user"] == "Zeloo"
    assert info["zeloo_bin"] == "/data/current-package/bin/Zeloo"








# =============================================================================
# _exec_in_container
# =============================================================================


@pytest.fixture
def docker_container_info():
    return {
        "backend": "docker",
        "container_name": "Zeloo-agent",
        "exec_user": "Zeloo",
        "zeloo_bin": "/data/current-package/bin/Zeloo",
    }


@pytest.fixture
def podman_container_info():
    return {
        "backend": "podman",
        "container_name": "Zeloo-agent",
        "exec_user": "Zeloo",
        "zeloo_bin": "/data/current-package/bin/Zeloo",
    }


def test_exec_in_container_calls_execvp(docker_container_info):
    """Verifies os.execvp is called with correct args: runtime, tty flags,
    user, env vars, container name, binary, and CLI args."""
    from zeloo_cli.main import _exec_in_container

    with patch("shutil.which", return_value="/usr/bin/docker"), \
         patch("subprocess.run") as mock_run, \
         patch("sys.stdin") as mock_stdin, \
         patch("os.execvp") as mock_execvp, \
         patch.dict(os.environ, {"TERM": "xterm-256color", "LANG": "en_US.UTF-8"},
                    clear=False):
        mock_stdin.isatty.return_value = True
        mock_run.return_value = MagicMock(returncode=0)

        _exec_in_container(docker_container_info, ["chat", "-m", "opus"])

    mock_execvp.assert_called_once()
    cmd = mock_execvp.call_args[0][1]
    assert cmd[0] == "/usr/bin/docker"
    assert cmd[1] == "exec"
    assert "-it" in cmd
    idx_u = cmd.index("-u")
    assert cmd[idx_u + 1] == "Zeloo"
    e_indices = [i for i, v in enumerate(cmd) if v == "-e"]
    e_values = [cmd[i + 1] for i in e_indices]
    assert "TERM=xterm-256color" in e_values
    assert "LANG=en_US.UTF-8" in e_values
    assert "Zeloo-agent" in cmd
    assert "/data/current-package/bin/Zeloo" in cmd
    assert "chat" in cmd


