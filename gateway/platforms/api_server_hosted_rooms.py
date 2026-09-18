"""HTTP routes for the M1.5 hosted-room CRUD surface.

Exposes the four verbs the Desktop renderer needs to call
``/api/hosted_rooms``:

  - GET    /api/hosted_rooms              → list active (or all) rooms
  - POST   /api/hosted_rooms              → create a new room
  - GET    /api/hosted_rooms/{room_id}    → get one room (full state)
  - DELETE /api/hosted_rooms/{room_id}    → disband (soft-delete) a room

The handlers are intentionally thin: they call the existing
``gateway.hosted_rooms`` functions (``list_rooms``, ``create_room``,
``get_room``, ``disband_room``) and serialize their return dicts to
JSON. Any auth, profile-scoping, or event-broadcast logic lives in
``gateway/hosted_rooms.py`` and is exercised by the unit tests
there — this file is the HTTP plumbing only.

Auth: the parent ``APIServerAdapter`` already gates every route on
``_check_auth`` (see ``api_server.py``). The handlers below therefore
trust the request and never re-validate the API key.
"""
from __future__ import annotations

import json
import time
from typing import Any, TYPE_CHECKING

try:
    from aiohttp import web
except ImportError:  # pragma: no cover
    web = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from gateway.platforms.api_server import APIServerAdapter


def _http_routes(self: "APIServerAdapter") -> list[tuple[str, str, Any]]:
    """Return the (method, path, handler) triples this module adds to
    the api_server route table.

    The route table iterates ``for method, path, handler in routes:
    app.router.add_route(method, path, handler)``. aiohttp binds the
    handler to the application at registration time, so the handler
    can be either an unbound function (which aiohttp will call with
    ``(request,)``) or a bound method (which aiohttp will call with
    ``(self, request)``). The OpenAI mixin uses unbound functions
    wrapped with ``_admit_api_agent_request``; the room-grants and
    api-runs modules use the bound-method form (``self._handle_...``).

    This module takes the simpler path: the four handlers are
    module-level ``async def _handle_hosted_rooms_<verb>(self, request)``
    functions. We bind them to the adapter instance via staticmethod
    on the class body (see ``APIServerAdapter``), so the route table
    can reference them the same way it does for room-grants and
    api-runs (``self._handle_hosted_rooms_<verb>``)."""
    return [
        ("GET", "/api/hosted_rooms", self._handle_hosted_rooms_list),
        ("POST", "/api/hosted_rooms", self._handle_hosted_rooms_create),
        ("GET", "/api/hosted_rooms/{room_id}", self._handle_hosted_rooms_get),
        ("DELETE", "/api/hosted_rooms/{room_id}", self._handle_hosted_rooms_disband),
    ]


def _json(payload: Any, status: int = 200) -> "web.Response":
    return web.Response(
        body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        content_type="application/json",
        status=status,
    )


async def _read_json(request: "web.Request") -> dict[str, Any]:
    body = await request.read()
    if not body:
        return {}
    return json.loads(body.decode("utf-8"))


def _db_path() -> Any:
    # Late import: gateway.hosted_rooms is the canonical home for the
    # sqlite path; pulling it at module level would also pull aiohttp
    # into zeloo_cli's import graph when this file is imported from
    # a non-server context (tests, in-process callers).
    from gateway import hosted_rooms
    return hosted_rooms.default_db_path()


def _serialize_room(room: dict[str, Any]) -> dict[str, Any]:
    """Mirror the Desktop ``RoomInfo`` shape (api/hosted_rooms.ts)."""
    members = room.get("members")
    if isinstance(members, str):
        # The python side stores members as a JSON string; decode so
        # the JSON wire shape matches what the client expects.
        try:
            members = json.loads(members)
        except json.JSONDecodeError:
            members = []
    elif members is None:
        members = []
    return {
        "room_id": room.get("room_id"),
        "name": room.get("name"),
        "members": members,
        "authority_gateway_id": room.get("authority_gateway_id"),
        "authority_epoch": room.get("authority_epoch", 0),
        "next_seq": room.get("next_seq", 0),
        "revision": room.get("revision", 0),
        "created_at": room.get("created_at", 0),
        "updated_at": room.get("updated_at", 0),
        "disbanded_at": room.get("disbanded_at"),
    }


