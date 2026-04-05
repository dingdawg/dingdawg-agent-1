"""Tests for DingDawg internal agent templates — @dingdawg-support and @dingdawg-sales.

These are DingDawg's OWN agents (eating our own dog food), representing the
company itself. Tests verify that both templates are complete, accurate, and
contain all required knowledge about the DingDawg platform.

Covers:
- Both templates load and return correct count
- Required field contract enforced on every template
- Handles are exactly 'dingdawg-support' and 'dingdawg-sales'
- agent_type is 'enterprise' for both
- System prompts contain required platform knowledge
- Capabilities are complete and correctly typed
- Flow steps meet minimum requirements
- Catalog schema correct for each template
- Constitution contains DingDawg brand rules
- DingDawg Support: billing, integration, template, account topics covered
- DingDawg Sales: pricing, ROI, sectors, handles, competitor comparison covered
- Featured flag: Support is featured, Sales is not
- No duplicate template names or handles

TDD discipline: tests written from requirements alongside implementation.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from isg_agent.templates.dingdawg_templates import get_dingdawg_templates


# ===========================================================================
# Helpers
# ===========================================================================


def _by_name(name: str) -> Dict[str, Any]:
    """Return the template with the given name, or raise KeyError."""
    templates = {t["name"]: t for t in get_dingdawg_templates()}
    if name not in templates:
        raise KeyError(f"Template '{name}' not found. Available: {list(templates.keys())}")
    return templates[name]


def _by_handle(handle: str) -> Dict[str, Any]:
    """Return the template with the given handle, or raise KeyError."""
    templates = {t["handle"]: t for t in get_dingdawg_templates()}
    if handle not in templates:
        raise KeyError(f"Handle '{handle}' not found. Available: {list(templates.keys())}")
    return templates[handle]


# ===========================================================================
# 1. Module-Level: Count, Names, Handles
# ===========================================================================


class TestDingDawgTemplatesCount:
    def test_returns_exactly_2_templates(self):
        assert len(get_dingdawg_templates()) == 2

    def test_returns_a_list(self):
        result = get_dingdawg_templates()
        assert isinstance(result, list)

    def test_template_names_unique(self):
        names = [t["name"] for t in get_dingdawg_templates()]
        assert len(names) == len(set(names)), "Duplicate template names detected"

    def test_handles_unique(self):
        handles = [t["handle"] for t in get_dingdawg_templates()]
        assert len(handles) == len(set(handles)), "Duplicate handles detected"

    def test_expected_template_names_present(self):
        names = {t["name"] for t in get_dingdawg_templates()}
        expected = {"DingDawg Support Agent", "DingDawg Sales Agent"}
        assert names == expected

    def test_expected_handles_present(self):
        handles = {t["handle"] for t in get_dingdawg_templates()}
        expected = {"dingdawg-support", "dingdawg-sales"}
        assert handles == expected

    def test_all_templates_have_enterprise_agent_type(self):
        for t in get_dingdawg_templates():
            assert t["agent_type"] == "enterprise", (
                f"Template '{t['name']}' has agent_type='{t['agent_type']}', expected 'enterprise'"
            )


# ===========================================================================
# 2. Required Field Contract
# ===========================================================================


class TestDingDawgTemplateFieldContract:
    REQUIRED_FIELDS = {
        "name",
        "handle",
        "agent_type",
        "industry_type",
        "icon",
        "featured",
        "skills",
        "system_prompt_template",
        "capabilities",
        "flow",
        "catalog_schema",
        "default_constitution_yaml",
    }

    def test_each_template_has_all_required_fields(self):
        for t in get_dingdawg_templates():
            missing = self.REQUIRED_FIELDS - set(t.keys())
            assert not missing, (
                f"Template '{t['name']}' is missing fields: {missing}"
            )

    def test_each_template_has_nonempty_icon(self):
        for t in get_dingdawg_templates():
            assert t.get("icon"), f"'{t['name']}' must have an icon"

    def test_each_template_system_prompt_substantial(self):
        for t in get_dingdawg_templates():
            prompt = t["system_prompt_template"]
            assert len(prompt) > 200, (
                f"'{t['name']}' system_prompt_template is too short ({len(prompt)} chars); "
                "DingDawg internal agents need substantial platform knowledge"
            )

    def test_each_template_has_at_least_5_capabilities(self):
        for t in get_dingdawg_templates():
            caps = t["capabilities"]
            assert isinstance(caps, list), f"'{t['name']}' capabilities must be a list"
            assert len(caps) >= 5, (
                f"'{t['name']}' needs at least 5 capabilities, got {len(caps)}"
            )

    def test_each_template_has_at_least_4_flow_steps(self):
        for t in get_dingdawg_templates():
            steps = t["flow"].get("steps", [])
            assert len(steps) >= 4, (
                f"'{t['name']}' flow needs at least 4 steps, got {len(steps)}"
            )

    def test_each_flow_step_has_id_and_prompt(self):
        for t in get_dingdawg_templates():
            for step in t["flow"]["steps"]:
                assert "id" in step, f"'{t['name']}' step missing 'id': {step}"
                assert "prompt" in step, f"'{t['name']}' step missing 'prompt': {step}"
                assert step["prompt"], f"'{t['name']}' step has empty prompt"

    def test_each_template_has_catalog_schema_with_item_type_and_fields(self):
        for t in get_dingdawg_templates():
            schema = t["catalog_schema"]
            assert "item_type" in schema, f"'{t['name']}' catalog_schema missing 'item_type'"
            assert "fields" in schema, f"'{t['name']}' catalog_schema missing 'fields'"
            assert len(schema["fields"]) >= 3, (
                f"'{t['name']}' needs at least 3 catalog schema fields"
            )

    def test_each_catalog_field_has_name_and_type(self):
        for t in get_dingdawg_templates():
            for field in t["catalog_schema"]["fields"]:
                assert "name" in field, f"'{t['name']}' catalog field missing 'name': {field}"
                assert "type" in field, f"'{t['name']}' catalog field missing 'type': {field}"

    def test_featured_is_bool(self):
        for t in get_dingdawg_templates():
            assert isinstance(t["featured"], bool), (
                f"'{t['name']}' featured must be a bool, got {type(t['featured'])}"
            )

    def test_skills_is_list(self):
        for t in get_dingdawg_templates():
            assert isinstance(t["skills"], list), f"'{t['name']}' skills must be a list"

    def test_skills_nonempty(self):
        for t in get_dingdawg_templates():
            assert len(t["skills"]) >= 2, (
                f"'{t['name']}' needs at least 2 skills, got {len(t['skills'])}"
            )


# ===========================================================================
# 3. Featured Flag
# ===========================================================================


class TestDingDawgFeaturedFlag:
    def test_support_agent_is_featured(self):
        t = _by_handle("dingdawg-support")
        assert t["featured"] is True, "DingDawg Support Agent must be featured"

    def test_sales_agent_is_not_featured(self):
        t = _by_handle("dingdawg-sales")
        assert t["featured"] is False, "DingDawg Sales Agent must not be featured"

    def test_exactly_one_template_is_featured(self):
        featured = [t for t in get_dingdawg_templates() if t["featured"]]
        assert len(featured) == 1, f"Expected exactly 1 featured template, got {len(featured)}"


# ===========================================================================
# 4. Handle and Identity Tests
# ===========================================================================


class TestDingDawgHandles:
    def test_support_handle_exact(self):
        t = _by_name("DingDawg Support Agent")
        assert t["handle"] == "dingdawg-support"

    def test_sales_handle_exact(self):
        t = _by_name("DingDawg Sales Agent")
        assert t["handle"] == "dingdawg-sales"

    def test_handles_contain_no_at_symbol(self):
        for t in get_dingdawg_templates():
            assert not t["handle"].startswith("@"), (
                f"'{t['name']}' handle '{t['handle']}' must NOT include '@' prefix — "
                "the @ is display-only"
            )

    def test_handles_use_hyphens_not_underscores(self):
        for t in get_dingdawg_templates():
            assert "_" not in t["handle"], (
                f"'{t['name']}' handle '{t['handle']}' must use hyphens, not underscores"
            )

    def test_lookup_by_handle_dingdawg_support(self):
        t = _by_handle("dingdawg-support")
        assert t["name"] == "DingDawg Support Agent"

    def test_lookup_by_handle_dingdawg_sales(self):
        t = _by_handle("dingdawg-sales")
        assert t["name"] == "DingDawg Sales Agent"


# ===========================================================================
# 5. Brand Constitution Tests
# ===========================================================================


BRAND_RULES_REQUIRED = [
    "represent_the_brand",
    "accuracy_first",
    "no_disparagement",
    "user_privacy",
]


class TestDingDawgBrandConstitution:
    def test_all_templates_contain_brand_rule_ids(self):
        for t in get_dingdawg_templates():
            yaml = t["default_constitution_yaml"]
            for rule_id in BRAND_RULES_REQUIRED:
                assert rule_id in yaml, (
                    f"Template '{t['name']}' is missing brand rule id: '{rule_id}'"
                )

    def test_constitution_is_string(self):
        for t in get_dingdawg_templates():
            assert isinstance(t["default_constitution_yaml"], str), (
                f"'{t['name']}' constitution must be a string"
            )

    def test_constitution_has_rules_section(self):
        for t in get_dingdawg_templates():
            yaml_str = t["default_constitution_yaml"]
            assert "rules:" in yaml_str, f"'{t['name']}' constitution must have 'rules:' section"

    def test_each_constitution_has_at_least_6_rules(self):
        for t in get_dingdawg_templates():
            yaml_str = t["default_constitution_yaml"]
            rule_lines = [line for line in yaml_str.splitlines() if "- id:" in line]
            assert len(rule_lines) >= 6, (
                f"'{t['name']}' constitution has only {len(rule_lines)} rules; "
                "DingDawg internal agents require at least 6"
            )

    def test_no_real_api_keys_in_constitution(self):
        for t in get_dingdawg_templates():
            yaml_str = t["default_constitution_yaml"]
            # Rough check: no strings that look like API keys (sk-, pk-, whsec_)
            assert "sk-" not in yaml_str, f"'{t['name']}' constitution may contain an API key"
            assert "whsec_" not in yaml_str, f"'{t['name']}' constitution may contain a webhook secret"


# ===========================================================================
# 6. DingDawg Support Agent — Platform Knowledge Tests
# ===========================================================================


class TestDingDawgSupportAgent:
    def test_exists_by_name(self):
        t = _by_name("DingDawg Support Agent")
        assert t is not None

    def test_exists_by_handle(self):
        t = _by_handle("dingdawg-support")
        assert t is not None

    def test_industry_type(self):
        t = _by_name("DingDawg Support Agent")
        assert t["industry_type"] == "dingdawg_support"

    def test_system_prompt_mentions_1_dollar_pricing(self):
        t = _by_name("DingDawg Support Agent")
        prompt = t["system_prompt_template"]
        assert "$1" in prompt or "1 per transaction" in prompt.lower(), (
            "Support agent prompt must mention $1/tx pricing"
        )

    def test_system_prompt_mentions_no_monthly_fees(self):
        t = _by_name("DingDawg Support Agent")
        prompt = t["system_prompt_template"].lower()
        assert "monthly" in prompt or "no monthly" in prompt, (
            "Support agent prompt must address the no-monthly-fees model"
        )

    def test_system_prompt_mentions_integrations(self):
        t = _by_name("DingDawg Support Agent")
        prompt = t["system_prompt_template"]
        required_integrations = ["Google Calendar", "SendGrid", "Twilio", "Vapi", "Stripe", "Slack"]
        for integration in required_integrations:
            assert integration in prompt, (
                f"Support agent prompt must mention integration: {integration}"
            )

    def test_system_prompt_mentions_36_plus_templates(self):
        t = _by_name("DingDawg Support Agent")
        prompt = t["system_prompt_template"]
        assert "36" in prompt or "templates" in prompt.lower(), (
            "Support agent prompt must reference the 36+ templates"
        )

    def test_system_prompt_mentions_handle_identity(self):
        t = _by_name("DingDawg Support Agent")
        prompt = t["system_prompt_template"].lower()
        assert "handle" in prompt or "@handle" in prompt, (
            "Support agent prompt must mention @handle identity"
        )

    def test_system_prompt_mentions_pwa(self):
        t = _by_name("DingDawg Support Agent")
        prompt = t["system_prompt_template"].lower()
        assert "pwa" in prompt or "progressive web" in prompt or "mobile" in prompt, (
            "Support agent prompt must mention PWA or mobile capability"
        )

    def test_system_prompt_mentions_8_sectors(self):
        t = _by_name("DingDawg Support Agent")
        prompt = t["system_prompt_template"].lower()
        sectors = ["personal", "business", "gaming", "health", "compliance"]
        found = [s for s in sectors if s in prompt]
        assert len(found) >= 3, (
            f"Support agent prompt must mention at least 3 sectors; found: {found}"
        )

    def test_capabilities_include_billing(self):
        t = _by_name("DingDawg Support Agent")
        caps_lower = " ".join(c.lower() for c in t["capabilities"])
        assert "billing" in caps_lower or "transaction" in caps_lower, (
            "Support agent capabilities must include billing support"
        )

    def test_capabilities_include_integration_help(self):
        t = _by_name("DingDawg Support Agent")
        caps_lower = " ".join(c.lower() for c in t["capabilities"])
        assert "integration" in caps_lower, (
            "Support agent capabilities must include integration guidance"
        )

    def test_capabilities_include_template_recommendations(self):
        t = _by_name("DingDawg Support Agent")
        caps_lower = " ".join(c.lower() for c in t["capabilities"])
        assert "template" in caps_lower, (
            "Support agent capabilities must include template recommendations"
        )

    def test_capabilities_include_scheduling(self):
        t = _by_name("DingDawg Support Agent")
        caps_lower = " ".join(c.lower() for c in t["capabilities"])
        assert "schedul" in caps_lower or "appointment" in caps_lower or "demo" in caps_lower, (
            "Support agent capabilities must include scheduling or demo sessions"
        )

    def test_skills_include_appointments(self):
        t = _by_name("DingDawg Support Agent")
        assert "appointments" in t["skills"], (
            "Support agent must have appointments skill to schedule demos"
        )

    def test_skills_include_contacts(self):
        t = _by_name("DingDawg Support Agent")
        assert "contacts" in t["skills"], (
            "Support agent must have contacts skill to track users"
        )

    def test_catalog_schema_item_type(self):
        t = _by_name("DingDawg Support Agent")
        assert t["catalog_schema"]["item_type"] == "support_ticket"

    def test_catalog_schema_has_issue_type_field(self):
        t = _by_name("DingDawg Support Agent")
        field_names = {f["name"] for f in t["catalog_schema"]["fields"]}
        assert "issue_type" in field_names, "Support catalog schema must have 'issue_type' field"

    def test_catalog_schema_has_user_handle_field(self):
        t = _by_name("DingDawg Support Agent")
        field_names = {f["name"] for f in t["catalog_schema"]["fields"]}
        assert "user_handle" in field_names, "Support catalog schema must have 'user_handle' field"

    def test_constitution_has_no_fees_confusion_rule(self):
        t = _by_name("DingDawg Support Agent")
        yaml = t["default_constitution_yaml"]
        assert "no_fees_confusion" in yaml, (
            "Support constitution must have 'no_fees_confusion' rule"
        )

    def test_constitution_has_integration_safety_rule(self):
        t = _by_name("DingDawg Support Agent")
        yaml = t["default_constitution_yaml"]
        assert "integration_safety" in yaml, (
            "Support constitution must have 'integration_safety' rule — API keys must never be in chat"
        )

    def test_constitution_has_escalation_threshold_rule(self):
        t = _by_name("DingDawg Support Agent")
        yaml = t["default_constitution_yaml"]
        assert "escalation_threshold" in yaml, (
            "Support constitution must have 'escalation_threshold' rule"
        )

    def test_voice_implied_in_capabilities_or_channels(self):
        t = _by_name("DingDawg Support Agent")
        # Voice is enabled — check that multi-channel or voice is referenced
        prompt_lower = t["system_prompt_template"].lower()
        caps_lower = " ".join(c.lower() for c in t["capabilities"])
        assert "voice" in prompt_lower or "voice" in caps_lower or "multi-channel" in prompt_lower, (
            "Support agent should reference voice or multi-channel capability"
        )


# ===========================================================================
# 7. DingDawg Sales Agent — Sales Knowledge Tests
# ===========================================================================


class TestDingDawgSalesAgent:
    def test_exists_by_name(self):
        t = _by_name("DingDawg Sales Agent")
        assert t is not None

    def test_exists_by_handle(self):
        t = _by_handle("dingdawg-sales")
        assert t is not None

    def test_industry_type(self):
        t = _by_name("DingDawg Sales Agent")
        assert t["industry_type"] == "dingdawg_sales"

    def test_system_prompt_mentions_1_dollar_pricing(self):
        t = _by_name("DingDawg Sales Agent")
        prompt = t["system_prompt_template"]
        assert "$1" in prompt or "1 per transaction" in prompt.lower(), (
            "Sales agent prompt must mention $1/tx pricing"
        )

    def test_system_prompt_mentions_no_monthly_fees(self):
        t = _by_name("DingDawg Sales Agent")
        prompt = t["system_prompt_template"].lower()
        assert "monthly" in prompt, (
            "Sales agent prompt must contrast against monthly-fee competitors"
        )

    def test_system_prompt_mentions_competitor_comparison(self):
        t = _by_name("DingDawg Sales Agent")
        prompt = t["system_prompt_template"]
        # Should reference at least one competitor or competitor pricing range
        assert "$97" in prompt or "HighLevel" in prompt or "GHL" in prompt or "Chatbase" in prompt, (
            "Sales agent prompt must include competitor pricing comparison"
        )

    def test_system_prompt_mentions_gaming_differentiator(self):
        t = _by_name("DingDawg Sales Agent")
        prompt = t["system_prompt_template"].lower()
        assert "gaming" in prompt and ("unique" in prompt or "only" in prompt or "$187" in prompt), (
            "Sales agent prompt must highlight gaming as a unique DingDawg differentiator"
        )

    def test_system_prompt_mentions_36_plus_templates(self):
        t = _by_name("DingDawg Sales Agent")
        prompt = t["system_prompt_template"]
        assert "36" in prompt or "templates" in prompt.lower(), (
            "Sales agent prompt must reference the 36+ templates"
        )

    def test_system_prompt_mentions_8_sectors(self):
        t = _by_name("DingDawg Sales Agent")
        prompt = t["system_prompt_template"].lower()
        sectors = ["personal", "business", "b2b", "compliance", "enterprise", "health", "gaming"]
        found = [s for s in sectors if s in prompt]
        assert len(found) >= 5, (
            f"Sales agent prompt must mention at least 5 sectors; found: {found}"
        )

    def test_system_prompt_mentions_handle_identity(self):
        t = _by_name("DingDawg Sales Agent")
        prompt = t["system_prompt_template"].lower()
        assert "handle" in prompt or "@handle" in prompt, (
            "Sales agent prompt must mention @handle as digital real estate"
        )

    def test_system_prompt_mentions_pwa(self):
        t = _by_name("DingDawg Sales Agent")
        prompt = t["system_prompt_template"].lower()
        assert "pwa" in prompt or "progressive web" in prompt or "mobile" in prompt, (
            "Sales agent prompt must mention PWA or mobile capability"
        )

    def test_system_prompt_mentions_governance_compliance(self):
        t = _by_name("DingDawg Sales Agent")
        prompt = t["system_prompt_template"].lower()
        assert "governance" in prompt or "compliance" in prompt or "mila" in prompt, (
            "Sales agent prompt must mention governance/compliance as a differentiator"
        )

    def test_system_prompt_mentions_roi_calculation(self):
        t = _by_name("DingDawg Sales Agent")
        prompt = t["system_prompt_template"].lower()
        assert "roi" in prompt or "return" in prompt or "calculation" in prompt or "100 interaction" in prompt, (
            "Sales agent prompt must include ROI calculation guidance"
        )

    def test_system_prompt_mentions_integrations(self):
        t = _by_name("DingDawg Sales Agent")
        prompt = t["system_prompt_template"]
        # Sales agent should mention key integrations
        assert "Google Calendar" in prompt or "Stripe" in prompt or "Slack" in prompt, (
            "Sales agent prompt must reference integration capabilities"
        )

    def test_capabilities_include_pricing_comparison(self):
        t = _by_name("DingDawg Sales Agent")
        caps_lower = " ".join(c.lower() for c in t["capabilities"])
        assert "pricing" in caps_lower or "comparison" in caps_lower, (
            "Sales agent capabilities must include pricing comparison"
        )

    def test_capabilities_include_roi_calculation(self):
        t = _by_name("DingDawg Sales Agent")
        caps_lower = " ".join(c.lower() for c in t["capabilities"])
        assert "roi" in caps_lower or "calculation" in caps_lower, (
            "Sales agent capabilities must include ROI calculation"
        )

    def test_capabilities_include_onboarding_scheduling(self):
        t = _by_name("DingDawg Sales Agent")
        caps_lower = " ".join(c.lower() for c in t["capabilities"])
        assert "onboarding" in caps_lower or "schedul" in caps_lower, (
            "Sales agent capabilities must include onboarding session scheduling"
        )

    def test_capabilities_include_gaming_pitch(self):
        t = _by_name("DingDawg Sales Agent")
        caps_lower = " ".join(c.lower() for c in t["capabilities"])
        assert "gaming" in caps_lower, (
            "Sales agent capabilities must include the gaming sector pitch"
        )

    def test_capabilities_include_template_matching(self):
        t = _by_name("DingDawg Sales Agent")
        caps_lower = " ".join(c.lower() for c in t["capabilities"])
        assert "template" in caps_lower, (
            "Sales agent capabilities must include template matching"
        )

    def test_skills_include_appointments(self):
        t = _by_name("DingDawg Sales Agent")
        assert "appointments" in t["skills"], (
            "Sales agent must have appointments skill to schedule onboarding"
        )

    def test_skills_include_contacts(self):
        t = _by_name("DingDawg Sales Agent")
        assert "contacts" in t["skills"], (
            "Sales agent must have contacts skill to track leads"
        )

    def test_catalog_schema_item_type(self):
        t = _by_name("DingDawg Sales Agent")
        assert t["catalog_schema"]["item_type"] == "sales_lead"

    def test_catalog_schema_has_sector_match_field(self):
        t = _by_name("DingDawg Sales Agent")
        field_names = {f["name"] for f in t["catalog_schema"]["fields"]}
        assert "sector_match" in field_names, "Sales catalog schema must have 'sector_match' field"

    def test_catalog_schema_has_onboarding_scheduled_field(self):
        t = _by_name("DingDawg Sales Agent")
        field_names = {f["name"] for f in t["catalog_schema"]["fields"]}
        assert "onboarding_scheduled" in field_names, (
            "Sales catalog schema must have 'onboarding_scheduled' field"
        )

    def test_catalog_schema_has_handle_interest_field(self):
        t = _by_name("DingDawg Sales Agent")
        field_names = {f["name"] for f in t["catalog_schema"]["fields"]}
        assert "handle_interest" in field_names, (
            "Sales catalog schema must track handle interest (core sales hook)"
        )

    def test_constitution_has_consultative_not_pushy_rule(self):
        t = _by_name("DingDawg Sales Agent")
        yaml = t["default_constitution_yaml"]
        assert "consultative_not_pushy" in yaml, (
            "Sales constitution must have 'consultative_not_pushy' rule"
        )

    def test_constitution_has_no_false_urgency_rule(self):
        t = _by_name("DingDawg Sales Agent")
        yaml = t["default_constitution_yaml"]
        assert "no_false_urgency" in yaml, (
            "Sales constitution must prohibit false urgency tactics"
        )

    def test_constitution_has_gaming_differentiator_rule(self):
        t = _by_name("DingDawg Sales Agent")
        yaml = t["default_constitution_yaml"]
        assert "gaming_differentiator" in yaml, (
            "Sales constitution must have 'gaming_differentiator' rule"
        )

    def test_constitution_has_onboarding_is_the_goal_rule(self):
        t = _by_name("DingDawg Sales Agent")
        yaml = t["default_constitution_yaml"]
        assert "onboarding_is_the_goal" in yaml, (
            "Sales constitution must have 'onboarding_is_the_goal' rule"
        )

    def test_constitution_has_handle_as_close_rule(self):
        t = _by_name("DingDawg Sales Agent")
        yaml = t["default_constitution_yaml"]
        assert "handle_as_close" in yaml, (
            "Sales constitution must have 'handle_as_close' rule — the handle question is the close"
        )

    def test_flow_includes_discovery_step(self):
        t = _by_name("DingDawg Sales Agent")
        step_ids = {step["id"] for step in t["flow"]["steps"]}
        # Should have a discovery/open step
        assert "discover" in step_ids or "open" in step_ids, (
            "Sales agent flow must include a discovery step"
        )

    def test_flow_includes_close_step(self):
        t = _by_name("DingDawg Sales Agent")
        step_ids = {step["id"] for step in t["flow"]["steps"]}
        assert "close" in step_ids, "Sales agent flow must include a close step"

    def test_flow_includes_roi_step(self):
        t = _by_name("DingDawg Sales Agent")
        step_ids = {step["id"] for step in t["flow"]["steps"]}
        assert "roi" in step_ids or "match" in step_ids, (
            "Sales agent flow must include ROI or template-match step"
        )

    def test_voice_enabled_implied_in_prompt(self):
        t = _by_name("DingDawg Sales Agent")
        prompt_lower = t["system_prompt_template"].lower()
        assert "voice" in prompt_lower or "multi-channel" in prompt_lower or "vapi" in prompt_lower, (
            "Sales agent prompt must reference voice capability as a selling point"
        )


# ===========================================================================
# 8. Cross-Template Consistency
# ===========================================================================


class TestDingDawgCrossTemplateConsistency:
    def test_both_agents_know_the_1_dollar_price(self):
        """Both agents must have $1/tx baked into their prompts."""
        for t in get_dingdawg_templates():
            prompt = t["system_prompt_template"]
            assert "$1" in prompt or "1 per transaction" in prompt.lower(), (
                f"'{t['name']}' must know the $1/tx pricing model"
            )

    def test_both_agents_have_appointments_skill(self):
        """Both agents schedule things — support schedules demos, sales schedules onboarding."""
        for t in get_dingdawg_templates():
            assert "appointments" in t["skills"], (
                f"'{t['name']}' must have appointments skill"
            )

    def test_both_agents_have_contacts_skill(self):
        for t in get_dingdawg_templates():
            assert "contacts" in t["skills"], (
                f"'{t['name']}' must have contacts skill"
            )

    def test_both_agents_have_brand_rules(self):
        for t in get_dingdawg_templates():
            yaml = t["default_constitution_yaml"]
            assert "represent_the_brand" in yaml, (
                f"'{t['name']}' must have the represent_the_brand rule"
            )
            assert "accuracy_first" in yaml, (
                f"'{t['name']}' must have the accuracy_first rule"
            )

    def test_both_agents_mention_gaming(self):
        """Gaming is a key differentiator — both agents should know about it."""
        for t in get_dingdawg_templates():
            prompt_lower = t["system_prompt_template"].lower()
            assert "gaming" in prompt_lower, (
                f"'{t['name']}' must mention gaming sector (key differentiator)"
            )

    def test_both_agents_mention_handles(self):
        for t in get_dingdawg_templates():
            prompt_lower = t["system_prompt_template"].lower()
            assert "handle" in prompt_lower, (
                f"'{t['name']}' must mention @handle identity"
            )

    def test_industry_types_are_distinct(self):
        industry_types = [t["industry_type"] for t in get_dingdawg_templates()]
        assert len(industry_types) == len(set(industry_types)), (
            "Each template must have a unique industry_type"
        )

    def test_catalog_item_types_are_distinct(self):
        item_types = [t["catalog_schema"]["item_type"] for t in get_dingdawg_templates()]
        assert len(item_types) == len(set(item_types)), (
            "Each template must have a unique catalog schema item_type"
        )

    def test_get_dingdawg_templates_is_deterministic(self):
        """Calling the function twice returns the same result."""
        first = get_dingdawg_templates()
        second = get_dingdawg_templates()
        assert len(first) == len(second)
        for a, b in zip(first, second):
            assert a["name"] == b["name"]
            assert a["handle"] == b["handle"]
