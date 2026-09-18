"""Tests for the M1.5 hosted-rooms HTTP routes."""
import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from gateway import hosted_rooms
from gateway.platforms import api_server_hosted_rooms as routes


def _make_adapter() -> Any:
    """Stub adapter. The handlers in ``_http_routes`` reference
    ``self._handle_hosted_rooms_<verb>``; we never call those stubs
    directly, but having them keeps the route-registration step
    from raising AttributeError when the test enumerates routes."""
    class _Stub:
        _handle_hosted_rooms_list = lambda self, req: None
        _handle_hosted_rooms_create = lambda self, req: None
        _handle_hosted_rooms_get = lambda self, req: None
        _handle_hosted_rooms_disband = lambda self, req: None
        _handle_hosted_rooms_events = lambda self, req: None
    return _Stub()


def _make_room_payload(**overrides: Any) -> dict[str, Any]:
    base = {
        "room_id": "r-test",
        "name": "Test Room",
        "members": [{"member_id": "user-boss", "kind": "user"}],
        "authority_gateway_id": "gw-1",
        "authority_epoch": 0,
        "next_seq": 0,
        "revision": 0,
        "created_at": 1_700_000_000.0,
        "updated_at": 1_700_000_000.0,
        "disbanded_at": None,
    }
    base.update(overrides)
    return base


