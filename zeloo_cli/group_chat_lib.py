"""Multi-agent fan-out library — reused by HTTP route, CLI, cron, and webhook.

Public surface:
  - `run_group_chat_fan_out(prompt, host, workers, *, timeout_s=180)` -> dict
  - `GroupChatResult` dataclass (or plain dict) with host + workers fields

This is the SINGLE source of truth for "spawn one CLI subprocess per worker
in parallel, then ask the host to synthesize". The HTTP route in
``zeloo_cli/web_routers/group_chat.py`` is now a thin wrapper around this
function; the ``Zeloo group-chat send`` CLI, the ``kind=group_chat`` cron
job, and the ``deliver=group_chat`` webhook target all call it directly.

Everything that used to be HTTP-shaped (Pydantic models, FastAPI exceptions)
is converted to plain raises + dataclasses so callers from any context get a
clean Python API.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class WorkerResult:
    name: str
    output: str
    elapsed_s: float
    ok: bool
    error: Optional[str] = None


@dataclass
class GroupChatResult:
    ok: bool
    host: str
    host_output: str
    host_elapsed_s: float
    workers: List[WorkerResult]
    elapsed_s: float
    total_workers: int
    failed_workers: int
    note: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "host": self.host,
            "host_output": self.host_output,
            "host_elapsed_s": self.host_elapsed_s,
            "workers": [asdict(w) for w in self.workers],
            "elapsed_s": self.elapsed_s,
            "total_workers": self.total_workers,
            "failed_workers": self.failed_workers,
            "note": self.note,
        }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_PROFILE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_MAX_WORKERS = 8
_MAX_WORKER_OUTPUT_CHARS = 4000


class GroupChatError(ValueError):
    """Raised when fan-out input is invalid (bad profile name, host == worker, …)."""


def validate_profile_name(name: str) -> None:
    if not _PROFILE_NAME_RE.match(name):
        raise GroupChatError(
            f"invalid profile name: {name!r} (must match ^[a-z0-9][a-z0-9_-]{{0,63}}$)"
        )


def validate_inputs(prompt: str, host: str, workers: List[str]) -> None:
    if not prompt or not prompt.strip():
        raise GroupChatError("prompt must be non-empty")
    if len(prompt) > 64_000:
        raise GroupChatError(f"prompt too long ({len(prompt)} chars, max 64000)")
    validate_profile_name(host)
    if not workers:
        raise GroupChatError("workers must contain at least 1 profile")
    if len(workers) > _MAX_WORKERS:
        raise GroupChatError(f"too many workers ({len(workers)}, max {_MAX_WORKERS})")
    for w in workers:
        validate_profile_name(w)
    if host in workers:
        raise GroupChatError("host must not also be a worker")


# ---------------------------------------------------------------------------
# @agent mention parsing
# ---------------------------------------------------------------------------
# `@agent` is a meta-token: when present in a prompt, it triggers group-chat
# fan-out instead of the normal single-agent run. Accepts inline options:
#
#   @agent                                -> bare: caller resolves via known_profiles
#   @agent(host=<profile>)                -> explicit host, workers resolved via known_profiles
#   @agent(workers=a,b,c)                 -> explicit workers, host resolved via known_profiles
#   @agent(host=<profile>, workers=a,b,c) -> both explicit
#
# Only ONE @agent per prompt is honoured — the first occurrence wins; later
# @agent tokens are treated as literal text. This avoids ambiguity and matches
# how @profile mentions already behave in the bundle.

_AGENT_MENTION_RE = re.compile(
    r"@agent"                                # the literal token
    r"(?:\(\s*([^)]*?)\s*\))?"               # optional inline options inside (...)
    ,
    re.IGNORECASE,
)

# Bare @agent followed by a non-letter (so "@agent42" wouldn't match) — we want
# to catch the literal word "agent", not substrings. We use a negative lookahead
# at the end so "@agent42" or "@agent_xyz" still parses the @agent prefix.
_AGENT_MENTION_BOUNDARY_RE = re.compile(
    r"@agent(?![a-z0-9_-])"                  # @agent not followed by another name char
    r"(?:\(\s*([^)]*?)\s*\))?"
    ,
    re.IGNORECASE,
)


def _parse_agent_options(raw: str) -> Dict[str, str]:
    """Parse ``host=foo, workers=a,b,c`` -> ``{"host": "foo", "workers": "a,b,c"}``.

    Unknown keys are silently dropped (forward-compat). Empty values are
    preserved so the caller can surface a clean error.
    """
    out: Dict[str, str] = {}
    if not raw:
        return out
    # Split on top-level commas — but commas inside ``workers=a,b,c`` are part of the value.
    # Tokenize by scanning for ``key=`` first, then collect the value up to the next ``,key=``.
    i = 0
    while i < len(raw):
        # skip whitespace + commas between options
        while i < len(raw) and raw[i] in " ,":
            i += 1
        if i >= len(raw):
            break
        # find ``=``
        eq = raw.find("=", i)
        if eq == -1:
            break
        key = raw[i:eq].strip().lower()
        i = eq + 1
        # value runs until the next ``,<ws>key=`` pattern (top-level separator)
        j = i
        while j < len(raw):
            if raw[j] == ",":
                # peek ahead — is the next non-space char the start of ``key=`` ?
                k = j + 1
                while k < len(raw) and raw[k] == " ":
                    k += 1
                if k < len(raw) and raw[k].isalpha():
                    next_eq = raw.find("=", k)
                    if next_eq != -1 and next_eq - k < 32:
                        candidate = raw[k:next_eq].strip().lower()
                        if candidate in {"host", "workers"}:
                            break
            j += 1
        value = raw[i:j].strip()
        if key in {"host", "workers"}:
            out[key] = value
        i = j + 1
    return out


def extract_agent_mention(prompt: str) -> Tuple[Optional[str], Optional[str], Optional[List[str]], Optional[Dict[str, str]]]:
    """Pull the first ``@agent(...)`` mention out of ``prompt``.

    Returns ``(cleaned_prompt, host, workers, options)``. When the prompt has
    no ``@agent`` token the tuple is ``(None, None, None, None)``. ``workers``
    is always a list when present (possibly empty if explicitly set that way).

    The matched token is stripped from the cleaned prompt — callers don't need
    to filter it themselves. Later @agent occurrences (rare, but valid as
    literal text) are left in the cleaned prompt.
    """
    if not prompt or not _AGENT_MENTION_BOUNDARY_RE.search(prompt):
        return None, None, None, None

    m = _AGENT_MENTION_BOUNDARY_RE.search(prompt)
    if not m:
        return None, None, None, None

    options = _parse_agent_options(m.group(1) or "")
    host = options.get("host") or None
    workers_raw = options.get("workers") or ""
    workers = [w.strip() for w in workers_raw.split(",") if w.strip()] if workers_raw else None

    # Strip the @agent token (with optional parens) + trailing whitespace before
    # the next non-space char. Leave the surrounding text intact.
    cleaned = (prompt[:m.start()] + prompt[m.end():]).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, host, workers, options


def resolve_agent_mention(
    prompt: str,
    *,
    known_profiles: List[str],
    default_host: Optional[str] = None,
) -> Optional[Tuple[str, str, List[str]]]:
    """Resolve an ``@agent`` mention into ``(cleaned_prompt, host, workers)``.

    Returns ``None`` when the prompt has no ``@agent``. Otherwise:

    * explicit ``host=`` and ``workers=`` in the token win verbatim
    * explicit ``host=`` only: workers are the remaining known profiles (capped
      at ``_MAX_WORKERS``), excluding the host
    * explicit ``workers=`` only: host defaults to ``default_host`` (or the
      first known profile alphabetically)
    * bare ``@agent``: first known profile alphabetically is host, the next
      up to ``_MAX_WORKERS - 1`` are workers

    Always raises ``GroupChatError`` when the resolved set has fewer than 2
    distinct profiles (need host + ≥1 worker to fan out) or when any explicit
    profile name fails ``validate_profile_name``.

    ``known_profiles`` MUST contain at least 2 names; otherwise the bare form
    raises (the explicit form still works if names are valid).
    """
    cleaned, host, workers, options = extract_agent_mention(prompt)
    if cleaned is None:
        return None

    known = [p for p in (known_profiles or []) if p]
    if not known:
        raise GroupChatError(
            "@agent mention detected but no known profiles to fan out to "
            "(create at least one profile via `Zeloo profile create`)"
        )

    # Validate explicit names eagerly so errors surface before subprocess spawn.
    if host:
        validate_profile_name(host)
    if workers:
        for w in workers:
            validate_profile_name(w)

    if not host:
        host = default_host or known[0]

    if not workers:
        # Remaining profiles, excluding the host, capped to fill up to MAX_WORKERS.
        rest = [p for p in known if p != host]
        if not rest:
            raise GroupChatError(
                f"@agent mention needs ≥2 distinct profiles; only '{host}' is known"
            )
        workers = rest[: _MAX_WORKERS]
    else:
        # Workers were explicit; drop any that equal the host and cap to MAX.
        workers = [w for w in workers if w != host][: _MAX_WORKERS]

    if host in workers:
        workers = [w for w in workers if w != host]

    if not workers:
        raise GroupChatError(
            f"@agent mention needs ≥1 worker besides host; resolved host='{host}', workers=[]"
        )

    # Final pass through validate_inputs so max_workers + host-in-workers is caught.
    validate_inputs(cleaned or "(empty)", host, workers)
    return cleaned, host, workers


# ---------------------------------------------------------------------------
# Subprocess plumbing
# ---------------------------------------------------------------------------

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


def _strip_ansi(text: str) -> str:
    cleaned = _ANSI_ESCAPE_RE.sub("", text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned.strip())
    return cleaned.strip()


def resolve_cli() -> Optional[str]:
    """The Zeloo interpreter entry point used to spawn per-profile subprocesses.

    Preference order:
      1. ``sys.executable`` — same interpreter the calling process is using,
         so the spawned workers run in the same venv with the same code on
         disk. This is the path that makes ``Zeloo group-chat send`` work
         both during development and inside the dashboard subprocess.
      2. ``Zeloo`` / ``zeloo`` on ``PATH`` — used when the caller is a small
         shell wrapper that doesn't have ``sys.executable`` handy.
    """
    candidate = sys.executable
    if candidate and Path(candidate).is_file():
        return candidate
    return shutil.which("Zeloo") or shutil.which("zeloo")


def project_root() -> Path:
    """Walk up from this file to find the Zeloo project root (where
    ``zeloo_cli/`` lives at the top level).

    Resolves ``zeloo_cli/group_chat_lib.py`` -> ``zeloo_cli/..`` -> project root.
    """
    return Path(__file__).resolve().parent.parent


async def spawn_zeloo(
    profile: str,
    prompt: str,
    *,
    timeout_s: int = 180,
    cli_path: Optional[str] = None,
) -> WorkerResult:
    """Spawn ``Zeloo -z PROMPT --cli -p <profile>`` and collect its stdout.

    Returns a ``WorkerResult`` regardless of failure so the fan-out loop can
    always carry on with the remaining workers.
    """
    cli_python = cli_path or resolve_cli()
    if not cli_python:
        return WorkerResult(
            name=profile, output="", elapsed_s=0.0, ok=False,
            error="Zeloo CLI interpreter not found (sys.executable and PATH both empty)",
        )

    cmd = [cli_python, "-m", "zeloo_cli.main", "-z", prompt, "--cli", "-p", profile]
    cwd = str(project_root())
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    # Allow the spawned child to inherit the gateway-side profile scope if it
    # was set by a cron / webhook dispatch. The flag is just a hint — the
    # CLI only reads it when the caller (cron scheduler / webhook runner)
    # explicitly installed it.
    env.setdefault("_ZELOO_CRON_GROUP_CHAT", "1")

    started = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=cwd, env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        return WorkerResult(
            name=profile, output="", elapsed_s=0.0, ok=False,
            error=f"failed to spawn CLI: {exc}",
        )

    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        finally:
            try:
                await proc.wait()
            except Exception:
                pass
        return WorkerResult(
            name=profile, output="", elapsed_s=time.time() - started,
            ok=False, error=f"timeout after {timeout_s}s",
        )

    elapsed = time.time() - started
    stdout = _strip_ansi(stdout_b.decode("utf-8", errors="replace"))
    stderr = stderr_b.decode("utf-8", errors="replace").strip()

    if proc.returncode != 0 and not stdout:
        return WorkerResult(
            name=profile, output="", elapsed_s=elapsed, ok=False,
            error=f"exit {proc.returncode}: {stderr[:400]}",
        )

    if len(stdout) > _MAX_WORKER_OUTPUT_CHARS:
        stdout = stdout[:_MAX_WORKER_OUTPUT_CHARS] + "\n…[truncated]…"
    return WorkerResult(name=profile, output=stdout, elapsed_s=round(elapsed, 2), ok=True)


# ---------------------------------------------------------------------------
# Host prompt assembly
# ---------------------------------------------------------------------------

def build_host_prompt(user_prompt: str, workers: List[WorkerResult]) -> str:
    """Compose the synthesized prompt sent to the host profile.

    Format: original user prompt + a section listing each worker's answer
    (or its failure reason). The host is told to integrate these into a single
    reply.
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
# Top-level entry point
# ---------------------------------------------------------------------------

