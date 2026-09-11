"""Unit tests for remote client and run subcommand."""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock
import pytest

from zeloo_cli.remote_client import RemoteConfig, RemoteClient


class TestRemoteConfig:
    def test_default(self):
        config = RemoteConfig()
        assert config.host == "localhost"
        assert config.port == 9113
        assert config.use_tls is False

    def test_base_url_http(self):
        config = RemoteConfig(host="example.com", port=8000)
        assert config.base_url == "http://example.com:8000"

    def test_base_url_https(self):
        config = RemoteConfig(host="example.com", port=443, use_tls=True)
        assert config.base_url == "https://example.com:443"

    def test_from_url_https(self):
        config = RemoteConfig.from_url("https://zeloo.example.com:9113")
        assert config.host == "zeloo.example.com"
        assert config.port == 9113
        assert config.use_tls is True

    def test_from_url_zeloo_scheme(self):
        config = RemoteConfig.from_url("zeloo://zeloo.example.com:9000")
        assert config.host == "zeloo.example.com"
        assert config.port == 9000

    def test_from_url_with_api_key(self):
        config = RemoteConfig.from_url("https://h:1", api_key="sk-xxx")
        assert config.api_key == "sk-xxx"


class TestRemoteClient:
    @pytest.fixture
    def client(self):
        return RemoteClient(RemoteConfig(host="localhost", port=9113))

    @patch("urllib.request.urlopen")
    def test_health_check_success(self, mock_urlopen, client):
        mock_urlopen.return_value.__enter__.return_value.status = 200
        assert client.health_check() is True

    @patch("urllib.request.urlopen")
    def test_health_check_failure(self, mock_urlopen, client):
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("refused")
        assert client.health_check() is False

    @patch("urllib.request.urlopen")
    def test_list_models(self, mock_urlopen, client):
        mock_urlopen.return_value.__enter__.return_value.read.return_value = json.dumps({
            "data": [{"id": "gpt-4o"}, {"id": "claude-3-5-sonnet"}]
        }).encode()
        models = client.list_models()
        assert models == ["gpt-4o", "claude-3-5-sonnet"]

    @patch("urllib.request.urlopen")
    def test_chat_completion(self, mock_urlopen, client):
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value.read.return_value = json.dumps({
            "choices": [{"message": {"content": "Hello back!"}}]
        }).encode()
        mock_urlopen.return_value = mock_resp

        result = client.chat_completion(
            messages=[{"role": "user", "content": "Hi"}],
            model="gpt-4o",
        )
        assert result["choices"][0]["message"]["content"] == "Hello back!"

    def test_auth_header_added(self):
        config = RemoteConfig(host="h", port=1, api_key="secret")
        client = RemoteClient(config)
        req = MagicMock()
        client._add_auth_header(req)
        req.add_header.assert_called_with("Authorization", "Bearer secret")
