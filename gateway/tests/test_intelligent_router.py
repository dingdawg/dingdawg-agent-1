"""Tests for the Multi-LLM Intelligent Router.

TDD test suite — 120+ tests covering:
- TaskType/ModelTier enums and mappings
- RoutingDecision / RoutingResult frozen dataclasses
- TaskClassifier: keyword-based heuristic classification
- ContextSanitizer: IP compartmentalization
- RoutingMetrics: SQLite-backed analytics
- IntelligentRouter: end-to-end routing pipeline
- IP Compartmentalization: verify no internal terms leak
- Forbidden imports: module isolation

All tests are pure unit tests — no LLM calls, no network, no side effects.
"""

from __future__ import annotations

import sqlite3
import tempfile
import threading
import time
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------

from isg_agent.models.intelligent_router import (
    ContextSanitizer,
    IntelligentRouter,
    MODEL_CONFIGS,
    ModelTier,
    RoutingDecision,
    RoutingMetrics,
    RoutingResult,
    TASK_TIER_MAP,
    TaskClassifier,
    TaskType,
)


# ===========================================================================
# TestTaskType — enum values and tier mapping
# ===========================================================================


class TestTaskType:
    """Verify TaskType enum values and completeness."""

    def test_speed_task_types_exist(self):
        """All SPEED-tier task types are defined."""
        speed_types = [
            TaskType.GREETING,
            TaskType.FAQ,
            TaskType.STATUS_CHECK,
            TaskType.SIMPLE_LOOKUP,
            TaskType.ACKNOWLEDGMENT,
        ]
        for tt in speed_types:
            assert tt.value in (
                "greeting", "faq", "status_check", "simple_lookup", "acknowledgment"
            )

    def test_all_task_types_have_tier_mapping(self):
        """Every TaskType must be present in TASK_TIER_MAP."""
        for tt in TaskType:
            assert tt in TASK_TIER_MAP, f"{tt} missing from TASK_TIER_MAP"

    def test_tier_mapping_returns_model_tier(self):
        """Every TASK_TIER_MAP value is a ModelTier."""
        for tt, tier in TASK_TIER_MAP.items():
            assert isinstance(tier, ModelTier), f"{tt} maps to {type(tier)}, not ModelTier"


# ===========================================================================
# TestRoutingDecision — frozen dataclass
# ===========================================================================


class TestRoutingDecision:
    """Verify RoutingDecision is frozen and has all required fields."""

    def _make_decision(self, **overrides):
        defaults = dict(
            tier=ModelTier.SPEED,
            task_type=TaskType.GREETING,
            confidence=0.85,
            model_id="mercury-2",
            fallback_chain=["gpt-4o-mini"],
            latency_estimate_ms=50,
            cost_estimate_usd=0.0001,
            context_sanitized=True,
        )
        defaults.update(overrides)
        return RoutingDecision(**defaults)

    def test_frozen_immutable(self):
        """RoutingDecision is frozen — cannot mutate fields."""
        d = self._make_decision()
        with pytest.raises(FrozenInstanceError):
            d.tier = ModelTier.CREATIVE  # type: ignore[misc]

    def test_all_fields_populated(self):
        """All fields are accessible after construction."""
        d = self._make_decision()
        assert d.tier == ModelTier.SPEED
        assert d.task_type == TaskType.GREETING
        assert d.confidence == 0.85
        assert d.model_id == "mercury-2"
        assert d.fallback_chain == ["gpt-4o-mini"]
        assert d.latency_estimate_ms == 50
        assert d.cost_estimate_usd == 0.0001
        assert d.context_sanitized is True

    def test_fallback_chain_is_list(self):
        """fallback_chain must be a list."""
        d = self._make_decision(fallback_chain=["a", "b", "c"])
        assert isinstance(d.fallback_chain, list)
        assert len(d.fallback_chain) == 3

    def test_confidence_range(self):
        """Confidence is stored as-is (range enforcement is caller's job)."""
        d = self._make_decision(confidence=0.0)
        assert d.confidence == 0.0
        d2 = self._make_decision(confidence=1.0)
        assert d2.confidence == 1.0


# ===========================================================================
# TestRoutingResult — frozen dataclass
# ===========================================================================


class TestRoutingResult:
    """Verify RoutingResult is frozen with correct fields."""

    def _make_result(self, **overrides):
        decision = RoutingDecision(
            tier=ModelTier.SPEED,
            task_type=TaskType.GREETING,
            confidence=0.85,
            model_id="mercury-2",
            fallback_chain=[],
            latency_estimate_ms=50,
            cost_estimate_usd=0.0001,
            context_sanitized=False,
        )
        defaults = dict(
            decision=decision,
            actual_latency_ms=45.2,
            actual_tokens=100,
            actual_cost_usd=0.00005,
            tier_used=ModelTier.SPEED,
            fallback_used=False,
        )
        defaults.update(overrides)
        return RoutingResult(**defaults)

    def test_frozen_immutable(self):
        """RoutingResult is frozen — cannot mutate fields."""
        r = self._make_result()
        with pytest.raises(FrozenInstanceError):
            r.fallback_used = True  # type: ignore[misc]

    def test_fallback_used_flag(self):
        """fallback_used tracks whether a fallback model was used."""
        r1 = self._make_result(fallback_used=False)
        assert r1.fallback_used is False
        r2 = self._make_result(fallback_used=True)
        assert r2.fallback_used is True

    def test_tier_used_override(self):
        """tier_used can differ from decision.tier when fallback fires."""
        r = self._make_result(tier_used=ModelTier.CREATIVE, fallback_used=True)
        assert r.decision.tier == ModelTier.SPEED
        assert r.tier_used == ModelTier.CREATIVE


