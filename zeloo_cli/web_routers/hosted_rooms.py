"""
M1.5 Phase 6 part 3: hosted-rooms FastAPI router for ``Zeloo serve``.

Mounts ``/api/hosted_rooms`` on the same FastAPI app that already
serves ``/api/profiles``, ``/api/sessions``, and the other desktop
client surfaces on port 9119. The previous Phase 6 part 2 commit
added the same routes on the gateway api_server (aiohttp, port
8642) so the room CRUD surface works against the gateway
directly. THIS commit closes the loop on the desktop's real
path: ``Zeloo serve`` -> IPC ``Zeloo:api`` -> HTTP fetch on 9119
-> THIS router -> in-process call to ``gateway.hosted_rooms``
(same sqlite, same authority, same author/committer signature).

The two layers are deliberately not unified: the gateway layer
is the authoritative surface for messaging / multi-tenant
deployments, the serve layer is the desktop-local surface that
forks no new process. When a desktop renderer runs the M1.5
``/api/hosted_rooms`` query through its standard ``ZELOOApi``
helper, this router answers.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from gateway import hosted_rooms

router = APIRouter()
_log = logging.getLogger("zeloo_cli.web_routers.hosted_rooms")


# ---- request / response models ---------------------------------------------

class RoomMemberIn(BaseModel):
    member_id: str
    kind: str  # 'user' | 'agent' | 'sub-agent' | 'gateway' | 'system'
    display_name: Optional[str] = None
    profile: Optional[str] = None
    capabilities: Optional[List[str]] = None


class CreateRoomIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    members: List[RoomMemberIn] = Field(..., min_length=1)
    room_id: Optional[str] = None  # server mints if absent


class CreateRoomOut(BaseModel):
    room: dict


# ---- helpers ----------------------------------------------------------------

def _serialize_room(room: dict) -> dict:
    members = room.get("members")
    if isinstance(members, str):
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


def _serialize_event(ev: dict) -> dict:
    """Decode payload_json / actor_json into nested objects so the
    desktop typed client sees the same shape the gateway wrote."""
    row = dict(ev)
    pj = row.pop("payload_json", None)
    aj = row.pop("actor_json", None)
    if isinstance(pj, str):
        try:
            row["payload"] = json.loads(pj)
        except json.JSONDecodeError:
            row["payload"] = None
    if isinstance(aj, str):
        try:
            row["actor"] = json.loads(aj)
        except json.JSONDecodeError:
            row["actor"] = None
    return row


# ---- routes -----------------------------------------------------------------

@router.get("/api/hosted_rooms")
def list_rooms(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    include_disbanded: bool = Query(False),
):
    rooms = hosted_rooms.list_rooms(
        hosted_rooms.default_db_path(),
        include_disbanded=include_disbanded,
        limit=limit,
        offset=offset,
    )
    return {
        "rooms": [_serialize_room(r) for r in rooms],
        "total": len(rooms),
        "limit": limit,
        "offset": offset,
    }


@router.post("/api/hosted_rooms", status_code=201)
def create_room(body: CreateRoomIn):
    # The desktop caller may either let the server mint a room_id
    # (the common case) or supply one explicitly. The gateway's
    # create_room requires room_id as a keyword, so we generate one
    # server-side when the body omits it.
    room_id = body.room_id
    if not room_id:
        ts_hex = format(int(time.time() * 1_000_000) & 0xFFFFFFFF, "08x")
        room_id = f"r-{hosted_rooms.local_authority_gateway_id()[:8]}-{ts_hex}"
    try:
        result = hosted_rooms.create_room(
            hosted_rooms.default_db_path(),
            room_id=room_id,
            name=body.name,
            members=[m.model_dump() for m in body.members],
            authority_gateway_id=hosted_rooms.local_authority_gateway_id(),
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"room": _serialize_room(result)}


@router.get("/api/hosted_rooms/{room_id}")
def get_room(room_id: str):
    rooms = hosted_rooms.list_rooms(
        hosted_rooms.default_db_path(),
        include_disbanded=True,
        limit=500,
    )
    match = next((r for r in rooms if r.get("room_id") == room_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail="room not found")
    return _serialize_room(match)


@router.delete("/api/hosted_rooms/{room_id}")
def disband_room(room_id: str):
    rooms = hosted_rooms.list_rooms(
        hosted_rooms.default_db_path(),
        include_disbanded=True,
        limit=500,
    )
    match = next((r for r in rooms if r.get("room_id") == room_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail="room not found")
    try:
        result = hosted_rooms.disband_room(
            hosted_rooms.default_db_path(),
            room_id=room_id,
            expected_gateway_id=match.get("authority_gateway_id", ""),
            expected_epoch=match.get("authority_epoch", 0),
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=404, detail="room not found")
    return {"ok": True, "room": _serialize_room(result)}


@router.get("/api/hosted_rooms/{room_id}/events")
def list_room_events(
    room_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    kinds: Optional[str] = Query(None, description="comma-separated kind allowlist"),
):
    kind_list = [k.strip() for k in (kinds or "").split(",") if k.strip()] or None
    try:
        events = hosted_rooms.list_room_events(
            hosted_rooms.default_db_path(),
            room_id=room_id,
            limit=limit,
            offset=offset,
            kinds=kind_list,
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "events": [_serialize_event(e) for e in events],
        "total": len(events),
        "limit": limit,
        "offset": offset,
    }
