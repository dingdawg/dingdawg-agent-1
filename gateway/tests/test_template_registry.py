"""Tests for isg_agent.templates.template_registry."""

from __future__ import annotations

import json

import pytest

from isg_agent.templates.template_registry import TemplateRecord, TemplateRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_registry() -> TemplateRegistry:
    """Return a fresh in-memory TemplateRegistry (not yet closed)."""
    return TemplateRegistry(db_path=":memory:")


# ---------------------------------------------------------------------------
# TestCreateTemplate
# ---------------------------------------------------------------------------


class TestCreateTemplate:
    """Tests for TemplateRegistry.create_template."""

    async def test_create_template_returns_uuid(self) -> None:
        reg = await _make_registry()
        try:
            template_id = await reg.create_template(
                name="My Template",
                agent_type="business",
                industry_type="restaurant",
                system_prompt_template="You are {agent_name} at {business_name}.",
                capabilities='["browse_menu"]',
            )
            assert isinstance(template_id, str)
            assert len(template_id) == 36  # UUID v4 format
        finally:
            await reg.close()

    async def test_create_template_invalid_agent_type_raises(self) -> None:
        reg = await _make_registry()
        try:
            with pytest.raises(ValueError, match="agent_type"):
                await reg.create_template(
                    name="Bad Template",
                    agent_type="robot",  # invalid
                )
        finally:
            await reg.close()

    async def test_create_template_personal_type(self) -> None:
        reg = await _make_registry()
        try:
            template_id = await reg.create_template(
                name="Personal Assistant",
                agent_type="personal",
            )
            record = await reg.get_template(template_id)
            assert record is not None
            assert record.agent_type == "personal"
        finally:
            await reg.close()


# ---------------------------------------------------------------------------
# TestGetTemplate
# ---------------------------------------------------------------------------


class TestGetTemplate:
    """Tests for TemplateRegistry.get_template."""

    async def test_get_template_returns_correct_record(self) -> None:
        reg = await _make_registry()
        try:
            template_id = await reg.create_template(
                name="Restaurant",
                agent_type="business",
                industry_type="restaurant",
                system_prompt_template="You are {agent_name}.",
                capabilities='["place_order"]',
                icon="\U0001f37d",
            )
            record = await reg.get_template(template_id)
            assert record is not None
            assert record.id == template_id
            assert record.name == "Restaurant"
            assert record.agent_type == "business"
            assert record.industry_type == "restaurant"
            assert record.system_prompt_template == "You are {agent_name}."
            assert record.capabilities == '["place_order"]'
            assert record.icon == "\U0001f37d"
        finally:
            await reg.close()

    async def test_get_template_not_found_returns_none(self) -> None:
        reg = await _make_registry()
        try:
            result = await reg.get_template("00000000-0000-0000-0000-000000000000")
            assert result is None
        finally:
            await reg.close()


# ---------------------------------------------------------------------------
# TestListTemplates
# ---------------------------------------------------------------------------


class TestListTemplates:
    """Tests for TemplateRegistry.list_templates."""

    async def test_list_all_templates(self) -> None:
        reg = await _make_registry()
        try:
            await reg.create_template(name="T1", agent_type="business", industry_type="salon")
            await reg.create_template(name="T2", agent_type="business", industry_type="fitness")
            await reg.create_template(name="T3", agent_type="personal")
            results = await reg.list_templates()
            assert len(results) == 3
        finally:
            await reg.close()

    async def test_list_by_agent_type_business(self) -> None:
        reg = await _make_registry()
        try:
            await reg.create_template(name="T1", agent_type="business")
            await reg.create_template(name="T2", agent_type="business")
            await reg.create_template(name="T3", agent_type="personal")
            results = await reg.list_templates(agent_type="business")
            assert len(results) == 2
            assert all(r.agent_type == "business" for r in results)
        finally:
            await reg.close()

    async def test_list_by_agent_type_personal(self) -> None:
        reg = await _make_registry()
        try:
            await reg.create_template(name="PA", agent_type="personal")
            await reg.create_template(name="Biz", agent_type="business")
            results = await reg.list_templates(agent_type="personal")
            assert len(results) == 1
            assert results[0].name == "PA"
        finally:
            await reg.close()

    async def test_list_by_industry_type(self) -> None:
        reg = await _make_registry()
        try:
            await reg.create_template(name="T1", agent_type="business", industry_type="restaurant")
            await reg.create_template(name="T2", agent_type="business", industry_type="restaurant")
            await reg.create_template(name="T3", agent_type="business", industry_type="salon")
            results = await reg.list_templates(industry_type="restaurant")
            assert len(results) == 2
            assert all(r.industry_type == "restaurant" for r in results)
        finally:
            await reg.close()

    async def test_list_empty_registry(self) -> None:
        reg = await _make_registry()
        try:
            results = await reg.list_templates()
            assert results == []
        finally:
            await reg.close()

    async def test_list_combined_filters(self) -> None:
        reg = await _make_registry()
        try:
            await reg.create_template(name="T1", agent_type="business", industry_type="restaurant")
            await reg.create_template(name="T2", agent_type="business", industry_type="salon")
            await reg.create_template(name="T3", agent_type="personal", industry_type="restaurant")
            results = await reg.list_templates(
                agent_type="business", industry_type="restaurant"
            )
            assert len(results) == 1
            assert results[0].name == "T1"
        finally:
            await reg.close()


