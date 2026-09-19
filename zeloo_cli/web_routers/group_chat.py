from __future__ import annotations

from dataclasses import asdict
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from zeloo_cli.group_chat_lib import (
    GroupChatError,
    MAX_WORKERS,
    GroupChatResult,
    resolve_cli,
    run_group_chat_fan_out,
)

router = APIRouter()


class GroupChatSendBody(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=64_000)
    host: str = Field(..., min_length=1, max_length=64)
    workers: List[str] = Field(..., min_length=1, max_length=MAX_WORKERS)
    timeout_s: int = Field(180, ge=10, le=900)


class WorkerResult(BaseModel):
    name: str
    output: str
    elapsed_s: float
    ok: bool
    error: Optional[str] = None


class GroupChatSendReply(BaseModel):
    ok: bool
    host: str
    host_output: str
    host_elapsed_s: float
    workers: List[WorkerResult]
    elapsed_s: float
    total_workers: int
    failed_workers: int
    note: Optional[str] = None


@router.post("/api/group-chat/send", response_model=GroupChatSendReply)
async def group_chat_send(body: GroupChatSendBody) -> GroupChatSendReply:
    """Fan out user input to worker profiles, then synthesize via the host profile."""
    try:
        result: GroupChatResult = await run_group_chat_fan_out(
            prompt=body.prompt,
            host=body.host,
            workers=body.workers,
            timeout_s=body.timeout_s,
        )
    except GroupChatError as exc:
        # Bad input (invalid profile name, host == worker, too many workers) ->
        # surface as a 400 so the dashboard UI can show a friendly message.
        raise HTTPException(status_code=400, detail=str(exc))

    return GroupChatSendReply(
        ok=result.ok,
        host=result.host,
        host_output=result.host_output,
        host_elapsed_s=result.host_elapsed_s,
        workers=[WorkerResult(**asdict(w)) for w in result.workers],
        elapsed_s=result.elapsed_s,
        total_workers=result.total_workers,
        failed_workers=result.failed_workers,
        note=result.note,
    )


@router.get("/api/group-chat/status")
async def group_chat_status() -> dict:
    """Liveness probe: report max_workers + cli_path so the UI can disable itself early."""
    return {
        "max_workers": MAX_WORKERS,
        "cli_path": resolve_cli(),
        "available": bool(resolve_cli()),
    }
