"""Chat HTTP route — non-PTY fallback for the dashboard /chat tab.

The ``/api/pty`` WebSocket is the canonical chat transport (xterm.js + TUI),
but it needs a managed Node runtime and a working POSIX PTY. When those are
unavailable (e.g. native Windows, missing node, broken build stamp) the WS
fails fast and the page renders an error banner. This module gives the
frontend a simple HTTP fallback so the user can still send a one-shot prompt
and get the answer back as JSON.

Wire-up: the router is included in ``web_server.py`` next to ``chat_ws``.

Endpoint:
  POST /api/chat/send
    body:  {"prompt": "...", "model": "claude-opus-4-20250514" (optional)}
    reply: {"ok": true, "output": "...", "model": "...", "elapsed_s": 1.23}
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from zeloo_cli.web_routers._common import log as _log

router = APIRouter()

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


class ChatSendBody(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=64_000)
    model: Optional[str] = None
    timeout_s: int = Field(180, ge=5, le=900)


class ChatSendReply(BaseModel):
    ok: bool
    output: str
    model: Optional[str] = None
    elapsed_s: float
    truncated: bool = False
    note: Optional[str] = None


def _strip_ansi(text: str) -> str:
    cleaned = _ANSI_ESCAPE_RE.sub("", text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _resolve_cli() -> Optional[str]:
    """Locate the Zeloo CLI interpreter — same venv that runs the dashboard."""
    candidate = sys.executable
    if candidate and Path(candidate).is_file():
        return candidate
    on_path = shutil.which("Zeloo") or shutil.which("zeloo")
    return on_path


async def _run_oneshot(prompt: str, model: Optional[str], timeout_s: int) -> ChatSendReply:
    """Spawn ``Zeloo -z PROMPT`` and return its stdout as a JSON reply."""
    # `@agent` mention triggers the multi-agent fan-out path. We do this BEFORE
    # the subprocess spawn so the user gets the synthesized host reply instead
    # of a raw single-agent response.
    GroupChatError = None
    try:
        from zeloo_cli.group_chat_lib import (
            GroupChatError as _GCError,
            resolve_agent_mention,
            run_group_chat_fan_out_sync,
        )
        from zeloo_cli import profiles as profiles_mod
        GroupChatError = _GCError
        known = profiles_mod.list_profile_names()
        resolved = resolve_agent_mention(prompt, known_profiles=known)
    except Exception as exc:
        # Import / profile-listing / resolver crash → fall back to normal path.
        # Resolver-raised GroupChatError → surface as 400.
        if GroupChatError is not None and isinstance(exc, GroupChatError):
            raise HTTPException(status_code=400, detail=f"@agent: {exc}") from exc
        resolved = None

    if resolved is not None:
        cleaned, host, workers = resolved
        try:
            result = await asyncio.to_thread(
                run_group_chat_fan_out_sync, cleaned, host, workers, timeout_s=timeout_s,
            )
        except GroupChatError as exc:
            raise HTTPException(status_code=400, detail=f"@agent: {exc}") from exc
        return ChatSendReply(
            ok=result.ok,
            output=result.host_output or "(empty)",
            model=f"@agent fan-out host={result.host} workers={','.join(w.name for w in result.workers)}",
            elapsed_s=result.elapsed_s,
            truncated=False,
            note=result.note,
        )

    cli_python = _resolve_cli()
    if not cli_python:
        raise HTTPException(status_code=503, detail="Zeloo CLI interpreter not found")

    project_root = Path(__file__).resolve().parent.parent.parent
    cmd = [cli_python, "-m", "zeloo_cli.main", "-z", prompt, "--cli"]
    if model:
        cmd += ["-m", model]

    cwd = str(project_root)

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")

    started = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"failed to spawn CLI: {exc}") from exc

    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise HTTPException(status_code=504, detail=f"chat timed out after {timeout_s}s")

    elapsed = time.time() - started
    stdout = _strip_ansi(stdout_b.decode("utf-8", errors="replace"))
    stderr = stderr_b.decode("utf-8", errors="replace").strip()

    if proc.returncode != 0 and not stdout:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Zeloo CLI exited non-zero",
                "returncode": proc.returncode,
                "stderr": stderr[:4000],
            },
        )

    truncated = len(stdout) > 32_000
    if truncated:
        stdout = stdout[:32_000] + "\n\n…[truncated]…"

    note = None
    if stderr:
        note = f"stderr (first 400 chars): {stderr[:400]}"

    return ChatSendReply(
        ok=True,
        output=stdout or "(empty response)",
        model=model,
        elapsed_s=round(elapsed, 2),
        truncated=truncated,
        note=note,
    )


@router.post("/api/chat/send", response_model=ChatSendReply)
async def chat_send(body: ChatSendBody) -> ChatSendReply:
    """Send a one-shot prompt; return the full reply."""
    _log.info(
        "chat_send prompt=%d chars model=%s timeout=%ds",
        len(body.prompt), body.model or "(default)", body.timeout_s,
    )
    return await _run_oneshot(body.prompt, body.model, body.timeout_s)


@router.get("/api/chat/status")
async def chat_status() -> dict:
    """Cheap liveness probe so the frontend can decide which UI to render."""
    cli = _resolve_cli()
    return {
        "pty_ws_url": "/api/pty",
        "http_fallback_available": bool(cli),
        "cli_path": cli,
    }
