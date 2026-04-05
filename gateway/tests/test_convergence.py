"""Tests for isg_agent.core.convergence.

Comprehensive coverage of:
- ResourceBudget defaults and custom values
- backoff_delay() exponential growth with cap
- ConvergenceBudgetExceeded exception attributes
- ConvergenceGuard tracking (iterations, LLM calls, tokens, duration)
- ConvergenceGuard status checks (WITHIN_BUDGET, WARNING at 80%, BUDGET_EXCEEDED)
- ConvergenceGuard.enforce() raising on exceeded budgets
- ConvergenceGuard.remaining() dimension reporting
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from isg_agent.core.convergence import (
    ConvergenceBudgetExceeded,
    ConvergenceGuard,
    ConvergenceStatus,
    ResourceBudget,
    backoff_delay,
)


# ---------------------------------------------------------------------------
# ResourceBudget tests
# ---------------------------------------------------------------------------


class TestResourceBudget:
    """Tests for the ResourceBudget frozen dataclass defaults and customisation."""

    def test_default_max_iterations(self) -> None:
        b = ResourceBudget()
        assert b.max_iterations == 100

    def test_default_max_duration_seconds(self) -> None:
        b = ResourceBudget()
        assert b.max_duration_seconds == 300.0

    def test_default_max_llm_calls(self) -> None:
        b = ResourceBudget()
        assert b.max_llm_calls == 50

    def test_default_max_tokens_is_none(self) -> None:
        b = ResourceBudget()
        assert b.max_tokens is None

    def test_custom_budget_values(self) -> None:
        b = ResourceBudget(
            max_iterations=10,
            max_duration_seconds=60.0,
            max_llm_calls=5,
            max_tokens=1000,
        )
        assert b.max_iterations == 10
        assert b.max_duration_seconds == 60.0
        assert b.max_llm_calls == 5
        assert b.max_tokens == 1000

    def test_frozen_raises_on_mutation(self) -> None:
        b = ResourceBudget()
        with pytest.raises(AttributeError):
            b.max_iterations = 999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# backoff_delay() tests
# ---------------------------------------------------------------------------


class TestBackoffDelay:
    """Tests for the backoff_delay() exponential backoff helper."""

    def test_attempt_zero_returns_base(self) -> None:
        """First attempt (0) returns base * 2^0 = base."""
        assert backoff_delay(attempt=0, base=1.0) == 1.0

    def test_attempt_one_doubles(self) -> None:
        assert backoff_delay(attempt=1, base=1.0) == 2.0

    def test_attempt_two_quadruples(self) -> None:
        assert backoff_delay(attempt=2, base=1.0) == 4.0

    def test_exponential_growth(self) -> None:
        """Each attempt doubles the delay from the previous."""
        delays = [backoff_delay(attempt=i, base=1.0, max_delay=1000.0) for i in range(5)]
        assert delays == [1.0, 2.0, 4.0, 8.0, 16.0]

    def test_capped_at_max_delay(self) -> None:
        """Delay never exceeds max_delay."""
        delay = backoff_delay(attempt=100, base=1.0, max_delay=60.0)
        assert delay == 60.0

    def test_custom_base(self) -> None:
        assert backoff_delay(attempt=0, base=5.0) == 5.0
        assert backoff_delay(attempt=1, base=5.0) == 10.0

    def test_custom_max_delay(self) -> None:
        delay = backoff_delay(attempt=10, base=1.0, max_delay=30.0)
        assert delay == 30.0

    def test_delay_between_base_and_max(self) -> None:
        """Result is always >= base and <= max_delay for any attempt."""
        for attempt in range(20):
            d = backoff_delay(attempt=attempt, base=2.0, max_delay=120.0)
            assert 2.0 <= d <= 120.0


# ---------------------------------------------------------------------------
# ConvergenceBudgetExceeded exception tests
# ---------------------------------------------------------------------------


class TestConvergenceBudgetExceeded:
    """Tests for the ConvergenceBudgetExceeded exception."""

    def test_exception_attributes_stored(self) -> None:
        exc = ConvergenceBudgetExceeded(dimension="iterations", used=110.0, limit=100.0)
        assert exc.dimension == "iterations"
        assert exc.used == 110.0
        assert exc.limit == 100.0

    def test_exception_message_format(self) -> None:
        exc = ConvergenceBudgetExceeded(dimension="llm_calls", used=55.0, limit=50.0)
        msg = str(exc)
        assert "llm_calls" in msg
        assert "55" in msg
        assert "50" in msg

    def test_is_subclass_of_exception(self) -> None:
        exc = ConvergenceBudgetExceeded(dimension="tokens", used=200.0, limit=100.0)
        assert isinstance(exc, Exception)

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(ConvergenceBudgetExceeded, match="iterations"):
            raise ConvergenceBudgetExceeded(dimension="iterations", used=101.0, limit=100.0)


# ---------------------------------------------------------------------------
# ConvergenceStatus enum tests
# ---------------------------------------------------------------------------


class TestConvergenceStatus:
    """Tests for the ConvergenceStatus enum."""

    def test_within_budget_value(self) -> None:
        assert ConvergenceStatus.WITHIN_BUDGET.value == "WITHIN_BUDGET"

    def test_warning_value(self) -> None:
        assert ConvergenceStatus.WARNING.value == "WARNING"

    def test_budget_exceeded_value(self) -> None:
        assert ConvergenceStatus.BUDGET_EXCEEDED.value == "BUDGET_EXCEEDED"

    def test_exactly_three_members(self) -> None:
        assert len(ConvergenceStatus) == 3


# ---------------------------------------------------------------------------
# ConvergenceGuard tracking tests
# ---------------------------------------------------------------------------


class TestConvergenceGuardTracking:
    """Tests for ConvergenceGuard iteration/LLM/token/duration tracking."""

    def test_initial_counters_zero(self) -> None:
        guard = ConvergenceGuard()
        assert guard.iterations_used == 0
        assert guard.llm_calls_made == 0
        assert guard.tokens_used == 0
        assert guard.duration_elapsed == 0.0

    def test_record_iteration_increments(self) -> None:
        guard = ConvergenceGuard()
        guard.record_iteration()
        guard.record_iteration()
        guard.record_iteration()
        assert guard.iterations_used == 3

    def test_record_llm_call_increments(self) -> None:
        guard = ConvergenceGuard()
        guard.record_llm_call()
        guard.record_llm_call()
        assert guard.llm_calls_made == 2

    def test_record_llm_call_with_tokens(self) -> None:
        guard = ConvergenceGuard()
        guard.record_llm_call(tokens=100)
        guard.record_llm_call(tokens=250)
        assert guard.llm_calls_made == 2
        assert guard.tokens_used == 350

    def test_start_enables_duration_tracking(self) -> None:
        guard = ConvergenceGuard()
        guard.start()
        time.sleep(0.01)  # 10ms sleep
        assert guard.duration_elapsed > 0.0

    def test_duration_zero_before_start(self) -> None:
        guard = ConvergenceGuard()
        assert guard.duration_elapsed == 0.0

    def test_start_resets_timer(self) -> None:
        guard = ConvergenceGuard()
        guard.start()
        time.sleep(0.02)
        first_elapsed = guard.duration_elapsed
        guard.start()  # Reset
        assert guard.duration_elapsed < first_elapsed


# ---------------------------------------------------------------------------
# ConvergenceGuard.check() status tests
# ---------------------------------------------------------------------------


class TestConvergenceGuardCheck:
    """Tests for ConvergenceGuard.check() three-tier status reporting."""

    def test_fresh_guard_within_budget(self) -> None:
        guard = ConvergenceGuard()
        assert guard.check() == ConvergenceStatus.WITHIN_BUDGET

    def test_warning_at_80_percent_iterations(self) -> None:
        budget = ResourceBudget(max_iterations=10)
        guard = ConvergenceGuard(budget=budget)
        for _ in range(8):
            guard.record_iteration()
        assert guard.check() == ConvergenceStatus.WARNING

    def test_exceeded_at_100_percent_iterations(self) -> None:
        budget = ResourceBudget(max_iterations=10)
        guard = ConvergenceGuard(budget=budget)
        for _ in range(10):
            guard.record_iteration()
        assert guard.check() == ConvergenceStatus.BUDGET_EXCEEDED

    def test_warning_at_80_percent_llm_calls(self) -> None:
        budget = ResourceBudget(max_llm_calls=10)
        guard = ConvergenceGuard(budget=budget)
        for _ in range(8):
            guard.record_llm_call()
        assert guard.check() == ConvergenceStatus.WARNING

    def test_exceeded_at_100_percent_llm_calls(self) -> None:
        budget = ResourceBudget(max_llm_calls=5)
        guard = ConvergenceGuard(budget=budget)
        for _ in range(5):
            guard.record_llm_call()
        assert guard.check() == ConvergenceStatus.BUDGET_EXCEEDED

    def test_token_budget_warning(self) -> None:
        budget = ResourceBudget(max_tokens=1000)
        guard = ConvergenceGuard(budget=budget)
        guard.record_llm_call(tokens=800)
        assert guard.check() == ConvergenceStatus.WARNING

    def test_token_budget_exceeded(self) -> None:
        budget = ResourceBudget(max_tokens=1000)
        guard = ConvergenceGuard(budget=budget)
        guard.record_llm_call(tokens=1000)
        assert guard.check() == ConvergenceStatus.BUDGET_EXCEEDED

    def test_no_token_budget_ignores_tokens(self) -> None:
        """When max_tokens is None, token usage does not affect status."""
        budget = ResourceBudget(max_tokens=None)
        guard = ConvergenceGuard(budget=budget)
        guard.record_llm_call(tokens=999999)
        # Only 1 LLM call out of 50, so still within budget
        assert guard.check() == ConvergenceStatus.WITHIN_BUDGET

    def test_is_exceeded_returns_bool(self) -> None:
        budget = ResourceBudget(max_iterations=5)
        guard = ConvergenceGuard(budget=budget)
        assert guard.is_exceeded() is False
        for _ in range(5):
            guard.record_iteration()
        assert guard.is_exceeded() is True


# ---------------------------------------------------------------------------
# ConvergenceGuard.enforce() tests
# ---------------------------------------------------------------------------


class TestConvergenceGuardEnforce:
    """Tests for ConvergenceGuard.enforce() raising on budget exceeded."""

    def test_enforce_does_not_raise_within_budget(self) -> None:
        guard = ConvergenceGuard()
        guard.enforce()  # Should not raise

    def test_enforce_raises_on_iterations_exceeded(self) -> None:
        budget = ResourceBudget(max_iterations=3)
        guard = ConvergenceGuard(budget=budget)
        for _ in range(3):
            guard.record_iteration()
        with pytest.raises(ConvergenceBudgetExceeded, match="iterations"):
            guard.enforce()

    def test_enforce_raises_on_llm_calls_exceeded(self) -> None:
        budget = ResourceBudget(max_llm_calls=2)
        guard = ConvergenceGuard(budget=budget)
        guard.record_llm_call()
        guard.record_llm_call()
        with pytest.raises(ConvergenceBudgetExceeded, match="llm_calls"):
            guard.enforce()

    def test_enforce_raises_on_tokens_exceeded(self) -> None:
        budget = ResourceBudget(max_tokens=500)
        guard = ConvergenceGuard(budget=budget)
        guard.record_llm_call(tokens=500)
        with pytest.raises(ConvergenceBudgetExceeded, match="tokens"):
            guard.enforce()

    def test_enforce_raises_on_duration_exceeded(self) -> None:
        """Duration enforcement triggers when elapsed >= max_duration_seconds."""
        budget = ResourceBudget(max_duration_seconds=0.01)  # 10ms
        guard = ConvergenceGuard(budget=budget)
        guard.start()
        time.sleep(0.02)  # Sleep 20ms to exceed 10ms budget
        with pytest.raises(ConvergenceBudgetExceeded, match="duration_seconds"):
            guard.enforce()

    def test_enforce_exception_has_correct_attributes(self) -> None:
        budget = ResourceBudget(max_iterations=5)
        guard = ConvergenceGuard(budget=budget)
        for _ in range(5):
            guard.record_iteration()
        with pytest.raises(ConvergenceBudgetExceeded) as exc_info:
            guard.enforce()
        assert exc_info.value.dimension == "iterations"
        assert exc_info.value.used == 5.0
        assert exc_info.value.limit == 5.0


# ---------------------------------------------------------------------------
# ConvergenceGuard.remaining() tests
# ---------------------------------------------------------------------------


class TestConvergenceGuardRemaining:
    """Tests for ConvergenceGuard.remaining() dimension reporting."""

    def test_remaining_at_start(self) -> None:
        budget = ResourceBudget(max_iterations=100, max_llm_calls=50)
        guard = ConvergenceGuard(budget=budget)
        rem = guard.remaining()
        assert rem["iterations"] == 100
        assert rem["llm_calls"] == 50
        assert rem["duration_seconds"] == 300.0  # default max_duration_seconds

    def test_remaining_after_usage(self) -> None:
        budget = ResourceBudget(max_iterations=10, max_llm_calls=5)
        guard = ConvergenceGuard(budget=budget)
        for _ in range(3):
            guard.record_iteration()
        guard.record_llm_call()
        rem = guard.remaining()
        assert rem["iterations"] == 7
        assert rem["llm_calls"] == 4

    def test_remaining_negative_when_exceeded(self) -> None:
        budget = ResourceBudget(max_iterations=5)
        guard = ConvergenceGuard(budget=budget)
        for _ in range(7):
            guard.record_iteration()
        rem = guard.remaining()
        assert rem["iterations"] == -2

    def test_remaining_includes_tokens_when_set(self) -> None:
        budget = ResourceBudget(max_tokens=1000)
        guard = ConvergenceGuard(budget=budget)
        guard.record_llm_call(tokens=300)
        rem = guard.remaining()
        assert rem["tokens"] == 700

    def test_remaining_excludes_tokens_when_none(self) -> None:
        budget = ResourceBudget(max_tokens=None)
        guard = ConvergenceGuard(budget=budget)
        rem = guard.remaining()
        assert "tokens" not in rem

    def test_remaining_duration_before_start(self) -> None:
        """Before start() is called, remaining duration equals full budget."""
        budget = ResourceBudget(max_duration_seconds=120.0)
        guard = ConvergenceGuard(budget=budget)
        rem = guard.remaining()
        assert rem["duration_seconds"] == 120.0

    def test_remaining_duration_after_start(self) -> None:
        budget = ResourceBudget(max_duration_seconds=120.0)
        guard = ConvergenceGuard(budget=budget)
        guard.start()
        time.sleep(0.01)
        rem = guard.remaining()
        assert rem["duration_seconds"] < 120.0
        assert rem["duration_seconds"] > 0.0


# ---------------------------------------------------------------------------
# ConvergenceGuard with default budget tests
# ---------------------------------------------------------------------------


class TestConvergenceGuardDefaultBudget:
    """Tests that ConvergenceGuard uses sensible defaults when no budget given."""

    def test_default_budget_applied(self) -> None:
        guard = ConvergenceGuard()
        rem = guard.remaining()
        assert rem["iterations"] == 100
        assert rem["llm_calls"] == 50
        assert rem["duration_seconds"] == 300.0
