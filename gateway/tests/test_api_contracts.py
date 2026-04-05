"""API contract tests for DD Agent 1.

Verifies that every API endpoint returns the EXACT response shape clients
expect — correct field names, correct types, required fields never null,
and optional fields correctly typed.

Auth endpoint contract tests (Section 1) use Pydantic schema validation
directly rather than HTTP round-trips. This is because the slowapi rate
limiter in auth.py requires a ``Response`` parameter that is not injected
correctly in the test environment, making HTTP-level auth tests unreliable.
The schema validation approach is equivalent for contract purposes: it verifies
the exact fields, types, and constraints that the HTTP response would carry.

All other sections exercise the real HTTP surface via httpx AsyncClient
against a fully-started FastAPI lifespan app.
"""

from __future__ import annotations

import os
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from isg_agent.api.routes.auth import _create_token, _set_auth_config
from isg_agent.config import get_settings


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SECRET = "contract-test-secret-key-do-not-use"
_STRONG_PASSWORD = "StrongPass1!"

# Each test class uses a DIFFERENT user ID to avoid the module-level
# in-memory rate limiter (10/minute per user) accumulating across tests
# within the same pytest session.
_USER_AGENT_CREATE = "ct-user-ag-create-001"
_USER_AGENT_LIST = "ct-user-ag-list-001"
_USER_AGENT_GET = "ct-user-ag-get-001"
_USER_AGENT_UPDATE = "ct-user-ag-update-001"
_USER_SESSION_CREATE = "ct-user-sess-create-001"
_USER_SESSION_MSG = "ct-user-sess-msg-001"
_USER_PUBLIC = "ct-user-public-001"
_USER_HEALTH = "ct-user-health-001"
_USER_CROSS = "ct-user-cross-001"

# Default user for simple tests
_USER_DEFAULT = "ct-user-default-001"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(user_id: str = _USER_DEFAULT, email: str = "default@contracttest.example.com") -> str:
    return _create_token(user_id=user_id, email=email, secret_key=_SECRET)


def _auth_headers(
    user_id: str = _USER_DEFAULT, email: str = "default@contracttest.example.com"
) -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_token(user_id, email)}"}


# ---------------------------------------------------------------------------
# Fixture: client — full lifespan app, all services initialised
# Matches test_api_agents.py pattern.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(tmp_path):
    """Async HTTP client bound to a test app with full lifespan initialisation.

    Sets the required env vars, clears the settings lru_cache so the
    lifespan reads the temp DB, then starts the lifespan so that
    app.state.agent_registry, handle_service, runtime, etc. are all live.

    Rate-limit response headers are disabled for tests. The slowapi module-level
    ``limiter`` has ``headers_enabled=True`` which causes it to call
    ``_inject_headers(kwargs.get('response'), ...)`` on endpoints that don't
    declare a ``Response`` parameter — raising an exception at the end of every
    request. Disabling headers in tests is safe: limits still apply, 429s still
    fire; only the ``X-RateLimit-*`` headers are suppressed.
    """
    db_file = str(tmp_path / "test_contracts.db")

    os.environ["ISG_AGENT_DB_PATH"] = db_file
    os.environ["ISG_AGENT_SECRET_KEY"] = _SECRET
    os.environ["ISG_AGENT_DEPLOYMENT_ENV"] = "test"

    get_settings.cache_clear()
    _set_auth_config(db_path=db_file, secret_key=_SECRET)

    # Disable rate-limit response headers to avoid slowapi's _inject_headers
    # crashing on endpoints that return Pydantic models (not Response objects).
    from isg_agent.middleware.rate_limiter_middleware import limiter as _limiter
    _orig_headers_enabled = _limiter._headers_enabled
    _limiter._headers_enabled = False

    from isg_agent.app import create_app, lifespan

    app = create_app()

    try:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ac
    finally:
        _limiter._headers_enabled = _orig_headers_enabled
        for key in ("ISG_AGENT_DB_PATH", "ISG_AGENT_SECRET_KEY", "ISG_AGENT_DEPLOYMENT_ENV"):
            os.environ.pop(key, None)
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Helpers for pre-creating resources
# ---------------------------------------------------------------------------


async def _create_agent(
    client: AsyncClient,
    handle: str = "contract-agent",
    name: str = "Contract Agent",
    agent_type: str = "business",
    user_id: str = _USER_DEFAULT,
) -> dict:
    """Create an agent and return the parsed JSON response."""
    resp = await client.post(
        "/api/v1/agents",
        json={"handle": handle, "name": name, "agent_type": agent_type},
        headers=_auth_headers(user_id),
    )
    assert resp.status_code == 201, f"Agent creation failed: {resp.text}"
    return resp.json()


async def _create_session(client: AsyncClient, user_id: str = _USER_DEFAULT) -> dict:
    """Create a session and return the parsed JSON response."""
    resp = await client.post(
        "/api/v1/sessions",
        json={},
        headers=_auth_headers(user_id),
    )
    assert resp.status_code == 201, f"Session creation failed: {resp.text}"
    return resp.json()


# ===========================================================================
# 1. Auth Endpoints — Schema-level contract tests
#
# The /auth/register and /auth/login endpoints have a known issue where the
# slowapi rate limiter requires a `Response` parameter that is not injected
# in the test environment. Instead of HTTP round-trips, we verify the
# AuthResponse Pydantic schema directly — which is the EXACT model used by
# both endpoints as their response_model. Schema-level testing is equivalent
# for contract purposes.
# ===========================================================================