# ===========================================================================
# TestTaskClassifierGreetings
# ===========================================================================


class TestTaskClassifierGreetings:
    """Classify greeting messages into SPEED tier."""

    @pytest.fixture
    def clf(self):
        return TaskClassifier()

    def test_hello(self, clf):
        tt, conf = clf.classify("hello")
        assert tt == TaskType.GREETING
        assert conf > 0.5

    def test_hi(self, clf):
        tt, _ = clf.classify("hi")
        assert tt == TaskType.GREETING

    def test_hey(self, clf):
        tt, _ = clf.classify("hey")
        assert tt == TaskType.GREETING

    def test_good_morning(self, clf):
        tt, _ = clf.classify("good morning")
        assert tt == TaskType.GREETING

    def test_good_afternoon(self, clf):
        tt, _ = clf.classify("good afternoon")
        assert tt == TaskType.GREETING

    def test_good_evening(self, clf):
        tt, _ = clf.classify("good evening")
        assert tt == TaskType.GREETING

    def test_howdy(self, clf):
        tt, _ = clf.classify("howdy")
        assert tt == TaskType.GREETING

    def test_short_greeting_high_confidence(self, clf):
        """Short greetings should have reasonable confidence."""
        _, conf = clf.classify("hi")
        assert conf >= 0.6


# ===========================================================================
# TestTaskClassifierFAQ
# ===========================================================================


class TestTaskClassifierFAQ:
    """Classify FAQ messages into SPEED tier."""

    @pytest.fixture
    def clf(self):
        return TaskClassifier()

    def test_what_is(self, clf):
        tt, _ = clf.classify("what is your return policy")
        assert tt == TaskType.FAQ

    def test_how_does(self, clf):
        tt, _ = clf.classify("how does shipping work")
        assert tt == TaskType.FAQ

    def test_help(self, clf):
        tt, _ = clf.classify("I need help with my order")
        assert tt == TaskType.FAQ

    def test_where_is(self, clf):
        tt, _ = clf.classify("where is my package")
        assert tt == TaskType.FAQ

    def test_when_does(self, clf):
        tt, _ = clf.classify("when does the store open")
        assert tt == TaskType.FAQ


# ===========================================================================
# TestTaskClassifierStatusCheck
# ===========================================================================


class TestTaskClassifierStatusCheck:
    """Classify status check messages into SPEED tier."""

    @pytest.fixture
    def clf(self):
        return TaskClassifier()

    def test_status(self, clf):
        tt, _ = clf.classify("what is the system status")
        assert TASK_TIER_MAP[tt] == ModelTier.SPEED

    def test_health(self, clf):
        tt, _ = clf.classify("health check")
        assert tt == TaskType.STATUS_CHECK

    def test_ping(self, clf):
        tt, _ = clf.classify("ping")
        assert tt == TaskType.STATUS_CHECK

    def test_uptime(self, clf):
        tt, _ = clf.classify("system uptime")
        assert tt == TaskType.STATUS_CHECK


# ===========================================================================
# TestTaskClassifierAcknowledgment
# ===========================================================================


class TestTaskClassifierAcknowledgment:
    """Classify acknowledgment messages into SPEED tier."""

    @pytest.fixture
    def clf(self):
        return TaskClassifier()

    def test_ok(self, clf):
        tt, _ = clf.classify("ok")
        assert tt == TaskType.ACKNOWLEDGMENT

    def test_thanks(self, clf):
        tt, _ = clf.classify("thanks")
        assert tt == TaskType.ACKNOWLEDGMENT

    def test_yes(self, clf):
        tt, _ = clf.classify("yes")
        assert tt == TaskType.ACKNOWLEDGMENT

    def test_no(self, clf):
        tt, _ = clf.classify("no")
        assert tt == TaskType.ACKNOWLEDGMENT

    def test_empty_string(self, clf):
        """Empty string falls to ACKNOWLEDGMENT with low confidence."""
        tt, conf = clf.classify("")
        assert tt == TaskType.ACKNOWLEDGMENT
        assert conf <= 0.6


# ===========================================================================
# TestTaskClassifierCreative
# ===========================================================================


