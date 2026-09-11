"""Aha! MCP — product strategy and roadmap platform."""

from __future__ import annotations

import json
import os

import httpx

from optional_mcps.base import MCPServer, make_tool

AHA_TOKEN = os.environ.get("AHA_API_TOKEN", "")
AHA_DOMAIN = os.environ.get("AHA_DOMAIN", "")
AHA_BASE_URL = f"https://{AHA_DOMAIN}.aha.io/api/v1"


def _aha_headers() -> dict[str, str]:
    if not AHA_TOKEN or not AHA_DOMAIN:
        raise ValueError("AHA_API_TOKEN and AHA_DOMAIN must be set")
    return {
        "Authorization": f"Bearer {AHA_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


@make_tool
def aha_list_products() -> str:
    """List Aha! products."""
    url = f"{AHA_BASE_URL}/products"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_aha_headers())
        resp.raise_for_status()
    products = [
        {"id": p["id"], "name": p.get("name"),
         "reference_prefix": p.get("reference_prefix")}
        for p in resp.json().get("products", [])
    ]
    return json.dumps({"products": products}, indent=2, ensure_ascii=False)


@make_tool
def aha_list_features(
    product_id: str, limit: int = 50
) -> str:
    """List features in Aha! product."""
    url = f"{AHA_BASE_URL}/products/{product_id}/features"
    params = {"per_page": min(limit, 200)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_aha_headers(), params=params)
        resp.raise_for_status()
    features = [
        {"id": f["id"], "name": f.get("name"),
         "workflow_status": f.get("workflow_status", {}).get("name"),
         "score": f.get("score")}
        for f in resp.json().get("features", [])
    ]
    return json.dumps({"features": features}, indent=2, ensure_ascii=False)


@make_tool
def aha_create_feature(
    product_id: str,
    name: str,
    description: str = "",
) -> str:
    """Create a new Aha! feature."""
    url = f"{AHA_BASE_URL}/products/{product_id}/features"
    payload = {
        "feature": {
            "name": name,
            "description": description,
        }
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_aha_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def aha_list_releases(
    product_id: str, limit: int = 50
) -> str:
    """List releases for product."""
    url = f"{AHA_BASE_URL}/products/{product_id}/releases"
    params = {"per_page": min(limit, 200)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_aha_headers(), params=params)
        resp.raise_for_status()
    releases = [
        {"id": r["id"], "name": r.get("name"),
         "release_date": r.get("release_date"),
         "progress": r.get("progress")}
        for r in resp.json().get("releases", [])
    ]
    return json.dumps({"releases": releases}, indent=2, ensure_ascii=False)


@make_tool
def aha_list_ideas(
    product_id: str, limit: int = 50
) -> str:
    """List ideas for Aha! product."""
    url = f"{AHA_BASE_URL}/products/{product_id}/ideas"
    params = {"per_page": min(limit, 200)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_aha_headers(), params=params)
        resp.raise_for_status()
    ideas = [
        {"id": i["id"], "name": i.get("name"),
         "score": i.get("score"),
         "status": i.get("workflow_status", {}).get("name")}
        for i in resp.json().get("ideas", [])
    ]
    return json.dumps({"ideas": ideas}, indent=2, ensure_ascii=False)


TOOLS = [
    aha_list_products,
    aha_list_features,
    aha_create_feature,
    aha_list_releases,
    aha_list_ideas,
]


class AhaMCPServer(MCPServer):
    name = "aha"
    description = "Aha! product strategy and roadmap platform"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["AhaMCPServer", "TOOLS"]