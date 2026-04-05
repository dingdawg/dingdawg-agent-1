"""Tests for isg_agent.core.trust_ledger.

Comprehensive coverage of:
- TrustLevel IntEnum values and ordering
- TrustRecord dataclass fields
- TrustScore: EMA calculation, confidence, level mapping, decay
- TrustLedger: get_or_create, record_success/failure, can_act_autonomously,
  decay_all, get_scores_by_level, reset
- Edge cases: boundary scores, zero observations, weight clamping
"""

from __future__ import annotations

import time

import pytest

from isg_agent.core.trust_ledger import (
    TrustLedger,
    TrustLevel,
    TrustRecord,
    TrustScore,
)


# ---------------------------------------------------------------------------
# TrustLevel enum tests
# ---------------------------------------------------------------------------


class TestTrustLevel:
    """Tests for the TrustLevel IntEnum."""

    def test_untrusted_value(self) -> None:
        assert TrustLevel.UNTRUSTED == 0

    def test_low_value(self) -> None:
        assert TrustLevel.LOW == 1

    def test_medium_value(self) -> None:
        assert TrustLevel.MEDIUM == 2

    def test_high_value(self) -> None:
        assert TrustLevel.HIGH == 3

    def test_verified_value(self) -> None:
        assert TrustLevel.VERIFIED == 4

    def test_exactly_five_members(self) -> None:
        assert len(TrustLevel) == 5

    def test_ordering(self) -> None:
        assert TrustLevel.UNTRUSTED < TrustLevel.LOW < TrustLevel.MEDIUM
        assert TrustLevel.MEDIUM < TrustLevel.HIGH < TrustLevel.VERIFIED


# ---------------------------------------------------------------------------
# TrustRecord tests
# ---------------------------------------------------------------------------


class TestTrustRecord:
    """Tests for the TrustRecord dataclass."""

    def test_fields_stored(self) -> None:
        rec = TrustRecord(timestamp=1.0, success=True, weight=0.5, context="test")
        assert rec.timestamp == 1.0
        assert rec.success is True
        assert rec.weight == 0.5
        assert rec.context == "test"

    def test_defaults(self) -> None:
        rec = TrustRecord(timestamp=2.0, success=False)
        assert rec.weight == 1.0
        assert rec.context == ""


# ---------------------------------------------------------------------------
# TrustScore tests
# ---------------------------------------------------------------------------


