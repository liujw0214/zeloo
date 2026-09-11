"""Tests for optional_mcps.stripe MCP server."""

from optional_mcps.stripe import (
    TOOLS,
    _format_balance,
    _format_customer,
    _format_payment_intent,
    _format_subscription,
)


class TestStripeFormatting:
    def test_format_balance_positive_amounts(self):
        balance = {
            "available": [{"amount": 10000, "currency": "usd"}],
            "pending": [{"amount": 5000, "currency": "usd"}],
        }
        result = _format_balance(balance)
        assert "100.00 USD" in result
        assert "50.00 USD" in result
        assert "Available:" in result
        assert "Pending:" in result

    def test_format_balance_zero_amounts(self):
        balance = {
            "available": [],
            "pending": [],
        }
        result = _format_balance(balance)
        assert "0.00 ?" in result

    def test_format_customer_with_name_email(self):
        customer = {
            "id": "cus_123",
            "name": "John Doe",
            "email": "john@example.com",
            "created": 1609459200,
        }
        result = _format_customer(customer)
        assert "John Doe" in result
        assert "john@example.com" in result
        assert "cus_123" in result

    def test_format_customer_minimal_data(self):
        customer = {
            "id": "cus_456",
        }
        result = _format_customer(customer)
        assert "cus_456" in result

    def test_format_payment_intent(self):
        payment_intent = {
            "id": "pi_abc123",
            "amount": 2500,
            "currency": "usd",
            "status": "succeeded",
            "created": 1609459200,
        }
        result = _format_payment_intent(payment_intent)
        assert "pi_abc123" in result
        assert "25.00" in result
        assert "USD" in result
        assert "succeeded" in result

    def test_format_subscription(self):
        subscription = {
            "id": "sub_xyz789",
            "status": "active",
            "customer": "cus_123",
            "current_period_end": 1640995200,
        }
        result = _format_subscription(subscription)
        assert "sub_xyz789" in result
        assert "active" in result
        assert "cus_123" in result
        assert "1640995200" in result


class TestStripeToolsList:
    def test_tools_defined(self):
        assert len(TOOLS) == 7
        names = [t.name for t in TOOLS]
        assert "stripe_get_balance" in names
        assert "stripe_list_customers" in names
        assert "stripe_create_customer" in names
        assert "stripe_get_customer" in names
        assert "stripe_list_payment_intents" in names
        assert "stripe_create_payment_intent" in names
        assert "stripe_list_subscriptions" in names

    def test_all_have_handlers(self):
        for tool in TOOLS:
            assert callable(tool.handler), f"{tool.name} has no handler"
