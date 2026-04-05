"""API smoke tests for template discovery endpoints.

Tests cover:
- GET /api/v1/templates — list all templates (no auth required)
- GET /api/v1/templates?agent_type=... — filter by type
- GET /api/v1/templates?industry_type=... — filter by industry
- GET /api/v1/templates/{template_id} — get single template
- GET /api/v1/templates/{nonexistent} — returns 404

The TemplateRegistry seeds 38 default templates on startup via the
lifespan context (28 original + 8 gaming + 2 DingDawg internal). The
fixture triggers the lifespan explicitly so that app.state.template_registry
is populated before tests run.

Note: the 2 DingDawg internal templates (agent_type="enterprise") are seeded
in the DB but filtered from the public API response. The public endpoint
exposes 36 templates only.
"""

from __future__ import annotations

import os
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from isg_agent.config import get_settings

# ---------------------------------------------------------------------------
# Expected seed template names (from template_registry._get_seed_templates)
# ---------------------------------------------------------------------------

_EXPECTED_SEED_NAMES = {
    # Original 7
    "Restaurant",
    "Salon / Spa",
    "Tutor / Education",
    "Home Service",
    "Fitness",
    "Generic Business",
    "Personal Assistant",
    # Personal (3 new)
    "Life Scheduler",
    "Shopping Concierge",
    "Family Hub",
    # Business (5 new)
    "Retail Store",
    "Professional Services",
    "Trade Business",
    "Creative Studio",
    "Real Estate Agent",
    # B2B (3)
    "Vendor Manager",
    "Procurement Desk",
    "Supply Chain Monitor",
    # A2A (2)
    "Task Orchestrator",
    "Payment Relay",
    # Compliance (3)
    "FERPA Education Guard",
    "HIPAA Health Gateway",
    "COPPA Children Guard",
    # Enterprise (2) — customer-facing enterprise templates, still public
    "Multi-Location Coordinator",
    "Field Service Dispatcher",
    # Health (3)
    "Patient Scheduling",
    "Pharmacy Refill",
    "Wellness Coach",
    # Gaming (8)
    "Game Coach",
    "Guild Commander",
    "Stream Copilot",
    "Tournament Director",
    "Quest Master",
    "Economy Analyst",
    "Parent Guardian",
    "Mod Workshop",
    # DingDawg's own operated agent templates (industry_type dingdawg_support /
    # dingdawg_sales) are seeded in the DB but filtered from the public API.
    # They must NOT appear in this set.
}

_EXPECTED_SEED_COUNT = len(_EXPECTED_SEED_NAMES)  # 36 public templates (38 seeded - 2 internal)

_SECRET = "test-secret-templates-suite"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(tmp_path):
    """Provide an async HTTP client with a running app lifespan.

    Sets env vars, clears the settings cache, then triggers the FastAPI
    lifespan context so that app.state.template_registry is initialised
    and seeded with the 28 default templates before any test request.
    """
    db_file = str(tmp_path / "test_templates.db")

    # Set env vars that the Settings model reads
    os.environ["ISG_AGENT_DB_PATH"] = db_file
    os.environ["ISG_AGENT_SECRET_KEY"] = _SECRET

    # Clear lru_cache so the lifespan picks up the new env vars
    get_settings.cache_clear()

    from isg_agent.app import create_app, lifespan

    app = create_app()

    # Trigger the lifespan so app.state is populated (template_registry etc.)
    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    # Restore env and cache
    os.environ.pop("ISG_AGENT_DB_PATH", None)
    os.environ.pop("ISG_AGENT_SECRET_KEY", None)
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# GET /api/v1/templates — list all
# ---------------------------------------------------------------------------


