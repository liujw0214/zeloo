"""Unit tests for ``agent.providers.model_updater``."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.providers.model_updater import (
    DEFAULT_TTL_HOURS,
    ModelInfo,
    ModelSource,
    ModelUpdater,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cache_path(tmp_path: Path) -> Path:
    """Return an isolated cache file path under ``tmp_path``."""
    return tmp_path / "models.json"


@pytest.fixture
def updater(cache_path: Path) -> ModelUpdater:
    """Build a ``ModelUpdater`` with an isolated cache file."""
    return ModelUpdater(cache_path=cache_path, ttl_hours=24)


# ---------------------------------------------------------------------------
# ModelInfo
# ---------------------------------------------------------------------------


class TestModelInfo:
    def test_construction_minimal(self) -> None:
        info = ModelInfo(
            id="gpt-4o",
            provider="openai",
            display_name="GPT-4o",
            context_length=128_000,
            input_cost_per_1k=2.50,
            output_cost_per_1k=10.00,
        )
        assert info.id == "gpt-4o"
        assert info.provider == "openai"
        assert info.context_length == 128_000
        assert info.input_cost_per_1k == 2.50
        assert info.output_cost_per_1k == 10.00

    def test_construction_defaults(self) -> None:
        info = ModelInfo(
            id="x", provider="y", display_name="z",
            context_length=1, input_cost_per_1k=0.0, output_cost_per_1k=0.0,
        )
        assert info.supports_vision is False
        assert info.supports_tools is False
        assert info.supports_streaming is True
        assert info.release_date is None
        assert info.metadata == {}

    def test_to_dict_basic(self) -> None:
        info = ModelInfo(
            id="gpt-4o", provider="openai", display_name="GPT-4o",
            context_length=128_000, input_cost_per_1k=2.50, output_cost_per_1k=10.00,
            supports_vision=True, supports_tools=True,
        )
        d = info.to_dict()
        assert d["id"] == "gpt-4o"
        assert d["supports_vision"] is True
        assert d["supports_tools"] is True
        assert d["supports_streaming"] is True

    def test_to_dict_serializes_release_date(self) -> None:
        info = ModelInfo(
            id="x", provider="y", display_name="z", context_length=1,
            input_cost_per_1k=0.0, output_cost_per_1k=0.0,
            release_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        d = info.to_dict()
        assert d["release_date"] == "2024-01-01T00:00:00+00:00"

    def test_from_dict_round_trip(self) -> None:
        info = ModelInfo(
            id="gpt-4o", provider="openai", display_name="GPT-4o",
            context_length=128_000, input_cost_per_1k=2.50, output_cost_per_1k=10.00,
            release_date=datetime(2024, 5, 13, tzinfo=timezone.utc),
        )
        round_trip = ModelInfo.from_dict(info.to_dict())
        assert round_trip.id == info.id
        assert round_trip.provider == info.provider
        assert round_trip.release_date == info.release_date

    def test_from_dict_handles_bad_release_date(self) -> None:
        info = ModelInfo.from_dict({
            "id": "x", "provider": "y", "display_name": "z", "context_length": 1,
            "input_cost_per_1k": 0.0, "output_cost_per_1k": 0.0,
            "release_date": "not-a-date",
        })
        assert info.release_date is None


# ---------------------------------------------------------------------------
# ModelSource enum
# ---------------------------------------------------------------------------


class TestModelSource:
    def test_enum_values(self) -> None:
        assert ModelSource.STATIC.value == "static"
        assert ModelSource.API.value == "api"
        assert ModelSource.OPENAI_COMPAT.value == "openai_compat"

    def test_enum_count(self) -> None:
        assert len(ModelSource) == 3

    def test_enum_lookup(self) -> None:
        assert ModelSource("static") is ModelSource.STATIC
        assert ModelSource("api") is ModelSource.API
        assert ModelSource("openai_compat") is ModelSource.OPENAI_COMPAT


# ---------------------------------------------------------------------------
# ModelUpdater — basic init & cache
# ---------------------------------------------------------------------------


class TestModelUpdaterInit:
    def test_init(self, updater: ModelUpdater) -> None:
        assert updater is not None

    def test_default_cache_path_used_when_none(self) -> None:
        u = ModelUpdater()
        assert u._cache_path is not None

    def test_init_loads_existing_cache(self, cache_path: Path) -> None:
        payload = {
            "models": {
                "openai": [
                    {
                        "id": "gpt-4o", "provider": "openai",
                        "display_name": "GPT-4o", "context_length": 128000,
                        "input_cost_per_1k": 0.005, "output_cost_per_1k": 0.015,
                        "supports_vision": True, "supports_tools": True,
                        "supports_streaming": True,
                    }
                ]
            },
            "timestamps": {
                "openai": datetime.now(timezone.utc).isoformat(),
            },
        }
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
        u = ModelUpdater(cache_path=cache_path, ttl_hours=24)
        models = u.get_models("openai")
        assert len(models) >= 1
        assert any(m.id == "gpt-4o" for m in models)


# ---------------------------------------------------------------------------
# ModelUpdater — get_models / static catalogues
# ---------------------------------------------------------------------------


class TestGetModels:
    def test_get_models_returns_list_for_openai(self, updater: ModelUpdater) -> None:
        models = updater.get_models("openai")
        assert isinstance(models, list)
        assert len(models) > 0
        assert all(isinstance(m, ModelInfo) for m in models)

    def test_get_provider_static_models(self, updater: ModelUpdater) -> None:
        for provider in (
            "openai", "anthropic", "google", "groq",
            "deepseek", "mistral", "xai",
        ):
            models = updater.get_provider_static_models(provider)
            assert isinstance(models, list)
            assert len(models) >= 1, f"provider {provider!r} should have ≥1 model"

    def test_get_unknown_provider_returns_empty_list(
        self, updater: ModelUpdater,
    ) -> None:
        models = updater.get_models("nonexistent-provider")
        assert isinstance(models, list)
        assert models == []

    def test_static_models_returns_copy(
        self, updater: ModelUpdater,
    ) -> None:
        a = updater.get_provider_static_models("openai")
        b = updater.get_provider_static_models("openai")
        assert a == b
        assert a is not b  # must be a fresh copy


# ---------------------------------------------------------------------------
# ModelUpdater — cache helpers
# ---------------------------------------------------------------------------


class TestCacheHelpers:
    def test_clear_cache_specific(self, updater: ModelUpdater) -> None:
        # Trigger fetch so cache has data
        updater.get_models("openai")
        updater.clear_cache("openai")
        age = updater.get_cache_age("openai")
        assert age is None

    def test_clear_cache_all(self, updater: ModelUpdater) -> None:
        updater.get_models("openai")
        updater.get_models("anthropic")
        updater.clear_cache()
        assert updater.get_cache_age("openai") is None
        assert updater.get_cache_age("anthropic") is None

    def test_clear_cache_unknown_provider_no_error(
        self, updater: ModelUpdater,
    ) -> None:
        # Should not raise even when the provider has no cache entry.
        updater.clear_cache("nonexistent")

    def test_get_cache_age_none_when_empty(
        self, updater: ModelUpdater,
    ) -> None:
        age = updater.get_cache_age("openai")
        assert age is None

    def test_get_cache_age_returns_timedelta_after_fetch(
        self, updater: ModelUpdater,
    ) -> None:
        updater.get_models("openai")
        age = updater.get_cache_age("openai")
        assert age is not None
        assert isinstance(age, timedelta)


# ---------------------------------------------------------------------------
# ModelUpdater — update_provider
# ---------------------------------------------------------------------------


class TestUpdateProvider:
    @patch("agent.providers.model_updater.httpx.Client")
    def test_update_provider_falls_back_to_static(
        self, mock_client_cls: MagicMock, updater: ModelUpdater,
    ) -> None:
        # When the network call raises, the static catalogue is returned.
        mock_client_cls.side_effect = RuntimeError("network down")
        models = updater.update_provider("openai")
        assert isinstance(models, list)
        assert len(models) > 0

    @patch("agent.providers.model_updater.httpx.Client")
    def test_update_provider_force(
        self, mock_client_cls: MagicMock, updater: ModelUpdater,
    ) -> None:
        # Force=True bypasses cache and re-fetches.
        mock_client_cls.side_effect = RuntimeError("network down")
        updater.get_models("openai")  # populate cache
        models = updater.update_provider("openai", force=True)
        assert isinstance(models, list)
        assert len(models) > 0


# ---------------------------------------------------------------------------
# ModelUpdater — update_all
# ---------------------------------------------------------------------------


class TestUpdateAll:
    @patch("agent.providers.model_updater.httpx.Client")
    def test_update_all_returns_dict_per_provider(
        self, mock_client_cls: MagicMock, updater: ModelUpdater,
    ) -> None:
        mock_client_cls.side_effect = RuntimeError("network down")
        results = updater.update_all()
        assert isinstance(results, dict)
        # At least the static providers should appear in the result.
        assert "openai" in results
        assert "anthropic" in results
        for provider, models in results.items():
            assert isinstance(models, list)


# ---------------------------------------------------------------------------
# ModelUpdater — fetch_openai_compatible
# ---------------------------------------------------------------------------


class TestFetchOpenAICompatible:
    @patch("agent.providers.model_updater.httpx.Client")
    def test_fetch_openai_compatible_parses_response(
        self, mock_client_cls: MagicMock, updater: ModelUpdater,
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "model-a", "name": "Model A", "context_length": 8000},
                {"id": "model-b", "name": "Model B"},
            ]
        }
        mock_response.raise_for_status.return_value = None

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = False
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        models = updater.fetch_openai_compatible(
            "https://api.example.com/v1", "sk-key",
        )
        assert isinstance(models, list)
        assert len(models) == 2
        assert all(isinstance(m, ModelInfo) for m in models)
        assert models[0].id == "model-a"
        assert models[0].context_length == 8000

    @patch("agent.providers.model_updater.httpx.Client")
    def test_fetch_openai_compatible_skips_invalid_entries(
        self, mock_client_cls: MagicMock, updater: ModelUpdater,
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "valid-model"},
                "not-a-dict",
                {"no_id": True},
                {},
            ]
        }
        mock_response.raise_for_status.return_value = None

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = False
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        models = updater.fetch_openai_compatible(
            "https://api.example.com/v1",
        )
        assert isinstance(models, list)
        assert len(models) == 1
        assert models[0].id == "valid-model"

    @patch("agent.providers.model_updater.httpx.Client")
    def test_fetch_openai_compatible_returns_empty_on_error(
        self, mock_client_cls: MagicMock, updater: ModelUpdater,
    ) -> None:
        mock_client_cls.side_effect = RuntimeError("boom")
        models = updater.fetch_openai_compatible(
            "https://api.example.com/v1", "k",
        )
        assert models == []

    @patch("agent.providers.model_updater.httpx.Client")
    def test_fetch_openai_compatible_sends_auth_header(
        self, mock_client_cls: MagicMock, updater: ModelUpdater,
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": []}
        mock_response.raise_for_status.return_value = None

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = False
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        updater.fetch_openai_compatible(
            "https://api.example.com/v1", "secret-key",
        )
        _, kwargs = mock_client.get.call_args
        headers = kwargs.get("headers") or {}
        assert headers.get("Authorization") == "Bearer secret-key"

    @patch("agent.providers.model_updater.httpx.Client")
    def test_fetch_openai_compatible_normalises_url(
        self, mock_client_cls: MagicMock, updater: ModelUpdater,
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": []}
        mock_response.raise_for_status.return_value = None

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = False
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        # Without trailing /v1 should still resolve.
        updater.fetch_openai_compatible("https://api.example.com")
        called_url = mock_client.get.call_args[0][0]
        assert called_url.endswith("/v1/models")

    @patch("agent.providers.model_updater.httpx.Client")
    def test_fetch_openai_compatible_infers_provider_from_url(
        self, mock_client_cls: MagicMock, updater: ModelUpdater,
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"id": "gpt-x"}]}
        mock_response.raise_for_status.return_value = None

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = False
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        models = updater.fetch_openai_compatible(
            "https://api.openai.com/v1",
        )
        assert models[0].provider == "openai"


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


class TestModuleConstants:
    def test_default_ttl_hours(self) -> None:
        assert DEFAULT_TTL_HOURS == 24

    def test_module_exports(self) -> None:
        from agent.providers import model_updater as mu
        for name in ("ModelInfo", "ModelSource", "ModelUpdater", "DEFAULT_CACHE_PATH"):
            assert name in mu.__all__
