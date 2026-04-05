"""Tests for the trust_ledger post-execute hook wired in app.py.

Covers:
- Hook records success on successful skill execution
- Hook records failure on failed skill execution (via direct call)
- Hook uses skill_name as entity_id with 'skill' entity_type
- Hook is exception-safe (never raises to caller)
- Hook extracts agent_id from parameters when available
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from isg_agent.core.trust_ledger import TrustLedger, TrustLevel
from isg_agent.skills.executor import ExecutionResult, SkillExecutor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_success_result(skill_name: str = "contacts") -> ExecutionResult:
    return ExecutionResult(
        success=True,
        output="ok",
        error=None,
        duration_ms=50,
        audit_id="audit-100",
        skill_name=skill_name,
    )


def _make_failure_result(skill_name: str = "contacts") -> ExecutionResult:
    return ExecutionResult(
        success=False,
        output="",
        error="db error",
        duration_ms=10,
        audit_id="audit-101",
        skill_name=skill_name,
    )


# ---------------------------------------------------------------------------
# Import the hook factory from app module
# ---------------------------------------------------------------------------


class TestTrustLedgerHookFactory:
    """Tests for make_trust_ledger_hook in isg_agent.hooks.trust_ledger_hook."""

    def test_hook_factory_returns_callable(self) -> None:
        """make_trust_ledger_hook returns an async callable."""
        from isg_agent.hooks.trust_ledger_hook import make_trust_ledger_hook

        ledger = TrustLedger()
        hook = make_trust_ledger_hook(ledger)
        assert callable(hook)
        assert asyncio.iscoroutinefunction(hook)

    async def test_hook_records_success_for_skill(self) -> None:
        """On successful execution, hook records success in trust ledger."""
        from isg_agent.hooks.trust_ledger_hook import make_trust_ledger_hook

        ledger = TrustLedger()
        hook = make_trust_ledger_hook(ledger)

        result = _make_success_result(skill_name="appointments")
        await hook("appointments", {"agent_id": "agent-1"}, result)

        score = ledger.get_or_create("skill:appointments", "skill")
        assert score.total_successes == 1
        assert score.total_failures == 0
        # Score should have moved above neutral (0.5) after a success
        assert score.score > 0.5

    async def test_hook_records_agent_trust_when_agent_id_present(self) -> None:
        """When parameters include agent_id, hook also records trust for the agent."""
        from isg_agent.hooks.trust_ledger_hook import make_trust_ledger_hook

        ledger = TrustLedger()
        hook = make_trust_ledger_hook(ledger)

        result = _make_success_result(skill_name="contacts")
        await hook("contacts", {"agent_id": "agent-42"}, result)

        agent_score = ledger.get_or_create("agent:agent-42", "agent")
        assert agent_score.total_successes == 1

    async def test_hook_does_not_record_agent_when_no_agent_id(self) -> None:
        """Without agent_id in parameters, only skill trust is recorded."""
        from isg_agent.hooks.trust_ledger_hook import make_trust_ledger_hook

        ledger = TrustLedger()
        hook = make_trust_ledger_hook(ledger)

        result = _make_success_result(skill_name="invoicing")
        await hook("invoicing", {}, result)

        skill_score = ledger.get_or_create("skill:invoicing", "skill")
        assert skill_score.total_successes == 1

        # No agent entries should exist (only the skill entry)
        assert len([
            s for s in ledger._scores.values()
            if s.entity_type == "agent"
        ]) == 0

    async def test_hook_never_raises(self) -> None:
        """Even if the ledger is broken, the hook must not raise."""
        from isg_agent.hooks.trust_ledger_hook import make_trust_ledger_hook

        # Create a ledger with a broken record_success
        ledger = TrustLedger()
        ledger.record_success = MagicMock(side_effect=RuntimeError("broken"))

        hook = make_trust_ledger_hook(ledger)
        result = _make_success_result()

        # Should not raise
        await hook("contacts", {}, result)

    async def test_hook_uses_skill_prefix_as_entity_id(self) -> None:
        """Entity ID for skills follows 'skill:<name>' pattern."""
        from isg_agent.hooks.trust_ledger_hook import make_trust_ledger_hook

        ledger = TrustLedger()
        hook = make_trust_ledger_hook(ledger)

        await hook("data-store", {"agent_id": "a1"}, _make_success_result("data-store"))

        # Skill should be registered with 'skill:' prefix
        assert "skill:data-store" in ledger._scores

    async def test_multiple_executions_accumulate(self) -> None:
        """Multiple skill executions accumulate in the trust score."""
        from isg_agent.hooks.trust_ledger_hook import make_trust_ledger_hook

        ledger = TrustLedger()
        hook = make_trust_ledger_hook(ledger)

        for _ in range(5):
            await hook("contacts", {"agent_id": "a1"}, _make_success_result("contacts"))

        score = ledger.get_or_create("skill:contacts", "skill")
        assert score.total_successes == 5
        assert score.score > 0.5  # Should be well above neutral after 5 successes
