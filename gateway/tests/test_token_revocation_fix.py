"""P1 Security fix tests — token revocation table unification.

Proves: logout → token rejected on every subsequent request.

Design:
- Spins up the FULL app via lifespan (same as test_integration_workflows.py).
- Tests run against an in-process ASGI app — no network, no mocks.
- Each test class is fully isolated: unique email + unique handle.
- Guards against regression: these tests MUST FAIL before the fix and
  PASS after. The critical assertion is `assert after_logout_resp.status_code == 401`.

Run with:
    cd /home/joe-rangel/Desktop/DingDawg-Agent-1/gateway
    python3 -m pytest tests/test_token_revocation_fix.py -v --tb=short
"""

from __future__ import annotations

import os
import uuid
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from isg_agent.config import get_settings


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SECRET = "revocation-test-secret-do-not-use-in-production"


# ---------------------------------------------------------------------------
# Fixture — full-lifespan app, isolated per-test DB
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def rev_client(tmp_path) -> AsyncIterator[AsyncClient]:
    """Full-lifespan async client with an isolated SQLite DB.

    Sets ISG_AGENT_DEPLOYMENT_ENV=test to bypass honeypot / Turnstile / email
    checks at /auth/register.  The TokenRevocationGuard middleware will read
    from the same DB that logout writes to once the fix is applied.
    """
    db_file = str(tmp_path / "revocation_test.db")

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unique_email(prefix: str = "rev") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@revocation-test.example"


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _register(client: AsyncClient, email: str, password: str) -> str:
    """Register a user, auto-verify email, and return the access token."""
    import aiosqlite as _aiosqlite
    resp = await client.post(
        "/auth/register",
        json={"email": email, "password": password, "terms_accepted": True},
    )
    assert resp.status_code == 201, f"register failed: {resp.text}"
    # Auto-verify email so re-login after logout works (email verification gate)
    db_path = os.environ.get("ISG_AGENT_DB_PATH", "")
    if db_path:
        async with _aiosqlite.connect(db_path) as db:
            await db.execute("UPDATE users SET email_verified=1 WHERE email=?", (email,))
            await db.commit()
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Test 1: Basic revocation — logout causes 401 on protected route
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLogoutRevokesToken:
    """Core security guarantee: a logged-out token MUST be rejected."""

    async def test_token_rejected_after_logout(self, rev_client: AsyncClient) -> None:
        """Register → access protected route → logout → 401 on same token.

        This is the primary regression test for the P1 table-mismatch fix.
        It MUST fail (token still accepted = 200) before the fix, and
        MUST pass (token rejected = 401) after the fix.
        """
        client = rev_client
        token = await _register(client, _unique_email("basic"), "Passw0rd!Secure")

        # Token is valid before logout — protected route returns 200.
        pre_resp = await client.get("/auth/me", headers=_auth_headers(token))
        assert pre_resp.status_code == 200, (
            f"pre-logout /auth/me should be 200, got {pre_resp.status_code}"
        )

        # Logout — server should write the token to token_revocations.
        logout_resp = await client.post("/auth/logout", headers=_auth_headers(token))
        assert logout_resp.status_code == 200
        assert "Logged out" in logout_resp.json()["message"]

        # CRITICAL ASSERTION: same token MUST be rejected after logout.
        after_resp = await client.get("/auth/me", headers=_auth_headers(token))
        assert after_resp.status_code == 401, (
            f"Expected 401 after logout, got {after_resp.status_code}. "
            "This means logout is writing to a different table than the guard reads from. "
            "Fix: make logout call revoke_token() from token_guard.py."
        )


