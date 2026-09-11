"""Token counter with multi-model support and cost estimation."""

from __future__ import annotations

from .cl100k import count_tokens as _count_tokens

try:
    import tiktoken
except ImportError:
    tiktoken = None


MODEL_ENCODINGS: dict[str, str] = {
    "gpt-4o": "cl100k_base",
    "gpt-4o-mini": "cl100k_base",
    "gpt-4-turbo": "cl100k_base",
    "gpt-4": "cl100k_base",
    "gpt-3.5-turbo": "cl100k_base",
    "claude-3-5-sonnet": "cl100k_base",
    "claude-3-opus": "cl100k_base",
    "claude-3-haiku": "cl100k_base",
    "deepseek-chat": "cl100k_base",
    "gemini-1.5-flash": "cl100k_base",
    "gemini-1.5-pro": "cl100k_base",
    "o1-preview": "cl100k_base",
    "o1-mini": "cl100k_base",
}

MODEL_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-4": (30.00, 60.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3-opus": (15.00, 75.00),
    "claude-3-haiku": (0.25, 1.25),
    "deepseek-chat": (0.14, 0.28),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.00),
    "o1-preview": (15.00, 60.00),
    "o1-mini": (3.00, 12.00),
}

DEFAULT_PRICE = (5.00, 15.00)


def count_tokens(text: str | list[dict], model: str = "gpt-4o") -> int:
    """Count tokens for a text or message list using cl100k_base encoding.

    Falls back to character-based estimation (chars / 4) if tiktoken unavailable.
    """
    return _count_tokens(text, model)


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    model: str = "gpt-4o",
) -> float:
    """Estimate cost in USD for given token counts."""
    price_in, price_out = MODEL_PRICES.get(model, DEFAULT_PRICE)
    return (input_tokens / 1_000_000) * price_in + (output_tokens / 1_000_000) * price_out


class TokenCounter:
    """Token counter with running totals and cost estimation."""

    def __init__(self, model: str = "gpt-4o") -> None:
        self.model = model
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cached_tokens = 0
        self.call_count = 0

    def count(self, text: str | list[dict]) -> int:
        tokens = count_tokens(text, self.model)
        self.total_input_tokens += tokens
        self.call_count += 1
        return tokens

    def record_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
    ) -> None:
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cached_tokens += cached_tokens
        self.call_count += 1

    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    def estimated_cost(self) -> float:
        return estimate_cost(self.total_input_tokens, self.total_output_tokens, self.model)

    def summary(self) -> dict:
        return {
            "model": self.model,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cached_tokens": self.total_cached_tokens,
            "total_tokens": self.total_tokens(),
            "estimated_cost_usd": round(self.estimated_cost(), 6),
            "call_count": self.call_count,
        }
