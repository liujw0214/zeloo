"""Group chat HTTP route — multi-agent fan-out for the dashboard /chat tab.

Spawns one Zeloo CLI subprocess per worker profile in parallel, then asks the
host profile to synthesize a final reply using the worker outputs as context.
Mirrors ``chat.py`` but fans out across profiles; the page-level result is one
``host`` answer plus a per-worker trail the UI can render in columns.

Endpoints:
  POST /api/group-chat/send
    body:  {"prompt": "...", "host": "<profile>", "workers": ["a","b"], "timeout_s": 180}
    reply: {"ok": true, "host": "<profile>", "host_output": "...", "host_elapsed_s": 1.2,
            "workers": [{"name":"a","output":"...","elapsed_s":0.8,"ok":true},
                        {"name":"b","output":"...","elapsed_s":0.9,"ok":false,"error":"timeout"}],
            "elapsed_s": 2.0, "total_workers": 2, "failed_workers": 1}
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from zeloo_cli.web_routers._common import log as _log

router = APIRouter()

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
_MAX_WORKERS = 8
_MAX_WORKER_OUTPUT_CHARS = 4000  # truncate each worker answer before sending to host


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class GroupChatSendBody(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=64_000)
    host: str = Field(..., min_length=1, max_length=64)
    workers: List[str] = Field(..., min_length=1, max_length=_MAX_WORKERS)
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_ansi(text: str) -> str:
    cleaned = _ANSI_ESCAPE_RE.sub("", text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned.strip())
    return cleaned.strip()


def _resolve_cli() -> Optional[str]:
    candidate = sys.executable
    if candidate and Path(candidate).is_file():
        return candidate
    return shutil.which("Zeloo") or shutil.which("zeloo")


def _project_root() -> Path:
    # web_routers/group_chat.py -> web_routers/.. -> zeloo_cli/.. -> project root
    return Path(__file__).resolve().parent.parent.parent


def _validate_profile_names(host: str, workers: List[str]) -> None:
    """Sanity-check profile names against the same regex the CLI uses.

    Avoids shell-injection (a profile name is passed via -p <name> on argv, but
    defense in depth) and catches typos early with a clear 400.
    """
    pat = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
    if not pat.match(host):
        raise HTTPException(status_code=400, detail=f"invalid host profile name: {host!r}")
    for w in workers:
        if not pat.match(w):
            raise HTTPException(status_code=400, detail=f"invalid worker profile name: {w!r}")


async def _spawn_zeloo(profile: str, prompt: str, timeout_s: int) -> WorkerResult:
    """Spawn ``Zeloo -z PROMPT -p <profile>`` and return its stdout as a WorkerResult."""
    cli_python = _resolve_cli()
    if not cli_python:
        return WorkerResult(name=profile, output="", elapsed_s=0.0, ok=False,
                            error="Zeloo CLI interpreter not found")

    project_root = _project_root()
    cmd = [cli_python, "-m", "zeloo_cli.main", "-z", prompt, "--cli", "-p", profile]
    cwd = str(project_root)

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")

    started = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=cwd, env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        return WorkerResult(name=profile, output="", elapsed_s=0.0, ok=False,
                            error=f"failed to spawn CLI: {exc}")

    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return WorkerResult(name=profile, output="", elapsed_s=time.time() - started,
                            ok=False, error=f"timeout after {timeout_s}s")

    elapsed = time.time() - started
    stdout = _strip_ansi(stdout_b.decode("utf-8", errors="replace"))
    stderr = stderr_b.decode("utf-8", errors="replace").strip()

    if proc.returncode != 0 and not stdout:
        return WorkerResult(name=profile, output="", elapsed_s=elapsed, ok=False,
                            error=f"exit {proc.returncode}: {stderr[:400]}")

    truncated = len(stdout) > _MAX_WORKER_OUTPUT_CHARS
    if truncated:
        stdout = stdout[:_MAX_WORKER_OUTPUT_CHARS] + "\n…[truncated]…"
    return WorkerResult(name=profile, output=stdout, elapsed_s=round(elapsed, 2),
                        ok=True)


def _build_host_prompt(user_prompt: str, workers: List[WorkerResult]) -> str:
    """Compose the synthesized prompt for the host profile.

    Format: original user prompt + a section listing each worker's answer (or its
    failure reason). The host is told to integrate these into a single reply.
    """
    lines: List[str] = [
        "You are the host of a multi-agent group chat. The user asked:",
        "",
        "--- USER PROMPT ---",
        user_prompt.strip(),
        "",
        "--- WORKER ANSWERS ---",
    ]
    for w in workers:
        lines.append(f"\n[{w.name}] (ok={w.ok}, {w.elapsed_s}s)")
        if w.ok:
            lines.append(w.output or "(empty)")
        else:
            lines.append(f"[FAILED] {w.error or 'unknown error'}")
    lines.append("")
    lines.append("--- TASK ---")
    lines.append("Integrate the worker answers above into a single, coherent reply to the user. "
                 "If any worker failed, acknowledge it briefly. Keep the response focused.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/api/group-chat/send", response_model=GroupChatSendReply)
async def group_chat_send(body: GroupChatSendBody) -> GroupChatSendReply:
    """Fan out user input to worker profiles, then synthesize via the host profile."""
    _validate_profile_names(body.host, body.workers)
    if body.host in body.workers:
        raise HTTPException(status_code=400, detail="host must not also be a worker")

    _log.info(
        "group_chat_send prompt=%d chars host=%s workers=%s timeout=%ds",
        len(body.prompt), body.host, body.workers, body.timeout_s,
    )

    started = time.time()
    # 1) Fan-out to workers in parallel.
    worker_results = await asyncio.gather(*[
        _spawn_zeloo(w, body.prompt, body.timeout_s) for w in body.workers
    ])
    failed = sum(1 for r in worker_results if not r.ok)

    # 2) Ask the host to synthesize the final reply.
    host_prompt = _build_host_prompt(body.prompt, worker_results)
    host_result = await _spawn_zeloo(body.host, host_prompt, body.timeout_s)

    elapsed = time.time() - started
    return GroupChatSendReply(
        ok=host_result.ok,
        host=body.host,
        host_output=host_result.output,
        host_elapsed_s=host_result.elapsed_s,
        workers=worker_results,
        elapsed_s=round(elapsed, 2),
        total_workers=len(worker_results),
        failed_workers=failed,
        note=None if host_result.ok else f"host failed: {host_result.error}",
    )


@router.get("/api/group-chat/status")
async def group_chat_status() -> dict:
    """Liveness probe: report max_workers + cli_path so the UI can disable itself early."""
    return {
        "max_workers": _MAX_WORKERS,
        "cli_path": _resolve_cli(),
        "available": bool(_resolve_cli()),
    }