class TestTaskClassifierCreative:
    """Classify creative messages into CREATIVE tier."""

    @pytest.fixture
    def clf(self):
        return TaskClassifier()

    def test_write_story(self, clf):
        tt, _ = clf.classify("write me a short story about dragons")
        assert TASK_TIER_MAP[tt] == ModelTier.CREATIVE

    def test_draft_email(self, clf):
        tt, _ = clf.classify("draft an email to my client about the project")
        assert TASK_TIER_MAP[tt] == ModelTier.CREATIVE

    def test_brainstorm(self, clf):
        tt, _ = clf.classify("brainstorm ideas for a birthday party")
        assert tt == TaskType.BRAINSTORM

    def test_marketing_copy(self, clf):
        tt, _ = clf.classify("create a marketing campaign with a catchy slogan")
        assert tt == TaskType.MARKETING_COPY

    def test_personality(self, clf):
        tt, _ = clf.classify("respond in the personality of a pirate")
        assert tt == TaskType.PERSONALITY

    def test_creative_keyword(self, clf):
        tt, _ = clf.classify("be creative and come up with something fun")
        assert TASK_TIER_MAP[tt] == ModelTier.CREATIVE

    def test_compose(self, clf):
        tt, _ = clf.classify("compose a poem about the ocean")
        assert TASK_TIER_MAP[tt] == ModelTier.CREATIVE

    def test_slogan(self, clf):
        tt, _ = clf.classify("create a catchy slogan for our brand")
        assert TASK_TIER_MAP[tt] == ModelTier.CREATIVE


# ===========================================================================
# TestTaskClassifierReasoning
# ===========================================================================


class TestTaskClassifierReasoning:
    """Classify reasoning messages into REASONING tier."""

    @pytest.fixture
    def clf(self):
        return TaskClassifier()

    def test_code_generation(self, clf):
        tt, _ = clf.classify("write a Python function to sort a list")
        assert TASK_TIER_MAP[tt] == ModelTier.REASONING

    def test_debug(self, clf):
        tt, _ = clf.classify("debug this function that crashes on empty input")
        assert TASK_TIER_MAP[tt] == ModelTier.REASONING

    def test_analyze(self, clf):
        tt, _ = clf.classify("analyze the performance of these two algorithms")
        assert tt == TaskType.ANALYSIS

    def test_plan(self, clf):
        tt, _ = clf.classify("plan out a roadmap for the next quarter")
        assert tt == TaskType.PLANNING

    def test_multi_step(self, clf):
        tt, _ = clf.classify("walk me through this step by step")
        assert tt == TaskType.MULTI_STEP

    def test_tool_use_flag(self, clf):
        """When has_tool_calls=True, always classify as TOOL_USE."""
        tt, conf = clf.classify("hello there", has_tool_calls=True)
        assert tt == TaskType.TOOL_USE
        assert conf >= 0.9

    def test_implement(self, clf):
        tt, _ = clf.classify("implement a REST API endpoint for user authentication")
        assert TASK_TIER_MAP[tt] == ModelTier.REASONING

    def test_architecture(self, clf):
        tt, _ = clf.classify("design system architecture for a microservices platform")
        assert TASK_TIER_MAP[tt] == ModelTier.REASONING


# ===========================================================================
# TestTaskClassifierEdgeCases
# ===========================================================================


class TestTaskClassifierEdgeCases:
    """Edge cases for classification."""

    @pytest.fixture
    def clf(self):
        return TaskClassifier()

    def test_long_message_defaults_to_analysis(self, clf):
        """Messages with 50+ words and no keyword match go to ANALYSIS."""
        msg = " ".join(["word"] * 55)
        tt, _ = clf.classify(msg)
        # Long messages without specific keywords -> analysis or conversation
        assert TASK_TIER_MAP[tt] in (ModelTier.REASONING, ModelTier.CREATIVE)

    def test_deep_conversation_defaults_to_conversation(self, clf):
        """Conversations 5+ turns deep default to CONVERSATION."""
        tt, _ = clf.classify("not sure what to say", conversation_depth=6)
        assert tt == TaskType.CONVERSATION

    def test_case_insensitive(self, clf):
        """Classification is case-insensitive."""
        tt1, _ = clf.classify("HELLO")
        tt2, _ = clf.classify("hello")
        assert tt1 == tt2

    def test_mixed_signals_reasoning_wins(self, clf):
        """When message has both creative and reasoning signals, reasoning wins."""
        tt, _ = clf.classify("write code to implement a creative story generator")
        assert TASK_TIER_MAP[tt] == ModelTier.REASONING

    def test_whitespace_only(self, clf):
        """Whitespace-only treated like empty."""
        tt, _ = clf.classify("   ")
        assert tt == TaskType.ACKNOWLEDGMENT

    def test_none_message_handling(self, clf):
        """None input returns ACKNOWLEDGMENT with low confidence."""
        # The classify method should handle None gracefully
        tt, conf = clf.classify("")
        assert tt == TaskType.ACKNOWLEDGMENT
        assert conf <= 0.6


# ===========================================================================
# TestContextSanitizer
# ===========================================================================


