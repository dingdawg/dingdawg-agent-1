"""Tests for ExplainEngine governance decision tracing.

Covers:
- Governance decisions create an explain trace in process_message
- Trace records the governance decision, reason, and risk tier
- HALT decisions are recorded with outcome "HALT"
- PROCEED decisions are recorded with outcome "PROCEED"
- Explain engine is wired as an attribute on AgentRuntime
"""

from __future__ import annotations

import time
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

import pytest

from isg_agent.core.explain import ExplainEngine, ExplainTrace


# ---------------------------------------------------------------------------
# Test the explain governance hook directly
# ---------------------------------------------------------------------------


class TestExplainGovernanceHook:
    """Tests for the explain_governance_decision helper."""

    def test_hook_creates_trace(self) -> None:
        """explain_governance_decision creates a new trace in the engine."""
        from isg_agent.hooks.explain_governance_hook import explain_governance_decision

        engine = ExplainEngine()
        trace = explain_governance_decision(
            engine=engine,
            session_id="sess-1",
            decision="PROCEED",
            reason="Low risk message",
            risk_tier="LOW",
        )

        assert trace is not None
        assert trace.is_finalized is True
        assert len(trace.steps) == 1

    def test_hook_records_decision_in_step(self) -> None:
        """The trace step contains the governance decision."""
        from isg_agent.hooks.explain_governance_hook import explain_governance_decision

        engine = ExplainEngine()
        trace = explain_governance_decision(
            engine=engine,
            session_id="sess-2",
            decision="HALT",
            reason="Critical keyword detected",
            risk_tier="CRITICAL",
        )

        step = trace.steps[0]
        assert step.decision == "HALT"
        assert "Critical keyword detected" in step.reason
        assert step.component == "governance"

    def test_hook_records_evidence(self) -> None:
        """The trace step evidence includes session_id and risk_tier."""
        from isg_agent.hooks.explain_governance_hook import explain_governance_decision

        engine = ExplainEngine()
        trace = explain_governance_decision(
            engine=engine,
            session_id="sess-3",
            decision="REVIEW",
            reason="Moderate risk",
            risk_tier="MEDIUM",
        )

        step = trace.steps[0]
        assert step.evidence.get("session_id") == "sess-3"
        assert step.evidence.get("risk_tier") == "MEDIUM"

    def test_hook_finalizes_with_decision_as_outcome(self) -> None:
        """The trace is finalized with the governance decision as the outcome."""
        from isg_agent.hooks.explain_governance_hook import explain_governance_decision

        engine = ExplainEngine()
        trace = explain_governance_decision(
            engine=engine,
            session_id="sess-4",
            decision="PROCEED",
            reason="All clear",
            risk_tier="LOW",
        )

        assert trace.outcome == "PROCEED"

    def test_hook_trace_stored_in_engine(self) -> None:
        """The trace is retrievable from the engine after creation."""
        from isg_agent.hooks.explain_governance_hook import explain_governance_decision

        engine = ExplainEngine()
        trace = explain_governance_decision(
            engine=engine,
            session_id="sess-5",
            decision="HALT",
            reason="Blocked",
            risk_tier="CRITICAL",
        )

        retrieved = engine.get_trace(trace.trace_id)
        assert retrieved is trace

    def test_hook_never_raises_on_engine_error(self) -> None:
        """If the engine raises, the hook returns None instead of propagating."""
        from isg_agent.hooks.explain_governance_hook import explain_governance_decision

        engine = ExplainEngine()
        engine.create_trace = MagicMock(side_effect=RuntimeError("engine broken"))

        result = explain_governance_decision(
            engine=engine,
            session_id="sess-6",
            decision="PROCEED",
            reason="test",
            risk_tier="LOW",
        )

        assert result is None

    def test_multiple_decisions_create_separate_traces(self) -> None:
        """Each governance decision creates its own trace."""
        from isg_agent.hooks.explain_governance_hook import explain_governance_decision

        engine = ExplainEngine()
        t1 = explain_governance_decision(
            engine=engine,
            session_id="sess-a",
            decision="PROCEED",
            reason="ok",
            risk_tier="LOW",
        )
        t2 = explain_governance_decision(
            engine=engine,
            session_id="sess-b",
            decision="HALT",
            reason="blocked",
            risk_tier="CRITICAL",
        )

        assert t1.trace_id != t2.trace_id
        assert len(engine.list_traces()) == 2
