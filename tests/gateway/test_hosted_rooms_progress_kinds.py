"""M1.1 INVARIANT tests: 6 new agent.* event kinds are registered and validated correctly.

These tests verify the schema contract, NOT the driver emit behavior (that's M1.2/M1.3).
"""
from __future__ import annotations

import pytest

from gateway import hosted_room_discussion as discussion
from gateway import hosted_rooms as rooms


class TestProgressKindsRegistered:
    """INVARIANT: all 6 agent.* kinds must be registered in _EVENT_KINDS_BY_ACTOR."""

    @pytest.mark.parametrize("kind", [
        "agent.thinking", "agent.tool_call", "agent.tool_result",
        "agent.waiting_child", "agent.done", "agent.failed",
    ])
    def test_kind_in_MEMBER_actor_set(self, kind: str):
        assert kind in rooms._EVENT_KINDS_BY_ACTOR["member"]

    @pytest.mark.parametrize("kind", [
        "agent.thinking", "agent.tool_call", "agent.tool_result",
        "agent.waiting_child", "agent.done", "agent.failed",
    ])
    def test_kind_matches_EVENT_KIND_RE(self, kind: str):
        assert rooms._EVENT_KIND_RE.match(kind)

    @pytest.mark.parametrize("kind", [
        "agent.thinking", "agent.tool_call", "agent.tool_result",
        "agent.waiting_child", "agent.done", "agent.failed",
    ])
    def test_kind_in_event_validators(self, kind: str):
        assert kind in discussion._EVENT_VALIDATORS

    def test_longest_kind_under_MAX_EVENT_KIND_CHARS(self):
        longest = max(rooms._EVENT_KINDS_BY_ACTOR["member"], key=len)
        assert len(longest) <= rooms.MAX_EVENT_KIND_CHARS


class TestProgressEventSchema:
    """INVARIANT: progress events with correct payloads pass validation; malformed ones raise."""

    @pytest.fixture
    def validated_room(self):
        member = discussion.DiscussionMember(
            member_id="bot1", profile="default", handle="Bot",
            display_name="Test Bot")
        room = discussion.DiscussionRoom(
            room_id="room1", name="Test", members=(member,),
            gateway_id="gw1", authority_epoch=1)
        return room

    def _actor(self, member_id: str = "bot1", profile: str = "default") -> dict:
        # Note: connection_id must be None for local members (peer_id is None)
        return {"kind": "member", "id": member_id, "profile": profile, "connection_id": None}

    def _turn_payload(self) -> dict:
        return {
            "task_id": "dtask:test", "thread_id": "t1",
            "member_id": "bot1", "member_index": 0, "round_index": 0,
            "discussion_event_id": "e1", "turn_id": "d1.r0.p0.s0.mabc",
        }

    # agent.thinking
    def test_agent_thinking_valid(self, validated_room):
        p = dict(self._turn_payload())
        p["model"] = "gpt-4o"
        p["round"] = 0
        v = discussion._validate_progress_event("agent.thinking", p, self._actor(), validated_room)
        assert v["model"] == "gpt-4o"

    def test_agent_thinking_missing_round(self, validated_room):
        p = dict(self._turn_payload())
        p["model"] = "gpt-4o"
        # missing round
        with pytest.raises(discussion.DiscussionValidationError):
            discussion._validate_progress_event("agent.thinking", p, self._actor(), validated_room)

    # agent.tool_call
    def test_agent_tool_call_valid(self, validated_room):
        p = dict(self._turn_payload())
        p["tool"] = "web_search"
        p["call_id"] = "call_1"
        p["round"] = 0
        v = discussion._validate_progress_event("agent.tool_call", p, self._actor(), validated_room)
        assert v["tool"] == "web_search"

    # agent.tool_result
    def test_agent_tool_result_valid(self, validated_room):
        p = dict(self._turn_payload())
        p["tool"] = "web_search"
        p["call_id"] = "call_1"
        p["duration_ms"] = 150
        p["status"] = "ok"
        v = discussion._validate_progress_event("agent.tool_result", p, self._actor(), validated_room)
        assert v["status"] == "ok"

    def test_agent_tool_result_invalid_status(self, validated_room):
        p = dict(self._turn_payload())
        p["tool"] = "web_search"
        p["call_id"] = "call_1"
        p["duration_ms"] = 150
        p["status"] = "partial"
        with pytest.raises(discussion.DiscussionValidationError):
            discussion._validate_progress_event("agent.tool_result", p, self._actor(), validated_room)

    def test_agent_tool_result_negative_duration(self, validated_room):
        p = dict(self._turn_payload())
        p["tool"] = "web_search"
        p["call_id"] = "call_1"
        p["duration_ms"] = -1
        p["status"] = "ok"
        with pytest.raises(discussion.DiscussionValidationError):
            discussion._validate_progress_event("agent.tool_result", p, self._actor(), validated_room)

    # agent.waiting_child
    def test_agent_waiting_child_valid(self, validated_room):
        p = dict(self._turn_payload())
        p["child_task_id"] = "dtask:child"
        p["child_target"] = "subagent"
        v = discussion._validate_progress_event("agent.waiting_child", p, self._actor(), validated_room)
        assert v["child_target"] == "subagent"

    # agent.done
    def test_agent_done_valid(self, validated_room):
        p = dict(self._turn_payload())
        p["terminal_kind"] = "settled"
        p["tokens"] = 1234
        v = discussion._validate_progress_event("agent.done", p, self._actor(), validated_room)
        assert v["terminal_kind"] == "settled"

    def test_agent_done_invalid_terminal_kind(self, validated_room):
        p = dict(self._turn_payload())
        p["terminal_kind"] = "partial"
        p["tokens"] = 1234
        with pytest.raises(discussion.DiscussionValidationError):
            discussion._validate_progress_event("agent.done", p, self._actor(), validated_room)

    def test_agent_done_zero_tokens(self, validated_room):
        p = dict(self._turn_payload())
        p["terminal_kind"] = "settled"
        p["tokens"] = 0
        with pytest.raises(discussion.DiscussionValidationError):
            discussion._validate_progress_event("agent.done", p, self._actor(), validated_room)

    # agent.failed
    def test_agent_failed_valid(self, validated_room):
        p = dict(self._turn_payload())
        p["error_class"] = "ToolExecutionError"
        p["error_message"] = "timeout"
        v = discussion._validate_progress_event("agent.failed", p, self._actor(), validated_room)
        assert v["error_class"] == "ToolExecutionError"

    # actor validation
    def test_user_actor_rejected(self, validated_room):
        p = dict(self._turn_payload())
        p["model"] = "gpt-4o"
        p["round"] = 0
        with pytest.raises(discussion.DiscussionValidationError):
            discussion._validate_progress_event("agent.thinking", p, {"kind": "user"}, validated_room)

    def test_unknown_member_rejected(self, validated_room):
        p = dict(self._turn_payload())
        p["model"] = "gpt-4o"
        p["round"] = 0
        with pytest.raises(discussion.DiscussionValidationError):
            discussion._validate_progress_event("agent.thinking", p, self._actor(member_id="unknown_bot"), validated_room)


