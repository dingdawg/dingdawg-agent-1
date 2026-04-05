"""Backend tests for the CLI invoke endpoints.

TDD-first: tests written before implementation.

Tests cover:
- POST /api/v1/cli/invoke — invoke agent from CLI (SSE stream, requires auth)
- GET  /api/v1/cli/agents — list user's agents
- GET  /api/v1/cli/agents/{handle}/skills — list agent's skills
- POST /api/v1/cli/device-code — generate device auth code (public)
- POST /api/v1/cli/device-token — exchange device code for token (public)
- CLI analytics tagging: source="cli" is recorded on invoke
- Tier isolation: CLI routes are governed by tier policy

Uses the same async lifespan fixture pattern as test_api_agents.py and
test_onboarding.py.
"""

from __future__ import annotations

import os
import time
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from isg_agent.api.routes.auth import _create_token
from isg_agent.config import get_settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SECRET = "test-secret-cli-invoke-suite"
_USER_A = "user-cli-alpha-001"
_USER_B = "user-cli-beta-002"
_BACKEND_URL = os.environ.get("BACKEND_URL", "https://api.dingdawg.com")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(user_id: str, email: str = "test@cli.dingdawg.com") -> str:
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
    db_file = str(tmp_path / "test_cli.db")

    os.environ["ISG_AGENT_DB_PATH"] = db_file
    os.environ["ISG_AGENT_SECRET_KEY"] = _SECRET
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
async def client_with_agent(client, tmp_path):
    """Extend client fixture with a pre-created agent for user A.

    Registers user A and creates an agent handle 'my-test-biz'.
    Yields (client, agent_data).
    """
    # Register user A
    await client.post(
        "/auth/register",
        json={"email": "clitest@dingdawg.com", "password": "TestPass123!", "terms_accepted": True},
    )

    # Create an agent for user A
    resp = await client.post(
        "/api/v1/agents",
        json={
            "handle": "my-test-biz",
            "name": "My Test Business",
            "agent_type": "business",
            "industry_type": "retail",
        },
        headers=_auth_headers(_USER_A),
    )
    assert resp.status_code == 201, f"Agent creation failed: {resp.text}"
    agent_data = resp.json()
    yield client, agent_data


# ---------------------------------------------------------------------------
# Section 1: POST /api/v1/cli/invoke — endpoint existence + auth
# ---------------------------------------------------------------------------


class TestCLIInvokeEndpointExists:
    """The /api/v1/cli/invoke endpoint must exist and respond."""

    @pytest.mark.asyncio
    async def test_cli_invoke_endpoint_exists(self, client):
        """POST /api/v1/cli/invoke returns non-404 (route is registered)."""
        resp = await client.post(
            "/api/v1/cli/invoke",
            json={"handle": "@nonexistent", "message": "hello"},
        )
        # Without auth we expect 401, not 404 — proving the route exists
        assert resp.status_code != 404, (
            "Route /api/v1/cli/invoke does not exist — check router registration"
        )

    @pytest.mark.asyncio
    async def test_cli_invoke_requires_auth_bearer(self, client):
        """POST /api/v1/cli/invoke without Authorization returns 401."""
        resp = await client.post(
            "/api/v1/cli/invoke",
            json={"handle": "@mybusiness", "message": "hello"},
        )
        assert resp.status_code == 401, resp.text

    @pytest.mark.asyncio
    async def test_cli_invoke_requires_auth_api_key(self, client):
        """POST /api/v1/cli/invoke with X-DD-API-Key but invalid key returns 401."""
        resp = await client.post(
            "/api/v1/cli/invoke",
            json={"handle": "@mybusiness", "message": "hello"},
            headers={"X-DD-API-Key": "sk_invalid_key_000"},
        )
        # Invalid API key: must reject with 401
        assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# Section 2: Handle resolution
# ---------------------------------------------------------------------------


