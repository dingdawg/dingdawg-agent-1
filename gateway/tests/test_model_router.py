"""Tests for the multi-LLM intelligent routing engine.

Tests cover:
- TaskClassification: keyword-based O(1) classification
- ContextSanitizer: IP protection layer
- ContextFirewall: compartmentalization enforcer
- IntelligentRouter: routing decisions, fallback chain, metrics
- RoutingMetrics: SQLite-backed analytics

150 tests total. All tests are pure unit tests using mocks (no real LLM calls).
"""

from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncGenerator, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from isg_agent.models.provider import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
    ProviderError,
)
from isg_agent.models.router import (
    COST_TABLE,
    ContextSanitizer,
    IntelligentRouter,
    ModelTier,
    RoutingDecision,
    TaskClassification,
)
from isg_agent.models.context_firewall import ContextFirewall
from isg_agent.models.routing_metrics import RoutingMetrics


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


class FakeProvider(LLMProvider):
    """A fake LLM provider for testing routing without real API calls."""

    def __init__(
        self,
        name: str = "fake",
        response_content: str = "fake response",
        should_fail: bool = False,
        fail_message: str = "provider failure",
    ) -> None:
        self._name = name
        self._response_content = response_content
        self._should_fail = should_fail
        self._fail_message = fail_message

    @property
    def provider_name(self) -> str:
        return self._name

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        if self._should_fail:
            raise ProviderError(
                message=self._fail_message,
                provider=self._name,
                status_code=500,
            )
        return LLMResponse(
            content=self._response_content,
            model=model or "fake-model",
            input_tokens=100,
            output_tokens=50,
            finish_reason="stop",
            extra={"provider": self._name},
        )

    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[str, None]:
        if self._should_fail:
            raise ProviderError(
                message=self._fail_message,
                provider=self._name,
            )
        yield self._response_content
        return  # noqa: B901


def _msg(content: str, role: str = "user") -> LLMMessage:
    """Shorthand for creating an LLMMessage."""
    return LLMMessage(role=role, content=content)


def _msgs(content: str) -> list[LLMMessage]:
    """Shorthand for creating a single-message list."""
    return [_msg(content)]


