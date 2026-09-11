"""Productboard MCP — product management and prioritization."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from optional_mcps.base import MCPServer, make_tool

PB_TOKEN = os.environ.get("PRODUCTBOARD_API_TOKEN", "")
PB_BASE_URL = "https://api.productboard.com"


def _pb_headers() -> dict[str, str]:
    if not PB_TOKEN:
        raise ValueError("PRODUCTBOARD_API_TOKEN must be set")
    return {
        "Authorization": f"Bearer {PB_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


@make_tool
def productboard_list_products() -> str:
    """List Productboard products."""
    url = f"{PB_BASE_URL}/products"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_pb_headers())
        resp.raise_for_status()
    data = resp.json().get("data", [])
    products = [
        {"id": p["id"], "name": p.get("name"),
         "description": p.get("description", "")}
        for p in data
    ]
    return json.dumps({"products": products}, indent=2, ensure_ascii=False)


@make_tool
def productboard_list_features(limit: int = 50) -> str:
    """List Productboard features."""
    url = f"{PB_BASE_URL}/features"
    params = {"pageLimit": min(limit, 100)}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_pb_headers(), params=params)
        resp.raise_for_status()
    data = resp.json().get("data", [])
    features = [
        {"id": f["id"], "name": f.get("name"),
         "status": f.get("status", {}).get("name"),
         "owner": f.get("owner", {}).get("email")}
        for f in data
    ]
    return json.dumps({"features": features}, indent=2, ensure_ascii=False)


@make_tool
def productboard_create_feature(
    name: str,
    description: str = "",
    product_id: str = "",
) -> str:
    """Create a Productboard feature."""
    url = f"{PB_BASE_URL}/features"
    payload: dict[str, Any] = {
        "name": name,
        "description": description,
    }
    if product_id:
        payload["product_id"] = product_id
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_pb_headers(), json=payload)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def productboard_list_objectives() -> str:
    """List Productboard objectives."""
    url = f"{PB_BASE_URL}/objectives"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_pb_headers())
        resp.raise_for_status()
    data = resp.json().get("data", [])
    objectives = [
        {"id": o["id"], "name": o.get("name"),
         "status": o.get("status", {}).get("name")}
        for o in data
    ]
    return json.dumps({"objectives": objectives}, indent=2, ensure_ascii=False)


@make_tool
def productboard_list_initiatives() -> str:
    """List Productboard initiatives."""
    url = f"{PB_BASE_URL}/initiatives"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_pb_headers())
        resp.raise_for_status()
    data = resp.json().get("data", [])
    initiatives = [
        {"id": i["id"], "name": i.get("name"),
         "status": i.get("status", {}).get("name")}
        for i in data
    ]
    return json.dumps({"initiatives": initiatives}, indent=2, ensure_ascii=False)


TOOLS = [
    productboard_list_products,
    productboard_list_features,
    productboard_create_feature,
    productboard_list_objectives,
    productboard_list_initiatives,
]


class ProductboardMCPServer(MCPServer):
    name = "productboard"
    description = "Productboard product management and prioritization"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["ProductboardMCPServer", "TOOLS"]