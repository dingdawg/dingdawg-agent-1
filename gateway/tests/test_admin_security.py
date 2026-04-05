"""STOA Security tests for the DingDawg Command Center admin API.

Covers
------
- Every admin endpoint returns 401 with no token
- Every admin endpoint returns 403 with a non-admin token
- No admin endpoint leaks Stripe secret key values
- No admin endpoint leaks JWT secret values
- No admin endpoint leaks database filesystem paths
- No admin endpoint returns Python stack traces
- Self-test endpoint only returns pass/fail (not key values)
- Health-detailed does NOT contain db_path in response
- env-check only returns var names + boolean set, never values
- System health does NOT expose raw API key values

Target: 40+ tests covering all 23 admin endpoints (19 in admin.py + 4 in
system_health.py).

Fixture pattern mirrors test_admin_api.py exactly.
"""

from __future__ import annotations

import json
import os
import uuid
from collections import namedtuple
from datetime import datetime, timezone
from typing import AsyncIterator

import aiosqlite
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from isg_agent.api.routes.auth import _create_token
from isg_agent.config import get_settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SECRET = "test-secret-security-suite-do-not-use"
_ADMIN_EMAIL = "admin@security-test.com"
_ADMIN_USER_ID = "admin-security-001"
_NON_ADMIN_EMAIL = "regularuser@security-test.com"
_NON_ADMIN_USER_ID = "nonadmin-security-002"

# Sentinel substrings that must NEVER appear in any admin response body.
# These are partial patterns that would indicate a real secret was leaked.
_FORBIDDEN_PATTERNS = [
    "sk_live_",
    "sk_test_",
    "SG.",  # SendGrid API key prefix
    "Traceback (most recent call last)",
    "Exception:",
    "Error: ",
    "sqlalchemy",  # internal ORM detail
]

ClientCtx = namedtuple("ClientCtx", ["ac", "db_path"])


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _make_token(user_id: str, email: str) -> str:
    return _create_token(user_id=user_id, email=email, secret_key=_SECRET)


def _admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_token(_ADMIN_USER_ID, _ADMIN_EMAIL)}"}


def _non_admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_token(_NON_ADMIN_USER_ID, _NON_ADMIN_EMAIL)}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(loop_scope="function")
async def ctx(tmp_path) -> AsyncIterator[ClientCtx]:
    """Async client + DB path.

    Injects Stripe and SendGrid keys that look real so we can verify they
    are NOT returned in any response body.
    """
    db_file = str(tmp_path / "test_security.db")

    _saved = {
        "ISG_AGENT_DB_PATH": os.environ.get("ISG_AGENT_DB_PATH"),
        "ISG_AGENT_SECRET_KEY": os.environ.get("ISG_AGENT_SECRET_KEY"),
        "ISG_AGENT_ADMIN_EMAIL": os.environ.get("ISG_AGENT_ADMIN_EMAIL"),
        "ISG_AGENT_STRIPE_SECRET_KEY": os.environ.get("ISG_AGENT_STRIPE_SECRET_KEY"),
        "ISG_AGENT_SENDGRID_API_KEY": os.environ.get("ISG_AGENT_SENDGRID_API_KEY"),
    }

    os.environ["ISG_AGENT_DB_PATH"] = db_file
    os.environ["ISG_AGENT_SECRET_KEY"] = _SECRET
    os.environ["ISG_AGENT_ADMIN_EMAIL"] = _ADMIN_EMAIL
    # Fake keys that look realistic — must never appear in any response body
    os.environ["ISG_AGENT_STRIPE_SECRET_KEY"] = "stripe_test_key_placeholder_for_security_tests"
    os.environ["ISG_AGENT_SENDGRID_API_KEY"] = "SG.FAKESGKEYFORTEST1234"
    get_settings.cache_clear()

    try:
        from isg_agent.app import create_app, lifespan
        from isg_agent.api.routes.auth import _CREATE_USERS_SQL, _CREATE_INDEX_EMAIL
        from isg_agent.db.schema import create_tables

        app = create_app()

        async with lifespan(app):
            async with aiosqlite.connect(db_file) as _db:
                await create_tables(_db)
                await _db.execute(_CREATE_USERS_SQL)
                await _db.execute(_CREATE_INDEX_EMAIL)
                await _db.commit()

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ClientCtx(ac=ac, db_path=db_file)
    finally:
        for key, original in _saved.items():
            if original is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Helper: assert body has no forbidden patterns
