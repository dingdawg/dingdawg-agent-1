"""Prompt builder: generates final system prompts from template + agent context.

Takes a :class:`TemplateRecord` and an :class:`AgentRecord` (plus optional
business context dict) and produces a complete, substituted system prompt
string ready to pass to an LLM.

Design decisions
----------------
- Uses Python ``str.format_map`` with a :class:`_SafeDict` that returns ``""``
  for any missing key — no ``KeyError``, no template breakage at runtime.
- No Jinja2 or external templating dependency needed.
- ``build_flow`` deserialises ``flow_json`` into a Python dict for callers
  that need to inspect or render the conversation flow graph.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from isg_agent.agents.agent_types import AgentRecord
from isg_agent.templates.template_registry import TemplateRecord

__all__ = [
    "LANGUAGE_INJECTIONS",
    "PromptBuilder",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Locale-aware language injections
# ---------------------------------------------------------------------------
# Maps ISO 639-1 locale codes to system-prompt preamble instructions that
# force the LLM to respond in the target language. These are prepended to
# the system prompt when ``agent.config_json`` contains a ``"locale"`` key.
#
# Design decisions:
# - Instruction is in BOTH the target language and English so the LLM
#   cannot claim it did not understand the directive.
# - "unless they explicitly ask for English" gives end-users an escape hatch.
# - Honorific / register guidance is locale-specific (Vietnamese "polite",
#   French "vous", Arabic MSA).
# ---------------------------------------------------------------------------

LANGUAGE_INJECTIONS: dict[str, str] = {
    "es": (
        "IMPORTANT: You MUST respond in Spanish (Español). "
        "If the customer writes in English, still respond in Spanish "
        "unless they explicitly ask for English."
    ),
    "ht": (
        "IMPORTANT: You MUST respond in Haitian Creole (Kreyòl Ayisyen). "
        "Use simple, clear language. If the customer writes in English, "
        "respond in Haitian Creole unless they explicitly ask for English."
    ),
    "vi": (
        "IMPORTANT: You MUST respond in Vietnamese (Tiếng Việt). "
        "Use polite Vietnamese with appropriate honorifics. "
        "If the customer writes in English, respond in Vietnamese "
        "unless they explicitly ask for English."
    ),
    "zh": (
        "IMPORTANT: You MUST respond in Simplified Chinese (简体中文). "
        "Use professional but friendly tone."
    ),
    "fr": (
        "IMPORTANT: You MUST respond in French (Français). "
        "Use formal 'vous' form with customers."
    ),
    "ar": (
        "IMPORTANT: You MUST respond in Arabic (العربية). "
        "Use Modern Standard Arabic."
    ),
}


# ---------------------------------------------------------------------------
# SafeDict — missing keys silently return ""
# ---------------------------------------------------------------------------


class _SafeDict(dict):  # type: ignore[type-arg]
    """A dict subclass that returns an empty string for missing keys.

    Used with ``str.format_map`` so that templates with optional placeholders
    never raise ``KeyError`` when context is partially provided.
    """

    def __missing__(self, key: str) -> str:  # noqa: D105
        return ""


# ---------------------------------------------------------------------------
# PromptBuilder
# ---------------------------------------------------------------------------


class PromptBuilder:
    """Builds LLM-ready system prompts from template + agent + business context.

    This class is stateless — all methods are pure functions that take their
    inputs as arguments and return deterministic results.
    """

    # Substitution variables supported in ``system_prompt_template``
    _KNOWN_VARS: frozenset[str] = frozenset(
        {
            "agent_name",
            "agent_handle",
            "industry_type",
            "business_name",
            "greeting",
            "capabilities",
        }
    )

    def build_system_prompt(
        self,
        template: TemplateRecord,
        agent: AgentRecord,
        business_context: Optional[dict[str, Any]] = None,
    ) -> str:
        """Build a complete system prompt string for an LLM.

        Substitutes all ``{placeholder}`` tokens in the template's
        ``system_prompt_template`` with values derived from the agent record
        and optional business context dictionary.  Missing values are replaced
        with safe empty-string defaults so the prompt always renders without
        error.

        Substitution mapping (in priority order):
        - ``{agent_name}``   → ``agent.name``
        - ``{agent_handle}`` → ``agent.handle``
        - ``{industry_type}`` → ``template.industry_type`` or ``"general"``
        - ``{business_name}`` → ``business_context["business_name"]`` if present,
                                  else ``agent.name``
        - ``{greeting}``     → ``business_context["greeting"]`` if present, else ``""``
        - ``{capabilities}`` → comma-joined list from ``template.capabilities``

        Parameters
        ----------
        template:
            The template providing ``system_prompt_template`` and ``capabilities``.
        agent:
            The agent record providing ``name``, ``handle``, and ``agent_type``.
        business_context:
            Optional dict with runtime overrides.  Recognised keys:
            ``"business_name"``, ``"greeting"``, plus any custom keys defined
            in the template.

        Returns
        -------
        str
            The fully substituted system prompt string.
        """
        ctx = business_context or {}

        # Build capabilities string from the JSON capabilities array
        capabilities_str = self._format_capabilities(template.capabilities)

        # Assemble substitution context — use SafeDict so missing keys => ""
        substitutions = _SafeDict(
            {
                "agent_name": agent.name or "",
                "agent_handle": agent.handle or "",
                "industry_type": template.industry_type or "general",
                "business_name": ctx.get("business_name") or agent.name or "",
                "greeting": ctx.get("greeting") or "",
                "capabilities": capabilities_str,
            }
        )

        # Merge any extra keys from business_context so custom templates work
        for key, value in ctx.items():
            if key not in substitutions:
                substitutions[key] = str(value) if value is not None else ""

        try:
            result = template.system_prompt_template.format_map(substitutions)
        except Exception as exc:  # pragma: no cover — defensive only
            logger.error(
                "PromptBuilder.build_system_prompt: format_map failed for "
                "template_id=%s agent_id=%s: %s",
                getattr(template, "id", "?"),
                agent.id,
                exc,
            )
            # Return template with placeholders stripped rather than crashing
            result = template.system_prompt_template

        # -- Locale-aware language injection ----------------------------------
        # Extract locale from agent.config_json or business_context["locale"].
        # Prepend the language injection so the LLM sees it FIRST.
        locale = self._extract_locale(agent, ctx)
        if locale and locale in LANGUAGE_INJECTIONS:
            result = LANGUAGE_INJECTIONS[locale] + "\n\n" + result
            logger.debug(
                "PromptBuilder: injected locale=%s for agent_id=%s",
                locale,
                agent.id,
            )

        logger.debug(
            "PromptBuilder.build_system_prompt: template=%s agent=%s prompt_len=%d",
            getattr(template, "id", "?"),
            agent.id,
            len(result),
        )
        return result

    def build_flow(self, template: TemplateRecord) -> dict[str, Any]:
        """Parse and return the conversation flow from the template.

        Deserialises ``template.flow_json`` into a Python dict.  Returns an
        empty dict with a ``steps`` key if the JSON is missing or malformed,
        ensuring callers always get a consistent structure.

        Parameters
        ----------
        template:
            Template whose ``flow_json`` field will be parsed.

        Returns
        -------
        dict
            Parsed flow dict.  Always contains at least ``{"steps": []}``.
        """
        raw = template.flow_json or "{}"
        try:
            flow = json.loads(raw)
            if not isinstance(flow, dict):
                logger.warning(
                    "PromptBuilder.build_flow: flow_json is not a dict for "
                    "template_id=%s, returning default",
                    getattr(template, "id", "?"),
                )
                return {"steps": []}
            # Ensure the "steps" key is always present
            flow.setdefault("steps", [])
            return flow
        except json.JSONDecodeError as exc:
            logger.error(
                "PromptBuilder.build_flow: invalid JSON in flow_json for "
                "template_id=%s: %s",
                getattr(template, "id", "?"),
                exc,
            )
            return {"steps": []}

    # -- Private helpers -------------------------------------------------------

    @staticmethod
    def _extract_locale(
        agent: AgentRecord,
        business_context: dict[str, Any],
    ) -> str:
        """Extract locale code from agent config or business context.

        Priority:
          1. ``business_context["locale"]`` — runtime override
          2. ``agent.config_json`` → parsed ``{"locale": "es"}``
          3. Returns ``""`` (no locale) → English default, no injection

        Parameters
        ----------
        agent:
            Agent record whose ``config_json`` may contain ``"locale"``.
        business_context:
            Runtime context dict that may override locale.

        Returns
        -------
        str
            ISO 639-1 locale code (e.g. ``"es"``, ``"ht"``, ``"vi"``),
            or ``""`` if no locale is configured.
        """
        # Priority 1: runtime override from business_context
        ctx_locale = business_context.get("locale")
        if ctx_locale and isinstance(ctx_locale, str):
            return ctx_locale.strip().lower()

        # Priority 2: agent.config_json
        try:
            config = json.loads(agent.config_json or "{}")
            agent_locale = config.get("locale")
            if agent_locale and isinstance(agent_locale, str):
                return agent_locale.strip().lower()
        except (json.JSONDecodeError, AttributeError):
            pass

        return ""

    @staticmethod
    def _format_capabilities(capabilities_json: str) -> str:
        """Convert a JSON array of capability strings to a readable list.

        Parameters
        ----------
        capabilities_json:
            A JSON-encoded array of strings, e.g.
            ``'["browse_menu", "place_order"]'``.

        Returns
        -------
        str
            Comma-separated, human-readable capability list.
            Returns ``"none"`` if the array is empty or cannot be parsed.
        """
        try:
            caps = json.loads(capabilities_json or "[]")
            if not isinstance(caps, list) or not caps:
                return "none"
            return ", ".join(str(c).replace("_", " ") for c in caps)
        except json.JSONDecodeError:
            return "none"
