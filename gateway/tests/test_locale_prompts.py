"""Tests for locale-aware system prompt injection in PromptBuilder.

Validates that LANGUAGE_INJECTIONS is complete for all 6 supported locales
and that build_system_prompt correctly prepends language instructions when
an agent has a locale configured via config_json or business_context.

TDD discipline: tests define the contract for locale injection behaviour.
"""

from __future__ import annotations

import json

import pytest

from isg_agent.agents.agent_types import AgentRecord, AgentStatus, AgentType
from isg_agent.templates.prompt_builder import LANGUAGE_INJECTIONS, PromptBuilder
from isg_agent.templates.template_registry import TemplateRecord


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_REQUIRED_LOCALES = ("es", "ht", "vi", "zh", "fr", "ar")


def _make_template(
    *,
    system_prompt_template: str = (
        "You are {agent_name} at {business_name}. "
        "Industry: {industry_type}. "
        "Capabilities: {capabilities}."
    ),
    capabilities: str = '["browse_menu", "place_order"]',
) -> TemplateRecord:
    return TemplateRecord(
        id="tmpl-locale-test",
        name="Locale Test Template",
        agent_type="business",
        industry_type="restaurant",
        system_prompt_template=system_prompt_template,
        flow_json='{"steps": []}',
        catalog_schema_json=None,
        capabilities=capabilities,
        default_constitution_yaml=None,
        icon=None,
        created_at="2026-01-01T00:00:00+00:00",
    )