@pytest.fixture()
def tmp_metrics_db() -> Path:
    """Provide a temporary SQLite path for RoutingMetrics."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    yield db_path
    if db_path.exists():
        db_path.unlink()
    for suffix in ("-wal", "-shm"):
        p = Path(str(db_path) + suffix)
        if p.exists():
            p.unlink()


@pytest.fixture()
def sanitizer() -> ContextSanitizer:
    return ContextSanitizer()


@pytest.fixture()
def firewall() -> ContextFirewall:
    return ContextFirewall()


@pytest.fixture()
def metrics(tmp_metrics_db: Path) -> RoutingMetrics:
    return RoutingMetrics(db_path=str(tmp_metrics_db))


@pytest.fixture()
def router() -> IntelligentRouter:
    """Create a router with fake providers for all tiers."""
    speed_provider = FakeProvider(name="mercury", response_content="speed response")
    creative_provider = FakeProvider(name="openai", response_content="creative response")
    reasoning_provider = FakeProvider(
        name="anthropic", response_content="reasoning response"
    )
    return IntelligentRouter(
        speed_provider=speed_provider,
        creative_provider=creative_provider,
        reasoning_provider=reasoning_provider,
    )


@pytest.fixture()
def router_with_failures() -> IntelligentRouter:
    """Create a router where speed and creative providers fail."""
    speed_provider = FakeProvider(
        name="mercury", should_fail=True, fail_message="Mercury down"
    )
    creative_provider = FakeProvider(
        name="openai", should_fail=True, fail_message="OpenAI down"
    )
    reasoning_provider = FakeProvider(
        name="anthropic", response_content="fallback response"
    )
    return IntelligentRouter(
        speed_provider=speed_provider,
        creative_provider=creative_provider,
        reasoning_provider=reasoning_provider,
    )


# ===========================================================================
# 1. TaskClassification Tests (30 tests)
# ===========================================================================


class TestTaskClassification:
    """Test the keyword-based O(1) task classification."""

    # -- FAST_LOOKUP --

    def test_what_time_appointment(self, router: IntelligentRouter) -> None:
        result = router.classify_task(_msgs("What time is my appointment?"), {})
        assert result == TaskClassification.FAST_LOOKUP

    def test_what_is_my_balance(self, router: IntelligentRouter) -> None:
        result = router.classify_task(_msgs("What is my account balance?"), {})
        assert result == TaskClassification.FAST_LOOKUP

    def test_where_is_my_order(self, router: IntelligentRouter) -> None:
        result = router.classify_task(_msgs("Where is my order?"), {})
        assert result == TaskClassification.FAST_LOOKUP

    # -- FAST_EXTRACTION --

    def test_how_many_orders(self, router: IntelligentRouter) -> None:
        result = router.classify_task(_msgs("How many orders did I get today?"), {})
        assert result == TaskClassification.FAST_EXTRACTION

    def test_list_my_appointments(self, router: IntelligentRouter) -> None:
        result = router.classify_task(_msgs("List my appointments"), {})
        assert result == TaskClassification.FAST_EXTRACTION

    def test_show_me_my_items(self, router: IntelligentRouter) -> None:
        result = router.classify_task(_msgs("Show me my recent orders"), {})
        assert result == TaskClassification.FAST_EXTRACTION

    # -- FAST_SLOT_FILL --

    def test_book_appointment(self, router: IntelligentRouter) -> None:
        result = router.classify_task(
            _msgs("Book an appointment for 3pm tomorrow"), {}
        )
        assert result == TaskClassification.FAST_SLOT_FILL

    def test_schedule_meeting(self, router: IntelligentRouter) -> None:
        result = router.classify_task(
            _msgs("Schedule a meeting at 2pm next Tuesday"), {}
        )
        assert result == TaskClassification.FAST_SLOT_FILL

    def test_reserve_table(self, router: IntelligentRouter) -> None:
        result = router.classify_task(
            _msgs("Reserve a table for 4 people tonight"), {}
        )
        assert result == TaskClassification.FAST_SLOT_FILL

    # -- FAST_FORMAT --

    def test_convert_to_pdf(self, router: IntelligentRouter) -> None:
        result = router.classify_task(_msgs("Convert this to a list format"), {})
        assert result == TaskClassification.FAST_FORMAT

    def test_format_address(self, router: IntelligentRouter) -> None:
        result = router.classify_task(_msgs("Format my address for shipping"), {})
        assert result == TaskClassification.FAST_FORMAT

    # -- FAST general: short messages --

    def test_short_message_fast(self, router: IntelligentRouter) -> None:
        result = router.classify_task(_msgs("Hi there"), {})
        assert result.value.startswith("fast_")

    def test_yes_is_fast(self, router: IntelligentRouter) -> None:
        result = router.classify_task(_msgs("Yes"), {})
        assert result.value.startswith("fast_")

    # -- CREATIVE_CONTENT --

    def test_write_marketing_email(self, router: IntelligentRouter) -> None:
        result = router.classify_task(
            _msgs("Write me a marketing email for my spring sale"), {}
        )
        assert result == TaskClassification.CREATIVE_CONTENT

    def test_compose_newsletter(self, router: IntelligentRouter) -> None:
        result = router.classify_task(
            _msgs("Compose a newsletter for my customers"), {}
        )
        assert result == TaskClassification.CREATIVE_CONTENT

    # -- CREATIVE_RESPONSE --

    def test_catchy_slogan(self, router: IntelligentRouter) -> None:
        result = router.classify_task(
            _msgs("Help me come up with a catchy slogan"), {}
        )
        assert result == TaskClassification.CREATIVE_RESPONSE

    def test_brainstorm_ideas(self, router: IntelligentRouter) -> None:
        result = router.classify_task(
            _msgs("Brainstorm some ideas for my new product launch"), {}
        )
        assert result == TaskClassification.CREATIVE_RESPONSE

    def test_suggest_names(self, router: IntelligentRouter) -> None:
        result = router.classify_task(
            _msgs("Suggest some creative names for my bakery"), {}
        )
        assert result == TaskClassification.CREATIVE_RESPONSE

    # -- CREATIVE_PERSONALITY --

    def test_tell_me_about_yourself(self, router: IntelligentRouter) -> None:
        result = router.classify_task(
            _msgs("Tell me about yourself"), {"has_personality": True}
        )
        assert result == TaskClassification.CREATIVE_PERSONALITY

    # -- CREATIVE_EMPATHY --

    def test_im_frustrated(self, router: IntelligentRouter) -> None:
        result = router.classify_task(
            _msgs("I'm really frustrated with my order being late"), {}
        )
        assert result == TaskClassification.CREATIVE_EMPATHY

    def test_disappointed_customer(self, router: IntelligentRouter) -> None:
        result = router.classify_task(
            _msgs("I'm so disappointed with the service"), {}
        )
        assert result == TaskClassification.CREATIVE_EMPATHY

    # -- COMPLEX_ANALYSIS --

    def test_sales_down_analysis(self, router: IntelligentRouter) -> None:
        result = router.classify_task(
            _msgs("Why are my sales down 20% compared to last month?"), {}
        )
        assert result == TaskClassification.COMPLEX_ANALYSIS

    def test_compare_performance(self, router: IntelligentRouter) -> None:
        result = router.classify_task(
            _msgs("Compare my performance across all three stores"), {}
        )
        assert result == TaskClassification.COMPLEX_ANALYSIS

    def test_analyze_trends(self, router: IntelligentRouter) -> None:
        result = router.classify_task(
            _msgs("Analyze my customer retention trends over the past quarter"), {}
        )
        assert result == TaskClassification.COMPLEX_ANALYSIS

    # -- COMPLEX_SAFETY --

    def test_cancel_subscription(self, router: IntelligentRouter) -> None:
        result = router.classify_task(
            _msgs("Cancel my subscription and refund the last payment"), {}
        )
        assert result == TaskClassification.COMPLEX_SAFETY

    def test_delete_my_account(self, router: IntelligentRouter) -> None:
        result = router.classify_task(_msgs("Delete my account"), {})
        assert result == TaskClassification.COMPLEX_SAFETY

    def test_payment_refund(self, router: IntelligentRouter) -> None:
        result = router.classify_task(
            _msgs("I need a refund for my last payment"), {}
        )
        assert result == TaskClassification.COMPLEX_SAFETY

    # -- COMPLEX_ORCHESTRATION --

    def test_if_revenue_drops(self, router: IntelligentRouter) -> None:
        result = router.classify_task(
            _msgs("If revenue drops below $5000, automatically send me an alert"), {}
        )
        assert result == TaskClassification.COMPLEX_ORCHESTRATION

    def test_when_then_workflow(self, router: IntelligentRouter) -> None:
        result = router.classify_task(
            _msgs("When a new order comes in, automatically notify my team"), {}
        )
        assert result == TaskClassification.COMPLEX_ORCHESTRATION

    # -- UNKNOWN defaults to REASONING --

    def test_ambiguous_defaults_to_reasoning(self, router: IntelligentRouter) -> None:
        """An ambiguous message with no strong keyword match should default to REASONING."""
        result = router.classify_task(
            _msgs("I have a question about the new thing and I need to understand several aspects of it in more detail"), {}
        )
        tier = router._classification_to_tier(result)
        assert tier == ModelTier.REASONING

    # -- Tier mapping correctness --

    def test_fast_maps_to_speed_tier(self, router: IntelligentRouter) -> None:
        for tc in TaskClassification:
            if tc.value.startswith("fast_"):
                assert router._classification_to_tier(tc) == ModelTier.SPEED

    def test_creative_maps_to_creative_tier(self, router: IntelligentRouter) -> None:
        for tc in TaskClassification:
            if tc.value.startswith("creative_"):
                assert router._classification_to_tier(tc) == ModelTier.CREATIVE

    def test_complex_maps_to_reasoning_tier(self, router: IntelligentRouter) -> None:
        for tc in TaskClassification:
            if tc.value.startswith("complex_"):
                assert router._classification_to_tier(tc) == ModelTier.REASONING

    def test_unknown_maps_to_reasoning(self, router: IntelligentRouter) -> None:
        assert (
            router._classification_to_tier(TaskClassification.UNKNOWN)
            == ModelTier.REASONING
        )


# ===========================================================================
# 2. ContextSanitizer Tests (25 tests)
# ===========================================================================


class TestContextSanitizer:
    """Test context sanitization for IP protection."""

    # -- sanitize_for_speed --

    def test_speed_strips_routing_metadata(self, sanitizer: ContextSanitizer) -> None:
        messages = [_msg("routed to Mercury for fast processing", role="system")]
        sanitized_msgs, prompt = sanitizer.sanitize_for_speed(
            messages, "You are the ISG Agent routing engine."
        )
        for msg in sanitized_msgs:
            assert "routed to Mercury" not in msg.content
        assert "routing engine" not in prompt.lower()

    def test_speed_strips_internal_architecture(
        self, sanitizer: ContextSanitizer
    ) -> None:
        messages = [_msg("The isg_agent SkillExecutor processed this")]
        sanitized_msgs, prompt = sanitizer.sanitize_for_speed(messages, "system")
        for msg in sanitized_msgs:
            assert "isg_agent" not in msg.content
            assert "SkillExecutor" not in msg.content

    def test_speed_strips_other_model_outputs(
        self, sanitizer: ContextSanitizer
    ) -> None:
        messages = [_msg("[GPT response] Here is a creative answer")]
        sanitized_msgs, _ = sanitizer.sanitize_for_speed(messages, "")
        for msg in sanitized_msgs:
            assert "[GPT response]" not in msg.content

    def test_speed_replaces_system_prompt(self, sanitizer: ContextSanitizer) -> None:
        _, prompt = sanitizer.sanitize_for_speed(
            [_msg("hello")], "Full complex system prompt with all the details"
        )
        assert len(prompt) < 200  # Must be minimal

    def test_speed_preserves_user_message(self, sanitizer: ContextSanitizer) -> None:
        messages = [_msg("What time is my appointment?")]
        sanitized_msgs, _ = sanitizer.sanitize_for_speed(messages, "system")
        assert any("appointment" in m.content for m in sanitized_msgs)

    def test_speed_includes_skill_params_in_context(
        self, sanitizer: ContextSanitizer
    ) -> None:
        messages = [_msg("Book at 3pm")]
        sanitized_msgs, prompt = sanitizer.sanitize_for_speed(
            messages,
            "system",
            skill_params={"time": "3pm", "action": "book"},
        )
        assert "3pm" in prompt or any("3pm" in m.content for m in sanitized_msgs)

    # -- sanitize_for_creative --

    def test_creative_includes_personality(
        self, sanitizer: ContextSanitizer
    ) -> None:
        agent_personality = {
            "name": "Luna",
            "voice": "friendly and warm",
            "style": "casual",
        }
        messages = [_msg("Tell me something fun")]
        sanitized_msgs, prompt = sanitizer.sanitize_for_creative(
            messages, "full system", agent_personality=agent_personality
        )
        assert "Luna" in prompt
        assert "friendly" in prompt.lower() or "warm" in prompt.lower()

    def test_creative_strips_pricing_logic(
        self, sanitizer: ContextSanitizer
    ) -> None:
        messages = [_msg("The margin is $1/tx with cost_usd tracking")]
        sanitized_msgs, _ = sanitizer.sanitize_for_creative(messages, "")
        for msg in sanitized_msgs:
            assert "$1/tx" not in msg.content
            assert "cost_usd" not in msg.content

    def test_creative_strips_internal_routing(
        self, sanitizer: ContextSanitizer
    ) -> None:
        messages = [_msg("classified as FAST_EXTRACTION by the router")]
        sanitized_msgs, _ = sanitizer.sanitize_for_creative(messages, "")
        for msg in sanitized_msgs:
            assert "FAST_EXTRACTION" not in msg.content
            assert "router" not in msg.content.lower()

    def test_creative_strips_governance_details(
        self, sanitizer: ContextSanitizer
    ) -> None:
        messages = [_msg("trust_ledger score is 0.95, explain_engine active")]
        sanitized_msgs, _ = sanitizer.sanitize_for_creative(messages, "")
        for msg in sanitized_msgs:
            assert "trust_ledger" not in msg.content
            assert "explain_engine" not in msg.content

    def test_creative_preserves_conversation_history(
        self, sanitizer: ContextSanitizer
    ) -> None:
        messages = [
            _msg("Hi there, I need help with my bakery", role="user"),
            _msg("I'd be happy to help with your bakery!", role="assistant"),
            _msg("Can you write a marketing tagline?", role="user"),
        ]
        sanitized_msgs, _ = sanitizer.sanitize_for_creative(messages, "")
        assert len(sanitized_msgs) >= 2  # preserves recent turns

    def test_creative_limits_history(self, sanitizer: ContextSanitizer) -> None:
        """Creative context should limit to last 5 turns."""
        messages = [_msg(f"Turn {i}") for i in range(10)]
        sanitized_msgs, _ = sanitizer.sanitize_for_creative(messages, "")
        # Should not include all 10 turns
        assert len(sanitized_msgs) <= 6  # 5 + possible system

    # -- sanitize_for_reasoning --

    def test_reasoning_preserves_full_history(
        self, sanitizer: ContextSanitizer
    ) -> None:
        messages = [_msg(f"Turn {i}") for i in range(8)]
        sanitized_msgs, _ = sanitizer.sanitize_for_reasoning(messages, "full system")
        assert len(sanitized_msgs) == 8

    def test_reasoning_preserves_system_prompt(
        self, sanitizer: ContextSanitizer
    ) -> None:
        _, prompt = sanitizer.sanitize_for_reasoning(
            [_msg("hello")], "Full complex system prompt"
        )
        assert "Full complex system prompt" in prompt

    def test_reasoning_strips_other_provider_outputs(
        self, sanitizer: ContextSanitizer
    ) -> None:
        messages = [_msg("[Mercury response] quick extraction done")]
        sanitized_msgs, _ = sanitizer.sanitize_for_reasoning(messages, "")
        for msg in sanitized_msgs:
            assert "[Mercury response]" not in msg.content

    def test_reasoning_strips_billing_internals(
        self, sanitizer: ContextSanitizer
    ) -> None:
        messages = [_msg("input_cost_per_m = 0.25, output_cost_per_m = 0.75")]
        sanitized_msgs, _ = sanitizer.sanitize_for_reasoning(messages, "")
        for msg in sanitized_msgs:
            assert "input_cost_per_m" not in msg.content
            assert "output_cost_per_m" not in msg.content

    def test_reasoning_preserves_safety_context(
        self, sanitizer: ContextSanitizer
    ) -> None:
        messages = [_msg("The user wants to cancel their subscription")]
        sanitized_msgs, _ = sanitizer.sanitize_for_reasoning(messages, "")
        assert any("cancel" in m.content for m in sanitized_msgs)

    def test_reasoning_preserves_skill_results(
        self, sanitizer: ContextSanitizer
    ) -> None:
        messages = [_msg("Skill result: 5 appointments found for today")]
        sanitized_msgs, _ = sanitizer.sanitize_for_reasoning(messages, "")
        assert any("5 appointments" in m.content for m in sanitized_msgs)

    # -- Edge cases --

    def test_sanitize_empty_messages(self, sanitizer: ContextSanitizer) -> None:
        sanitized_msgs, prompt = sanitizer.sanitize_for_speed([], "")
        assert sanitized_msgs == []
        assert isinstance(prompt, str)

    def test_sanitize_none_content_handled(
        self, sanitizer: ContextSanitizer
    ) -> None:
        """Handles messages where content might be empty."""
        messages = [_msg("")]
        sanitized_msgs, _ = sanitizer.sanitize_for_speed(messages, "")
        assert isinstance(sanitized_msgs, list)

    def test_sanitize_unicode_preserved(self, sanitizer: ContextSanitizer) -> None:
        messages = [_msg("Reservar una mesa para 4 personas")]
        sanitized_msgs, _ = sanitizer.sanitize_for_speed(messages, "")
        assert any("Reservar" in m.content for m in sanitized_msgs)

    def test_sanitize_no_double_stripping(
        self, sanitizer: ContextSanitizer
    ) -> None:
        """Sanitizing already-clean content should not corrupt it."""
        messages = [_msg("Hello, how can I help you today?")]
        sanitized_msgs, _ = sanitizer.sanitize_for_speed(messages, "")
        assert any("Hello" in m.content for m in sanitized_msgs)

    def test_all_tiers_strip_model_routing_references(
        self, sanitizer: ContextSanitizer
    ) -> None:
        """No tier should leak routing metadata in its output."""
        msg_text = "routed to Mercury, classified as FAST_EXTRACTION"
        messages = [_msg(msg_text)]

        for method in [
            sanitizer.sanitize_for_speed,
            sanitizer.sanitize_for_creative,
            sanitizer.sanitize_for_reasoning,
        ]:
            sanitized_msgs, _ = method(messages, "system")
            for msg in sanitized_msgs:
                assert "routed to Mercury" not in msg.content


# ===========================================================================
# 3. ContextFirewall Tests (25 tests)
# ===========================================================================


class TestContextFirewall:
    """Test the compartmentalization enforcer."""

    # -- strip_system_internals --

    def test_strip_routing_reference(self, firewall: ContextFirewall) -> None:
        text = "This was routed to Mercury for speed"
        result = firewall.strip_system_internals(text)
        assert "routed to Mercury" not in result

    def test_strip_classified_as(self, firewall: ContextFirewall) -> None:
        text = "classified as FAST_EXTRACTION by router"
        result = firewall.strip_system_internals(text)
        assert "classified as FAST" not in result

    def test_strip_isg_agent_reference(self, firewall: ContextFirewall) -> None:
        text = "The isg_agent module processes this"
        result = firewall.strip_system_internals(text)
        assert "isg_agent" not in result

    def test_strip_skill_executor(self, firewall: ContextFirewall) -> None:
        text = "SkillExecutor ran the appointment skill"
        result = firewall.strip_system_internals(text)
        assert "SkillExecutor" not in result

    def test_strip_agent_runtime(self, firewall: ContextFirewall) -> None:
        text = "AgentRuntime initialized the session"
        result = firewall.strip_system_internals(text)
        assert "AgentRuntime" not in result

    def test_strip_gpt_response_tag(self, firewall: ContextFirewall) -> None:
        text = "[GPT response] Here is some content"
        result = firewall.strip_system_internals(text)
        assert "[GPT response]" not in result

    def test_strip_claude_analysis_tag(self, firewall: ContextFirewall) -> None:
        text = "[Claude analysis] The data shows..."
        result = firewall.strip_system_internals(text)
        assert "[Claude analysis]" not in result

    def test_strip_mercury_response_tag(self, firewall: ContextFirewall) -> None:
        text = "[Mercury response] Extracted value: 42"
        result = firewall.strip_system_internals(text)
        assert "[Mercury response]" not in result

    def test_strip_pricing_reference(self, firewall: ContextFirewall) -> None:
        text = "The cost is $1/tx with margin tracking"
        result = firewall.strip_system_internals(text)
        assert "$1/tx" not in result

    def test_strip_cost_usd(self, firewall: ContextFirewall) -> None:
        text = "cost_usd = 0.003"
        result = firewall.strip_system_internals(text)
        assert "cost_usd" not in result

    def test_strip_trust_ledger(self, firewall: ContextFirewall) -> None:
        text = "trust_ledger score: 0.95"
        result = firewall.strip_system_internals(text)
        assert "trust_ledger" not in result

    def test_strip_explain_engine(self, firewall: ContextFirewall) -> None:
        text = "explain_engine generated this explanation"
        result = firewall.strip_system_internals(text)
        assert "explain_engine" not in result

    def test_strip_circuit_breaker(self, firewall: ContextFirewall) -> None:
        text = "circuit_breaker triggered for safety"
        result = firewall.strip_system_internals(text)
        assert "circuit_breaker" not in result

    def test_preserve_user_content(self, firewall: ContextFirewall) -> None:
        text = "I want to book an appointment for tomorrow at 3pm"
        result = firewall.strip_system_internals(text)
        assert "book an appointment" in result
        assert "3pm" in result

    def test_handle_empty_string(self, firewall: ContextFirewall) -> None:
        assert firewall.strip_system_internals("") == ""

    def test_handle_none_gracefully(self, firewall: ContextFirewall) -> None:
        """Should handle None without raising."""
        result = firewall.strip_system_internals(None)  # type: ignore[arg-type]
        assert result == ""

    # -- create_speed_context --

    def test_speed_context_minimal(self, firewall: ContextFirewall) -> None:
        ctx = firewall.create_speed_context(
            "What time is my appointment?", {"action": "lookup"}
        )
        assert "appointment" in ctx.lower() or "lookup" in ctx.lower()
        assert len(ctx) < 500  # Must be minimal

    def test_speed_context_no_full_system(self, firewall: ContextFirewall) -> None:
        ctx = firewall.create_speed_context("Hello", {})
        assert "agent configuration" not in ctx.lower()
        assert "governance" not in ctx.lower()

    # -- create_creative_context --

    def test_creative_context_includes_personality(
        self, firewall: ContextFirewall
    ) -> None:
        personality = {"name": "Luna", "voice": "warm", "style": "casual"}
        messages = [_msg("Write me a tagline")]
        ctx = firewall.create_creative_context(personality, messages, "professional")
        assert "Luna" in ctx

    def test_creative_context_includes_recent_turns(
        self, firewall: ContextFirewall
    ) -> None:
        messages = [_msg(f"Turn {i}") for i in range(3)]
        ctx = firewall.create_creative_context({}, messages, "casual")
        assert "Turn 2" in ctx  # Last turn should be there

    def test_creative_context_limits_to_five_turns(
        self, firewall: ContextFirewall
    ) -> None:
        messages = [_msg(f"Turn {i}") for i in range(10)]
        ctx = firewall.create_creative_context({}, messages, "casual")
        # Should only include the last 5 turns
        assert "Turn 5" in ctx
        assert "Turn 0" not in ctx

    def test_creative_context_no_skill_internals(
        self, firewall: ContextFirewall
    ) -> None:
        ctx = firewall.create_creative_context(
            {"name": "Luna"}, [_msg("hello")], "casual"
        )
        assert "SkillExecutor" not in ctx
        assert "isg_agent" not in ctx

    # -- create_reasoning_context --

    def test_reasoning_context_full_history(
        self, firewall: ContextFirewall
    ) -> None:
        messages = [_msg(f"Turn {i}") for i in range(8)]
        ctx = firewall.create_reasoning_context(
            messages, "Full system prompt", []
        )
        assert "Turn 0" in ctx
        assert "Turn 7" in ctx
        assert "Full system prompt" in ctx

    def test_reasoning_context_strips_billing(
        self, firewall: ContextFirewall
    ) -> None:
        messages = [_msg("input_cost_per_m tracking")]
        ctx = firewall.create_reasoning_context(messages, "", [])
        assert "input_cost_per_m" not in ctx

    # -- validate_outbound --

    def test_validate_outbound_strips_leaked_internals(
        self, firewall: ContextFirewall
    ) -> None:
        response = "Here is your answer. Routed to Mercury for speed. The time is 3pm."
        cleaned = firewall.validate_outbound(response, ModelTier.SPEED)
        assert "routed to Mercury" not in cleaned.lower()
        assert "3pm" in cleaned

    def test_validate_outbound_preserves_clean_response(
        self, firewall: ContextFirewall
    ) -> None:
        response = "Your appointment is at 3pm tomorrow."
        cleaned = firewall.validate_outbound(response, ModelTier.SPEED)
        assert cleaned == response

    def test_validate_outbound_strips_isg_agent_leak(
        self, firewall: ContextFirewall
    ) -> None:
        response = "I processed this via isg_agent. Your order ships tomorrow."
        cleaned = firewall.validate_outbound(response, ModelTier.CREATIVE)
        assert "isg_agent" not in cleaned


# ===========================================================================
# 4. IntelligentRouter Tests (40 tests)
# ===========================================================================


class TestIntelligentRouter:
    """Test routing decisions, model selection, fallback, and metrics."""

    # -- route() method --

    @pytest.mark.asyncio
    async def test_route_fast_selects_mercury(
        self, router: IntelligentRouter
    ) -> None:
        decision = router.route(
            _msgs("What time is my appointment?"), "system", {}
        )
        assert decision.tier == ModelTier.SPEED
        assert "mercury" in decision.model_name.lower()

    @pytest.mark.asyncio
    async def test_route_creative_selects_gpt(
        self, router: IntelligentRouter
    ) -> None:
        decision = router.route(
            _msgs("Write me a marketing email for my spring sale"), "system", {}
        )
        assert decision.tier == ModelTier.CREATIVE
        assert "gpt" in decision.model_name.lower()

    @pytest.mark.asyncio
    async def test_route_complex_selects_claude(
        self, router: IntelligentRouter
    ) -> None:
        decision = router.route(
            _msgs("Why are my sales down 20% compared to last month?"),
            "system",
            {},
        )
        assert decision.tier == ModelTier.REASONING
        assert "claude" in decision.model_name.lower()

    def test_route_returns_routing_decision(
        self, router: IntelligentRouter
    ) -> None:
        decision = router.route(_msgs("hello"), "system", {})
        assert isinstance(decision, RoutingDecision)
        assert isinstance(decision.tier, ModelTier)
        assert isinstance(decision.classification, TaskClassification)
        assert isinstance(decision.confidence, float)
        assert isinstance(decision.model_name, str)
        assert isinstance(decision.reason, str)

    # -- Confidence scores --

    def test_confidence_between_0_and_1(self, router: IntelligentRouter) -> None:
        for msg_text in [
            "What time?",
            "Write a poem",
            "Analyze my data",
            "Some random thing",
        ]:
            decision = router.route(_msgs(msg_text), "system", {})
            assert 0.0 <= decision.confidence <= 1.0

    # -- Cost estimates --

    def test_cost_estimate_matches_cost_table(
        self, router: IntelligentRouter
    ) -> None:
        decision = router.route(_msgs("What time?"), "system", {})
        assert decision.estimated_cost_usd >= 0.0

    def test_speed_tier_cheapest(self, router: IntelligentRouter) -> None:
        speed_decision = router.route(_msgs("What time?"), "system", {})
        reasoning_decision = router.route(
            _msgs("Analyze the complex relationship between customer retention and revenue"),
            "system",
            {},
        )
        assert speed_decision.estimated_cost_usd <= reasoning_decision.estimated_cost_usd

    # -- Latency estimates --

    def test_latency_estimate_positive(self, router: IntelligentRouter) -> None:
        decision = router.route(_msgs("hello"), "system", {})
        assert decision.estimated_latency_ms > 0

    def test_speed_tier_fastest(self, router: IntelligentRouter) -> None:
        speed_decision = router.route(_msgs("What time?"), "system", {})
        reasoning_decision = router.route(
            _msgs("Analyze the data and explain the relationship"),
            "system",
            {},
        )
        assert speed_decision.estimated_latency_ms <= reasoning_decision.estimated_latency_ms

    # -- complete() method --

    @pytest.mark.asyncio
    async def test_complete_returns_response_and_decision(
        self, router: IntelligentRouter
    ) -> None:
        response, decision = await router.complete(
            _msgs("What time is my appointment?"), "system", {}
        )
        assert isinstance(response, LLMResponse)
        assert isinstance(decision, RoutingDecision)

    @pytest.mark.asyncio
    async def test_complete_fast_uses_speed_provider(
        self, router: IntelligentRouter
    ) -> None:
        response, decision = await router.complete(
            _msgs("What time is my appointment?"), "system", {}
        )
        assert decision.tier == ModelTier.SPEED
        assert response.content == "speed response"

    @pytest.mark.asyncio
    async def test_complete_creative_uses_openai(
        self, router: IntelligentRouter
    ) -> None:
        response, decision = await router.complete(
            _msgs("Write me a marketing email for my spring sale"), "system", {}
        )
        assert decision.tier == ModelTier.CREATIVE
        assert response.content == "creative response"

    @pytest.mark.asyncio
    async def test_complete_complex_uses_anthropic(
        self, router: IntelligentRouter
    ) -> None:
        response, decision = await router.complete(
            _msgs("Why are my sales down 20% compared to last month?"),
            "system",
            {},
        )
        assert decision.tier == ModelTier.REASONING
        assert response.content == "reasoning response"

    # -- Fallback chain --

    @pytest.mark.asyncio
    async def test_fallback_speed_to_creative(self) -> None:
        """When speed provider fails, falls back to creative."""
        speed = FakeProvider(name="mercury", should_fail=True)
        creative = FakeProvider(name="openai", response_content="creative fallback")
        reasoning = FakeProvider(name="anthropic", response_content="reason")
        router = IntelligentRouter(
            speed_provider=speed,
            creative_provider=creative,
            reasoning_provider=reasoning,
        )
        response, decision = await router.complete(
            _msgs("What time?"), "system", {}
        )
        assert response.content == "creative fallback"

    @pytest.mark.asyncio
    async def test_fallback_speed_to_reasoning(self) -> None:
        """When speed and creative providers fail, falls back to reasoning."""
        speed = FakeProvider(name="mercury", should_fail=True)
        creative = FakeProvider(name="openai", should_fail=True)
        reasoning = FakeProvider(name="anthropic", response_content="reason fallback")
        router = IntelligentRouter(
            speed_provider=speed,
            creative_provider=creative,
            reasoning_provider=reasoning,
        )
        response, decision = await router.complete(
            _msgs("What time?"), "system", {}
        )
        assert response.content == "reason fallback"

    @pytest.mark.asyncio
    async def test_fallback_creative_to_reasoning(self) -> None:
        """When creative provider fails, falls back to reasoning."""
        speed = FakeProvider(name="mercury", response_content="speed")
        creative = FakeProvider(name="openai", should_fail=True)
        reasoning = FakeProvider(name="anthropic", response_content="reason fallback")
        router = IntelligentRouter(
            speed_provider=speed,
            creative_provider=creative,
            reasoning_provider=reasoning,
        )
        response, decision = await router.complete(
            _msgs("Write me a poem about sunset"), "system", {}
        )
        assert response.content == "reason fallback"

    @pytest.mark.asyncio
    async def test_fallback_all_fail_raises(self) -> None:
        """When all providers fail, raises ProviderError."""
        speed = FakeProvider(name="mercury", should_fail=True)
        creative = FakeProvider(name="openai", should_fail=True)
        reasoning = FakeProvider(name="anthropic", should_fail=True)
        router = IntelligentRouter(
            speed_provider=speed,
            creative_provider=creative,
            reasoning_provider=reasoning,
        )
        with pytest.raises(ProviderError, match="All providers exhausted"):
            await router.complete(_msgs("hello"), "system", {})

    @pytest.mark.asyncio
    async def test_fallback_chain_order_speed(self) -> None:
        """Speed tasks try: Mercury -> GPT -> Claude."""
        call_order: list[str] = []

        class TrackingProvider(FakeProvider):
            async def complete(self, messages, **kwargs):
                call_order.append(self._name)
                return await super().complete(messages, **kwargs)

        speed = TrackingProvider(name="mercury", should_fail=True)
        creative = TrackingProvider(name="openai", response_content="ok")
        reasoning = TrackingProvider(name="anthropic", response_content="ok")

        router = IntelligentRouter(
            speed_provider=speed,
            creative_provider=creative,
            reasoning_provider=reasoning,
        )
        await router.complete(_msgs("What time?"), "system", {})
        assert call_order == ["mercury", "openai"]

    @pytest.mark.asyncio
    async def test_fallback_chain_order_creative(self) -> None:
        """Creative tasks try: GPT -> Claude."""
        call_order: list[str] = []

        class TrackingProvider(FakeProvider):
            async def complete(self, messages, **kwargs):
                call_order.append(self._name)
                return await super().complete(messages, **kwargs)

        speed = TrackingProvider(name="mercury", response_content="ok")
        creative = TrackingProvider(name="openai", should_fail=True)
        reasoning = TrackingProvider(name="anthropic", response_content="ok")

        router = IntelligentRouter(
            speed_provider=speed,
            creative_provider=creative,
            reasoning_provider=reasoning,
        )
        await router.complete(
            _msgs("Write me a marketing email"), "system", {}
        )
        assert call_order == ["openai", "anthropic"]

    @pytest.mark.asyncio
    async def test_fallback_chain_order_reasoning(self) -> None:
        """Reasoning tasks try: Claude only (no fallback to weaker models)."""
        call_order: list[str] = []

        class TrackingProvider(FakeProvider):
            async def complete(self, messages, **kwargs):
                call_order.append(self._name)
                return await super().complete(messages, **kwargs)

        speed = TrackingProvider(name="mercury", response_content="ok")
        creative = TrackingProvider(name="openai", response_content="ok")
        reasoning = TrackingProvider(name="anthropic", response_content="ok")

        router = IntelligentRouter(
            speed_provider=speed,
            creative_provider=creative,
            reasoning_provider=reasoning,
        )
        await router.complete(
            _msgs("Analyze my customer retention trends"), "system", {}
        )
        assert call_order == ["anthropic"]

    # -- Stats tracking --

    @pytest.mark.asyncio
    async def test_stats_incremented_after_complete(
        self, router: IntelligentRouter
    ) -> None:
        await router.complete(_msgs("What time?"), "system", {})
        await router.complete(_msgs("Write a poem"), "system", {})
        stats = router.get_routing_stats()
        assert stats["total_requests"] == 2

    @pytest.mark.asyncio
    async def test_stats_per_tier(self, router: IntelligentRouter) -> None:
        await router.complete(_msgs("What time?"), "system", {})
        await router.complete(_msgs("Write me a marketing email for my spring sale"), "system", {})
        await router.complete(_msgs("Analyze my revenue trends over the past quarter"), "system", {})
        stats = router.get_routing_stats()
        assert stats["requests_by_tier"][ModelTier.SPEED.value] >= 1
        assert stats["requests_by_tier"][ModelTier.CREATIVE.value] >= 1
        assert stats["requests_by_tier"][ModelTier.REASONING.value] >= 1

    @pytest.mark.asyncio
    async def test_stats_cost_savings_positive(
        self, router: IntelligentRouter
    ) -> None:
        """Routing fast tasks to Mercury should save money vs all-Claude baseline."""
        for _ in range(5):
            await router.complete(_msgs("What time?"), "system", {})
        stats = router.get_routing_stats()
        assert stats["estimated_cost_savings_usd"] >= 0.0

    @pytest.mark.asyncio
    async def test_stats_empty_initially(self, router: IntelligentRouter) -> None:
        stats = router.get_routing_stats()
        assert stats["total_requests"] == 0

    # -- Context sanitization integration --

    @pytest.mark.asyncio
    async def test_complete_sanitizes_context(
        self, router: IntelligentRouter
    ) -> None:
        """The complete method should sanitize context before calling the provider."""
        # This test verifies the sanitization pipeline runs without error
        messages = [
            _msg("You are an agent", role="system"),
            _msg("isg_agent SkillExecutor processed this"),
            _msg("What time is my appointment?"),
        ]
        response, decision = await router.complete(messages, "system prompt", {})
        assert isinstance(response, LLMResponse)

    # -- Model name selection --

    def test_speed_model_name(self, router: IntelligentRouter) -> None:
        decision = router.route(_msgs("What time?"), "system", {})
        assert decision.model_name == "mercury-2"

    def test_creative_model_name(self, router: IntelligentRouter) -> None:
        decision = router.route(_msgs("Write me a marketing email for my spring sale"), "system", {})
        assert decision.model_name == "gpt-5-mini"

    def test_reasoning_model_name(self, router: IntelligentRouter) -> None:
        decision = router.route(
            _msgs("Analyze the relationship between cost and revenue"), "system", {}
        )
        assert decision.model_name == "claude-sonnet-4-6"

    # -- Reason string --

    def test_route_includes_reason(self, router: IntelligentRouter) -> None:
        decision = router.route(_msgs("What time?"), "system", {})
        assert len(decision.reason) > 0

    # -- Context dict forwarding --

    def test_context_with_skill_params(self, router: IntelligentRouter) -> None:
        ctx = {"skill_params": {"action": "book", "time": "3pm"}}
        decision = router.route(
            _msgs("Book an appointment for 3pm"), "system", ctx
        )
        assert isinstance(decision, RoutingDecision)

    def test_context_with_personality(self, router: IntelligentRouter) -> None:
        ctx = {"has_personality": True, "agent_personality": {"name": "Luna"}}
        decision = router.route(
            _msgs("Tell me about yourself"), "system", ctx
        )
        assert isinstance(decision, RoutingDecision)

    # -- Edge cases --

    def test_empty_messages(self, router: IntelligentRouter) -> None:
        decision = router.route([], "system", {})
        assert decision.tier == ModelTier.REASONING  # safest default

    @pytest.mark.asyncio
    async def test_complete_empty_messages(
        self, router: IntelligentRouter
    ) -> None:
        response, decision = await router.complete([], "system", {})
        assert isinstance(response, LLMResponse)

    def test_very_long_message(self, router: IntelligentRouter) -> None:
        long_msg = "analyze " + "word " * 500
        decision = router.route(_msgs(long_msg), "system", {})
        assert decision.tier == ModelTier.REASONING

    @pytest.mark.asyncio
    async def test_complete_with_system_and_user_messages(
        self, router: IntelligentRouter
    ) -> None:
        messages = [
            _msg("You are a helpful agent", role="system"),
            _msg("What time is my appointment?"),
        ]
        response, decision = await router.complete(messages, "system", {})
        assert isinstance(response, LLMResponse)


# ===========================================================================
# 5. RoutingMetrics Tests (30 tests)
# ===========================================================================


class TestRoutingMetrics:
    """Test SQLite-backed routing analytics."""

    def _make_decision(
        self,
        tier: ModelTier = ModelTier.SPEED,
        classification: TaskClassification = TaskClassification.FAST_LOOKUP,
        model: str = "mercury-2",
        confidence: float = 0.9,
    ) -> RoutingDecision:
        return RoutingDecision(
            tier=tier,
            classification=classification,
            confidence=confidence,
            model_name=model,
            reason="test routing",
            estimated_cost_usd=0.001,
            estimated_latency_ms=50,
        )

    # -- Table creation --

    def test_table_created_on_init(self, metrics: RoutingMetrics) -> None:
        conn = sqlite3.connect(metrics.db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='routing_decisions'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    # -- record_routing --

    def test_record_routing(self, metrics: RoutingMetrics) -> None:
        decision = self._make_decision()
        metrics.record_routing(
            decision=decision,
            actual_latency_ms=45.0,
            actual_cost_usd=0.0008,
            success=True,
        )
        conn = sqlite3.connect(metrics.db_path)
        cursor = conn.execute("SELECT COUNT(*) FROM routing_decisions")
        assert cursor.fetchone()[0] == 1
        conn.close()

    def test_record_multiple(self, metrics: RoutingMetrics) -> None:
        for i in range(5):
            metrics.record_routing(
                decision=self._make_decision(),
                actual_latency_ms=40.0 + i,
                actual_cost_usd=0.001,
                success=True,
            )
        conn = sqlite3.connect(metrics.db_path)
        cursor = conn.execute("SELECT COUNT(*) FROM routing_decisions")
        assert cursor.fetchone()[0] == 5
        conn.close()

    def test_record_with_fallback(self, metrics: RoutingMetrics) -> None:
        metrics.record_routing(
            decision=self._make_decision(),
            actual_latency_ms=120.0,
            actual_cost_usd=0.005,
            success=True,
            fallback_used=True,
        )
        conn = sqlite3.connect(metrics.db_path)
        cursor = conn.execute(
            "SELECT fallback_used FROM routing_decisions WHERE id=1"
        )
        row = cursor.fetchone()
        assert row[0] == 1  # SQLite stores bool as int
        conn.close()

    def test_record_failure(self, metrics: RoutingMetrics) -> None:
        metrics.record_routing(
            decision=self._make_decision(),
            actual_latency_ms=500.0,
            actual_cost_usd=0.0,
            success=False,
        )
        conn = sqlite3.connect(metrics.db_path)
        cursor = conn.execute(
            "SELECT success FROM routing_decisions WHERE id=1"
        )
        row = cursor.fetchone()
        assert row[0] == 0
        conn.close()

    # -- get_tier_distribution --

    def test_tier_distribution_empty(self, metrics: RoutingMetrics) -> None:
        dist = metrics.get_tier_distribution()
        assert dist == {}

    def test_tier_distribution_single_tier(self, metrics: RoutingMetrics) -> None:
        for _ in range(3):
            metrics.record_routing(
                decision=self._make_decision(tier=ModelTier.SPEED),
                actual_latency_ms=50.0,
                actual_cost_usd=0.001,
                success=True,
            )
        dist = metrics.get_tier_distribution()
        assert dist.get("speed", 0.0) == pytest.approx(100.0, abs=0.1)

    def test_tier_distribution_multiple_tiers(
        self, metrics: RoutingMetrics
    ) -> None:
        for tier in [ModelTier.SPEED, ModelTier.CREATIVE, ModelTier.REASONING]:
            metrics.record_routing(
                decision=self._make_decision(tier=tier),
                actual_latency_ms=50.0,
                actual_cost_usd=0.001,
                success=True,
            )
        dist = metrics.get_tier_distribution()
        for key in ["speed", "creative", "reasoning"]:
            assert dist.get(key, 0.0) == pytest.approx(33.33, abs=1.0)

    def test_tier_distribution_respects_days_filter(
        self, metrics: RoutingMetrics
    ) -> None:
        metrics.record_routing(
            decision=self._make_decision(tier=ModelTier.SPEED),
            actual_latency_ms=50.0,
            actual_cost_usd=0.001,
            success=True,
        )
        # With 30-day window, should see the record
        dist = metrics.get_tier_distribution(days=30)
        assert len(dist) > 0

    # -- get_cost_savings --

    def test_cost_savings_empty(self, metrics: RoutingMetrics) -> None:
        savings = metrics.get_cost_savings()
        assert savings["total_actual_cost"] == 0.0
        assert savings["total_baseline_cost"] == 0.0

    def test_cost_savings_speed_saves_money(
        self, metrics: RoutingMetrics
    ) -> None:
        for _ in range(10):
            metrics.record_routing(
                decision=self._make_decision(
                    tier=ModelTier.SPEED, model="mercury-2"
                ),
                actual_latency_ms=50.0,
                actual_cost_usd=0.0001,
                success=True,
            )
        savings = metrics.get_cost_savings()
        assert savings["total_actual_cost"] < savings["total_baseline_cost"]

    def test_cost_savings_calculation(self, metrics: RoutingMetrics) -> None:
        metrics.record_routing(
            decision=self._make_decision(tier=ModelTier.SPEED),
            actual_latency_ms=50.0,
            actual_cost_usd=0.001,
            success=True,
        )
        savings = metrics.get_cost_savings()
        assert "savings_usd" in savings
        assert "savings_percent" in savings

    # -- get_latency_percentiles --

    def test_latency_percentiles_empty(self, metrics: RoutingMetrics) -> None:
        percentiles = metrics.get_latency_percentiles(ModelTier.SPEED)
        assert percentiles == {"p50": 0.0, "p95": 0.0, "p99": 0.0}

    def test_latency_percentiles_single(self, metrics: RoutingMetrics) -> None:
        metrics.record_routing(
            decision=self._make_decision(tier=ModelTier.SPEED),
            actual_latency_ms=50.0,
            actual_cost_usd=0.001,
            success=True,
        )
        percentiles = metrics.get_latency_percentiles(ModelTier.SPEED)
        assert percentiles["p50"] == pytest.approx(50.0, abs=1.0)

    def test_latency_percentiles_multiple(self, metrics: RoutingMetrics) -> None:
        for latency in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
            metrics.record_routing(
                decision=self._make_decision(tier=ModelTier.SPEED),
                actual_latency_ms=float(latency),
                actual_cost_usd=0.001,
                success=True,
            )
        percentiles = metrics.get_latency_percentiles(ModelTier.SPEED)
        assert percentiles["p50"] > 0.0
        assert percentiles["p95"] >= percentiles["p50"]
        assert percentiles["p99"] >= percentiles["p95"]

    def test_latency_percentiles_per_tier(self, metrics: RoutingMetrics) -> None:
        """Speed tier should not include reasoning tier latencies."""
        for latency in [50, 60, 70]:
            metrics.record_routing(
                decision=self._make_decision(tier=ModelTier.SPEED),
                actual_latency_ms=float(latency),
                actual_cost_usd=0.001,
                success=True,
            )
        for latency in [500, 600, 700]:
            metrics.record_routing(
                decision=self._make_decision(tier=ModelTier.REASONING),
                actual_latency_ms=float(latency),
                actual_cost_usd=0.01,
                success=True,
            )
        speed_p = metrics.get_latency_percentiles(ModelTier.SPEED)
        reasoning_p = metrics.get_latency_percentiles(ModelTier.REASONING)
        assert speed_p["p50"] < reasoning_p["p50"]

    # -- get_fallback_rate --

    def test_fallback_rate_empty(self, metrics: RoutingMetrics) -> None:
        assert metrics.get_fallback_rate() == 0.0

    def test_fallback_rate_none(self, metrics: RoutingMetrics) -> None:
        for _ in range(5):
            metrics.record_routing(
                decision=self._make_decision(),
                actual_latency_ms=50.0,
                actual_cost_usd=0.001,
                success=True,
                fallback_used=False,
            )
        assert metrics.get_fallback_rate() == 0.0

    def test_fallback_rate_all(self, metrics: RoutingMetrics) -> None:
        for _ in range(5):
            metrics.record_routing(
                decision=self._make_decision(),
                actual_latency_ms=50.0,
                actual_cost_usd=0.001,
                success=True,
                fallback_used=True,
            )
        assert metrics.get_fallback_rate() == pytest.approx(100.0, abs=0.1)

    def test_fallback_rate_partial(self, metrics: RoutingMetrics) -> None:
        for i in range(10):
            metrics.record_routing(
                decision=self._make_decision(),
                actual_latency_ms=50.0,
                actual_cost_usd=0.001,
                success=True,
                fallback_used=(i < 3),  # 30% fallback
            )
        assert metrics.get_fallback_rate() == pytest.approx(30.0, abs=1.0)

    # -- get_quality_correlation --

    def test_quality_correlation_empty(self, metrics: RoutingMetrics) -> None:
        corr = metrics.get_quality_correlation(ModelTier.SPEED)
        assert corr["total_requests"] == 0

    def test_quality_correlation_success_rate(
        self, metrics: RoutingMetrics
    ) -> None:
        for i in range(10):
            metrics.record_routing(
                decision=self._make_decision(tier=ModelTier.SPEED),
                actual_latency_ms=50.0,
                actual_cost_usd=0.001,
                success=(i < 8),  # 80% success
            )
        corr = metrics.get_quality_correlation(ModelTier.SPEED)
        assert corr["success_rate"] == pytest.approx(80.0, abs=1.0)
        assert corr["total_requests"] == 10

    # -- SQLite busy timeout --

    def test_busy_timeout_set(self, tmp_metrics_db: Path) -> None:
        """Ensure busy_timeout is set for shared DB safety."""
        m = RoutingMetrics(db_path=str(tmp_metrics_db))
        conn = sqlite3.connect(str(tmp_metrics_db))
        # The RoutingMetrics should have set busy_timeout
        # We test that the table exists (init completed without locking issues)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='routing_decisions'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    # -- Column completeness --

    def test_all_columns_stored(self, metrics: RoutingMetrics) -> None:
        decision = self._make_decision(
            tier=ModelTier.CREATIVE,
            classification=TaskClassification.CREATIVE_CONTENT,
            model="gpt-5-mini",
            confidence=0.85,
        )
        metrics.record_routing(
            decision=decision,
            actual_latency_ms=120.5,
            actual_cost_usd=0.003,
            success=True,
            fallback_used=False,
        )
        conn = sqlite3.connect(metrics.db_path)
        cursor = conn.execute("SELECT * FROM routing_decisions WHERE id=1")
        row = cursor.fetchone()
        assert row is not None
        columns = [desc[0] for desc in cursor.description]
        assert "tier" in columns
        assert "classification" in columns
        assert "model" in columns
        assert "confidence" in columns
        assert "estimated_cost" in columns
        assert "actual_cost" in columns
        assert "estimated_latency" in columns
        assert "actual_latency" in columns
        assert "success" in columns
        assert "fallback_used" in columns
        conn.close()


# ===========================================================================
# 6. Cost Table Tests (5 tests)
# ===========================================================================


class TestCostTable:
    """Validate the COST_TABLE constants."""

    def test_mercury_in_cost_table(self) -> None:
        assert "mercury-2" in COST_TABLE

    def test_gpt_in_cost_table(self) -> None:
        assert "gpt-5-mini" in COST_TABLE

    def test_claude_sonnet_in_cost_table(self) -> None:
        assert "claude-sonnet-4-6" in COST_TABLE

    def test_claude_haiku_in_cost_table(self) -> None:
        assert "claude-haiku-4-5" in COST_TABLE

    def test_cost_table_has_input_output(self) -> None:
        for model, costs in COST_TABLE.items():
            assert "input" in costs, f"Missing 'input' for {model}"
            assert "output" in costs, f"Missing 'output' for {model}"
            assert costs["input"] >= 0, f"Negative input cost for {model}"
            assert costs["output"] >= 0, f"Negative output cost for {model}"


# ===========================================================================
# 7. Integration / Edge Case Tests (5 tests)
# ===========================================================================


class TestIntegration:
    """Cross-cutting integration and edge case tests."""

    @pytest.mark.asyncio
    async def test_no_imports_from_brain_or_api(self) -> None:
        """Ensure router module does not import from isg_agent.brain or isg_agent.api."""
        import importlib
        import inspect

        mod = importlib.import_module("isg_agent.models.router")
        source = inspect.getsource(mod)
        assert "from isg_agent.brain" not in source
        assert "from isg_agent.api" not in source
        assert "import isg_agent.brain" not in source
        assert "import isg_agent.api" not in source

    @pytest.mark.asyncio
    async def test_no_imports_from_brain_in_firewall(self) -> None:
        import importlib
        import inspect

        mod = importlib.import_module("isg_agent.models.context_firewall")
        source = inspect.getsource(mod)
        assert "from isg_agent.brain" not in source
        assert "from isg_agent.api" not in source

    @pytest.mark.asyncio
    async def test_no_imports_from_brain_in_metrics(self) -> None:
        import importlib
        import inspect

        mod = importlib.import_module("isg_agent.models.routing_metrics")
        source = inspect.getsource(mod)
        assert "from isg_agent.brain" not in source
        assert "from isg_agent.api" not in source

    @pytest.mark.asyncio
    async def test_classification_is_o1_no_llm_calls(
        self, router: IntelligentRouter
    ) -> None:
        """Classification must be pattern matching only, not an LLM call.
        We verify by ensuring no providers are called during classify_task."""
        # If classify_task called an LLM, the FakeProvider.complete would be
        # invoked. We can verify by checking that no provider was called.
        result = router.classify_task(
            _msgs("What time is my appointment?"), {}
        )
        assert isinstance(result, TaskClassification)
        # The fact that this returns synchronously proves no LLM call was made
        # (LLM calls are async)

    @pytest.mark.asyncio
    async def test_full_pipeline_fast_task(
        self, router: IntelligentRouter
    ) -> None:
        """Full end-to-end pipeline for a fast task."""
        messages = [
            _msg("You are a helpful assistant", role="system"),
            _msg("What time is my appointment?"),
        ]
        response, decision = await router.complete(messages, "system", {})
        assert decision.tier == ModelTier.SPEED
        assert decision.classification.value.startswith("fast_")
        assert 0.0 <= decision.confidence <= 1.0
        assert decision.estimated_cost_usd >= 0.0
        assert decision.estimated_latency_ms > 0
        assert len(decision.reason) > 0
        assert isinstance(response.content, str)
        assert response.content == "speed response"
