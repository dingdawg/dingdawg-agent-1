"""Backend tests for onboarding endpoints.

TDD-first: tests written before implementation.

Tests cover:
- GET /api/v1/onboarding/sectors — list all 8 sectors with metadata
- GET /api/v1/onboarding/check-handle/{handle} — real-time availability (public, no auth)
- POST /api/v1/onboarding/claim — create agent with selected template (auth required)

Uses the same async lifespan fixture pattern as test_api_agents.py.
"""

from __future__ import annotations

import os
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from isg_agent.api.routes.auth import _create_token
from isg_agent.config import get_settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SECRET = "test-secret-onboarding-suite"
_USER_A = "user-onboarding-alpha"
_USER_B = "user-onboarding-beta"

# All 8 sectors including Gaming (which maps to "business" agent_type until
# the gaming sector is formally added to VALID_AGENT_TYPES)
_EXPECTED_SECTOR_NAMES = {
    "Personal",
    "Business",
    "B2B",
    "A2A",
    "Compliance",
    "Enterprise",
    "Health",
    "Gaming",
}

_SECTOR_REQUIRED_FIELDS = {"id", "name", "description", "icon", "agent_type"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(user_id: str, email: str = "test@onboarding.com") -> str:
    """Create a valid JWT for test requests."""
    return _create_token(user_id=user_id, email=email, secret_key=_SECRET)


def _auth_headers(user_id: str) -> dict[str, str]:
    """Return Authorization Bearer headers for the given user."""
    return {"Authorization": f"Bearer {_make_token(user_id)}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(tmp_path):
    """Provide an async HTTP client with a running app lifespan.

    Sets env vars, clears the settings cache, then triggers the FastAPI
    lifespan context so all app.state services are initialised before
    requests are made.
    """
    db_file = str(tmp_path / "test_onboarding.db")

    os.environ["ISG_AGENT_DB_PATH"] = db_file
    os.environ["ISG_AGENT_SECRET_KEY"] = _SECRET

    get_settings.cache_clear()

    from isg_agent.app import create_app, lifespan

    app = create_app()

    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    os.environ.pop("ISG_AGENT_DB_PATH", None)
    os.environ.pop("ISG_AGENT_SECRET_KEY", None)
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# GET /api/v1/onboarding/sectors
# ---------------------------------------------------------------------------


class TestSectorsEndpoint:
    """Tests for GET /api/v1/onboarding/sectors."""

    @pytest.mark.asyncio
    async def test_sectors_endpoint_returns_200(self, client):
        """The sectors endpoint returns HTTP 200."""
        resp = await client.get("/api/v1/onboarding/sectors")
        assert resp.status_code == 200, resp.text

    @pytest.mark.asyncio
    async def test_sectors_endpoint_returns_all_sectors(self, client):
        """All 8 sectors are returned with the correct names."""
        resp = await client.get("/api/v1/onboarding/sectors")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "sectors" in data
        assert "count" in data
        names = {s["name"] for s in data["sectors"]}
        assert names == _EXPECTED_SECTOR_NAMES

    @pytest.mark.asyncio
    async def test_sectors_count_is_eight(self, client):
        """The count field reflects exactly 8 sectors."""
        resp = await client.get("/api/v1/onboarding/sectors")
        data = resp.json()
        assert data["count"] == 8
        assert len(data["sectors"]) == 8

    @pytest.mark.asyncio
    async def test_sectors_response_shape(self, client):
        """Each sector has all required fields."""
        resp = await client.get("/api/v1/onboarding/sectors")
        data = resp.json()
        for sector in data["sectors"]:
            for field in _SECTOR_REQUIRED_FIELDS:
                assert field in sector, f"Missing field '{field}' in sector {sector.get('name')}"

    @pytest.mark.asyncio
    async def test_sectors_no_auth_required(self, client):
        """Sectors endpoint is public — no auth header needed."""
        resp = await client.get("/api/v1/onboarding/sectors")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_sectors_each_has_valid_agent_type(self, client):
        """Each sector's agent_type maps to a known value."""
        # Valid agent types include the existing 7 + gaming maps to business
        _VALID = {"personal", "business", "b2b", "a2a", "compliance", "enterprise", "health"}
        resp = await client.get("/api/v1/onboarding/sectors")
        data = resp.json()
        for sector in data["sectors"]:
            assert sector["agent_type"] in _VALID, (
                f"Sector '{sector['name']}' has unknown agent_type '{sector['agent_type']}'"
            )

    @pytest.mark.asyncio
    async def test_sectors_each_has_non_empty_description(self, client):
        """Each sector has a non-empty description string."""
        resp = await client.get("/api/v1/onboarding/sectors")
        data = resp.json()
        for sector in data["sectors"]:
            assert sector["description"], f"Sector '{sector['name']}' has empty description"

    @pytest.mark.asyncio
    async def test_sectors_each_has_icon(self, client):
        """Each sector has a non-empty icon."""
        resp = await client.get("/api/v1/onboarding/sectors")
        data = resp.json()
        for sector in data["sectors"]:
            assert sector["icon"], f"Sector '{sector['name']}' has empty icon"

    @pytest.mark.asyncio
    async def test_sectors_personal_has_correct_agent_type(self, client):
        """The Personal sector maps to agent_type 'personal'."""
        resp = await client.get("/api/v1/onboarding/sectors")
        data = resp.json()
        personal = next((s for s in data["sectors"] if s["name"] == "Personal"), None)
        assert personal is not None
        assert personal["agent_type"] == "personal"

    @pytest.mark.asyncio
    async def test_sectors_gaming_has_correct_agent_type(self, client):
        """The Gaming sector maps to agent_type 'business' (gaming sector maps to business)."""
        resp = await client.get("/api/v1/onboarding/sectors")
        data = resp.json()
        gaming = next((s for s in data["sectors"] if s["name"] == "Gaming"), None)
        assert gaming is not None
        # Gaming maps to 'business' type since the gaming AgentType is not yet in VALID_AGENT_TYPES
        assert gaming["agent_type"] == "business"


# ---------------------------------------------------------------------------
# GET /api/v1/onboarding/check-handle/{handle}
# ---------------------------------------------------------------------------


class TestCheckHandleEndpoint:
    """Tests for GET /api/v1/onboarding/check-handle/{handle}."""

    @pytest.mark.asyncio
    async def test_check_handle_available(self, client):
        """A fresh handle returns available=True, no auth required."""
        resp = await client.get("/api/v1/onboarding/check-handle/fresh-handle")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["handle"] == "fresh-handle"
        assert data["available"] is True

    @pytest.mark.asyncio
    async def test_check_handle_taken(self, client):
        """A handle already claimed returns available=False."""
        # First claim an agent with the handle
        await client.post(
            "/api/v1/agents",
            json={
                "handle": "taken-ob-handle",
                "name": "Taken Agent",
                "agent_type": "business",
            },
            headers=_auth_headers(_USER_A),
        )
        # Now check availability via onboarding endpoint
        resp = await client.get("/api/v1/onboarding/check-handle/taken-ob-handle")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["available"] is False

    @pytest.mark.asyncio
    async def test_check_handle_invalid_format(self, client):
        """An invalid handle format returns available=False with a validation_error."""
        # Uppercase is invalid
        resp = await client.get("/api/v1/onboarding/check-handle/INVALID_HANDLE")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["available"] is False
        # Should have a reason field explaining why
        assert "reason" in data

    @pytest.mark.asyncio
    async def test_check_handle_too_short(self, client):
        """A handle shorter than 3 chars returns available=False with reason."""
        resp = await client.get("/api/v1/onboarding/check-handle/ab")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["available"] is False
        assert "reason" in data

    @pytest.mark.asyncio
    async def test_check_handle_reserved_word(self, client):
        """A reserved handle like 'admin' returns available=False."""
        resp = await client.get("/api/v1/onboarding/check-handle/admin")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["available"] is False

    @pytest.mark.asyncio
    async def test_check_handle_no_auth_required(self, client):
        """Handle check is public — no auth header needed."""
        resp = await client.get("/api/v1/onboarding/check-handle/public-check")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_check_handle_with_numbers(self, client):
        """A handle with lowercase letters and numbers is valid and available."""
        resp = await client.get("/api/v1/onboarding/check-handle/agent99")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["available"] is True

    @pytest.mark.asyncio
    async def test_check_handle_with_hyphens(self, client):
        """A handle with hyphens is valid when following naming rules."""
        resp = await client.get("/api/v1/onboarding/check-handle/my-cool-bot")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["available"] is True

    @pytest.mark.asyncio
    async def test_check_handle_leading_hyphen_invalid(self, client):
        """A handle starting with a hyphen is invalid."""
        resp = await client.get("/api/v1/onboarding/check-handle/-bad-handle")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["available"] is False

    @pytest.mark.asyncio
    async def test_check_handle_response_has_handle_field(self, client):
        """Response echoes back the handle that was checked."""
        handle = "echo-test-handle"
        resp = await client.get(f"/api/v1/onboarding/check-handle/{handle}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["handle"] == handle


# ---------------------------------------------------------------------------
# POST /api/v1/onboarding/claim
# ---------------------------------------------------------------------------


class TestClaimEndpoint:
    """Tests for POST /api/v1/onboarding/claim."""

    @pytest.mark.asyncio
    async def test_claim_creates_agent(self, client):
        """A valid claim with auth creates an agent and returns 201."""
        # Get a template ID first
        tmpl_resp = await client.get("/api/v1/templates")
        templates = tmpl_resp.json()["templates"]
        assert len(templates) > 0
        template_id = templates[0]["id"]
        agent_type = templates[0]["agent_type"]

        resp = await client.post(
            "/api/v1/onboarding/claim",
            json={
                "handle": "claim-test-handle",
                "name": "Claim Test Agent",
                "agent_type": agent_type,
                "template_id": template_id,
            },
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["handle"] == "claim-test-handle"
        assert data["name"] == "Claim Test Agent"
        assert data["agent_type"] == agent_type
        assert data["template_id"] == template_id
        assert data["status"] == "active"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_claim_requires_auth(self, client):
        """Claiming without auth returns 401."""
        resp = await client.post(
            "/api/v1/onboarding/claim",
            json={
                "handle": "no-auth-claim",
                "name": "Test",
                "agent_type": "personal",
            },
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_claim_duplicate_handle_rejected(self, client):
        """Claiming an already-taken handle returns 409."""
        # First claim
        await client.post(
            "/api/v1/onboarding/claim",
            json={
                "handle": "first-claimer",
                "name": "First Agent",
                "agent_type": "business",
            },
            headers=_auth_headers(_USER_A),
        )
        # Second claim same handle (different user)
        resp = await client.post(
            "/api/v1/onboarding/claim",
            json={
                "handle": "first-claimer",
                "name": "Second Agent",
                "agent_type": "business",
            },
            headers=_auth_headers(_USER_B),
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_claim_invalid_handle_format(self, client):
        """Claiming with an invalid handle returns 422."""
        resp = await client.post(
            "/api/v1/onboarding/claim",
            json={
                "handle": "INVALID_HANDLE!",
                "name": "Test Agent",
                "agent_type": "business",
            },
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_claim_with_optional_industry_type(self, client):
        """Claiming with an industry_type stores the value on the agent."""
        resp = await client.post(
            "/api/v1/onboarding/claim",
            json={
                "handle": "claim-industry-test",
                "name": "Restaurant Bot",
                "agent_type": "business",
                "industry_type": "restaurant",
            },
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["industry_type"] == "restaurant"

    @pytest.mark.asyncio
    async def test_claim_personal_agent(self, client):
        """Claiming a personal agent works without industry_type."""
        resp = await client.post(
            "/api/v1/onboarding/claim",
            json={
                "handle": "my-personal-claim",
                "name": "Personal Assistant",
                "agent_type": "personal",
            },
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["agent_type"] == "personal"
        assert data["industry_type"] is None

    @pytest.mark.asyncio
    async def test_claim_b2b_agent(self, client):
        """Claiming a b2b agent type works."""
        resp = await client.post(
            "/api/v1/onboarding/claim",
            json={
                "handle": "b2b-test-agent",
                "name": "B2B Procurement Bot",
                "agent_type": "b2b",
            },
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["agent_type"] == "b2b"

    @pytest.mark.asyncio
    async def test_claim_enterprise_agent(self, client):
        """Claiming an enterprise agent type works."""
        resp = await client.post(
            "/api/v1/onboarding/claim",
            json={
                "handle": "enterprise-test-bot",
                "name": "Enterprise Coordinator",
                "agent_type": "enterprise",
            },
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["agent_type"] == "enterprise"

    @pytest.mark.asyncio
    async def test_claim_response_includes_user_id(self, client):
        """The claim response includes the authenticated user's ID."""
        resp = await client.post(
            "/api/v1/onboarding/claim",
            json={
                "handle": "userid-check-agent",
                "name": "User ID Test",
                "agent_type": "personal",
            },
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["user_id"] == _USER_A

    @pytest.mark.asyncio
    async def test_claim_handle_too_short_returns_422(self, client):
        """A handle shorter than 3 chars returns 422."""
        resp = await client.post(
            "/api/v1/onboarding/claim",
            json={
                "handle": "ab",
                "name": "Short Handle",
                "agent_type": "business",
            },
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_claim_missing_name_returns_422(self, client):
        """Omitting the name field returns 422."""
        resp = await client.post(
            "/api/v1/onboarding/claim",
            json={
                "handle": "missing-name-handle",
                "agent_type": "business",
            },
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_claim_invalid_agent_type_returns_422(self, client):
        """An unknown agent_type value returns 422."""
        resp = await client.post(
            "/api/v1/onboarding/claim",
            json={
                "handle": "bad-type-handle",
                "name": "Bad Type Agent",
                "agent_type": "spectral",  # spectral is not a valid backend type
            },
            headers=_auth_headers(_USER_A),
        )
        # spectral is not valid — must return 422
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_claim_gaming_agent_type_accepted(self, client):
        """gaming is a valid agent_type since S29 — must succeed (200/201/409)."""
        resp = await client.post(
            "/api/v1/onboarding/claim",
            json={
                "handle": "gaming-test-agent",
                "name": "My Gaming Agent",
                "agent_type": "gaming",
            },
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code in (200, 201, 409), (
            f"Expected 200/201/409 for valid gaming type, got {resp.status_code}: {resp.text}"
        )

    @pytest.mark.asyncio
    async def test_claimed_agent_appears_in_list(self, client):
        """After claiming, the agent appears in the user's agent list."""
        create_resp = await client.post(
            "/api/v1/onboarding/claim",
            json={
                "handle": "list-check-agent",
                "name": "List Check Bot",
                "agent_type": "business",
            },
            headers=_auth_headers(_USER_A),
        )
        assert create_resp.status_code == 201, create_resp.text
        agent_id = create_resp.json()["id"]

        list_resp = await client.get(
            "/api/v1/agents",
            headers=_auth_headers(_USER_A),
        )
        assert list_resp.status_code == 200
        ids = [a["id"] for a in list_resp.json()["agents"]]
        assert agent_id in ids

    @pytest.mark.asyncio
    async def test_claim_handle_not_available_after_claim(self, client):
        """After claiming, the handle shows as unavailable in check-handle."""
        handle = "post-claim-check"
        await client.post(
            "/api/v1/onboarding/claim",
            json={
                "handle": handle,
                "name": "Post Claim Agent",
                "agent_type": "personal",
            },
            headers=_auth_headers(_USER_A),
        )
        check_resp = await client.get(f"/api/v1/onboarding/check-handle/{handle}")
        assert check_resp.status_code == 200
        assert check_resp.json()["available"] is False
