"""Tests for isg_agent.core.explain.

Comprehensive coverage of:
- ExplainStep dataclass fields and defaults
- ExplainTrace: add_step, finalize, is_finalized, outcome,
  to_human_readable, to_dict, read-only after finalize
- ExplainEngine: create_trace, get_trace, record_decision,
  finalize_trace, explain, list_traces, cleanup (LRU eviction)
"""

from __future__ import annotations

import time

import pytest

from isg_agent.core.explain import (
    ExplainEngine,
    ExplainStep,
    ExplainTrace,
)


# ---------------------------------------------------------------------------
# ExplainStep tests
# ---------------------------------------------------------------------------


class TestExplainStep:
    """Tests for the ExplainStep dataclass."""

    def test_fields_stored(self) -> None:
        step = ExplainStep(
            step_number=1,
            decision="allow",
            reason="low risk",
            evidence={"risk": 0.1},
            component="governance",
        )
        assert step.step_number == 1
        assert step.decision == "allow"
        assert step.reason == "low risk"
        assert step.evidence == {"risk": 0.1}
        assert step.component == "governance"

    def test_defaults(self) -> None:
        step = ExplainStep(step_number=2, decision="deny", reason="high risk")
        assert step.evidence == {}
        assert step.component == ""

    def test_timestamp_is_monotonic(self) -> None:
        before = time.monotonic()
        step = ExplainStep(step_number=1, decision="d", reason="r")
        after = time.monotonic()
        assert before <= step.timestamp <= after

    def test_evidence_mutable(self) -> None:
        step = ExplainStep(step_number=1, decision="d", reason="r")
        step.evidence["new_key"] = "value"
        assert step.evidence["new_key"] == "value"


# ---------------------------------------------------------------------------
# ExplainTrace tests
# ---------------------------------------------------------------------------


class TestExplainTrace:
    """Tests for the ExplainTrace explanation trace."""

    def test_new_trace_has_no_steps(self) -> None:
        trace = ExplainTrace(trace_id="t1")
        assert len(trace.steps) == 0

    def test_new_trace_is_not_finalized(self) -> None:
        trace = ExplainTrace(trace_id="t1")
        assert trace.is_finalized is False

    def test_outcome_empty_before_finalize(self) -> None:
        trace = ExplainTrace(trace_id="t1")
        assert trace.outcome == ""

    def test_add_step_returns_step(self) -> None:
        trace = ExplainTrace(trace_id="t1")
        step = trace.add_step(decision="allow", reason="safe")
        assert isinstance(step, ExplainStep)

    def test_add_step_increments_number(self) -> None:
        trace = ExplainTrace(trace_id="t1")
        s1 = trace.add_step(decision="a", reason="r")
        s2 = trace.add_step(decision="b", reason="r")
        assert s1.step_number == 1
        assert s2.step_number == 2

    def test_add_step_with_component_and_evidence(self) -> None:
        trace = ExplainTrace(trace_id="t1")
        step = trace.add_step(
            decision="allow",
            reason="safe",
            component="security",
            evidence={"score": 0.9},
        )
        assert step.component == "security"
        assert step.evidence == {"score": 0.9}

    def test_finalize_marks_read_only(self) -> None:
        trace = ExplainTrace(trace_id="t1")
        trace.finalize(outcome="PROCEED")
        assert trace.is_finalized is True
        assert trace.outcome == "PROCEED"

    def test_finalize_without_outcome(self) -> None:
        trace = ExplainTrace(trace_id="t1")
        trace.finalize()
        assert trace.is_finalized is True
        assert trace.outcome == ""

    def test_add_step_after_finalize_raises(self) -> None:
        trace = ExplainTrace(trace_id="t1")
        trace.finalize()
        with pytest.raises(RuntimeError, match="finalized"):
            trace.add_step(decision="x", reason="y")

    def test_to_human_readable_format(self) -> None:
        trace = ExplainTrace(trace_id="abc123")
        trace.add_step(decision="allow", reason="low risk", component="gov")
        trace.finalize(outcome="PROCEED")
        text = trace.to_human_readable()
        assert "abc123" in text
        assert "allow" in text
        assert "low risk" in text
        assert "gov" in text
        assert "PROCEED" in text

    def test_to_human_readable_not_finalized(self) -> None:
        trace = ExplainTrace(trace_id="t1")
        text = trace.to_human_readable()
        assert "(not finalized)" in text

    def test_to_human_readable_evidence_shown(self) -> None:
        trace = ExplainTrace(trace_id="t1")
        trace.add_step(
            decision="d", reason="r", evidence={"key": "val"}
        )
        text = trace.to_human_readable()
        assert "key" in text
        assert "val" in text

    def test_to_human_readable_no_component_omits_line(self) -> None:
        trace = ExplainTrace(trace_id="t1")
        trace.add_step(decision="d", reason="r", component="")
        text = trace.to_human_readable()
        assert "Component" not in text

    def test_to_dict_structure(self) -> None:
        trace = ExplainTrace(trace_id="t1")
        trace.add_step(decision="allow", reason="safe", component="gov")
        trace.finalize(outcome="PROCEED")
        d = trace.to_dict()
        assert d["trace_id"] == "t1"
        assert d["is_finalized"] is True
        assert d["outcome"] == "PROCEED"
        assert len(d["steps"]) == 1
        assert d["steps"][0]["decision"] == "allow"
        assert d["steps"][0]["component"] == "gov"

    def test_to_dict_has_started_at(self) -> None:
        trace = ExplainTrace(trace_id="t1")
        d = trace.to_dict()
        assert "started_at" in d
        assert isinstance(d["started_at"], float)

    def test_started_at_is_monotonic(self) -> None:
        before = time.monotonic()
        trace = ExplainTrace(trace_id="t1")
        after = time.monotonic()
        assert before <= trace.started_at <= after