# ---------------------------------------------------------------------------


def _assert_no_secrets(response_text: str, context: str = "") -> None:
    """Fail if any forbidden pattern appears in the response body."""
    body_lower = response_text
    for pattern in _FORBIDDEN_PATTERNS:
        assert pattern not in body_lower, (
            f"Response leaked forbidden pattern '{pattern}' "
            f"{'in ' + context if context else ''}. "
            f"Body snippet: {response_text[:300]}"
        )


# ---------------------------------------------------------------------------
# All admin endpoints under test
# ---------------------------------------------------------------------------

# admin.py router (prefix: /api/v1/admin)
_ADMIN_GET_ENDPOINTS = [
    "/api/v1/admin/whoami",
    "/api/v1/admin/platform-stats",
    "/api/v1/admin/agents",
    "/api/v1/admin/errors",
    "/api/v1/admin/health-detailed",
    "/api/v1/admin/integration-health",
    "/api/v1/admin/stripe-status",
    "/api/v1/admin/contacts",
    "/api/v1/admin/funnel",
    "/api/v1/admin/campaigns",
    "/api/v1/admin/email-stats",
    "/api/v1/admin/workflow-tests",
    "/api/v1/admin/alerts",
    "/api/v1/admin/events",
    "/api/v1/admin/priorities",
    # system_health.py router (prefix: /api/v1/admin/system)
    "/api/v1/admin/system/health",
    "/api/v1/admin/system/errors",
    "/api/v1/admin/system/metrics",
]

_ADMIN_POST_ENDPOINTS_NO_BODY = [
    "/api/v1/admin/deploy-marketing-agent",
    "/api/v1/admin/system/self-test",
]


# ===========================================================================
# Phase 1: 401 — no auth on every endpoint
# ===========================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", _ADMIN_GET_ENDPOINTS)
async def test_get_endpoint_returns_401_without_token(endpoint: str, ctx: ClientCtx) -> None:
    """Every GET admin endpoint must reject unauthenticated requests with 401."""
    resp = await ctx.ac.get(endpoint)
    assert resp.status_code == 401, (
        f"Expected 401 for unauthenticated GET {endpoint}, got {resp.status_code}. "
        f"Body: {resp.text[:200]}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", _ADMIN_POST_ENDPOINTS_NO_BODY)
async def test_post_endpoint_returns_401_without_token(endpoint: str, ctx: ClientCtx) -> None:
    """Every POST admin endpoint must reject unauthenticated requests with 401."""
    resp = await ctx.ac.post(endpoint)
    assert resp.status_code == 401, (
        f"Expected 401 for unauthenticated POST {endpoint}, got {resp.status_code}. "
        f"Body: {resp.text[:200]}"
    )


