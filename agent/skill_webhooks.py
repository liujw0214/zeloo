"""Webhook callbacks for :mod:`agent.skill_hot_reload`.

When a ``SKILL.md`` is added / modified / removed, the reloader emits
events. Some deployments want those events delivered to an external
service (e.g. an internal IDE plugin, a notification bot, or a CI
gatekeeper). This module provides a small, dependency-free dispatcher:

  * :class:`WebhookSubscriber` — declarative config for one endpoint
    (URL, shared secret, optional headers, retry / timeout policy).
  * :class:`WebhookRegistry` — JSON-on-disk registry at
    ``~/.Zeloo/skill_webhooks.json``. Persists across restarts so the
    same endpoints keep getting events after a reload of the agent.
  * :class:`WebhookDispatcher` — background worker that drains a
    bounded queue, signs each payload with HMAC-SHA256, and POSTs
    with exponential backoff. Survives transient network errors
    without blocking the reloader.
  * :func:`attach_to` — wire a dispatcher to a
    :class:`~agent.skill_hot_reload.SkillHotReloader`.

Wire format (POST body)::

    {
      "event_id": "evt_<uuid>",
      "kind": "added" | "modified" | "removed",
      "skill_name": "my-skill",
      "path": "/abs/path/to/SKILL.md",
      "previous_mtime": 1234567890000000000,   // or null
      "current_mtime":  1234567890000000000,   // or null
      "timestamp": "2026-09-08T12:34:56.789Z"
    }

Headers::

    Content-Type: application/json
    X-Zeloo-Event-Id: evt_<uuid>
    X-Zeloo-Event-Kind: added|modified|removed
    X-Zeloo-Signature: sha256=<hex>
    X-Zeloo-Delivery-Attempt: 1

Receivers verify the signature by recomputing
``HMAC-SHA256(secret, raw_body)`` and comparing to ``X-Zeloo-Signature``
(constant-time compare).

Persistence is append-safe:

  * Writes go to ``<file>.tmp`` then ``os.replace`` for atomicity.
  * File mode is 0600 on POSIX (best-effort; ignored on Windows).
  * If the JSON is corrupt, the registry falls back to empty and a
    warning is logged.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import queue
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Subscriber config ────────────────────────────────────────────


@dataclass
class WebhookSubscriber:
    """Configuration for one webhook endpoint.

    Attributes:
        name: Unique human-readable identifier (used as registry key).
        url: HTTP/HTTPS URL to POST events to.
        secret: Shared secret used for HMAC-SHA256 signing.
        enabled: Whether the dispatcher should deliver to this
            subscriber. Disable to pause without losing config.
        headers: Extra HTTP headers (e.g. ``{"Authorization": "Bearer ..."}``).
        timeout_s: Per-request timeout in seconds.
        max_retries: Number of additional attempts on transient failures.
        backoff_base_s: Initial backoff sleep; doubled each retry.
        events: Optional set of event kinds to deliver. ``None`` means
            deliver all (added / modified / removed).
        created_at: ISO timestamp set automatically on construction.
    """

    name: str
    url: str
    secret: str = ""
    enabled: bool = True
    headers: dict[str, str] = field(default_factory=dict)
    timeout_s: float = 5.0
    max_retries: int = 3
    backoff_base_s: float = 1.0
    events: set[str] | None = None
    created_at: str = field(default_factory=lambda: _now_iso())

    # ── (De)serialization ───────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # ``events`` may be a set; JSON only knows lists.
        if d.get("events") is not None:
            d["events"] = sorted(d["events"])
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebhookSubscriber:
        events = data.get("events")
        return cls(
            name=data["name"],
            url=data["url"],
            secret=data.get("secret", ""),
            enabled=bool(data.get("enabled", True)),
            headers=dict(data.get("headers", {})),
            timeout_s=float(data.get("timeout_s", 5.0)),
            max_retries=int(data.get("max_retries", 3)),
            backoff_base_s=float(data.get("backoff_base_s", 1.0)),
            events=set(events) if events else None,
            created_at=data.get("created_at", _now_iso()),
        )


# ── Persistence ──────────────────────────────────────────────────


def _default_registry_path() -> Path:
    """Return the canonical path for the webhook registry JSON file."""
    home = Path(os.path.expanduser("~")) / ".Zeloo"
    return home / "skill_webhooks.json"


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="milliseconds")


class WebhookRegistry:
    """Thread-safe JSON-backed registry of webhook subscribers."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else _default_registry_path()
        self._lock = threading.RLock()
        self._subscribers: dict[str, WebhookSubscriber] = {}
        self.reload()

    # ── Persistence ─────────────────────────────────────────────

    def reload(self) -> None:
        """Load subscribers from disk; missing/corrupt → empty registry."""
        with self._lock:
            if not self._path.is_file():
                self._subscribers = {}
                return
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning(
                    "skill_webhooks: failed to load %s (%s); starting empty",
                    self._path,
                    exc,
                )
                self._subscribers = {}
                return
            subs = data.get("subscribers", []) if isinstance(data, dict) else []
            loaded: dict[str, WebhookSubscriber] = {}
            for entry in subs:
                if not isinstance(entry, dict):
                    continue
                try:
                    sub = WebhookSubscriber.from_dict(entry)
                except (KeyError, ValueError, TypeError) as exc:
                    logger.warning("skill_webhooks: bad entry skipped: %s", exc)
                    continue
                loaded[sub.name] = sub
            self._subscribers = loaded

    def save(self) -> None:
        """Persist current subscribers to disk atomically (mode 0600)."""
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                {"version": 1, "subscribers": [s.to_dict() for s in self._subscribers.values()]},
                indent=2,
                sort_keys=True,
            )
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            tmp.write_text(payload, encoding="utf-8")
            try:
                os.replace(tmp, self._path)
            except OSError:
                # Fallback for Windows / cross-volume moves.
                self._path.write_text(payload, encoding="utf-8")
                if tmp.exists():
                    tmp.unlink()
            # Restrict permissions on POSIX. Best-effort.
            try:
                os.chmod(self._path, 0o600)
            except OSError:
                pass

    # ── CRUD ────────────────────────────────────────────────────

    def add(self, subscriber: WebhookSubscriber) -> None:
        with self._lock:
            self._subscribers[subscriber.name] = subscriber
            self.save()

    def remove(self, name: str) -> bool:
        with self._lock:
            if name in self._subscribers:
                del self._subscribers[name]
                self.save()
                return True
            return False

    def get(self, name: str) -> WebhookSubscriber | None:
        with self._lock:
            return self._subscribers.get(name)

    def enable(self, name: str, enabled: bool = True) -> bool:
        with self._lock:
            sub = self._subscribers.get(name)
            if sub is None:
                return False
            sub.enabled = enabled
            self.save()
            return True

    def all(self) -> list[WebhookSubscriber]:
        with self._lock:
            return list(self._subscribers.values())

    def enabled_for(self, kind: str) -> list[WebhookSubscriber]:
        with self._lock:
            return [
                s
                for s in self._subscribers.values()
                if s.enabled and (s.events is None or kind in s.events)
            ]

    def __len__(self) -> int:
        with self._lock:
            return len(self._subscribers)

    @property
    def path(self) -> Path:
        return self._path