class TestProgressFieldsDict:
    """INVARIANT: _PROGRESS_EVENT_FIELDS has correct structure for every kind."""

    def test_all_kinds_have_fields_dict(self):
        """Every agent.* kind has an entry in _PROGRESS_EVENT_FIELDS."""
        for kind in ("agent.thinking", "agent.tool_call", "agent.tool_result",
                     "agent.waiting_child", "agent.done", "agent.failed"):
            assert kind in discussion._PROGRESS_EVENT_FIELDS, f"{kind} missing from _PROGRESS_EVENT_FIELDS"

    def test_fields_dict_all_is_superset_of_identifier(self):
        """INVARIANT: identifier_fields ⊆ all_fields for every kind."""
        for kind in discussion._PROGRESS_EVENT_FIELDS:
            all_fields, identifier_fields = discussion._PROGRESS_EVENT_FIELDS[kind]
            assert frozenset(all_fields).issuperset(frozenset(identifier_fields)), f"{kind}: identifier not subset of all_fields"

    def test_all_fields_includes_turn_coordinates(self):
        """INVARIANT: every progress event schema includes turn coordinates."""
        turn_coords = {"task_id", "thread_id", "member_id", "member_index", "round_index"}
        for kind in discussion._PROGRESS_EVENT_FIELDS:
            all_fields, _ = discussion._PROGRESS_EVENT_FIELDS[kind]
            assert turn_coords.issubset(frozenset(all_fields)), f"{kind}: missing turn coordinates"

    def test_thinking_required_includes_model_and_round(self):
        required, _ = discussion._PROGRESS_EVENT_FIELDS["agent.thinking"]
        assert "model" in required and "round" in required

    def test_tool_result_required_includes_duration_ms_and_status(self):
        required, _ = discussion._PROGRESS_EVENT_FIELDS["agent.tool_result"]
        assert "duration_ms" in required and "status" in required

    def test_done_required_includes_tokens_and_terminal_kind(self):
        required, _ = discussion._PROGRESS_EVENT_FIELDS["agent.done"]
        assert "tokens" in required and "terminal_kind" in required
