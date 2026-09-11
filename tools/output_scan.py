"""Shared post-output secret scanner for tool results.

Used by ``file_read`` / ``shell`` / ``shell_unsafe`` / ``web_fetch`` so
a leaked credential never reaches the LLM context.

The scanner is **best-effort and stateless**: any failure is logged
and the original content is returned unchanged so the tool path never
breaks because of scanner bugs.

Filter semantics:

  * ``SecretScanner.redact()`` already handles which rules are
    ``auto_redact=True`` (HIGH/CRITICAL/MEDIUM by default) and which
    are flag-only (LOW). This module delegates to that machinery.
  * When findings are detected, an audit event ``tool_output_secret_found``
    is written with the findings + categories + counts.
  * A one-line ``[Zeloo: redacted N secret(s) ...]`` header is
    prepended so the LLM can see that the content was altered.

The whole call is wrapped in try/except so any failure — scanner
import, scanner crash, audit failure — degrades gracefully to the
original content.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

# Module-level state (process-wide).
_state_lock = threading.RLock()
_enabled = True


def output_scan_enabled() -> bool:
    """Return whether output scanning is currently active."""
    with _state_lock:
        return _enabled


def set_output_scan_enabled(enabled: bool) -> None:
    """Globally enable / disable post-output secret scanning."""
    global _enabled
    with _state_lock:
        _enabled = bool(enabled)


def scan_tool_output(
    content: str,
    *,
    tool_name: str,
    source: str,
) -> str:
    """Run *content* through the secret scanner and return redacted text.

    Args:
        content: The text returned by a tool (``str``). Empty/None is a
            no-op.
        tool_name: Name of the calling tool (for audit / logs).
        source: A short identifier of where the content came from
            (e.g. a file path or URL).

    Returns:
        The (possibly redacted) string. If anything was redacted, a
        one-line header is prepended so the LLM can see that content
        was altered.
    """
    if not content or not output_scan_enabled():
        return content

    try:
        from agent.secret_scanner import SecretScanner
    except Exception as exc:  # noqa: BLE001
        logger.warning("output_scan: scanner import failed: %s", exc)
        return content

    try:
        result = SecretScanner().scan_and_redact(content)
    except Exception as exc:  # noqa: BLE001
        logger.warning("output_scan: scan failed for %s: %s", tool_name, exc)
        return content

    if not result.has_findings:
        return content

    _audit(tool_name=tool_name, source=source, result=result)

    # Only emit the redacted prefix + text when something was actually
    # stripped (low-severity findings may be flagged without redaction).
    redacted = result.redacted_text
    if redacted is None or redacted == content:
        # Nothing auto-redactable — return content unchanged but log.
        logger.info(
            "output_scan: %d low/medium secret(s) flagged in %s (no redaction)",
            len(result.findings),
            tool_name,
        )
        return content

    summary = ", ".join(
        f"{cat}({n})" for cat, n in sorted(result.by_severity.items()) if n > 0
    )
    logger.warning(
        "output_scan: %d secret(s) redacted from %s:%s [%s]",
        len(result.findings),
        tool_name,
        source,
        summary,
    )

    header = (
        f"[Zeloo: redacted {len(result.findings)} secret(s) from {tool_name} — {summary}]\n"
    )
    return header + redacted


def _audit(*, tool_name: str, source: str, result: Any) -> None:
    """Best-effort write of an audit event for the finding."""
    try:
        from agent.audit_log import audit_event

        audit_event(
            "tool_output_secret_found",
            actor=f"tool:{tool_name}",
            resource=source,
            outcome="ok",
            detail={
                "tool": tool_name,
                "source": source,
                "finding_count": len(result.findings),
                "counts_by_severity": result.by_severity,
                "categories": sorted(result.categories),
            },
        )
    except Exception:  # noqa: BLE001
        pass


__all__ = [
    "output_scan_enabled",
    "scan_tool_output",
    "set_output_scan_enabled",
]
