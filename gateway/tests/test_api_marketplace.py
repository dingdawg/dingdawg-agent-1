"""API integration tests for the marketplace routes.

Covers all 12 API routes at /api/v1/marketplace/... using the FastAPI
TestClient pattern established in test_api_templates.py.

Auth strategy: uses _create_token() from auth.py to mint valid JWTs
directly (no need to hit /auth/register first).

Admin strategy: sets MARKETPLACE_ADMIN_USERS env var to a known user_id
before each test that requires admin access.
"""

from __future__ import annotations

import os
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from isg_agent.config import get_settings

# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------

_SECRET = "test-secret-marketplace-suite"
_USER_ID = "user_alice"
_USER_ID_2 = "user_bob"
_ADMIN_ID = "admin_carol"


# ---------------------------------------------------------------------------
# Helpers: token minting and auth headers
# ---------------------------------------------------------------------------


def _mint_token(user_id: str, email: str, secret: str = _SECRET) -> str:
    """Mint a valid JWT for a test user without touching the database."""
    from isg_agent.api.routes.auth import _create_token
    return _create_token(user_id=user_id, email=email, secret_key=secret)


def _auth_headers(user_id: str, email: str | None = None) -> dict[str, str]:
    """Return Authorization headers for the given user_id."""
    email = email or f"{user_id}@test.example"
    token = _mint_token(user_id, email)
    return {"Authorization": f"Bearer {token}"}


def _admin_headers(admin_id: str = _ADMIN_ID) -> dict[str, str]:
    """Return Authorization headers for an admin user."""
    return _auth_headers(admin_id, f"{admin_id}@admin.example")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    """Provide an async HTTP client with a running app lifespan.

    - Unique temp DB per test via tmp_path.
    - MARKETPLACE_ADMIN_USERS cleared (admin = any authed user in dev mode).
    - Settings cache cleared before and after.
    """
    db_file = str(tmp_path / "test_marketplace.db")

    monkeypatch.setenv("ISG_AGENT_DB_PATH", db_file)
    monkeypatch.setenv("ISG_AGENT_SECRET_KEY", _SECRET)
    # Clear admin users so any authenticated user can act as admin by default
    monkeypatch.delenv("MARKETPLACE_ADMIN_USERS", raising=False)

    get_settings.cache_clear()

    from isg_agent.app import create_app, lifespan

    app = create_app()

    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    get_settings.cache_clear()


@pytest_asyncio.fixture
async def client_with_admin(tmp_path, monkeypatch):
    """Like ``client`` but with MARKETPLACE_ADMIN_USERS set to _ADMIN_ID."""
    db_file = str(tmp_path / "test_mp_admin.db")

    monkeypatch.setenv("ISG_AGENT_DB_PATH", db_file)
    monkeypatch.setenv("ISG_AGENT_SECRET_KEY", _SECRET)
    monkeypatch.setenv("MARKETPLACE_ADMIN_USERS", _ADMIN_ID)

    get_settings.cache_clear()

    # Patch the module-level _ADMIN_USERS set so it picks up the new value
    import isg_agent.api.routes.marketplace as mp_mod
    original_admin_users = mp_mod._ADMIN_USERS.copy()
    mp_mod._ADMIN_USERS = {_ADMIN_ID}

    from isg_agent.app import create_app, lifespan

    app = create_app()

    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    mp_mod._ADMIN_USERS = original_admin_users
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Test helpers: create + advance listings via the API
# ---------------------------------------------------------------------------


async def _api_create_listing(
    ac: AsyncClient,
    *,
    user_id: str = _USER_ID,
    name: str = "Test Template",
    agent_type: str = "business",
    industry_type: str | None = "restaurant",
    price_cents: int = 0,
    base_template_id: str = "base_tmpl_001",
) -> dict:
    resp = await ac.post(
        "/api/v1/marketplace/templates",
        json={
            "base_template_id": base_template_id,
            "display_name": name,
            "tagline": "Short tagline",
            "description_md": "## Desc",
            "agent_type": agent_type,
            "industry_type": industry_type,
            "price_cents": price_cents,
            "tags": ["tag1"],
            "preview_json": {},
        },
        headers=_auth_headers(user_id),
    )
    assert resp.status_code == 201, f"create_listing failed: {resp.text}"
    return resp.json()


