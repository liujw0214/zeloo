"""Stripe MCP server — exposes Stripe REST API as MCP tools over stdio JSON-RPC."""

from __future__ import annotations

import os

from optional_mcps.base import MCPServer, make_tool

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False


STRIPE_API_BASE = "https://api.stripe.com/v1"


def _stripe_get(endpoint: str, params: dict | None = None) -> dict:
    secret_key = os.environ.get("STRIPE_SECRET_KEY", "")
    url = f"{STRIPE_API_BASE}/{endpoint}"
    headers = {"Authorization": f"Bearer {secret_key}"}
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=headers, params=params or {})
        if resp.status_code != 200:
            resp.raise_for_status()
        return resp.json()


def _stripe_post(endpoint: str, data: dict) -> dict:
    secret_key = os.environ.get("STRIPE_SECRET_KEY", "")
    url = f"{STRIPE_API_BASE}/{endpoint}"
    headers = {
        "Authorization": f"Bearer {secret_key}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=headers, data=data)
        if resp.status_code != 200:
            resp.raise_for_status()
        return resp.json()


def _format_balance(balance: dict) -> str:
    available = balance.get("available", [])
    pending = balance.get("pending", [])
    if available:
        available_str = ", ".join(
            f"{a.get('amount', 0) / 100:.2f} {a.get('currency', '?').upper()}"
            for a in available
        )
    else:
        available_str = "0.00 ?"
    if pending:
        pending_str = ", ".join(
            f"{p.get('amount', 0) / 100:.2f} {p.get('currency', '?').upper()}"
            for p in pending
        )
    else:
        pending_str = "0.00 ?"
    return f"Balance:\n  Available: {available_str}\n  Pending: {pending_str}"


def _format_customer(c: dict) -> str:
    name = c.get("name") or ""
    email = c.get("email") or ""
    customer_id = c.get("id", "?")
    created = c.get("created", 0)
    return f"Customer: {name} <{email}> | ID: {customer_id} | Created: {created}"


def _format_payment_intent(pi: dict) -> str:
    pi_id = pi.get("id", "?")
    amount = pi.get("amount", 0) / 100
    currency = pi.get("currency", "?").upper()
    status = pi.get("status", "?")
    created = pi.get("created", 0)
    return (
        f"PaymentIntent: {pi_id} | {amount:.2f} {currency} | "
        f"Status: {status} | Created: {created}"
    )


def _format_subscription(sub: dict) -> str:
    sub_id = sub.get("id", "?")
    status = sub.get("status", "?")
    customer = sub.get("customer", "?")
    period_end = sub.get("current_period_end", 0)
    return (
        f"Subscription: {sub_id} | Status: {status} | "
        f"Customer: {customer} | Period End: {period_end}"
    )


if _HTTPX_AVAILABLE:

    @make_tool(
        name="stripe_get_balance",
        description="Get Stripe account balance (available and pending amounts)",
        input_schema={
            "type": "object",
            "properties": {},
        },
    )
    def stripe_get_balance() -> str:
        balance = _stripe_get("balance")
        return _format_balance(balance)

    @make_tool(
        name="stripe_list_customers",
        description="List Stripe customers",
        input_schema={
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of customers to return",
                    "default": 10,
                },
            },
        },
    )
    def stripe_list_customers(max_results: int = 10) -> str:
        data = _stripe_get("customers", {"limit": max_results})
        customers = data.get("data", [])
        if not customers:
            return "No customers found."
        return "\n".join(_format_customer(c) for c in customers)

    @make_tool(
        name="stripe_create_customer",
        description="Create a new Stripe customer",
        input_schema={
            "type": "object",
            "properties": {
                "email": {"type": "string", "description": "Customer email address"},
                "name": {"type": "string", "description": "Customer name"},
                "description": {
                    "type": "string",
                    "description": "Optional customer description",
                },
            },
            "required": ["email", "name"],
        },
    )
    def stripe_create_customer(email: str, name: str, description: str = "") -> str:
        form_data = {"email": email, "name": name}
        if description:
            form_data["description"] = description
        customer = _stripe_post("customers", form_data)
        return (
            f"Customer created: {customer.get('id', '?')} | "
            f"{customer.get('name', '')} <{customer.get('email', '')}>"
        )

    @make_tool(
        name="stripe_get_customer",
        description="Get details of a specific Stripe customer",
        input_schema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Stripe customer ID",
                },
            },
            "required": ["customer_id"],
        },
    )
    def stripe_get_customer(customer_id: str) -> str:
        customer = _stripe_get(f"customers/{customer_id}")
        return _format_customer(customer)

    @make_tool(
        name="stripe_list_payment_intents",
        description="List Stripe payment intents",
        input_schema={
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of payment intents to return",
                    "default": 10,
                },
            },
        },
    )
    def stripe_list_payment_intents(max_results: int = 10) -> str:
        data = _stripe_get("payment_intents", {"limit": max_results})
        intents = data.get("data", [])
        if not intents:
            return "No payment intents found."
        return "\n".join(_format_payment_intent(pi) for pi in intents)

    @make_tool(
        name="stripe_create_payment_intent",
        description="Create a new Stripe payment intent",
        input_schema={
            "type": "object",
            "properties": {
                "amount": {
                    "type": "integer",
                    "description": "Amount in cents (e.g., 1000 = $10.00)",
                },
                "currency": {
                    "type": "string",
                    "description": "Currency code (e.g., usd)",
                    "default": "usd",
                },
                "description": {
                    "type": "string",
                    "description": "Optional payment intent description",
                },
            },
            "required": ["amount"],
        },
    )
    def stripe_create_payment_intent(
        amount: int, currency: str = "usd", description: str = ""
    ) -> str:
        form_data: dict[str, object] = {"amount": amount, "currency": currency}
        if description:
            form_data["description"] = description
        pi = _stripe_post("payment_intents", form_data)
        return (
            f"PaymentIntent created: {pi.get('id', '?')} | "
            f"Client secret: {pi.get('client_secret', '?')} | "
            f"Amount: {pi.get('amount', 0) / 100:.2f} {pi.get('currency', '').upper()} | "
            f"Status: {pi.get('status', '?')}"
        )

    @make_tool(
        name="stripe_list_subscriptions",
        description="List Stripe subscriptions",
        input_schema={
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of subscriptions to return",
                    "default": 10,
                },
            },
        },
    )
    def stripe_list_subscriptions(max_results: int = 10) -> str:
        data = _stripe_get("subscriptions", {"limit": max_results})
        subscriptions = data.get("data", [])
        if not subscriptions:
            return "No subscriptions found."
        return "\n".join(_format_subscription(sub) for sub in subscriptions)

    TOOLS: list = [
        stripe_get_balance,
        stripe_list_customers,
        stripe_create_customer,
        stripe_get_customer,
        stripe_list_payment_intents,
        stripe_create_payment_intent,
        stripe_list_subscriptions,
    ]

else:
    TOOLS = []


def main() -> None:
    server = MCPServer(name="stripe", version="1.0.0", tools=TOOLS)
    server.run()


if __name__ == "__main__":
    main()