@pytest.fixture
def temp_db(monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point hosted_rooms.default_db_path() at a fresh sqlite file in a
    temp dir so each test starts clean."""
    tmp = tempfile.mkdtemp(prefix="hosted_rooms_test_")
    db = Path(tmp) / "shared-state.db"
    monkeypatch.setattr(hosted_rooms, "default_db_path", lambda: db)
    monkeypatch.setattr(hosted_rooms, "local_authority_gateway_id", lambda: "test-gateway")
    return db


def _create(db: Path, room_id: str, name: str | None = None, members: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Wrapper around hosted_rooms.create_room with the right signature."""
    return hosted_rooms.create_room(
        db,
        room_id=room_id,
        name=name or room_id,
        members=members or [{"member_id": "u", "kind": "user"}],
        authority_gateway_id="test-gateway",
    )


def _make_request(query: dict[str, str] | None = None, body: dict[str, Any] | None = None,
                  match_info: dict[str, str] | None = None) -> Any:
    """Minimal aiohttp-like request."""

    class _Req:
        def __init__(self) -> None:
            self._query = query or {}
            self._body = body
            self.match_info = match_info or {}

        @property
        def query(self) -> dict[str, str]:
            return self._query

        async def read(self) -> bytes:
            if self._body is None:
                return b""
            return json.dumps(self._body).encode("utf-8")

    return _Req()


def _body(response: Any) -> dict[str, Any]:
    raw = response.body
    if isinstance(raw, (bytes, bytearray)):
        return json.loads(raw.decode("utf-8"))
    return json.loads(raw)


def _get_handler(index: int):
    """Pull the unbound module-level handler by name. The route table
    references ``self._handle_hosted_rooms_<verb>``; the actual
    implementation lives at module level as
    ``routes._handle_hosted_rooms_<verb>`` and is what we want to call."""
    verb_map = {
        0: "_handle_hosted_rooms_list",
        1: "_handle_hosted_rooms_create",
        2: "_handle_hosted_rooms_get",
        3: "_handle_hosted_rooms_disband",
        4: "_handle_hosted_rooms_events",
    }
    return getattr(routes, verb_map[index])


# -- _http_routes shape ---------------------------------------------------------

def test_http_routes_returns_five_routes() -> None:
    routes_list = routes._http_routes(_make_adapter())
    methods_paths = [(m, p) for m, p, _ in routes_list]
    assert ("GET", "/api/hosted_rooms") in methods_paths
    assert ("POST", "/api/hosted_rooms") in methods_paths
    assert ("GET", "/api/hosted_rooms/{room_id}") in methods_paths
    assert ("DELETE", "/api/hosted_rooms/{room_id}") in methods_paths
    assert ("GET", "/api/hosted_rooms/{room_id}/events") in methods_paths
    assert len(routes_list) == 5


# -- _serialize_room -------------------------------------------------------------

def test_serialize_room_decodes_members_json_string() -> None:
    room = _make_room_payload(members=json.dumps([{"member_id": "m1", "kind": "agent"}]))
    out = routes._serialize_room(room)
    assert isinstance(out["members"], list)
    assert out["members"][0]["member_id"] == "m1"


def test_serialize_room_passes_list_members_through() -> None:
    members = [{"member_id": "m1", "kind": "agent"}]
    room = _make_room_payload(members=members)
    out = routes._serialize_room(room)
    assert out["members"] == members


def test_serialize_room_handles_none_members() -> None:
    room = _make_room_payload(members=None)
    out = routes._serialize_room(room)
    assert out["members"] == []


# -- list -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_returns_empty_when_no_rooms(temp_db: Path) -> None:
    handler = _get_handler(0)
    response = await handler(_make_adapter(), _make_request())
    body = _body(response)
    assert body == {"rooms": [], "total": 0, "limit": 50, "offset": 0}
    assert response.status == 200


@pytest.mark.asyncio
async def test_list_returns_created_rooms(temp_db: Path) -> None:
    _create(temp_db, "R1")
    handler = _get_handler(0)
    response = await handler(_make_adapter(), _make_request())
    body = _body(response)
    assert body["total"] == 1
    assert body["rooms"][0]["name"] == "R1"


@pytest.mark.asyncio
async def test_list_respects_limit_and_offset(temp_db: Path) -> None:
    for i in range(5):
        _create(temp_db, f"R{i}")
    handler = _get_handler(0)
    response = await handler(_make_adapter(), _make_request(query={"limit": "2", "offset": "1"}))
    body = _body(response)
    assert body["total"] == 2
    assert body["limit"] == 2
    assert body["offset"] == 1


# -- create ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_persists_and_returns_201(temp_db: Path) -> None:
    handler = _get_handler(1)
    response = await handler(
        _make_adapter(),
        _make_request(body={"name": "New", "members": [{"member_id": "u", "kind": "user"}]}),
    )
    body = _body(response)
    assert response.status == 201
    assert body["name"] == "New"
    assert body["members"][0]["member_id"] == "u"


@pytest.mark.asyncio
async def test_create_rejects_empty_name(temp_db: Path) -> None:
    handler = _get_handler(1)
    response = await handler(
        _make_adapter(),
        _make_request(body={"name": "", "members": [{"member_id": "u", "kind": "user"}]}),
    )
    assert response.status == 400


@pytest.mark.asyncio
async def test_create_rejects_empty_members(temp_db: Path) -> None:
    handler = _get_handler(1)
    response = await handler(_make_adapter(), _make_request(body={"name": "X", "members": []}))
    assert response.status == 400


# -- get -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_returns_room(temp_db: Path) -> None:
    room = _create(temp_db, "R-get")
    handler = _get_handler(2)
    response = await handler(_make_adapter(), _make_request(match_info={"room_id": room["room_id"]}))
    body = _body(response)
    assert body["room_id"] == room["room_id"]


@pytest.mark.asyncio
async def test_get_returns_404_for_unknown(temp_db: Path) -> None:
    handler = _get_handler(2)
    response = await handler(_make_adapter(), _make_request(match_info={"room_id": "nope"}))
    assert response.status == 404


# -- disband -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_disband_marks_room_as_disbanded(temp_db: Path) -> None:
    room = _create(temp_db, "R-disband")
    disband_handler = _get_handler(3)
    list_handler = _get_handler(0)
    response = await disband_handler(_make_adapter(), _make_request(match_info={"room_id": room["room_id"]}))
    body = _body(response)
    assert body["ok"] is True
    list_response = await list_handler(_make_adapter(), _make_request())
    assert _body(list_response)["total"] == 0


@pytest.mark.asyncio
async def test_disband_returns_404_for_unknown(temp_db: Path) -> None:
    handler = _get_handler(3)
    response = await handler(_make_adapter(), _make_request(match_info={"room_id": "nope"}))
    assert response.status == 404


# -- events (Phase 9) ---------------------------------------------------------

def _emit_event(db: Path, *, room_id: str, kind: str, payload: dict, actor_id: str = "test-actor") -> dict:
    """Helper: append a hosted_room_events row via the gateway helpers
    and return the loaded row. Bypasses the full append_event ceremony
    (it requires a DiscussionTaskPlan); we only need a row for the
    list_room_events test surface."""
    from gateway import hosted_rooms
    # room_state requires the room to exist; create one with create_room.
    if not hosted_rooms.list_rooms(db, include_disbanded=True, limit=500):
        hosted_rooms.create_room(
            db, room_id=room_id, name="Events Test",
            members=[{"member_id": "u", "kind": "user"}],
            authority_gateway_id="test-gateway",
        )
    import json as _json
    import time as _time
    with hosted_rooms._transaction(db) as conn:  # type: ignore[attr-defined]
        # Pick the next seq.
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) AS m FROM hosted_room_events WHERE room_id=?",
            (room_id,),
        ).fetchone()
        seq = int(row["m"]) + 1
        event_id = f"e-{kind}-{seq}"
        conn.execute(
            "INSERT INTO hosted_room_events(room_id, seq, event_id, kind, actor_json, authority_epoch, payload_json, created_at)"
            " VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
            (room_id, seq, event_id, kind, _json.dumps({"actor_id": actor_id, "kind": "agent"}), _json.dumps(payload), _time.time()),
        )
    return {"room_id": room_id, "seq": seq, "event_id": event_id, "kind": kind, "payload": payload}


