"""Tests for the Community sector — 9th agent type + 8 community templates.

Covers:
- AgentType enum and VALID_AGENT_TYPES contain 'community'
- 8 community templates present and valid
- Dignity-first constitution rules present in all templates
- Restaurant-community templates (Taqueria, Bodega, Haitian, Pho)
- Gaming-community template (Community Gaming Hub)
- General community templates (Immigrant Entrepreneur, Food Pantry, Nail Salon)
- Template registry field contract enforced
- Bilingual / multilingual system prompt markers

TDD discipline: tests written from requirements BEFORE implementation.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from isg_agent.agents.agent_types import VALID_AGENT_TYPES, AgentType
from isg_agent.templates.community_templates import get_community_templates


# ===========================================================================
# Fixtures
# ===========================================================================


def _by_name(name: str) -> Dict[str, Any]:
    """Return the template with the given name, or raise KeyError."""
    templates = {t["name"]: t for t in get_community_templates()}
    return templates[name]


# ===========================================================================
# 1. Agent Type Tests
# ===========================================================================


class TestCommunityAgentType:
    def test_community_in_valid_agent_types(self):
        assert "community" in VALID_AGENT_TYPES

    def test_community_enum_value(self):
        assert AgentType.COMMUNITY.value == "community"

    def test_all_9_types_present(self):
        # 9 original types + marketing (added in v29.1) = 10 total
        expected = {
            "personal", "business", "b2b", "a2a",
            "compliance", "enterprise", "health", "gaming", "community",
            "marketing",
        }
        assert expected == set(VALID_AGENT_TYPES)

    def test_community_agent_type_enum_construction(self):
        t = AgentType("community")
        assert t == AgentType.COMMUNITY


# ===========================================================================
# 2. Community Templates — Count and Names
# ===========================================================================


class TestCommunityTemplatesCount:
    def test_returns_8_templates(self):
        assert len(get_community_templates()) == 8

    def test_all_templates_agent_type_community(self):
        for t in get_community_templates():
            assert t["agent_type"] == "community", (
                f"Template '{t['name']}' has agent_type='{t['agent_type']}', expected 'community'"
            )

    def test_template_names_unique(self):
        names = [t["name"] for t in get_community_templates()]
        assert len(names) == len(set(names)), "Duplicate template names detected"

    def test_expected_template_names_present(self):
        names = {t["name"] for t in get_community_templates()}
        expected = {
            "Taqueria Agent",
            "Bodega Agent",
            "Haitian Restaurant Agent",
            "Pho Shop Agent",
            "Community Gaming Hub",
            "Immigrant Entrepreneur Agent",
            "Community Food Pantry",
            "Vietnamese Nail Salon Agent",
        }
        assert names == expected


# ===========================================================================
# 3. Required Field Contract
# ===========================================================================


class TestCommunityTemplateFieldContract:
    REQUIRED_FIELDS = {
        "name",
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
        "primary_language",
        "supported_languages",
    }

    def test_each_template_has_required_fields(self):
        for t in get_community_templates():
            missing = self.REQUIRED_FIELDS - set(t.keys())
            assert not missing, (
                f"Template '{t['name']}' is missing fields: {missing}"
            )

    def test_each_template_has_icon(self):
        for t in get_community_templates():
            assert t.get("icon"), f"'{t['name']}' must have an icon"

    def test_each_template_system_prompt_nonempty(self):
        for t in get_community_templates():
            assert len(t["system_prompt_template"]) > 80, (
                f"'{t['name']}' system_prompt_template is too short"
            )

    def test_each_template_has_at_least_4_capabilities(self):
        for t in get_community_templates():
            caps = t["capabilities"]
            assert isinstance(caps, list), f"'{t['name']}' capabilities must be a list"
            assert len(caps) >= 4, f"'{t['name']}' needs at least 4 capabilities"

    def test_each_template_has_at_least_3_flow_steps(self):
        for t in get_community_templates():
            steps = t["flow"].get("steps", [])
            assert len(steps) >= 3, f"'{t['name']}' flow needs at least 3 steps"

    def test_each_template_has_catalog_schema(self):
        for t in get_community_templates():
            schema = t["catalog_schema"]
            assert "item_type" in schema, f"'{t['name']}' catalog_schema missing item_type"
            assert "fields" in schema, f"'{t['name']}' catalog_schema missing fields"
            assert len(schema["fields"]) >= 2, f"'{t['name']}' needs at least 2 catalog fields"

    def test_each_template_featured_is_bool(self):
        for t in get_community_templates():
            assert isinstance(t["featured"], bool), (
                f"'{t['name']}' featured must be a bool, got {type(t['featured'])}"
            )

    def test_skills_are_lists(self):
        for t in get_community_templates():
            assert isinstance(t["skills"], list), f"'{t['name']}' skills must be a list"

    def test_supported_languages_nonempty(self):
        for t in get_community_templates():
            langs = t["supported_languages"]
            assert isinstance(langs, list), f"'{t['name']}' supported_languages must be a list"
            assert len(langs) >= 1, f"'{t['name']}' needs at least one supported language"


# ===========================================================================
# 4. Dignity-First Constitution
# ===========================================================================


DIGNITY_RULES = [
    "Never assume financial status from language or ethnicity",
    "Always offer service in the customer's preferred language",
    "Treat every business owner as the expert of their own business",
    "Privacy-first: never share customer data across businesses",
]


class TestDignityFirstConstitution:
    def test_all_templates_contain_dignity_rules(self):
        for t in get_community_templates():
            yaml = t["default_constitution_yaml"]
            for rule in DIGNITY_RULES:
                assert rule in yaml, (
                    f"Template '{t['name']}' is missing dignity rule: '{rule}'"
                )

    def test_constitution_is_valid_yaml_string(self):
        for t in get_community_templates():
            yaml_str = t["default_constitution_yaml"]
            assert isinstance(yaml_str, str), f"'{t['name']}' constitution must be a string"
            assert "rules:" in yaml_str, f"'{t['name']}' constitution must have 'rules:' section"

    def test_each_constitution_has_at_least_5_rules(self):
        for t in get_community_templates():
            yaml_str = t["default_constitution_yaml"]
            # Count lines starting with '  - id:'
            rule_lines = [l for l in yaml_str.splitlines() if "- id:" in l]
            assert len(rule_lines) >= 5, (
                f"'{t['name']}' constitution has only {len(rule_lines)} rules; need at least 5"
            )


# ===========================================================================
# 5. Restaurant Community Templates
# ===========================================================================


class TestTaqueriaAgent:
    def test_exists(self):
        t = _by_name("Taqueria Agent")
        assert t["industry_type"] == "restaurant_taqueria"

    def test_primary_language_spanish(self):
        t = _by_name("Taqueria Agent")
        assert t["primary_language"] == "es"

    def test_spanish_in_supported_languages(self):
        t = _by_name("Taqueria Agent")
        assert "es" in t["supported_languages"]

    def test_bilingual_marker_in_system_prompt(self):
        t = _by_name("Taqueria Agent")
        # System prompt should indicate bilingual capability
        prompt = t["system_prompt_template"].lower()
        assert any(kw in prompt for kw in ["spanish", "español", "bilingual", "bilingüe"]), (
            "Taqueria Agent prompt must reference bilingual capability"
        )

    def test_has_quinceañera_catering_capability(self):
        t = _by_name("Taqueria Agent")
        caps_lower = [c.lower() for c in t["capabilities"]]
        assert any("quincea" in c or "catering" in c or "family" in c for c in caps_lower), (
            "Taqueria Agent must mention catering or family-style capability"
        )

    def test_skills_include_orders(self):
        t = _by_name("Taqueria Agent")
        assert "orders" in t["skills"] or "appointments" in t["skills"], (
            "Taqueria Agent needs orders or appointments skill"
        )


class TestBodegaAgent:
    def test_exists(self):
        t = _by_name("Bodega Agent")
        assert t["industry_type"] == "bodega"

    def test_primary_language_spanish(self):
        t = _by_name("Bodega Agent")
        assert t["primary_language"] == "es"

    def test_fiado_in_prompt(self):
        t = _by_name("Bodega Agent")
        assert "fiado" in t["system_prompt_template"].lower(), (
            "Bodega Agent must mention fiado (community credit)"
        )

    def test_has_check_cashing_capability(self):
        t = _by_name("Bodega Agent")
        caps_lower = [c.lower() for c in t["capabilities"]]
        assert any("check" in c or "cash" in c for c in caps_lower), (
            "Bodega Agent must mention check cashing capability"
        )

    def test_has_lottery_or_money_orders_in_capabilities(self):
        t = _by_name("Bodega Agent")
        caps_lower = [c.lower() for c in t["capabilities"]]
        assert any("lottery" in c or "money order" in c for c in caps_lower), (
            "Bodega Agent must mention lottery or money orders"
        )


class TestHaitianRestaurantAgent:
    def test_exists(self):
        t = _by_name("Haitian Restaurant Agent")
        assert t["industry_type"] == "restaurant_haitian"

    def test_primary_language_haitian_creole(self):
        t = _by_name("Haitian Restaurant Agent")
        assert t["primary_language"] == "ht"

    def test_kreyo_or_creole_in_prompt(self):
        t = _by_name("Haitian Restaurant Agent")
        prompt_lower = t["system_prompt_template"].lower()
        assert any(kw in prompt_lower for kw in ["kreyòl", "kreyl", "creole", "haitian"]), (
            "Haitian Restaurant Agent prompt must reference Kreyòl/Creole"
        )

    def test_griot_or_diri_in_capabilities(self):
        t = _by_name("Haitian Restaurant Agent")
        caps_lower = " ".join(c.lower() for c in t["capabilities"])
        assert any(kw in caps_lower for kw in ["griot", "diri", "haitian", "menu"]), (
            "Haitian Restaurant Agent must reference Haitian menu knowledge"
        )


class TestPhoShopAgent:
    def test_exists(self):
        t = _by_name("Pho Shop Agent")
        assert t["industry_type"] == "restaurant_pho"

    def test_primary_language_vietnamese(self):
        t = _by_name("Pho Shop Agent")
        assert t["primary_language"] == "vi"

    def test_vietnamese_in_supported_languages(self):
        t = _by_name("Pho Shop Agent")
        assert "vi" in t["supported_languages"]

    def test_pho_or_banh_mi_in_prompt(self):
        t = _by_name("Pho Shop Agent")
        prompt_lower = t["system_prompt_template"].lower()
        assert any(kw in prompt_lower for kw in ["phở", "pho", "bánh mì", "banh mi"]), (
            "Pho Shop Agent prompt must reference phở or bánh mì"
        )


# ===========================================================================
# 6. Gaming Community Template
# ===========================================================================


class TestCommunityGamingHub:
    def test_exists(self):
        t = _by_name("Community Gaming Hub")
        assert t["industry_type"] == "gaming_community"

    def test_multilingual_support(self):
        t = _by_name("Community Gaming Hub")
        langs = t["supported_languages"]
        assert len(langs) >= 2, "Community Gaming Hub should support multiple languages"

    def test_barbershop_or_church_in_prompt(self):
        t = _by_name("Community Gaming Hub")
        prompt_lower = t["system_prompt_template"].lower()
        assert any(kw in prompt_lower for kw in ["barber", "church", "community", "tournament"]), (
            "Community Gaming Hub must reference community venue context"
        )

    def test_tournament_skill_included(self):
        t = _by_name("Community Gaming Hub")
        assert "tournament" in t["skills"] or "match_tracker" in t["skills"], (
            "Community Gaming Hub needs tournament or match_tracker skill"
        )


# ===========================================================================
# 7. General Community Templates
# ===========================================================================


class TestImmigrantEntrepreneurAgent:
    def test_exists(self):
        t = _by_name("Immigrant Entrepreneur Agent")
        assert t["industry_type"] == "immigrant_entrepreneur"

    def test_multilingual_support(self):
        t = _by_name("Immigrant Entrepreneur Agent")
        langs = t["supported_languages"]
        assert len(langs) >= 3, "Immigrant Entrepreneur Agent needs at least 3 languages"

    def test_permits_or_startup_in_capabilities(self):
        t = _by_name("Immigrant Entrepreneur Agent")
        caps_lower = " ".join(c.lower() for c in t["capabilities"])
        assert any(kw in caps_lower for kw in ["permit", "startup", "business", "sba", "tax"]), (
            "Immigrant Entrepreneur Agent must cover startup/permit capabilities"
        )

    def test_sba_or_small_business_in_prompt(self):
        t = _by_name("Immigrant Entrepreneur Agent")
        prompt_lower = t["system_prompt_template"].lower()
        assert any(kw in prompt_lower for kw in ["sba", "small business", "startup", "permit"]), (
            "Immigrant Entrepreneur Agent must reference SBA or business startup"
        )


class TestCommunityFoodPantry:
    def test_exists(self):
        t = _by_name("Community Food Pantry")
        assert t["industry_type"] == "nonprofit_food_pantry"

    def test_spanish_and_haitian_creole_supported(self):
        t = _by_name("Community Food Pantry")
        langs = t["supported_languages"]
        assert "es" in langs, "Food Pantry must support Spanish"
        assert "ht" in langs, "Food Pantry must support Haitian Creole"

    def test_volunteer_capability(self):
        t = _by_name("Community Food Pantry")
        caps_lower = " ".join(c.lower() for c in t["capabilities"])
        assert "volunteer" in caps_lower, "Food Pantry must mention volunteer management"

    def test_usda_in_constitution(self):
        t = _by_name("Community Food Pantry")
        assert "USDA" in t["default_constitution_yaml"] or "usda" in t["default_constitution_yaml"].lower(), (
            "Food Pantry constitution must reference USDA compliance"
        )

    def test_inventory_in_capabilities(self):
        t = _by_name("Community Food Pantry")
        caps_lower = " ".join(c.lower() for c in t["capabilities"])
        assert "inventory" in caps_lower, "Food Pantry must mention inventory management"


class TestVietnameseNailSalonAgent:
    def test_exists(self):
        t = _by_name("Vietnamese Nail Salon Agent")
        assert t["industry_type"] == "nail_salon_vietnamese"

    def test_primary_language_vietnamese(self):
        t = _by_name("Vietnamese Nail Salon Agent")
        assert t["primary_language"] == "vi"

    def test_vietnamese_in_supported_languages(self):
        t = _by_name("Vietnamese Nail Salon Agent")
        assert "vi" in t["supported_languages"]

    def test_appointment_skill_included(self):
        t = _by_name("Vietnamese Nail Salon Agent")
        assert "appointments" in t["skills"], (
            "Vietnamese Nail Salon Agent needs appointments skill"
        )

    def test_tip_calculation_in_capabilities(self):
        t = _by_name("Vietnamese Nail Salon Agent")
        caps_lower = " ".join(c.lower() for c in t["capabilities"])
        assert "tip" in caps_lower, "Vietnamese Nail Salon Agent must mention tip calculation"

    def test_service_menu_in_capabilities(self):
        t = _by_name("Vietnamese Nail Salon Agent")
        caps_lower = " ".join(c.lower() for c in t["capabilities"])
        assert "service" in caps_lower or "menu" in caps_lower, (
            "Vietnamese Nail Salon Agent must mention service menu"
        )


# ===========================================================================
# 8. Skills Are Reused Existing Skills (not new)
# ===========================================================================


VALID_SKILLS = frozenset({
    "appointments", "orders", "tasks", "contacts", "invoicing",
    "analytics", "expenses", "inventory",
    "match_tracker", "tournament", "game_session", "loot_tracker",
})


class TestCommunityTemplatesReuseExistingSkills:
    def test_all_skills_are_valid_existing_skills(self):
        for t in get_community_templates():
            for skill in t["skills"]:
                assert skill in VALID_SKILLS, (
                    f"Template '{t['name']}' references unknown skill '{skill}'. "
                    f"Community templates must reuse existing skills only."
                )


# ===========================================================================
# 9. Taqueria Is the Featured Template
# ===========================================================================


class TestFeaturedTemplate:
    def test_taqueria_is_featured(self):
        t = _by_name("Taqueria Agent")
        assert t["featured"] is True, "Taqueria Agent should be the featured community template"

    def test_only_one_featured_template(self):
        featured = [t for t in get_community_templates() if t.get("featured") is True]
        assert len(featured) == 1, f"Expected exactly 1 featured template, found {len(featured)}"

    def test_other_templates_not_featured(self):
        for t in get_community_templates():
            if t["name"] != "Taqueria Agent":
                assert t.get("featured") is False, (
                    f"'{t['name']}' should not be featured"
                )