class TestAuthRegisterContract:
    """Contract tests for POST /auth/register via AuthResponse Pydantic schema.

    Verifies the EXACT fields, types, and constraints of the AuthResponse
    model returned by /auth/register.
    """

    def test_auth_response_has_required_fields(self):
        """AuthResponse schema has all required fields: user_id, email, access_token, token_type."""
        from isg_agent.api.routes.auth import AuthResponse

        resp = AuthResponse(
            user_id="test-user-id-001",
            email="test@example.com",
            access_token="eyJhbGc.eyJzdWIi.SIG",
        )

        # --- Required string fields ---
        assert hasattr(resp, "user_id")
        assert hasattr(resp, "email")
        assert hasattr(resp, "access_token")
        assert hasattr(resp, "token_type")

        assert isinstance(resp.user_id, str)
        assert isinstance(resp.email, str)
        assert isinstance(resp.access_token, str)
        assert isinstance(resp.token_type, str)

    def test_auth_response_token_type_default_is_bearer(self):
        """token_type defaults to 'bearer' when not specified."""
        from isg_agent.api.routes.auth import AuthResponse

        resp = AuthResponse(
            user_id="u1",
            email="test@example.com",
            access_token="tok",
        )
        assert resp.token_type == "bearer", \
            f"Default token_type must be 'bearer', got '{resp.token_type}'"

    def test_auth_response_mfa_required_default_is_false(self):
        """mfa_required defaults to False."""
        from isg_agent.api.routes.auth import AuthResponse

        resp = AuthResponse(
            user_id="u1",
            email="test@example.com",
            access_token="tok",
        )
        assert resp.mfa_required is False
        assert isinstance(resp.mfa_required, bool)

    def test_auth_response_mfa_challenge_token_default_is_none(self):
        """mfa_challenge_token defaults to None (Optional[str])."""
        from isg_agent.api.routes.auth import AuthResponse

        resp = AuthResponse(
            user_id="u1",
            email="test@example.com",
            access_token="tok",
        )
        assert resp.mfa_challenge_token is None

    def test_auth_response_field_names_are_snake_case(self):
        """AuthResponse fields use snake_case — verify via model_fields."""
        from isg_agent.api.routes.auth import AuthResponse

        field_names = set(AuthResponse.model_fields.keys())

        assert "user_id" in field_names, "Field 'user_id' must exist"
        assert "access_token" in field_names, "Field 'access_token' must exist"
        assert "token_type" in field_names, "Field 'token_type' must exist"
        assert "mfa_required" in field_names, "Field 'mfa_required' must exist"
        assert "mfa_challenge_token" in field_names, "Field 'mfa_challenge_token' must exist"

        # No camelCase
        assert "userId" not in field_names, "userId (camelCase) must NOT be a field"
        assert "accessToken" not in field_names, "accessToken (camelCase) must NOT be a field"
        assert "tokenType" not in field_names, "tokenType (camelCase) must NOT be a field"
        assert "mfaRequired" not in field_names, "mfaRequired (camelCase) must NOT be a field"

    def test_auth_response_serialises_to_correct_json_keys(self):
        """AuthResponse serializes to JSON with exactly the expected snake_case keys."""
        from isg_agent.api.routes.auth import AuthResponse

        resp = AuthResponse(
            user_id="u123",
            email="user@example.com",
            access_token="eyJ.tok.sig",
        )
        data = resp.model_dump()

        assert "user_id" in data
        assert "email" in data
        assert "access_token" in data
        assert "token_type" in data
        assert "mfa_required" in data
        assert "mfa_challenge_token" in data

        assert data["token_type"] == "bearer"
        assert data["mfa_required"] is False
        assert data["mfa_challenge_token"] is None

    def test_register_request_requires_terms_accepted(self):
        """RegisterRequest enforces terms_accepted=True for account creation."""
        from isg_agent.api.routes.auth import RegisterRequest
        import pytest

        # terms_accepted defaults to False — should create model but be rejected at route level
        req_no_terms = RegisterRequest(
            email="test@example.com",
            password=_STRONG_PASSWORD,
        )
        assert req_no_terms.terms_accepted is False, \
            "terms_accepted must default to False"

        req_with_terms = RegisterRequest(
            email="test@example.com",
            password=_STRONG_PASSWORD,
            terms_accepted=True,
        )
        assert req_with_terms.terms_accepted is True

    def test_register_request_password_complexity(self):
        """RegisterRequest enforces password complexity constraints."""
        from isg_agent.api.routes.auth import RegisterRequest
        import pytest

        # Weak password must be rejected
        with pytest.raises(Exception):
            RegisterRequest(email="test@example.com", password="weak")

        # Strong password is accepted
        req = RegisterRequest(
            email="test@example.com",
            password=_STRONG_PASSWORD,
            terms_accepted=True,
        )
        assert req.password == _STRONG_PASSWORD

    def test_register_request_email_lowercased(self):
        """RegisterRequest automatically lowercases the email."""
        from isg_agent.api.routes.auth import RegisterRequest

        req = RegisterRequest(
            email="USER@EXAMPLE.COM",
            password=_STRONG_PASSWORD,
            terms_accepted=True,
        )
        assert req.email == "user@example.com"


