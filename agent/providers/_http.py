"""Internal HTTP helper shared by all :mod:`agent.providers` implementations.

Every provider in this package needs the same building blocks:

* an async HTTP client wrapper around :mod:`httpx` with timeouts and
  consistent error handling,
* a synchronous helper for lightweight credential probes (model list,
  /me endpoints, etc.),
* JSON encode/decode helpers,
* an OpenAI-style error normaliser that converts a provider's raw
  error payload into the unified ``{ok: False, error: str, status: int}``
  shape returned by :meth:`BaseProvider.chat_completion`.

The helpers here are intentionally thin and dependency-free beyond
``httpx`` (which the rest of the runtime already depends on).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)


DEFAULT_TIMEOUT_S = 60.0
DEFAULT_PROBE_TIMEOUT_S = 10.0

# M1 — LLM timeout protection: bounded timeouts so a hung provider can't
# block the conversation loop for ten minutes. ``connect`` is bounded
# tightly because TCP/TLS handshake should never take more than a few
# seconds; ``read``/``write``/``pool`` are scaled from the env override so
# long-running generations can still stream safely.
DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=300.0, pool=300.0)


def get_timeout() -> httpx.Timeout:
    """Return configured timeout with safe defaults.

    Reads ``ZELOO_LLM_TIMEOUT_SECONDS`` (seconds) from the environment.
    ``connect`` is capped at 30s to fail fast on unreachable hosts;
    ``read``/``write``/``pool`` are scaled to ``seconds * 5`` so streamed
    completions can complete even on slow models.

    Falls back to :data:`DEFAULT_TIMEOUT` when the variable is missing or
    unparsable, so providers always get a bounded timeout.
    """
    env = os.environ.get("ZELOO_LLM_TIMEOUT_SECONDS")
    if env:
        try:
            seconds = float(env)
            return httpx.Timeout(
                connect=min(seconds, 30.0),
                read=seconds * 5,
                write=seconds * 5,
                pool=seconds * 5,
            )
        except ValueError:
            pass
    return DEFAULT_TIMEOUT


async def async_post_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_payload: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """POST *json_payload* to *url* and return the decoded JSON body.

    On any error the function returns ``{"ok": False, "error": str,
    "status": int, "raw": raw_body}`` instead of raising. Callers can
    therefore treat errors uniformly.
    """
    try:
        async with httpx.AsyncClient(timeout=get_timeout()) as client:
            resp = await client.post(
                url,
                headers=headers or {},
                json=json_payload or {},
            )
            body_text = resp.text
            try:
                body: dict[str, Any] = resp.json()
            except (json.JSONDecodeError, ValueError):
                body = {"_raw": body_text}
            if resp.status_code >= 400:
                err_msg = _extract_error_message(body) or body_text or resp.reason_phrase
                return {
                    "ok": False,
                    "error": err_msg,
                    "status": resp.status_code,
                    "raw": body,
                }
            return {"ok": True, "status": resp.status_code, "data": body}
    except httpx.TimeoutException as exc:
        return {"ok": False, "error": f"timeout: {exc}", "status": 0}
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"http error: {exc}", "status": 0}
    except Exception as exc:  # pragma: no cover - defensive
        return {"ok": False, "error": f"unexpected: {exc}", "status": 0}


async def async_get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """GET *url* and return decoded JSON. Returns ``ok=False`` on error."""
    try:
        async with httpx.AsyncClient(timeout=get_timeout()) as client:
            resp = await client.get(url, headers=headers or {})
            try:
                body: dict[str, Any] = resp.json()
            except (json.JSONDecodeError, ValueError):
                body = {"_raw": resp.text}
            if resp.status_code >= 400:
                return {
                    "ok": False,
                    "error": body.get("error", {}).get("message") if isinstance(body.get("error"), dict) else str(body.get("error", resp.text)),
                    "status": resp.status_code,
                    "raw": body,
                }
            return {"ok": True, "status": resp.status_code, "data": body}
    except httpx.TimeoutException as exc:
        return {"ok": False, "error": f"timeout: {exc}", "status": 0}
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"http error: {exc}", "status": 0}
    except Exception as exc:  # pragma: no cover - defensive
        return {"ok": False, "error": f"unexpected: {exc}", "status": 0}


def sync_get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_PROBE_TIMEOUT_S,
) -> dict[str, Any]:
    """Synchronous GET helper used by ``is_available`` / ``list_models``."""
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url, headers=headers or {})
            if resp.status_code >= 400:
                return {"ok": False, "status": resp.status_code, "raw": resp.text}
            try:
                return {"ok": True, "status": resp.status_code, "data": resp.json()}
            except (json.JSONDecodeError, ValueError):
                return {"ok": False, "status": resp.status_code, "raw": resp.text}
    except httpx.TimeoutException as exc:
        return {"ok": False, "status": 0, "error": f"timeout: {exc}"}
    except httpx.HTTPError as exc:
        return {"ok": False, "status": 0, "error": f"http error: {exc}"}
    except Exception as exc:  # pragma: no cover - defensive
        return {"ok": False, "status": 0, "error": f"unexpected: {exc}"}


def sync_post_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_payload: dict[str, Any] | None = None,
    timeout: float = DEFAULT_PROBE_TIMEOUT_S,
) -> dict[str, Any]:
    """Synchronous POST helper used by probe-style requests."""
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                url,
                headers=headers or {},
                json=json_payload or {},
            )
            if resp.status_code >= 400:
                return {"ok": False, "status": resp.status_code, "raw": resp.text}
            try:
                return {"ok": True, "status": resp.status_code, "data": resp.json()}
            except (json.JSONDecodeError, ValueError):
                return {"ok": False, "status": resp.status_code, "raw": resp.text}
    except httpx.TimeoutException as exc:
        return {"ok": False, "status": 0, "error": f"timeout: {exc}"}
    except httpx.HTTPError as exc:
        return {"ok": False, "status": 0, "error": f"http error: {exc}"}
    except Exception as exc:  # pragma: no cover - defensive
        return {"ok": False, "status": 0, "error": f"unexpected: {exc}"}


def _extract_error_message(body: dict[str, Any] | str | None) -> str:
    """Best-effort extraction of a human-readable error message."""
    if not body:
        return ""
    if isinstance(body, str):
        return body[:500]
    err = body.get("error")
    if isinstance(err, dict):
        msg = err.get("message") or err.get("type") or ""
        if isinstance(msg, str):
            return msg[:500]
    if isinstance(err, str):
        return err[:500]
    detail = body.get("detail") or body.get("message")
    if isinstance(detail, str):
        return detail[:500]
    if isinstance(detail, dict):
        return json.dumps(detail)[:500]
    return json.dumps(body)[:500]


def build_error_response(
    *,
    provider: str,
    error: str,
    status: int = 0,
    raw: Any = None,
) -> dict[str, Any]:
    """Standardised error payload used by every provider's chat_completion."""
    return {
        "ok": False,
        "provider": provider,
        "error": error,
        "status": status,
        "raw": raw,
        "content": "",
        "finish_reason": "error",
    }


def build_success_response(
    *,
    provider: str,
    content: str,
    model: str,
    finish_reason: str = "stop",
    usage: dict[str, int] | None = None,
    raw: Any = None,
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Standardised success payload returned by every provider's chat_completion."""
    usage = usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    return {
        "ok": True,
        "provider": provider,
        "content": content,
        "model": model,
        "finish_reason": finish_reason,
        "usage": usage,
        "raw": raw,
        "tool_calls": tool_calls or [],
    }


__all__ = [
    "DEFAULT_TIMEOUT",
    "DEFAULT_TIMEOUT_S",
    "DEFAULT_PROBE_TIMEOUT_S",
    "get_timeout",
    "async_post_json",
    "async_get_json",
    "sync_get_json",
    "sync_post_json",
    "build_error_response",
    "build_success_response",
]