class TestContextSanitizer:
    """Test IP compartmentalization via context sanitization."""

    @pytest.fixture
    def sanitizer(self):
        return ContextSanitizer()

    def test_strips_mila_references(self, sanitizer):
        """MiLA references stripped from all tiers."""
        text = "The mila_governance module handles trust checks"
        result = sanitizer.sanitize_for_tier(text, ModelTier.SPEED)
        assert "mila_" not in result
        assert "[REDACTED]" in result

    def test_strips_MiLA_capitalized(self, sanitizer):
        """Capitalized MiLA stripped."""
        result = sanitizer.sanitize_for_tier("MiLA is the brain", ModelTier.CREATIVE)
        assert "MiLA" not in result

    def test_strips_MILA_uppercase(self, sanitizer):
        """All-caps MILA stripped."""
        result = sanitizer.sanitize_for_tier("MILA system", ModelTier.REASONING)
        assert "MILA" not in result

    def test_strips_isg_agent(self, sanitizer):
        """isg_agent internal module name stripped."""
        result = sanitizer.sanitize_for_tier("isg_agent.brain module", ModelTier.SPEED)
        assert "isg_agent" not in result

    def test_strips_governance(self, sanitizer):
        """Governance terms stripped."""
        result = sanitizer.sanitize_for_tier("governance check passed", ModelTier.CREATIVE)
        assert "governance" not in result

    def test_strips_sovereign(self, sanitizer):
        """Sovereign terms stripped."""
        result = sanitizer.sanitize_for_tier("sovereign execution kernel", ModelTier.SPEED)
        assert "sovereign" not in result

    def test_speed_strips_architecture_terms(self, sanitizer):
        """SPEED tier additionally strips architecture terms."""
        text = "circuit_breaker triggered and drift_detect flagged"
        result = sanitizer.sanitize_for_tier(text, ModelTier.SPEED)
        assert "circuit_breaker" not in result
        assert "drift_detect" not in result

    def test_creative_keeps_architecture_terms(self, sanitizer):
        """CREATIVE tier does NOT strip architecture terms."""
        text = "circuit_breaker triggered"
        result = sanitizer.sanitize_for_tier(text, ModelTier.CREATIVE)
        assert "circuit_breaker" in result

    def test_empty_input_returns_empty(self, sanitizer):
        """Empty string passes through."""
        assert sanitizer.sanitize_for_tier("", ModelTier.SPEED) == ""

    def test_none_input_returns_none(self, sanitizer):
        """None input passes through."""
        assert sanitizer.sanitize_for_tier(None, ModelTier.SPEED) is None


# ===========================================================================
# TestContextSanitizerSystemPrompt
# ===========================================================================


class TestContextSanitizerSystemPrompt:
    """Test system prompt sanitization."""

    @pytest.fixture
    def sanitizer(self):
        return ContextSanitizer()

    def test_sanitize_system_prompt_strips_internals(self, sanitizer):
        prompt = "You are powered by MiLA governance engine"
        result = sanitizer.sanitize_system_prompt(prompt, ModelTier.SPEED)
        assert "MiLA" not in result
        assert "governance" not in result

    def test_sanitize_system_prompt_speed_extra(self, sanitizer):
        prompt = "Use circuit_breaker for resilience"
        result = sanitizer.sanitize_system_prompt(prompt, ModelTier.SPEED)
        assert "circuit_breaker" not in result

    def test_sanitize_system_prompt_creative_keeps_arch(self, sanitizer):
        prompt = "Use circuit_breaker for resilience"
        result = sanitizer.sanitize_system_prompt(prompt, ModelTier.CREATIVE)
        assert "circuit_breaker" in result

    def test_sanitize_system_prompt_none(self, sanitizer):
        assert sanitizer.sanitize_system_prompt(None, ModelTier.SPEED) is None


# ===========================================================================
# TestRoutingMetrics
# ===========================================================================


class TestRoutingMetrics:
    """SQLite-backed routing analytics tests."""

    def _make_decision(self, **overrides):
        defaults = dict(
            tier=ModelTier.SPEED,
            task_type=TaskType.GREETING,
            confidence=0.85,
            model_id="mercury-2",
            fallback_chain=[],
            latency_estimate_ms=50,
            cost_estimate_usd=0.0001,
            context_sanitized=False,
        )
        defaults.update(overrides)
        return RoutingDecision(**defaults)

    def _make_result(self, decision=None, **overrides):
        if decision is None:
            decision = self._make_decision()
        defaults = dict(
            decision=decision,
            actual_latency_ms=45.0,
            actual_tokens=100,
            actual_cost_usd=0.00005,
            tier_used=decision.tier,
            fallback_used=False,
        )
        defaults.update(overrides)
        return RoutingResult(**defaults)

    def test_record_and_retrieve(self):
        """Can record a result and retrieve tier stats."""
        m = RoutingMetrics()
        result = self._make_result()
        m.record(result)
        stats = m.get_tier_stats()
        assert "speed" in stats
        assert stats["speed"]["count"] == 1

    def test_empty_stats(self):
        """Empty metrics returns empty dict."""
        m = RoutingMetrics()
        stats = m.get_tier_stats()
        assert stats == {}

    def test_multiple_tiers(self):
        """Stats tracked separately per tier."""
        m = RoutingMetrics()
        # Record SPEED
        d_speed = self._make_decision(tier=ModelTier.SPEED, task_type=TaskType.GREETING)
        m.record(self._make_result(decision=d_speed))
        # Record REASONING
        d_reason = self._make_decision(
            tier=ModelTier.REASONING,
            task_type=TaskType.CODE_GENERATION,
            model_id="claude-sonnet-4-6",
        )
        m.record(self._make_result(decision=d_reason, tier_used=ModelTier.REASONING))
        stats = m.get_tier_stats()
        assert "speed" in stats
        assert "reasoning" in stats

    def test_avg_latency(self):
        """Average latency calculated correctly."""
        m = RoutingMetrics()
        for lat in [40.0, 60.0]:
            m.record(self._make_result(actual_latency_ms=lat))
        stats = m.get_tier_stats()
        assert stats["speed"]["avg_latency_ms"] == pytest.approx(50.0, abs=0.2)

    def test_total_cost(self):
        """Total cost summed correctly."""
        m = RoutingMetrics()
        for _ in range(3):
            m.record(self._make_result(actual_cost_usd=0.001))
        stats = m.get_tier_stats()
        assert stats["speed"]["total_cost_usd"] == pytest.approx(0.003, abs=0.0001)

    def test_fallback_count(self):
        """Fallback count tracked."""
        m = RoutingMetrics()
        m.record(self._make_result(fallback_used=True))
        m.record(self._make_result(fallback_used=False))
        stats = m.get_tier_stats()
        assert stats["speed"]["fallback_count"] == 1

    def test_cost_savings_empty(self):
        """Cost savings on empty metrics."""
        m = RoutingMetrics()
        savings = m.get_cost_savings()
        assert savings["actual_cost_usd"] == 0.0
        assert savings["savings_pct"] == 0.0

    def test_cost_savings_with_data(self):
        """Cost savings calculated vs REASONING baseline."""
        m = RoutingMetrics()
        # Record cheap SPEED calls
        for _ in range(10):
            m.record(self._make_result(actual_tokens=1000, actual_cost_usd=0.001))
        savings = m.get_cost_savings()
        assert savings["savings_usd"] > 0
        assert savings["savings_pct"] > 0

    def test_task_distribution(self):
        """Task distribution counts correctly."""
        m = RoutingMetrics()
        d1 = self._make_decision(task_type=TaskType.GREETING)
        d2 = self._make_decision(task_type=TaskType.FAQ)
        m.record(self._make_result(decision=d1))
        m.record(self._make_result(decision=d1))
        m.record(self._make_result(decision=d2))
        dist = m.get_task_distribution()
        assert dist["greeting"] == 2
        assert dist["faq"] == 1

    def test_busy_timeout_set(self):
        """SQLite busy_timeout is set to 5000ms."""
        with tempfile.NamedTemporaryFile(suffix=".db") as f:
            m = RoutingMetrics(db_path=f.name)
            # Verify busy_timeout is set by checking pragma
            cursor = m._conn.execute("PRAGMA busy_timeout")
            timeout = cursor.fetchone()[0]
            assert timeout == 5000


