"""Tests for isg_agent.core.governance.

Comprehensive coverage of:
- GovernanceDecision enum values
- RiskTier enum values and ordering
- GovernanceResult frozen dataclass
- classify_risk() keyword analysis
- _check_sensitive_files() pattern matching
- _escalate_tier() tier escalation logic
- GovernanceGate.evaluate() async decision pipeline
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from isg_agent.core.governance import (
    GovernanceDecision,
    GovernanceGate,
    GovernanceResult,
    RiskTier,
    _check_sensitive_files,
    _escalate_tier,
    classify_risk,
)


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestGovernanceDecisionEnum:
    """Tests for GovernanceDecision enum members and values."""

    def test_proceed_value(self) -> None:
        assert GovernanceDecision.PROCEED.value == "PROCEED"

    def test_review_value(self) -> None:
        assert GovernanceDecision.REVIEW.value == "REVIEW"

    def test_halt_value(self) -> None:
        assert GovernanceDecision.HALT.value == "HALT"

    def test_exactly_three_members(self) -> None:
        assert len(GovernanceDecision) == 3


class TestRiskTierEnum:
    """Tests for RiskTier enum members and values."""

    def test_low_value(self) -> None:
        assert RiskTier.LOW.value == "LOW"

    def test_medium_value(self) -> None:
        assert RiskTier.MEDIUM.value == "MEDIUM"

    def test_high_value(self) -> None:
        assert RiskTier.HIGH.value == "HIGH"

    def test_critical_value(self) -> None:
        assert RiskTier.CRITICAL.value == "CRITICAL"

    def test_exactly_four_members(self) -> None:
        assert len(RiskTier) == 4


# ---------------------------------------------------------------------------
# GovernanceResult dataclass tests
# ---------------------------------------------------------------------------


class TestGovernanceResult:
    """Tests for the GovernanceResult frozen dataclass."""

    def test_fields_stored_correctly(self) -> None:
        result = GovernanceResult(
            decision=GovernanceDecision.PROCEED,
            risk_tier=RiskTier.LOW,
            reason="All clear.",
        )
        assert result.decision == GovernanceDecision.PROCEED
        assert result.risk_tier == RiskTier.LOW
        assert result.reason == "All clear."
        assert result.checks == {}

    def test_frozen_raises_on_mutation(self) -> None:
        result = GovernanceResult(
            decision=GovernanceDecision.HALT,
            risk_tier=RiskTier.CRITICAL,
            reason="Blocked.",
        )
        with pytest.raises(AttributeError):
            result.decision = GovernanceDecision.PROCEED  # type: ignore[misc]

    def test_timestamp_auto_generated(self) -> None:
        before = datetime.now(timezone.utc).isoformat()
        result = GovernanceResult(
            decision=GovernanceDecision.PROCEED,
            risk_tier=RiskTier.LOW,
            reason="Auto timestamp test.",
        )
        after = datetime.now(timezone.utc).isoformat()
        # Timestamp should be between before and after (ISO lexicographic)
        assert before <= result.timestamp <= after

    def test_checks_default_to_empty_dict(self) -> None:
        result = GovernanceResult(
            decision=GovernanceDecision.REVIEW,
            risk_tier=RiskTier.MEDIUM,
            reason="Default checks.",
        )
        assert result.checks == {}
        assert isinstance(result.checks, dict)

    def test_custom_checks_stored(self) -> None:
        checks = {"file_check": True, "keyword_check": ["delete"]}
        result = GovernanceResult(
            decision=GovernanceDecision.HALT,
            risk_tier=RiskTier.HIGH,
            reason="Custom checks.",
            checks=checks,
        )
        assert result.checks == checks


# ---------------------------------------------------------------------------
# classify_risk() tests
# ---------------------------------------------------------------------------


class TestClassifyRisk:
    """Tests for the classify_risk() keyword analysis function."""

    def test_no_keywords_returns_low(self) -> None:
        assert classify_risk("read the configuration file") == RiskTier.LOW

    def test_high_keyword_delete_returns_high(self) -> None:
        assert classify_risk("delete the old backup files") == RiskTier.HIGH

    def test_high_keyword_drop_returns_high(self) -> None:
        assert classify_risk("drop the index on users table") == RiskTier.HIGH

    def test_high_keyword_truncate_returns_high(self) -> None:
        assert classify_risk("truncate the logs table") == RiskTier.HIGH

    def test_high_keyword_rm_rf_returns_high(self) -> None:
        assert classify_risk("run rm -rf on temp directory") == RiskTier.HIGH

    def test_high_keyword_force_push_returns_high(self) -> None:
        assert classify_risk("force push the branch") == RiskTier.HIGH

    def test_high_keyword_migrate_returns_high(self) -> None:
        assert classify_risk("migrate the database schema") == RiskTier.HIGH

    def test_critical_keyword_alone_returns_medium(self) -> None:
        """Critical keyword (production/deploy) alone -> MEDIUM, not CRITICAL."""
        assert classify_risk("deploy the service") == RiskTier.MEDIUM

    def test_critical_keyword_production_alone_returns_medium(self) -> None:
        assert classify_risk("check production logs") == RiskTier.MEDIUM

    def test_both_high_and_critical_returns_critical(self) -> None:
        assert classify_risk("delete production database") == RiskTier.CRITICAL

    def test_case_insensitive(self) -> None:
        """Keywords are detected regardless of case."""
        assert classify_risk("DELETE the PRODUCTION data") == RiskTier.CRITICAL

    def test_empty_string_returns_low(self) -> None:
        assert classify_risk("") == RiskTier.LOW


# ---------------------------------------------------------------------------
# _check_sensitive_files() tests
# ---------------------------------------------------------------------------


class TestCheckSensitiveFiles:
    """Tests for the _check_sensitive_files() pattern matching helper."""

    def test_empty_list_returns_false(self) -> None:
        found, matched = _check_sensitive_files([])
        assert found is False
        assert matched == []

    def test_env_file_detected(self) -> None:
        found, matched = _check_sensitive_files([".env"])
        assert found is True
        assert ".env" in matched

    def test_env_dot_variant_detected(self) -> None:
        found, matched = _check_sensitive_files([".env.production"])
        assert found is True
        assert ".env.production" in matched

    def test_key_file_detected(self) -> None:
        found, matched = _check_sensitive_files(["server.key"])
        assert found is True
        assert "server.key" in matched

    def test_pem_file_detected(self) -> None:
        found, matched = _check_sensitive_files(["cert.pem"])
        assert found is True

    def test_secrets_directory_detected(self) -> None:
        found, matched = _check_sensitive_files(["/app/secrets/api_key.json"])
        assert found is True

    def test_credentials_file_detected(self) -> None:
        found, matched = _check_sensitive_files(["credentials.json"])
        assert found is True

    def test_credentials_directory_detected(self) -> None:
        found, matched = _check_sensitive_files(["/config/credentials/db.yaml"])
        assert found is True

    def test_normal_files_not_detected(self) -> None:
        found, matched = _check_sensitive_files(["main.py", "README.md", "config.yaml"])
        assert found is False
        assert matched == []

    def test_mixed_files_returns_only_sensitive(self) -> None:
        files = ["main.py", ".env", "config.yaml", "server.key"]
        found, matched = _check_sensitive_files(files)
        assert found is True
        assert len(matched) == 2
        assert ".env" in matched
        assert "server.key" in matched

    def test_case_insensitive_matching(self) -> None:
        """Patterns are compiled with re.IGNORECASE."""
        found, matched = _check_sensitive_files([".ENV"])
        assert found is True


# ---------------------------------------------------------------------------
# _escalate_tier() tests
# ---------------------------------------------------------------------------


class TestEscalateTier:
    """Tests for the _escalate_tier() risk tier escalation helper."""

    def test_escalate_low_to_high(self) -> None:
        assert _escalate_tier(RiskTier.LOW, RiskTier.HIGH) == RiskTier.HIGH

    def test_escalate_low_to_critical(self) -> None:
        assert _escalate_tier(RiskTier.LOW, RiskTier.CRITICAL) == RiskTier.CRITICAL

    def test_no_escalation_when_current_is_higher(self) -> None:
        assert _escalate_tier(RiskTier.CRITICAL, RiskTier.LOW) == RiskTier.CRITICAL

    def test_same_tier_returns_current(self) -> None:
        assert _escalate_tier(RiskTier.MEDIUM, RiskTier.MEDIUM) == RiskTier.MEDIUM

    def test_escalate_medium_to_high(self) -> None:
        assert _escalate_tier(RiskTier.MEDIUM, RiskTier.HIGH) == RiskTier.HIGH

    def test_no_escalation_high_to_medium(self) -> None:
        assert _escalate_tier(RiskTier.HIGH, RiskTier.MEDIUM) == RiskTier.HIGH


# ---------------------------------------------------------------------------
# GovernanceGate.evaluate() async tests
# ---------------------------------------------------------------------------


class TestGovernanceGateEvaluate:
    """Tests for the GovernanceGate.evaluate() async method."""

    async def test_low_risk_returns_proceed(self) -> None:
        gate = GovernanceGate(audit_chain=None)
        result = await gate.evaluate("read the config file")
        assert result.decision == GovernanceDecision.PROCEED
        assert result.risk_tier == RiskTier.LOW

    async def test_medium_risk_returns_review(self) -> None:
        gate = GovernanceGate(audit_chain=None)
        result = await gate.evaluate("deploy the service")
        assert result.decision == GovernanceDecision.REVIEW
        assert result.risk_tier == RiskTier.MEDIUM

    async def test_high_risk_returns_review(self) -> None:
        gate = GovernanceGate(audit_chain=None)
        result = await gate.evaluate("delete old backups")
        assert result.decision == GovernanceDecision.REVIEW
        assert result.risk_tier == RiskTier.HIGH

    async def test_critical_risk_returns_halt(self) -> None:
        gate = GovernanceGate(audit_chain=None)
        result = await gate.evaluate("delete production database")
        assert result.decision == GovernanceDecision.HALT
        assert result.risk_tier == RiskTier.CRITICAL

    async def test_explicit_risk_tier_override(self) -> None:
        """Explicit risk_tier parameter overrides auto-classification."""
        gate = GovernanceGate(audit_chain=None)
        result = await gate.evaluate(
            "read a harmless file",
            risk_tier=RiskTier.HIGH,
        )
        # Explicit HIGH, but no high keywords so no keyword escalation
        assert result.risk_tier == RiskTier.HIGH
        assert result.decision == GovernanceDecision.REVIEW

    async def test_sensitive_files_escalate_tier(self) -> None:
        """Sensitive affected files escalate the effective tier to HIGH."""
        gate = GovernanceGate(audit_chain=None)
        result = await gate.evaluate(
            "update configuration",
            affected_files=[".env"],
        )
        # Base is LOW (no keywords), but .env escalates to HIGH
        assert result.risk_tier == RiskTier.HIGH
        assert result.decision == GovernanceDecision.REVIEW

    async def test_checks_contain_risk_tier_info(self) -> None:
        gate = GovernanceGate(audit_chain=None)
        result = await gate.evaluate("deploy a new feature")
        assert "risk_tier_check" in result.checks
        check = result.checks["risk_tier_check"]
        assert check["auto_classified"] == "MEDIUM"
        assert check["explicit_override"] is None
        assert check["effective"] == "MEDIUM"

    async def test_checks_contain_keyword_analysis(self) -> None:
        gate = GovernanceGate(audit_chain=None)
        result = await gate.evaluate("delete the old logs")
        assert "keyword_analysis" in result.checks
        kw = result.checks["keyword_analysis"]
        assert "delete" in kw["dangerous_keywords_high"]

    async def test_checks_contain_file_sensitivity(self) -> None:
        gate = GovernanceGate(audit_chain=None)
        result = await gate.evaluate(
            "read files",
            affected_files=["main.py", ".env"],
        )
        fc = result.checks["file_sensitivity_check"]
        assert fc["files_checked"] == 2
        assert fc["sensitive_detected"] is True
        assert ".env" in fc["sensitive_files"]

    async def test_no_affected_files_shows_zero(self) -> None:
        gate = GovernanceGate(audit_chain=None)
        result = await gate.evaluate("just a simple task")
        fc = result.checks["file_sensitivity_check"]
        assert fc["files_checked"] == 0
        assert fc["sensitive_detected"] is False
        assert fc["sensitive_files"] == []

    async def test_result_has_timestamp(self) -> None:
        gate = GovernanceGate(audit_chain=None)
        result = await gate.evaluate("simple task")
        assert result.timestamp  # Non-empty
        # Should be parseable as ISO 8601
        datetime.fromisoformat(result.timestamp)

    async def test_result_has_reason_string(self) -> None:
        gate = GovernanceGate(audit_chain=None)
        result = await gate.evaluate("simple task")
        assert isinstance(result.reason, str)
        assert len(result.reason) > 0

    async def test_audit_chain_record_called(self, tmp_path) -> None:
        """When audit_chain is provided, record() is called with decision details."""
        from isg_agent.core.audit import AuditChain

        db_path = str(tmp_path / "gov_audit.db")
        chain = AuditChain(db_path=db_path)
        gate = GovernanceGate(audit_chain=chain)

        result = await gate.evaluate("read a config file")
        assert result.decision == GovernanceDecision.PROCEED

        # Verify the audit chain has the GENESIS + governance_decision entry
        length = await chain.get_chain_length()
        assert length >= 2  # GENESIS + at least 1 governance entry

    async def test_audit_chain_none_does_not_raise(self) -> None:
        """When audit_chain is None, evaluate still works."""
        gate = GovernanceGate(audit_chain=None)
        result = await gate.evaluate("safe task")
        assert result.decision == GovernanceDecision.PROCEED

    async def test_keyword_escalation_with_explicit_low_tier(self) -> None:
        """Even with explicit LOW, high keywords escalate to HIGH."""
        gate = GovernanceGate(audit_chain=None)
        result = await gate.evaluate(
            "delete the old temp files",
            risk_tier=RiskTier.LOW,
        )
        # Explicit LOW overridden by keyword escalation to HIGH
        assert result.risk_tier == RiskTier.HIGH
        assert result.decision == GovernanceDecision.REVIEW

    async def test_combined_keywords_and_sensitive_files(self) -> None:
        """Both dangerous keywords and sensitive files compound escalation."""
        gate = GovernanceGate(audit_chain=None)
        result = await gate.evaluate(
            "delete production credentials",
            affected_files=[".env", "server.key"],
        )
        assert result.risk_tier == RiskTier.CRITICAL
        assert result.decision == GovernanceDecision.HALT