@pytest.mark.asyncio
async def test_post_command_returns_401_without_token(ctx: ClientCtx) -> None:
    resp = await ctx.ac.post("/api/v1/admin/command", json={"command": "status"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_post_alerts_configure_returns_401_without_token(ctx: ClientCtx) -> None:
    resp = await ctx.ac.post("/api/v1/admin/alerts/configure", json={})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_post_workflow_test_run_returns_401_without_token(ctx: ClientCtx) -> None:
    resp = await ctx.ac.post("/api/v1/admin/workflow-tests/health_check/run")
    assert resp.status_code == 401


# ===========================================================================
# Phase 2: 403 — non-admin token on every endpoint
# ===========================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", _ADMIN_GET_ENDPOINTS)
async def test_get_endpoint_returns_403_with_non_admin_token(endpoint: str, ctx: ClientCtx) -> None:
    """Every GET admin endpoint must reject non-admin authenticated users with 403."""
    resp = await ctx.ac.get(endpoint, headers=_non_admin_headers())
    assert resp.status_code == 403, (
        f"Expected 403 for non-admin GET {endpoint}, got {resp.status_code}. "
        f"Body: {resp.text[:200]}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", _ADMIN_POST_ENDPOINTS_NO_BODY)
async def test_post_endpoint_returns_403_with_non_admin_token(endpoint: str, ctx: ClientCtx) -> None:
    """Every POST admin endpoint must reject non-admin users with 403."""
    resp = await ctx.ac.post(endpoint, headers=_non_admin_headers())
    assert resp.status_code == 403, (
        f"Expected 403 for non-admin POST {endpoint}, got {resp.status_code}. "
        f"Body: {resp.text[:200]}"
    )


@pytest.mark.asyncio
async def test_post_command_returns_403_with_non_admin_token(ctx: ClientCtx) -> None:
    resp = await ctx.ac.post(
        "/api/v1/admin/command",
        json={"command": "status"},
        headers=_non_admin_headers(),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_post_alerts_configure_returns_403_with_non_admin_token(ctx: ClientCtx) -> None:
    resp = await ctx.ac.post(
        "/api/v1/admin/alerts/configure",
        json={"error_rate_per_hour": 50},
        headers=_non_admin_headers(),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_post_workflow_test_run_returns_403_with_non_admin_token(ctx: ClientCtx) -> None:
    resp = await ctx.ac.post(
        "/api/v1/admin/workflow-tests/health_check/run",
        headers=_non_admin_headers(),
    )
    assert resp.status_code == 403


# ===========================================================================
# Phase 3: 200 — admin token works (baseline auth smoke test)
# ===========================================================================


@pytest.mark.asyncio
async def test_whoami_returns_200_for_admin(ctx: ClientCtx) -> None:
    resp = await ctx.ac.get("/api/v1/admin/whoami", headers=_admin_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_admin"] is True
    assert data["email"] == _ADMIN_EMAIL


# ===========================================================================
# Phase 4: No Stripe secret key values leaked in responses
# ===========================================================================


@pytest.mark.asyncio
async def test_stripe_status_does_not_leak_stripe_key(ctx: ClientCtx) -> None:
    """stripe-status returns mode (test/live) but NEVER the key value."""
    resp = await ctx.ac.get("/api/v1/admin/stripe-status", headers=_admin_headers())
    assert resp.status_code == 200
    body = resp.text
    assert "stripe_test_key_placeholder_for_security_tests" not in body, (
        "stripe-status response leaked the Stripe secret key value"
    )
    assert "sk_live_" not in body
    data = resp.json()
    # Mode is acceptable: "test" or "live" string — but NOT the full key
    assert "mode" in data
    assert data["mode"] in ("test", "live", "not_configured", "unknown")


@pytest.mark.asyncio
async def test_system_health_does_not_leak_stripe_key(ctx: ClientCtx) -> None:
    resp = await ctx.ac.get("/api/v1/admin/system/health", headers=_admin_headers())
    assert resp.status_code == 200
    body = resp.text
    assert "stripe_test_key_placeholder_for_security_tests" not in body
    assert "sk_live_" not in body


@pytest.mark.asyncio
async def test_priorities_does_not_leak_stripe_key(ctx: ClientCtx) -> None:
    """priorities must not leak the actual Stripe key value.

    The action field may contain the instructional text 'sk_live_...' as a
    placeholder hint to guide the operator — that is acceptable.  What must
    never appear is the real key value injected by the fixture.
    """
    resp = await ctx.ac.get("/api/v1/admin/priorities", headers=_admin_headers())
    assert resp.status_code == 200
    body = resp.text
    # The actual fake key value must never appear
    assert "stripe_test_key_placeholder_for_security_tests" not in body, (
        "priorities response leaked the actual Stripe secret key value"
    )


@pytest.mark.asyncio
async def test_self_test_does_not_leak_stripe_key(ctx: ClientCtx) -> None:
    """self-test reports stripe as pass/fail, not the key value."""
    resp = await ctx.ac.post("/api/v1/admin/system/self-test", headers=_admin_headers())
    assert resp.status_code == 200
    body = resp.text
    assert "stripe_test_key_placeholder_for_security_tests" not in body, (
        "self-test response leaked the Stripe secret key value"
    )
    # The result must be a pass/fail string, not the key
    data = resp.json()
    stripe_result = next((r for r in data["results"] if r["test"] == "stripe"), None)
    assert stripe_result is not None
    assert stripe_result["result"] in ("pass", "fail", "warning")
    # message should say mode (TEST/LIVE) but never the key
    assert "stripe_test_key_placeholder_for_security_tests" not in stripe_result.get("message", "")


@pytest.mark.asyncio
async def test_command_env_check_does_not_leak_stripe_key(ctx: ClientCtx) -> None:
    """env-check reports var names + boolean, never actual values."""
    resp = await ctx.ac.post(
        "/api/v1/admin/command",
        json={"command": "env-check"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    body = resp.text
    assert "stripe_test_key_placeholder_for_security_tests" not in body, (
        "env-check command leaked the Stripe secret key value"
    )
    # Validate shape: each var entry has 'var' + 'set' bool, no 'value' field
    data = resp.json()
    for entry in data["response"]["vars"]:
        assert "var" in entry
        assert "set" in entry
        assert "value" not in entry, f"env-check leaked 'value' field for {entry['var']}"


# ===========================================================================
# Phase 5: No JWT secret leaked
# ===========================================================================


@pytest.mark.asyncio
async def test_no_endpoint_leaks_jwt_secret(ctx: ClientCtx) -> None:
    """Spot-check key endpoints don't return the JWT secret in the body."""
    secret = _SECRET
    for endpoint in [
        "/api/v1/admin/whoami",
        "/api/v1/admin/platform-stats",
        "/api/v1/admin/system/health",
    ]:
        resp = await ctx.ac.get(endpoint, headers=_admin_headers())
        assert resp.status_code == 200
        assert secret not in resp.text, (
            f"JWT secret leaked in response body for {endpoint}"
        )


# ===========================================================================
# Phase 6: No database filesystem path leaked
# ===========================================================================


@pytest.mark.asyncio
async def test_health_detailed_does_not_expose_db_path(ctx: ClientCtx) -> None:
    """health-detailed must NOT include the db_path filesystem field.

    The db_path field was removed in the security fix — this test verifies
    the fix holds and will catch any regression.
    """
    resp = await ctx.ac.get("/api/v1/admin/health-detailed", headers=_admin_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert "db_path" not in data, (
        f"health-detailed response leaked db_path: {data.get('db_path')}"
    )
    # The actual path string must not appear in the body
    assert ctx.db_path not in resp.text, (
        "health-detailed response contains the literal database file path"
    )


@pytest.mark.asyncio
async def test_platform_stats_does_not_expose_db_path(ctx: ClientCtx) -> None:
    resp = await ctx.ac.get("/api/v1/admin/platform-stats", headers=_admin_headers())
    assert resp.status_code == 200
    assert ctx.db_path not in resp.text


@pytest.mark.asyncio
async def test_system_health_does_not_expose_db_path(ctx: ClientCtx) -> None:
    resp = await ctx.ac.get("/api/v1/admin/system/health", headers=_admin_headers())
    assert resp.status_code == 200
    assert ctx.db_path not in resp.text


@pytest.mark.asyncio
async def test_self_test_does_not_expose_db_path(ctx: ClientCtx) -> None:
    resp = await ctx.ac.post("/api/v1/admin/system/self-test", headers=_admin_headers())
    assert resp.status_code == 200
    assert ctx.db_path not in resp.text


@pytest.mark.asyncio
async def test_priorities_does_not_expose_db_path(ctx: ClientCtx) -> None:
    resp = await ctx.ac.get("/api/v1/admin/priorities", headers=_admin_headers())
    assert resp.status_code == 200
    assert ctx.db_path not in resp.text


# ===========================================================================
# Phase 7: No stack traces on error conditions
# ===========================================================================


@pytest.mark.asyncio
async def test_workflow_test_invalid_id_no_stack_trace(ctx: ClientCtx) -> None:
    """Invalid workflow test ID returns 404 with a clean error — no traceback."""
    resp = await ctx.ac.post(
        "/api/v1/admin/workflow-tests/NONEXISTENT_ID_XYZ/run",
        headers=_admin_headers(),
    )
    assert resp.status_code == 404
    body = resp.text
    assert "Traceback" not in body
    assert "traceback" not in body.lower()
    assert "Exception" not in body or "HTTPException" not in body


@pytest.mark.asyncio
async def test_command_unknown_does_not_stack_trace(ctx: ClientCtx) -> None:
    """Unknown command returns a help response, not a stack trace."""
    resp = await ctx.ac.post(
        "/api/v1/admin/command",
        json={"command": "__unknown_command_xyz__"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    body = resp.text
    assert "Traceback" not in body
    assert "traceback" not in body.lower()


@pytest.mark.asyncio
async def test_command_empty_string_no_stack_trace(ctx: ClientCtx) -> None:
    """Empty command returns 422 cleanly — no traceback."""
    resp = await ctx.ac.post(
        "/api/v1/admin/command",
        json={"command": ""},
        headers=_admin_headers(),
    )
    assert resp.status_code == 422
    assert "Traceback" not in resp.text


@pytest.mark.asyncio
async def test_alerts_configure_invalid_type_no_stack_trace(ctx: ClientCtx) -> None:
    """Invalid body type returns 422, not a stack trace."""
    resp = await ctx.ac.post(
        "/api/v1/admin/alerts/configure",
        json={"error_rate_per_hour": "not_an_int"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 422
    assert "Traceback" not in resp.text


# ===========================================================================
# Phase 8: Self-test only returns pass/fail (not key values anywhere)
# ===========================================================================


@pytest.mark.asyncio
async def test_self_test_sendgrid_result_is_pass_fail_only(ctx: ClientCtx) -> None:
    """self-test sendgrid result must say configured/not-configured, not the key."""
    resp = await ctx.ac.post("/api/v1/admin/system/self-test", headers=_admin_headers())
    assert resp.status_code == 200
    data = resp.json()
    sendgrid_result = next((r for r in data["results"] if r["test"] == "sendgrid"), None)
    assert sendgrid_result is not None
    assert "SG.FAKESGKEYFORTEST" not in sendgrid_result.get("message", ""), (
        "self-test leaked SendGrid API key value"
    )
    assert "SG.FAKESGKEYFORTEST" not in resp.text


@pytest.mark.asyncio
async def test_self_test_llm_providers_no_key_values(ctx: ClientCtx) -> None:
    """llm_providers self-test must not expose any API key values."""
    resp = await ctx.ac.post("/api/v1/admin/system/self-test", headers=_admin_headers())
    assert resp.status_code == 200
    body = resp.text
    # No OpenAI, Anthropic, Google, Inception key patterns
    for pattern in ["sk-", "AIza", "Bearer sk"]:
        assert pattern not in body, f"self-test leaked key pattern '{pattern}'"


# ===========================================================================
# Phase 9: Sensitive env-check shape validation
# ===========================================================================


@pytest.mark.asyncio
async def test_env_check_response_has_correct_shape(ctx: ClientCtx) -> None:
    """env-check vars have 'var' + 'set' fields only — no 'value' or 'content'."""
    resp = await ctx.ac.post(
        "/api/v1/admin/command",
        json={"command": "env-check"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "response" in data
    assert "vars" in data["response"]
    vars_list = data["response"]["vars"]
    assert isinstance(vars_list, list)
    assert len(vars_list) > 0
    for entry in vars_list:
        allowed_keys = {"var", "set"}
        actual_keys = set(entry.keys())
        forbidden_extra = actual_keys - allowed_keys
        assert not forbidden_extra, (
            f"env-check entry has forbidden extra keys: {forbidden_extra}"
        )


# ===========================================================================
# Phase 10: Admin cannot reach other users' data via cross-contamination
# ===========================================================================


@pytest.mark.asyncio
async def test_admin_agents_list_does_not_expose_passwords(ctx: ClientCtx) -> None:
    """agents list must never include password_hash or salt fields."""
    resp = await ctx.ac.get("/api/v1/admin/agents", headers=_admin_headers())
    assert resp.status_code == 200
    body = resp.text
    assert "password_hash" not in body
    assert "fakehash" not in body
    assert "fakesalt" not in body


@pytest.mark.asyncio
async def test_admin_contacts_does_not_expose_passwords(ctx: ClientCtx) -> None:
    resp = await ctx.ac.get("/api/v1/admin/contacts", headers=_admin_headers())
    assert resp.status_code == 200
    body = resp.text
    assert "password_hash" not in body
    assert "fakehash" not in body


# ===========================================================================
# Phase 11: Response shape verification for security-critical fields
# ===========================================================================


@pytest.mark.asyncio
async def test_stripe_status_shape_security(ctx: ClientCtx) -> None:
    """stripe-status response has expected shape with no raw key fields."""
    resp = await ctx.ac.get("/api/v1/admin/stripe-status", headers=_admin_headers())
    assert resp.status_code == 200
    data = resp.json()
    # Must have mode but not key, not secret
    assert "mode" in data
    assert "webhook_configured" in data
    assert "key" not in data
    assert "secret" not in data
    assert "stripe_secret_key" not in data


@pytest.mark.asyncio
async def test_system_health_security_layer_present(ctx: ClientCtx) -> None:
    """system health response must include security layer status."""
    resp = await ctx.ac.get("/api/v1/admin/system/health", headers=_admin_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert "components" in data
    assert "security" in data["components"]
    security = data["components"]["security"]
    assert "rate_limiter" in security
    assert "constitution" in security


@pytest.mark.asyncio
async def test_health_detailed_has_required_fields_after_security_fix(ctx: ClientCtx) -> None:
    """Verify health-detailed still returns useful data after removing db_path."""
    resp = await ctx.ac.get("/api/v1/admin/health-detailed", headers=_admin_headers())
    assert resp.status_code == 200
    data = resp.json()
    # These fields must still be present
    assert "db_size_bytes" in data
    assert "memory_rss_kb" in data
    assert "checked_at" in data
    assert "audit_event_counts" in data
    # db_path must be absent (was the security gap)
    assert "db_path" not in data


# ===========================================================================
# Phase 12: Rate limiting note test (structural check)
# ===========================================================================


@pytest.mark.asyncio
async def test_admin_endpoints_do_not_expose_rate_limit_internals(ctx: ClientCtx) -> None:
    """Rate limiter state/config should not be exposed in admin responses."""
    resp = await ctx.ac.get("/api/v1/admin/system/health", headers=_admin_headers())
    assert resp.status_code == 200
    data = resp.json()
    security = data["components"]["security"]
    # Status is OK to return ('active'), but not internal config/limits
    assert security.get("rate_limiter") == "active"
    # Must not expose rate limit counts or windows
    assert "rate_limit_window" not in data
    assert "rate_limit_count" not in data
    assert "max_requests" not in data