# ---------------------------------------------------------------------------
# Test 2: Agents endpoint also rejects revoked token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRevokedTokenRejectedOnAgentsRoute:
    """Revocation guard must block ALL protected routes, not just /auth/me."""

    async def test_agents_list_rejects_revoked_token(self, rev_client: AsyncClient) -> None:
        client = rev_client
        token = await _register(client, _unique_email("agents"), "Passw0rd!Secure")

        # Confirm access works before logout.
        pre_resp = await client.get("/api/v1/agents", headers=_auth_headers(token))
        assert pre_resp.status_code == 200, (
            f"pre-logout /api/v1/agents should be 200, got {pre_resp.status_code}"
        )

        # Logout.
        logout_resp = await client.post("/auth/logout", headers=_auth_headers(token))
        assert logout_resp.status_code == 200

        # Revoked token must be rejected on agents route.
        after_resp = await client.get("/api/v1/agents", headers=_auth_headers(token))
        assert after_resp.status_code == 401, (
            f"Expected 401 for revoked token on /api/v1/agents, got {after_resp.status_code}"
        )
        body = after_resp.json()
        # The TokenRevocationGuard returns a specific error shape.
        assert "error" in body or "detail" in body


# ---------------------------------------------------------------------------
# Test 3: New token from re-login is NOT affected by old token revocation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestNewTokenValidAfterLogout:
    """Re-login after logout issues a fresh token that is not revoked."""

    async def test_new_token_works_after_old_revoked(self, rev_client: AsyncClient) -> None:
        client = rev_client
        email = _unique_email("relogin")
        password = "Passw0rd!Secure"
        old_token = await _register(client, email, password)

        # Logout old token.
        logout_resp = await client.post("/auth/logout", headers=_auth_headers(old_token))
        assert logout_resp.status_code == 200

        # Login again — gets a new JWT.
        login_resp = await client.post(
            "/auth/login",
            json={"email": email, "password": password},
        )
        assert login_resp.status_code == 200
        new_token = login_resp.json()["access_token"]
        assert new_token != old_token, "Re-login must issue a distinct token"

        # New token must work on protected routes.
        me_resp = await client.get("/auth/me", headers=_auth_headers(new_token))
        assert me_resp.status_code == 200, (
            f"New token after re-login should be accepted, got {me_resp.status_code}"
        )

        # Old token must still be rejected.
        old_resp = await client.get("/auth/me", headers=_auth_headers(old_token))
        assert old_resp.status_code == 401, (
            f"Old (revoked) token must be rejected, got {old_resp.status_code}"
        )


# ---------------------------------------------------------------------------
# Test 4: Logout is idempotent — double-logout returns 401 (token invalid)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDoubleLogoutIdempotent:
    """Calling logout twice must not crash; second call should fail gracefully."""

    async def test_double_logout_second_call_rejects(self, rev_client: AsyncClient) -> None:
        client = rev_client
        token = await _register(client, _unique_email("double"), "Passw0rd!Secure")

        # First logout.
        resp1 = await client.post("/auth/logout", headers=_auth_headers(token))
        assert resp1.status_code == 200

        # Second logout with the same (now revoked) token.
        # The revocation guard intercepts the request before the route handler —
        # it must return 401 because the token is already revoked.
        resp2 = await client.post("/auth/logout", headers=_auth_headers(token))
        assert resp2.status_code == 401, (
            f"Second logout attempt with revoked token must return 401, got {resp2.status_code}"
        )


# ---------------------------------------------------------------------------
# Test 5: Revocation guard response shape is correct
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRevocationErrorShape:
    """The 401 response from the revocation guard must have the correct JSON shape."""

    async def test_revocation_response_json_shape(self, rev_client: AsyncClient) -> None:
        client = rev_client
        token = await _register(client, _unique_email("shape"), "Passw0rd!Secure")

        # Logout.
        logout_resp = await client.post("/auth/logout", headers=_auth_headers(token))
        assert logout_resp.status_code == 200

        # Request with revoked token — check JSON error body.
        after_resp = await client.get("/auth/me", headers=_auth_headers(token))
        assert after_resp.status_code == 401

        body = after_resp.json()
        # TokenRevocationGuard returns: {"error": "token_revoked", "message": "..."}
        # Route-level auth returns: {"detail": "..."}
        # Either shape is acceptable as long as it's a 401.
        assert isinstance(body, dict), "Response body must be a JSON object"
        has_error_key = "error" in body or "detail" in body
        assert has_error_key, (
            f"401 response must contain 'error' or 'detail' key, got: {body}"
        )
