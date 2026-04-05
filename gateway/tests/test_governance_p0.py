"""P0 tests for governance.py — MEDIUM risk tier reachability fix.

Verifies that the classify_risk() function can produce MEDIUM tier, and that
MEDIUM tier results in a REVIEW governance decision (not PROCEED or HALT).
"""

import pytest

from isg_agent.core.governance import (
    GovernanceDecision,
    GovernanceGate,
    RiskTier,
    classify_risk,
)


class TestMediumRiskTierReachable:
    """Tests that MEDIUM risk tier is reachable via auto-classification."""

    def test_critical_keyword_alone_produces_medium(self) -> None:
        """A task with only critical keywords (no high keywords) classifies as MEDIUM.

        Critical keywords alone indicate awareness of a sensitive context
        (production, deploy) without dangerous operations (delete, drop, etc.),
        warranting review but not a full halt.
        """
        tier = classify_risk("deploy the service")
        assert tier == RiskTier.MEDIUM, (
            f"Expected MEDIUM for critical-only keywords, got {tier.value}"
        )

    def test_production_keyword_alone_produces_medium(self) -> None:
        """'production' is a critical keyword — alone it should produce MEDIUM."""
        tier = classify_risk("check production logs")
        assert tier == RiskTier.MEDIUM, (
            f"Expected MEDIUM for 'production' alone, got {tier.value}"
        )

    def test_high_keyword_alone_produces_high(self) -> None:
        """A task with only high keywords (no critical keywords) classifies as HIGH."""
        tier = classify_risk("delete the old backup files")
        assert tier == RiskTier.HIGH, (
            f"Expected HIGH for high-only keywords, got {tier.value}"
        )

    def test_both_keywords_produce_critical(self) -> None:
        """A task with both high and critical keywords classifies as CRITICAL."""
        tier = classify_risk("delete production database")
        assert tier == RiskTier.CRITICAL, (
            f"Expected CRITICAL for both keyword sets, got {tier.value}"
        )

    def test_no_keywords_produce_low(self) -> None:
        """A task with no dangerous keywords classifies as LOW."""
        tier = classify_risk("read the configuration file")
        assert tier == RiskTier.LOW, (
            f"Expected LOW for no keywords, got {tier.value}"
        )


class TestMediumDecisionIsReview:
    """Tests that MEDIUM risk tier produces a REVIEW governance decision."""

    @pytest.mark.asyncio
    async def test_medium_tier_returns_review(self) -> None:
        """GovernanceGate.evaluate with MEDIUM auto-classification returns REVIEW."""
        gate = GovernanceGate(audit_chain=None)
        result = await gate.evaluate("deploy the new feature")
        assert result.risk_tier == RiskTier.MEDIUM, (
            f"Expected MEDIUM risk tier, got {result.risk_tier.value}"
        )
        assert result.decision == GovernanceDecision.REVIEW, (
            f"Expected REVIEW decision for MEDIUM tier, got {result.decision.value}"
        )

    @pytest.mark.asyncio
    async def test_explicit_medium_tier_returns_review(self) -> None:
        """GovernanceGate.evaluate with explicit MEDIUM tier returns REVIEW."""
        gate = GovernanceGate(audit_chain=None)
        result = await gate.evaluate(
            "update the readme file",
            risk_tier=RiskTier.MEDIUM,
        )
        assert result.decision == GovernanceDecision.REVIEW, (
            f"Expected REVIEW for explicit MEDIUM tier, got {result.decision.value}"
        )

    @pytest.mark.asyncio
    async def test_low_tier_returns_proceed(self) -> None:
        """LOW tier should still return PROCEED."""
        gate = GovernanceGate(audit_chain=None)
        result = await gate.evaluate("read config file")
        assert result.decision == GovernanceDecision.PROCEED, (
            f"Expected PROCEED for LOW tier, got {result.decision.value}"
        )

    @pytest.mark.asyncio
    async def test_critical_tier_returns_halt(self) -> None:
        """CRITICAL tier should still return HALT."""
        gate = GovernanceGate(audit_chain=None)
        result = await gate.evaluate("delete production database")
        assert result.decision == GovernanceDecision.HALT, (
            f"Expected HALT for CRITICAL tier, got {result.decision.value}"
        )