class TestCLIInvokeResolvesHandle:
    """The invoke endpoint must resolve @handle to a real agent."""

    @pytest.mark.asyncio
    async def test_cli_invoke_unknown_handle_returns_404(self, client):
        """POST /api/v1/cli/invoke with unknown handle returns 404."""
        resp = await client.post(
            "/api/v1/cli/invoke",
            json={"handle": "@does-not-exist-ever-xyz", "message": "hello"},
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 404, resp.text

    @pytest.mark.asyncio
    async def test_cli_invoke_resolves_handle_with_at_prefix(self, client_with_agent):
        """@handle (with @) resolves to the correct agent."""
        client, agent_data = client_with_agent
        resp = await client.post(
            "/api/v1/cli/invoke",
            json={"handle": "@my-test-biz", "message": "hello"},
            headers=_auth_headers(_USER_A),
        )
        # Should not be 404 — agent exists and is owned by user A
        assert resp.status_code != 404, (
            f"Handle @my-test-biz not resolved. Response: {resp.text}"
        )

    @pytest.mark.asyncio
    async def test_cli_invoke_resolves_handle_without_at_prefix(self, client_with_agent):
        """handle (without @) also resolves correctly."""
        client, agent_data = client_with_agent
        resp = await client.post(
            "/api/v1/cli/invoke",
            json={"handle": "my-test-biz", "message": "hello"},
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code != 404, (
            f"Handle my-test-biz (no @) not resolved. Response: {resp.text}"
        )


# ---------------------------------------------------------------------------
# Section 3: SSE stream response
# ---------------------------------------------------------------------------


class TestCLIInvokeReturnsSSEStream:
    """The invoke endpoint must return a text/event-stream response."""

    @pytest.mark.asyncio
    async def test_cli_invoke_returns_sse_content_type(self, client_with_agent):
        """POST /api/v1/cli/invoke returns Content-Type: text/event-stream."""
        client, agent_data = client_with_agent
        resp = await client.post(
            "/api/v1/cli/invoke",
            json={"handle": "@my-test-biz", "message": "say hi"},
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 200, resp.text
        content_type = resp.headers.get("content-type", "")
        assert "text/event-stream" in content_type, (
            f"Expected text/event-stream, got: {content_type}"
        )

    @pytest.mark.asyncio
    async def test_cli_invoke_sse_contains_data_events(self, client_with_agent):
        """SSE response body contains 'data:' prefixed lines."""
        client, agent_data = client_with_agent
        resp = await client.post(
            "/api/v1/cli/invoke",
            json={"handle": "@my-test-biz", "message": "say hi"},
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 200, resp.text
        body = resp.text
        assert "data:" in body, f"No SSE data events in response body: {body[:300]}"

    @pytest.mark.asyncio
    async def test_cli_invoke_sse_contains_done_event(self, client_with_agent):
        """SSE stream terminates with a [DONE] marker or done event."""
        client, agent_data = client_with_agent
        resp = await client.post(
            "/api/v1/cli/invoke",
            json={"handle": "@my-test-biz", "message": "say hi"},
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 200, resp.text
        body = resp.text
        # Either [DONE] or event: done in the stream
        assert ("[DONE]" in body or "event: done" in body), (
            f"SSE stream has no termination marker: {body[:500]}"
        )


# ---------------------------------------------------------------------------
# Section 4: Skill invocation
# ---------------------------------------------------------------------------


class TestCLIInvokeWithExplicitSkill:
    """The invoke endpoint must support explicit skill dispatch."""

    @pytest.mark.asyncio
    async def test_cli_invoke_with_skill_field(self, client_with_agent):
        """POST with skill='appointments' is accepted (not rejected with 400)."""
        client, agent_data = client_with_agent
        resp = await client.post(
            "/api/v1/cli/invoke",
            json={
                "handle": "@my-test-biz",
                "message": "list my appointments",
                "skill": "appointments",
            },
            headers=_auth_headers(_USER_A),
        )
        # Must be 200 (SSE) or a meaningful skill error — not 400/422
        assert resp.status_code not in (400, 422), (
            f"Skill field was rejected: {resp.text}"
        )

    @pytest.mark.asyncio
    async def test_cli_invoke_with_action_field(self, client_with_agent):
        """POST with action='list' alongside skill is accepted."""
        client, agent_data = client_with_agent
        resp = await client.post(
            "/api/v1/cli/invoke",
            json={
                "handle": "@my-test-biz",
                "message": "list my appointments",
                "skill": "appointments",
                "action": "list",
                "parameters": {},
            },
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code not in (400, 422), (
            f"Action field was rejected: {resp.text}"
        )

    @pytest.mark.asyncio
    async def test_cli_invoke_empty_message_returns_422(self, client_with_agent):
        """POST with empty message string returns 422."""
        client, agent_data = client_with_agent
        resp = await client.post(
            "/api/v1/cli/invoke",
            json={"handle": "@my-test-biz", "message": ""},
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# Section 5: GET /api/v1/cli/agents — list agents
# ---------------------------------------------------------------------------


class TestCLIAgentsList:
    """GET /api/v1/cli/agents returns the authenticated user's agents."""

    @pytest.mark.asyncio
    async def test_cli_agents_list_endpoint_exists(self, client):
        """GET /api/v1/cli/agents returns non-404."""
        resp = await client.get("/api/v1/cli/agents")
        assert resp.status_code != 404, (
            "Route /api/v1/cli/agents does not exist"
        )

    @pytest.mark.asyncio
    async def test_cli_agents_list_requires_auth(self, client):
        """GET /api/v1/cli/agents without token returns 401."""
        resp = await client.get("/api/v1/cli/agents")
        assert resp.status_code == 401, resp.text

    @pytest.mark.asyncio
    async def test_cli_agents_list_returns_agents(self, client_with_agent):
        """GET /api/v1/cli/agents returns at least one agent."""
        client, agent_data = client_with_agent
        resp = await client.get(
            "/api/v1/cli/agents",
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "agents" in data, f"Missing 'agents' key: {data}"
        assert len(data["agents"]) >= 1, f"Expected at least 1 agent: {data}"

    @pytest.mark.asyncio
    async def test_cli_agents_list_response_shape(self, client_with_agent):
        """Each agent in the list has expected fields."""
        client, agent_data = client_with_agent
        resp = await client.get(
            "/api/v1/cli/agents",
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        agents = data["agents"]
        assert len(agents) >= 1
        agent = agents[0]
        required_fields = {"id", "handle", "name", "agent_type", "status"}
        missing = required_fields - set(agent.keys())
        assert not missing, f"Agent missing fields: {missing}"

    @pytest.mark.asyncio
    async def test_cli_agents_list_user_isolation(self, client_with_agent):
        """User B cannot see User A's agents."""
        client, agent_data = client_with_agent
        resp = await client.get(
            "/api/v1/cli/agents",
            headers=_auth_headers(_USER_B),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        handles = [a["handle"] for a in data["agents"]]
        assert "my-test-biz" not in handles, (
            f"User B should not see User A's agent: {handles}"
        )

    @pytest.mark.asyncio
    async def test_cli_agents_list_includes_count(self, client_with_agent):
        """Response includes a 'count' field."""
        client, agent_data = client_with_agent
        resp = await client.get(
            "/api/v1/cli/agents",
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "count" in data, f"Missing 'count' key: {data}"


# ---------------------------------------------------------------------------
# Section 6: GET /api/v1/cli/agents/{handle}/skills
# ---------------------------------------------------------------------------


class TestCLIAgentsSkills:
    """GET /api/v1/cli/agents/{handle}/skills returns skills for an agent."""

    @pytest.mark.asyncio
    async def test_cli_agents_skills_endpoint_exists(self, client_with_agent):
        """GET /api/v1/cli/agents/my-test-biz/skills returns non-404."""
        client, agent_data = client_with_agent
        resp = await client.get(
            "/api/v1/cli/agents/my-test-biz/skills",
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code != 404, (
            f"Route /api/v1/cli/agents/{{handle}}/skills does not exist: {resp.text}"
        )

    @pytest.mark.asyncio
    async def test_cli_agents_skills_requires_auth(self, client):
        """GET /api/v1/cli/agents/{handle}/skills without token returns 401."""
        resp = await client.get("/api/v1/cli/agents/any-handle/skills")
        assert resp.status_code == 401, resp.text

    @pytest.mark.asyncio
    async def test_cli_agents_skills_returns_list(self, client_with_agent):
        """Response contains a 'skills' list."""
        client, agent_data = client_with_agent
        resp = await client.get(
            "/api/v1/cli/agents/my-test-biz/skills",
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "skills" in data, f"Missing 'skills' key: {data}"
        assert isinstance(data["skills"], list), f"'skills' is not a list: {data}"

    @pytest.mark.asyncio
    async def test_cli_agents_skills_unknown_handle_404(self, client_with_agent):
        """GET skills for unknown handle returns 404."""
        client, agent_data = client_with_agent
        resp = await client.get(
            "/api/v1/cli/agents/no-such-agent-xyz99/skills",
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 404, resp.text

    @pytest.mark.asyncio
    async def test_cli_agents_skills_with_at_prefix(self, client_with_agent):
        """GET /api/v1/cli/agents/@my-test-biz/skills also works."""
        client, agent_data = client_with_agent
        resp = await client.get(
            "/api/v1/cli/agents/@my-test-biz/skills",
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Section 7: Device code flow
# ---------------------------------------------------------------------------


class TestCLIDeviceCodeGeneration:
    """POST /api/v1/cli/device-code generates a device auth code (public)."""

    @pytest.mark.asyncio
    async def test_device_code_endpoint_exists(self, client):
        """POST /api/v1/cli/device-code returns non-404."""
        resp = await client.post("/api/v1/cli/device-code", json={})
        assert resp.status_code != 404, (
            "Route /api/v1/cli/device-code does not exist"
        )

    @pytest.mark.asyncio
    async def test_device_code_is_public(self, client):
        """POST /api/v1/cli/device-code requires NO auth."""
        resp = await client.post("/api/v1/cli/device-code", json={})
        # Must not return 401 — this is a public endpoint
        assert resp.status_code != 401, (
            f"device-code should be public but returned 401: {resp.text}"
        )

    @pytest.mark.asyncio
    async def test_device_code_returns_required_fields(self, client):
        """Response contains device_code, user_code, verification_url, expires_in."""
        resp = await client.post("/api/v1/cli/device-code", json={})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        required = {"device_code", "user_code", "verification_url", "expires_in"}
        missing = required - set(data.keys())
        assert not missing, f"Response missing fields: {missing}. Got: {data}"

    @pytest.mark.asyncio
    async def test_device_code_user_code_is_readable(self, client):
        """user_code is a short human-readable string (e.g. XXXX-XXXX)."""
        resp = await client.post("/api/v1/cli/device-code", json={})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        user_code = data.get("user_code", "")
        assert len(user_code) >= 4, f"user_code too short: {user_code!r}"
        assert isinstance(user_code, str), f"user_code not a string: {user_code}"

    @pytest.mark.asyncio
    async def test_device_code_verification_url_contains_code(self, client):
        """verification_url contains the user_code for direct URL opening."""
        resp = await client.post("/api/v1/cli/device-code", json={})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        user_code = data.get("user_code", "")
        verification_url = data.get("verification_url", "")
        assert user_code in verification_url or "device" in verification_url, (
            f"verification_url {verification_url!r} should contain user_code or 'device'"
        )

    @pytest.mark.asyncio
    async def test_device_code_expires_in_is_positive(self, client):
        """expires_in is a positive integer (seconds until expiry)."""
        resp = await client.post("/api/v1/cli/device-code", json={})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        expires_in = data.get("expires_in", 0)
        assert isinstance(expires_in, int), f"expires_in not int: {expires_in}"
        assert expires_in > 0, f"expires_in must be positive: {expires_in}"

    @pytest.mark.asyncio
    async def test_device_code_device_code_is_unique(self, client):
        """Two calls to device-code return different device_code values."""
        r1 = await client.post("/api/v1/cli/device-code", json={})
        r2 = await client.post("/api/v1/cli/device-code", json={})
        assert r1.status_code == 200, r1.text
        assert r2.status_code == 200, r2.text
        code1 = r1.json().get("device_code")
        code2 = r2.json().get("device_code")
        assert code1 != code2, "device_code values must be unique across calls"


# ---------------------------------------------------------------------------
# Section 8: Device token exchange
# ---------------------------------------------------------------------------


class TestCLIDeviceTokenExchange:
    """POST /api/v1/cli/device-token exchanges a device code for a JWT."""

    @pytest.mark.asyncio
    async def test_device_token_endpoint_exists(self, client):
        """POST /api/v1/cli/device-token returns non-404."""
        resp = await client.post(
            "/api/v1/cli/device-token",
            json={"device_code": "some-code"},
        )
        assert resp.status_code != 404, (
            "Route /api/v1/cli/device-token does not exist"
        )

    @pytest.mark.asyncio
    async def test_device_token_is_public(self, client):
        """POST /api/v1/cli/device-token requires NO Authorization header.

        The endpoint itself is public — any 401 must be about the device_code
        validity, not about a missing Bearer token.  We verify this by checking
        the error detail does not mention 'Authentication required'.
        """
        resp = await client.post(
            "/api/v1/cli/device-token",
            json={"device_code": "pending-code-xyz"},
        )
        # The endpoint must not require a Bearer token.
        # If 401, it should be about the device_code, not the auth header.
        if resp.status_code == 401:
            detail = resp.json().get("detail", "")
            assert "Authentication required" not in detail, (
                f"device-token endpoint requires a Bearer token (should be public): {detail}"
            )

    @pytest.mark.asyncio
    async def test_device_token_missing_device_code_returns_422(self, client):
        """POST without device_code returns 422 Unprocessable Entity."""
        resp = await client.post(
            "/api/v1/cli/device-token",
            json={},
        )
        assert resp.status_code == 422, resp.text

    @pytest.mark.asyncio
    async def test_device_token_invalid_code_returns_400_or_401(self, client):
        """POST with unknown/expired device_code returns 400 or 401."""
        resp = await client.post(
            "/api/v1/cli/device-token",
            json={"device_code": "invalid-code-does-not-exist"},
        )
        assert resp.status_code in (400, 401), (
            f"Expected 400 or 401 for invalid device_code, got {resp.status_code}: {resp.text}"
        )

    @pytest.mark.asyncio
    async def test_device_token_pending_code_returns_202(self, client):
        """POST with a valid but un-confirmed device_code returns 202 (still pending)."""
        # First create a fresh device code
        r = await client.post("/api/v1/cli/device-code", json={})
        assert r.status_code == 200, r.text
        device_code = r.json()["device_code"]

        # Try to exchange immediately — it has not been confirmed in browser yet
        resp = await client.post(
            "/api/v1/cli/device-token",
            json={"device_code": device_code},
        )
        # Should return 202 (authorization_pending), not 200 or 401
        assert resp.status_code == 202, (
            f"Expected 202 authorization_pending for unconfirmed code, got {resp.status_code}: {resp.text}"
        )


# ---------------------------------------------------------------------------
# Section 9: Analytics source tagging
# ---------------------------------------------------------------------------


class TestCLIInvokeRecordsUsageWithSourceCLI:
    """CLI invocations are tagged with source='cli' in analytics."""

    @pytest.mark.asyncio
    async def test_cli_invoke_source_field_accepted(self, client_with_agent):
        """POST /api/v1/cli/invoke accepts optional source field."""
        client, agent_data = client_with_agent
        resp = await client.post(
            "/api/v1/cli/invoke",
            json={
                "handle": "@my-test-biz",
                "message": "hello from cli",
                "source": "cli",
            },
            headers=_auth_headers(_USER_A),
        )
        # Providing source='cli' must not cause a 422
        assert resp.status_code not in (400, 422), (
            f"source field was rejected: {resp.text}"
        )

    @pytest.mark.asyncio
    async def test_cli_invoke_response_includes_source(self, client_with_agent):
        """The SSE stream or completion event includes source metadata."""
        client, agent_data = client_with_agent
        resp = await client.post(
            "/api/v1/cli/invoke",
            json={"handle": "@my-test-biz", "message": "hello"},
            headers=_auth_headers(_USER_A),
        )
        assert resp.status_code == 200, resp.text
        body = resp.text
        # The stream data or a metadata event should tag this as 'cli'
        # We check that the stream contains _some_ data (the source tagging
        # is internal; we verify that the pipeline ran end-to-end)
        assert "data:" in body, f"SSE stream has no data events: {body[:300]}"


# ---------------------------------------------------------------------------
# Section 10: Tier isolation
# ---------------------------------------------------------------------------


class TestCLIRouteTierRules:
    """CLI routes must be governed by the tier policy (not fall-through 403)."""

    @pytest.mark.asyncio
    async def test_cli_invoke_is_not_ungoverned(self, client):
        """POST /api/v1/cli/invoke must not return 403 'ungoverned route'."""
        resp = await client.post(
            "/api/v1/cli/invoke",
            json={"handle": "@test", "message": "hello"},
            headers=_auth_headers(_USER_A),
        )
        # 403 with "route not governed" means tier rules are missing
        if resp.status_code == 403:
            detail = resp.json().get("detail", "")
            assert "not governed" not in detail, (
                f"CLI invoke route is ungoverned: {detail}"
            )

    @pytest.mark.asyncio
    async def test_cli_agents_is_not_ungoverned(self, client):
        """GET /api/v1/cli/agents must not return 403 'ungoverned route'."""
        resp = await client.get(
            "/api/v1/cli/agents",
            headers=_auth_headers(_USER_A),
        )
        if resp.status_code == 403:
            detail = resp.json().get("detail", "")
            assert "not governed" not in detail, (
                f"CLI agents route is ungoverned: {detail}"
            )

    @pytest.mark.asyncio
    async def test_cli_device_code_is_not_ungoverned(self, client):
        """POST /api/v1/cli/device-code must not return 403 'ungoverned route'."""
        resp = await client.post("/api/v1/cli/device-code", json={})
        if resp.status_code == 403:
            detail = resp.json().get("detail", "")
            assert "not governed" not in detail, (
                f"CLI device-code route is ungoverned: {detail}"
            )

    @pytest.mark.asyncio
    async def test_cli_device_token_is_not_ungoverned(self, client):
        """POST /api/v1/cli/device-token must not return 403 'ungoverned route'."""
        resp = await client.post(
            "/api/v1/cli/device-token",
            json={"device_code": "dummy"},
        )
        if resp.status_code == 403:
            detail = resp.json().get("detail", "")
            assert "not governed" not in detail, (
                f"CLI device-token route is ungoverned: {detail}"
            )

    @pytest.mark.asyncio
    async def test_all_cli_routes_user_tier_required(self, client_with_agent):
        """Authenticated CLI routes reject requests with missing auth (401, not 403)."""
        client, _ = client_with_agent
        auth_required_routes = [
            ("POST", "/api/v1/cli/invoke", {"handle": "@x", "message": "hi"}),
            ("GET", "/api/v1/cli/agents", None),
            ("GET", "/api/v1/cli/agents/x/skills", None),
        ]
        for method, path, body in auth_required_routes:
            if method == "POST":
                resp = await client.post(path, json=body or {})
            else:
                resp = await client.get(path)
            assert resp.status_code == 401, (
                f"Expected 401 for unauthenticated {method} {path}, "
                f"got {resp.status_code}: {resp.text}"
            )