async def run_group_chat_fan_out(
    prompt: str,
    host: str,
    workers: List[str],
    *,
    timeout_s: int = 180,
    cli_path: Optional[str] = None,
) -> GroupChatResult:
    """Fan out ``prompt`` to ``workers`` in parallel, then synthesize via ``host``.

    Args:
        prompt: User question / task. Already-cleaned — callers do NOT need to
            strip ``@profile`` mentions themselves.
        host: Profile name that produces the final reply.
        workers: Profile names that run in parallel as ``workers``. Must be
            non-empty, distinct from ``host``, and at most ``_MAX_WORKERS``.
        timeout_s: Per-profile subprocess timeout (10–900s). Default 180s.
        cli_path: Override the Zeloo CLI interpreter (mostly for tests). When
            None, uses ``sys.executable``.

    Returns:
        ``GroupChatResult`` — always returns even when every worker / the host
        failed; ``ok`` reflects the host's success.

    Raises:
        GroupChatError: bad inputs (invalid name, host == worker, too many
            workers, empty prompt). The fan-out itself never raises.
    """
    validate_inputs(prompt, host, workers)
    timeout_s = max(10, min(int(timeout_s), 900))

    started = time.time()
    # 1) Fan out to workers in parallel.
    worker_results = await asyncio.gather(*[
        spawn_zeloo(w, prompt, timeout_s=timeout_s, cli_path=cli_path)
        for w in workers
    ])
    failed = sum(1 for r in worker_results if not r.ok)

    # 2) Ask the host to synthesize.
    host_prompt = build_host_prompt(prompt, worker_results)
    host_result = await spawn_zeloo(
        host, host_prompt, timeout_s=timeout_s, cli_path=cli_path,
    )

    elapsed = time.time() - started
    return GroupChatResult(
        ok=host_result.ok,
        host=host,
        host_output=host_result.output,
        host_elapsed_s=host_result.elapsed_s,
        workers=worker_results,
        elapsed_s=round(elapsed, 2),
        total_workers=len(worker_results),
        failed_workers=failed,
        note=None if host_result.ok else f"host failed: {host_result.error}",
    )


def run_group_chat_fan_out_sync(
    prompt: str,
    host: str,
    workers: List[str],
    *,
    timeout_s: int = 180,
    cli_path: Optional[str] = None,
) -> GroupChatResult:
    """Synchronous wrapper around ``run_group_chat_fan_out``.

    Use from CLI / sync call sites. For asyncio callers (web route, webhook
    dispatcher, cron runner) call the async version directly.
    """
    return asyncio.run(
        run_group_chat_fan_out(
            prompt, host, workers, timeout_s=timeout_s, cli_path=cli_path,
        )
    )


# ---------------------------------------------------------------------------
# Constants exported for callers
# ---------------------------------------------------------------------------

MAX_WORKERS = _MAX_WORKERS
MAX_WORKER_OUTPUT_CHARS = _MAX_WORKER_OUTPUT_CHARS
__all__ = [
    "GroupChatError", "GroupChatResult", "WorkerResult",
    "MAX_WORKERS", "MAX_WORKER_OUTPUT_CHARS",
    "build_host_prompt", "resolve_cli", "project_root",
    "run_group_chat_fan_out", "run_group_chat_fan_out_sync",
    "spawn_zeloo", "validate_inputs", "validate_profile_name",
]