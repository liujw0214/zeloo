"""Unit tests for 9 new platform adapters (batch 2).

Covers payload parsing and signature-verification logic only — no
network calls are made. Adapters tested: Teams, Matrix, Google Chat,
SMS (Twilio), QQ Bot, IRC, LINE, Mattermost, Home Assistant.
"""

# ruff: noqa: E402
import base64
import hashlib
import hmac
import json
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlencode

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)
import os

os.environ.setdefault("zeloo_HOME", tempfile.mkdtemp())

from gateway.platforms.google_chat import GoogleChatAdapter
from gateway.platforms.home_assistant import HomeAssistantAdapter
from gateway.platforms.irc import IRCAdapter
from gateway.platforms.line import LINEAdapter
from gateway.platforms.matrix import MatrixAdapter
from gateway.platforms.mattermost import MattermostAdapter
from gateway.platforms.qqbot import QQBotAdapter
from gateway.platforms.sms import SMSAdapter
from gateway.platforms.teams import TeamsAdapter

# ── Teams ───────────────────────────────────────────────────────────


def test_teams_parse_message_activity() -> None:
    """TeamsAdapter.parse_incoming extracts user_id + text from a message activity."""
    adapter = TeamsAdapter(bot_id="bot1", bot_password="pass")
    payload = {
        "type": "message",
        "from": {"id": "user1", "role": "user"},
        "conversation": {"id": "conv1"},
        "serviceUrl": "https://example.com",
        "text": "hello teams",
    }
    result = adapter.parse_incoming(json.dumps(payload).encode(), {})
    assert result == ("user1", "hello teams")


def test_teams_ignore_conversation_update() -> None:
    """conversationUpdate activities are ignored (return None)."""
    adapter = TeamsAdapter(bot_id="bot1", bot_password="pass")
    payload = {
        "type": "conversationUpdate",
        "from": {"id": "user1"},
        "conversation": {"id": "conv1"},
    }
    assert adapter.parse_incoming(json.dumps(payload).encode(), {}) is None


def test_teams_ignore_bot_messages() -> None:
    """Messages from other bots are ignored to avoid loops."""
    adapter = TeamsAdapter(bot_id="bot1", bot_password="pass")
    payload = {
        "type": "message",
        "from": {"id": "bot2", "role": "bot"},
        "text": "hello",
    }
    assert adapter.parse_incoming(json.dumps(payload).encode(), {}) is None


# ── Matrix ──────────────────────────────────────────────────────────


def test_matrix_parse_text_message() -> None:
    """MatrixAdapter.parse extracts sender + body from an m.room.message/m.text event."""
    event = {
        "type": "m.room.message",
        "sender": "@alice:example.org",
        "content": {"msgtype": "m.text", "body": "hello matrix"},
    }
    result = MatrixAdapter.parse(event)
    assert result == ("@alice:example.org", "hello matrix")


def test_matrix_parse_ignores_non_text_msgtype() -> None:
    """Non-m.text messages (e.g. m.emote) return None."""
    event = {
        "type": "m.room.message",
        "sender": "@alice:example.org",
        "content": {"msgtype": "m.emote", "body": "waves"},
    }
    assert MatrixAdapter.parse(event) is None


def test_matrix_parse_ignores_missing_sender() -> None:
    """Events without a sender or body return None."""
    event = {"type": "m.room.message", "content": {"msgtype": "m.text", "body": ""}}
    assert MatrixAdapter.parse(event) is None


# ── Google Chat ─────────────────────────────────────────────────────


def test_google_chat_parse_message_event() -> None:
    """GoogleChatAdapter.parse_incoming extracts sender.name + text."""
    adapter = GoogleChatAdapter()
    payload = {
        "type": "MESSAGE",
        "message": {
            "sender": {"name": "users/123"},
            "text": "hello google chat",
            "space": {"name": "spaces/abc"},
        },
    }
    result = adapter.parse_incoming(json.dumps(payload).encode(), {})
    assert result == ("users/123", "hello google chat")


def test_google_chat_ignore_non_message_event() -> None:
    """Non-MESSAGE/TEXT event types (e.g. ADDED_TO_SPACE) return None."""
    adapter = GoogleChatAdapter()
    payload = {"type": "ADDED_TO_SPACE", "message": {"sender": {"name": "u"}, "text": "x"}}
    assert adapter.parse_incoming(json.dumps(payload).encode(), {}) is None


# ── SMS (Twilio) ────────────────────────────────────────────────────


