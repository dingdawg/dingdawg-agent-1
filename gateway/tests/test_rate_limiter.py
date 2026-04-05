"""Tests for isg_agent.core.rate_limiter.

Comprehensive coverage of:
- TokenBucket: capacity, refill, consume, try_consume, available
- SlidingWindowCounter: limit, window, record, try_record, count
- RateLimiter: per-key management, check raises, try_acquire, reset, remove
- RateLimitExceeded exception fields
"""

from __future__ import annotations

import time

import pytest

from isg_agent.core.rate_limiter import (
    RateLimiter,
    RateLimitExceeded,
    SlidingWindowCounter,
    TokenBucket,
)


# ---------------------------------------------------------------------------
# RateLimitExceeded exception tests
# ---------------------------------------------------------------------------


class TestRateLimitExceeded:
    """Tests for the RateLimitExceeded exception."""

    def test_fields_stored(self) -> None:
        exc = RateLimitExceeded(
            key="api_calls", limit=10, window_seconds=60.0, retry_after=5.5
        )
        assert exc.key == "api_calls"
        assert exc.limit == 10
        assert exc.window_seconds == 60.0
        assert exc.retry_after == 5.5

    def test_message_format(self) -> None:
        exc = RateLimitExceeded(
            key="uploads", limit=5, window_seconds=30.0, retry_after=2.0
        )
        msg = str(exc)
        assert "uploads" in msg
        assert "5" in msg
        assert "retry" in msg.lower()


# ---------------------------------------------------------------------------
# TokenBucket tests
# ---------------------------------------------------------------------------


class TestTokenBucket:
    """Tests for the TokenBucket rate limiter."""

    def test_starts_at_full_capacity(self) -> None:
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        assert bucket.available == pytest.approx(10.0, abs=0.5)

    def test_consume_succeeds_when_available(self) -> None:
        bucket = TokenBucket(capacity=5, refill_rate=1.0)
        assert bucket.consume(3) is True

    def test_consume_fails_when_empty(self) -> None:
        bucket = TokenBucket(capacity=2, refill_rate=0.0)
        assert bucket.consume(2) is True  # drain it
        assert bucket.consume(1) is False  # empty, no refill

    def test_consume_does_not_mutate_on_failure(self) -> None:
        bucket = TokenBucket(capacity=2, refill_rate=0.0)
        bucket.consume(1)  # 1 left
        assert bucket.consume(5) is False  # too many
        # Still 1 token available (not consumed)
        assert bucket.available == pytest.approx(1.0, abs=0.1)

    def test_try_consume_returns_zero_on_success(self) -> None:
        bucket = TokenBucket(capacity=5, refill_rate=1.0)
        wait = bucket.try_consume(1)
        assert wait == 0.0

    def test_try_consume_returns_wait_on_failure(self) -> None:
        bucket = TokenBucket(capacity=1, refill_rate=1.0)
        bucket.consume(1)  # drain it
        wait = bucket.try_consume(1)
        assert wait > 0.0

    def test_refill_adds_tokens_over_time(self) -> None:
        bucket = TokenBucket(capacity=10, refill_rate=1000.0)
        bucket.consume(10)  # drain it
        # With high refill rate, tokens should refill almost immediately
        time.sleep(0.01)
        assert bucket.available > 0.0

    def test_refill_does_not_exceed_capacity(self) -> None:
        bucket = TokenBucket(capacity=5, refill_rate=10000.0)
        time.sleep(0.01)
        assert bucket.available <= 5.0

    def test_zero_refill_rate_never_refills(self) -> None:
        bucket = TokenBucket(capacity=2, refill_rate=0.0)
        bucket.consume(2)
        time.sleep(0.01)
        assert bucket.available == pytest.approx(0.0, abs=0.01)

    def test_try_consume_infinite_wait_with_zero_refill(self) -> None:
        bucket = TokenBucket(capacity=1, refill_rate=0.0)
        bucket.consume(1)
        wait = bucket.try_consume(1)
        assert wait == float("inf")


# ---------------------------------------------------------------------------
# SlidingWindowCounter tests
# ---------------------------------------------------------------------------