# ---------------------------------------------------------------------------
# TestSeedDefaults
# ---------------------------------------------------------------------------


class TestSeedDefaults:
    """Tests for TemplateRegistry.seed_defaults."""

    async def test_seed_defaults_creates_38_templates(self) -> None:
        """28 original + 8 gaming + 2 DingDawg internal = 38 total seed templates."""
        reg = await _make_registry()
        try:
            inserted = await reg.seed_defaults()
            assert inserted == 38
            all_templates = await reg.list_templates()
            assert len(all_templates) == 38
        finally:
            await reg.close()

    async def test_seed_defaults_idempotent(self) -> None:
        """Calling seed_defaults twice must still result in exactly 38 templates."""
        reg = await _make_registry()
        try:
            first = await reg.seed_defaults()
            assert first == 38
            second = await reg.seed_defaults()
            assert second == 0  # Nothing new inserted
            all_templates = await reg.list_templates()
            assert len(all_templates) == 38
        finally:
            await reg.close()

    async def test_seed_defaults_includes_personal_type(self) -> None:
        reg = await _make_registry()
        try:
            await reg.seed_defaults()
            personal_templates = await reg.list_templates(agent_type="personal")
            assert len(personal_templates) == 4
            personal_names = {t.name for t in personal_templates}
            assert "Personal Assistant" in personal_names
            assert "Life Scheduler" in personal_names
            assert "Shopping Concierge" in personal_names
            assert "Family Hub" in personal_names
        finally:
            await reg.close()

    async def test_seed_defaults_includes_business_types(self) -> None:
        reg = await _make_registry()
        try:
            await reg.seed_defaults()
            business_templates = await reg.list_templates(agent_type="business")
            assert len(business_templates) == 11
        finally:
            await reg.close()

    async def test_seed_defaults_includes_b2b_types(self) -> None:
        reg = await _make_registry()
        try:
            await reg.seed_defaults()
            b2b_templates = await reg.list_templates(agent_type="b2b")
            assert len(b2b_templates) == 3
            b2b_names = {t.name for t in b2b_templates}
            assert "Vendor Manager" in b2b_names
            assert "Procurement Desk" in b2b_names
            assert "Supply Chain Monitor" in b2b_names
        finally:
            await reg.close()

    async def test_seed_defaults_includes_a2a_types(self) -> None:
        reg = await _make_registry()
        try:
            await reg.seed_defaults()
            a2a_templates = await reg.list_templates(agent_type="a2a")
            assert len(a2a_templates) == 2
            a2a_names = {t.name for t in a2a_templates}
            assert "Task Orchestrator" in a2a_names
            assert "Payment Relay" in a2a_names
        finally:
            await reg.close()

    async def test_seed_defaults_includes_compliance_types(self) -> None:
        reg = await _make_registry()
        try:
            await reg.seed_defaults()
            compliance_templates = await reg.list_templates(agent_type="compliance")
            assert len(compliance_templates) == 3
            compliance_names = {t.name for t in compliance_templates}
            assert "FERPA Education Guard" in compliance_names
            assert "HIPAA Health Gateway" in compliance_names
            assert "COPPA Children Guard" in compliance_names
        finally:
            await reg.close()

    async def test_seed_defaults_includes_enterprise_types(self) -> None:
        reg = await _make_registry()
        try:
            await reg.seed_defaults()
            enterprise_templates = await reg.list_templates(agent_type="enterprise")
            assert len(enterprise_templates) == 4
            enterprise_names = {t.name for t in enterprise_templates}
            assert "Multi-Location Coordinator" in enterprise_names
            assert "Field Service Dispatcher" in enterprise_names
            assert "DingDawg Support Agent" in enterprise_names
            assert "DingDawg Sales Agent" in enterprise_names
        finally:
            await reg.close()

    async def test_seed_defaults_includes_health_types(self) -> None:
        reg = await _make_registry()
        try:
            await reg.seed_defaults()
            health_templates = await reg.list_templates(agent_type="health")
            assert len(health_templates) == 3
            health_names = {t.name for t in health_templates}
            assert "Patient Scheduling" in health_names
            assert "Pharmacy Refill" in health_names
            assert "Wellness Coach" in health_names
        finally:
            await reg.close()

    async def test_seed_defaults_capabilities_are_valid_json(self) -> None:
        reg = await _make_registry()
        try:
            await reg.seed_defaults()
            all_templates = await reg.list_templates()
            for t in all_templates:
                caps = json.loads(t.capabilities)
                assert isinstance(caps, list)
                assert len(caps) > 0
        finally:
            await reg.close()

    async def test_seed_defaults_flow_json_has_steps(self) -> None:
        reg = await _make_registry()
        try:
            await reg.seed_defaults()
            all_templates = await reg.list_templates()
            for t in all_templates:
                flow = json.loads(t.flow_json)
                assert "steps" in flow
                assert len(flow["steps"]) > 0
        finally:
            await reg.close()