def test_sms_parse_form_urlencoded_body() -> None:
    """SMSAdapter.parse_incoming extracts From + Body from form-urlencoded payload."""
    body = urlencode({"Body": "hello sms", "From": "+1234567890"}).encode()
    result = SMSAdapter.parse_incoming(body, {})
    assert result == ("+1234567890", "hello sms")


def test_sms_parse_missing_fields_returns_none() -> None:
    """Payloads without Body or From return None."""
    body = urlencode({"Body": "no sender"}).encode()
    assert SMSAdapter.parse_incoming(body, {}) is None


# ── QQ Bot ──────────────────────────────────────────────────────────


def test_qqbot_parse_c2c_message_create() -> None:
    """QQBotAdapter.parse_incoming extracts user_openid + content from C2C_MESSAGE_CREATE."""
    adapter = QQBotAdapter(app_id="app1", app_secret="secret")
    payload = {
        "eventType": "C2C_MESSAGE_CREATE",
        "data": {
            "author": {"user_openid": "user123"},
            "content": "hello qqbot",
        },
    }
    result = adapter.parse_incoming(json.dumps(payload).encode(), {})
    assert result == ("user123", "hello qqbot")


def test_qqbot_ignore_non_c2c_event() -> None:
    """Non-C2C_MESSAGE_CREATE events return None."""
    adapter = QQBotAdapter(app_id="app1", app_secret="secret")
    payload = {"eventType": "GROUP_AT_MESSAGE_CREATE", "data": {"content": "x"}}
    assert adapter.parse_incoming(json.dumps(payload).encode(), {}) is None


def test_qqbot_verify_request_valid_signature() -> None:
    """verify_request accepts a valid HMAC-SHA256 hex signature."""
    adapter = QQBotAdapter(app_id="app1", app_secret="mysecret")
    body = b'{"eventType":"C2C_MESSAGE_CREATE"}'
    expected = hmac.new(b"mysecret", body, hashlib.sha256).hexdigest()
    headers = {"x-signature": expected}
    assert adapter.verify_request(body, headers) is True


def test_qqbot_verify_request_bad_signature() -> None:
    """verify_request rejects an invalid signature."""
    adapter = QQBotAdapter(app_id="app1", app_secret="mysecret")
    body = b'{"eventType":"C2C_MESSAGE_CREATE"}'
    assert adapter.verify_request(body, {"x-signature": "badsig"}) is False
    assert adapter.verify_request(body, {}) is False  # no signature header


def test_qqbot_verify_request_no_secret_skips() -> None:
    """Without an app_secret, verification is skipped (returns True)."""
    adapter = QQBotAdapter(app_id="app1", app_secret="")
    assert adapter.verify_request(b"body", {}) is True


# ── IRC ─────────────────────────────────────────────────────────────


def test_irc_parse_privmsg_line() -> None:
    """IRCAdapter.parse extracts nick + text from a PRIVMSG line."""
    line = ":alice!alice@localhost PRIVMSG #test :hello irc"
    result = IRCAdapter.parse(line)
    assert result == ("alice", "hello irc")


def test_irc_parse_ignores_non_privmsg() -> None:
    """Non-PRIVMSG commands return None."""
    assert IRCAdapter.parse(":server NOTICE #test :info") is None
    assert IRCAdapter.parse("PING :server") is None  # no leading colon


def test_irc_parse_no_text_returns_none() -> None:
    """PRIVMSG without a trailing text portion returns None."""
    assert IRCAdapter.parse(":alice!alice@host PRIVMSG #test") is None


# ── LINE ────────────────────────────────────────────────────────────


def test_line_parse_text_message_event() -> None:
    """LINEAdapter.parse_incoming extracts reply_token + text from a text message event."""
    adapter = LINEAdapter(channel_access_token="token", channel_secret="secret")
    payload = {
        "events": [
            {
                "type": "message",
                "reply_token": "reply123",
                "message": {"type": "text", "text": "hello line"},
            }
        ],
    }
    result = adapter.parse_incoming(json.dumps(payload).encode(), {})
    assert result == ("reply123", "hello line")


def test_line_ignore_non_text_message() -> None:
    """Non-text message events (e.g. image) return None."""
    adapter = LINEAdapter(channel_access_token="token", channel_secret="secret")
    payload = {
        "events": [
            {
                "type": "message",
                "replyToken": "rt",
                "message": {"type": "image", "text": ""},
            }
        ],
    }
    assert adapter.parse_incoming(json.dumps(payload).encode(), {}) is None