class TestSlidingWindowCounter:
    """Tests for the SlidingWindowCounter rate limiter."""

    def test_record_within_limit(self) -> None:
        sw = SlidingWindowCounter(limit=5, window_seconds=10.0)
        for _ in range(5):
            assert sw.record() is True

    def test_record_over_limit_returns_false(self) -> None:
        sw = SlidingWindowCounter(limit=2, window_seconds=10.0)
        assert sw.record() is True
        assert sw.record() is True
        assert sw.record() is False

    def test_try_record_returns_zero_when_ok(self) -> None:
        sw = SlidingWindowCounter(limit=10, window_seconds=10.0)
        assert sw.try_record() == 0.0

    def test_try_record_returns_wait_when_full(self) -> None:
        sw = SlidingWindowCounter(limit=1, window_seconds=10.0)
        sw.record()
        wait = sw.try_record()
        assert wait > 0.0

    def test_count_property(self) -> None:
        sw = SlidingWindowCounter(limit=10, window_seconds=10.0)
        sw.record()
        sw.record()
        sw.record()
        assert sw.count == 3

    def test_entries_expire_over_time(self) -> None:
        sw = SlidingWindowCounter(limit=1, window_seconds=0.01)
        sw.record()
        time.sleep(0.02)  # Wait for window to pass
        assert sw.record() is True  # Old entry expired

    def test_count_decreases_after_expiry(self) -> None:
        sw = SlidingWindowCounter(limit=10, window_seconds=0.01)
        sw.record()
        sw.record()
        time.sleep(0.02)
        assert sw.count == 0


# ---------------------------------------------------------------------------
# RateLimiter tests
# ---------------------------------------------------------------------------


class TestRateLimiter:
    """Tests for the combined RateLimiter manager."""

    def test_add_and_check_token_bucket(self) -> None:
        rl = RateLimiter()
        rl.add_token_bucket("api", capacity=10, refill_rate=1.0)
        rl.check("api")  # Should not raise

    def test_add_and_check_sliding_window(self) -> None:
        rl = RateLimiter()
        rl.add_sliding_window("api", limit=10, window_seconds=10.0)
        rl.check("api")  # Should not raise

    def test_check_raises_when_bucket_empty(self) -> None:
        rl = RateLimiter()
        rl.add_token_bucket("api", capacity=1, refill_rate=0.0)
        rl.check("api")  # consumes the 1 token
        with pytest.raises(RateLimitExceeded) as exc_info:
            rl.check("api")
        assert exc_info.value.key == "api"

    def test_check_raises_when_window_full(self) -> None:
        rl = RateLimiter()
        rl.add_sliding_window("api", limit=1, window_seconds=10.0)
        rl.check("api")  # records 1 event
        with pytest.raises(RateLimitExceeded):
            rl.check("api")

    def test_try_acquire_returns_zero_when_ok(self) -> None:
        rl = RateLimiter()
        rl.add_token_bucket("api", capacity=10, refill_rate=1.0)
        assert rl.try_acquire("api") == 0.0

    def test_try_acquire_returns_wait_when_exceeded(self) -> None:
        rl = RateLimiter()
        rl.add_token_bucket("api", capacity=1, refill_rate=1.0)
        rl.try_acquire("api")  # consume 1
        wait = rl.try_acquire("api")
        assert wait > 0.0

    def test_unknown_key_does_not_raise(self) -> None:
        """Checking an unknown key does nothing (no limiter registered)."""
        rl = RateLimiter()
        rl.check("unknown")  # Should not raise

    def test_reset_refills_bucket(self) -> None:
        rl = RateLimiter()
        rl.add_token_bucket("api", capacity=5, refill_rate=0.0)
        for _ in range(5):
            rl.check("api")
        rl.reset("api")
        rl.check("api")  # Should succeed after reset

    def test_reset_clears_window(self) -> None:
        rl = RateLimiter()
        rl.add_sliding_window("api", limit=1, window_seconds=60.0)
        rl.check("api")
        rl.reset("api")
        rl.check("api")  # Should succeed after reset

    def test_remove_key(self) -> None:
        rl = RateLimiter()
        rl.add_token_bucket("api", capacity=1, refill_rate=0.0)
        rl.check("api")
        rl.remove("api")
        rl.check("api")  # Key removed, nothing to check

    def test_remove_nonexistent_key_no_error(self) -> None:
        rl = RateLimiter()
        rl.remove("nonexistent")  # Should not raise

    def test_both_limiter_types_on_same_key(self) -> None:
        rl = RateLimiter()
        rl.add_token_bucket("api", capacity=10, refill_rate=1.0)
        rl.add_sliding_window("api", limit=10, window_seconds=10.0)
        rl.check("api")  # Both should pass

    def test_exception_retry_after_positive(self) -> None:
        rl = RateLimiter()
        rl.add_token_bucket("api", capacity=1, refill_rate=0.5)
        rl.check("api")
        with pytest.raises(RateLimitExceeded) as exc_info:
            rl.check("api")
        assert exc_info.value.retry_after > 0.0
