"""Cloudflare MCP — DNS, Workers, and R2 management."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from optional_mcps.base import MCPServer, make_tool

CF_API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "")
CF_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
CF_BASE_URL = "https://api.cloudflare.com/client/v4"


def _cf_headers() -> dict[str, str]:
    if not CF_API_TOKEN:
        raise ValueError("CLOUDFLARE_API_TOKEN environment variable not set")
    return {
        "Authorization": f"Bearer {CF_API_TOKEN}",
        "Content-Type": "application/json",
    }


@make_tool
def cloudflare_list_zones() -> str:
    """List all Cloudflare zones (domains) in your account."""
    url = f"{CF_BASE_URL}/zones"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_cf_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def cloudflare_get_zone_dns(
    zone_id: str,
    record_type: str | None = None,
    per_page: int = 20,
) -> str:
    """Get DNS records for a zone.

    Args:
        zone_id: The Cloudflare zone ID.
        record_type: Optional DNS record type (A/AAAA/CNAME/MX/TXT).
        per_page: Number of records per page.
    """
    url = f"{CF_BASE_URL}/zones/{zone_id}/dns_records"
    params: dict[str, Any] = {"per_page": per_page}
    if record_type:
        params["type"] = record_type
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_cf_headers(), params=params)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def cloudflare_create_dns_record(
    zone_id: str,
    record_type: str,
    name: str,
    content: str,
    ttl: int = 3600,
    proxied: bool = False,
) -> str:
    """Create a DNS record in a Cloudflare zone.

    Args:
        zone_id: The Cloudflare zone ID.
        record_type: DNS record type (A/AAAA/CNAME/MX/TXT).
        name: Record name (hostname).
        content: Record content (IP address, target, etc.).
        ttl: Time-to-live in seconds.
        proxied: Whether to enable Cloudflare proxy.
    """
    url = f"{CF_BASE_URL}/zones/{zone_id}/dns_records"
    body = {
        "type": record_type,
        "name": name,
        "content": content,
        "ttl": ttl,
        "proxied": proxied,
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_cf_headers(), json=body)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def cloudflare_list_workers_scripts() -> str:
    """List all Cloudflare Workers scripts in your account."""
    if not CF_ACCOUNT_ID:
        raise ValueError("CLOUDFLARE_ACCOUNT_ID environment variable not set")
    url = f"{CF_BASE_URL}/accounts/{CF_ACCOUNT_ID}/workers/scripts"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_cf_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def cloudflare_list_r2_buckets() -> str:
    """List all R2 object storage buckets in your account."""
    if not CF_ACCOUNT_ID:
        raise ValueError("CLOUDFLARE_ACCOUNT_ID environment variable not set")
    url = f"{CF_BASE_URL}/accounts/{CF_ACCOUNT_ID}/r2/buckets"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_cf_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


TOOLS = [
    cloudflare_list_zones,
    cloudflare_get_zone_dns,
    cloudflare_create_dns_record,
    cloudflare_list_workers_scripts,
    cloudflare_list_r2_buckets,
]


class CloudflareMCPServer(MCPServer):
    name = "cloudflare"
    description = "Cloudflare DNS, Workers, and R2 management"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["CloudflareMCPServer", "TOOLS"]