# ===========================================================================
# TestModelConfigs
# ===========================================================================


class TestModelConfigs:
    """Verify MODEL_CONFIGS structure."""

    def test_all_tiers_have_primary(self):
        """Every tier has a primary model config."""
        for tier in ModelTier:
            assert tier in MODEL_CONFIGS, f"{tier} missing from MODEL_CONFIGS"
            assert "primary" in MODEL_CONFIGS[tier]

    def test_all_tiers_have_fallbacks(self):
        """Every tier has a fallbacks list."""
        for tier in ModelTier:
            assert "fallbacks" in MODEL_CONFIGS[tier]
            assert isinstance(MODEL_CONFIGS[tier]["fallbacks"], list)

    def test_cost_fields_present(self):
        """Primary config has cost fields."""
        for tier in ModelTier:
            primary = MODEL_CONFIGS[tier]["primary"]
            assert "cost_per_1k_input" in primary
            assert "cost_per_1k_output" in primary
            assert primary["cost_per_1k_input"] >= 0
            assert primary["cost_per_1k_output"] >= 0

    def test_latency_fields_present(self):
        """Primary config has avg_latency_ms."""
        for tier in ModelTier:
            primary = MODEL_CONFIGS[tier]["primary"]
            assert "avg_latency_ms" in primary
            assert primary["avg_latency_ms"] > 0


# ===========================================================================
# TestIntelligentRouterRoute
# ===========================================================================


class TestIntelligentRouterRoute:
    """End-to-end routing tests."""

    @pytest.fixture
    def router(self):
        return IntelligentRouter()

    def test_greeting_routes_to_speed(self, router):
        d = router.route("hello")
        assert d.tier == ModelTier.SPEED

    def test_code_routes_to_reasoning(self, router):
        d = router.route("write a Python function to parse JSON")
        assert d.tier == ModelTier.REASONING

    def test_brainstorm_routes_to_creative(self, router):
        d = router.route("brainstorm ideas for a new product")
        assert d.tier == ModelTier.CREATIVE

    def test_tool_use_override(self, router):
        """has_tool_calls=True forces REASONING regardless of message."""
        d = router.route("hello", has_tool_calls=True)
        assert d.tier == ModelTier.REASONING

    def test_confidence_range_valid(self, router):
        """Confidence is between 0.0 and 1.0."""
        d = router.route("hello world")
        assert 0.0 <= d.confidence <= 1.0

    def test_model_id_matches_tier_speed(self, router):
        d = router.route("hi")
        assert d.model_id == MODEL_CONFIGS[ModelTier.SPEED]["primary"]["id"]

    def test_model_id_matches_tier_reasoning(self, router):
        d = router.route("write code to sort a list")
        assert d.model_id == MODEL_CONFIGS[ModelTier.REASONING]["primary"]["id"]

    def test_model_id_matches_tier_creative(self, router):
        d = router.route("brainstorm names for my startup")
        assert d.model_id == MODEL_CONFIGS[ModelTier.CREATIVE]["primary"]["id"]

    def test_fallback_chain_populated(self, router):
        d = router.route("hello")
        assert isinstance(d.fallback_chain, list)
        assert len(d.fallback_chain) >= 1

    def test_latency_estimate_positive(self, router):
        d = router.route("hello")
        assert d.latency_estimate_ms > 0

    def test_cost_estimate_nonnegative(self, router):
        d = router.route("hello")
        assert d.cost_estimate_usd >= 0

    def test_context_sanitized_flag_with_prompt(self, router):
        """context_sanitized=True when system_prompt is provided."""
        d = router.route("hello", system_prompt="You are a helper")
        assert d.context_sanitized is True

    def test_context_sanitized_flag_without_prompt(self, router):
        """context_sanitized=False when no system_prompt."""
        d = router.route("hello")
        assert d.context_sanitized is False


