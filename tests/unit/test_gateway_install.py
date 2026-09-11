"""Unit tests for gateway install service."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from zeloo_cli.gateway import (  # noqa: E402
    _install_windows_service,
    cmd_gateway_install_service,
)


class TestGatewayInstallWindows:
    @patch("zeloo_cli.gateway.subprocess.run")
    @patch("zeloo_cli.gateway._supports_windows_service", return_value=True)
    @patch("zeloo_cli.gateway._supports_launchd", return_value=False)
    @patch("zeloo_cli.gateway._supports_systemd_services", return_value=False)
    def test_windows_invokes_powershell(
        self, mock_systemd, mock_launchd, mock_windows, mock_run
    ):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        result = cmd_gateway_install_service(args=None)
        assert result == 0
        # Verify PowerShell was called
        mock_run.assert_called_once()
        called_cmd = mock_run.call_args[0][0]
        assert called_cmd[0] == "powershell"

    @patch("zeloo_cli.gateway.Path.exists", return_value=False)
    @patch("zeloo_cli.gateway._supports_windows_service", return_value=True)
    @patch("zeloo_cli.gateway._supports_launchd", return_value=False)
    @patch("zeloo_cli.gateway._supports_systemd_services", return_value=False)
    def test_windows_script_not_found(
        self, mock_systemd, mock_launchd, mock_windows, mock_exists
    ):
        result = cmd_gateway_install_service(args=None)
        assert result == 1

    @patch(
        "zeloo_cli.gateway.subprocess.run",
        side_effect=subprocess.TimeoutExpired("powershell", 60),
    )
    @patch("zeloo_cli.gateway.Path.exists", return_value=True)
    @patch("zeloo_cli.gateway._supports_windows_service", return_value=True)
    @patch("zeloo_cli.gateway._supports_launchd", return_value=False)
    @patch("zeloo_cli.gateway._supports_systemd_services", return_value=False)
    def test_windows_uac_cancelled(
        self, mock_systemd, mock_launchd, mock_windows, mock_exists, mock_run
    ):
        result = cmd_gateway_install_service(args=None)
        assert result == 1

    @patch(
        "zeloo_cli.gateway.subprocess.run",
        side_effect=FileNotFoundError("powershell not found"),
    )
    @patch("zeloo_cli.gateway.Path.exists", return_value=True)
    @patch("zeloo_cli.gateway._supports_windows_service", return_value=True)
    @patch("zeloo_cli.gateway._supports_launchd", return_value=False)
    @patch("zeloo_cli.gateway._supports_systemd_services", return_value=False)
    def test_windows_no_powershell(
        self, mock_systemd, mock_launchd, mock_windows, mock_exists, mock_run
    ):
        result = cmd_gateway_install_service(args=None)
        assert result == 1

    @patch("zeloo_cli.gateway.subprocess.run")
    @patch("zeloo_cli.gateway.Path.exists", return_value=True)
    def test_install_windows_helper_returns_zero_on_success(
        self, mock_exists, mock_run
    ):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        assert _install_windows_service() == 0
        mock_run.assert_called_once()

    @patch("zeloo_cli.gateway.subprocess.run")
    @patch("zeloo_cli.gateway.Path.exists", return_value=True)
    def test_install_windows_helper_returns_one_on_nonzero(
        self, mock_exists, mock_run
    ):
        mock_run.return_value = MagicMock(returncode=1, stderr="boom")
        assert _install_windows_service() == 1


class TestGatewayInstallUnsupported:
    @patch("zeloo_cli.gateway._supports_windows_service", return_value=False)
    @patch("zeloo_cli.gateway._supports_launchd", return_value=False)
    @patch("zeloo_cli.gateway._supports_systemd_services", return_value=False)
    def test_unsupported_platform(self, mock_systemd, mock_launchd, mock_windows):
        result = cmd_gateway_install_service(args=None)
        assert result == 1
