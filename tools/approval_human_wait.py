"""Human-in-the-loop approval waiting.

Block execution until a human approves/denies via several transports:

- Polling an HTTP callback URL (JSON response with status field)
- Watching a file for an approval marker (systemd / devops scenarios)
- Watching a GitHub PR comment containing a marker token (e.g. ``/approve``)
- Native desktop notification (best-effort; falls back to logging)

All waiters share a common timeout/exception contract and never raise
arbitrary errors out to the caller — they return a dict with ``status``
set to ``"approved"``, ``"denied"``, ``"timeout"`` or ``"error"``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public dataclass returned by every waiter
# ---------------------------------------------------------------------------


@dataclass
class WaitResult:
    """Result of a human-in-the-loop wait.

    Attributes:
        status: One of ``"approved"``, ``"denied"``, ``"timeout"``, ``"error"``.
        reason: Human-readable explanation of the outcome.
        transport: Which transport produced the decision (callback/file/github/...).
        elapsed: Seconds spent waiting before returning.
        details: Optional transport-specific payload (response body, comment, ...).
    """

    status: str
    reason: str
    transport: str
    elapsed: float = 0.0
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation."""
        return {
            "status": self.status,
            "reason": self.reason,
            "transport": self.transport,
            "elapsed": round(self.elapsed, 3),
            "details": self.details or {},
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_result(
    status: str,
    reason: str,
    transport: str,
    elapsed: float,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a normalized dict result for every waiter."""
    return WaitResult(
        status=status,
        reason=reason,
        transport=transport,
        elapsed=elapsed,
        details=details,
    ).to_dict()


def _normalize_status(payload: Any) -> tuple[str, str]:
    """Extract ``(status, reason)`` from a callback payload.

    Accepts dict / str / bytes / list. Returns ``("pending", "")`` when the
    payload does not contain a recognizable decision.
    """
    if payload is None:
        return "pending", ""

    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8", errors="replace")
        except Exception:  # pragma: no cover - extremely defensive
            payload = ""

    if isinstance(payload, str):
        text = payload.strip().lower()
        if not text:
            return "pending", ""
        # Try JSON first
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            if text in {"approved", "approve", "ok", "true", "yes", "y", "1"}:
                return "approved", text
            if text in {"denied", "deny", "reject", "no", "n", "false", "0"}:
                return "denied", text
            return "pending", text

    if isinstance(payload, dict):
        status = str(payload.get("status") or payload.get("decision") or "").lower()
        reason = str(payload.get("reason") or payload.get("message") or "")
        if status in {"approved", "approve", "ok"}:
            return "approved", reason
        if status in {"denied", "deny", "rejected", "reject", "no"}:
            return "denied", reason
        return "pending", reason

    return "pending", ""


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class HumanApprovalWaiter:
    """Wait for human approval with multiple transport options.

    Each ``wait_for_*`` method blocks (asynchronously) until the human
    responds, the timeout fires, or an error occurs. The methods never
    propagate raw exceptions — instead they return a dict with
    ``status`` set to one of:

    - ``"approved"`` — human approved the action
    - ``"denied"`` — human denied the action
    - ``"timeout"`` — waited longer than ``self.timeout`` seconds
    - ``"error"`` — transport-level error (network / file not found / ...)

    Args:
        approval_id: Unique identifier of this approval request. Used for
            logging and embedded in callback URLs / GitHub comments so
            multiple concurrent approvals can be disambiguated.
        timeout: Default timeout in seconds for all ``wait_for_*`` methods.
    """

    DEFAULT_INTERVAL = 2.0
    DEFAULT_GITHUB_API = "https://api.github.com"

    def __init__(self, approval_id: str, timeout: float = 300.0) -> None:
        self.approval_id = approval_id
        self.timeout = float(timeout)

    # ------------------------------------------------------------------
    # HTTP callback transport
    # ------------------------------------------------------------------

    async def wait_for_callback(
        self,
        callback_url: str,
        interval: float = DEFAULT_INTERVAL,
        *,
        headers: dict[str, str] | None = None,
        auth: tuple[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Poll callback URL for approval status.

        The URL is polled every ``interval`` seconds using ``httpx``. The
        response body must be JSON of the shape
        ``{"status": "approved" | "denied" | "pending", "reason": "..."}``.
        Plain-text ``"approved"`` / ``"denied"`` is also accepted.

        Args:
            callback_url: HTTP(S) URL exposing the approval state.
            interval: Seconds between polls.
            headers: Optional HTTP headers (e.g. bearer tokens).
            auth: Optional ``(username, password)`` basic auth tuple.
            timeout: Override the per-request HTTP timeout (seconds).

        Returns:
            Dict with ``status``, ``reason``, ``transport="callback"`` and
            ``details`` containing the last successful response body.
        """
        transport = "callback"
        effective_timeout = float(timeout) if timeout is not None else self.timeout
        start = time.monotonic()
        last_details: dict[str, Any] = {}

        try:
            import httpx  # local import keeps module importable without httpx at import time
        except ImportError as exc:  # pragma: no cover - guarded
            logger.error("httpx is required for wait_for_callback: %s", exc)
            return _to_result("error", "httpx_not_available", transport, 0.0)

        http_timeout = max(interval, 1.0)
        async with httpx.AsyncClient(
            timeout=http_timeout,
            headers=headers or {},
            auth=auth,
        ) as client:
            while True:
                elapsed = time.monotonic() - start
                if elapsed >= effective_timeout:
                    return _to_result(
                        "timeout",
                        f"No callback response within {effective_timeout}s",
                        transport,
                        elapsed,
                        last_details,
                    )

                try:
                    response = await client.get(
                        callback_url,
                        params={"approval_id": self.approval_id},
                    )
                    if response.status_code < 400:
                        try:
                            payload = response.json()
                        except (ValueError, json.JSONDecodeError):
                            payload = response.text

                        status, reason = _normalize_status(payload)
                        last_details = {
                            "status_code": response.status_code,
                            "body": payload if not isinstance(payload, bytes) else payload.decode(
                                "utf-8", errors="replace"
                            ),
                        }
                        if status in {"approved", "denied"}:
                            return _to_result(
                                status,
                                reason or status,
                                transport,
                                elapsed,
                                last_details,
                            )
                except httpx.HTTPError as exc:
                    logger.debug("Callback poll error (will retry): %s", exc)
                    last_details = {"error": str(exc)}

                await asyncio.sleep(max(interval, 0.1))

    # ------------------------------------------------------------------
    # File-based transport
    # ------------------------------------------------------------------

    async def wait_for_file(
        self,
        watch_path: str | Path,
        approval_marker: str = "APPROVED",
        *,
        denial_marker: str = "DENIED",
        interval: float = DEFAULT_INTERVAL,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Watch a file for an approval marker.

        Intended for systemd/devops scenarios where an operator writes a
        marker into a file (e.g. ``/run/Zeloo/<approval_id>.txt``). The
        file is polled every ``interval`` seconds.

        The first occurrence of ``approval_marker`` (case-insensitive)
        triggers ``"approved"``; the first occurrence of ``denial_marker``
        triggers ``"denied"``. Either marker may appear anywhere in the
        file content.

        Args:
            watch_path: File path to watch. Created if it does not exist
                (so that absence does not look like denial).
            approval_marker: Marker substring meaning "approve".
            denial_marker: Marker substring meaning "deny".
            interval: Poll interval in seconds.
            timeout: Override the default timeout.

        Returns:
            Dict with ``status``, ``reason``, ``transport="file"`` and
            ``details`` containing the file content that resolved the wait.
        """
        transport = "file"
        effective_timeout = float(timeout) if timeout is not None else self.timeout
        start = time.monotonic()
        path = Path(watch_path)
        approval_lower = approval_marker.lower()
        denial_lower = denial_marker.lower()

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.touch()
        except OSError as exc:
            logger.error("Cannot prepare watch file %s: %s", path, exc)
            return _to_result("error", f"file_unreachable: {exc}", transport, 0.0)

        while True:
            elapsed = time.monotonic() - start
            if elapsed >= effective_timeout:
                return _to_result(
                    "timeout",
                    f"No marker found in {path} within {effective_timeout}s",
                    transport,
                    elapsed,
                )

            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                logger.debug("File read error (will retry): %s", exc)
                content = ""

            content_lower = content.lower()
            if approval_lower in content_lower:
                return _to_result(
                    "approved",
                    f"Marker {approval_marker!r} found",
                    transport,
                    elapsed,
                    {"content": content, "path": str(path)},
                )
            if denial_lower in content_lower:
                return _to_result(
                    "denied",
                    f"Marker {denial_marker!r} found",
                    transport,
                    elapsed,
                    {"content": content, "path": str(path)},
                )

            await asyncio.sleep(max(interval, 0.1))

    # ------------------------------------------------------------------
    # GitHub PR comment transport
    # ------------------------------------------------------------------

    async def wait_for_github_comment(
        self,
        pr_number: int,
        repo: str,
        marker: str = "/approve",
        *,
        denial_marker: str = "/deny",
        interval: float = 10.0,
        timeout: float | None = None,
        token: str | None = None,
        api_base: str = DEFAULT_GITHUB_API,
        since_iso: str | None = None,
    ) -> dict[str, Any]:
        """Wait for a GitHub PR comment containing an approval marker.

        Polls the GitHub REST API for new issue comments on the given PR
        and looks for a comment whose body contains ``marker`` or
        ``denial_marker``. Requires ``httpx`` and a GitHub token
        (falls back to ``GITHUB_TOKEN`` / ``GH_TOKEN`` env vars).

        Args:
            pr_number: Pull request number.
            repo: ``owner/name`` of the repository.
            marker: Substring that signals approval.
            denial_marker: Substring that signals denial.
            interval: Poll interval in seconds (GitHub recommends >=10s).
            timeout: Override the default timeout.
            token: GitHub token. Falls back to ``GITHUB_TOKEN``/``GH_TOKEN``.
            api_base: Base URL for the GitHub API (override for GHES).
            since_iso: Only consider comments newer than this ISO timestamp.
                Defaults to "now" so we only react to comments made while
                waiting.

        Returns:
            Dict with ``status``, ``reason``, ``transport="github"`` and
            ``details`` containing the matching comment payload.
        """
        transport = "github"
        effective_timeout = float(timeout) if timeout is not None else self.timeout
        start = time.monotonic()
        gh_token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

        try:
            import httpx  # noqa: F811  (local import kept consistent with wait_for_callback)
        except ImportError as exc:  # pragma: no cover - guarded
            logger.error("httpx is required for wait_for_github_comment: %s", exc)
            return _to_result("error", "httpx_not_available", transport, 0.0)

        if not gh_token:
            return _to_result(
                "error",
                "missing_github_token",
                transport,
                0.0,
                {"hint": "Set GITHUB_TOKEN / GH_TOKEN env var or pass token="},
            )

        headers = {
            "Authorization": f"Bearer {gh_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Zeloo-approval-waiter",
        }
        if since_iso is None:
            since_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start))

        url = f"{api_base.rstrip('/')}/repos/{repo}/issues/{pr_number}/comments"
        params: dict[str, str] = {"per_page": "100", "sort": "created", "direction": "desc"}

        async with httpx.AsyncClient(timeout=max(interval, 5.0), headers=headers) as client:
            while True:
                elapsed = time.monotonic() - start
                if elapsed >= effective_timeout:
                    return _to_result(
                        "timeout",
                        f"No GitHub comment within {effective_timeout}s",
                        transport,
                        elapsed,
                    )

                try:
                    response = await client.get(url, params=params)
                    if response.status_code == 200:
                        comments = response.json() or []
                        for comment in comments:
                            created_at = str(comment.get("created_at", ""))
                            if created_at and created_at < since_iso:
                                continue
                            body = str(comment.get("body", "") or "")
                            body_lower = body.lower()
                            if marker.lower() in body_lower:
                                return _to_result(
                                    "approved",
                                    f"Marker {marker!r} found",
                                    transport,
                                    elapsed,
                                    {"comment": comment, "approval_id": self.approval_id},
                                )
                            if denial_marker.lower() in body_lower:
                                return _to_result(
                                    "denied",
                                    f"Marker {denial_marker!r} found",
                                    transport,
                                    elapsed,
                                    {"comment": comment, "approval_id": self.approval_id},
                                )
                    else:
                        logger.debug(
                            "GitHub API returned %s: %s",
                            response.status_code,
                            response.text[:200],
                        )
                except httpx.HTTPError as exc:
                    logger.debug("GitHub poll error (will retry): %s", exc)

                await asyncio.sleep(max(interval, 1.0))

    # ------------------------------------------------------------------
    # Desktop notification transport (best effort)
    # ------------------------------------------------------------------

    async def notify_desktop(
        self,
        title: str,
        message: str,
        actions: list[str] | None = None,
    ) -> dict[str, Any]:
        """Show a native desktop notification (best effort).

        Tries platform-specific notifiers in order:
        - macOS: ``osascript -e 'display notification ...'``
        - Linux: ``notify-send`` (libnotify)
        - Windows: ``powershell BurntToast``/``win10toast`` (optional) or
          a fallback PowerShell ``MessageBox``.

        If no native notifier is available the message is logged via
        ``logger.warning`` so that headless / CI runs still record the
        prompt.

        Args:
            title: Notification title.
            message: Notification body.
            actions: Optional list of suggested action labels (displayed
                only when supported by the underlying notifier).

        Returns:
            Dict with ``status`` (``"sent"``/``"error"``) and details.
        """
        transport = "desktop"
        system = platform.system().lower()
        actions = list(actions or [])
        try:
            if system == "darwin":
                return await self._notify_macos(title, message, actions)
            if system == "linux":
                return await self._notify_linux(title, message, actions)
            if system == "windows":
                return await self._notify_windows(title, message, actions)
            logger.warning("[approval-waiter] %s: %s (actions=%s)", title, message, actions)
            return _to_result(
                "sent",
                "logged_no_native_support",
                transport,
                0.0,
                {"system": system, "fallback": "logger"},
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Desktop notification failed: %s", exc)
            return _to_result(
                "error",
                f"desktop_notify_failed: {exc}",
                transport,
                0.0,
                {"system": system},
            )

    async def _notify_macos(
        self, title: str, message: str, actions: list[str]
    ) -> dict[str, Any]:
        script = f'display notification "{message}" with title "{title}"'
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"osascript failed: {err.decode('utf-8', errors='replace')}")
        return _to_result(
            "sent",
            "macos_notification_dispatched",
            "desktop",
            0.0,
            {"system": "darwin", "actions": actions},
        )

    async def _notify_linux(
        self, title: str, message: str, actions: list[str]
    ) -> dict[str, Any]:
        if not shutil.which("notify-send"):
            raise RuntimeError("notify-send not installed")
        proc = await asyncio.create_subprocess_exec(
            "notify-send", "--app-name", "Zeloo", title, message,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"notify-send failed: {err.decode('utf-8', errors='replace')}")
        return _to_result(
            "sent",
            "linux_notification_dispatched",
            "desktop",
            0.0,
            {"system": "linux", "actions": actions},
        )

    async def _notify_windows(
        self, title: str, message: str, actions: list[str]
    ) -> dict[str, Any]:
        # Prefer BurntToast if installed (PowerShell module), else fall back
        # to a generic MessageBox via PowerShell.
        ps_script = (
            "Add-Type -AssemblyName PresentationFramework; "
            f"[System.Windows.MessageBox]::Show('{message}', '{title}', "
            "'OK', 'Information') | Out-Null"
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "powershell",
                "-NoProfile",
                "-Command",
                ps_script,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, err = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(
                    f"powershell notify failed: {err.decode('utf-8', errors='replace')}"
                )
            return _to_result(
                "sent",
                "windows_messagebox_dispatched",
                "desktop",
                0.0,
                {"system": "windows", "actions": actions},
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"powershell not available: {exc}") from exc


__all__ = ["HumanApprovalWaiter", "WaitResult"]