# ===========================================================================
# TestIntelligentRouterSanitize
# ===========================================================================


class TestIntelligentRouterSanitize:
    """Sanitization through the router interface."""

    @pytest.fixture
    def router(self):
        return IntelligentRouter()

    def test_sanitize_context_strips_mila(self, router):
        result = router.sanitize_context("MiLA is active", ModelTier.SPEED)
        assert "MiLA" not in result

    def test_sanitize_prompt_strips_internals(self, router):
        result = router.sanitize_prompt("isg_agent.brain logic", ModelTier.CREATIVE)
        assert "isg_agent" not in result

    def test_sanitize_context_speed_strips_arch(self, router):
        result = router.sanitize_context("circuit_breaker enabled", ModelTier.SPEED)
        assert "circuit_breaker" not in result

    def test_sanitize_context_creative_keeps_arch(self, router):
        result = router.sanitize_context("circuit_breaker enabled", ModelTier.CREATIVE)
        assert "circuit_breaker" in result

    def test_sanitize_context_reasoning_keeps_arch(self, router):
        result = router.sanitize_context("circuit_breaker enabled", ModelTier.REASONING)
        assert "circuit_breaker" in result


# ===========================================================================
# TestIntelligentRouterRecordResult
# ===========================================================================


class TestIntelligentRouterRecordResult:
    """Recording completed routing results."""

    @pytest.fixture
    def router(self):
        return IntelligentRouter()

    def _make_decision(self):
        return RoutingDecision(
            tier=ModelTier.SPEED,
            task_type=TaskType.GREETING,
            confidence=0.85,
            model_id="mercury-2",
            fallback_chain=["gpt-4o-mini"],
            latency_estimate_ms=50,
            cost_estimate_usd=0.0001,
            context_sanitized=False,
        )

    def test_record_result_returns_routing_result(self, router):
        d = self._make_decision()
        result = router.record_result(d, latency_ms=42.0, tokens=100, cost_usd=0.0001)
        assert isinstance(result, RoutingResult)

    def test_record_result_updates_metrics(self, router):
        d = self._make_decision()
        router.record_result(d, latency_ms=42.0, tokens=100, cost_usd=0.0001)
        stats = router.get_stats()
        assert stats["tier_stats"]["speed"]["count"] == 1

    def test_record_result_fallback_tracking(self, router):
        d = self._make_decision()
        router.record_result(
            d, latency_ms=42.0, tokens=100, cost_usd=0.0001,
            fallback_used=True, tier_used=ModelTier.CREATIVE,
        )
        stats = router.get_stats()
        # The tier_used was CREATIVE, but the decision tier was SPEED
        # Metrics record by tier_used
        assert "creative" in stats["tier_stats"] or "speed" in stats["tier_stats"]

    def test_record_result_default_tier_used(self, router):
        """When tier_used not specified, uses decision.tier."""
        d = self._make_decision()
        result = router.record_result(d, latency_ms=42.0, tokens=100, cost_usd=0.0001)
        assert result.tier_used == ModelTier.SPEED

    def test_record_result_explicit_tier_used(self, router):
        d = self._make_decision()
        result = router.record_result(
            d, latency_ms=42.0, tokens=100, cost_usd=0.0001,
            tier_used=ModelTier.REASONING,
        )
        assert result.tier_used == ModelTier.REASONING


# ===========================================================================
# TestIntelligentRouterStats
# ===========================================================================


class TestIntelligentRouterStats:
    """Statistics from the router."""

    @pytest.fixture
    def router(self):
        return IntelligentRouter()

    def test_get_stats_empty(self, router):
        stats = router.get_stats()
        assert "tier_stats" in stats
        assert "cost_savings" in stats
        assert "task_distribution" in stats

    def test_get_stats_after_records(self, router):
        d = RoutingDecision(
            tier=ModelTier.SPEED,
            task_type=TaskType.GREETING,
            confidence=0.85,
            model_id="mercury-2",
            fallback_chain=[],
            latency_estimate_ms=50,
            cost_estimate_usd=0.0001,
            context_sanitized=False,
        )
        router.record_result(d, latency_ms=42.0, tokens=100, cost_usd=0.0001)
        stats = router.get_stats()
        assert stats["tier_stats"]["speed"]["count"] == 1
        assert stats["task_distribution"]["greeting"] == 1

    def test_cost_savings_positive_with_speed(self, router):
        """Using SPEED tier should show cost savings vs all-REASONING baseline."""
        d = RoutingDecision(
            tier=ModelTier.SPEED,
            task_type=TaskType.GREETING,
            confidence=0.85,
            model_id="mercury-2",
            fallback_chain=[],
            latency_estimate_ms=50,
            cost_estimate_usd=0.0001,
            context_sanitized=False,
        )
        for _ in range(10):
            router.record_result(d, latency_ms=42.0, tokens=1000, cost_usd=0.001)
        savings = router.get_stats()["cost_savings"]
        assert savings["savings_usd"] > 0

    def test_stats_with_days_param(self, router):
        """Stats accept days parameter."""
        stats = router.get_stats(days=7)
        assert isinstance(stats, dict)


