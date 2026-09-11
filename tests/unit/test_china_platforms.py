"""Unit tests for Feishu, DingTalk, and WeCom platform adapters.

Tests focus on payload parsing, signature/verification logic, and the
URL-verification challenge handshake — all without making network calls.
"""

# ruff: noqa: E402
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from gateway.platforms.dingtalk import DingTalkAdapter
from gateway.platforms.feishu import FeishuAdapter
from gateway.platforms.wecom import WeComAdapter

# ── Feishu ──────────────────────────────────────────────────────────


def test_feishu_url_verification_challenge() -> None:
    """Feishu url_verification payload must echo the challenge."""
    adapter = FeishuAdapter(app_id="a", app_secret="s")
    body = json.dumps({"type": "url_verification", "challenge": "abc123"}).encode()
    result = adapter.get_verification_response(body, {})
    assert result is not None
    content_type, resp_body = result
    assert content_type == "application/json"
    assert json.loads(resp_body) == {"challenge": "abc123"}


def test_feishu_parse_v2_text_message() -> None:
    """Feishu v2.0 im.message.receive_v1 event extracts open_id + text."""
    adapter = FeishuAdapter(app_id="a", app_secret="s")
    payload = {
        "schema": "2.0",
        "header": {"event_type": "im.message.receive_v1", "token": "t"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou_123"}},
            "message": {
                "message_type": "text",
                "content": json.dumps({"text": "hello feishu"}),
            },
        },
    }
    result = adapter.parse_incoming(json.dumps(payload).encode(), {})
    assert result == ("ou_123", "hello feishu")


def test_feishu_ignore_non_message_events() -> None:
    """Non-message events return None."""
    adapter = FeishuAdapter(app_id="a", app_secret="s")
    payload = {"schema": "2.0", "header": {"event_type": "im.chat.member.bot.added_v1"}}
    assert adapter.parse_incoming(json.dumps(payload).encode(), {}) is None


def test_feishu_verify_token() -> None:
    """verify_request rejects payloads whose token mismatches."""
    adapter = FeishuAdapter(app_id="a", app_secret="s", verification_token="secret")
    good = json.dumps({"header": {"token": "secret"}}).encode()
    bad = json.dumps({"header": {"token": "wrong"}}).encode()
    assert adapter.verify_request(good, {}) is True
    assert adapter.verify_request(bad, {}) is False


# ── DingTalk ────────────────────────────────────────────────────────


def test_dingtalk_parse_text_message() -> None:
    """DingTalk text callback extracts senderId + content."""
    payload = {"msgtype": "text", "senderId": "uid_001", "text": {"content": "ping"}}
    result = DingTalkAdapter._parse_incoming(json.dumps(payload).encode())
    assert result == ("uid_001", "ping")


def test_dingtalk_ignore_non_text() -> None:
    """Non-text DingTalk messages return None."""
    payload = {"msgtype": "image", "senderId": "uid_001"}
    assert DingTalkAdapter._parse_incoming(json.dumps(payload).encode()) is None


def test_dingtalk_signature_verification() -> None:
    """DingTalk HMAC-SHA256 signature is validated correctly."""
    adapter = DingTalkAdapter(app_key="k", app_secret="mysecret")
    timestamp = "1700000000000"
    body = b'{"msgtype":"text"}'
    string_to_sign = f"{timestamp}\n".encode() + body
    sig = base64.b64encode(
        hmac.new(b"mysecret", string_to_sign, hashlib.sha256).digest()
    ).decode()
    assert adapter._verify_signature(timestamp, sig, body) is True
    assert adapter._verify_signature(timestamp, "badsig", body) is False


# ── WeCom ───────────────────────────────────────────────────────────


def test_wecom_parse_text_message() -> None:
    """WeCom XML text callback extracts FromUserName + Content."""
    xml = (
        "<xml>"
        "<MsgType>text</MsgType>"
        "<FromUserName>user_456</FromUserName>"
        "<Content>hello wecom</Content>"
        "</xml>"
    )
    result = WeComAdapter._parse_incoming(xml.encode())
    assert result == ("user_456", "hello wecom")


def test_wecom_ignore_non_text() -> None:
    """Non-text WeCom messages return None."""
    xml = "<xml><MsgType>image</MsgType><FromUserName>u</FromUserName></xml>"
    assert WeComAdapter._parse_incoming(xml.encode()) is None


def test_wecom_signature_verification() -> None:
    """WeCom SHA1 signature over sorted(token, timestamp, nonce) is checked."""
    adapter = WeComAdapter(
        corp_id="c", corp_secret="s", agent_id=1, token="mytoken"
    )
    timestamp = "1700000000"
    nonce = "abc"
    sorted_str = "".join(sorted(["mytoken", timestamp, nonce]))
    sig = hashlib.sha1(sorted_str.encode()).hexdigest()
    assert adapter._verify_signature(timestamp, nonce, sig) is True
    assert adapter._verify_signature(timestamp, nonce, "wrong") is False


if __name__ == "__main__":
    import sys

    tests = [
        test_feishu_url_verification_challenge,
        test_feishu_parse_v2_text_message,
        test_feishu_ignore_non_message_events,
        test_feishu_verify_token,
        test_dingtalk_parse_text_message,
        test_dingtalk_ignore_non_text,
        test_dingtalk_signature_verification,
        test_wecom_parse_text_message,
        test_wecom_ignore_non_text,
        test_wecom_signature_verification,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
