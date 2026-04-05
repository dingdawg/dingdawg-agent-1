"""Intelligent multi-LLM routing engine.

Routes requests to the optimal model tier based on task classification:
- SPEED (Mercury 2): fast extraction, classification, slot-filling, formatting
- CREATIVE (GPT): personality, marketing, empathy, long-form content
- REASONING (Claude): complex analysis, safety-critical, multi-step reasoning

Task classification is O(1) pattern matching — no LLM calls in the routing path.
Context is sanitized per-tier to enforce IP compartmentalization (no single
provider sees the full system).

This module sits ON TOP of the existing ModelRegistry and does not modify it.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from isg_agent.models.provider import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
    ProviderError,
)

__all__ = [
    "TaskClassification",
    "ModelTier",
    "RoutingDecision",
    "ContextSanitizer",
    "IntelligentRouter",
    "COST_TABLE",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TaskClassification(str, Enum):
    """Classification of user tasks for model routing."""

    FAST_EXTRACTION = "fast_extraction"
    FAST_CLASSIFICATION = "fast_classification"
    FAST_SLOT_FILL = "fast_slot_fill"
    FAST_FORMAT = "fast_format"
    FAST_LOOKUP = "fast_lookup"
    CREATIVE_RESPONSE = "creative_response"
    CREATIVE_CONTENT = "creative_content"
    CREATIVE_PERSONALITY = "creative_personality"
    CREATIVE_EMPATHY = "creative_empathy"
    COMPLEX_REASONING = "complex_reasoning"
    COMPLEX_ANALYSIS = "complex_analysis"
    COMPLEX_SAFETY = "complex_safety"
    COMPLEX_ORCHESTRATION = "complex_orchestration"
    COMPLEX_CODE = "complex_code"
    UNKNOWN = "unknown"


class ModelTier(str, Enum):
    """Model tier indicating the class of LLM to use."""

    SPEED = "speed"
    CREATIVE = "creative"
    REASONING = "reasoning"


# ---------------------------------------------------------------------------
# Cost table — per million tokens (USD)
# ---------------------------------------------------------------------------

COST_TABLE: dict[str, dict[str, float]] = {
    "mercury-2": {"input": 0.25, "output": 0.75},
    "gpt-5-mini": {"input": 0.15, "output": 0.60},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5": {"input": 0.25, "output": 1.25},
}

# Default models per tier
_DEFAULT_MODELS: dict[ModelTier, str] = {
    ModelTier.SPEED: "mercury-2",
    ModelTier.CREATIVE: "gpt-5-mini",
    ModelTier.REASONING: "claude-sonnet-4-6",
}

# Estimated latency per tier (milliseconds)
_ESTIMATED_LATENCY: dict[ModelTier, int] = {
    ModelTier.SPEED: 80,
    ModelTier.CREATIVE: 300,
    ModelTier.REASONING: 800,
}

# Fallback chains per tier — ordered list of tiers to try on failure
_FALLBACK_CHAINS: dict[ModelTier, list[ModelTier]] = {
    ModelTier.SPEED: [ModelTier.SPEED, ModelTier.CREATIVE, ModelTier.REASONING],
    ModelTier.CREATIVE: [ModelTier.CREATIVE, ModelTier.REASONING],
    ModelTier.REASONING: [ModelTier.REASONING],
}


# ---------------------------------------------------------------------------
# RoutingDecision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoutingDecision:
    """Immutable record of a routing decision.

    Attributes
    ----------
    tier:
        The model tier selected for this request.
    classification:
        The task classification that determined the tier.
    confidence:
        Confidence in the classification (0.0 to 1.0).
    model_name:
        The specific model identifier to call.
    reason:
        Human-readable explanation of the routing decision.
    estimated_cost_usd:
        Estimated cost based on average token usage for this tier.
    estimated_latency_ms:
        Estimated latency in milliseconds.
    """

    tier: ModelTier
    classification: TaskClassification
    confidence: float
    model_name: str
    reason: str
    estimated_cost_usd: float
    estimated_latency_ms: int


# ---------------------------------------------------------------------------
# Classification patterns (compiled once at module load for O(1) amortized)
# ---------------------------------------------------------------------------

# Pattern groups: (compiled_regex, TaskClassification, confidence)
# Patterns are checked in priority order — first match wins.

_COMPLEX_SAFETY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:cancel|refund|delete|remove)\b.*\b(?:account|subscription|payment|order)\b", re.I),
    re.compile(r"\b(?:account|subscription|payment)\b.*\b(?:cancel|refund|delete|remove)\b", re.I),
    re.compile(r"\bdelete\s+(?:my|the)\b", re.I),
    re.compile(r"\brefund\b", re.I),
]

_COMPLEX_ORCHESTRATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bif\b.+\b(?:then|automatically|auto)\b", re.I),
    re.compile(r"\bwhen\b.+\b(?:then|automatically|auto|notify)\b", re.I),
    re.compile(r"\bautomatically\b", re.I),
]

_COMPLEX_ANALYSIS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:analyze|analyse)\b", re.I),
    re.compile(r"\bcompare\b", re.I),
    re.compile(r"\bwhy\s+(?:are|is|did|do|does|has|have|were|was)\b", re.I),
    re.compile(r"\bexplain\s+the\s+relationship\b", re.I),
    re.compile(r"\btrend[s]?\b.*\b(?:over|across|past|last)\b", re.I),
    re.compile(r"\b(?:down|up)\s+\d+%\b", re.I),
    re.compile(r"\bretention\b", re.I),
]

_COMPLEX_CODE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:debug|fix\s+the\s+code|write\s+a\s+function|implement)\b", re.I),
    re.compile(r"\bcode\s+review\b", re.I),
]

_COMPLEX_REASONING_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:explain|reason|think\s+through|step.by.step)\b", re.I),
    re.compile(r"\brelationship\s+between\b", re.I),
]

_CREATIVE_CONTENT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:write|compose|draft|create)\s+(?:me\s+)?(?:a\s+)?(?:marketing|newsletter|email|blog|post|article|letter|copy)\b", re.I),
    re.compile(r"\bwrite\s+me\b", re.I),
    re.compile(r"\bcompose\b", re.I),
]

_CREATIVE_RESPONSE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:brainstorm|suggest|come\s+up\s+with|ideas?\s+for)\b", re.I),
    re.compile(r"\b(?:catchy|creative|clever|fun|witty)\b", re.I),
    re.compile(r"\bhelp\s+me\s+(?:come\s+up|think\s+of|figure\s+out)\b", re.I),
]

_CREATIVE_EMPATHY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:frustrated|disappointed|upset|angry|annoyed|sad|worried|stressed)\b", re.I),
    re.compile(r"\bi['']m\s+(?:so\s+)?(?:frustrated|disappointed|upset|angry)\b", re.I),
]

_CREATIVE_PERSONALITY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\btell\s+me\s+about\s+yourself\b", re.I),
    re.compile(r"\bwho\s+are\s+you\b", re.I),
    re.compile(r"\bwhat\s+(?:are\s+you|can\s+you\s+do)\b", re.I),
]

_FAST_SLOT_FILL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:book|schedule|reserve|set\s+up)\b", re.I),
]

_FAST_FORMAT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:convert|format|reformat|transform)\b", re.I),
]

_FAST_EXTRACTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:how\s+many|list\s+(?:my|all|the)|show\s+(?:me|my|all))\b", re.I),
    re.compile(r"\bextract\b", re.I),
    re.compile(r"\bparse\b", re.I),
]

_FAST_LOOKUP_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:what\s+(?:time|is|are|was)|where\s+is|when\s+is|status\s+of)\b", re.I),
    re.compile(r"\bcheck\s+(?:my|the)\b", re.I),
]

# Short message threshold (word count)
_SHORT_MESSAGE_THRESHOLD = 10

# Long message threshold (word count) — triggers REASONING for analytical
_LONG_MESSAGE_THRESHOLD = 50


# ---------------------------------------------------------------------------
# ContextSanitizer — IP protection layer
# ---------------------------------------------------------------------------

# Patterns to strip from all tiers
_ROUTING_STRIP_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\brouted to (?:Mercury|GPT|Claude|OpenAI|Anthropic)\b[^.]*?(?=\s[A-Z]|\.\s|$)", re.I),
    re.compile(r"\bclassified as \w+\b[^.]*?(?=\s[A-Z]|\.\s|$)", re.I),
    re.compile(r"\brouter\b", re.I),
    re.compile(r"\bisg_agent\b", re.I),
    re.compile(r"\bSkillExecutor\b"),
    re.compile(r"\bAgentRuntime\b"),
    re.compile(r"\[(?:GPT|Claude|Mercury|Anthropic|OpenAI)\s+(?:response|analysis|output)\][^.]*?(?=\s[A-Z]|\.\s|$)", re.I),
]

# Patterns to strip from speed and creative tiers (billing/governance)
_INTERNAL_STRIP_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\$1/tx\b"),
    re.compile(r"\bcost_usd\b"),
    re.compile(r"\bmargin\b"),
    re.compile(r"\btrust_ledger\b"),
    re.compile(r"\bexplain_engine\b"),
    re.compile(r"\bcircuit_breaker\b"),
    re.compile(r"\binput_cost_per_m\b"),
    re.compile(r"\boutput_cost_per_m\b"),
    re.compile(r"\bFAST_EXTRACTION\b"),
    re.compile(r"\bFAST_LOOKUP\b"),
    re.compile(r"\bFAST_SLOT_FILL\b"),
    re.compile(r"\bFAST_FORMAT\b"),
    re.compile(r"\bFAST_CLASSIFICATION\b"),
    re.compile(r"\bCREATIVE_\w+\b"),
    re.compile(r"\bCOMPLEX_\w+\b"),
]

# Billing-only patterns (stripped from reasoning tier too)
_BILLING_STRIP_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\binput_cost_per_m\b"),
    re.compile(r"\boutput_cost_per_m\b"),
    re.compile(r"\bcost_usd\b"),
    re.compile(r"\$1/tx\b"),
]


def _strip_patterns(text: str, patterns: list[re.Pattern[str]]) -> str:
    """Apply all regex patterns to strip matches from text."""
    for pat in patterns:
        text = pat.sub("", text)
    # Clean up double spaces left by stripping
    text = re.sub(r"  +", " ", text).strip()
    return text


def _sanitize_messages(
    messages: list[LLMMessage],
    patterns: list[re.Pattern[str]],
) -> list[LLMMessage]:
    """Sanitize all messages by stripping patterns from content."""
    sanitized: list[LLMMessage] = []
    for msg in messages:
        cleaned = _strip_patterns(msg.content, patterns)
        sanitized.append(LLMMessage(role=msg.role, content=cleaned))
    return sanitized


class ContextSanitizer:
    """IP protection layer that sanitizes context before sending to each tier.

    Each tier receives only the information it needs. No single provider
    sees the full system architecture, routing logic, or other providers'
    outputs.
    """

    def sanitize_for_speed(
        self,
        messages: list[LLMMessage],
        system_prompt: str,
        *,
        skill_params: Optional[dict[str, str]] = None,
    ) -> tuple[list[LLMMessage], str]:
        """Sanitize context for the SPEED tier (Mercury 2).

        Strips routing metadata, internal architecture, other model outputs,
        and governance details. Replaces system prompt with minimal task-focused
        prompt. Passes only user message and skill parameters.

        Parameters
        ----------
        messages:
            The conversation messages.
        system_prompt:
            The full system prompt (will be replaced with a minimal version).
        skill_params:
            Optional skill parameters to include in the minimal prompt.

        Returns
        -------
        tuple[list[LLMMessage], str]
            Sanitized messages and a minimal system prompt.
        """
        all_patterns = _ROUTING_STRIP_PATTERNS + _INTERNAL_STRIP_PATTERNS
        sanitized = _sanitize_messages(messages, all_patterns)

        # Limit to last 2 turns only (minimal context for speed)
        user_msgs = [m for m in sanitized if m.role == "user"]
        sanitized = user_msgs[-2:] if len(user_msgs) > 2 else user_msgs

        # Build minimal system prompt
        prompt_parts = ["You are a fast, precise extraction assistant."]
        if skill_params:
            param_str = ", ".join(f"{k}: {v}" for k, v in skill_params.items())
            prompt_parts.append(f"Extract or process these parameters: {param_str}")

        minimal_prompt = " ".join(prompt_parts)
        return sanitized, minimal_prompt

    def sanitize_for_creative(
        self,
        messages: list[LLMMessage],
        system_prompt: str,
        *,
        agent_personality: Optional[dict[str, str]] = None,
    ) -> tuple[list[LLMMessage], str]:
        """Sanitize context for the CREATIVE tier (GPT).

        Strips skill implementations, pricing logic, internal routing, and
        governance details. Passes agent personality, conversation history
        (last 5 turns), and creative context.

        Parameters
        ----------
        messages:
            The conversation messages.
        system_prompt:
            The full system prompt (will be replaced with personality-focused).
        agent_personality:
            Optional dict with name, voice, style, greeting fields.

        Returns
        -------
        tuple[list[LLMMessage], str]
            Sanitized messages and a personality-focused prompt.
        """
        all_patterns = _ROUTING_STRIP_PATTERNS + _INTERNAL_STRIP_PATTERNS
        sanitized = _sanitize_messages(messages, all_patterns)

        # Limit to last 5 turns for continuity
        if len(sanitized) > 5:
            sanitized = sanitized[-5:]

        # Build personality-focused system prompt
        prompt_parts = ["You are a creative, engaging conversational assistant."]
        if agent_personality:
            name = agent_personality.get("name", "")
            voice = agent_personality.get("voice", "")
            style = agent_personality.get("style", "")
            greeting = agent_personality.get("greeting", "")
            if name:
                prompt_parts.append(f"Your name is {name}.")
            if voice:
                prompt_parts.append(f"Your voice is {voice}.")
            if style:
                prompt_parts.append(f"Your communication style is {style}.")
            if greeting:
                prompt_parts.append(f"Your greeting is: {greeting}")

        personality_prompt = " ".join(prompt_parts)
        return sanitized, personality_prompt

    def sanitize_for_reasoning(
        self,
        messages: list[LLMMessage],
        system_prompt: str,
    ) -> tuple[list[LLMMessage], str]:
        """Sanitize context for the REASONING tier (Claude).

        Passes full context (Claude is the trusted tier). Strips only other
        providers' raw outputs and billing internals.

        Parameters
        ----------
        messages:
            The conversation messages.
        system_prompt:
            The full system prompt (preserved).

        Returns
        -------
        tuple[list[LLMMessage], str]
            Sanitized messages and the (mostly preserved) system prompt.
        """
        # Strip other providers' outputs and billing, but preserve everything else
        strip_patterns = _ROUTING_STRIP_PATTERNS + _BILLING_STRIP_PATTERNS
        sanitized = _sanitize_messages(messages, strip_patterns)
        cleaned_prompt = _strip_patterns(system_prompt, _BILLING_STRIP_PATTERNS)

        return sanitized, cleaned_prompt


# ---------------------------------------------------------------------------
# IntelligentRouter
# ---------------------------------------------------------------------------


class IntelligentRouter:
    """Multi-LLM intelligent routing engine.

    Routes requests to the optimal model tier based on O(1) task classification.
    Sanitizes context per tier for IP protection. Handles fallback chains when
    a provider fails.

    Parameters
    ----------
    speed_provider:
        The LLM provider for the SPEED tier (Mercury 2).
    creative_provider:
        The LLM provider for the CREATIVE tier (GPT).
    reasoning_provider:
        The LLM provider for the REASONING tier (Claude).
    sanitizer:
        Optional ContextSanitizer override (default creates a new one).
    """

    def __init__(
        self,
        speed_provider: LLMProvider,
        creative_provider: LLMProvider,
        reasoning_provider: LLMProvider,
        *,
        sanitizer: Optional[ContextSanitizer] = None,
    ) -> None:
        self._providers: dict[ModelTier, LLMProvider] = {
            ModelTier.SPEED: speed_provider,
            ModelTier.CREATIVE: creative_provider,
            ModelTier.REASONING: reasoning_provider,
        }
        self._sanitizer = sanitizer or ContextSanitizer()

        # In-memory stats (lightweight; use RoutingMetrics for persistent)
        self._stats: dict[str, object] = {
            "total_requests": 0,
            "requests_by_tier": {t.value: 0 for t in ModelTier},
            "total_estimated_cost": 0.0,
            "total_baseline_cost": 0.0,
            "fallback_count": 0,
        }

    # -- Classification (O(1) pattern matching) --

    def classify_task(
        self,
        messages: list[LLMMessage],
        context: dict,
    ) -> TaskClassification:
        """Classify the user's task using keyword pattern matching.

        This is O(1) amortized — compiled regex patterns checked in priority
        order. No LLM calls. First match wins.

        Parameters
        ----------
        messages:
            The conversation messages. Classification uses the last user message.
        context:
            Optional context dict (may contain skill_params, has_personality, etc.).

        Returns
        -------
        TaskClassification
            The classified task type.
        """
        # Get the last user message for classification
        user_text = ""
        for msg in reversed(messages):
            if msg.role == "user":
                user_text = msg.content
                break

        if not user_text:
            return TaskClassification.UNKNOWN

        user_lower = user_text.lower()

        # Priority order: SAFETY > ORCHESTRATION > ANALYSIS > CODE > REASONING
        # then CREATIVE (empathy > content > response > personality)
        # then FAST (slot_fill > format > extraction > lookup)
        # Short messages without complex keywords → FAST

        # --- COMPLEX tier (highest priority) ---

        for pat in _COMPLEX_SAFETY_PATTERNS:
            if pat.search(user_text):
                return TaskClassification.COMPLEX_SAFETY

        for pat in _COMPLEX_ORCHESTRATION_PATTERNS:
            if pat.search(user_text):
                return TaskClassification.COMPLEX_ORCHESTRATION

        for pat in _COMPLEX_ANALYSIS_PATTERNS:
            if pat.search(user_text):
                return TaskClassification.COMPLEX_ANALYSIS

        for pat in _COMPLEX_CODE_PATTERNS:
            if pat.search(user_text):
                return TaskClassification.COMPLEX_CODE

        for pat in _COMPLEX_REASONING_PATTERNS:
            if pat.search(user_text):
                return TaskClassification.COMPLEX_REASONING

        # --- CREATIVE tier ---

        for pat in _CREATIVE_EMPATHY_PATTERNS:
            if pat.search(user_text):
                return TaskClassification.CREATIVE_EMPATHY

        for pat in _CREATIVE_CONTENT_PATTERNS:
            if pat.search(user_text):
                return TaskClassification.CREATIVE_CONTENT

        for pat in _CREATIVE_RESPONSE_PATTERNS:
            if pat.search(user_text):
                return TaskClassification.CREATIVE_RESPONSE

        # Personality detection (requires context signal)
        if context.get("has_personality"):
            for pat in _CREATIVE_PERSONALITY_PATTERNS:
                if pat.search(user_text):
                    return TaskClassification.CREATIVE_PERSONALITY

        # --- FAST tier ---

        for pat in _FAST_SLOT_FILL_PATTERNS:
            if pat.search(user_text):
                return TaskClassification.FAST_SLOT_FILL

        for pat in _FAST_FORMAT_PATTERNS:
            if pat.search(user_text):
                return TaskClassification.FAST_FORMAT

        for pat in _FAST_EXTRACTION_PATTERNS:
            if pat.search(user_text):
                return TaskClassification.FAST_EXTRACTION

        for pat in _FAST_LOOKUP_PATTERNS:
            if pat.search(user_text):
                return TaskClassification.FAST_LOOKUP

        # --- Fallback heuristics ---

        word_count = len(user_text.split())

        # Short messages with no keyword match → FAST_LOOKUP
        if word_count < _SHORT_MESSAGE_THRESHOLD:
            return TaskClassification.FAST_LOOKUP

        # Long messages without a clear match → REASONING (safest)
        if word_count >= _LONG_MESSAGE_THRESHOLD:
            return TaskClassification.COMPLEX_REASONING

        # Medium-length ambiguous → UNKNOWN (maps to REASONING)
        return TaskClassification.UNKNOWN

    def _classification_to_tier(self, classification: TaskClassification) -> ModelTier:
        """Map a TaskClassification to its ModelTier."""
        prefix = classification.value.split("_")[0]
        tier_map = {
            "fast": ModelTier.SPEED,
            "creative": ModelTier.CREATIVE,
            "complex": ModelTier.REASONING,
            "unknown": ModelTier.REASONING,
        }
        return tier_map.get(prefix, ModelTier.REASONING)

    def _compute_confidence(
        self,
        classification: TaskClassification,
        user_text: str,
    ) -> float:
        """Estimate classification confidence.

        Higher confidence for explicit keyword matches, lower for fallback
        heuristics.

        Returns
        -------
        float
            Confidence between 0.0 and 1.0.
        """
        if classification == TaskClassification.UNKNOWN:
            return 0.3

        word_count = len(user_text.split())

        # Short messages that matched FAST → high confidence
        if classification.value.startswith("fast_") and word_count < _SHORT_MESSAGE_THRESHOLD:
            return 0.85

        # Strong keyword match → good confidence
        if classification.value.startswith("complex_safety"):
            return 0.95  # Safety keywords are very reliable

        if classification.value.startswith("complex_"):
            return 0.8

        if classification.value.startswith("creative_"):
            return 0.75

        if classification.value.startswith("fast_"):
            return 0.85

        return 0.5

    def _estimate_cost(self, tier: ModelTier, avg_tokens: int = 500) -> float:
        """Estimate USD cost for a request in this tier.

        Uses COST_TABLE with an assumed average token count.

        Parameters
        ----------
        tier:
            The model tier.
        avg_tokens:
            Assumed average input+output tokens.

        Returns
        -------
        float
            Estimated cost in USD.
        """
        model = _DEFAULT_MODELS[tier]
        costs = COST_TABLE.get(model, {"input": 0.0, "output": 0.0})
        # Assume 60% input, 40% output
        input_tokens = int(avg_tokens * 0.6)
        output_tokens = int(avg_tokens * 0.4)
        input_cost = (input_tokens / 1_000_000) * costs["input"]
        output_cost = (output_tokens / 1_000_000) * costs["output"]
        return round(input_cost + output_cost, 8)

    def _baseline_cost(self, avg_tokens: int = 500) -> float:
        """Estimate the cost if ALL requests went to Claude (reasoning tier)."""
        return self._estimate_cost(ModelTier.REASONING, avg_tokens)

    # -- Routing --

    def route(
        self,
        messages: list[LLMMessage],
        system_prompt: str,
        context: dict,
    ) -> RoutingDecision:
        """Classify the task and produce a routing decision.

        Parameters
        ----------
        messages:
            The conversation messages.
        system_prompt:
            The system prompt for the request.
        context:
            Context dict (may contain skill_params, agent_personality, etc.).

        Returns
        -------
        RoutingDecision
            The routing decision with tier, model, cost, and latency estimates.
        """
        classification = self.classify_task(messages, context)
        tier = self._classification_to_tier(classification)

        # Get user text for confidence computation
        user_text = ""
        for msg in reversed(messages):
            if msg.role == "user":
                user_text = msg.content
                break

        confidence = self._compute_confidence(classification, user_text)
        model_name = _DEFAULT_MODELS[tier]
        estimated_cost = self._estimate_cost(tier)
        estimated_latency = _ESTIMATED_LATENCY[tier]

        reason = (
            f"Task classified as {classification.value} "
            f"(confidence={confidence:.2f}). "
            f"Routing to {tier.value} tier ({model_name})."
        )

        return RoutingDecision(
            tier=tier,
            classification=classification,
            confidence=confidence,
            model_name=model_name,
            reason=reason,
            estimated_cost_usd=estimated_cost,
            estimated_latency_ms=estimated_latency,
        )

    # -- Completion with fallback --

    async def complete(
        self,
        messages: list[LLMMessage],
        system_prompt: str,
        context: dict,
        *,
        max_tokens: int = 1024,
    ) -> tuple[LLMResponse, RoutingDecision]:
        """Full pipeline: classify, sanitize, call model, handle fallback.

        Parameters
        ----------
        messages:
            The conversation messages.
        system_prompt:
            The system prompt.
        context:
            Context dict.
        max_tokens:
            Maximum tokens for the LLM response.  Defaults to 1024.

        Returns
        -------
        tuple[LLMResponse, RoutingDecision]
            The LLM response and the routing decision used.

        Raises
        ------
        ProviderError
            If all providers in the fallback chain fail.
        """
        decision = self.route(messages, system_prompt, context)
        fallback_chain = _FALLBACK_CHAINS[decision.tier]
        fallback_used = False
        last_error: Exception | None = None

        for i, tier in enumerate(fallback_chain):
            provider = self._providers[tier]

            # Sanitize context for this tier
            sanitized_msgs, sanitized_prompt = self._sanitize_for_tier(
                tier, messages, system_prompt, context
            )

            # Prepend system prompt as a system message
            call_messages = [LLMMessage(role="system", content=sanitized_prompt)]
            call_messages.extend(sanitized_msgs)

            model_name = _DEFAULT_MODELS[tier]

            try:
                start_time = time.monotonic()
                response = await provider.complete(
                    call_messages,
                    model=model_name,
                    temperature=0.7 if tier != ModelTier.SPEED else 0.3,
                    max_tokens=max_tokens,
                )
                elapsed_ms = (time.monotonic() - start_time) * 1000

                if i > 0:
                    fallback_used = True
                    logger.warning(
                        "Fallback activated: %s -> %s for classification %s",
                        decision.tier.value,
                        tier.value,
                        decision.classification.value,
                    )

                # Update stats
                self._update_stats(decision, fallback_used)

                return response, decision

            except ProviderError as exc:
                last_error = exc
                logger.warning(
                    "Provider %s failed for tier %s: %s. Trying next fallback.",
                    provider.provider_name,
                    tier.value,
                    exc,
                )

        # All providers exhausted
        self._stats["total_requests"] = int(self._stats["total_requests"]) + 1
        raise ProviderError(
            message=(
                f"All providers exhausted for classification "
                f"{decision.classification.value}. "
                f"Tried tiers: {[t.value for t in fallback_chain]}. "
                f"Last error: {last_error}"
            ),
            provider="router",
        )

    def _sanitize_for_tier(
        self,
        tier: ModelTier,
        messages: list[LLMMessage],
        system_prompt: str,
        context: dict,
    ) -> tuple[list[LLMMessage], str]:
        """Apply tier-appropriate sanitization."""
        if tier == ModelTier.SPEED:
            return self._sanitizer.sanitize_for_speed(
                messages,
                system_prompt,
                skill_params=context.get("skill_params"),
            )
        elif tier == ModelTier.CREATIVE:
            return self._sanitizer.sanitize_for_creative(
                messages,
                system_prompt,
                agent_personality=context.get("agent_personality"),
            )
        else:
            return self._sanitizer.sanitize_for_reasoning(
                messages,
                system_prompt,
            )

    def _update_stats(
        self,
        decision: RoutingDecision,
        fallback_used: bool,
    ) -> None:
        """Update in-memory routing statistics."""
        self._stats["total_requests"] = int(self._stats["total_requests"]) + 1

        tier_key = decision.tier.value
        by_tier = self._stats["requests_by_tier"]
        if isinstance(by_tier, dict):
            by_tier[tier_key] = by_tier.get(tier_key, 0) + 1

        self._stats["total_estimated_cost"] = (
            float(self._stats["total_estimated_cost"]) + decision.estimated_cost_usd
        )
        self._stats["total_baseline_cost"] = (
            float(self._stats["total_baseline_cost"]) + self._baseline_cost()
        )

        if fallback_used:
            self._stats["fallback_count"] = int(self._stats["fallback_count"]) + 1

    # -- Stats --

    def get_routing_stats(self) -> dict:
        """Return current routing statistics.

        Returns
        -------
        dict
            Statistics including total requests, per-tier breakdown, and
            estimated cost savings vs an all-Claude baseline.
        """
        total = int(self._stats["total_requests"])
        total_cost = float(self._stats["total_estimated_cost"])
        baseline_cost = float(self._stats["total_baseline_cost"])
        savings = baseline_cost - total_cost

        return {
            "total_requests": total,
            "requests_by_tier": dict(self._stats["requests_by_tier"]),  # type: ignore[arg-type]
            "total_estimated_cost_usd": total_cost,
            "total_baseline_cost_usd": baseline_cost,
            "estimated_cost_savings_usd": max(savings, 0.0),
            "fallback_count": int(self._stats["fallback_count"]),
        }