async def _handle_hosted_rooms_list(self: "APIServerAdapter", request: "web.Request") -> "web.Response":
    """GET /api/hosted_rooms?limit=&offset=&include_disbanded="""
    from gateway import hosted_rooms
    limit = int(request.query.get("limit", "50"))
    offset = int(request.query.get("offset", "0"))
    include_disbanded = request.query.get("include_disbanded", "false").lower() in ("1", "true", "yes")
    rooms = hosted_rooms.list_rooms(
        _db_path(),
        include_disbanded=include_disbanded,
        limit=limit,
        offset=offset,
    )
    return _json({
        "rooms": [_serialize_room(r) for r in rooms],
        "total": len(rooms),
        "limit": limit,
        "offset": offset,
    })


async def _handle_hosted_rooms_create(self: "APIServerAdapter", request: "web.Request") -> "web.Response":
    """POST /api/hosted_rooms with {name, members, room_id?}.

    The Desktop caller may either let the server mint a room_id (the
    common case) or supply one explicitly to make the create
    idempotent across retries. The gateway's hosted_rooms.create_room
    requires room_id as a keyword, so we generate one server-side
    when the body omits it.
    """
    from gateway import hosted_rooms
    body = await _read_json(request)
    name = (body.get("name") or "").strip()
    if not name:
        return _json({"error": "name is required"}, status=400)
    members = body.get("members") or []
    if not isinstance(members, list) or not members:
        return _json({"error": "members must be a non-empty list"}, status=400)
    # room_id: prefer the caller's value; otherwise mint one from
    # the local gateway id + a timestamp so it is unique across
    # restarts and the desktop can correlate logs to the room.
    room_id = body.get("room_id")
    if not room_id:
        ts_hex = format(int(time.time() * 1_000_000) & 0xFFFFFFFF, "08x")
        room_id = f"r-{hosted_rooms.local_authority_gateway_id()[:8]}-{ts_hex}"
    try:
        result = hosted_rooms.create_room(
            _db_path(),
            room_id=room_id,
            name=name,
            members=members,
            authority_gateway_id=hosted_rooms.local_authority_gateway_id(),
        )
    except (ValueError, TypeError) as exc:
        return _json({"error": str(exc)}, status=400)
    return _json(_serialize_room(result), status=201)


async def _handle_hosted_rooms_get(self: "APIServerAdapter", request: "web.Request") -> "web.Response":
    """GET /api/hosted_rooms/{room_id}"""
    from gateway import hosted_rooms
    room_id = request.match_info.get("room_id", "")
    # hosted_rooms has no public get_room(); the canonical read is
    # list_rooms(include_disbanded=True) followed by an in-process
    # filter. This is O(N) but the room table is bounded by the number
    # of active + recently-disbanded rooms (small in practice).
    rooms = hosted_rooms.list_rooms(_db_path(), include_disbanded=True, limit=500)
    match = next((r for r in rooms if r.get("room_id") == room_id), None)
    if match is None:
        return _json({"error": "room not found"}, status=404)
    return _json(_serialize_room(match))


async def _handle_hosted_rooms_disband(self: "APIServerAdapter", request: "web.Request") -> "web.Response":
    """DELETE /api/hosted_rooms/{room_id}"""
    from gateway import hosted_rooms
    room_id = request.match_info.get("room_id", "")
    # disband_room requires expected_gateway_id + expected_epoch as
    # the optimistic-concurrency key. hosted_rooms has no public
    # get_room(); we look the room up via list_rooms(include_disbanded=True)
    # so a disband request against an unknown id returns 404 instead
    # of crashing on a missing row.
    rooms = hosted_rooms.list_rooms(_db_path(), include_disbanded=True, limit=500)
    match = next((r for r in rooms if r.get("room_id") == room_id), None)
    if match is None:
        return _json({"error": "room not found"}, status=404)
    try:
        result = hosted_rooms.disband_room(
            _db_path(),
            room_id=room_id,
            expected_gateway_id=match.get("authority_gateway_id", ""),
            expected_epoch=match.get("authority_epoch", 0),
        )
    except (ValueError, TypeError) as exc:
        return _json({"error": str(exc)}, status=400)
    if result is None:
        return _json({"error": "room not found"}, status=404)
    return _json({"ok": True, "room": _serialize_room(result)})