async def _api_submit(
    ac: AsyncClient, listing_id: str, user_id: str = _USER_ID
) -> dict:
    resp = await ac.post(
        f"/api/v1/marketplace/templates/{listing_id}/submit",
        headers=_auth_headers(user_id),
    )
    assert resp.status_code == 200, f"submit failed: {resp.text}"
    return resp.json()


async def _api_approve(
    ac: AsyncClient, listing_id: str, admin_id: str = _USER_ID
) -> dict:
    resp = await ac.post(
        f"/api/v1/marketplace/admin/{listing_id}/approve",
        headers=_auth_headers(admin_id),
    )
    assert resp.status_code == 200, f"approve failed: {resp.text}"
    return resp.json()


async def _make_approved_via_api(
    ac: AsyncClient,
    *,
    user_id: str = _USER_ID,
    name: str = "Approved Template",
    agent_type: str = "business",
    industry_type: str | None = "restaurant",
    price_cents: int = 0,
    admin_id: str = _USER_ID,
) -> dict:
    """Create → submit → approve a listing through the API. Returns approved listing."""
    listing = await _api_create_listing(
        ac,
        user_id=user_id,
        name=name,
        agent_type=agent_type,
        industry_type=industry_type,
        price_cents=price_cents,
    )
    await _api_submit(ac, listing["id"], user_id)
    return await _api_approve(ac, listing["id"], admin_id)


# ===========================================================================
# Public endpoints — no auth required
# ===========================================================================