def test_line_verify_request_valid_signature() -> None:
    """verify_request accepts a valid HMAC-SHA256 base64 signature."""
    adapter = LINEAdapter(channel_access_token="token", channel_secret="mysecret")
    body = b'{"events":[]}'
    expected = base64.b64encode(
        hmac.new(b"mysecret", body, hashlib.sha256).digest()
    ).decode("utf-8")
    headers = {"x-line-signature": expected}
    assert adapter.verify_request(body, headers) is True


def test_line_verify_request_bad_signature() -> None:
    """verify_request rejects an invalid signature."""
    adapter = LINEAdapter(channel_access_token="token", channel_secret="mysecret")
    body = b'{"events":[]}'
    assert adapter.verify_request(body, {"x-line-signature": "badsig"}) is False
    assert adapter.verify_request(body, {}) is False  # no signature header


def test_line_verify_request_no_secret_skips() -> None:
    """Without channel_secret, verification is skipped (returns True)."""
    adapter = LINEAdapter(channel_access_token="token")
    assert adapter.verify_request(b"body", {}) is True


# ── Mattermost ──────────────────────────────────────────────────────


def test_mattermost_parse_outgoing_webhook() -> None:
    """MattermostAdapter.parse_incoming extracts user_id + text + caches channel_id."""
    adapter = MattermostAdapter(base_url="https://mm.example.com", bot_token="tok")
    body = urlencode(
        {"text": "hello mattermost", "user_id": "user456", "channel_id": "ch789"}
    ).encode()
    result = adapter.parse_incoming(body, {})
    assert result == ("user456", "hello mattermost")
    # channel_id should be cached for replying
    assert adapter._channel_map.get("user456") == "ch789"


def test_mattermost_parse_missing_fields_returns_none() -> None:
    """Payload without text or user_id returns None."""
    adapter = MattermostAdapter(base_url="https://mm.example.com", bot_token="tok")
    body = urlencode({"text": "no user"}).encode()
    assert adapter.parse_incoming(body, {}) is None


# ── Home Assistant ──────────────────────────────────────────────────


def test_home_assistant_parse_message_payload() -> None:
    """HomeAssistantAdapter.parse_incoming extracts user_id + message from JSON."""
    adapter = HomeAssistantAdapter(ha_url="https://ha.example.com", ha_token="tok")
    payload = {
        "event_type": "message",
        "message": "hello home assistant",
        "user_id": "user789",
    }
    result = adapter.parse_incoming(json.dumps(payload).encode(), {})
    assert result == ("user789", "hello home assistant")


def test_home_assistant_ignore_non_message_event() -> None:
    """Non-message event types return None."""
    adapter = HomeAssistantAdapter(ha_url="https://ha.example.com", ha_token="tok")
    payload = {"event_type": "state_changed", "message": "x", "user_id": "u"}
    assert adapter.parse_incoming(json.dumps(payload).encode(), {}) is None


def test_home_assistant_missing_fields_returns_none() -> None:
    """Payload without message or user_id returns None."""
    adapter = HomeAssistantAdapter(ha_url="https://ha.example.com", ha_token="tok")
    payload = {"event_type": "message", "message": "", "user_id": ""}
    assert adapter.parse_incoming(json.dumps(payload).encode(), {}) is None


if __name__ == "__main__":
    test_teams_parse_message_activity()
    test_teams_ignore_conversation_update()
    test_teams_ignore_bot_messages()
    test_matrix_parse_text_message()
    test_matrix_parse_ignores_non_text_msgtype()
    test_matrix_parse_ignores_missing_sender()
    test_google_chat_parse_message_event()
    test_google_chat_ignore_non_message_event()
    test_sms_parse_form_urlencoded_body()
    test_sms_parse_missing_fields_returns_none()
    test_qqbot_parse_c2c_message_create()
    test_qqbot_ignore_non_c2c_event()
    test_qqbot_verify_request_valid_signature()
    test_qqbot_verify_request_bad_signature()
    test_qqbot_verify_request_no_secret_skips()
    test_irc_parse_privmsg_line()
    test_irc_parse_ignores_non_privmsg()
    test_irc_parse_no_text_returns_none()
    test_line_parse_text_message_event()
    test_line_ignore_non_text_message()
    test_line_verify_request_valid_signature()
    test_line_verify_request_bad_signature()
    test_line_verify_request_no_secret_skips()
    test_mattermost_parse_outgoing_webhook()
    test_mattermost_parse_missing_fields_returns_none()
    test_home_assistant_parse_message_payload()
    test_home_assistant_ignore_non_message_event()
    test_home_assistant_missing_fields_returns_none()
    print("All platform batch-2 tests passed!")