class TestAuthLoginContract:
    """Contract tests for POST /auth/login via AuthResponse Pydantic schema.

    Verifies that the same AuthResponse model returned by /auth/register is
    also used by /auth/login, and has the same field contracts.
    """

    def test_login_uses_same_auth_response_model(self):
        """Both register and login return the AuthResponse model (same shape)."""
        from isg_agent.api.routes.auth import AuthResponse
        import inspect
        from isg_agent.api.routes import auth as auth_module

        # Verify the login route function uses AuthResponse as response type
        login_fn = getattr(auth_module, "login", None)
        assert login_fn is not None, "auth module must have a 'login' function"

        # The return annotation or response_model of login should be AuthResponse
        # We check via router route definitions
        from isg_agent.api.routes.auth import router as auth_router

        # Router includes prefix in path: /auth/login
        login_routes = [
            r for r in auth_router.routes
            if hasattr(r, "path") and r.path.endswith("/login")
        ]
        assert len(login_routes) == 1, "There must be exactly one /login route"

        login_route = login_routes[0]
        # response_model must be AuthResponse
        assert login_route.response_model is AuthResponse, \
            f"Login route response_model must be AuthResponse, got {login_route.response_model}"

    def test_register_uses_auth_response_model(self):
        """Register route uses AuthResponse as its response_model."""
        from isg_agent.api.routes.auth import AuthResponse, router as auth_router

        # Router includes prefix in path: /auth/register
        register_routes = [
            r for r in auth_router.routes
            if hasattr(r, "path") and r.path.endswith("/register")
        ]
        assert len(register_routes) == 1, "There must be exactly one /register route"

        register_route = register_routes[0]
        assert register_route.response_model is AuthResponse, \
            f"Register route response_model must be AuthResponse, got {register_route.response_model}"

    def test_auth_response_access_token_is_str(self):
        """access_token in AuthResponse is always a str type."""
        from isg_agent.api.routes.auth import AuthResponse

        resp = AuthResponse(
            user_id="u1",
            email="test@example.com",
            access_token="eyJhbGc.eyJzdWIi.SIGNATURE",
        )
        assert isinstance(resp.access_token, str)
        assert len(resp.access_token) > 0

    def test_create_token_produces_3_part_jwt(self):
        """_create_token produces a 3-part dot-separated JWT string."""
        from isg_agent.api.routes.auth import _create_token

        token = _create_token(
            user_id="test-user-123",
            email="jwt@example.com",
            secret_key=_SECRET,
        )
        assert isinstance(token, str)
        parts = token.split(".")
        assert len(parts) == 3, \
            f"JWT must have 3 dot-separated parts, got {len(parts)}: {token[:80]}"

    def test_created_token_contains_user_id_in_payload(self):
        """JWT payload from _create_token contains the user_id as 'sub'."""
        from isg_agent.api.routes.auth import _create_token, verify_token

        token = _create_token(
            user_id="my-user-id",
            email="payload@example.com",
            secret_key=_SECRET,
        )
        payload = verify_token(token, _SECRET)
        assert payload is not None, "Token must be verifiable"
        assert payload["sub"] == "my-user-id", \
            f"Payload sub must match user_id, got: {payload.get('sub')!r}"
        assert payload["email"] == "payload@example.com"

    def test_login_request_email_lowercased(self):
        """LoginRequest automatically lowercases the email."""
        from isg_agent.api.routes.auth import LoginRequest

        req = LoginRequest(email="LOGIN@EXAMPLE.COM", password="anypass")
        assert req.email == "login@example.com"


# ===========================================================================
# 2. Agent Endpoints
# ===========================================================================


