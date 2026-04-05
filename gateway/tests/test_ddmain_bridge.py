"""Tests for isg_agent.integrations.ddmain_bridge.

Covers:
- Business registration (new + duplicate update)
- Handle generation from business names (various edge cases)
- Handle collision resolution (suffix appending)
- Business sync (update branding, config, status)
- Business unregistration (handle release, agent archive)
- Mapping lookup (exists + not found)
- List registered businesses
- Edge cases: empty listing, pagination, bad input
"""

from __future__ import annotations

import pytest

from isg_agent.agents.agent_registry import AgentRegistry
from isg_agent.agents.handle_service import HandleService
from isg_agent.integrations.ddmain_bridge import DDMainBridge, _slugify
from isg_agent.templates.template_registry import TemplateRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BIZ_ID = "aaaaaaaa-0000-0000-0000-000000000001"
_BIZ_ID_2 = "aaaaaaaa-0000-0000-0000-000000000002"
_BIZ_ID_3 = "aaaaaaaa-0000-0000-0000-000000000003"


async def _make_bridge() -> DDMainBridge:
    """Create an isolated in-memory bridge with all dependencies."""
    agent_registry = AgentRegistry(db_path=":memory:")
    handle_service = HandleService(db_path=":memory:")
    template_registry = TemplateRegistry(db_path=":memory:")
    await template_registry.seed_defaults()

    bridge = DDMainBridge(
        agent_registry=agent_registry,
        handle_service=handle_service,
        template_registry=template_registry,
        db_path=":memory:",
    )
    return bridge


async def _close_bridge(bridge: DDMainBridge) -> None:
    await bridge.close()
    await bridge._agent_registry.close()
    await bridge._handle_service.close()
    await bridge._template_registry.close()


# ---------------------------------------------------------------------------
# _slugify unit tests
# ---------------------------------------------------------------------------