@pytest.mark.asyncio
async def test_events_returns_appended_rows_oldest_first(temp_db: Path) -> None:
    _emit_event(temp_db, room_id="R-evt", kind="agent.thinking", payload={"model": "x", "round": 0})
    _emit_event(temp_db, room_id="R-evt", kind="agent.tool_call", payload={"tool": "read_file", "call_id": "c1"})
    _emit_event(temp_db, room_id="R-evt", kind="agent.done", payload={"terminal_kind": "success"})

    handler = _get_handler(4)  # events
    response = await handler(
        _make_adapter(),
        _make_request(match_info={"room_id": "R-evt"}, query={"limit": "50"}),
    )
    body = _body(response)
    assert response.status == 200
    assert body["total"] == 3
    kinds = [e["kind"] for e in body["events"]]
    assert kinds == ["agent.thinking", "agent.tool_call", "agent.done"]
    # payload_json / actor_json must be decoded into nested objects.
    assert body["events"][0]["payload"] == {"model": "x", "round": 0}
    assert body["events"][0]["actor"] == {"actor_id": "test-actor", "kind": "agent"}


@pytest.mark.asyncio
async def test_events_respects_kinds_filter(temp_db: Path) -> None:
    _emit_event(temp_db, room_id="R-kf", kind="agent.thinking", payload={})
    _emit_event(temp_db, room_id="R-kf", kind="agent.tool_call", payload={})
    _emit_event(temp_db, room_id="R-kf", kind="agent.done", payload={})

    handler = _get_handler(4)
    response = await handler(
        _make_adapter(),
        _make_request(match_info={"room_id": "R-kf"}, query={"kinds": "agent.thinking,agent.done"}),
    )
    body = _body(response)
    assert body["total"] == 2
    kinds = [e["kind"] for e in body["events"]]
    assert kinds == ["agent.thinking", "agent.done"]


@pytest.mark.asyncio
async def test_events_returns_empty_for_unknown_room(temp_db: Path) -> None:
    handler = _get_handler(4)
    response = await handler(
        _make_adapter(),
        _make_request(match_info={"room_id": "no-such-room"}),
    )
    body = _body(response)
    assert response.status == 200
    assert body == {"events": [], "total": 0, "limit": 100, "offset": 0}