def _make_agent(
    *,
    name: str = "Test Bot",
    handle: str = "test-bot",
    config_json: str = "{}",
) -> AgentRecord:
    return AgentRecord(
        id="agent-locale-test",
        user_id="user-locale-test",
        handle=handle,
        name=name,
        agent_type=AgentType.BUSINESS,
        industry_type="restaurant",
        config_json=config_json,
        status=AgentStatus.ACTIVE,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


# ---------------------------------------------------------------------------
# TestLanguageInjectionsDictionary
# ---------------------------------------------------------------------------


class TestLanguageInjectionsDictionary:
    """Verify LANGUAGE_INJECTIONS has entries for all required locales."""

    def test_all_six_locales_present(self) -> None:
        """LANGUAGE_INJECTIONS must have entries for es, ht, vi, zh, fr, ar."""
        for locale in _REQUIRED_LOCALES:
            assert locale in LANGUAGE_INJECTIONS, (
                f"Missing LANGUAGE_INJECTIONS entry for locale '{locale}'"
            )

    def test_all_injection_values_are_nonempty_strings(self) -> None:
        for locale in _REQUIRED_LOCALES:
            value = LANGUAGE_INJECTIONS[locale]
            assert isinstance(value, str), (
                f"LANGUAGE_INJECTIONS['{locale}'] is not a string"
            )
            assert len(value) > 20, (
                f"LANGUAGE_INJECTIONS['{locale}'] is suspiciously short: "
                f"{len(value)} chars"
            )

    def test_en_not_in_injections(self) -> None:
        """English should NOT have a language injection — it is the default."""
        assert "en" not in LANGUAGE_INJECTIONS

    def test_spanish_injection_mentions_spanish(self) -> None:
        assert "Spanish" in LANGUAGE_INJECTIONS["es"]
        assert "Español" in LANGUAGE_INJECTIONS["es"]

    def test_haitian_creole_injection_mentions_kreyol(self) -> None:
        assert "Haitian Creole" in LANGUAGE_INJECTIONS["ht"]
        assert "Kreyòl" in LANGUAGE_INJECTIONS["ht"]

    def test_vietnamese_injection_mentions_vietnamese(self) -> None:
        assert "Vietnamese" in LANGUAGE_INJECTIONS["vi"]
        assert "Tiếng Việt" in LANGUAGE_INJECTIONS["vi"]

    def test_chinese_injection_mentions_chinese(self) -> None:
        assert "Chinese" in LANGUAGE_INJECTIONS["zh"]
        assert "简体中文" in LANGUAGE_INJECTIONS["zh"]

    def test_french_injection_mentions_vous(self) -> None:
        assert "French" in LANGUAGE_INJECTIONS["fr"]
        assert "vous" in LANGUAGE_INJECTIONS["fr"]

    def test_arabic_injection_mentions_arabic(self) -> None:
        assert "Arabic" in LANGUAGE_INJECTIONS["ar"]
        assert "العربية" in LANGUAGE_INJECTIONS["ar"]


# ---------------------------------------------------------------------------
# TestLocaleInjectionInPrompt
# ---------------------------------------------------------------------------


class TestLocaleInjectionInPrompt:
    """Verify build_system_prompt integrates locale injection correctly."""

    def test_spanish_locale_via_config_json(self) -> None:
        """Agent with locale='es' in config_json gets Spanish injection."""
        builder = PromptBuilder()
        template = _make_template()
        agent = _make_agent(config_json=json.dumps({"locale": "es"}))
        prompt = builder.build_system_prompt(template, agent)

        assert prompt.startswith("IMPORTANT: You MUST respond in Spanish")
        assert "Test Bot" in prompt  # original prompt still present

    def test_haitian_creole_locale_via_config_json(self) -> None:
        builder = PromptBuilder()
        template = _make_template()
        agent = _make_agent(config_json=json.dumps({"locale": "ht"}))
        prompt = builder.build_system_prompt(template, agent)

        assert "Haitian Creole" in prompt
        assert "Kreyòl" in prompt

    def test_vietnamese_locale_via_config_json(self) -> None:
        builder = PromptBuilder()
        template = _make_template()
        agent = _make_agent(config_json=json.dumps({"locale": "vi"}))
        prompt = builder.build_system_prompt(template, agent)

        assert "Vietnamese" in prompt
        assert "Tiếng Việt" in prompt

    def test_no_locale_means_no_injection(self) -> None:
        """Agent without locale should NOT have any language injection."""
        builder = PromptBuilder()
        template = _make_template()
        agent = _make_agent(config_json="{}")
        prompt = builder.build_system_prompt(template, agent)

        assert not prompt.startswith("IMPORTANT:")
        # None of the injection phrases should appear
        for injection in LANGUAGE_INJECTIONS.values():
            assert injection not in prompt

    def test_english_locale_means_no_injection(self) -> None:
        """locale='en' should NOT trigger any injection — English is default."""
        builder = PromptBuilder()
        template = _make_template()
        agent = _make_agent(config_json=json.dumps({"locale": "en"}))
        prompt = builder.build_system_prompt(template, agent)

        assert not prompt.startswith("IMPORTANT:")

    def test_none_locale_means_no_injection(self) -> None:
        """locale=None in config should NOT trigger injection."""
        builder = PromptBuilder()
        template = _make_template()
        agent = _make_agent(config_json=json.dumps({"locale": None}))
        prompt = builder.build_system_prompt(template, agent)

        assert not prompt.startswith("IMPORTANT:")

    def test_locale_via_business_context_overrides_config(self) -> None:
        """business_context['locale'] takes priority over config_json."""
        builder = PromptBuilder()
        template = _make_template()
        # config_json says "es" but business_context says "fr"
        agent = _make_agent(config_json=json.dumps({"locale": "es"}))
        ctx = {"locale": "fr"}
        prompt = builder.build_system_prompt(template, agent, business_context=ctx)

        assert "French" in prompt
        assert "vous" in prompt
        # Should NOT contain Spanish injection
        assert "Español" not in prompt

    def test_locale_injection_prepended_not_appended(self) -> None:
        """Language injection must be at the START of the prompt."""
        builder = PromptBuilder()
        template = _make_template()
        agent = _make_agent(config_json=json.dumps({"locale": "ar"}))
        prompt = builder.build_system_prompt(template, agent)

        assert prompt.startswith("IMPORTANT: You MUST respond in Arabic")

    def test_all_six_locales_produce_valid_prompts(self) -> None:
        """Every supported locale produces a non-empty prompt with injection."""
        builder = PromptBuilder()
        template = _make_template()

        for locale in _REQUIRED_LOCALES:
            agent = _make_agent(
                config_json=json.dumps({"locale": locale}),
            )
            prompt = builder.build_system_prompt(template, agent)

            assert isinstance(prompt, str)
            assert len(prompt) > 50, (
                f"Prompt for locale '{locale}' suspiciously short"
            )
            assert prompt.startswith("IMPORTANT:"), (
                f"Prompt for locale '{locale}' missing injection prefix"
            )
            # Original template content still present
            assert "Test Bot" in prompt, (
                f"Prompt for locale '{locale}' lost original template content"
            )

    def test_unsupported_locale_no_injection(self) -> None:
        """An unsupported locale (e.g. 'ja') should NOT crash or inject."""
        builder = PromptBuilder()
        template = _make_template()
        agent = _make_agent(config_json=json.dumps({"locale": "ja"}))
        prompt = builder.build_system_prompt(template, agent)

        assert not prompt.startswith("IMPORTANT:")
        assert "Test Bot" in prompt

    def test_invalid_config_json_no_crash(self) -> None:
        """Malformed config_json must not crash — gracefully skip injection."""
        builder = PromptBuilder()
        template = _make_template()
        agent = _make_agent(config_json="not valid json {{{")
        prompt = builder.build_system_prompt(template, agent)

        assert isinstance(prompt, str)
        assert "Test Bot" in prompt