class TestSlugify:
    """Unit tests for the _slugify helper."""

    def test_simple_name(self) -> None:
        assert _slugify("bobs pizza") == "bobs-pizza"

    def test_apostrophe_stripped(self) -> None:
        assert _slugify("Bob's Pizza") == "bobs-pizza"

    def test_ampersand_replaced_with_and(self) -> None:
        assert _slugify("Luxe Salon & Spa") == "luxe-salon-and-spa"

    def test_multiple_spaces_collapsed(self) -> None:
        assert _slugify("The   Place") == "the-place"

    def test_special_chars_stripped(self) -> None:
        assert _slugify("Joe's #1 Grill!") == "joes-1-grill"

    def test_leading_digit_gets_prefix(self) -> None:
        slug = _slugify("123 Burger")
        assert slug.startswith("biz-")

    def test_max_length_truncated(self) -> None:
        long_name = "a" * 100
        slug = _slugify(long_name)
        assert len(slug) <= 30

    def test_empty_name_returns_business(self) -> None:
        assert _slugify("") == "business"

    def test_leading_trailing_hyphens_stripped(self) -> None:
        result = _slugify("  -Hello World-  ")
        assert not result.startswith("-")
        assert not result.endswith("-")

    def test_accented_chars_normalised(self) -> None:
        slug = _slugify("Café España")
        assert "á" not in slug
        assert "é" not in slug


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestRegisterBusiness:
    """Tests for DDMainBridge.register_business."""

    async def test_register_new_business_returns_is_new_true(self) -> None:
        bridge = await _make_bridge()
        try:
            result = await bridge.register_business({
                "business_id": _BIZ_ID,
                "name": "Marios Pizza",
            })
            assert result["is_new"] is True
            assert result["status"] == "created"
            assert result["agent_id"]
            assert result["handle"]
        finally:
            await _close_bridge(bridge)

    async def test_register_creates_agent_in_registry(self) -> None:
        bridge = await _make_bridge()
        try:
            result = await bridge.register_business({
                "business_id": _BIZ_ID,
                "name": "Taco Bell Clone",
            })
            agent = await bridge._agent_registry.get_agent(result["agent_id"])
            assert agent is not None
            assert agent.industry_type == "restaurant"
            assert agent.agent_type.value == "business"
        finally:
            await _close_bridge(bridge)

    async def test_register_claims_handle(self) -> None:
        bridge = await _make_bridge()
        try:
            result = await bridge.register_business({
                "business_id": _BIZ_ID,
                "name": "Green Garden Bistro",
            })
            handle_info = await bridge._handle_service.get_handle_info(result["handle"])
            assert handle_info is not None
            assert handle_info["agent_id"] == result["agent_id"]
        finally:
            await _close_bridge(bridge)

    async def test_register_duplicate_business_updates_agent(self) -> None:
        bridge = await _make_bridge()
        try:
            r1 = await bridge.register_business({
                "business_id": _BIZ_ID,
                "name": "Old Name",
            })
            r2 = await bridge.register_business({
                "business_id": _BIZ_ID,
                "name": "New Name",
            })
            assert r2["is_new"] is False
            assert r2["status"] == "updated"
            # Same agent and handle — not duplicated
            assert r1["agent_id"] == r2["agent_id"]
            assert r1["handle"] == r2["handle"]
            # Agent name should be updated
            agent = await bridge._agent_registry.get_agent(r1["agent_id"])
            assert agent is not None
            assert agent.name == "New Name"
        finally:
            await _close_bridge(bridge)

    async def test_register_stores_branding(self) -> None:
        bridge = await _make_bridge()
        try:
            result = await bridge.register_business({
                "business_id": _BIZ_ID,
                "name": "Branded Burger",
                "logo_url": "https://example.com/logo.png",
                "primary_color": "#FF0000",
                "cuisine_type": "American",
                "address": "123 Main St",
                "greeting": "Welcome to Branded Burger!",
            })
            agent = await bridge._agent_registry.get_agent(result["agent_id"])
            assert agent is not None
            import json
            branding = json.loads(agent.branding_json)
            assert branding["logo_url"] == "https://example.com/logo.png"
            assert branding["primary_color"] == "#FF0000"
            assert branding["cuisine_type"] == "American"
        finally:
            await _close_bridge(bridge)

    async def test_register_stores_config(self) -> None:
        bridge = await _make_bridge()
        try:
            result = await bridge.register_business({
                "business_id": _BIZ_ID,
                "name": "Config Test Restaurant",
                "description": "A test restaurant",
                "agentic_live": True,
                "readiness_score": 85,
                "offerings_count": 42,
            })
            agent = await bridge._agent_registry.get_agent(result["agent_id"])
            assert agent is not None
            import json
            config = json.loads(agent.config_json)
            assert config["source"] == "ddmain"
            assert config["ddmain_business_id"] == _BIZ_ID
            assert config["agentic_live"] is True
            assert config["readiness_score"] == 85
            assert config["offerings_count"] == 42
        finally:
            await _close_bridge(bridge)

    async def test_register_uses_handle_preference_when_available(self) -> None:
        bridge = await _make_bridge()
        try:
            result = await bridge.register_business({
                "business_id": _BIZ_ID,
                "name": "Any Name",
                "handle_preference": "my-restaurant",
            })
            assert result["handle"] == "my-restaurant"
        finally:
            await _close_bridge(bridge)

    async def test_register_falls_back_when_handle_preference_taken(self) -> None:
        bridge = await _make_bridge()
        try:
            # Claim the preferred handle first
            await bridge._handle_service.claim_handle("my-restaurant", "some-agent-id")
            result = await bridge.register_business({
                "business_id": _BIZ_ID,
                "name": "My Restaurant",
                "handle_preference": "my-restaurant",
            })
            # Should have fallen back to a generated handle
            assert result["handle"] != "my-restaurant"
            assert result["is_new"] is True
        finally:
            await _close_bridge(bridge)

    async def test_register_raises_on_missing_business_id(self) -> None:
        bridge = await _make_bridge()
        try:
            with pytest.raises(ValueError, match="business_id"):
                await bridge.register_business({"name": "No ID"})
        finally:
            await _close_bridge(bridge)

    async def test_register_raises_on_missing_name(self) -> None:
        bridge = await _make_bridge()
        try:
            with pytest.raises(ValueError, match="name"):
                await bridge.register_business({"business_id": _BIZ_ID})
        finally:
            await _close_bridge(bridge)

    async def test_register_uses_restaurant_template(self) -> None:
        bridge = await _make_bridge()
        try:
            result = await bridge.register_business({
                "business_id": _BIZ_ID,
                "name": "Template Test Diner",
            })
            agent = await bridge._agent_registry.get_agent(result["agent_id"])
            assert agent is not None
            assert agent.template_id is not None  # Restaurant template was seeded
        finally:
            await _close_bridge(bridge)


# ---------------------------------------------------------------------------
# Handle generation tests
# ---------------------------------------------------------------------------


