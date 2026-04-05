"""Context firewall — compartmentalization enforcer for multi-LLM routing.

Ensures no single LLM provider sees the full system architecture.
Each tier receives only the information it needs to complete its task.
Validates outbound responses to catch any leaked internal references.

This module is used by the IntelligentRouter (router.py) and can also
be used standalone for response validation.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from isg_agent.models.provider import LLMMessage

__all__ = ["ContextFirewall"]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Compiled patterns for stripping internal references
# ---------------------------------------------------------------------------

# Internal architecture references
_ARCHITECTURE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bisg_agent\b"),
    re.compile(r"\bSkillExecutor\b"),
    re.compile(r"\bAgentRuntime\b"),
    re.compile(r"\bModelRegistry\b"),
    re.compile(r"\bIntelligentRouter\b"),
    re.compile(r"\bContextSanitizer\b"),
    re.compile(r"\bContextFirewall\b"),
    re.compile(r"\bRoutingMetrics\b"),
]

# Routing metadata references
_ROUTING_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\brouted to (?:Mercury|GPT|Claude|OpenAI|Anthropic)\b[^.]*?(?=\s[A-Z]|\.\s|$)", re.I),
    re.compile(r"\bclassified as \w+\b[^.]*?(?=\s[A-Z]|\.\s|$)", re.I),
    re.compile(r"\brouting (?:decision|engine|logic|metadata)\b", re.I),
    re.compile(r"\brouter\b", re.I),
    re.compile(r"\bfallback (?:chain|tier|activated)\b", re.I),
    re.compile(r"\btier\s*=\s*(?:speed|creative|reasoning)\b", re.I),
]

# Other model output tags
_MODEL_OUTPUT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\[(?:GPT|Claude|Mercury|Anthropic|OpenAI)\s+(?:response|analysis|output)\][^.]*", re.I),
    re.compile(r"\[Mercury response\][^.]*", re.I),
]

# Pricing and billing internals
_PRICING_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\$1/tx\b"),
    re.compile(r"\bcost_usd\b"),
    re.compile(r"\bmargin\b(?:\s*=|\s*:|\s*tracking)", re.I),
    re.compile(r"\binput_cost_per_m\b"),
    re.compile(r"\boutput_cost_per_m\b"),
    re.compile(r"\bestimated_cost\b"),
    re.compile(r"\bactual_cost\b"),
]

# Governance internals
_GOVERNANCE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\btrust_ledger\b"),
    re.compile(r"\bexplain_engine\b"),
    re.compile(r"\bcircuit_breaker\b"),
    re.compile(r"\bgovernance_check\b"),
    re.compile(r"\baudit_record\b"),
]

# Classification enum values that should not leak
_CLASSIFICATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bFAST_(?:EXTRACTION|CLASSIFICATION|SLOT_FILL|FORMAT|LOOKUP)\b"),
    re.compile(r"\bCREATIVE_(?:RESPONSE|CONTENT|PERSONALITY|EMPATHY)\b"),
    re.compile(r"\bCOMPLEX_(?:REASONING|ANALYSIS|SAFETY|ORCHESTRATION|CODE)\b"),
]

# All patterns combined for full stripping
_ALL_STRIP_PATTERNS: list[re.Pattern[str]] = (
    _ARCHITECTURE_PATTERNS
    + _ROUTING_PATTERNS
    + _MODEL_OUTPUT_PATTERNS
    + _PRICING_PATTERNS
    + _GOVERNANCE_PATTERNS
    + _CLASSIFICATION_PATTERNS
)


def _apply_patterns(text: str, patterns: list[re.Pattern[str]]) -> str:
    """Strip all pattern matches from text and clean up whitespace."""
    for pat in patterns:
        text = pat.sub("", text)
    # Collapse multiple spaces and strip
    text = re.sub(r"  +", " ", text).strip()
    return text


class ContextFirewall:
    """Compartmentalization enforcer for multi-LLM routing.

    Strips internal references from text, creates tier-appropriate contexts,
    and validates outbound responses for leaked internals.
    """

    # -- Core stripping --

    def strip_system_internals(self, text: Optional[str]) -> str:
        """Remove all internal system references from text.

        Strips references to: routing logic, internal architecture, other
        model outputs, pricing/billing, governance internals, and
        classification enum values.

        Parameters
        ----------
        text:
            The text to sanitize. If None or empty, returns empty string.

        Returns
        -------
        str
            The sanitized text.
        """
        if not text:
            return ""
        return _apply_patterns(text, _ALL_STRIP_PATTERNS)

    # -- Tier-specific context creation --

    def create_speed_context(
        self,
        user_message: str,
        skill_params: dict,
    ) -> str:
        """Create minimal context for the SPEED tier.

        Never includes full system prompt, agent config, or conversation
        history beyond the immediate task.

        Parameters
        ----------
        user_message:
            The user's current message.
        skill_params:
            Skill parameters to extract or process.

        Returns
        -------
        str
            A minimal, task-focused context string under 500 characters.
        """
        parts: list[str] = []
        parts.append("Task: Process the user's request efficiently.")

        if skill_params:
            param_items = ", ".join(f"{k}={v}" for k, v in skill_params.items())
            parts.append(f"Parameters: {param_items}")

        # Include sanitized user message
        clean_msg = self.strip_system_internals(user_message)
        if clean_msg:
            parts.append(f"User request: {clean_msg}")

        return " ".join(parts)

    def create_creative_context(
        self,
        personality: dict,
        recent_messages: list[LLMMessage],
        tone: str,
    ) -> str:
        """Create rich personality context for the CREATIVE tier.

        Includes agent personality, last 5 conversation turns for continuity,
        and desired tone. Never includes skill internals, pricing, or routing.

        Parameters
        ----------
        personality:
            Agent personality dict with name, voice, style, greeting fields.
        recent_messages:
            Recent conversation messages (will be limited to last 5).
        tone:
            Desired tone for the response (e.g. "professional", "casual").

        Returns
        -------
        str
            A personality-focused context string.
        """
        parts: list[str] = []

        # Personality section
        if personality:
            name = personality.get("name", "")
            voice = personality.get("voice", "")
            style = personality.get("style", "")
            greeting = personality.get("greeting", "")
            if name:
                parts.append(f"Agent name: {name}.")
            if voice:
                parts.append(f"Voice: {voice}.")
            if style:
                parts.append(f"Style: {style}.")
            if greeting:
                parts.append(f"Greeting: {greeting}")

        # Tone
        if tone:
            parts.append(f"Tone: {tone}.")

        # Last 5 turns of conversation for continuity
        limited = recent_messages[-5:] if len(recent_messages) > 5 else recent_messages
        if limited:
            parts.append("Recent conversation:")
            for msg in limited:
                clean = self.strip_system_internals(msg.content)
                if clean:
                    role_label = msg.role.capitalize()
                    parts.append(f"  {role_label}: {clean}")

        return " ".join(parts)

    def create_reasoning_context(
        self,
        full_messages: list[LLMMessage],
        system_prompt: str,
        skill_results: list,
    ) -> str:
        """Create full context for the REASONING tier.

        Claude gets the most context as the trusted reasoning tier. Still
        strips other providers' raw responses and billing internals.

        Parameters
        ----------
        full_messages:
            Complete conversation history.
        system_prompt:
            The full system prompt.
        skill_results:
            Results from skill executions to include.

        Returns
        -------
        str
            A comprehensive context string for complex reasoning.
        """
        # Strip only billing and other-provider outputs
        billing_and_output_patterns = (
            _MODEL_OUTPUT_PATTERNS + _PRICING_PATTERNS
        )

        parts: list[str] = []

        # System prompt (stripped of billing only)
        if system_prompt:
            clean_prompt = _apply_patterns(system_prompt, billing_and_output_patterns)
            parts.append(clean_prompt)

        # Full message history
        for msg in full_messages:
            clean = _apply_patterns(msg.content, billing_and_output_patterns)
            if clean:
                role_label = msg.role.capitalize()
                parts.append(f"{role_label}: {clean}")

        # Skill results
        if skill_results:
            parts.append("Skill results:")
            for result in skill_results:
                clean_result = self.strip_system_internals(str(result))
                if clean_result:
                    parts.append(f"  - {clean_result}")

        return " ".join(parts)

    # -- Outbound validation --

    def validate_outbound(
        self,
        response: str,
        tier: "ModelTier",  # noqa: F821 — forward reference
    ) -> str:
        """Validate and sanitize an outbound response before returning to user.

        Checks for internal metadata that may have leaked into the model's
        response and strips it. Logs warnings if internal references are
        detected.

        Parameters
        ----------
        response:
            The raw response text from the model.
        tier:
            The tier that generated the response (for logging context).

        Returns
        -------
        str
            The sanitized response safe for the end user.
        """
        if not response:
            return ""

        # Check for leaked internals before stripping (for logging)
        leaked = False
        for pat in _ALL_STRIP_PATTERNS:
            if pat.search(response):
                leaked = True
                logger.warning(
                    "Internal reference leaked in %s tier response: pattern=%s",
                    tier.value if hasattr(tier, "value") else str(tier),
                    pat.pattern,
                )

        if leaked:
            logger.warning(
                "Stripping leaked internal references from %s tier response",
                tier.value if hasattr(tier, "value") else str(tier),
            )

        return _apply_patterns(response, _ALL_STRIP_PATTERNS)
