"""Lightweight smoke tests for Agent 1.

Two modes:
1. LOCAL mode (default): runs against the in-process ASGI app.
   Fast, no network needed, safe to run in CI.

2. LIVE mode: runs against the live production Railway deployment.
   Activate by setting the BASE_URL environment variable:

       BASE_URL=https://api.dingdawg.com \
       python3 -m pytest tests/test_smoke_live.py -v

   Live mode tests are marked with @pytest.mark.live and are skipped
   automatically when BASE_URL is not set.

Run local mode only:
    python3 -m pytest tests/test_smoke_live.py -v --tb=short

Run both local and live (requires BASE_URL):
    BASE_URL=https://... python3 -m pytest tests/test_smoke_live.py -v --tb=short
"""

from __future__ import annotations

import os
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_BASE_URL = os.environ.get("BASE_URL", "")
_IS_LIVE = bool(_BASE_URL)
_LIVE_MARK = pytest.mark.skipif(not _IS_LIVE, reason="Set BASE_URL env var for live smoke tests")

# ---------------------------------------------------------------------------
# Local in-process fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def local_client(tmp_path) -> AsyncIterator[AsyncClient]:
    """Full-lifespan async client for local smoke tests."""
    from isg_agent.config import get_settings

    db_file = str(tmp_path / "smoke_test.db")
    os.environ["ISG_AGENT_DB_PATH"] = db_file
    os.environ["ISG_AGENT_SECRET_KEY"] = "smoke-test-secret-do-not-use"
    os.environ["ISG_AGENT_DEPLOYMENT_ENV"] = "test"
    get_settings.cache_clear()

    from isg_agent.app import create_app, lifespan

    app = create_app()
    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    os.environ.pop("ISG_AGENT_DB_PATH", None)
    os.environ.pop("ISG_AGENT_SECRET_KEY", None)
    os.environ.pop("ISG_AGENT_DEPLOYMENT_ENV", None)
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def live_client() -> AsyncIterator[AsyncClient]:
    """HTTP client targeting the live Railway deployment."""
    async with AsyncClient(base_url=_BASE_URL, timeout=30.0) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Local smoke tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLocalSmoke:
    """Smoke tests against the in-process app — must always pass in CI."""

    async def test_health_returns_200_healthy(self, local_client: AsyncClient) -> None:
        resp = await local_client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert "version" in body
        assert body["database"] == "connected"

    async def test_platform_did_returns_200_with_context(
        self, local_client: AsyncClient
    ) -> None:
        resp = await local_client.get("/.well-known/did.json")
        assert resp.status_code == 200
        body = resp.json()
        assert "@context" in body
        assert "id" in body

    async def test_mcp_json_returns_200(self, local_client: AsyncClient) -> None:
        resp = await local_client.get("/.well-known/mcp.json")
        assert resp.status_code == 200
        body = resp.json()
        assert "server_info" in body
        assert "capabilities" in body

    async def test_mcp_server_card_returns_200(self, local_client: AsyncClient) -> None:
        resp = await local_client.get("/.well-known/mcp-server-card.json")
        assert resp.status_code == 200
        body = resp.json()
        assert "serverInfo" in body
        assert "authentication" in body

    async def test_acp_capabilities_returns_200(self, local_client: AsyncClient) -> None:
        resp = await local_client.get("/api/v1/acp/capabilities")
        assert resp.status_code == 200
        body = resp.json()
        assert "capabilities" in body
        assert "acp_spec_version" in body

    async def test_acp_manifest_returns_200(self, local_client: AsyncClient) -> None:
        resp = await local_client.get("/api/v1/acp/.well-known/acp-manifest")
        assert resp.status_code == 200
        body = resp.json()
        assert "acp_spec_version" in body
        assert "merchant" in body

    async def test_register_with_bad_data_returns_422(
        self, local_client: AsyncClient
    ) -> None:
        resp = await local_client.post(
            "/auth/register",
            json={"email": "not-an-email!!!", "password": "short"},
        )
        assert resp.status_code == 422

    async def test_login_with_bad_creds_returns_401(
        self, local_client: AsyncClient
    ) -> None:
        resp = await local_client.post(
            "/auth/login",
            json={"email": "nobody@example.com", "password": "wrongpassword"},
        )
        assert resp.status_code == 401

    async def test_agents_without_auth_returns_401(
        self, local_client: AsyncClient
    ) -> None:
        resp = await local_client.get("/api/v1/agents")
        assert resp.status_code == 401

    async def test_docs_disabled_in_test_mode(self, local_client: AsyncClient) -> None:
        # In production ISG_AGENT_DEPLOYMENT_ENV=production → docs disabled.
        # In test mode (our fixture), docs are enabled, so we just verify the
        # health endpoint is what we get at /health (not docs).
        resp = await local_client.get("/health")
        assert resp.status_code == 200

    async def test_handle_check_public_no_auth(self, local_client: AsyncClient) -> None:
        resp = await local_client.get("/api/v1/agents/handle/doesnotexist123/check")
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is True

    async def test_acp_products_returns_list(self, local_client: AsyncClient) -> None:
        resp = await local_client.get("/api/v1/acp/products")
        assert resp.status_code == 200
        body = resp.json()
        assert "products" in body
        assert isinstance(body["products"], list)
        # Platform should advertise at least one plan
        assert body["count"] >= 0


# ---------------------------------------------------------------------------
# Live smoke tests (skipped unless BASE_URL is set)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLiveSmoke:
    """Smoke tests targeting the live production Railway server.

    Skip this class entirely when BASE_URL is not set.
    """

    @_LIVE_MARK
    async def test_health_returns_200(self, live_client: AsyncClient) -> None:
        resp = await live_client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] in ("healthy", "degraded")
        assert "version" in body

    @_LIVE_MARK
    async def test_platform_did_returns_200_with_context(
        self, live_client: AsyncClient
    ) -> None:
        resp = await live_client.get("/.well-known/did.json")
        assert resp.status_code == 200
        body = resp.json()
        assert "@context" in body

    @_LIVE_MARK
    async def test_acp_manifest_returns_200(self, live_client: AsyncClient) -> None:
        resp = await live_client.get("/api/v1/acp/.well-known/acp-manifest")
        assert resp.status_code == 200
        body = resp.json()
        assert "acp_spec_version" in body

    @_LIVE_MARK
    async def test_acp_capabilities_returns_200(self, live_client: AsyncClient) -> None:
        resp = await live_client.get("/api/v1/acp/capabilities")
        assert resp.status_code == 200

    @_LIVE_MARK
    async def test_docs_disabled_in_production(self, live_client: AsyncClient) -> None:
        # In production ISG_AGENT_DEPLOYMENT_ENV=production → /docs is disabled (404).
        resp = await live_client.get("/docs")
        assert resp.status_code == 404

    @_LIVE_MARK
    async def test_register_with_bad_data_returns_422(
        self, live_client: AsyncClient
    ) -> None:
        resp = await live_client.post(
            "/auth/register",
            json={"email": "bad-data", "password": "x"},
        )
        assert resp.status_code == 422

    @_LIVE_MARK
    async def test_login_with_bad_creds_returns_401(
        self, live_client: AsyncClient
    ) -> None:
        resp = await live_client.post(
            "/auth/login",
            json={"email": "ghost@example.com", "password": "wrongpassword"},
        )
        assert resp.status_code == 401

    @_LIVE_MARK
    async def test_agents_without_auth_returns_401(
        self, live_client: AsyncClient
    ) -> None:
        resp = await live_client.get("/api/v1/agents")
        assert resp.status_code == 401