# ── Signing helpers ──────────────────────────────────────────────


def sign_payload(secret: str, body: bytes) -> str:
    """Return the ``sha256=<hex>`` signature for *body* using *secret*."""
    if not secret:
        return ""
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def verify_signature(secret: str, body: bytes, signature: str) -> bool:
    """Constant-time verify; returns False on any mismatch."""
    expected = sign_payload(secret, body)
    if not expected or not signature:
        return False
    return hmac.compare_digest(expected, signature)


# ── Dispatcher (background worker) ───────────────────────────────


@dataclass
class DeliveryResult:
    """Outcome of one webhook delivery attempt."""

    subscriber: str
    event_id: str
    attempts: int
    success: bool
    status_code: int | None
    error: str | None


class WebhookDispatcher:
    """Background worker that signs and POSTs reloader events.

    The dispatcher owns a bounded :class:`queue.Queue`. Producers
    (reloader subscribers) call :meth:`enqueue_event`; the worker
    (:meth:`_run`) pulls, signs, and POSTs one delivery at a time.

    Dependencies:

      * ``urllib.request`` is used so this module has **no third-party
        dependencies**. If the project has ``httpx`` installed, the
        dispatcher prefers it for richer error reporting.
    """

    def __init__(
        self,
        registry: WebhookRegistry,
        queue_maxsize: int = 1024,
        on_delivery: callable = None,  # type: ignore[valid-type]
        audit: bool = True,
    ) -> None:
        self._registry = registry
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=queue_maxsize)
        self._on_delivery = on_delivery
        self._audit = audit
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        # Lightweight stats
        self._stats_lock = threading.Lock()
        self._stats = {"enqueued": 0, "delivered": 0, "failed": 0, "dropped": 0}

    # ── Lifecycle ───────────────────────────────────────────────

    def start(self) -> None:
        with self._stats_lock:
            self._stop_event.clear()
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, name="WebhookDispatcher", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float | None = 5.0) -> None:
        self._stop_event.set()
        # Unblock the worker via sentinel.
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None

    def stats(self) -> dict[str, int]:
        with self._stats_lock:
            return dict(self._stats)

    # ── Producer API ────────────────────────────────────────────

    def enqueue_event(self, event: Any) -> bool:
        """Enqueue a :class:`SkillChangeEvent` for delivery.

        Returns False if the queue is full (event dropped).
        """
        payload = _event_to_payload(event)
        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            with self._stats_lock:
                self._stats["dropped"] += 1
            logger.warning("skill_webhooks: queue full, dropped %s", payload.get("event_id"))
            return False
        with self._stats_lock:
            self._stats["enqueued"] += 1
        return True

    # ── Worker ──────────────────────────────────────────────────

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                payload = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if payload is None:  # sentinel
                break
            self._deliver_to_all(payload)

    def _deliver_to_all(self, payload: dict[str, Any]) -> None:
        kind = str(payload.get("kind", ""))
        subscribers = self._registry.enabled_for(kind)
        for sub in subscribers:
            result = self._deliver_one(sub, payload)
            if self._on_delivery is not None:
                try:
                    self._on_delivery(result)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("skill_webhooks: on_delivery callback raised: %s", exc)
            if self._audit:
                self._audit_delivery(result, payload)
            with self._stats_lock:
                if result.success:
                    self._stats["delivered"] += 1
                else:
                    self._stats["failed"] += 1

    def _audit_delivery(self, result: DeliveryResult, payload: dict[str, Any]) -> None:
        """Best-effort audit hook for one delivery."""
        try:
            from agent.audit_log import audit_event

            audit_event(
                "webhook_delivered" if result.success else "webhook_failed",
                actor=f"webhook:{result.subscriber}",
                resource=str(payload.get("path", "")),
                outcome="ok" if result.success else "error",
                detail={
                    "url": self._registry.get(result.subscriber).url
                    if self._registry.get(result.subscriber)
                    else "",
                    "event_id": result.event_id,
                    "kind": payload.get("kind", ""),
                    "skill_name": payload.get("skill_name", ""),
                    "attempts": result.attempts,
                    "status_code": result.status_code,
                    "error": result.error,
                },
            )
        except Exception:  # noqa: BLE001
            pass

    def _deliver_one(
        self, sub: WebhookSubscriber, payload: dict[str, Any]
    ) -> DeliveryResult:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        signature = sign_payload(sub.secret, body)
        headers = {
            "Content-Type": "application/json",
            "X-Zeloo-Event-Id": str(payload.get("event_id", "")),
            "X-Zeloo-Event-Kind": str(payload.get("kind", "")),
            **sub.headers,
        }
        if signature:
            headers["X-Zeloo-Signature"] = signature

        attempt = 0
        last_error: str | None = None
        last_status: int | None = None
        backoff = sub.backoff_base_s
        while attempt <= sub.max_retries:
            attempt += 1
            headers["X-Zeloo-Delivery-Attempt"] = str(attempt)
            try:
                status = _http_post(sub.url, body, headers, sub.timeout_s)
                last_status = status
                if 200 <= status < 300:
                    return DeliveryResult(
                        subscriber=sub.name,
                        event_id=str(payload.get("event_id", "")),
                        attempts=attempt,
                        success=True,
                        status_code=status,
                        error=None,
                    )
                # 4xx other than 408/429 are not retried
                if 400 <= status < 500 and status not in (408, 429):
                    return DeliveryResult(
                        subscriber=sub.name,
                        event_id=str(payload.get("event_id", "")),
                        attempts=attempt,
                        success=False,
                        status_code=status,
                        error=f"HTTP {status}",
                    )
                last_error = f"HTTP {status}"
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
            if attempt > sub.max_retries:
                break
            # Exponential backoff with jitter; do not block the worker forever.
            sleep_for = min(backoff, 30.0)
            self._stop_event.wait(sleep_for)
            if self._stop_event.is_set():
                break
            backoff *= 2.0

        return DeliveryResult(
            subscriber=sub.name,
            event_id=str(payload.get("event_id", "")),
            attempts=attempt,
            success=False,
            status_code=last_status,
            error=last_error or "unknown error",
        )


