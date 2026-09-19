"""Cron-friendly wrapper around the group-chat fan-out library.

Two responsibilities:
  1. ``run_group_chat_cron_job(job)`` — invoked by ``cron/scheduler.py`` when a
     job has ``kind == "group_chat"``. Mirrors the contract of
     ``_run_no_agent_job``: returns ``(ok, doc_markdown, alert, error)``.
  2. ``validate_group_chat_job(job)`` — called by ``cron/jobs.create_job``
     so a job with bad host/workers fields is rejected at create-time
     instead of failing every fire.

The actual fan-out is delegated to ``zeloo_cli.group_chat_lib.run_group_chat_fan_out``
so the dashboard, CLI, cron, and webhook paths all share one implementation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from zeloo_cli.group_chat_lib import (
    GroupChatError,
    GroupChatResult,
    MAX_WORKERS,
    run_group_chat_fan_out,
    validate_inputs,
)


def _now_header_iso() -> str:
    """Local timestamp used in the cron doc header (matches the rest of the scheduler)."""
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _job_doc_header(job_name: str, job_id: str, when_iso: str, mode_label: str) -> str:
    return (
        f"# Cron Job: {job_name}\n\n"
        f"**Job ID:** {job_id}\n"
        f"**Run Time:** {when_iso}\n"
        f"**Mode:** {mode_label}\n\n"
    )


def validate_group_chat_job(job: Dict[str, Any]) -> None:
    """Reject malformed ``kind=group_chat`` jobs at create-time.

    Same checks ``validate_inputs`` runs at fire-time, raised eagerly so the
    operator gets a clear error during ``Zeloo cron create`` instead of every
    tick silently failing.
    """
    if job.get("kind") != "group_chat":
        return
    host = job.get("group_chat_host")
    workers = job.get("group_chat_workers") or []
    prompt = job.get("prompt") or ""
    if not host or not isinstance(host, str):
        raise GroupChatError(
            "kind=group_chat jobs require --host <profile> (group_chat_host is missing)"
        )
    if not workers or not isinstance(workers, list):
        raise GroupChatError(
            "kind=group_chat jobs require --workers a,b,c (group_chat_workers is missing or empty)"
        )
    validate_inputs(prompt=prompt, host=host, workers=workers)


async def run_group_chat_cron_job(
    job: Dict[str, Any],
    job_id: str,
    job_name: str,
    timeout_s: int = 180,
) -> Tuple[bool, str, str, Optional[str]]:
    """Run a ``kind=group_chat`` cron job and return the standard cron result tuple.

    The contract matches ``_run_no_agent_job`` so the scheduler can deliver
    the doc markdown via the same path that handles watchdog scripts:

        (ok, doc_markdown, alert, error)

    - ok: True when the host profile produced a non-empty reply, False otherwise.
    - doc_markdown: the host reply wrapped in the standard cron header, ready
      to ship to whatever ``--deliver`` target the job has.
    - alert: a short human-readable summary surfaced on failure; empty on success.
    - error: technical error string for the ledger; None on success.

    The synthesized host reply is also prepended with a compact worker trail
    (collapsed into one line per worker) so the operator can see why each
    worker contributed, not just the final answer.
    """
    host: str = job["group_chat_host"]
    workers: List[str] = list(job.get("group_chat_workers") or [])
    prompt: str = job.get("prompt") or ""

    # validate_inputs is defensive — create_job should have rejected bad jobs
    # already, but a hand-edited jobs.json may have bypassed that gate.
    validate_inputs(prompt=prompt, host=host, workers=workers)

    try:
        result: GroupChatResult = await run_group_chat_fan_out(
            prompt=prompt, host=host, workers=workers, timeout_s=timeout_s,
        )
    except GroupChatError as exc:
        now_iso = _now_header_iso()
        header = _job_doc_header(job_name, job_id, now_iso, "group_chat (config error)")
        msg = f"Group chat fan-out failed before run: {exc}"
        return False, f"{header}**Status:** config error\n\n{msg}\n", msg, msg

    now_iso = _now_header_iso()
    header = _job_doc_header(job_name, job_id, now_iso, f"group_chat (host={host}, workers={','.join(workers)})")

    # Build a compact worker trail — one short line each, so the doc isn't
    # dominated by raw worker output (which the host already integrated).
    trail_lines = []
    for w in result.workers:
        marker = "OK " if w.ok else "ERR"
        snippet = (w.output or w.error or "").replace("\n", " ").strip()
        if len(snippet) > 120:
            snippet = snippet[:120] + "…"
        trail_lines.append(f"- [{marker}] `{w.name}` ({w.elapsed_s}s) — {snippet}")
    worker_trail = "\n".join(trail_lines)

    body = (
        f"**Status:** {'ok' if result.ok else 'failed'}\n"
        f"**Host:** `{host}` ({result.host_elapsed_s}s)\n"
        f"**Workers:** {result.total_workers} total, {result.failed_workers} failed, "
        f"total fan-out {result.elapsed_s}s\n\n"
        f"## Worker trail\n{worker_trail}\n\n"
        f"## Host reply\n{result.host_output}\n"
    )

    if not result.ok:
        # Deliver the failure alert so a recurring config bug doesn't silently
        # produce empty docs every tick.
        alert = (
            f"⚠ Cron group chat '{job_name}' failed\n\n"
            f"Host `{host}` did not return a reply.\n"
            f"{result.note or ''}\n\n"
            f"Time: {now_iso}"
        )
        return False, f"{header}{body}\n", alert, result.note

    # ok=True, non-empty doc, empty alert — same shape as a no_agent silent run.
    return True, f"{header}{body}\n", result.host_output, None


def run_group_chat_cron_job_sync(job: Dict[str, Any], job_id: str, job_name: str) -> Tuple[bool, str, str, Optional[str]]:
    """Sync entry point for CLI ``Zeloo cron run`` / direct test callers."""
    import asyncio
    return asyncio.run(run_group_chat_cron_job(job, job_id, job_name))


__all__ = [
    "MAX_WORKERS",
    "validate_group_chat_job",
    "run_group_chat_cron_job",
    "run_group_chat_cron_job_sync",
]