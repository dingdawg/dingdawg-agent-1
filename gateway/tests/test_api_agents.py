"""API smoke tests for agent CRUD and handle endpoints.

Tests cover:
- POST /api/v1/agents — create agent (201, 409 duplicate, 422 invalid handle)
- GET /api/v1/agents — list agents (user isolation)
- GET /api/v1/agents/{id} — get agent (200, 404 not found)
- PATCH /api/v1/agents/{id} — update agent (owner only)
- DELETE /api/v1/agents/{id} — archive agent (204)
- GET /api/v1/agents/handle/{handle}/check — availability (no auth)

Auth headers are forged via the same _create_token utility the production
code uses, ensuring the JWT verification path is exercised for real.

The fixture:
1. Sets ISG_AGENT_DB_PATH and ISG_AGENT_SECRET_KEY env vars
2. Clears the get_settings lru_cache so the lifespan picks up the test DB
3. Triggers the FastAPI lifespan via app.router.lifespan_context so that
   app.state.agent_registry, handle_service, template_registry are populated
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

_SECRET = "test-secret-agents-suite"
_USER_A = "user-alpha-001"
_USER_B = "user-beta-002"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(user_id: str, email: str = "test@example.com") -> str:
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
    lifespan context so that all app.state services are initialised before
    requests are made.
    """
    db_file = str(tmp_path / "test_agents.db")

    # Set env vars that the Settings model reads
    os.environ["ISG_AGENT_DB_PATH"] = db_file
    os.environ["ISG_AGENT_SECRET_KEY"] = _SECRET

    # Clear lru_cache so the lifespan picks up the new env vars
    get_settings.cache_clear()

    from isg_agent.app import create_app, lifespan

    app = create_app()

    # Trigger the lifespan so app.state is populated (agent_registry etc.)
    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    # Restore env and cache
    os.environ.pop("ISG_AGENT_DB_PATH", None)
    os.environ.pop("ISG_AGENT_SECRET_KEY", None)
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# POST /api/v1/agents — create
# ---------------------------------------------------------------------------