class TestTrustScore:
    """Tests for the TrustScore EMA-based trust tracker."""

    def test_initial_score_is_half(self) -> None:
        ts = TrustScore(entity_id="agent-1", entity_type="agent")
        assert ts.score == 0.5

    def test_initial_level_is_medium(self) -> None:
        ts = TrustScore(entity_id="agent-1", entity_type="agent")
        assert ts.level == TrustLevel.MEDIUM

    def test_success_increases_score(self) -> None:
        ts = TrustScore(entity_id="a1", entity_type="agent")
        initial = ts.score
        ts.record_outcome(success=True)
        assert ts.score > initial

    def test_failure_decreases_score(self) -> None:
        ts = TrustScore(entity_id="a1", entity_type="agent")
        initial = ts.score
        ts.record_outcome(success=False)
        assert ts.score < initial

    def test_ema_formula(self) -> None:
        """Verify the EMA update: score = alpha * obs + (1 - alpha) * score."""
        ts = TrustScore(entity_id="a1", entity_type="agent")
        # Alpha = 0.1, initial score = 0.5, success obs = 1.0
        expected = 0.1 * 1.0 + 0.9 * 0.5
        ts.record_outcome(success=True)
        assert ts.score == pytest.approx(expected, abs=1e-6)

    def test_failure_ema_formula(self) -> None:
        ts = TrustScore(entity_id="a1", entity_type="agent")
        # Alpha = 0.1, initial score = 0.5, failure obs = 0.0
        expected = 0.1 * 0.0 + 0.9 * 0.5
        ts.record_outcome(success=False)
        assert ts.score == pytest.approx(expected, abs=1e-6)

    def test_confidence_starts_at_zero(self) -> None:
        ts = TrustScore(entity_id="a1", entity_type="agent")
        assert ts.confidence == 0.0

    def test_confidence_after_one_observation(self) -> None:
        ts = TrustScore(entity_id="a1", entity_type="agent")
        ts.record_outcome(success=True)
        assert ts.confidence == pytest.approx(1.0 / 20.0, abs=1e-6)

    def test_confidence_capped_at_one(self) -> None:
        ts = TrustScore(entity_id="a1", entity_type="agent")
        for _ in range(50):
            ts.record_outcome(success=True)
        assert ts.confidence == 1.0

    def test_total_successes_incremented(self) -> None:
        ts = TrustScore(entity_id="a1", entity_type="agent")
        ts.record_outcome(success=True)
        ts.record_outcome(success=True)
        assert ts.total_successes == 2

    def test_total_failures_incremented(self) -> None:
        ts = TrustScore(entity_id="a1", entity_type="agent")
        ts.record_outcome(success=False)
        assert ts.total_failures == 1

    def test_decay_moves_toward_half(self) -> None:
        ts = TrustScore(entity_id="a1", entity_type="agent", score=0.9)
        ts.apply_decay(decay_rate=0.1)
        # Should move 10% of distance toward 0.5: 0.9 - 0.1 * (0.9 - 0.5) = 0.86
        assert ts.score == pytest.approx(0.86, abs=1e-6)

    def test_decay_from_below_half_moves_up(self) -> None:
        ts = TrustScore(entity_id="a1", entity_type="agent", score=0.1)
        ts.apply_decay(decay_rate=0.1)
        # 0.1 - 0.1 * (0.1 - 0.5) = 0.1 + 0.04 = 0.14
        assert ts.score == pytest.approx(0.14, abs=1e-6)

    def test_score_clamped_to_valid_range(self) -> None:
        ts = TrustScore(entity_id="a1", entity_type="agent", score=0.0)
        ts.record_outcome(success=False)
        assert ts.score >= 0.0
        assert ts.score <= 1.0

    def test_level_mapping_verified(self) -> None:
        ts = TrustScore(entity_id="a1", entity_type="agent", score=0.9)
        assert ts.level == TrustLevel.VERIFIED

    def test_level_mapping_untrusted(self) -> None:
        ts = TrustScore(entity_id="a1", entity_type="agent", score=0.1)
        assert ts.level == TrustLevel.UNTRUSTED

    def test_level_mapping_high(self) -> None:
        ts = TrustScore(entity_id="a1", entity_type="agent", score=0.7)
        assert ts.level == TrustLevel.HIGH

    def test_level_mapping_low(self) -> None:
        ts = TrustScore(entity_id="a1", entity_type="agent", score=0.3)
        assert ts.level == TrustLevel.LOW

    def test_history_appended(self) -> None:
        ts = TrustScore(entity_id="a1", entity_type="agent")
        ts.record_outcome(success=True, context="test1")
        ts.record_outcome(success=False, context="test2")
        assert len(ts._history) == 2
        assert ts._history[0].success is True
        assert ts._history[1].success is False


# ---------------------------------------------------------------------------
# TrustLedger tests
# ---------------------------------------------------------------------------