class TestListTemplates:
    """Tests for GET /api/v1/templates."""

    @pytest.mark.asyncio
    async def test_list_templates_returns_all_seeds(self, client):
        """Listing templates returns 36 public templates (38 seeded minus 2 internal enterprise templates)."""
        resp = await client.get("/api/v1/templates")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["count"] == _EXPECTED_SEED_COUNT
        assert len(data["templates"]) == _EXPECTED_SEED_COUNT

    @pytest.mark.asyncio
    async def test_list_templates_no_auth_required(self, client):
        """Template listing is public — no auth header needed."""
        resp = await client.get("/api/v1/templates")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_templates_has_expected_names(self, client):
        """All 36 public template names are present; internal enterprise templates are absent."""
        resp = await client.get("/api/v1/templates")
        data = resp.json()
        names = {t["name"] for t in data["templates"]}
        assert names == _EXPECTED_SEED_NAMES

    @pytest.mark.asyncio
    async def test_list_templates_response_shape(self, client):
        """Each template in the list has required fields."""
        resp = await client.get("/api/v1/templates")
        data = resp.json()
        for template in data["templates"]:
            assert "id" in template
            assert "name" in template
            assert "agent_type" in template
            assert "capabilities" in template
            # icon may be None for some templates but key must exist
            assert "icon" in template

    @pytest.mark.asyncio
    async def test_list_templates_filter_by_agent_type_business(self, client):
        """Filtering by agent_type=business returns only business templates."""
        resp = await client.get("/api/v1/templates", params={"agent_type": "business"})
        assert resp.status_code == 200
        data = resp.json()
        # 6 business templates (all except Personal Assistant)
        assert data["count"] >= 1
        for t in data["templates"]:
            assert t["agent_type"] == "business"

    @pytest.mark.asyncio
    async def test_list_templates_filter_by_agent_type_personal(self, client):
        """Filtering by agent_type=personal returns only personal templates."""
        resp = await client.get("/api/v1/templates", params={"agent_type": "personal"})
        assert resp.status_code == 200
        data = resp.json()
        # 4 personal templates: Personal Assistant, Life Scheduler,
        # Shopping Concierge, Family Hub
        assert data["count"] == 4
        names = {t["name"] for t in data["templates"]}
        assert "Personal Assistant" in names
        assert "Life Scheduler" in names
        assert "Shopping Concierge" in names
        assert "Family Hub" in names
        for t in data["templates"]:
            assert t["agent_type"] == "personal"

    @pytest.mark.asyncio
    async def test_list_templates_filter_by_invalid_agent_type_returns_422(self, client):
        """Filtering with an invalid agent_type returns 422."""
        resp = await client.get("/api/v1/templates", params={"agent_type": "invalid"})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_list_templates_filter_by_industry_type(self, client):
        """Filtering by industry_type=restaurant returns only restaurant templates."""
        resp = await client.get("/api/v1/templates", params={"industry_type": "restaurant"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["templates"][0]["name"] == "Restaurant"

    @pytest.mark.asyncio
    async def test_list_templates_combined_filter(self, client):
        """Filtering by both agent_type and industry_type works correctly."""
        resp = await client.get(
            "/api/v1/templates",
            params={"agent_type": "business", "industry_type": "salon"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["templates"][0]["name"] == "Salon / Spa"

    @pytest.mark.asyncio
    async def test_internal_dingdawg_templates_not_exposed(self, client):
        """Internal DingDawg operated agent templates must not appear in the public listing."""
        resp = await client.get("/api/v1/templates")
        data = resp.json()
        names = {t["name"] for t in data["templates"]}
        assert "DingDawg Support Agent" not in names, (
            "DingDawg Support Agent (internal) leaked into public API"
        )
        assert "DingDawg Sales Agent" not in names, (
            "DingDawg Sales Agent (internal) leaked into public API"
        )

    @pytest.mark.asyncio
    async def test_enterprise_customer_templates_still_exposed(self, client):
        """Legitimate enterprise templates (Multi-Location Coordinator, Field Service Dispatcher)
        are still returned — only DingDawg's own operated agents are filtered."""
        resp = await client.get("/api/v1/templates", params={"agent_type": "enterprise"})
        assert resp.status_code == 200
        data = resp.json()
        names = {t["name"] for t in data["templates"]}
        assert "Multi-Location Coordinator" in names
        assert "Field Service Dispatcher" in names

    @pytest.mark.asyncio
    async def test_list_templates_industry_with_no_match_returns_empty(self, client):
        """Filtering by a nonexistent industry_type returns empty list."""
        resp = await client.get(
            "/api/v1/templates",
            params={"industry_type": "nonexistent-industry"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["templates"] == []


# ---------------------------------------------------------------------------
# GET /api/v1/templates/{template_id} — get single
# ---------------------------------------------------------------------------


class TestGetTemplate:
    """Tests for GET /api/v1/templates/{template_id}."""

    @pytest.mark.asyncio
    async def test_get_template_returns_200(self, client):
        """Getting a seeded template by ID returns 200 with full detail."""
        # First, get the list to obtain a real template ID
        list_resp = await client.get("/api/v1/templates")
        templates = list_resp.json()["templates"]
        assert len(templates) > 0

        template_id = templates[0]["id"]

        get_resp = await client.get(f"/api/v1/templates/{template_id}")
        assert get_resp.status_code == 200, get_resp.text
        data = get_resp.json()
        assert data["id"] == template_id
        assert "name" in data
        assert "agent_type" in data
        assert "capabilities" in data

    @pytest.mark.asyncio
    async def test_get_nonexistent_template_returns_404(self, client):
        """Getting a non-existent template ID returns 404."""
        resp = await client.get("/api/v1/templates/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_template_no_auth_required(self, client):
        """Getting a template by ID is public — no auth needed."""
        list_resp = await client.get("/api/v1/templates")
        template_id = list_resp.json()["templates"][0]["id"]

        resp = await client.get(f"/api/v1/templates/{template_id}")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_restaurant_template_has_capabilities(self, client):
        """The Restaurant template has capabilities as a non-empty JSON array."""
        import json

        list_resp = await client.get(
            "/api/v1/templates",
            params={"industry_type": "restaurant"},
        )
        template_id = list_resp.json()["templates"][0]["id"]

        get_resp = await client.get(f"/api/v1/templates/{template_id}")
        data = get_resp.json()

        caps = json.loads(data["capabilities"])
        assert isinstance(caps, list)
        assert len(caps) > 0

    @pytest.mark.asyncio
    async def test_get_all_seeded_templates_by_id(self, client):
        """Every template returned by the list endpoint is also gettable by ID."""
        list_resp = await client.get("/api/v1/templates")
        templates = list_resp.json()["templates"]

        for template in templates:
            get_resp = await client.get(f"/api/v1/templates/{template['id']}")
            assert get_resp.status_code == 200, (
                f"Template {template['name']} (id={template['id']}) failed with "
                f"{get_resp.status_code}: {get_resp.text}"
            )