class TestCreateAgent:
    """Tests for POST /api/v1/agents."""

    @pytest.mark.asyncio
    async def test_create_agent_returns_201(self, client):
        """Creating a valid agent returns 201 with correct fields."""
        resp = await client.post(
            "/api/v1/agents",
            json={
                "handle": "joes-pizza",
                "name": "Joe's Pizza",
                "agent_type": "business",
                "industry_type": "restaurant",
            },
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["handle"] == "joes-pizza"
        assert data["name"] == "Joe's Pizza"
        assert data["agent_type"] == "business"
        assert data["industry_type"] == "restaurant"
        assert data["status"] == "active"
        assert data["subscription_tier"] == "free"
        assert data["user_id"] == _USER_A
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data

    @pytest.mark.asyncio
    async def test_create_agent_requires_auth(self, client):
        """Creating an agent without a token returns 401."""
        resp = await client.post(
            "/api/v1/agents",
            json={"handle": "no-auth-agent", "name": "Test", "agent_type": "personal"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_create_agent_duplicate_handle_returns_409(self, client):
        """Creating two agents with the same handle returns 409 on the second."""
        payload = {
            "handle": "unique-handle",
            "name": "First Agent",
            "agent_type": "business",
        }
        resp1 = await client.post(
            "/api/v1/agents",
            json=payload,
            headers=_auth_headers(_USER_A),
        )
        assert resp1.status_code == 201, resp1.text

        resp2 = await client.post(
            "/api/v1/agents",
            json={**payload, "name": "Duplicate Agent"},
            headers=_auth_headers(_USER_A),
        )
        assert resp2.status_code == 409

    @pytest.mark.asyncio
    async def test_create_agent_invalid_handle_returns_422(self, client):
        """An invalid handle format (uppercase, spaces, etc.) returns 422."""
        resp = await client.post(
            "/api/v1/agents",
            json={"handle": "INVALID_HANDLE!", "name": "Test", "agent_type": "business"},
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_agent_with_template_id(self, client):
        """Creating an agent with a template_id stores the template reference."""
        resp = await client.post(
            "/api/v1/agents",
            json={
                "handle": "salon-agent",
                "name": "My Salon",
                "agent_type": "business",
                "industry_type": "salon",
                "template_id": "some-template-uuid",
            },
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["template_id"] == "some-template-uuid"

    @pytest.mark.asyncio
    async def test_create_personal_agent(self, client):
        """A personal agent can be created without industry_type."""
        resp = await client.post(
            "/api/v1/agents",
            json={
                "handle": "my-assistant",
                "name": "Personal Assistant",
                "agent_type": "personal",
            },
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["agent_type"] == "personal"
        assert data["industry_type"] is None


# ---------------------------------------------------------------------------
# GET /api/v1/agents — list
# ---------------------------------------------------------------------------


class TestListAgents:
    """Tests for GET /api/v1/agents."""

    @pytest.mark.asyncio
    async def test_list_agents_returns_user_agents_only(self, client):
        """Each user only sees their own agents."""
        # User A creates an agent
        await client.post(
            "/api/v1/agents",
            json={"handle": "agent-user-a", "name": "User A Agent", "agent_type": "business"},
            headers=_auth_headers(_USER_A),
        )
        # User B creates an agent
        await client.post(
            "/api/v1/agents",
            json={"handle": "agent-user-b", "name": "User B Agent", "agent_type": "personal"},
            headers=_auth_headers(_USER_B),
        )

        resp_a = await client.get("/api/v1/agents", headers=_auth_headers(_USER_A))
        assert resp_a.status_code == 200
        data_a = resp_a.json()
        assert data_a["count"] == 1
        assert data_a["agents"][0]["handle"] == "agent-user-a"

        resp_b = await client.get("/api/v1/agents", headers=_auth_headers(_USER_B))
        assert resp_b.status_code == 200
        data_b = resp_b.json()
        assert data_b["count"] == 1
        assert data_b["agents"][0]["handle"] == "agent-user-b"

    @pytest.mark.asyncio
    async def test_list_agents_empty_returns_empty_list(self, client):
        """Listing agents for a user with none returns empty list."""
        resp = await client.get("/api/v1/agents", headers=_auth_headers(_USER_A))
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["agents"] == []

    @pytest.mark.asyncio
    async def test_list_agents_requires_auth(self, client):
        """Listing agents without a token returns 401."""
        resp = await client.get("/api/v1/agents")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_agents_filter_by_type(self, client):
        """Filtering by agent_type returns only matching agents."""
        await client.post(
            "/api/v1/agents",
            json={"handle": "biz-agent", "name": "Business", "agent_type": "business"},
            headers=_auth_headers(_USER_A),
        )
        await client.post(
            "/api/v1/agents",
            json={"handle": "personal-agent", "name": "Personal", "agent_type": "personal"},
            headers=_auth_headers(_USER_A),
        )

        resp = await client.get(
            "/api/v1/agents",
            params={"agent_type": "business"},
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["agents"][0]["agent_type"] == "business"


# ---------------------------------------------------------------------------
# GET /api/v1/agents/{agent_id} — get single
# ---------------------------------------------------------------------------


class TestGetAgent:
    """Tests for GET /api/v1/agents/{agent_id}."""

    @pytest.mark.asyncio
    async def test_get_agent_returns_200(self, client):
        """Getting an owned agent returns 200 with correct data."""
        create_resp = await client.post(
            "/api/v1/agents",
            json={"handle": "get-me", "name": "Get Agent", "agent_type": "business"},
            headers=_auth_headers(_USER_A),
        )
        assert create_resp.status_code == 201
        agent_id = create_resp.json()["id"]

        get_resp = await client.get(
            f"/api/v1/agents/{agent_id}",
            headers=_auth_headers(_USER_A),
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == agent_id

    @pytest.mark.asyncio
    async def test_get_nonexistent_agent_returns_404(self, client):
        """Getting a non-existent agent ID returns 404."""
        resp = await client.get(
            "/api/v1/agents/nonexistent-id-12345",
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_agent_owned_by_other_user_returns_404(self, client):
        """A user cannot see another user's agent (returns 404, not 403)."""
        create_resp = await client.post(
            "/api/v1/agents",
            json={"handle": "secret-agent", "name": "Secret", "agent_type": "business"},
            headers=_auth_headers(_USER_A),
        )
        agent_id = create_resp.json()["id"]

        resp = await client.get(
            f"/api/v1/agents/{agent_id}",
            headers=_auth_headers(_USER_B),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_agent_requires_auth(self, client):
        """Getting an agent without auth returns 401."""
        resp = await client.get("/api/v1/agents/any-id")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PATCH /api/v1/agents/{agent_id} — update
# ---------------------------------------------------------------------------


class TestUpdateAgent:
    """Tests for PATCH /api/v1/agents/{agent_id}."""

    @pytest.mark.asyncio
    async def test_update_agent_name(self, client):
        """Updating the agent name returns updated record."""
        create_resp = await client.post(
            "/api/v1/agents",
            json={"handle": "update-me", "name": "Original Name", "agent_type": "business"},
            headers=_auth_headers(_USER_A),
        )
        agent_id = create_resp.json()["id"]

        patch_resp = await client.patch(
            f"/api/v1/agents/{agent_id}",
            json={"name": "Updated Name"},
            headers=_auth_headers(_USER_A),
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["name"] == "Updated Name"

    @pytest.mark.asyncio
    async def test_update_agent_requires_auth(self, client):
        """Updating without auth returns 401."""
        resp = await client.patch("/api/v1/agents/any-id", json={"name": "New"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_update_nonexistent_agent_returns_404(self, client):
        """Updating a non-existent agent returns 404."""
        resp = await client.patch(
            "/api/v1/agents/nonexistent-id",
            json={"name": "New Name"},
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_other_users_agent_returns_404(self, client):
        """Updating another user's agent returns 404 (no information leakage)."""
        create_resp = await client.post(
            "/api/v1/agents",
            json={"handle": "dont-touch", "name": "Mine", "agent_type": "business"},
            headers=_auth_headers(_USER_A),
        )
        agent_id = create_resp.json()["id"]

        resp = await client.patch(
            f"/api/v1/agents/{agent_id}",
            json={"name": "Stolen Name"},
            headers=_auth_headers(_USER_B),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_with_no_fields_returns_400(self, client):
        """Sending an empty PATCH body returns 400."""
        create_resp = await client.post(
            "/api/v1/agents",
            json={"handle": "empty-patch", "name": "Agent", "agent_type": "business"},
            headers=_auth_headers(_USER_A),
        )
        agent_id = create_resp.json()["id"]

        resp = await client.patch(
            f"/api/v1/agents/{agent_id}",
            json={},
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# DELETE /api/v1/agents/{agent_id} — archive
# ---------------------------------------------------------------------------


class TestDeleteAgent:
    """Tests for DELETE /api/v1/agents/{agent_id}."""

    @pytest.mark.asyncio
    async def test_delete_agent_returns_204(self, client):
        """Archiving an owned agent returns 204 No Content."""
        create_resp = await client.post(
            "/api/v1/agents",
            json={"handle": "delete-me", "name": "Bye", "agent_type": "business"},
            headers=_auth_headers(_USER_A),
        )
        agent_id = create_resp.json()["id"]

        del_resp = await client.delete(
            f"/api/v1/agents/{agent_id}",
            headers=_auth_headers(_USER_A),
        )
        assert del_resp.status_code == 204

    @pytest.mark.asyncio
    async def test_deleted_agent_not_in_list(self, client):
        """After deletion, the agent no longer appears in the user's list."""
        create_resp = await client.post(
            "/api/v1/agents",
            json={"handle": "gone-soon", "name": "Gone", "agent_type": "business"},
            headers=_auth_headers(_USER_A),
        )
        agent_id = create_resp.json()["id"]

        await client.delete(
            f"/api/v1/agents/{agent_id}",
            headers=_auth_headers(_USER_A),
        )

        list_resp = await client.get("/api/v1/agents", headers=_auth_headers(_USER_A))
        data = list_resp.json()
        ids = [a["id"] for a in data["agents"]]
        assert agent_id not in ids

    @pytest.mark.asyncio
    async def test_delete_agent_requires_auth(self, client):
        """Deleting without auth returns 401."""
        resp = await client.delete("/api/v1/agents/any-id")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_delete_nonexistent_agent_returns_404(self, client):
        """Deleting a non-existent agent returns 404."""
        resp = await client.delete(
            "/api/v1/agents/nonexistent-id",
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_other_users_agent_returns_404(self, client):
        """Deleting another user's agent returns 404."""
        create_resp = await client.post(
            "/api/v1/agents",
            json={"handle": "protected-agent", "name": "Protected", "agent_type": "business"},
            headers=_auth_headers(_USER_A),
        )
        agent_id = create_resp.json()["id"]

        resp = await client.delete(
            f"/api/v1/agents/{agent_id}",
            headers=_auth_headers(_USER_B),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/agents/handle/{handle}/check — public availability
# ---------------------------------------------------------------------------


class TestHandleCheck:
    """Tests for GET /api/v1/agents/handle/{handle}/check."""

    @pytest.mark.asyncio
    async def test_handle_available_no_auth(self, client):
        """Checking an unclaimed handle returns available=true without auth."""
        resp = await client.get("/api/v1/agents/handle/free-handle/check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["handle"] == "free-handle"
        assert data["available"] is True

    @pytest.mark.asyncio
    async def test_handle_taken_after_agent_created(self, client):
        """After creating an agent with a handle, that handle is no longer available."""
        await client.post(
            "/api/v1/agents",
            json={"handle": "taken-handle", "name": "Taken", "agent_type": "business"},
            headers=_auth_headers(_USER_A),
        )

        resp = await client.get("/api/v1/agents/handle/taken-handle/check")
        assert resp.status_code == 200
        assert resp.json()["available"] is False

    @pytest.mark.asyncio
    async def test_handle_check_invalid_format_returns_not_available(self, client):
        """An invalid handle format returns available=false (not 422)."""
        resp = await client.get("/api/v1/agents/handle/INVALID_HANDLE/check")
        assert resp.status_code == 200
        assert resp.json()["available"] is False

    @pytest.mark.asyncio
    async def test_handle_check_reserved_word_returns_not_available(self, client):
        """Reserved handles (e.g. 'admin') return available=false."""
        resp = await client.get("/api/v1/agents/handle/admin/check")
        assert resp.status_code == 200
        assert resp.json()["available"] is False