# ---------------------------------------------------------------------------
# ExplainEngine tests
# ---------------------------------------------------------------------------


class TestExplainEngine:
    """Tests for the ExplainEngine trace manager."""

    def test_create_trace_auto_id(self) -> None:
        engine = ExplainEngine()
        trace = engine.create_trace()
        assert len(trace.trace_id) == 12
        assert trace.trace_id.isalnum()

    def test_create_trace_custom_id(self) -> None:
        engine = ExplainEngine()
        trace = engine.create_trace(trace_id="custom-id")
        assert trace.trace_id == "custom-id"

    def test_get_trace_returns_existing(self) -> None:
        engine = ExplainEngine()
        t = engine.create_trace(trace_id="t1")
        assert engine.get_trace("t1") is t

    def test_get_trace_returns_none_for_missing(self) -> None:
        engine = ExplainEngine()
        assert engine.get_trace("nonexistent") is None

    def test_record_decision_appends_step(self) -> None:
        engine = ExplainEngine()
        engine.create_trace(trace_id="t1")
        step = engine.record_decision(
            trace_id="t1",
            decision="allow",
            reason="safe",
            component="gov",
        )
        assert step.step_number == 1
        assert step.decision == "allow"

    def test_record_decision_missing_trace_raises(self) -> None:
        engine = ExplainEngine()
        with pytest.raises(KeyError, match="t1"):
            engine.record_decision(
                trace_id="t1", decision="x", reason="y"
            )

    def test_record_decision_finalized_trace_raises(self) -> None:
        engine = ExplainEngine()
        engine.create_trace(trace_id="t1")
        engine.finalize_trace("t1", outcome="done")
        with pytest.raises(RuntimeError, match="finalized"):
            engine.record_decision(
                trace_id="t1", decision="x", reason="y"
            )

    def test_finalize_trace_returns_trace(self) -> None:
        engine = ExplainEngine()
        engine.create_trace(trace_id="t1")
        result = engine.finalize_trace("t1", outcome="HALT")
        assert result is not None
        assert result.is_finalized is True
        assert result.outcome == "HALT"

    def test_finalize_trace_missing_returns_none(self) -> None:
        engine = ExplainEngine()
        assert engine.finalize_trace("missing") is None

    def test_explain_returns_human_readable(self) -> None:
        engine = ExplainEngine()
        engine.create_trace(trace_id="t1")
        engine.record_decision("t1", "allow", "safe", "gov")
        engine.finalize_trace("t1", outcome="PROCEED")
        text = engine.explain("t1")
        assert "t1" in text
        assert "allow" in text
        assert "PROCEED" in text

    def test_explain_missing_returns_empty(self) -> None:
        engine = ExplainEngine()
        assert engine.explain("missing") == ""

    def test_list_traces_returns_ids(self) -> None:
        engine = ExplainEngine()
        engine.create_trace(trace_id="a")
        engine.create_trace(trace_id="b")
        engine.create_trace(trace_id="c")
        ids = engine.list_traces()
        assert ids == ["a", "b", "c"]

    def test_list_traces_respects_limit(self) -> None:
        engine = ExplainEngine()
        for i in range(10):
            engine.create_trace(trace_id=f"t{i}")
        ids = engine.list_traces(limit=3)
        assert len(ids) == 3
        # Should return the last 3 (newest)
        assert ids == ["t7", "t8", "t9"]

    def test_list_traces_empty_engine(self) -> None:
        engine = ExplainEngine()
        assert engine.list_traces() == []

    def test_cleanup_evicts_oldest(self) -> None:
        engine = ExplainEngine(max_traces=3)
        engine.create_trace(trace_id="t1")
        engine.create_trace(trace_id="t2")
        engine.create_trace(trace_id="t3")
        # t1, t2, t3 exist
        engine.create_trace(trace_id="t4")
        # t1 should be evicted
        assert engine.get_trace("t1") is None
        assert engine.get_trace("t2") is not None
        assert engine.get_trace("t4") is not None

    def test_cleanup_returns_removed_count(self) -> None:
        engine = ExplainEngine(max_traces=2)
        engine.create_trace(trace_id="a")
        engine.create_trace(trace_id="b")
        # Next create triggers cleanup internally; call manually to test return
        engine.create_trace(trace_id="c")
        # After create, cleanup has already run. Calling again shows 0 excess.
        count = engine.cleanup()
        assert count == 0

    def test_cleanup_no_excess(self) -> None:
        engine = ExplainEngine(max_traces=100)
        engine.create_trace(trace_id="a")
        assert engine.cleanup() == 0

    def test_record_decision_with_evidence(self) -> None:
        engine = ExplainEngine()
        engine.create_trace(trace_id="t1")
        step = engine.record_decision(
            trace_id="t1",
            decision="block",
            reason="secret detected",
            evidence={"pattern": "AWS_KEY"},
        )
        assert step.evidence == {"pattern": "AWS_KEY"}

    def test_multiple_steps_multiple_traces(self) -> None:
        engine = ExplainEngine()
        engine.create_trace(trace_id="t1")
        engine.create_trace(trace_id="t2")
        engine.record_decision("t1", "d1", "r1")
        engine.record_decision("t1", "d2", "r2")
        engine.record_decision("t2", "d3", "r3")
        t1 = engine.get_trace("t1")
        t2 = engine.get_trace("t2")
        assert t1 is not None and len(t1.steps) == 2
        assert t2 is not None and len(t2.steps) == 1
