"""Unit tests for WhatsApp integration."""

from __future__ import annotations

from unittest.mock import patch, MagicMock, AsyncMock
import pytest

from tools.integrations.base import AuthError
from tools.integrations.whatsapp_integration import WhatsAppIntegration


def _resp(payload=None, code: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = code
    r.text = "" if code < 400 else '{"error":{"code":0,"message":"x"}}'
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
def wa() -> WhatsAppIntegration:
    return WhatsAppIntegration(config={
        "phone_number_id": "123", "access_token": "tk", "verify_token": "v",
    })


class TestWhatsAppInit:
    def test_basic_init(self, wa) -> None:
        assert wa.phone_number_id == "123" and wa.access_token == "tk"
        assert wa.api_version == "v18.0" and wa.verify_token == "v"

    def test_missing_phone_id(self) -> None:
        with pytest.raises(AuthError):
            WhatsAppIntegration(config={"access_token": "tk"})

    def test_missing_access_token(self) -> None:
        with pytest.raises(AuthError):
            WhatsAppIntegration(config={"phone_number_id": "1"})


class TestSendMessages:
    @patch("httpx.AsyncClient")
    async def test_send_text(self, mc, wa) -> None:
        _wire(mc, _resp({"messages": [{"id": "m1"}],
                             "contacts": [{"wa_id": "1"}]}))
        out = await wa.send_message("8612345678901", "hi")
        assert out["ok"] and out["message_id"] == "m1"

    @patch("httpx.AsyncClient")
    async def test_send_text_strips_plus(self, mc, wa) -> None:
        client = _wire(mc, _resp({"messages": [{"id": "m"}],
                                       "contacts": [{"wa_id": "1"}]}))
        await wa.send_text("+8612345678901", "hi")
        body = client.request.call_args.kwargs["json"]
        assert body["to"] == "8612345678901" and body["text"]["body"] == "hi"

    @patch("httpx.AsyncClient")
    async def test_send_template(self, mc, wa) -> None:
        client = _wire(mc, _resp({"messages": [{"id": "t"}]}))
        out = await wa.send_template(
            "8612345678901", "welcome", language="zh_CN",
            components=[{"type": "body", "parameters": []}],
        )
        assert out["ok"]
        body = client.request.call_args.kwargs["json"]
        assert body["template"]["name"] == "welcome"
        assert body["template"]["language"]["code"] == "zh_CN"

    @patch("httpx.AsyncClient")
    async def test_send_image(self, mc, wa) -> None:
        client = _wire(mc, _resp({"messages": [{"id": "i"}]}))
        out = await wa.send_image("8612345678901", "https://x/y.jpg", "cap")
        assert out["ok"]
        body = client.request.call_args.kwargs["json"]
        assert body["image"]["link"] == "https://x/y.jpg"
        assert body["image"]["caption"] == "cap"

    @patch("httpx.AsyncClient")
    async def test_send_document(self, mc, wa) -> None:
        client = _wire(mc, _resp({"messages": [{"id": "d"}]}))
        out = await wa.send_document("8612345678901", "https://x/r.pdf", "f.pdf")
        assert out["ok"]
        body = client.request.call_args.kwargs["json"]
        assert body["document"]["filename"] == "f.pdf"


class TestWebhook:
    def test_verify_webhook(self, wa) -> None:
        assert wa.verify_webhook("subscribe", "v") is True
        assert wa.verify_webhook("subscribe", "bad") is False
        assert wa.verify_webhook("unsubscribe", "v") is False

    async def test_handle_webhook_invokes_callback(self, wa) -> None:
        called = []

        async def cb(event):
            called.append(event)

        await wa.receive_messages(cb)
        assert await wa.handle_webhook_event({"entry": []}) == {"ok": True}
        assert called == [{"entry": []}]

    async def test_handle_webhook_swallows_callback_errors(self, wa) -> None:
        async def bad(event):
            raise RuntimeError("boom")

        await wa.receive_messages(bad)
        assert await wa.handle_webhook_event({"x": 1}) == {"ok": True}


class TestErrorPath:
    @patch("httpx.AsyncClient")
    async def test_auth_error(self, mc, wa) -> None:
        _wire(mc, _resp(code=401))
        out = await wa.send_text("8612345678901", "x")
        assert out["ok"] is False and out["code"] == "unauthorized"
