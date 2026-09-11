"""Unit tests for the update checker with Beta channel support."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from zeloo_cli.update_checker import (
    VersionInfo,
    _get_channel,
    _get_latest_for_channel,
    _is_prerelease,
    _parse_pypi_json,
    check_latest_version,
    get_update_command,
    get_version_info,
)


class TestIsPrerelease:
    """Tests for _is_prerelease()."""

    def test_stable_versions(self):
        assert _is_prerelease("0.16.0") is False
        assert _is_prerelease("1.0.0") is False
        assert _is_prerelease("2.3.4") is False
        assert _is_prerelease("0.9.9") is False

    def test_alpha_versions(self):
        assert _is_prerelease("0.17.0a1") is True
        assert _is_prerelease("1.0.0a0") is True
        assert _is_prerelease("2.0.0alpha1") is True

    def test_beta_versions(self):
        assert _is_prerelease("0.17.0b1") is True
        assert _is_prerelease("1.0.0b2") is True
        assert _is_prerelease("2.0.0beta1") is True

    def test_rc_versions(self):
        assert _is_prerelease("0.17.0rc1") is True
        assert _is_prerelease("1.0.0rc2") is True
        assert _is_prerelease("2.0.0.rc3") is True


class TestGetChannel:
    """Tests for _get_channel()."""

    def test_default_stable(self, monkeypatch):
        monkeypatch.delenv("ZELOO_UPDATE_CHANNEL", raising=False)
        assert _get_channel() == "stable"

    def test_explicit_stable(self, monkeypatch):
        monkeypatch.setenv("ZELOO_UPDATE_CHANNEL", "stable")
        assert _get_channel() == "stable"

    def test_beta(self, monkeypatch):
        monkeypatch.setenv("ZELOO_UPDATE_CHANNEL", "beta")
        assert _get_channel() == "beta"

    def test_beta_1(self, monkeypatch):
        monkeypatch.setenv("ZELOO_UPDATE_CHANNEL", "1")
        assert _get_channel() == "beta"

    def test_beta_true(self, monkeypatch):
        monkeypatch.setenv("ZELOO_UPDATE_CHANNEL", "true")
        assert _get_channel() == "beta"

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("ZELOO_UPDATE_CHANNEL", "BETA")
        assert _get_channel() == "beta"


class TestParsePypiJson:
    """Tests for _parse_pypi_json()."""

    def test_parses_versions(self):
        payload = {
            "releases": {
                "0.16.0": [{"upload_time": "2026-09-11T00:00:00", "url": "https://files.pypi.org/zeloo-0.16.0.tar.gz"}],
                "0.17.0": [{"upload_time": "2026-09-12T00:00:00", "url": "https://files.pypi.org/zeloo-0.17.0.tar.gz"}],
                "0.17.0b1": [{"upload_time": "2026-09-10T00:00:00", "url": "https://files.pypi.org/zeloo-0.17.0b1.tar.gz"}],
                "0.15.0": [{"upload_time": "2026-09-09T00:00:00", "url": "https://files.pypi.org/zeloo-0.15.0.tar.gz"}],
            },
            "info": {},
        }
        versions = _parse_pypi_json(payload)
        assert len(versions) == 4
        assert versions[0].version == "0.17.0"
        assert versions[1].version == "0.17.0b1"
        assert versions[2].version == "0.16.0"
        assert versions[3].version == "0.15.0"

    def test_channel_classification(self):
        payload = {
            "releases": {
                "0.16.0": [{"upload_time": "2026-09-11T00:00:00", "url": "x"}],
                "0.17.0b1": [{"upload_time": "2026-09-10T00:00:00", "url": "x"}],
                "0.17.0rc1": [{"upload_time": "2026-09-09T00:00:00", "url": "x"}],
            },
            "info": {},
        }
        versions = _parse_pypi_json(payload)
        version_map = {v.version: v for v in versions}
        assert version_map["0.16.0"].is_prerelease is False
        assert version_map["0.17.0b1"].is_prerelease is True
        assert version_map["0.17.0rc1"].is_prerelease is True

    def test_empty_releases_ignored(self):
        payload = {
            "releases": {
                "0.16.0": [],
            },
            "info": {},
        }
        versions = _parse_pypi_json(payload)
        assert len(versions) == 0


class TestGetLatestForChannel:
    """Tests for _get_latest_for_channel()."""

    def test_stable_channel_skips_prerelease(self):
        versions = [
            VersionInfo("0.17.0b1", "beta", "2026-09-10", "x", True),
            VersionInfo("0.17.0", "stable", "2026-09-11", "x", False),
            VersionInfo("0.16.0", "stable", "2026-09-09", "x", False),
        ]
        result = _get_latest_for_channel(versions, "stable")
        assert result is not None
        assert result.version == "0.17.0"

    def test_beta_channel_includes_prerelease(self):
        versions = [
            VersionInfo("0.17.0b1", "beta", "2026-09-10", "x", True),
            VersionInfo("0.17.0", "stable", "2026-09-11", "x", False),
            VersionInfo("0.16.0", "stable", "2026-09-09", "x", False),
        ]
        result = _get_latest_for_channel(versions, "beta")
        assert result is not None
        assert result.version == "0.17.0b1"

    def test_stable_channel_all_prerelease_returns_none(self):
        versions = [
            VersionInfo("0.17.0b1", "beta", "2026-09-10", "x", True),
            VersionInfo("0.17.0rc1", "beta", "2026-09-09", "x", True),
        ]
        result = _get_latest_for_channel(versions, "stable")
        assert result is None


class TestCheckLatestVersion:
    """Tests for check_latest_version()."""

    @patch("zeloo_cli.update_checker._query_pypi_versions")
    def test_returns_3_tuple(self, mock_query, monkeypatch):
        monkeypatch.delenv("ZELOO_UPDATE_CHANNEL", raising=False)
        mock_query.return_value = [
            VersionInfo("0.17.0", "stable", "2026-09-11", "x", False),
            VersionInfo("0.16.0", "stable", "2026-09-10", "x", False),
        ]
        result = check_latest_version()
        assert len(result) == 3
        assert result[2] == "stable"

    @patch("zeloo_cli.update_checker._query_pypi_versions")
    def test_beta_channel(self, mock_query, monkeypatch):
        monkeypatch.setenv("ZELOO_UPDATE_CHANNEL", "beta")
        mock_query.return_value = [
            VersionInfo("0.17.0b1", "beta", "2026-09-10", "x", True),
            VersionInfo("0.17.0", "stable", "2026-09-11", "x", False),
            VersionInfo("0.16.0", "stable", "2026-09-09", "x", False),
        ]
        current, latest, channel = check_latest_version()
        assert latest == "0.17.0b1"
        assert channel == "beta"

    @patch("zeloo_cli.update_checker._query_pypi_versions")
    def test_stable_channel(self, mock_query, monkeypatch):
        monkeypatch.delenv("ZELOO_UPDATE_CHANNEL", raising=False)
        mock_query.return_value = [
            VersionInfo("0.17.0b1", "beta", "2026-09-10", "x", True),
            VersionInfo("0.17.0", "stable", "2026-09-11", "x", False),
            VersionInfo("0.16.0", "stable", "2026-09-09", "x", False),
        ]
        current, latest, channel = check_latest_version()
        assert latest == "0.17.0"
        assert channel == "stable"

    @patch("zeloo_cli.update_checker._query_pypi_versions")
    def test_none_on_network_error(self, mock_query, monkeypatch):
        monkeypatch.delenv("ZELOO_UPDATE_CHANNEL", raising=False)
        mock_query.return_value = None
        current, latest, channel = check_latest_version()
        assert latest is None
        assert channel == "stable"

    @patch("zeloo_cli.update_checker._query_pypi_versions")
    def test_explicit_channel_overrides_env(self, mock_query, monkeypatch):
        monkeypatch.setenv("ZELOO_UPDATE_CHANNEL", "stable")
        mock_query.return_value = [
            VersionInfo("0.17.0b1", "beta", "2026-09-10", "x", True),
            VersionInfo("0.17.0", "stable", "2026-09-11", "x", False),
        ]
        current, latest, channel = check_latest_version(channel="beta")
        assert latest == "0.17.0b1"
        assert channel == "beta"


class TestGetVersionInfo:
    """Tests for get_version_info()."""

    @patch("zeloo_cli.update_checker._query_pypi_versions")
    def test_returns_version_info(self, mock_query, monkeypatch):
        monkeypatch.delenv("ZELOO_UPDATE_CHANNEL", raising=False)
        mock_query.return_value = [
            VersionInfo("0.17.0", "stable", "2026-09-11T00:00:00", "https://x.tar.gz", False),
            VersionInfo("0.16.0", "stable", "2026-09-10T00:00:00", "https://y.tar.gz", False),
        ]
        info = get_version_info("0.17.0")
        assert info is not None
        assert info.version == "0.17.0"
        assert info.release_date == "2026-09-11T00:00:00"
        assert info.is_prerelease is False

    @patch("zeloo_cli.update_checker._query_pypi_versions")
    def test_returns_none_for_missing_version(self, mock_query, monkeypatch):
        monkeypatch.delenv("ZELOO_UPDATE_CHANNEL", raising=False)
        mock_query.return_value = [
            VersionInfo("0.16.0", "stable", "2026-09-10", "x", False),
        ]
        info = get_version_info("0.99.0")
        assert info is None


class TestGetUpdateCommand:
    """Tests for get_update_command()."""

    def test_returns_pip_command(self):
        assert get_update_command("0.17.0") == "pip install zeloo==0.17.0"
        assert get_update_command("0.17.0b1") == "pip install zeloo==0.17.0b1"
        assert get_update_command("1.0.0") == "pip install zeloo==1.0.0"
