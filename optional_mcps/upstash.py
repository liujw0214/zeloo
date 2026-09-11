"""Upstash Redis MCP — serverless Redis for data storage."""

from __future__ import annotations

import json
import os

import httpx

from optional_mcps.base import MCPServer, make_tool

UPSTASH_REST_URL = os.environ.get("UPSTASH_REDIS_REST_URL", "")
UPSTASH_REST_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")


def _upstash_headers() -> dict[str, str]:
    if not UPSTASH_REST_URL or not UPSTASH_REST_TOKEN:
        raise ValueError(
            "UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN "
            "environment variables must be set"
        )
    return {
        "Authorization": f"Bearer {UPSTASH_REST_TOKEN}",
        "Content-Type": "application/json",
    }


@make_tool
def upstash_get(key: str) -> str:
    """Get a value from Upstash Redis by key.

    Args:
        key: The Redis key to retrieve.
    """
    body = {"command": ["GET", key]}
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(UPSTASH_REST_URL, json=body, headers=_upstash_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def upstash_set(
    key: str,
    value: str,
    ex: int | None = None,
) -> str:
    """Set a key-value pair in Upstash Redis.

    Args:
        key: The Redis key.
        value: The value to store.
        ex: Optional expiration in seconds.
    """
    cmd = ["SET", key, value]
    if ex:
        cmd.extend(["EX", str(ex)])
    body = {"command": cmd}
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(UPSTASH_REST_URL, json=body, headers=_upstash_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def upstash_delete(*keys: str) -> str:
    """Delete one or more keys from Upstash Redis.

    Args:
        *keys: One or more Redis keys to delete.
    """
    cmd = ["DEL"] + list(keys)
    body = {"command": cmd}
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(UPSTASH_REST_URL, json=body, headers=_upstash_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def upstash_hgetall(key: str) -> str:
    """Get all fields and values of a hash in Upstash Redis.

    Args:
        key: The Redis hash key.
    """
    body = {"command": ["HGETALL", key]}
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(UPSTASH_REST_URL, json=body, headers=_upstash_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def upstash_llen(key: str) -> str:
    """Get the length of a list in Upstash Redis.

    Args:
        key: The Redis list key.
    """
    body = {"command": ["LLEN", key]}
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(UPSTASH_REST_URL, json=body, headers=_upstash_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def upstash_exec(command: str) -> str:
    """Execute an arbitrary Redis command via Upstash.

    Args:
        command: The command as a JSON array, e.g. '["INCR", "mycounter"]'.
    """
    cmd = json.loads(command)
    body = {"command": cmd}
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(UPSTASH_REST_URL, json=body, headers=_upstash_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


TOOLS = [
    upstash_get,
    upstash_set,
    upstash_delete,
    upstash_hgetall,
    upstash_llen,
    upstash_exec,
]


class UpstashMCPServer(MCPServer):
    name = "upstash"
    description = "Upstash serverless Redis data storage"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["UpstashMCPServer", "TOOLS"]