class TestHandleGeneration:
    """Tests for handle collision resolution."""

    async def test_collision_adds_numeric_suffix(self) -> None:
        bridge = await _make_bridge()
        try:
            r1 = await bridge.register_business({
                "business_id": _BIZ_ID,
                "name": "Sunset Grill",
            })
            r2 = await bridge.register_business({
                "business_id": _BIZ_ID_2,
                "name": "Sunset Grill",  # Same name — collision
            })
            assert r1["handle"] != r2["handle"]
            # Second handle should have a numeric suffix
            assert r2["handle"].startswith("sunset-grill-")
        finally:
            await _close_bridge(bridge)

    async def test_three_collisions_all_unique(self) -> None:
        bridge = await _make_bridge()
        try:
            handles = set()
            for i, biz_id in enumerate([_BIZ_ID, _BIZ_ID_2, _BIZ_ID_3]):
                result = await bridge.register_business({
                    "business_id": biz_id,
                    "name": "Popular Place",
                })
                handles.add(result["handle"])
            assert len(handles) == 3  # All unique
        finally:
            await _close_bridge(bridge)

    async def test_very_short_name_gets_padded(self) -> None:
        bridge = await _make_bridge()
        try:
            result = await bridge.register_business({
                "business_id": _BIZ_ID,
                "name": "AB",  # Only 2 chars → slug "ab" → too short
            })
            assert len(result["handle"]) >= 3
        finally:
            await _close_bridge(bridge)


# ---------------------------------------------------------------------------
# Sync tests
# ---------------------------------------------------------------------------


class TestSyncBusiness:
    """Tests for DDMainBridge.sync_business."""

    async def test_sync_updates_name(self) -> None:
        bridge = await _make_bridge()
        try:
            reg = await bridge.register_business({
                "business_id": _BIZ_ID,
                "name": "Original Name",
            })
            result = await bridge.sync_business(
                _BIZ_ID, {"name": "Updated Name"}
            )
            assert "name" in result["updated_fields"]
            agent = await bridge._agent_registry.get_agent(reg["agent_id"])
            assert agent is not None
            assert agent.name == "Updated Name"
        finally:
            await _close_bridge(bridge)

    async def test_sync_updates_branding_fields(self) -> None:
        bridge = await _make_bridge()
        try:
            await bridge.register_business({
                "business_id": _BIZ_ID,
                "name": "Branding Test",
            })
            result = await bridge.sync_business(_BIZ_ID, {
                "logo_url": "https://cdn.example.com/new-logo.png",
                "primary_color": "#00FF00",
            })
            assert "logo_url" in result["updated_fields"]
            assert "primary_color" in result["updated_fields"]
        finally:
            await _close_bridge(bridge)

    async def test_sync_updates_config_fields(self) -> None:
        bridge = await _make_bridge()
        try:
            await bridge.register_business({
                "business_id": _BIZ_ID,
                "name": "Config Sync Test",
            })
            result = await bridge.sync_business(_BIZ_ID, {
                "agentic_live": True,
                "readiness_score": 95,
                "offerings_count": 100,
            })
            assert "agentic_live" in result["updated_fields"]
            assert "readiness_score" in result["updated_fields"]
        finally:
            await _close_bridge(bridge)

    async def test_sync_returns_agent_id_and_handle(self) -> None:
        bridge = await _make_bridge()
        try:
            reg = await bridge.register_business({
                "business_id": _BIZ_ID,
                "name": "Handle Test",
            })
            result = await bridge.sync_business(_BIZ_ID, {"description": "New desc"})
            assert result["agent_id"] == reg["agent_id"]
            assert result["handle"] == reg["handle"]
        finally:
            await _close_bridge(bridge)

    async def test_sync_raises_on_unregistered_business(self) -> None:
        bridge = await _make_bridge()
        try:
            with pytest.raises(KeyError):
                await bridge.sync_business("not-registered-id", {"name": "X"})
        finally:
            await _close_bridge(bridge)

    async def test_sync_no_fields_returns_empty_list(self) -> None:
        bridge = await _make_bridge()
        try:
            await bridge.register_business({
                "business_id": _BIZ_ID,
                "name": "No Fields Test",
            })
            result = await bridge.sync_business(_BIZ_ID, {})
            assert result["updated_fields"] == []
        finally:
            await _close_bridge(bridge)


# ---------------------------------------------------------------------------
# Lookup and listing tests
# ---------------------------------------------------------------------------