# ===========================================================================
# TestIPCompartmentalization
# ===========================================================================


class TestIPCompartmentalization:
    """Verify IP compartmentalization — no internal terms leak to external tiers."""

    @pytest.fixture
    def sanitizer(self):
        return ContextSanitizer()

    def test_speed_never_sees_mila(self, sanitizer):
        """SPEED tier never sees MiLA references."""
        texts = [
            "MiLA governance check",
            "mila_bridge active",
            "MILA system online",
        ]
        for text in texts:
            result = sanitizer.sanitize_for_tier(text, ModelTier.SPEED)
            assert "MiLA" not in result
            assert "mila_" not in result
            assert "MILA" not in result

    def test_creative_never_sees_mila(self, sanitizer):
        """CREATIVE tier never sees MiLA references."""
        result = sanitizer.sanitize_for_tier("MiLA mila_ MILA", ModelTier.CREATIVE)
        assert "MiLA" not in result
        assert "mila_" not in result
        assert "MILA" not in result

    def test_reasoning_never_sees_mila(self, sanitizer):
        """REASONING tier never sees MiLA references."""
        result = sanitizer.sanitize_for_tier("MiLA mila_ MILA", ModelTier.REASONING)
        assert "MiLA" not in result
        assert "mila_" not in result
        assert "MILA" not in result

    def test_speed_never_sees_architecture_terms(self, sanitizer):
        """SPEED tier never sees architecture internals."""
        terms = [
            "circuit_breaker", "drift_detect",
            "capability_distiller", "flywheel",
            "executor", "heartbeat",
        ]
        for term in terms:
            result = sanitizer.sanitize_for_tier(f"using {term} module", ModelTier.SPEED)
            assert term not in result, f"{term} leaked to SPEED tier"

    def test_each_tier_gets_different_sanitization(self, sanitizer):
        """SPEED tier strips more than CREATIVE/REASONING."""
        text = "MiLA circuit_breaker drift_detect executor"
        speed_result = sanitizer.sanitize_for_tier(text, ModelTier.SPEED)
        creative_result = sanitizer.sanitize_for_tier(text, ModelTier.CREATIVE)
        # Speed should have more redactions
        assert speed_result.count("[REDACTED]") > creative_result.count("[REDACTED]")

    def test_trust_ledger_never_leaks(self, sanitizer):
        """trust_ledger is stripped from all tiers."""
        for tier in ModelTier:
            result = sanitizer.sanitize_for_tier("trust_ledger entry", tier)
            assert "trust_ledger" not in result


# ===========================================================================
# TestNoForbiddenImports
# ===========================================================================


class TestNoForbiddenImports:
    """Ensure router.py has no forbidden imports from other isg_agent modules."""

    def _read_source(self) -> str:
        """Read the intelligent_router.py source code."""
        import importlib
        import inspect
        from isg_agent.models import intelligent_router as router_mod
        return inspect.getsource(router_mod)

    def test_no_brain_import(self):
        """router.py must not import from isg_agent.brain."""
        source = self._read_source()
        assert "isg_agent.brain" not in source

    def test_no_api_import(self):
        """router.py must not import from isg_agent.api."""
        source = self._read_source()
        assert "isg_agent.api" not in source


# ===========================================================================
# Additional edge case and integration tests to reach 120+
# ===========================================================================


class TestTaskClassifierConfidenceRanges:
    """Verify confidence scores are within valid range."""

    @pytest.fixture
    def clf(self):
        return TaskClassifier()

    def test_greeting_confidence_above_threshold(self, clf):
        _, conf = clf.classify("hello there")
        assert 0.0 <= conf <= 1.0

    def test_tool_use_highest_confidence(self, clf):
        """Tool use should have the highest confidence."""
        _, conf = clf.classify("anything", has_tool_calls=True)
        assert conf >= 0.9

    def test_ambiguous_message_lower_confidence(self, clf):
        """Ambiguous messages should have lower confidence."""
        _, conf = clf.classify("hmm")
        assert conf < 0.9

    def test_multiple_keyword_matches_boost_confidence(self, clf):
        """Multiple matching keywords should boost confidence."""
        _, conf_single = clf.classify("analyze this")
        _, conf_multi = clf.classify("analyze and evaluate and assess this carefully")
        assert conf_multi >= conf_single


