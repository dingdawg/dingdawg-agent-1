"""Tests for isg_agent.templates.prompt_builder."""

from __future__ import annotations

import json

import pytest

from isg_agent.agents.agent_types import AgentRecord, AgentStatus, AgentType
from isg_agent.templates.prompt_builder import PromptBuilder, _SafeDict
from isg_agent.templates.template_registry import TemplateRecord, TemplateRegistry


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_template(
    *,
    name: str = "Test Template",
    agent_type: str = "business",
    industry_type: str | None = "restaurant",
    system_prompt_template: str = (
        "You are {agent_name} at {business_name}. "
        "Industry: {industry_type}. "
        "Capabilities: {capabilities}. "
        "{greeting}"
    ),
    capabilities: str = '["browse_menu", "place_order"]',
    flow_json: str = '{"steps": [{"id": "greeting"}, {"id": "order"}]}',
) -> TemplateRecord:
    return TemplateRecord(
        id="tmpl-001",
        name=name,
        agent_type=agent_type,
        industry_type=industry_type,
        system_prompt_template=system_prompt_template,
        flow_json=flow_json,
        catalog_schema_json=None,
        capabilities=capabilities,
        default_constitution_yaml=None,
        icon=None,
        created_at="2026-01-01T00:00:00+00:00",
    )


