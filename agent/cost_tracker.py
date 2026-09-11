"""Cost tracking — estimate $ cost from LLM token usage.

Pricing is per-1M-tokens for input (prompt) and output (completion) tokens.
Values are approximate and should be updated when provider prices change.
Models not in the table fall back to a generic default price.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class CostLimitExceeded(Exception):
    """Raised when the cost exceeds the abort threshold."""


# Price per 1M tokens: (input_price, output_price) in USD.
# Sourced from public price lists (approximate).
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-4": (30.00, 60.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "o1": (15.00, 60.00),
    "o1-mini": (3.00, 12.00),
    "o3-mini": (1.10, 4.40),
    "dall-e-3": (0.0, 0.0),  # image, per-image pricing not token-based
    # Anthropic (via OpenRouter/compatible endpoint)
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
    "claude-3-opus-20240229": (15.00, 75.00),
    "claude-3-haiku-20240307": (0.25, 1.25),
    # DeepSeek
    "deepseek-chat": (0.14, 0.28),
    "deepseek-coder": (0.14, 0.28),
    # Google
    "gemini-1.5-pro": (1.25, 5.00),
    "gemini-1.5-flash": (0.075, 0.30),
    # Groq
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "mixtral-8x7b-32768": (0.24, 0.24),
}

# Fallback pricing for unknown models.
_DEFAULT_PRICE: tuple[float, float] = (5.00, 15.00)


def estimate_cost(input_tokens: int, output_tokens: int, model: str = "gpt-4o") -> float:
    price_in, price_out = get_model_price(model)
    return (input_tokens / 1_000_000) * price_in + (output_tokens / 1_000_000) * price_out


def get_model_price(model: str) -> tuple[float, float]:
    """Return (input_price, output_price) per 1M tokens for *model*.

    Falls back to a default price if the model is not in the table.
    Matches are case-insensitive and prefix-based.
    """
    model_lower = model.lower()
    for key, price in _MODEL_PRICING.items():
        if model_lower == key or model_lower.startswith(key):
            return price
    return _DEFAULT_PRICE


@dataclass
class CostTracker:
    """Accumulate token usage and estimate $ cost across a session.

    Includes cost threshold controls:
    - ``warn_threshold_usd``: emit a warning log when total cost exceeds this.
    - ``abort_threshold_usd``: raise ``CostLimitExceeded`` when exceeded.
    - ``warn_callbacks``: called with ``("warn", total_cost)`` on threshold breach.
    - ``abort_callbacks``: called with ``("abort", total_cost)`` before raising.
    """

    model: str = "gpt-4o"
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cached_tokens: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)
    # Cost thresholds (in USD).
    warn_threshold_usd: float = 10.0
    abort_threshold_usd: float = 100.0
    # Subscribers receive a JSON-safe snapshot after every record_usage().
    _subscribers: list[Any] = field(default_factory=list, repr=False)
    _subs_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    # Threshold callbacks: list of (level, cost) -> None callables.
    _warn_callbacks: list[Any] = field(default_factory=list, repr=False)
    _abort_callbacks: list[Any] = field(default_factory=list, repr=False)
    _warn_fired: bool = field(default=False, repr=False)
    _warn_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        """Read threshold overrides from environment variables.

        Env vars:
            zeloo_COST_WARN_THRESHOLD  (USD, float, default 10.0)
            zeloo_COST_ABORT_THRESHOLD (USD, float, default 100.0)
        """
        import os

        warn_env = os.environ.get("zeloo_COST_WARN_THRESHOLD")
        if warn_env:
            try:
                self.warn_threshold_usd = float(warn_env)
            except ValueError:
                logger.warning(
                    "Invalid zeloo_COST_WARN_THRESHOLD=%r, keeping default %.2f",
                    warn_env,
                    self.warn_threshold_usd,
                )
        abort_env = os.environ.get("zeloo_COST_ABORT_THRESHOLD")
        if abort_env:
            try:
                self.abort_threshold_usd = float(abort_env)
            except ValueError:
                logger.warning(
                    "Invalid zeloo_COST_ABORT_THRESHOLD=%r, keeping default %.2f",
                    abort_env,
                    self.abort_threshold_usd,
                )
        if self.abort_threshold_usd < self.warn_threshold_usd:
            logger.warning(
                "CostTracker abort threshold (%.2f) < warn threshold (%.2f); abort will never fire",
                self.abort_threshold_usd,
                self.warn_threshold_usd,
            )

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    @property
    def input_cost(self) -> float:
        input_price = get_model_price(self.model)[0]
        uncached = max(0, self.total_input_tokens - self.total_cached_tokens)
        # Cached tokens are typically ~10% of the input price.
        cached_price = input_price * 0.1
        return (uncached * input_price + self.total_cached_tokens * cached_price) / 1_000_000

    @property
    def output_cost(self) -> float:
        output_price = get_model_price(self.model)[1]
        return (self.total_output_tokens * output_price) / 1_000_000

    @property
    def total_cost(self) -> float:
        return self.input_cost + self.output_cost

    def record_usage(self, usage: Any) -> None:
        """Record token usage from an LLM response's ``usage`` object.

        Accepts both attribute-style (OpenAI) and dict-style usage objects.
        """
        if usage is None:
            return

        def _get(attr: str) -> int:
            val = getattr(usage, attr, None)
            if val is None and isinstance(usage, dict):
                val = usage.get(attr)
            return int(val or 0)

        prompt_tokens = _get("prompt_tokens")
        completion_tokens = _get("completion_tokens")
        cached_tokens = 0

        details = getattr(usage, "prompt_tokens_details", None)
        if details is not None:
            cached_tokens = int(getattr(details, "cached_tokens", 0) or 0)
        elif isinstance(usage, dict) and "prompt_tokens_details" in usage:
            cached_tokens = int(usage["prompt_tokens_details"].get("cached_tokens", 0) or 0)

        # Anthropic-style cache read tokens
        if cached_tokens == 0:
            cached_tokens = _get("cache_read_input_tokens")

        self.total_input_tokens += prompt_tokens
        self.total_output_tokens += completion_tokens
        self.total_cached_tokens += min(cached_tokens, prompt_tokens)

        self.history.append(
            {
                "input": prompt_tokens,
                "output": completion_tokens,
                "cached": cached_tokens,
            }
        )
        self._check_thresholds()
        # Fan-out to subscribers (e.g. Langfuse observer).
        snapshot = self.snapshot()
        for cb in self._safe_subscribers():
            try:
                cb(snapshot)
            except Exception as exc:  # noqa: BLE001
                logger.warning("cost_tracker: subscriber raised: %s", exc)

    # ── Observers / subscribers ─────────────────────────────────

    def _safe_subscribers(self) -> list:
        with self._subs_lock:
            return list(self._subscribers)

    def subscribe(self, callback: Any) -> None:
        """Register *callback* to receive each usage snapshot.

        The callback signature is ``(snapshot: dict) -> None``.
        Exceptions raised by subscribers are logged but never propagate
        back into :meth:`record_usage`.
        """
        with self._subs_lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)

    def unsubscribe(self, callback: Any) -> bool:
        with self._subs_lock:
            try:
                self._subscribers.remove(callback)
                return True
            except ValueError:
                return False

    def subscriber_count(self) -> int:
        with self._subs_lock:
            return len(self._subscribers)

    def _check_thresholds(self) -> None:
        cost = self.total_cost
        if cost >= self.abort_threshold_usd:
            self._trigger_abort()
            raise CostLimitExceeded(
                f"Cost ${cost:.4f} exceeded abort threshold ${self.abort_threshold_usd:.4f}"
            )
        if cost >= self.warn_threshold_usd:
            with self._warn_lock:
                if not self._warn_fired:
                    self._warn_fired = True
                    self._trigger_warn()

    def _trigger_warn(self) -> None:
        logger.warning(
            "CostTracker: cost $%.4f exceeded warn threshold $%.4f",
            self.total_cost,
            self.warn_threshold_usd,
        )
        for cb in list(self._warn_callbacks):
            try:
                cb("warn", self.total_cost)
            except Exception as exc:  # noqa: BLE001
                logger.warning("CostTracker warn callback raised: %s", exc)

    def _trigger_abort(self) -> None:
        logger.error(
            "CostTracker: cost $%.4f exceeded abort threshold $%.4f",
            self.total_cost,
            self.abort_threshold_usd,
        )
        for cb in list(self._abort_callbacks):
            try:
                cb("abort", self.total_cost)
            except Exception as exc:  # noqa: BLE001
                logger.warning("CostTracker abort callback raised: %s", exc)

    def register_warn_callback(self, callback: Any) -> None:
        with self._warn_lock:
            if callback not in self._warn_callbacks:
                self._warn_callbacks.append(callback)

    def register_abort_callback(self, callback: Any) -> None:
        if callback not in self._abort_callbacks:
            self._abort_callbacks.append(callback)

    def reset_warn(self) -> None:
        with self._warn_lock:
            self._warn_fired = False

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-safe snapshot of current usage + cost."""
        return {
            "model": self.model,
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "cached_tokens": self.total_cached_tokens,
            "total_tokens": self.total_tokens,
            "input_cost": self.input_cost,
            "output_cost": self.output_cost,
            "total_cost": self.total_cost,
            "warn_threshold": self.warn_threshold_usd,
            "abort_threshold": self.abort_threshold_usd,
            "call_count": len(self.history),
        }

    def push_to_tracer(
        self,
        tracer: Any | None = None,
        *,
        trace_id: str | None = None,
        name: str = "llm_cost",
    ) -> str | None:
        """Forward a usage snapshot to a Langfuse tracer as a generation.

        Returns the Langfuse generation id (or ``None`` when no
        tracer is available). Falls back to the process-wide
        :func:`agent.langfuse_integration.get_tracer` when *tracer*
        is ``None``.
        """
        if tracer is None:
            try:
                from agent.langfuse_integration import get_tracer

                tracer = get_tracer()
            except Exception:  # noqa: BLE001
                tracer = None
        if tracer is None or not getattr(tracer, "enabled", False):
            return None

        snap = self.snapshot()
        try:
            return tracer.log_llm_call(
                trace_id=trace_id,
                model=self.model,
                input_tokens=self.total_input_tokens,
                output_tokens=self.total_output_tokens,
                cost=self.total_cost,
                prompt_tokens_cost=self.input_cost,
                completion_tokens_cost=self.output_cost,
                name=name,
                metadata={
                    "cached_tokens": self.total_cached_tokens,
                    "call_count": snap["call_count"],
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("cost_tracker: push_to_tracer failed: %s", exc)
            return None

    def format_cost(
        self,
        currency: str = "USD",
        locale: str | None = None,
    ) -> str:
        """Return a formatted cost string in the requested currency.

        Args:
            currency: One of USD, CNY, EUR, GBP, JPY. Defaults to USD.
            locale: Optional BCP-47 locale tag (e.g. "en-US", "zh-CN").
                    When provided the string is returned in that locale's
                    number format. If ``None`` the system's default locale
                    is used.

        Returns:
            A human-readable string such as ``"¥6.84"`` or ``"€1.99"``.
        """
        rates: dict[str, float] = {
            "USD": 1.0,
            "CNY": 7.2,
            "EUR": 0.92,
            "GBP": 0.79,
            "JPY": 155.0,
        }
        rate = rates.get(currency.upper(), 1.0)
        total = self.total_cost * rate
        symbol_map: dict[str, str] = {
            "USD": "$",
            "CNY": "¥",
            "EUR": "€",
            "GBP": "£",
            "JPY": "¥",
        }
        symbol = symbol_map.get(currency.upper(), "$")

        if locale:
            try:
                import locale as _locale

                saved = _locale.getlocale(_locale.LC_ALL)
                _locale.setlocale(_locale.LC_ALL, locale)
                try:
                    return f"{symbol}{_locale.format_string('%.4f', total, grouping=True)}"
                finally:
                    _locale.setlocale(_locale.LC_ALL, saved)
            except Exception:  # noqa: BLE001
                pass
        if currency.upper() == "JPY":
            return f"{symbol}{int(round(total)):,}"
        decimals = 4 if rate < 1 else 2
        return f"{symbol}{total:,.{decimals}f}"

    def summary(self) -> str:
        """Return a human-readable cost summary string (English)."""
        return (
            f"Tokens: {self.total_tokens:,} "
            f"(in={self.total_input_tokens:,}, out={self.total_output_tokens:,}, "
            f"cached={self.total_cached_tokens:,}) | "
            f"Cost: ${self.total_cost:.4f} "
            f"(in=${self.input_cost:.4f}, out=${self.output_cost:.4f})"
        )

    def summary_zh(self) -> str:
        """Return a human-readable cost summary string (Chinese)."""
        return (
            f"令牌: {self.total_tokens:,} "
            f"(输入={self.total_input_tokens:,}, 输出={self.total_output_tokens:,}, "
            f"缓存={self.total_cached_tokens:,}) | "
            f"费用: ¥{self.total_cost * 7.2:.2f} "
            f"(输入=¥{self.input_cost * 7.2:.4f}, 输出=¥{self.output_cost * 7.2:.4f})"
        )