class TestTrustLedger:
    """Tests for the TrustLedger manager."""

    def test_get_or_create_new_entity(self) -> None:
        ledger = TrustLedger()
        score = ledger.get_or_create("agent-1")
        assert score.entity_id == "agent-1"
        assert score.score == 0.5

    def test_get_or_create_returns_existing(self) -> None:
        ledger = TrustLedger()
        s1 = ledger.get_or_create("agent-1")
        s2 = ledger.get_or_create("agent-1")
        assert s1 is s2

    def test_record_success(self) -> None:
        ledger = TrustLedger()
        ledger.record_success("agent-1")
        score = ledger.get_or_create("agent-1")
        assert score.score > 0.5

    def test_record_failure(self) -> None:
        ledger = TrustLedger()
        ledger.record_failure("agent-1")
        score = ledger.get_or_create("agent-1")
        assert score.score < 0.5

    def test_can_act_autonomously_false_by_default(self) -> None:
        ledger = TrustLedger(autonomous_threshold=0.7)
        assert ledger.can_act_autonomously("new-agent") is False

    def test_can_act_autonomously_after_many_successes(self) -> None:
        ledger = TrustLedger(autonomous_threshold=0.7)
        for _ in range(50):
            ledger.record_success("reliable-agent")
        assert ledger.can_act_autonomously("reliable-agent") is True

    def test_can_act_autonomously_after_failures(self) -> None:
        ledger = TrustLedger(autonomous_threshold=0.7)
        for _ in range(50):
            ledger.record_failure("bad-agent")
        assert ledger.can_act_autonomously("bad-agent") is False

    def test_decay_all(self) -> None:
        ledger = TrustLedger()
        ledger.get_or_create("a1")
        ledger.get_or_create("a2")
        count = ledger.decay_all()
        assert count == 2

    def test_get_trust_level(self) -> None:
        ledger = TrustLedger()
        level = ledger.get_trust_level("new-agent")
        assert level == TrustLevel.MEDIUM  # 0.5 is MEDIUM

    def test_get_scores_by_level(self) -> None:
        ledger = TrustLedger()
        ledger.get_or_create("a1")  # 0.5 = MEDIUM
        ledger.get_or_create("a2")  # 0.5 = MEDIUM
        mediums = ledger.get_scores_by_level(TrustLevel.MEDIUM)
        assert len(mediums) == 2

    def test_get_scores_by_level_empty(self) -> None:
        ledger = TrustLedger()
        ledger.get_or_create("a1")
        assert ledger.get_scores_by_level(TrustLevel.VERIFIED) == []

    def test_reset_entity(self) -> None:
        ledger = TrustLedger()
        for _ in range(20):
            ledger.record_success("a1")
        ledger.reset("a1")
        score = ledger.get_or_create("a1")
        assert score.score == 0.5
        assert score.total_successes == 0
        assert score.total_failures == 0

    def test_reset_nonexistent_no_error(self) -> None:
        ledger = TrustLedger()
        ledger.reset("nonexistent")  # Should not raise

    def test_custom_autonomous_threshold(self) -> None:
        ledger = TrustLedger(autonomous_threshold=0.5)
        # At 0.5 threshold, neutral score exactly meets it
        assert ledger.can_act_autonomously("new-agent") is True


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case tests for trust scoring."""

    def test_many_successes_approaches_one(self) -> None:
        ts = TrustScore(entity_id="a1", entity_type="agent")
        for _ in range(200):
            ts.record_outcome(success=True)
        assert ts.score > 0.95

    def test_many_failures_approaches_zero(self) -> None:
        ts = TrustScore(entity_id="a1", entity_type="agent")
        for _ in range(200):
            ts.record_outcome(success=False)
        assert ts.score < 0.05

    def test_alternating_stays_near_half(self) -> None:
        ts = TrustScore(entity_id="a1", entity_type="agent")
        for i in range(100):
            ts.record_outcome(success=(i % 2 == 0))
        # Should stay near 0.5
        assert 0.4 < ts.score < 0.6

    def test_weight_zero_has_minimal_effect(self) -> None:
        ts = TrustScore(entity_id="a1", entity_type="agent")
        initial = ts.score
        ts.record_outcome(success=True, weight=0.0)
        # Weight 0 means observation is 0.0 regardless of success
        # EMA: 0.1 * 0.0 + 0.9 * 0.5 = 0.45
        assert ts.score == pytest.approx(0.45, abs=1e-6)

    def test_last_updated_changes(self) -> None:
        ts = TrustScore(entity_id="a1", entity_type="agent")
        before = ts.last_updated
        time.sleep(0.001)
        ts.record_outcome(success=True)
        assert ts.last_updated > before

    def test_record_with_context(self) -> None:
        ledger = TrustLedger()
        ledger.record_success("a1", context="passed governance check")
        score = ledger.get_or_create("a1")
        assert score._history[0].context == "passed governance check"
