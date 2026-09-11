"""DigitalOcean MCP — cloud infrastructure management."""

from __future__ import annotations

import json
import os

import httpx

from optional_mcps.base import MCPServer, make_tool

DO_TOKEN = os.environ.get("DIGITALOCEAN_TOKEN", "")
DO_BASE_URL = "https://api.digitalocean.com/v2"


def _do_headers() -> dict[str, str]:
    if not DO_TOKEN:
        raise ValueError("DIGITALOCEAN_TOKEN environment variable not set")
    return {
        "Authorization": f"Bearer {DO_TOKEN}",
        "Content-Type": "application/json",
    }


@make_tool
def digitalocean_list_droplets(
    page: int = 1,
    per_page: int = 25,
) -> str:
    """List all Droplets (VMs) in your account.

    Args:
        page: Page number for pagination.
        per_page: Number of results per page (max 200).
    """
    url = f"{DO_BASE_URL}/droplets"
    params = {"page": page, "per_page": min(per_page, 200)}
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, headers=_do_headers(), params=params)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def digitalocean_get_droplet(droplet_id: int) -> str:
    """Get details of a specific Droplet by ID.

    Args:
        droplet_id: The numeric ID of the Droplet.
    """
    url = f"{DO_BASE_URL}/droplets/{droplet_id}"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_do_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def digitalocean_list_domains() -> str:
    """List all DNS domains registered in your account."""
    url = f"{DO_BASE_URL}/domains"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_do_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def digitalocean_list_floating_ips() -> str:
    """List all Floating IPs in your account."""
    url = f"{DO_BASE_URL}/floating_ips"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_do_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def digitalocean_list_volumes(
    region: str | None = None,
) -> str:
    """List block storage volumes.

    Args:
        region: Optional region to filter by.
    """
    url = f"{DO_BASE_URL}/volumes"
    params = {}
    if region:
        params["region"] = region
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_do_headers(), params=params)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def digitalocean_get_account() -> str:
    """Get your DigitalOcean account information."""
    url = f"{DO_BASE_URL}/account"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_do_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


TOOLS = [
    digitalocean_list_droplets,
    digitalocean_get_droplet,
    digitalocean_list_domains,
    digitalocean_list_floating_ips,
    digitalocean_list_volumes,
    digitalocean_get_account,
]


class DigitalOceanMCPServer(MCPServer):
    name = "digitalocean"
    description = "DigitalOcean cloud infrastructure management"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["DigitalOceanMCPServer", "TOOLS"]
