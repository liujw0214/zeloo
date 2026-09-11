"""Tests for agent.rate_limiter."""

from __future__ import annotations

from agent.error_classifier import ErrorCategory, ErrorClassification
from agent.rate_limiter import (
    AdaptiveRateLimiter,
    AuthCircuitOpen,
    TokenBucket,
)


def _classification(category: ErrorCategory) -> ErrorClassification:
    """Build a minimal ErrorClassification for a category."""
    return ErrorClassification(
        category=category,
        message=f"test {category.value}",
        retryable=category in (ErrorCategory.RATE_LIMIT, ErrorCategory.TIMEOUT),
        retry_delay_seconds=0.0,
        should_fallback_provider=False,
        should_escalate=False,
    )


class TestTokenBucket:
    def test_initial_state(self) -> None:
        b = TokenBucket(base_rate=10.0, capacity=20.0)
        assert b.current_rate == 10.0
        assert b.tokens == 20.0
        assert b.auth_failures == 0

    def test_try_acquire_consumes_token(self) -> None:
        b = TokenBucket(base_rate=10.0, capacity=20.0)
        assert b.try_acquire() is True
        assert b.tokens < 20.0
        assert b.total_acquired == 1

    def test_try_acquire_throttled_when_empty(self) -> None:
        b = TokenBucket(base_rate=10.0, capacity=1.0)
        b.tokens = 0.0
        assert b.try_acquire() is False
        assert b.total_throttled == 1

    def test_retry_after_returns_zero_when_tokens_available(self) -> None:
        b = TokenBucket(base_rate=10.0, capacity=20.0)
        b.tokens = 5.0
        assert b.retry_after() == 0.0

    def test_retry_after_when_throttled(self) -> None:
        b = TokenBucket(base_rate=10.0, capacity=1.0)
        b.tokens = 0.0
        # cost=1.0, rate=10 -> retry_after = 0.1
        assert abs(b.retry_after() - 0.1) < 1e-9

    def test_record_success_ramps_up(self) -> None:
        b = TokenBucket(base_rate=10.0, capacity=20.0)
        b.current_rate = 5.0
        for _ in range(5):
            b.record_success()
        # 5% per success, clamped at base_rate
        assert b.current_rate > 5.0
        assert b.current_rate <= 10.0

    def test_record_success_capped_at_base(self) -> None:
        b = TokenBucket(base_rate=10.0, capacity=20.0)
        b.current_rate = 9.9
        for _ in range(20):
            b.record_success()
        assert b.current_rate <= 10.0


class TestRecordError:
    def test_rate_limit_halves_rate(self) -> None:
        b = TokenBucket(base_rate=10.0, capacity=20.0)
        b.record_error(_classification(ErrorCategory.RATE_LIMIT))
        # 10 * 0.5 = 5.0
        assert b.current_rate == 5.0

    def test_rate_limit_floor_is_zero_point_one(self) -> None:
        b = TokenBucket(base_rate=10.0, capacity=20.0)
        for _ in range(20):
            b.record_error(_classification(ErrorCategory.RATE_LIMIT))
        assert b.current_rate >= 0.1

    def test_server_error_reduces_rate(self) -> None:
        b = TokenBucket(base_rate=10.0, capacity=20.0)
        b.record_error(_classification(ErrorCategory.SERVER_ERROR))
        # 10 * 0.7 = 7.0
        assert b.current_rate == 7.0

    def test_timeout_reduces_rate(self) -> None:
        b = TokenBucket(base_rate=10.0, capacity=20.0)
        b.record_error(_classification(ErrorCategory.TIMEOUT))
        # 10 * 0.85 = 8.5
        assert b.current_rate == 8.5

    def test_unknown_error_mild_backoff(self) -> None:
        b = TokenBucket(base_rate=10.0, capacity=20.0)
        b.record_error(_classification(ErrorCategory.UNKNOWN))
        assert b.current_rate == 9.5


class TestAuthCircuit:
    def test_first_auth_failure_freezes_rate(self) -> None:
        """First AUTH failure must freeze rate at 0 (without raising)
        so subsequent calls fail fast."""
        b = TokenBucket(base_rate=10.0, capacity=20.0)
        # Should NOT raise — caller may still have a backup credential.
        b.record_error(_classification(ErrorCategory.AUTH))
        assert b.current_rate == 0.0
        assert b.auth_failures == 1
        # try_acquire immediately fails because rate is 0 (no tokens refill).
        assert b.try_acquire() is False

    def test_second_auth_failure_trips_circuit(self) -> None:
        b = TokenBucket(base_rate=10.0, capacity=20.0)
        b.record_error(_classification(ErrorCategory.AUTH))
        try:
            b.record_error(_classification(ErrorCategory.AUTH))
        except AuthCircuitOpen as exc:
            assert exc.provider == "default"
            assert exc.failures == 2
        else:
            raise AssertionError("expected AuthCircuitOpen")

    def test_reset_clears_auth_state(self) -> None:
        b = TokenBucket(base_rate=10.0, capacity=20.0)
        b.record_error(_classification(ErrorCategory.AUTH))
        b.reset()
        assert b.auth_failures == 0
        assert b.current_rate == 10.0


class TestAdaptiveRateLimiter:
    def test_get_bucket_creates_lazily(self) -> None:
        limiter = AdaptiveRateLimiter(base_rate=5.0, capacity=10.0)
        b1 = limiter.get_bucket("openai")
        b2 = limiter.get_bucket("openai")
        b3 = limiter.get_bucket("anthropic")
        assert b1 is b2
        assert b1 is not b3
        assert b1.base_rate == 5.0
        assert b1.capacity == 10.0

    def test_reset_all(self) -> None:
        limiter = AdaptiveRateLimiter(base_rate=10.0, capacity=20.0)
        b = limiter.get_bucket("openai")
        b.current_rate = 0.0
        b.tokens = 0.0
        limiter.reset_all()
        assert b.current_rate == 10.0
        assert b.tokens == 20.0

    def test_stats_returns_all_buckets(self) -> None:
        limiter = AdaptiveRateLimiter()
        limiter.get_bucket("a")
        limiter.get_bucket("b")
        stats = limiter.stats()
        assert set(stats.keys()) == {"a", "b"}

    def test_try_call_proxies_to_bucket(self) -> None:
        limiter = AdaptiveRateLimiter()
        assert limiter.try_call("openai") is True

    def test_wait_and_acquire_returns_false_on_timeout(self) -> None:
        limiter = AdaptiveRateLimiter(base_rate=10.0, capacity=1.0)
        b = limiter.get_bucket("openai")
        b.tokens = 0.0
        # Set max_wait to near-zero — should time out immediately.
        assert limiter.wait_and_acquire("openai", max_wait=0.001) is False