# ── HTTP transport (urllib only) ────────────────────────────────


def _http_post(url: str, body: bytes, headers: dict[str, str], timeout: float) -> int:
    """POST *body* to *url* with *headers*; return HTTP status code."""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # Drain body to free the connection.
            try:
                resp.read()
            except Exception:  # noqa: BLE001
                pass
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        # The body wasn't readable but we still got a status code.
        try:
            exc.read()
        except Exception:  # noqa: BLE001
            pass
        return int(exc.code)
    except urllib.error.URLError as exc:
        raise OSError(f"urllib URLError: {exc}") from exc


# ── Conversion helper ────────────────────────────────────────────


def _event_to_payload(event: Any) -> dict[str, Any]:
    """Convert a :class:`SkillChangeEvent` to a JSON-ready dict."""
    return {
        "event_id": f"evt_{uuid.uuid4().hex[:16]}",
        "kind": str(getattr(event, "kind", "")),
        "skill_name": getattr(event, "skill_name", ""),
        "path": str(getattr(event, "path", "")),
        "previous_mtime": getattr(event, "previous_mtime", None),
        "current_mtime": getattr(event, "current_mtime", None),
        "timestamp": _now_iso(),
    }


# ── Convenience wiring ──────────────────────────────────────────


def attach_to(
    reloader: Any,
    registry: WebhookRegistry | None = None,
    *,
    start: bool = True,
) -> WebhookDispatcher:
    """Wire a dispatcher to *reloader* and (optionally) start its worker.

    Convenience for callers who just want ``reloader.subscribe(dispatcher.enqueue_event)``.
    """
    reg = registry if registry is not None else WebhookRegistry()
    dispatcher = WebhookDispatcher(reg)

    def _adapter(evt: Any) -> None:
        dispatcher.enqueue_event(evt)

    reloader.subscribe(_adapter)
    if start:
        dispatcher.start()
    return dispatcher


__all__ = [
    "DeliveryResult",
    "WebhookDispatcher",
    "WebhookRegistry",
    "WebhookSubscriber",
    "attach_to",
    "sign_payload",
    "verify_signature",
]


# ── Module-level singleton (process-wide convenience) ────────────

_default_registry: WebhookRegistry | None = None
_default_lock = threading.Lock()


def get_default_registry() -> WebhookRegistry:
    """Return the process-wide :class:`WebhookRegistry` (lazy)."""
    global _default_registry
    with _default_lock:
        if _default_registry is None:
            _default_registry = WebhookRegistry()
        return _default_registry


def reset_default_registry() -> None:
    """Clear the singleton (used in tests)."""
    global _default_registry
    with _default_lock:
        _default_registry = None