class TestLookupAndList:
    """Tests for get_agent_for_business and list_registered_businesses."""

    async def test_get_agent_for_registered_business(self) -> None:
        bridge = await _make_bridge()
        try:
            reg = await bridge.register_business({
                "business_id": _BIZ_ID,
                "name": "Lookup Test",
            })
            mapping = await bridge.get_agent_for_business(_BIZ_ID)
            assert mapping is not None
            assert mapping["agent_id"] == reg["agent_id"]
            assert mapping["handle"] == reg["handle"]
            assert mapping["sync_status"] == "active"
        finally:
            await _close_bridge(bridge)

    async def test_get_agent_for_unknown_business_returns_none(self) -> None:
        bridge = await _make_bridge()
        try:
            mapping = await bridge.get_agent_for_business("no-such-business-id")
            assert mapping is None
        finally:
            await _close_bridge(bridge)

    async def test_list_returns_registered_businesses(self) -> None:
        bridge = await _make_bridge()
        try:
            await bridge.register_business({"business_id": _BIZ_ID, "name": "One"})
            await bridge.register_business({"business_id": _BIZ_ID_2, "name": "Two"})
            businesses = await bridge.list_registered_businesses()
            ids = {b["business_id"] for b in businesses}
            assert _BIZ_ID in ids
            assert _BIZ_ID_2 in ids
        finally:
            await _close_bridge(bridge)

    async def test_list_excludes_removed_businesses(self) -> None:
        bridge = await _make_bridge()
        try:
            await bridge.register_business({"business_id": _BIZ_ID, "name": "Active"})
            await bridge.register_business({"business_id": _BIZ_ID_2, "name": "To Remove"})
            await bridge.unregister_business(_BIZ_ID_2)

            businesses = await bridge.list_registered_businesses()
            ids = {b["business_id"] for b in businesses}
            assert _BIZ_ID in ids
            assert _BIZ_ID_2 not in ids
        finally:
            await _close_bridge(bridge)

    async def test_list_empty_returns_empty_list(self) -> None:
        bridge = await _make_bridge()
        try:
            businesses = await bridge.list_registered_businesses()
            assert businesses == []
        finally:
            await _close_bridge(bridge)

    async def test_list_respects_limit(self) -> None:
        bridge = await _make_bridge()
        try:
            ids = [f"biz-{i:04d}-0000-0000-0000-000000000000" for i in range(5)]
            for i, biz_id in enumerate(ids):
                await bridge.register_business({
                    "business_id": biz_id,
                    "name": f"Restaurant {i}",
                })
            result = await bridge.list_registered_businesses(limit=3)
            assert len(result) == 3
        finally:
            await _close_bridge(bridge)


# ---------------------------------------------------------------------------
# Unregister tests
# ---------------------------------------------------------------------------


class TestUnregisterBusiness:
    """Tests for DDMainBridge.unregister_business."""

    async def test_unregister_returns_true(self) -> None:
        bridge = await _make_bridge()
        try:
            await bridge.register_business({"business_id": _BIZ_ID, "name": "Remove Me"})
            assert await bridge.unregister_business(_BIZ_ID) is True
        finally:
            await _close_bridge(bridge)

    async def test_unregister_archives_agent(self) -> None:
        bridge = await _make_bridge()
        try:
            reg = await bridge.register_business({
                "business_id": _BIZ_ID, "name": "Archive Test"
            })
            await bridge.unregister_business(_BIZ_ID)
            agent = await bridge._agent_registry.get_agent(reg["agent_id"])
            assert agent is not None
            assert agent.status.value == "archived"
        finally:
            await _close_bridge(bridge)

    async def test_unregister_releases_handle(self) -> None:
        bridge = await _make_bridge()
        try:
            reg = await bridge.register_business({
                "business_id": _BIZ_ID, "name": "Handle Release Test"
            })
            handle = reg["handle"]
            await bridge.unregister_business(_BIZ_ID)
            # Handle should now be available
            assert await bridge._handle_service.is_available(handle) is True
        finally:
            await _close_bridge(bridge)

    async def test_unregister_marks_mapping_as_removed(self) -> None:
        bridge = await _make_bridge()
        try:
            await bridge.register_business({"business_id": _BIZ_ID, "name": "Status Test"})
            await bridge.unregister_business(_BIZ_ID)
            mapping = await bridge.get_agent_for_business(_BIZ_ID)
            assert mapping is not None
            assert mapping["sync_status"] == "removed"
        finally:
            await _close_bridge(bridge)

    async def test_unregister_unknown_business_returns_false(self) -> None:
        bridge = await _make_bridge()
        try:
            assert await bridge.unregister_business("no-such-id") is False
        finally:
            await _close_bridge(bridge)

    async def test_unregister_already_removed_returns_false(self) -> None:
        bridge = await _make_bridge()
        try:
            await bridge.register_business({"business_id": _BIZ_ID, "name": "Double Remove"})
            await bridge.unregister_business(_BIZ_ID)
            assert await bridge.unregister_business(_BIZ_ID) is False
        finally:
            await _close_bridge(bridge)