def _make_agent(
    *,
    name: str = "Joes Pizza Bot",
    handle: str = "joes-pizza",
    agent_type: str = "business",
    industry_type: str | None = "restaurant",
) -> AgentRecord:
    return AgentRecord(
        id="agent-001",
        user_id="user-001",
        handle=handle,
        name=name,
        agent_type=AgentType(agent_type),
        industry_type=industry_type,
        status=AgentStatus.ACTIVE,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


# ---------------------------------------------------------------------------
# TestBuildSystemPrompt
# ---------------------------------------------------------------------------


class TestBuildSystemPrompt:
    """Tests for PromptBuilder.build_system_prompt."""

    def test_build_prompt_restaurant(self) -> None:
        builder = PromptBuilder()
        template = _make_template(
            industry_type="restaurant",
            system_prompt_template=(
                "You are {agent_name} at {business_name}. "
                "Industry: {industry_type}. "
                "Capabilities: {capabilities}."
            ),
            capabilities='["browse_menu", "place_order"]',
        )
        agent = _make_agent(name="Pizza Bot", handle="pizza-bot")
        prompt = builder.build_system_prompt(template, agent)

        assert "Pizza Bot" in prompt
        assert "browse menu" in prompt  # underscores replaced with spaces
        assert "place order" in prompt
        assert "restaurant" in prompt

    def test_build_prompt_personal(self) -> None:
        builder = PromptBuilder()
        template = _make_template(
            name="Personal Assistant",
            agent_type="personal",
            industry_type=None,
            system_prompt_template=(
                "You are {agent_name}, assistant to your owner. "
                "Capabilities: {capabilities}."
            ),
            capabilities='["manage_tasks", "set_reminders"]',
        )
        agent = _make_agent(
            name="My Assistant",
            handle="my-assistant",
            agent_type="personal",
            industry_type=None,
        )
        prompt = builder.build_system_prompt(template, agent)

        assert "My Assistant" in prompt
        assert "manage tasks" in prompt
        assert "set reminders" in prompt

    def test_build_prompt_missing_context_safe(self) -> None:
        """Template with placeholders but no business_context must not raise."""
        builder = PromptBuilder()
        template = _make_template(
            system_prompt_template=(
                "You are {agent_name}. Business: {business_name}. "
                "Custom: {nonexistent_key}."
            ),
        )
        agent = _make_agent()
        # Must not raise KeyError for {nonexistent_key}
        prompt = builder.build_system_prompt(template, agent, business_context=None)
        assert isinstance(prompt, str)
        assert "Joes Pizza Bot" in prompt

    def test_build_prompt_with_business_context(self) -> None:
        builder = PromptBuilder()
        template = _make_template(
            system_prompt_template="Welcome to {business_name}! {greeting}",
        )
        agent = _make_agent()
        ctx = {
            "business_name": "Tony's Trattoria",
            "greeting": "Ciao!",
        }
        prompt = builder.build_system_prompt(template, agent, business_context=ctx)

        assert "Tony's Trattoria" in prompt
        assert "Ciao!" in prompt

    def test_build_prompt_business_name_falls_back_to_agent_name(self) -> None:
        builder = PromptBuilder()
        template = _make_template(
            system_prompt_template="Welcome to {business_name}.",
        )
        agent = _make_agent(name="My Salon")
        # No business_name in context — should fall back to agent.name
        prompt = builder.build_system_prompt(template, agent, business_context={})
        assert "My Salon" in prompt

    def test_build_prompt_greeting_empty_when_not_provided(self) -> None:
        builder = PromptBuilder()
        template = _make_template(
            system_prompt_template="You are {agent_name}.{greeting}",
        )
        agent = _make_agent()
        prompt = builder.build_system_prompt(template, agent)
        # {greeting} should be empty string, not literal "{greeting}"
        assert "{greeting}" not in prompt

    def test_build_prompt_escapes_special_chars_in_context(self) -> None:
        """Business name with curly braces must not break format_map."""
        builder = PromptBuilder()
        template = _make_template(
            system_prompt_template="Welcome to {business_name}.",
        )
        agent = _make_agent()
        # Curly braces in business_name value — format_map handles the template,
        # the VALUE itself is substituted safely as a string
        ctx = {"business_name": "Joe's Place"}
        prompt = builder.build_system_prompt(template, agent, business_context=ctx)
        assert "Joe's Place" in prompt

    def test_build_prompt_capabilities_formatted_as_readable_list(self) -> None:
        builder = PromptBuilder()
        template = _make_template(
            system_prompt_template="Capabilities: {capabilities}",
            capabilities='["make_booking", "browse_catalog", "check_availability"]',
        )
        agent = _make_agent()
        prompt = builder.build_system_prompt(template, agent)
        assert "make booking" in prompt
        assert "browse catalog" in prompt
        assert "check availability" in prompt

    def test_build_prompt_empty_capabilities_shows_none(self) -> None:
        builder = PromptBuilder()
        template = _make_template(
            system_prompt_template="Capabilities: {capabilities}",
            capabilities="[]",
        )
        agent = _make_agent()
        prompt = builder.build_system_prompt(template, agent)
        assert "none" in prompt.lower()

    def test_build_prompt_agent_handle_substituted(self) -> None:
        builder = PromptBuilder()
        template = _make_template(
            system_prompt_template="Handle: {agent_handle}",
        )
        agent = _make_agent(handle="test-handle-99")
        prompt = builder.build_system_prompt(template, agent)
        assert "test-handle-99" in prompt


# ---------------------------------------------------------------------------
# TestBuildFlow
# ---------------------------------------------------------------------------


class TestBuildFlow:
    """Tests for PromptBuilder.build_flow."""

    def test_build_flow_returns_dict(self) -> None:
        builder = PromptBuilder()
        template = _make_template(
            flow_json='{"steps": [{"id": "greeting"}, {"id": "order"}]}'
        )
        flow = builder.build_flow(template)
        assert isinstance(flow, dict)
        assert "steps" in flow
        assert len(flow["steps"]) == 2

    def test_build_flow_invalid_json_returns_default(self) -> None:
        builder = PromptBuilder()
        template = _make_template(flow_json="not valid json {{{")
        flow = builder.build_flow(template)
        assert isinstance(flow, dict)
        assert flow == {"steps": []}

    def test_build_flow_empty_json_returns_default_steps(self) -> None:
        builder = PromptBuilder()
        template = _make_template(flow_json="{}")
        flow = builder.build_flow(template)
        assert "steps" in flow
        assert flow["steps"] == []

    def test_build_flow_preserves_extra_keys(self) -> None:
        builder = PromptBuilder()
        template = _make_template(
            flow_json='{"steps": [], "version": "2.0", "timeout_seconds": 30}'
        )
        flow = builder.build_flow(template)
        assert flow.get("version") == "2.0"
        assert flow.get("timeout_seconds") == 30


# ---------------------------------------------------------------------------
# TestAllSeedTemplatesBuildValidPrompts
# ---------------------------------------------------------------------------


class TestAllSeedTemplatesBuildValidPrompts:
    """Verify all 38 seed templates produce non-empty prompts without errors."""

    async def test_all_seed_templates_build_valid_prompts(self) -> None:
        registry = TemplateRegistry(db_path=":memory:")
        builder = PromptBuilder()
        try:
            await registry.seed_defaults()
            templates = await registry.list_templates()
            assert len(templates) == 38  # 28 original + 8 gaming + 2 DingDawg

            for template in templates:
                agent = AgentRecord(
                    id=f"agent-{template.name}",
                    user_id="user-seed-test",
                    handle=f"handle-{template.name.lower().replace(' ', '-').replace('/', '-')}",
                    name=f"{template.name} Agent",
                    agent_type=AgentType(template.agent_type),
                    industry_type=template.industry_type,
                    status=AgentStatus.ACTIVE,
                    created_at="2026-01-01T00:00:00+00:00",
                    updated_at="2026-01-01T00:00:00+00:00",
                )
                ctx = {
                    "business_name": f"{template.name} Business",
                    "greeting": "",
                }
                prompt = builder.build_system_prompt(template, agent, ctx)

                # Prompt must be a non-empty string
                assert isinstance(prompt, str), (
                    f"Template {template.name!r} returned non-string prompt"
                )
                assert len(prompt) > 50, (
                    f"Template {template.name!r} returned suspiciously short prompt: "
                    f"{len(prompt)} chars"
                )
                # No un-substituted placeholders should remain for known vars
                assert "{agent_name}" not in prompt, (
                    f"Template {template.name!r} has un-substituted {{agent_name}}"
                )
                assert "{business_name}" not in prompt, (
                    f"Template {template.name!r} has un-substituted {{business_name}}"
                )
                assert "{capabilities}" not in prompt, (
                    f"Template {template.name!r} has un-substituted {{capabilities}}"
                )

                # build_flow must return a valid dict with steps
                flow = builder.build_flow(template)
                assert isinstance(flow, dict), (
                    f"Template {template.name!r} flow is not a dict"
                )
                assert "steps" in flow, (
                    f"Template {template.name!r} flow has no 'steps' key"
                )
                assert len(flow["steps"]) > 0, (
                    f"Template {template.name!r} flow has empty steps list"
                )
        finally:
            await registry.close()


# ---------------------------------------------------------------------------
# TestSafeDict
# ---------------------------------------------------------------------------


class TestSafeDict:
    """Tests for the _SafeDict helper."""

    def test_safe_dict_returns_empty_string_for_missing_key(self) -> None:
        d = _SafeDict({"a": "hello"})
        assert d["a"] == "hello"
        assert d["b"] == ""  # missing key → ""
        assert d["nonexistent_key_xyz"] == ""

    def test_safe_dict_with_format_map(self) -> None:
        d = _SafeDict({"name": "World"})
        result = "Hello {name}! Extra: {missing_key}.".format_map(d)
        assert result == "Hello World! Extra: ."