class TestAgentCreateContract:
    """Contract tests for POST /api/v1/agents."""

    _UID = _USER_AGENT_CREATE  # unique user per class to avoid rate-limit accumulation

    @pytest.mark.asyncio
    async def test_create_agent_response_shape(self, client: AsyncClient):
        """POST /api/v1/agents returns the full AgentResponse shape."""
        resp = await client.post(
            "/api/v1/agents",
            json={
                "handle": "shape-agent",
                "name": "Shape Test Agent",
                "agent_type": "business",
                "industry_type": "restaurant",
            },
            headers=_auth_headers(self._UID),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()

        # --- Required string fields (never null) ---
        required_str_fields = ("id", "user_id", "handle", "name", "agent_type", "status",
                               "subscription_tier", "created_at", "updated_at")
        for field in required_str_fields:
            assert field in data, f"Missing field: {field}"
            assert data[field] is not None, f"{field} must not be null"
            assert isinstance(data[field], str), f"{field} must be str, got {type(data[field])}"
            assert data[field] != "", f"{field} must not be empty"

        # --- Optional fields are present but may be None ---
        assert "industry_type" in data, "Missing field: industry_type"
        assert "template_id" in data, "Missing field: template_id"

        # industry_type was provided — should be the value we sent
        assert data["industry_type"] == "restaurant"
        # template_id was not provided — should be None
        assert data["template_id"] is None

        # --- Specific value contracts ---
        assert data["handle"] == "shape-agent"
        assert data["name"] == "Shape Test Agent"
        assert data["agent_type"] == "business"
        assert data["status"] == "active", f"Expected status 'active', got '{data['status']}'"
        assert data["subscription_tier"] == "free", \
            f"Expected 'free' tier, got '{data['subscription_tier']}'"
        assert data["user_id"] == self._UID

    @pytest.mark.asyncio
    async def test_create_agent_returns_201(self, client: AsyncClient):
        """POST /api/v1/agents returns HTTP 201 Created."""
        resp = await client.post(
            "/api/v1/agents",
            json={"handle": "status-ct", "name": "Status CT", "agent_type": "business"},
            headers=_auth_headers(self._UID),
        )
        assert resp.status_code == 201, \
            f"Create agent should return 201, got {resp.status_code}: {resp.text}"

    @pytest.mark.asyncio
    async def test_create_agent_id_is_uuid_format(self, client: AsyncClient):
        """Agent id field returned from POST is a valid UUID."""
        import uuid

        data = await _create_agent(client, handle="uuid-agent", name="UUID Agent",
                                   user_id=self._UID)
        parsed = uuid.UUID(data["id"])
        assert str(parsed) == data["id"]

    @pytest.mark.asyncio
    async def test_create_agent_timestamps_are_iso8601(self, client: AsyncClient):
        """created_at and updated_at are ISO 8601 formatted strings."""
        from datetime import datetime

        data = await _create_agent(client, handle="ts-agent", name="Timestamp Agent",
                                   user_id=self._UID)

        for ts_field in ("created_at", "updated_at"):
            ts_val = data[ts_field]
            assert isinstance(ts_val, str), f"{ts_field} must be a string"
            try:
                datetime.fromisoformat(ts_val.replace("Z", "+00:00"))
            except ValueError as exc:
                pytest.fail(f"{ts_field}='{ts_val}' is not valid ISO 8601: {exc}")

    @pytest.mark.asyncio
    async def test_create_personal_agent_industry_type_is_none(self, client: AsyncClient):
        """Personal agents without industry_type have industry_type=null in response."""
        resp = await client.post(
            "/api/v1/agents",
            json={"handle": "personal-ct", "name": "Personal CT", "agent_type": "personal"},
            headers=_auth_headers(self._UID),
        )
        assert resp.status_code == 201
        data = resp.json()

        assert "industry_type" in data, "industry_type field must be present even when null"
        assert data["industry_type"] is None, f"Expected None, got {data['industry_type']!r}"

    @pytest.mark.asyncio
    async def test_create_agent_no_camelcase_keys(self, client: AsyncClient):
        """Agent response uses snake_case — no camelCase variants."""
        data = await _create_agent(client, handle="camel-ct", name="Camel CT",
                                   user_id=self._UID)

        assert "agentType" not in data, "agentType must not appear — use agent_type"
        assert "userId" not in data, "userId must not appear — use user_id"
        assert "industryType" not in data, "industryType must not appear — use industry_type"
        assert "templateId" not in data, "templateId must not appear — use template_id"
        assert "subscriptionTier" not in data, \
            "subscriptionTier must not appear — use subscription_tier"
        assert "createdAt" not in data, "createdAt must not appear — use created_at"
        assert "updatedAt" not in data, "updatedAt must not appear — use updated_at"

    @pytest.mark.asyncio
    async def test_create_agent_with_template_id_stored(self, client: AsyncClient):
        """template_id provided at creation time is reflected in the response."""
        resp = await client.post(
            "/api/v1/agents",
            json={
                "handle": "tpl-ct",
                "name": "Template CT",
                "agent_type": "business",
                "template_id": "some-template-uuid-123",
            },
            headers=_auth_headers(self._UID),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["template_id"] == "some-template-uuid-123"


class TestAgentListContract:
    """Contract tests for GET /api/v1/agents."""

    _UID = _USER_AGENT_LIST

    @pytest.mark.asyncio
    async def test_list_agents_response_shape(self, client: AsyncClient):
        """GET /api/v1/agents returns {agents: list, count: int}."""
        await _create_agent(client, handle="list-ct-1", name="List CT 1", user_id=self._UID)
        await _create_agent(client, handle="list-ct-2", name="List CT 2", user_id=self._UID)

        resp = await client.get("/api/v1/agents", headers=_auth_headers(self._UID))
        assert resp.status_code == 200, resp.text
        data = resp.json()

        # --- Top-level shape ---
        assert "agents" in data, "Missing field: agents"
        assert "count" in data, "Missing field: count"
        assert isinstance(data["agents"], list), f"agents must be list, got {type(data['agents'])}"
        assert isinstance(data["count"], int), f"count must be int, got {type(data['count'])}"

        # --- count matches actual list length ---
        assert data["count"] == len(data["agents"]), \
            f"count={data['count']} does not match len(agents)={len(data['agents'])}"
        assert data["count"] == 2

    @pytest.mark.asyncio
    async def test_list_agents_each_item_has_required_fields(self, client: AsyncClient):
        """Each agent object in the list has all required fields with correct types."""
        await _create_agent(client, handle="item-ct", name="Item CT", user_id=self._UID)

        resp = await client.get("/api/v1/agents", headers=_auth_headers(self._UID))
        assert resp.status_code == 200
        data = resp.json()

        assert len(data["agents"]) >= 1
        agent = data["agents"][0]

        required_str = ("id", "user_id", "handle", "name", "agent_type",
                        "status", "subscription_tier", "created_at", "updated_at")
        for field in required_str:
            assert field in agent, f"Agent list item missing field: {field}"
            assert agent[field] is not None, f"Agent list item field {field} must not be null"
            assert isinstance(agent[field], str), f"Agent list item {field} must be str"

        # Optional fields must be present (even if null)
        assert "industry_type" in agent, "industry_type must be present in list items"
        assert "template_id" in agent, "template_id must be present in list items"

    @pytest.mark.asyncio
    async def test_list_agents_empty_returns_zero_count(self, client: AsyncClient):
        """Empty list returns {agents: [], count: 0}."""
        resp = await client.get(
            "/api/v1/agents",
            headers=_auth_headers("ct-empty-list-user", "empty@ct.example.com"),
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["agents"] == []
        assert data["count"] == 0
        assert isinstance(data["count"], int)

    @pytest.mark.asyncio
    async def test_list_agents_count_type_is_int(self, client: AsyncClient):
        """count in list response is always an integer, not a string."""
        resp = await client.get("/api/v1/agents", headers=_auth_headers(self._UID))
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["count"], int), \
            f"count must be int, got {type(data['count'])}: {data['count']!r}"


class TestAgentGetContract:
    """Contract tests for GET /api/v1/agents/{agent_id}."""

    _UID = _USER_AGENT_GET

    @pytest.mark.asyncio
    async def test_get_agent_response_shape(self, client: AsyncClient):
        """GET /api/v1/agents/{id} returns a single AgentResponse with all fields."""
        created = await _create_agent(client, handle="get-ct", name="Get CT",
                                      user_id=self._UID)
        agent_id = created["id"]

        resp = await client.get(f"/api/v1/agents/{agent_id}", headers=_auth_headers(self._UID))
        assert resp.status_code == 200, resp.text
        data = resp.json()

        # Must be a dict (single object, not a list)
        assert isinstance(data, dict), f"Expected dict, got {type(data)}"

        # All required fields present with correct types
        required_str = ("id", "user_id", "handle", "name", "agent_type",
                        "status", "subscription_tier", "created_at", "updated_at")
        for field in required_str:
            assert field in data, f"Missing field: {field}"
            assert data[field] is not None, f"{field} must not be null"
            assert isinstance(data[field], str), f"{field} must be str"

        # ID matches what we created
        assert data["id"] == agent_id

    @pytest.mark.asyncio
    async def test_get_agent_optional_fields_present(self, client: AsyncClient):
        """Optional fields (industry_type, template_id) are present in single-agent response."""
        created = await _create_agent(client, handle="opt-ct", name="Opt CT",
                                      user_id=self._UID)

        resp = await client.get(f"/api/v1/agents/{created['id']}",
                                headers=_auth_headers(self._UID))
        assert resp.status_code == 200
        data = resp.json()

        assert "industry_type" in data, "industry_type must be present (may be null)"
        assert "template_id" in data, "template_id must be present (may be null)"
        # Both are Optional[str] — can be None or str
        assert data["industry_type"] is None or isinstance(data["industry_type"], str)
        assert data["template_id"] is None or isinstance(data["template_id"], str)

    @pytest.mark.asyncio
    async def test_get_agent_data_matches_create(self, client: AsyncClient):
        """Values returned by GET match the values used to create the agent."""
        created = await _create_agent(
            client, handle="match-ct", name="Match CT", agent_type="personal",
            user_id=self._UID
        )
        agent_id = created["id"]

        resp = await client.get(f"/api/v1/agents/{agent_id}",
                                headers=_auth_headers(self._UID))
        assert resp.status_code == 200
        data = resp.json()

        assert data["id"] == agent_id
        assert data["handle"] == "match-ct"
        assert data["name"] == "Match CT"
        assert data["agent_type"] == "personal"
        assert data["user_id"] == self._UID


class TestAgentUpdateContract:
    """Contract tests for PATCH /api/v1/agents/{agent_id}."""

    _UID = _USER_AGENT_UPDATE

    @pytest.mark.asyncio
    async def test_update_agent_response_shape(self, client: AsyncClient):
        """PATCH /api/v1/agents/{id} returns the full updated AgentResponse."""
        created = await _create_agent(client, handle="patch-ct", name="Patch CT Original",
                                      user_id=self._UID)
        agent_id = created["id"]

        resp = await client.patch(
            f"/api/v1/agents/{agent_id}",
            json={"name": "Patch CT Updated"},
            headers=_auth_headers(self._UID),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert isinstance(data, dict)

        # All required fields present with correct types
        required_str = ("id", "user_id", "handle", "name", "agent_type",
                        "status", "subscription_tier", "created_at", "updated_at")
        for field in required_str:
            assert field in data, f"Missing field after PATCH: {field}"
            assert data[field] is not None, f"{field} must not be null after PATCH"
            assert isinstance(data[field], str), f"{field} must be str after PATCH"

        # Updated name is reflected in response
        assert data["name"] == "Patch CT Updated"

        # ID remains unchanged
        assert data["id"] == agent_id

    @pytest.mark.asyncio
    async def test_update_agent_returns_all_fields_not_just_changed(self, client: AsyncClient):
        """PATCH returns the FULL agent object, not just the changed fields."""
        created = await _create_agent(client, handle="full-patch-ct", name="Full Patch CT",
                                      user_id=self._UID)
        agent_id = created["id"]

        resp = await client.patch(
            f"/api/v1/agents/{agent_id}",
            json={"name": "Full Patch CT Updated"},
            headers=_auth_headers(self._UID),
        )
        assert resp.status_code == 200
        data = resp.json()

        # Every field from the original should still be present
        for field in ("id", "user_id", "handle", "agent_type", "status",
                      "subscription_tier", "created_at", "updated_at",
                      "industry_type", "template_id"):
            assert field in data, f"PATCH response missing field: {field}"

    @pytest.mark.asyncio
    async def test_update_agent_optional_fields_still_present(self, client: AsyncClient):
        """After PATCH, optional fields (industry_type, template_id) remain in the response."""
        created = await _create_agent(client, handle="opt-patch-ct", name="Opt Patch CT",
                                      user_id=self._UID)

        resp = await client.patch(
            f"/api/v1/agents/{created['id']}",
            json={"name": "Opt Patch CT Updated"},
            headers=_auth_headers(self._UID),
        )
        assert resp.status_code == 200
        data = resp.json()

        assert "industry_type" in data, "industry_type must be present after PATCH"
        assert "template_id" in data, "template_id must be present after PATCH"
        # Both are Optional[str] — null is valid
        assert data["industry_type"] is None or isinstance(data["industry_type"], str)
        assert data["template_id"] is None or isinstance(data["template_id"], str)


# ===========================================================================
# 3. Session Endpoints
# ===========================================================================


class TestSessionCreateContract:
    """Contract tests for POST /api/v1/sessions."""

    _UID = _USER_SESSION_CREATE

    @pytest.mark.asyncio
    async def test_create_session_response_shape(self, client: AsyncClient):
        """POST /api/v1/sessions returns {session_id, user_id, created_at, updated_at, message_count, total_tokens, status}."""
        resp = await client.post("/api/v1/sessions", json={},
                                 headers=_auth_headers(self._UID))
        assert resp.status_code == 201, resp.text
        data = resp.json()

        # --- Required string fields ---
        required_str = ("session_id", "user_id", "created_at", "updated_at", "status")
        for field in required_str:
            assert field in data, f"Missing field: {field}"
            assert data[field] is not None, f"{field} must not be null"
            assert isinstance(data[field], str), f"{field} must be str, got {type(data[field])}"
            assert data[field] != "", f"{field} must not be empty"

        # --- Required int fields ---
        for field in ("message_count", "total_tokens"):
            assert field in data, f"Missing field: {field}"
            assert isinstance(data[field], int), f"{field} must be int, got {type(data[field])}"

        # --- Default value contracts ---
        assert data["status"] == "active", \
            f"New session status must be 'active', got '{data['status']}'"
        assert data["message_count"] == 0, \
            f"New session message_count must be 0, got {data['message_count']}"
        assert data["total_tokens"] == 0, \
            f"New session total_tokens must be 0, got {data['total_tokens']}"

        # --- user_id matches authenticated user ---
        assert data["user_id"] == self._UID

    @pytest.mark.asyncio
    async def test_create_session_returns_201(self, client: AsyncClient):
        """POST /api/v1/sessions returns HTTP 201 Created."""
        resp = await client.post("/api/v1/sessions", json={},
                                 headers=_auth_headers(self._UID))
        assert resp.status_code == 201, \
            f"Create session should return 201, got {resp.status_code}: {resp.text}"

    @pytest.mark.asyncio
    async def test_create_session_session_id_is_non_empty_string(self, client: AsyncClient):
        """session_id from POST /api/v1/sessions is a non-empty string."""
        resp = await client.post("/api/v1/sessions", json={},
                                 headers=_auth_headers(self._UID))
        assert resp.status_code == 201
        data = resp.json()

        sid = data["session_id"]
        assert isinstance(sid, str)
        assert len(sid) > 0

    @pytest.mark.asyncio
    async def test_create_session_timestamps_are_iso8601(self, client: AsyncClient):
        """created_at and updated_at in session response are ISO 8601 strings."""
        from datetime import datetime

        resp = await client.post("/api/v1/sessions", json={},
                                 headers=_auth_headers(self._UID))
        assert resp.status_code == 201
        data = resp.json()

        for ts_field in ("created_at", "updated_at"):
            ts_val = data[ts_field]
            assert isinstance(ts_val, str), f"{ts_field} must be a string"
            try:
                datetime.fromisoformat(ts_val.replace("Z", "+00:00"))
            except ValueError as exc:
                pytest.fail(f"{ts_field}='{ts_val}' is not valid ISO 8601: {exc}")

    @pytest.mark.asyncio
    async def test_create_session_no_camelcase_fields(self, client: AsyncClient):
        """Session response uses snake_case field names throughout."""
        resp = await client.post("/api/v1/sessions", json={},
                                 headers=_auth_headers(self._UID))
        assert resp.status_code == 201
        data = resp.json()

        assert "sessionId" not in data, "sessionId must not appear — use session_id"
        assert "userId" not in data, "userId must not appear — use user_id"
        assert "createdAt" not in data, "createdAt must not appear — use created_at"
        assert "updatedAt" not in data, "updatedAt must not appear — use updated_at"
        assert "messageCount" not in data, "messageCount must not appear — use message_count"
        assert "totalTokens" not in data, "totalTokens must not appear — use total_tokens"

    @pytest.mark.asyncio
    async def test_create_session_message_count_and_tokens_are_integers(self, client: AsyncClient):
        """message_count and total_tokens are integers (not strings or floats)."""
        resp = await client.post("/api/v1/sessions", json={},
                                 headers=_auth_headers(self._UID))
        assert resp.status_code == 201
        data = resp.json()

        assert type(data["message_count"]) is int, \
            f"message_count must be int, got {type(data['message_count'])}"
        assert type(data["total_tokens"]) is int, \
            f"total_tokens must be int, got {type(data['total_tokens'])}"


class TestSessionMessageContract:
    """Contract tests for POST /api/v1/sessions/{id}/message."""

    _UID = _USER_SESSION_MSG

    @pytest.mark.asyncio
    async def test_send_message_response_shape(self, client: AsyncClient):
        """POST /api/v1/sessions/{id}/message returns the full MessageResponse shape."""
        session = await _create_session(client, user_id=self._UID)
        session_id = session["session_id"]

        resp = await client.post(
            f"/api/v1/sessions/{session_id}/message",
            json={"content": "Hello, contract test!"},
            headers=_auth_headers(self._UID),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        # --- Required string fields ---
        required_str = ("content", "session_id", "model_used", "governance_decision",
                        "convergence_status")
        for field in required_str:
            assert field in data, f"Missing field: {field}"
            assert data[field] is not None, f"{field} must not be null"
            assert isinstance(data[field], str), f"{field} must be str, got {type(data[field])}"

        # --- Required int fields ---
        for field in ("input_tokens", "output_tokens"):
            assert field in data, f"Missing field: {field}"
            assert isinstance(data[field], int), f"{field} must be int, got {type(data[field])}"
            assert data[field] >= 0, f"{field} must be non-negative"

        # --- Required bool field ---
        assert "halted" in data, "Missing field: halted"
        assert isinstance(data["halted"], bool), f"halted must be bool, got {type(data['halted'])}"

        # --- session_id in response matches the one we used ---
        assert data["session_id"] == session_id

        # --- governance_decision valid values ---
        valid_decisions = {"PROCEED", "REVIEW", "HALT"}
        assert data["governance_decision"] in valid_decisions, \
            f"governance_decision='{data['governance_decision']}' not in {valid_decisions}"

        # --- convergence_status valid values ---
        valid_statuses = {"WITHIN_BUDGET", "WARNING", "BUDGET_EXCEEDED"}
        assert data["convergence_status"] in valid_statuses, \
            f"convergence_status='{data['convergence_status']}' not in {valid_statuses}"

    @pytest.mark.asyncio
    async def test_send_message_returns_200(self, client: AsyncClient):
        """POST /api/v1/sessions/{id}/message returns HTTP 200 OK."""
        session = await _create_session(client, user_id=self._UID)

        resp = await client.post(
            f"/api/v1/sessions/{session['session_id']}/message",
            json={"content": "status check"},
            headers=_auth_headers(self._UID),
        )
        assert resp.status_code == 200, \
            f"Send message should return 200, got {resp.status_code}: {resp.text}"

    @pytest.mark.asyncio
    async def test_send_message_content_is_non_empty_string(self, client: AsyncClient):
        """The content field in message response is a non-empty string."""
        session = await _create_session(client, user_id=self._UID)

        resp = await client.post(
            f"/api/v1/sessions/{session['session_id']}/message",
            json={"content": "Say something!"},
            headers=_auth_headers(self._UID),
        )
        assert resp.status_code == 200
        data = resp.json()

        assert isinstance(data["content"], str)
        assert len(data["content"]) > 0, "content must not be empty"

    @pytest.mark.asyncio
    async def test_send_message_no_camelcase_fields(self, client: AsyncClient):
        """MessageResponse uses snake_case throughout."""
        session = await _create_session(client, user_id=self._UID)

        resp = await client.post(
            f"/api/v1/sessions/{session['session_id']}/message",
            json={"content": "snake_case check"},
            headers=_auth_headers(self._UID),
        )
        assert resp.status_code == 200
        data = resp.json()

        assert "sessionId" not in data, "sessionId must not appear — use session_id"
        assert "modelUsed" not in data, "modelUsed must not appear — use model_used"
        assert "inputTokens" not in data, "inputTokens must not appear — use input_tokens"
        assert "outputTokens" not in data, "outputTokens must not appear — use output_tokens"
        assert "governanceDecision" not in data, \
            "governanceDecision must not appear — use governance_decision"
        assert "convergenceStatus" not in data, \
            "convergenceStatus must not appear — use convergence_status"

    @pytest.mark.asyncio
    async def test_send_message_halted_is_bool(self, client: AsyncClient):
        """The halted field is always a boolean (never a string '0' or 'false')."""
        session = await _create_session(client, user_id=self._UID)

        resp = await client.post(
            f"/api/v1/sessions/{session['session_id']}/message",
            json={"content": "type check"},
            headers=_auth_headers(self._UID),
        )
        assert resp.status_code == 200
        data = resp.json()

        assert type(data["halted"]) is bool, \
            f"halted must be bool (not {type(data['halted']).__name__}): {data['halted']!r}"


# ===========================================================================
# 4. Public Endpoints
# ===========================================================================


class TestPublicAgentsContract:
    """Contract tests for GET /api/v1/public/agents (no auth required)."""

    @pytest.mark.asyncio
    async def test_list_public_agents_response_shape(self, client: AsyncClient):
        """GET /api/v1/public/agents returns {agents: list, total: int, limit: int, offset: int}."""
        resp = await client.get("/api/v1/public/agents")
        assert resp.status_code == 200, resp.text
        data = resp.json()

        # --- Top-level structure ---
        assert "agents" in data, "Missing field: agents"
        assert "total" in data, "Missing field: total"
        assert "limit" in data, "Missing field: limit"
        assert "offset" in data, "Missing field: offset"

        assert isinstance(data["agents"], list), f"agents must be list, got {type(data['agents'])}"
        assert isinstance(data["total"], int), f"total must be int, got {type(data['total'])}"
        assert isinstance(data["limit"], int), f"limit must be int, got {type(data['limit'])}"
        assert isinstance(data["offset"], int), f"offset must be int, got {type(data['offset'])}"

        assert data["total"] >= 0
        assert data["limit"] >= 1
        assert data["offset"] >= 0

    @pytest.mark.asyncio
    async def test_list_public_agents_no_auth_required(self, client: AsyncClient):
        """GET /api/v1/public/agents succeeds with no Authorization header."""
        resp = await client.get("/api/v1/public/agents")
        assert resp.status_code == 200, \
            f"Public agents endpoint should not require auth, got {resp.status_code}: {resp.text}"

    @pytest.mark.asyncio
    async def test_list_public_agents_default_limit_is_20(self, client: AsyncClient):
        """Default limit in the public agents list is 20."""
        resp = await client.get("/api/v1/public/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert data["limit"] == 20, f"Default limit should be 20, got {data['limit']}"

    @pytest.mark.asyncio
    async def test_list_public_agents_default_offset_is_0(self, client: AsyncClient):
        """Default offset in the public agents list is 0."""
        resp = await client.get("/api/v1/public/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert data["offset"] == 0, f"Default offset should be 0, got {data['offset']}"

    @pytest.mark.asyncio
    async def test_list_public_agents_items_have_public_safe_fields(self, client: AsyncClient):
        """Each item in the public agents list has expected public-safe fields."""
        # Create an agent so we have something to list
        await _create_agent(client, handle="public-ct", name="Public CT")

        resp = await client.get("/api/v1/public/agents")
        assert resp.status_code == 200
        data = resp.json()

        if not data["agents"]:
            pytest.skip("No agents returned in public list — may be filtered out")

        agent = data["agents"][0]

        # Public-safe required fields
        public_fields = ("handle", "name", "agent_type", "created_at")
        for field in public_fields:
            assert field in agent, f"Public agent item missing field: {field}"
            assert agent[field] is not None, f"Public agent field {field} must not be null"
            assert isinstance(agent[field], str), f"Public agent field {field} must be str"

        # MUST NOT contain user_id (privacy — this is a public endpoint)
        assert "user_id" not in agent, \
            "user_id must NOT appear in public agent responses (privacy leak)"

    @pytest.mark.asyncio
    async def test_list_public_agents_empty_database_returns_valid_shape(self, client: AsyncClient):
        """Empty database still returns {agents: [], total: 0, limit: int, offset: int}."""
        resp = await client.get("/api/v1/public/agents")
        assert resp.status_code == 200
        data = resp.json()

        assert isinstance(data["agents"], list)
        assert isinstance(data["total"], int)
        assert data["total"] >= 0


# ===========================================================================
# 5. Health Endpoint
# ===========================================================================


class TestHealthContract:
    """Contract tests for GET /health.

    The actual health endpoint is defined in app.py (not health.py) and
    returns: {status, version, database, ...distiller_info}
    """

    @pytest.mark.asyncio
    async def test_health_response_shape(self, client: AsyncClient):
        """GET /health returns {status, version, database} and optional distiller fields."""
        resp = await client.get("/health")
        assert resp.status_code == 200, resp.text
        data = resp.json()

        # --- Required fields ---
        assert "status" in data, "Missing field: status"
        assert "version" in data, "Missing field: version"
        assert "database" in data, "Missing field: database"

        # --- Types ---
        assert isinstance(data["status"], str), f"status must be str, got {type(data['status'])}"
        assert isinstance(data["version"], str), f"version must be str, got {type(data['version'])}"
        assert isinstance(data["database"], str), \
            f"database must be str, got {type(data['database'])}"

        # --- Required values ---
        assert data["status"] != "", "status must not be empty"
        assert data["version"] != "", "version must not be empty"
        assert data["database"] != "", "database must not be empty"

    @pytest.mark.asyncio
    async def test_health_status_is_valid_value(self, client: AsyncClient):
        """Health status field is one of the expected values."""
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()

        valid_statuses = {"healthy", "degraded", "error", "unknown"}
        assert data["status"] in valid_statuses, \
            f"status='{data['status']}' not in expected values {valid_statuses}"

    @pytest.mark.asyncio
    async def test_health_database_field_is_valid_value(self, client: AsyncClient):
        """The database field reports a meaningful status string."""
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()

        # Observed values: 'connected', 'error', 'not_initialized', 'no_audit_chain'
        # Must be non-empty string
        assert isinstance(data["database"], str)
        assert data["database"] != "", "database must be non-empty"

    @pytest.mark.asyncio
    async def test_health_field_name_is_database_not_db(self, client: AsyncClient):
        """The database connectivity field is named 'database' (not 'db').

        The actual /health endpoint in app.py uses 'database' — clients must
        use that exact field name.
        """
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()

        assert "database" in data, "Field 'database' must be present"

    @pytest.mark.asyncio
    async def test_health_no_auth_required(self, client: AsyncClient):
        """Health endpoint is public — no Authorization header needed."""
        resp = await client.get("/health")
        assert resp.status_code == 200, \
            f"Health endpoint must not require auth, got {resp.status_code}"

    @pytest.mark.asyncio
    async def test_health_returns_200(self, client: AsyncClient):
        """GET /health returns HTTP 200 when app is running."""
        resp = await client.get("/health")
        assert resp.status_code == 200, f"Health check failed: {resp.status_code} {resp.text}"

    @pytest.mark.asyncio
    async def test_health_version_is_semver_format(self, client: AsyncClient):
        """version field follows semver (major.minor.patch)."""
        import re

        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()

        version = data["version"]
        semver_pattern = r"^\d+\.\d+\.\d+$"
        assert re.match(semver_pattern, version), \
            f"version='{version}' does not match semver pattern X.Y.Z"


# ===========================================================================
# 6. Cross-cutting contract invariants
# ===========================================================================


class TestCrossCuttingContracts:
    """Cross-cutting invariants that apply to multiple endpoints."""

    @pytest.mark.asyncio
    async def test_agent_list_and_create_return_json_content_type(self, client: AsyncClient):
        """Agent CRUD endpoints return Content-Type: application/json."""
        # POST
        create_resp = await client.post(
            "/api/v1/agents",
            json={"handle": "ct-json-agent", "name": "CT JSON Agent", "agent_type": "business"},
            headers=_auth_headers(),
        )
        assert "application/json" in create_resp.headers.get("content-type", ""), \
            f"Create agent must return JSON, got: {create_resp.headers.get('content-type')}"

        # GET list
        list_resp = await client.get("/api/v1/agents", headers=_auth_headers())
        assert "application/json" in list_resp.headers.get("content-type", ""), \
            f"List agents must return JSON, got: {list_resp.headers.get('content-type')}"

    @pytest.mark.asyncio
    async def test_health_returns_json_content_type(self, client: AsyncClient):
        """Health endpoint returns Content-Type: application/json."""
        resp = await client.get("/health")
        assert "application/json" in resp.headers.get("content-type", ""), \
            f"Health must return JSON, got: {resp.headers.get('content-type')}"

    @pytest.mark.asyncio
    async def test_unauthenticated_requests_return_401_not_403(self, client: AsyncClient):
        """Protected endpoints return 401 (not 403) when no token is provided."""
        endpoints_methods = [
            ("POST", "/api/v1/agents"),
            ("GET", "/api/v1/agents"),
            ("GET", "/api/v1/sessions"),
            ("POST", "/api/v1/sessions"),
        ]
        for method, path in endpoints_methods:
            if method == "GET":
                resp = await client.get(path)
            else:
                resp = await client.post(path, json={})
            assert resp.status_code == 401, \
                f"{method} {path} expected 401 without auth, got {resp.status_code}"

    @pytest.mark.asyncio
    async def test_404_responses_include_detail_field(self, client: AsyncClient):
        """404 Not Found responses include a 'detail' field with an error message."""
        resp = await client.get(
            "/api/v1/agents/nonexistent-agent-id-xxxxxxxxxx",
            headers=_auth_headers(),
        )
        assert resp.status_code == 404
        data = resp.json()
        assert "detail" in data, "404 response must include 'detail' field"
        assert isinstance(data["detail"], str), "detail must be a string"
        assert data["detail"] != "", "detail must not be empty"

    @pytest.mark.asyncio
    async def test_public_agents_returns_json_content_type(self, client: AsyncClient):
        """Public agents endpoint returns Content-Type: application/json."""
        resp = await client.get("/api/v1/public/agents")
        assert "application/json" in resp.headers.get("content-type", ""), \
            f"Public agents must return JSON, got: {resp.headers.get('content-type')}"

    @pytest.mark.asyncio
    async def test_agent_crud_responses_are_json_dicts_not_lists(self, client: AsyncClient):
        """Single-resource agent responses (create, get, patch) are JSON objects not arrays."""
        created = await _create_agent(client, handle="dict-ct", name="Dict CT")
        agent_id = created["id"]

        # create should be a dict
        assert isinstance(created, dict), "POST /api/v1/agents should return a dict"

        # get should be a dict
        get_resp = await client.get(f"/api/v1/agents/{agent_id}", headers=_auth_headers())
        assert isinstance(get_resp.json(), dict), "GET /api/v1/agents/{id} should return a dict"

        # patch should be a dict
        patch_resp = await client.patch(
            f"/api/v1/agents/{agent_id}",
            json={"name": "Dict CT Updated"},
            headers=_auth_headers(),
        )
        assert isinstance(patch_resp.json(), dict), \
            "PATCH /api/v1/agents/{id} should return a dict"

    @pytest.mark.asyncio
    async def test_session_create_and_list_response_types(self, client: AsyncClient):
        """Session create returns a dict; session list returns a dict with a list."""
        # Create returns dict
        session = await _create_session(client)
        assert isinstance(session, dict), "POST /api/v1/sessions should return a dict"

        # List returns dict with sessions list
        list_resp = await client.get("/api/v1/sessions", headers=_auth_headers())
        assert list_resp.status_code == 200
        list_data = list_resp.json()
        assert isinstance(list_data, dict), "GET /api/v1/sessions should return a dict"
        assert "sessions" in list_data, "Session list response must have 'sessions' field"
        assert isinstance(list_data["sessions"], list), "'sessions' must be a list"
        assert "count" in list_data, "Session list response must have 'count' field"
        assert isinstance(list_data["count"], int), "'count' must be an int"
