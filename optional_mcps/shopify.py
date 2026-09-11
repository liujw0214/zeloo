"""Shopify MCP — e-commerce store management."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from optional_mcps.base import MCPServer, make_tool

SHOPIFY_SHOP = os.environ.get("SHOPIFY_SHOP", "")
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_ACCESS_TOKEN", "")


def _shopify_headers() -> dict[str, str]:
    if not SHOPIFY_TOKEN:
        raise ValueError("SHOPIFY_ACCESS_TOKEN environment variable not set")
    return {
        "X-Shopify-Access-Token": SHOPIFY_TOKEN,
        "Content-Type": "application/json",
    }


@make_tool
def shopify_list_products(
    limit: int = 50,
    status: str = "active",
) -> str:
    """List products from Shopify store.

    Args:
        limit: Number of products to return (max 250).
        status: Product status filter (active, archived, draft).
    """
    if not SHOPIFY_SHOP:
        raise ValueError("SHOPIFY_SHOP environment variable not set")
    url = f"https://{SHOPIFY_SHOP}/admin/api/2024-01/products.json"
    params = {"limit": min(limit, 250), "status": status}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_shopify_headers(), params=params)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def shopify_get_order(order_id: int) -> str:
    """Get details of a specific order.

    Args:
        order_id: The numeric order ID.
    """
    if not SHOPIFY_SHOP:
        raise ValueError("SHOPIFY_SHOP environment variable not set")
    url = f"https://{SHOPIFY_SHOP}/admin/api/2024-01/orders/{order_id}.json"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_shopify_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def shopify_list_orders(
    limit: int = 50,
    status: str = "any",
    financial_status: str = "",
) -> str:
    """List orders from Shopify store.

    Args:
        limit: Number of orders to return.
        status: Order status (open, closed, cancelled, any).
        financial_status: Financial status filter.
    """
    if not SHOPIFY_SHOP:
        raise ValueError("SHOPIFY_SHOP environment variable not set")
    url = f"https://{SHOPIFY_SHOP}/admin/api/2024-01/orders.json"
    params: dict[str, Any] = {"limit": min(limit, 250), "status": status}
    if financial_status:
        params["financial_status"] = financial_status
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_shopify_headers(), params=params)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def shopify_create_order(order_data: str) -> str:
    """Create a new order in Shopify.

    Args:
        order_data: JSON string with order details.
    """
    if not SHOPIFY_SHOP:
        raise ValueError("SHOPIFY_SHOP environment variable not set")
    url = f"https://{SHOPIFY_SHOP}/admin/api/2024-01/orders.json"
    body = json.loads(order_data)
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_shopify_headers(), json=body)
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


@make_tool
def shopify_get_fulfillment_order(order_id: int) -> str:
    """Get fulfillment order details.

    Args:
        order_id: The numeric order ID.
    """
    if not SHOPIFY_SHOP:
        raise ValueError("SHOPIFY_SHOP environment variable not set")
    url = (
        f"https://{SHOPIFY_SHOP}/admin/api/2024-01/orders/"
        f"{order_id}/fulfillment_orders.json"
    )
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_shopify_headers())
        resp.raise_for_status()
    return json.dumps(resp.json(), indent=2, ensure_ascii=False)


TOOLS = [
    shopify_list_products,
    shopify_get_order,
    shopify_list_orders,
    shopify_create_order,
    shopify_get_fulfillment_order,
]


class ShopifyMCPServer(MCPServer):
    name = "shopify"
    description = "Shopify e-commerce store management"

    def __init__(self) -> None:
        super().__init__(tools=TOOLS)


__all__ = ["ShopifyMCPServer", "TOOLS"]
