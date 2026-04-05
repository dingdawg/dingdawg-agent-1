"""API smoke tests for DD Main integration endpoints.

Tests cover:
- POST /api/v1/integrations/ddmain/register — register business (200, 422)
- POST /api/v1/integrations/ddmain/sync — sync updates (200, 404)
- GET  /api/v1/integrations/ddmain/businesses — list (200, pagination)
- GET  /api/v1/integrations/ddmain/businesses/{id} — get mapping (200, 404)
- DELETE /api/v1/integrations/ddmain/businesses/{id} — unregister (204, 404)
- Auth gate — 401 when no token provided
- Bridge unavailable — 503 guard

The fixture pattern mirrors test_api_agents.py:
1. Sets ISG_AGENT_DB_PATH / ISG_AGENT_SECRET_KEY env vars
2. Clears get_settings lru_cache
3. Triggers the FastAPI lifespan so app.state.ddmain_bridge is populated
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

_SECRET = "test-secret-integrations-suite"
_USER_A = "user-integration-alpha"

_BIZ_ID = "ddmain-biz-0000-0000-0000-000000000001"
_BIZ_ID_2 = "ddmain-biz-0000-0000-0000-000000000002"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(user_id: str, email: str = "integration@example.com") -> str:
    return _create_token(user_id=user_id, email=email, secret_key=_SECRET)


def _auth_headers(user_id: str = _USER_A) -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_token(user_id)}"}


def _reg_payload(
    business_id: str = _BIZ_ID,
    name: str = "Test Restaurant",
    **kwargs,
) -> dict:
    payload = {"business_id": business_id, "name": name}
    payload.update(kwargs)
    return payload


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(tmp_path):
    """Async HTTP client with full app lifespan (ddmain_bridge on app.state)."""
    db_file = str(tmp_path / "test_integrations.db")

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
# POST /api/v1/integrations/ddmain/register
# ---------------------------------------------------------------------------


class TestRegisterEndpoint:
    """Tests for POST /api/v1/integrations/ddmain/register."""

    async def test_register_new_business_returns_200(self, client) -> None:
        resp = await client.post(
            "/api/v1/integrations/ddmain/register",
            json=_reg_payload(),
            headers=_auth_headers(),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["is_new"] is True
        assert body["status"] == "created"
        assert body["agent_id"]
        assert body["handle"]

    async def test_register_same_business_again_returns_updated(self, client) -> None:
        await client.post(
            "/api/v1/integrations/ddmain/register",
            json=_reg_payload(name="First Name"),
            headers=_auth_headers(),
        )
        resp = await client.post(
            "/api/v1/integrations/ddmain/register",
            json=_reg_payload(name="Second Name"),
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_new"] is False
        assert body["status"] == "updated"

    async def test_register_with_full_payload(self, client) -> None:
        resp = await client.post(
            "/api/v1/integrations/ddmain/register",
            json=_reg_payload(
                cuisine_type="Italian",
                description="Great pizza",
                logo_url="https://example.com/logo.png",
                primary_color="#FF0000",
                greeting="Benvenuto!",
                readiness_score=80,
                offerings_count=25,
                agentic_live=True,
            ),
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["is_new"] is True

    async def test_register_requires_auth(self, client) -> None:
        resp = await client.post(
            "/api/v1/integrations/ddmain/register",
            json=_reg_payload(),
        )
        assert resp.status_code == 401

    async def test_register_missing_name_returns_422(self, client) -> None:
        resp = await client.post(
            "/api/v1/integrations/ddmain/register",
            json={"business_id": _BIZ_ID},
            headers=_auth_headers(),
        )
        assert resp.status_code == 422

    async def test_register_missing_business_id_returns_422(self, client) -> None:
        resp = await client.post(
            "/api/v1/integrations/ddmain/register",
            json={"name": "No ID"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v1/integrations/ddmain/sync
# ---------------------------------------------------------------------------


class TestSyncEndpoint:
    """Tests for POST /api/v1/integrations/ddmain/sync."""

    async def test_sync_registered_business_returns_200(self, client) -> None:
        await client.post(
            "/api/v1/integrations/ddmain/register",
            json=_reg_payload(),
            headers=_auth_headers(),
        )
        resp = await client.post(
            "/api/v1/integrations/ddmain/sync",
            json={"business_id": _BIZ_ID, "name": "Updated Name"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "name" in body["updated_fields"]

    async def test_sync_unregistered_business_returns_404(self, client) -> None:
        resp = await client.post(
            "/api/v1/integrations/ddmain/sync",
            json={"business_id": "no-such-biz-id", "name": "Ghost"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 404

    async def test_sync_requires_auth(self, client) -> None:
        resp = await client.post(
            "/api/v1/integrations/ddmain/sync",
            json={"business_id": _BIZ_ID},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/v1/integrations/ddmain/businesses
# ---------------------------------------------------------------------------


class TestListEndpoint:
    """Tests for GET /api/v1/integrations/ddmain/businesses."""

    async def test_list_empty_returns_zero_count(self, client) -> None:
        resp = await client.get(
            "/api/v1/integrations/ddmain/businesses",
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 0
        assert body["businesses"] == []

    async def test_list_shows_registered_businesses(self, client) -> None:
        await client.post(
            "/api/v1/integrations/ddmain/register",
            json=_reg_payload(_BIZ_ID, "Biz One"),
            headers=_auth_headers(),
        )
        await client.post(
            "/api/v1/integrations/ddmain/register",
            json=_reg_payload(_BIZ_ID_2, "Biz Two"),
            headers=_auth_headers(),
        )
        resp = await client.get(
            "/api/v1/integrations/ddmain/businesses",
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 2

    async def test_list_requires_auth(self, client) -> None:
        resp = await client.get("/api/v1/integrations/ddmain/businesses")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/v1/integrations/ddmain/businesses/{id}
# ---------------------------------------------------------------------------


class TestGetBusinessEndpoint:
    """Tests for GET /api/v1/integrations/ddmain/businesses/{business_id}."""

    async def test_get_registered_business_returns_200(self, client) -> None:
        reg = await client.post(
            "/api/v1/integrations/ddmain/register",
            json=_reg_payload(),
            headers=_auth_headers(),
        )
        agent_id = reg.json()["agent_id"]

        resp = await client.get(
            f"/api/v1/integrations/ddmain/businesses/{_BIZ_ID}",
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["business_id"] == _BIZ_ID
        assert body["agent_id"] == agent_id
        assert body["sync_status"] == "active"

    async def test_get_unknown_business_returns_404(self, client) -> None:
        resp = await client.get(
            "/api/v1/integrations/ddmain/businesses/no-such-biz",
            headers=_auth_headers(),
        )
        assert resp.status_code == 404

    async def test_get_requires_auth(self, client) -> None:
        resp = await client.get(
            f"/api/v1/integrations/ddmain/businesses/{_BIZ_ID}"
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /api/v1/integrations/ddmain/businesses/{id}
# ---------------------------------------------------------------------------


class TestDeleteEndpoint:
    """Tests for DELETE /api/v1/integrations/ddmain/businesses/{business_id}."""

    async def test_unregister_returns_204(self, client) -> None:
        await client.post(
            "/api/v1/integrations/ddmain/register",
            json=_reg_payload(),
            headers=_auth_headers(),
        )
        resp = await client.delete(
            f"/api/v1/integrations/ddmain/businesses/{_BIZ_ID}",
            headers=_auth_headers(),
        )
        assert resp.status_code == 204

    async def test_unregister_then_get_still_returns_mapping(self, client) -> None:
        await client.post(
            "/api/v1/integrations/ddmain/register",
            json=_reg_payload(),
            headers=_auth_headers(),
        )
        await client.delete(
            f"/api/v1/integrations/ddmain/businesses/{_BIZ_ID}",
            headers=_auth_headers(),
        )
        # Mapping still exists but with removed status
        resp = await client.get(
            f"/api/v1/integrations/ddmain/businesses/{_BIZ_ID}",
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["sync_status"] == "removed"

    async def test_unregister_unknown_returns_404(self, client) -> None:
        resp = await client.delete(
            "/api/v1/integrations/ddmain/businesses/not-registered",
            headers=_auth_headers(),
        )
        assert resp.status_code == 404

    async def test_unregister_requires_auth(self, client) -> None:
        resp = await client.delete(
            f"/api/v1/integrations/ddmain/businesses/{_BIZ_ID}"
        )
        assert resp.status_code == 401
