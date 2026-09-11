"""Unit tests for Home Assistant integration."""

from __future__ import annotations

from unittest.mock import patch, MagicMock, AsyncMock
import pytest

from tools.integrations.base import AuthError
from tools.integrations.homeassistant_integration import HomeAssistantIntegration


def _resp(payload=None, code: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = code
    r.text = "" if code < 400 else "err"
    r.content = b"{}"
    r.headers = {}
    r.json.return_value = payload if payload is not None else {}
    return r


def _wire(mock_cls, resp: MagicMock) -> AsyncMock:
    client = AsyncMock()
    for m in ("request", "get", "post", "put", "delete"):
        setattr(client, m, AsyncMock(return_value=resp))
    client.aclose = AsyncMock(return_value=None)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    mock_cls.return_value = client
    return client


@pytest.fixture
def ha() -> HomeAssistantIntegration:
    return HomeAssistantIntegration(config={"url": "http://ha.local:8123", "token": "tok"})


class TestHomeAssistantInit:
    def test_basic(self, ha) -> None:
        assert ha.url == "http://ha.local:8123" and ha.token == "tok"
        assert ha.headers["Authorization"] == "Bearer tok"

    def test_strips_trailing_slash(self) -> None:
        h = HomeAssistantIntegration(config={"url": "http://ha:8123/", "token": "t"})
        assert h.url == "http://ha:8123"

    def test_missing_url(self) -> None:
        with pytest.raises(AuthError):
            HomeAssistantIntegration(config={"token": "t"})

    def test_missing_token(self) -> None:
        with pytest.raises(AuthError):
            HomeAssistantIntegration(config={"url": "http://x"})

    def test_ws_url(self, ha) -> None:
        assert "ws://ha.local:8123/api/websocket" == ha.ws_url()
        ha.url = "https://ha.example.com"
        assert "wss://ha.example.com/api/websocket" == ha.ws_url()


class TestStates:
    @patch("httpx.AsyncClient")
    async def test_get_states(self, mc, ha) -> None:
        client = _wire(mc, _resp([
            {"entity_id": "light.kitchen", "state": "on"},
            {"entity_id": "switch.tv", "state": "off"},
        ]))
        states = await ha.get_states()
        assert len(states) == 2
        assert states[0]["entity_id"] == "light.kitchen"
        assert client.request.call_args.args[1] == "/api/states"

    @patch("httpx.AsyncClient")
    async def test_get_states_with_filter(self, mc, ha) -> None:
        client = _wire(mc, _resp([{"entity_id": "light.kitchen"}]))
        await ha.get_states(entity_ids=["light.kitchen"])
        assert client.request.call_args.kwargs["params"] == {"entity_id": "light.kitchen"}

    @patch("httpx.AsyncClient")
    async def test_get_state(self, mc, ha) -> None:
        _wire(mc, _resp({"entity_id": "light.x", "state": "off"}))
        out = await ha.get_state("light.x")
        assert out["ok"] and out["state"]["entity_id"] == "light.x"


class TestServices:
    @patch("httpx.AsyncClient")
    async def test_call_service(self, mc, ha) -> None:
        client = _wire(mc, _resp([{"context": {"id": "c"}}]))
        out = await ha.call_service("light", "turn_on", entity_id="light.k")
        assert out["ok"]
        body = client.request.call_args.kwargs["json"]
        assert body["entity_id"] == "light.k"
        assert client.request.call_args.args == ("POST", "/api/services/light/turn_on")

    @patch("httpx.AsyncClient")
    async def test_call_service_with_data(self, mc, ha) -> None:
        client = _wire(mc, _resp([{"context": {"id": "c"}}]))
        await ha.call_service("light", "turn_on", data={"brightness": 200})
        body = client.request.call_args.kwargs["json"]
        assert body["brightness"] == 200

    @patch("httpx.AsyncClient")
    async def test_fire_event(self, mc, ha) -> None:
        client = _wire(mc, _resp({"event": {"event_type": "x"}}))
        out = await ha.fire_event("x", {"k": "v"})
        assert out["ok"]
        assert client.request.call_args.kwargs["json"] == {"k": "v"}


class TestTemplate:
    @patch("httpx.AsyncClient")
    async def test_render_template(self, mc, ha) -> None:
        client = _wire(mc, _resp({"result": "42"}))
        out = await ha.render_template("{{ 40 + 2 }}")
        assert out == "42"
        assert client.request.call_args.kwargs["json"] == {"template": "{{ 40 + 2 }}"}