class TestPublicListListings:
    """Tests for GET /api/v1/marketplace/templates."""

    @pytest.mark.asyncio
    async def test_list_returns_only_approved(self, client):
        """Public listing returns only approved templates."""
        # Create a draft (should not appear)
        await _api_create_listing(client, name="Draft Only")
        # Create an approved
        await _make_approved_via_api(client, name="Visible Approved")
        resp = await client.get("/api/v1/marketplace/templates")
        assert resp.status_code == 200
        data = resp.json()
        names = [item["display_name"] for item in data["items"]]
        assert "Visible Approved" in names
        assert "Draft Only" not in names

    @pytest.mark.asyncio
    async def test_list_no_auth_required(self, client):
        """Public list endpoint works without an Authorization header."""
        resp = await client.get("/api/v1/marketplace/templates")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_response_shape(self, client):
        """Response has items, total, page, page_size keys."""
        resp = await client.get("/api/v1/marketplace/templates")
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data

    @pytest.mark.asyncio
    async def test_list_filter_by_agent_type(self, client):
        """agent_type filter returns only matching listings."""
        await _make_approved_via_api(client, agent_type="business", name="Biz")
        await _make_approved_via_api(client, agent_type="personal", name="Personal")
        resp = await client.get(
            "/api/v1/marketplace/templates", params={"agent_type": "business"}
        )
        assert resp.status_code == 200
        data = resp.json()
        for item in data["items"]:
            assert item["agent_type"] == "business"

    @pytest.mark.asyncio
    async def test_list_filter_by_industry_type(self, client):
        """industry_type filter returns only matching listings."""
        await _make_approved_via_api(
            client, industry_type="restaurant", name="Restaurant"
        )
        await _make_approved_via_api(
            client, industry_type="fitness", name="Fitness"
        )
        resp = await client.get(
            "/api/v1/marketplace/templates", params={"industry_type": "fitness"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["industry_type"] == "fitness"

    @pytest.mark.asyncio
    async def test_list_sort_newest(self, client):
        """sort=newest is accepted without error."""
        resp = await client.get(
            "/api/v1/marketplace/templates", params={"sort": "newest"}
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_sort_most_installed(self, client):
        """sort=most_installed is accepted without error."""
        resp = await client.get(
            "/api/v1/marketplace/templates", params={"sort": "most_installed"}
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_invalid_sort_returns_422(self, client):
        """Invalid sort value returns HTTP 422."""
        resp = await client.get(
            "/api/v1/marketplace/templates", params={"sort": "random_order"}
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_list_pagination(self, client):
        """page and page_size query params are respected."""
        for i in range(5):
            await _make_approved_via_api(client, name=f"Template {i}", user_id=f"u{i}")
        resp = await client.get(
            "/api/v1/marketplace/templates", params={"page": 1, "page_size": 2}
        )
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["page_size"] == 2


class TestPublicGetListing:
    """Tests for GET /api/v1/marketplace/templates/{id}."""

    @pytest.mark.asyncio
    async def test_get_listing_returns_200(self, client):
        """Getting an existing listing returns 200 with full detail."""
        listing = await _api_create_listing(client, name="Single Listing")
        resp = await client.get(f"/api/v1/marketplace/templates/{listing['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == listing["id"]
        assert data["display_name"] == "Single Listing"

    @pytest.mark.asyncio
    async def test_get_listing_no_auth_required(self, client):
        """Getting a listing is public — no Authorization header needed."""
        listing = await _api_create_listing(client)
        resp = await client.get(f"/api/v1/marketplace/templates/{listing['id']}")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_listing_includes_recent_ratings(self, client):
        """Get listing response contains recent_ratings list."""
        listing = await _api_create_listing(client)
        resp = await client.get(f"/api/v1/marketplace/templates/{listing['id']}")
        data = resp.json()
        assert "recent_ratings" in data

    @pytest.mark.asyncio
    async def test_get_listing_404_for_nonexistent(self, client):
        """Requesting a non-existent listing ID returns HTTP 404."""
        resp = await client.get("/api/v1/marketplace/templates/no_such_id_xyz")
        assert resp.status_code == 404


# ===========================================================================
# Authenticated endpoints
# ===========================================================================


class TestCreateListingAPI:
    """Tests for POST /api/v1/marketplace/templates."""

    @pytest.mark.asyncio
    async def test_create_listing_returns_201(self, client):
        """Authenticated POST creates a listing and returns 201."""
        resp = await client.post(
            "/api/v1/marketplace/templates",
            json={
                "base_template_id": "base_1",
                "display_name": "My Listing",
                "tagline": "Tagline here",
                "description_md": "Description",
                "agent_type": "business",
            },
            headers=_auth_headers(_USER_ID),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "draft"
        assert data["display_name"] == "My Listing"

    @pytest.mark.asyncio
    async def test_create_listing_401_without_auth(self, client):
        """POST without Authorization returns 401."""
        resp = await client.post(
            "/api/v1/marketplace/templates",
            json={
                "base_template_id": "base_1",
                "display_name": "Unauthorized Listing",
                "tagline": "t",
                "description_md": "d",
                "agent_type": "business",
            },
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_create_listing_sets_author_to_current_user(self, client):
        """The listing's author_user_id matches the authenticated user."""
        resp = await client.post(
            "/api/v1/marketplace/templates",
            json={
                "base_template_id": "base_1",
                "display_name": "Authored Listing",
                "tagline": "",
                "description_md": "",
                "agent_type": "business",
            },
            headers=_auth_headers(_USER_ID),
        )
        assert resp.status_code == 201
        assert resp.json()["author_user_id"] == _USER_ID


class TestUpdateListingAPI:
    """Tests for PUT /api/v1/marketplace/templates/{id}."""

    @pytest.mark.asyncio
    async def test_update_listing_returns_200(self, client):
        """Author can update their draft listing."""
        listing = await _api_create_listing(client, user_id=_USER_ID)
        resp = await client.put(
            f"/api/v1/marketplace/templates/{listing['id']}",
            json={"display_name": "Updated Name"},
            headers=_auth_headers(_USER_ID),
        )
        assert resp.status_code == 200
        assert resp.json()["display_name"] == "Updated Name"

    @pytest.mark.asyncio
    async def test_update_listing_403_wrong_author(self, client):
        """Non-author gets 403 when trying to update a listing."""
        listing = await _api_create_listing(client, user_id=_USER_ID)
        resp = await client.put(
            f"/api/v1/marketplace/templates/{listing['id']}",
            json={"display_name": "Hack Attempt"},
            headers=_auth_headers(_USER_ID_2),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_update_listing_400_approved_status(self, client):
        """Cannot update an approved listing — returns 400."""
        approved = await _make_approved_via_api(client, user_id=_USER_ID)
        resp = await client.put(
            f"/api/v1/marketplace/templates/{approved['id']}",
            json={"display_name": "Post-Approval Edit"},
            headers=_auth_headers(_USER_ID),
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_update_listing_400_no_fields(self, client):
        """Sending an empty body (all None fields) returns 400."""
        listing = await _api_create_listing(client, user_id=_USER_ID)
        resp = await client.put(
            f"/api/v1/marketplace/templates/{listing['id']}",
            json={},
            headers=_auth_headers(_USER_ID),
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_update_listing_401_without_auth(self, client):
        """PUT without Authorization returns 401."""
        listing = await _api_create_listing(client, user_id=_USER_ID)
        resp = await client.put(
            f"/api/v1/marketplace/templates/{listing['id']}",
            json={"display_name": "No Auth"},
        )
        assert resp.status_code == 401


class TestSubmitListingAPI:
    """Tests for POST /api/v1/marketplace/templates/{id}/submit."""

    @pytest.mark.asyncio
    async def test_submit_returns_200(self, client):
        """Author can submit their draft listing."""
        listing = await _api_create_listing(client, user_id=_USER_ID)
        resp = await client.post(
            f"/api/v1/marketplace/templates/{listing['id']}/submit",
            headers=_auth_headers(_USER_ID),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_submit_403_wrong_author(self, client):
        """Non-author gets 403 when trying to submit."""
        listing = await _api_create_listing(client, user_id=_USER_ID)
        resp = await client.post(
            f"/api/v1/marketplace/templates/{listing['id']}/submit",
            headers=_auth_headers(_USER_ID_2),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_submit_already_approved_returns_400(self, client):
        """Submitting an already-approved listing returns 400."""
        approved = await _make_approved_via_api(client, user_id=_USER_ID)
        resp = await client.post(
            f"/api/v1/marketplace/templates/{approved['id']}/submit",
            headers=_auth_headers(_USER_ID),
        )
        assert resp.status_code == 400


class TestInstallTemplateAPI:
    """Tests for POST /api/v1/marketplace/templates/{id}/install."""

    @pytest.mark.asyncio
    async def test_install_returns_201(self, client):
        """Installing an approved listing returns 201 with install record."""
        approved = await _make_approved_via_api(client, user_id=_USER_ID)
        resp = await client.post(
            f"/api/v1/marketplace/templates/{approved['id']}/install",
            json={"agent_id": "target_agent_001"},
            headers=_auth_headers(_USER_ID_2),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["marketplace_template_id"] == approved["id"]
        assert data["installer_user_id"] == _USER_ID_2

    @pytest.mark.asyncio
    async def test_install_unapproved_returns_400(self, client):
        """Installing a draft (not yet approved) returns 400."""
        draft = await _api_create_listing(client, user_id=_USER_ID)
        resp = await client.post(
            f"/api/v1/marketplace/templates/{draft['id']}/install",
            json={"agent_id": "ag_001"},
            headers=_auth_headers(_USER_ID_2),
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_install_401_without_auth(self, client):
        """Installing without auth returns 401."""
        approved = await _make_approved_via_api(client, user_id=_USER_ID)
        resp = await client.post(
            f"/api/v1/marketplace/templates/{approved['id']}/install",
            json={"agent_id": "ag_001"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_install_submitted_listing_returns_400(self, client):
        """Installing a submitted (not yet approved) listing returns 400."""
        listing = await _api_create_listing(client, user_id=_USER_ID)
        await _api_submit(client, listing["id"], _USER_ID)
        resp = await client.post(
            f"/api/v1/marketplace/templates/{listing['id']}/install",
            json={"agent_id": "ag_001"},
            headers=_auth_headers(_USER_ID_2),
        )
        assert resp.status_code == 400


class TestRateTemplateAPI:
    """Tests for POST /api/v1/marketplace/templates/{id}/rate."""

    @pytest.mark.asyncio
    async def test_rate_returns_200_with_rating(self, client):
        """Rating a listing returns 200 and the rating record."""
        listing = await _api_create_listing(client)
        resp = await client.post(
            f"/api/v1/marketplace/templates/{listing['id']}/rate",
            json={"stars": 4, "review_text": "Pretty good"},
            headers=_auth_headers(_USER_ID_2),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["stars"] == 4
        assert data["review_text"] == "Pretty good"

    @pytest.mark.asyncio
    async def test_rate_stars_below_1_returns_422(self, client):
        """Stars = 0 fails Pydantic validation with HTTP 422."""
        listing = await _api_create_listing(client)
        resp = await client.post(
            f"/api/v1/marketplace/templates/{listing['id']}/rate",
            json={"stars": 0},
            headers=_auth_headers(_USER_ID_2),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_rate_stars_above_5_returns_422(self, client):
        """Stars = 6 fails Pydantic validation with HTTP 422."""
        listing = await _api_create_listing(client)
        resp = await client.post(
            f"/api/v1/marketplace/templates/{listing['id']}/rate",
            json={"stars": 6},
            headers=_auth_headers(_USER_ID_2),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_rate_401_without_auth(self, client):
        """Rating without auth returns 401."""
        listing = await _api_create_listing(client)
        resp = await client.post(
            f"/api/v1/marketplace/templates/{listing['id']}/rate",
            json={"stars": 3},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_rate_nonexistent_listing_returns_400(self, client):
        """Rating a non-existent listing returns 400."""
        resp = await client.post(
            "/api/v1/marketplace/templates/no_listing_xyz/rate",
            json={"stars": 3},
            headers=_auth_headers(_USER_ID),
        )
        assert resp.status_code == 400


class TestForkTemplateAPI:
    """Tests for POST /api/v1/marketplace/templates/{id}/fork."""

    @pytest.mark.asyncio
    async def test_fork_returns_201_with_new_draft(self, client):
        """Forking an approved listing returns 201 with a new draft."""
        approved = await _make_approved_via_api(client, user_id=_USER_ID, name="Source")
        resp = await client.post(
            f"/api/v1/marketplace/templates/{approved['id']}/fork",
            json={"display_name": "My Fork"},
            headers=_auth_headers(_USER_ID_2),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "draft"
        assert data["display_name"] == "My Fork"
        assert data["forked_from_id"] == approved["id"]
        assert data["author_user_id"] == _USER_ID_2

    @pytest.mark.asyncio
    async def test_fork_draft_returns_400(self, client):
        """Forking a draft listing (not approved) returns 400."""
        draft = await _api_create_listing(client, user_id=_USER_ID)
        resp = await client.post(
            f"/api/v1/marketplace/templates/{draft['id']}/fork",
            json={"display_name": "Fork Attempt"},
            headers=_auth_headers(_USER_ID_2),
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_fork_submitted_listing_returns_400(self, client):
        """Forking a submitted (not yet approved) listing returns 400."""
        listing = await _api_create_listing(client, user_id=_USER_ID)
        await _api_submit(client, listing["id"], _USER_ID)
        resp = await client.post(
            f"/api/v1/marketplace/templates/{listing['id']}/fork",
            json={"display_name": "Fork"},
            headers=_auth_headers(_USER_ID_2),
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_fork_401_without_auth(self, client):
        """Forking without auth returns 401."""
        approved = await _make_approved_via_api(client, user_id=_USER_ID)
        resp = await client.post(
            f"/api/v1/marketplace/templates/{approved['id']}/fork",
            json={"display_name": "Anon Fork"},
        )
        assert resp.status_code == 401


class TestMyTemplatesAPI:
    """Tests for GET /api/v1/marketplace/my-templates."""

    @pytest.mark.asyncio
    async def test_my_templates_returns_own_listings(self, client):
        """Returns only listings owned by the authenticated user.

        The my-templates endpoint defaults to status=approved.  We create
        approved listings for Alice and an approved listing for Bob, then
        verify only Alice's listings are returned for Alice's auth token.
        """
        # Alice creates two approved listings
        await _make_approved_via_api(client, user_id=_USER_ID, name="Alice T1")
        await _make_approved_via_api(client, user_id=_USER_ID, name="Alice T2")
        # Bob creates one approved listing
        await _make_approved_via_api(client, user_id=_USER_ID_2, name="Bob T1")

        resp = await client.get(
            "/api/v1/marketplace/my-templates",
            headers=_auth_headers(_USER_ID),
        )
        assert resp.status_code == 200
        data = resp.json()
        names = [item["display_name"] for item in data["items"]]
        assert "Alice T1" in names
        assert "Alice T2" in names
        assert "Bob T1" not in names

    @pytest.mark.asyncio
    async def test_my_templates_401_without_auth(self, client):
        """GET /my-templates without auth returns 401."""
        resp = await client.get("/api/v1/marketplace/my-templates")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_my_templates_empty_for_new_user(self, client):
        """A user with no listings gets an empty result."""
        resp = await client.get(
            "/api/v1/marketplace/my-templates",
            headers=_auth_headers("brand_new_user"),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0


class TestEarningsAPI:
    """Tests for GET /api/v1/marketplace/earnings."""

    @pytest.mark.asyncio
    async def test_earnings_returns_user_id(self, client):
        """Earnings endpoint returns the authenticated user's user_id."""
        resp = await client.get(
            "/api/v1/marketplace/earnings",
            headers=_auth_headers(_USER_ID),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == _USER_ID

    @pytest.mark.asyncio
    async def test_earnings_zero_for_new_creator(self, client):
        """New creator with no installs has zero earnings."""
        resp = await client.get(
            "/api/v1/marketplace/earnings",
            headers=_auth_headers("fresh_creator"),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_earned_cents"] == 0
        assert data["template_count"] == 0

    @pytest.mark.asyncio
    async def test_earnings_reflects_paid_installs(self, client):
        """After a paid install, creator earnings show correct payout."""
        # Create and approve a paid listing
        listing = await _api_create_listing(
            client, user_id=_USER_ID, name="Paid T", price_cents=500
        )
        await _api_submit(client, listing["id"], _USER_ID)
        await _api_approve(client, listing["id"], _USER_ID)

        # Another user installs it
        await client.post(
            f"/api/v1/marketplace/templates/{listing['id']}/install",
            json={"agent_id": "ag_pay"},
            headers=_auth_headers(_USER_ID_2),
        )

        resp = await client.get(
            "/api/v1/marketplace/earnings",
            headers=_auth_headers(_USER_ID),
        )
        assert resp.status_code == 200
        data = resp.json()
        # 500 * 70% = 350
        assert data["total_earned_cents"] == 350

    @pytest.mark.asyncio
    async def test_earnings_401_without_auth(self, client):
        """GET /earnings without auth returns 401."""
        resp = await client.get("/api/v1/marketplace/earnings")
        assert resp.status_code == 401


# ===========================================================================
# Admin endpoints
# ===========================================================================


class TestAdminApproveAPI:
    """Tests for POST /api/v1/marketplace/admin/{id}/approve."""

    @pytest.mark.asyncio
    async def test_admin_approve_returns_200(self, client):
        """Admin (or any user in dev mode) can approve a submitted listing."""
        listing = await _api_create_listing(client, user_id=_USER_ID)
        await _api_submit(client, listing["id"], _USER_ID)
        resp = await client.post(
            f"/api/v1/marketplace/admin/{listing['id']}/approve",
            headers=_auth_headers(_USER_ID),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approved"
        assert data["reviewed_by"] == _USER_ID
        assert data["published_at"] is not None

    @pytest.mark.asyncio
    async def test_admin_approve_draft_returns_400(self, client):
        """Approving a draft (not submitted) returns 400."""
        listing = await _api_create_listing(client, user_id=_USER_ID)
        resp = await client.post(
            f"/api/v1/marketplace/admin/{listing['id']}/approve",
            headers=_auth_headers(_USER_ID),
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_admin_approve_401_without_auth(self, client):
        """Approve endpoint without auth returns 401."""
        listing = await _api_create_listing(client, user_id=_USER_ID)
        resp = await client.post(
            f"/api/v1/marketplace/admin/{listing['id']}/approve",
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_admin_approve_403_non_admin(self, client_with_admin):
        """With MARKETPLACE_ADMIN_USERS configured, non-admin user gets 403."""
        listing = await _api_create_listing(
            client_with_admin, user_id=_USER_ID
        )
        await _api_submit(client_with_admin, listing["id"], _USER_ID)
        # _USER_ID is NOT in _ADMIN_USERS (which contains only _ADMIN_ID)
        resp = await client_with_admin.post(
            f"/api/v1/marketplace/admin/{listing['id']}/approve",
            headers=_auth_headers(_USER_ID),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_approve_200_actual_admin(self, client_with_admin):
        """With MARKETPLACE_ADMIN_USERS configured, the admin user can approve."""
        listing = await _api_create_listing(
            client_with_admin, user_id=_USER_ID
        )
        await _api_submit(client_with_admin, listing["id"], _USER_ID)
        resp = await client_with_admin.post(
            f"/api/v1/marketplace/admin/{listing['id']}/approve",
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"


class TestAdminRejectAPI:
    """Tests for POST /api/v1/marketplace/admin/{id}/reject."""

    @pytest.mark.asyncio
    async def test_admin_reject_returns_200_with_reason(self, client):
        """Admin can reject a submitted listing with a reason."""
        listing = await _api_create_listing(client, user_id=_USER_ID)
        await _api_submit(client, listing["id"], _USER_ID)
        resp = await client.post(
            f"/api/v1/marketplace/admin/{listing['id']}/reject",
            json={"reason": "Needs better screenshots"},
            headers=_auth_headers(_USER_ID),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "rejected"
        assert data["rejection_reason"] == "Needs better screenshots"

    @pytest.mark.asyncio
    async def test_admin_reject_draft_returns_400(self, client):
        """Rejecting a draft (not submitted) returns 400."""
        listing = await _api_create_listing(client, user_id=_USER_ID)
        resp = await client.post(
            f"/api/v1/marketplace/admin/{listing['id']}/reject",
            json={"reason": "Bad draft"},
            headers=_auth_headers(_USER_ID),
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_admin_reject_401_without_auth(self, client):
        """Reject endpoint without auth returns 401."""
        listing = await _api_create_listing(client, user_id=_USER_ID)
        resp = await client.post(
            f"/api/v1/marketplace/admin/{listing['id']}/reject",
            json={"reason": "reason"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_admin_reject_missing_reason_returns_422(self, client):
        """Reject request missing 'reason' field fails Pydantic validation (422)."""
        listing = await _api_create_listing(client, user_id=_USER_ID)
        await _api_submit(client, listing["id"], _USER_ID)
        resp = await client.post(
            f"/api/v1/marketplace/admin/{listing['id']}/reject",
            json={},
            headers=_auth_headers(_USER_ID),
        )
        assert resp.status_code == 422


# ===========================================================================
# Error-path edge cases
# ===========================================================================


class TestEdgeCasesAPI:
    """Error paths and boundary conditions across routes."""

    @pytest.mark.asyncio
    async def test_update_approved_template_returns_400(self, client):
        """Updating a listing after approval is rejected with 400."""
        approved = await _make_approved_via_api(client, user_id=_USER_ID)
        resp = await client.put(
            f"/api/v1/marketplace/templates/{approved['id']}",
            json={"tagline": "Sneaky edit"},
            headers=_auth_headers(_USER_ID),
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_submit_approved_template_returns_400(self, client):
        """Re-submitting an approved template returns 400."""
        approved = await _make_approved_via_api(client, user_id=_USER_ID)
        resp = await client.post(
            f"/api/v1/marketplace/templates/{approved['id']}/submit",
            headers=_auth_headers(_USER_ID),
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_install_returns_correct_installer_user_id(self, client):
        """Install record's installer_user_id matches the authenticated requester."""
        approved = await _make_approved_via_api(client, user_id=_USER_ID)
        resp = await client.post(
            f"/api/v1/marketplace/templates/{approved['id']}/install",
            json={"agent_id": "agent_check"},
            headers=_auth_headers(_USER_ID_2),
        )
        assert resp.status_code == 201
        assert resp.json()["installer_user_id"] == _USER_ID_2

    @pytest.mark.asyncio
    async def test_fork_unapproved_template_returns_400(self, client):
        """Forking a template that has not been approved returns 400."""
        draft = await _api_create_listing(client, user_id=_USER_ID)
        resp = await client.post(
            f"/api/v1/marketplace/templates/{draft['id']}/fork",
            json={"display_name": "Fork of Draft"},
            headers=_auth_headers(_USER_ID_2),
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_rate_nonexistent_template_returns_400(self, client):
        """Rating a listing that does not exist returns 400."""
        resp = await client.post(
            "/api/v1/marketplace/templates/ghost_listing/rate",
            json={"stars": 5},
            headers=_auth_headers(_USER_ID),
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_price_cents_must_be_non_negative(self, client):
        """Listing creation with negative price_cents fails Pydantic validation."""
        resp = await client.post(
            "/api/v1/marketplace/templates",
            json={
                "base_template_id": "b1",
                "display_name": "Bad Price",
                "tagline": "",
                "description_md": "",
                "agent_type": "business",
                "price_cents": -100,
            },
            headers=_auth_headers(_USER_ID),
        )
        assert resp.status_code == 422