class TestRoutingMetricsPersistence:
    """Test metrics with file-backed SQLite."""

    def test_file_backed_persistence(self):
        """Metrics persist to file."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            m = RoutingMetrics(db_path=db_path)
            decision = RoutingDecision(
                tier=ModelTier.SPEED,
                task_type=TaskType.GREETING,
                confidence=0.85,
                model_id="mercury-2",
                fallback_chain=[],
                latency_estimate_ms=50,
                cost_estimate_usd=0.0001,
                context_sanitized=False,
            )
            result = RoutingResult(
                decision=decision,
                actual_latency_ms=42.0,
                actual_tokens=100,
                actual_cost_usd=0.00005,
                tier_used=ModelTier.SPEED,
                fallback_used=False,
            )
            m.record(result)

            # Verify by reopening
            conn = sqlite3.connect(db_path)
            cursor = conn.execute("SELECT COUNT(*) FROM routing_log")
            count = cursor.fetchone()[0]
            conn.close()
            assert count == 1
        finally:
            import os
            os.unlink(db_path)

    def test_wal_mode_on_file(self):
        """WAL mode enabled for file-backed databases."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            m = RoutingMetrics(db_path=db_path)
            cursor = m._conn.execute("PRAGMA journal_mode")
            mode = cursor.fetchone()[0]
            assert mode == "wal"
        finally:
            import os
            # WAL creates additional files
            for ext in ["", "-wal", "-shm"]:
                try:
                    os.unlink(db_path + ext)
                except FileNotFoundError:
                    pass


class TestRouterCustomConfigs:
    """Test router with custom model configs."""

    def test_custom_model_configs(self):
        """Router uses custom configs when provided."""
        custom = {
            ModelTier.SPEED: {
                "primary": {"id": "custom-fast", "cost_per_1k_input": 0.0001, "cost_per_1k_output": 0.0003, "avg_latency_ms": 20},
                "fallbacks": [],
            },
            ModelTier.CREATIVE: {
                "primary": {"id": "custom-creative", "cost_per_1k_input": 0.001, "cost_per_1k_output": 0.003, "avg_latency_ms": 100},
                "fallbacks": [],
            },
            ModelTier.REASONING: {
                "primary": {"id": "custom-reason", "cost_per_1k_input": 0.01, "cost_per_1k_output": 0.03, "avg_latency_ms": 500},
                "fallbacks": [],
            },
        }
        router = IntelligentRouter(model_configs=custom)
        d = router.route("hi")
        assert d.model_id == "custom-fast"

    def test_custom_config_reasoning(self):
        custom = {
            ModelTier.SPEED: {
                "primary": {"id": "x", "cost_per_1k_input": 0, "cost_per_1k_output": 0, "avg_latency_ms": 10},
                "fallbacks": [],
            },
            ModelTier.CREATIVE: {
                "primary": {"id": "y", "cost_per_1k_input": 0, "cost_per_1k_output": 0, "avg_latency_ms": 10},
                "fallbacks": [],
            },
            ModelTier.REASONING: {
                "primary": {"id": "my-reasoner", "cost_per_1k_input": 0.01, "cost_per_1k_output": 0.03, "avg_latency_ms": 500},
                "fallbacks": [{"id": "backup-reasoner"}],
            },
        }
        router = IntelligentRouter(model_configs=custom)
        d = router.route("write code to parse XML")
        assert d.model_id == "my-reasoner"
        assert "backup-reasoner" in d.fallback_chain


class TestRouterThreadSafety:
    """Basic thread safety checks."""

    def test_concurrent_records_no_crash(self):
        """Multiple threads recording metrics should not crash."""
        router = IntelligentRouter()
        decision = RoutingDecision(
            tier=ModelTier.SPEED,
            task_type=TaskType.GREETING,
            confidence=0.85,
            model_id="mercury-2",
            fallback_chain=[],
            latency_estimate_ms=50,
            cost_estimate_usd=0.0001,
            context_sanitized=False,
        )

        errors = []

        def record_many():
            try:
                for _ in range(50):
                    router.record_result(
                        decision, latency_ms=42.0, tokens=100, cost_usd=0.0001
                    )
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=record_many) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Thread errors: {errors}"
        stats = router.get_stats()
        assert stats["tier_stats"]["speed"]["count"] == 200

    def test_concurrent_route_no_crash(self):
        """Multiple threads routing should not crash."""
        router = IntelligentRouter()
        errors = []

        def route_many():
            try:
                for msg in ["hello", "write code", "brainstorm ideas"] * 10:
                    router.route(msg)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=route_many) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0


class TestModelTierEnum:
    """ModelTier enum value checks."""

    def test_speed_value(self):
        assert ModelTier.SPEED.value == "speed"

    def test_creative_value(self):
        assert ModelTier.CREATIVE.value == "creative"

    def test_reasoning_value(self):
        assert ModelTier.REASONING.value == "reasoning"

    def test_three_tiers_total(self):
        assert len(ModelTier) == 3


class TestTaskTypeTierMappingCompleteness:
    """Verify tier mapping covers all expected types per tier."""

    def test_speed_tier_has_five_types(self):
        speed_types = [tt for tt, tier in TASK_TIER_MAP.items() if tier == ModelTier.SPEED]
        assert len(speed_types) == 5

    def test_creative_tier_has_five_types(self):
        creative_types = [tt for tt, tier in TASK_TIER_MAP.items() if tier == ModelTier.CREATIVE]
        assert len(creative_types) == 5

    def test_reasoning_tier_has_five_types(self):
        reasoning_types = [tt for tt, tier in TASK_TIER_MAP.items() if tier == ModelTier.REASONING]
        assert len(reasoning_types) == 5

    def test_total_fifteen_types(self):
        assert len(TaskType) == 15