# ---------------------------------------------------------------------------
# TestTemplateRecord
# ---------------------------------------------------------------------------


class TestTemplateRecord:
    """Tests for TemplateRecord.from_row and TemplateRecord.to_dict."""

    def test_template_record_from_row_dict(self) -> None:
        row = {
            "id": "abc-123",
            "name": "Test",
            "agent_type": "business",
            "industry_type": "salon",
            "system_prompt_template": "You are {agent_name}.",
            "flow_json": '{"steps": []}',
            "catalog_schema_json": '{"item_type": "service"}',
            "capabilities": '["book"]',
            "default_constitution_yaml": "rules:\n  - id: test\n",
            "icon": "\U0001f487",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        record = TemplateRecord.from_row(row)
        assert record.id == "abc-123"
        assert record.name == "Test"
        assert record.agent_type == "business"
        assert record.industry_type == "salon"
        assert record.icon == "\U0001f487"
        assert record.created_at == "2026-01-01T00:00:00+00:00"

    def test_template_record_from_row_missing_optional_fields(self) -> None:
        row = {
            "id": "def-456",
            "name": "Minimal",
            "agent_type": "personal",
            # industry_type, catalog_schema_json, default_constitution_yaml, icon all absent
        }
        record = TemplateRecord.from_row(row)
        assert record.id == "def-456"
        assert record.industry_type is None
        assert record.catalog_schema_json is None
        assert record.default_constitution_yaml is None
        assert record.icon is None

    def test_template_record_to_dict(self) -> None:
        record = TemplateRecord(
            id="ghi-789",
            name="Dict Test",
            agent_type="business",
            industry_type="fitness",
            system_prompt_template="Prompt here.",
            flow_json='{"steps": []}',
            catalog_schema_json='{"item_type": "class"}',
            capabilities='["schedule"]',
            default_constitution_yaml=None,
            icon="\U0001f3cb",
            created_at="2026-02-01T00:00:00+00:00",
        )
        d = record.to_dict()
        assert d["id"] == "ghi-789"
        assert d["name"] == "Dict Test"
        assert d["agent_type"] == "business"
        assert d["industry_type"] == "fitness"
        assert d["icon"] == "\U0001f3cb"
        assert d["default_constitution_yaml"] is None
        # Ensure all expected keys are present
        expected_keys = {
            "id", "name", "agent_type", "industry_type", "system_prompt_template",
            "flow_json", "catalog_schema_json", "capabilities",
            "default_constitution_yaml", "icon", "created_at",
        }
        assert set(d.keys()) == expected_keys

    def test_template_record_is_frozen(self) -> None:
        record = TemplateRecord(
            id="frozen-test",
            name="Frozen",
            agent_type="personal",
            industry_type=None,
            system_prompt_template="",
            flow_json="{}",
            catalog_schema_json=None,
            capabilities="[]",
            default_constitution_yaml=None,
            icon=None,
            created_at="",
        )
        with pytest.raises((AttributeError, TypeError)):
            record.name = "Changed"  # type: ignore[misc]
