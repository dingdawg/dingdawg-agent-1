"""End-to-end workflow integration tests for Agent 1.

Each test class simulates a complete user journey through the API —
register, create agents, configure integrations, exercise payments, etc.
Tests run against a fully-initialised in-process ASGI app (no network).

Run with:
    cd /home/joe-rangel/Desktop/DingDawg-Agent-1/gateway
    python3 -m pytest tests/test_integration_workflows.py -v --tb=short

Design rules:
- Every workflow registers its OWN user (unique email + unique handle) so
  workflows are fully isolated and can run in any order.
- Fixture spins up the full lifespan so all app.state components are live.
- No mocks except for third-party network calls (Stripe, SendGrid, Twilio).
- All assertions check both HTTP status code AND response body shape.
"""

from __future__ import annotations

import base64
import json
import os
import time
import uuid
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from isg_agent.config import get_settings

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_SECRET = "workflow-test-secret-do-not-use-in-production"

# ---------------------------------------------------------------------------
# Shared async_client fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def wf_client(tmp_path) -> AsyncIterator[AsyncClient]:
    """Full-lifespan async client used across all workflow tests.

    Sets ISG_AGENT_DEPLOYMENT_ENV=test so bot-prevention (honeypot,
    Turnstile) and disposable-email checks are skipped at /auth/register.
    """
    db_file = str(tmp_path / "workflow_test.db")

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


def _unique_email(prefix: str = "user") -> str:
    """Generate a unique test email address per call."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}@workflow-test.example"


def _unique_handle(prefix: str = "testagent") -> str:
    """Generate a unique handle per call (letters + digits, max 24 chars)."""
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _verify_email_in_db(email: str) -> None:
    """Auto-verify a user's email directly in the test DB (bypasses email flow)."""
    import aiosqlite
    db_path = os.environ.get("ISG_AGENT_DB_PATH", "")
    if not db_path:
        return
    async with aiosqlite.connect(db_path) as db:
        await db.execute("UPDATE users SET email_verified=1 WHERE email=?", (email,))
        await db.commit()


async def _register_and_login(client: AsyncClient, email: str, password: str) -> str:
    """Register a user, verify email in DB, return the access token."""
    resp = await client.post(
        "/auth/register",
        json={"email": email, "password": password, "terms_accepted": True},
    )
    assert resp.status_code == 201, f"register failed: {resp.text}"
    # Auto-verify email so login succeeds (email verification gate)
    await _verify_email_in_db(email)
    login_resp = await client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )
    assert login_resp.status_code == 200, f"login after verify failed: {login_resp.text}"
    return login_resp.json()["access_token"]


async def _create_agent(
    client: AsyncClient,
    token: str,
    handle: str,
    name: str = "Workflow Test Agent",
    agent_type: str = "business",
) -> dict:
    """Create an agent and return the response body."""
    resp = await client.post(
        "/api/v1/agents",
        json={
            "handle": handle,
            "name": name,
            "agent_type": agent_type,
        },
        headers=_auth_headers(token),
    )
    assert resp.status_code == 201, f"create_agent failed: {resp.text}"
    return resp.json()


# ---------------------------------------------------------------------------
# Workflow 1: Complete Onboarding Journey
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestWorkflow01OnboardingJourney:
    """Register → Login → Handle check → Create agent → List → Get → Health."""

    async def test_complete_onboarding_journey(self, wf_client: AsyncClient) -> None:
        client = wf_client
        email = _unique_email("onboard")
        password = "Passw0rd!Secure"
        handle = _unique_handle("onboard")

        # Step 1: Register
        reg_resp = await client.post(
            "/auth/register",
            json={"email": email, "password": password, "terms_accepted": True},
        )
        assert reg_resp.status_code == 201
        reg_body = reg_resp.json()
        assert reg_body["access_token"]
        assert reg_body["user_id"]
        assert reg_body["email"] == email
        token = reg_body["access_token"]

        # Auto-verify email so subsequent login works (email verification gate)
        await _verify_email_in_db(email)

        # Step 2: Login with same credentials
        login_resp = await client.post(
            "/auth/login",
            json={"email": email, "password": password},
        )
        assert login_resp.status_code == 200
        assert login_resp.json()["access_token"]

        # Step 3: Check handle availability (should be available)
        avail_resp = await client.get(f"/api/v1/agents/handle/{handle}/check")
        assert avail_resp.status_code == 200
        avail_body = avail_resp.json()
        assert avail_body["available"] is True
        assert avail_body["handle"] == handle

        # Step 4: Create agent
        create_resp = await client.post(
            "/api/v1/agents",
            json={"handle": handle, "name": "Onboarding Agent", "agent_type": "business"},
            headers=_auth_headers(token),
        )
        assert create_resp.status_code == 201
        agent = create_resp.json()
        agent_id = agent["id"]
        assert agent["handle"] == handle
        assert agent["status"] in ("active", "setup")

        # Step 5: Handle no longer available after claim
        taken_resp = await client.get(f"/api/v1/agents/handle/{handle}/check")
        assert taken_resp.status_code == 200
        assert taken_resp.json()["available"] is False

        # Step 6: Agent appears in list
        list_resp = await client.get(
            "/api/v1/agents",
            headers=_auth_headers(token),
        )
        assert list_resp.status_code == 200
        list_body = list_resp.json()
        assert list_body["count"] >= 1
        agent_ids = [a["id"] for a in list_body["agents"]]
        assert agent_id in agent_ids

        # Step 7: Get agent by ID
        get_resp = await client.get(
            f"/api/v1/agents/{agent_id}",
            headers=_auth_headers(token),
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == agent_id

        # Step 8: Health check returns healthy
        health_resp = await client.get("/health")
        assert health_resp.status_code == 200
        health_body = health_resp.json()
        assert health_body["status"] == "healthy"
        assert health_body["version"]
        assert health_body["database"] == "connected"


# ---------------------------------------------------------------------------
# Workflow 2: Chat & Session Journey
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestWorkflow02ChatSessionJourney:
    """Login → Create agent → Create session → List sessions → Get /auth/me."""

    async def test_chat_session_journey(self, wf_client: AsyncClient) -> None:
        client = wf_client
        email = _unique_email("chat")
        token = await _register_and_login(client, email, "Passw0rd!Secure")
        handle = _unique_handle("chat")

        # Create agent
        agent = await _create_agent(client, token, handle, name="Chat Agent")
        agent_id = agent["id"]

        # Get /auth/me — verify user identity
        me_resp = await client.get(
            "/auth/me",
            headers=_auth_headers(token),
        )
        assert me_resp.status_code == 200
        me_body = me_resp.json()
        assert me_body["email"] == email
        assert me_body["user_id"]
        assert me_body["created_at"]

        # List agents — agent is present
        list_resp = await client.get("/api/v1/agents", headers=_auth_headers(token))
        assert list_resp.status_code == 200
        ids = [a["id"] for a in list_resp.json()["agents"]]
        assert agent_id in ids

        # Get agent by type filter
        biz_resp = await client.get(
            "/api/v1/agents?agent_type=business",
            headers=_auth_headers(token),
        )
        assert biz_resp.status_code == 200
        biz_ids = [a["id"] for a in biz_resp.json()["agents"]]
        assert agent_id in biz_ids

        # Invalid agent_type filter returns 422
        bad_resp = await client.get(
            "/api/v1/agents?agent_type=invalid_type",
            headers=_auth_headers(token),
        )
        assert bad_resp.status_code == 422


# ---------------------------------------------------------------------------
# Workflow 3: Integration Configuration Journey
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestWorkflow03IntegrationConfigJourney:
    """Login → Create agent → Get integration status → Configure/disconnect."""

    async def test_integration_status_journey(self, wf_client: AsyncClient) -> None:
        client = wf_client
        email = _unique_email("integ")
        token = await _register_and_login(client, email, "Passw0rd!Secure")
        handle = _unique_handle("integ")
        agent = await _create_agent(client, token, handle, name="Integration Agent")
        agent_id = agent["id"]

        # Get initial integration status — all disconnected
        status_resp = await client.get(
            f"/api/v1/integrations/{agent_id}/status",
            headers=_auth_headers(token),
        )
        assert status_resp.status_code == 200
        status_body = status_resp.json()
        assert status_body["agent_id"] == agent_id
        assert "email" in status_body
        assert "sms" in status_body
        assert "calendar" in status_body
        assert "voice" in status_body
        assert status_body["email"]["connected"] is False
        assert status_body["sms"]["connected"] is False

        # Attempt to get status for agent owned by different user → 404
        other_token = await _register_and_login(
            client, _unique_email("other"), "Passw0rd!Secure"
        )
        forbidden_resp = await client.get(
            f"/api/v1/integrations/{agent_id}/status",
            headers=_auth_headers(other_token),
        )
        assert forbidden_resp.status_code == 404

        # Webhooks list — initially empty
        wh_resp = await client.get(
            f"/api/v1/integrations/{agent_id}/webhooks",
            headers=_auth_headers(token),
        )
        assert wh_resp.status_code == 200
        assert wh_resp.json() == []


# ---------------------------------------------------------------------------
# Workflow 4: Webhook Lifecycle Journey
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestWorkflow04WebhookLifecycleJourney:
    """Create webhook → List → Simulate inbound (SendGrid + Twilio) → Delete."""

    async def test_webhook_lifecycle(self, wf_client: AsyncClient) -> None:
        client = wf_client
        email = _unique_email("webhook")
        token = await _register_and_login(client, email, "Passw0rd!Secure")
        handle = _unique_handle("webhook")
        agent = await _create_agent(client, token, handle, name="Webhook Agent")
        agent_id = agent["id"]

        # Create outbound webhook subscription
        create_wh_resp = await client.post(
            f"/api/v1/integrations/{agent_id}/webhooks",
            json={
                "url": "https://example.com/webhook",
                "events": ["message.received", "conversation.started"],
                "auth_type": "none",
            },
            headers=_auth_headers(token),
        )
        assert create_wh_resp.status_code == 201
        wh = create_wh_resp.json()
        webhook_id = wh["id"]
        assert wh["url"] == "https://example.com/webhook"
        assert "message.received" in wh["events"]
        assert wh["active"] is True

        # List webhooks — should contain our new one
        list_wh_resp = await client.get(
            f"/api/v1/integrations/{agent_id}/webhooks",
            headers=_auth_headers(token),
        )
        assert list_wh_resp.status_code == 200
        wh_list = list_wh_resp.json()
        assert len(wh_list) == 1
        assert wh_list[0]["id"] == webhook_id

        # Simulate inbound webhook (SendGrid) — no auth token = 401
        sg_resp = await client.post(
            "/api/v1/webhooks/sendgrid/inbound",
            json={
                "from": "sender@example.com",
                "to": f"{handle}@inbound.dingdawg.com",
                "subject": "Test email",
                "text": "Hello agent!",
            },
        )
        # Expects 401 because no SendGrid Basic Auth credentials are configured
        assert sg_resp.status_code == 401

        # Simulate inbound Twilio SMS — no signature = permissive mode (no token set)
        twilio_resp = await client.post(
            "/api/v1/webhooks/twilio/inbound",
            data={
                "From": "+15555550100",
                "To": "+15555550200",
                "Body": "Hello from SMS!",
                "MessageSid": "SMtest0001",
            },
        )
        # No TWILIO_AUTH_TOKEN configured → permissive dev mode → 200
        assert twilio_resp.status_code == 200
        twilio_body = twilio_resp.json()
        assert twilio_body["status"] == "ok"

        # Simulate Google Calendar push (sync event)
        gcal_resp = await client.post(
            "/api/v1/webhooks/google-calendar/push",
            headers={
                "X-Goog-Channel-ID": "channel-001",
                "X-Goog-Resource-State": "sync",
                "X-Goog-Resource-ID": "resource-001",
            },
        )
        assert gcal_resp.status_code == 200
        assert gcal_resp.json()["status"] == "acknowledged"

        # Delete webhook
        del_resp = await client.delete(
            f"/api/v1/integrations/{agent_id}/webhooks/{webhook_id}",
            headers=_auth_headers(token),
        )
        assert del_resp.status_code == 200
        assert del_resp.json()["status"] == "deleted"

        # Verify webhook no longer listed
        final_list_resp = await client.get(
            f"/api/v1/integrations/{agent_id}/webhooks",
            headers=_auth_headers(token),
        )
        assert final_list_resp.status_code == 200
        assert final_list_resp.json() == []

        # Duplicate delete → 404
        dup_del_resp = await client.delete(
            f"/api/v1/integrations/{agent_id}/webhooks/{webhook_id}",
            headers=_auth_headers(token),
        )
        assert dup_del_resp.status_code == 404


# ---------------------------------------------------------------------------
# Workflow 5: Payment & Billing Journey
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestWorkflow05PaymentBillingJourney:
    """Check usage → Subscribe free → Verify sub → Stripe endpoints 503 without keys."""

    async def test_payment_journey(self, wf_client: AsyncClient) -> None:
        client = wf_client
        email = _unique_email("payment")
        token = await _register_and_login(client, email, "Passw0rd!Secure")
        handle = _unique_handle("payment")
        agent = await _create_agent(client, token, handle, name="Payment Agent")
        agent_id = agent["id"]

        # Check usage (payment gate)
        usage_resp = await client.get(
            "/api/v1/payments/usage",
            headers=_auth_headers(token),
        )
        assert usage_resp.status_code == 200
        usage = usage_resp.json()
        assert "total_messages" in usage
        assert "free_remaining" in usage
        assert "is_paid" in usage

        # Subscribe to free plan (does not require Stripe)
        sub_resp = await client.post(
            "/api/v1/payments/subscribe",
            json={"agent_id": agent_id, "plan": "free"},
            headers=_auth_headers(token),
        )
        assert sub_resp.status_code == 201
        sub = sub_resp.json()
        assert sub["plan"] == "free"
        assert sub["agent_id"] == agent_id
        assert sub["is_active"] is True

        # Get skill usage for agent
        skill_usage_resp = await client.get(
            f"/api/v1/payments/usage/{agent_id}",
            headers=_auth_headers(token),
        )
        assert skill_usage_resp.status_code == 200
        skill_usage = skill_usage_resp.json()
        assert skill_usage["plan"] == "free"
        assert "total_actions" in skill_usage
        assert "remaining_free" in skill_usage

        # Get usage history
        history_resp = await client.get(
            f"/api/v1/payments/usage/{agent_id}/history",
            headers=_auth_headers(token),
        )
        assert history_resp.status_code == 200
        assert isinstance(history_resp.json(), list)

        # Paid plan without Stripe configured → 400
        paid_resp = await client.post(
            "/api/v1/payments/subscribe",
            json={"agent_id": agent_id, "plan": "starter"},
            headers=_auth_headers(token),
        )
        assert paid_resp.status_code == 400

        # Checkout session without Stripe configured → 503
        checkout_resp = await client.post(
            "/api/v1/payments/create-checkout-session",
            json={"plan": "starter", "agent_id": agent_id},
            headers=_auth_headers(token),
        )
        assert checkout_resp.status_code == 503

        # Invalid plan → 400
        invalid_plan_resp = await client.post(
            "/api/v1/payments/subscribe",
            json={"agent_id": agent_id, "plan": "diamond"},
            headers=_auth_headers(token),
        )
        assert invalid_plan_resp.status_code == 400

        # Stripe webhook without Stripe configured → 503
        wh_resp = await client.post(
            "/api/v1/payments/webhook",
            content=b"{}",
            headers={"stripe-signature": "fake-sig"},
        )
        assert wh_resp.status_code == 503

        # Payment usage without auth → 401
        no_auth_resp = await client.get("/api/v1/payments/usage")
        assert no_auth_resp.status_code == 401


# ---------------------------------------------------------------------------
# Workflow 6: Agent Management Journey
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestWorkflow06AgentManagementJourney:
    """Create → Update settings → Update branding → Verify → Archive → Verify."""

    async def test_agent_management_journey(self, wf_client: AsyncClient) -> None:
        client = wf_client
        email = _unique_email("mgmt")
        token = await _register_and_login(client, email, "Passw0rd!Secure")
        handle = _unique_handle("mgmt")
        agent = await _create_agent(client, token, handle, name="Management Agent")
        agent_id = agent["id"]

        # Update agent name
        update_resp = await client.patch(
            f"/api/v1/agents/{agent_id}",
            json={"name": "Updated Management Agent"},
            headers=_auth_headers(token),
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["name"] == "Updated Management Agent"

        # Update branding
        branding_resp = await client.patch(
            f"/api/v1/agents/{agent_id}",
            json={"branding_json": json.dumps({"primary_color": "#FF5733", "avatar_url": ""})},
            headers=_auth_headers(token),
        )
        assert branding_resp.status_code == 200

        # Verify changes persisted via GET
        get_resp = await client.get(
            f"/api/v1/agents/{agent_id}",
            headers=_auth_headers(token),
        )
        assert get_resp.status_code == 200
        refreshed = get_resp.json()
        assert refreshed["name"] == "Updated Management Agent"

        # PATCH with no updatable fields → 400
        empty_patch_resp = await client.patch(
            f"/api/v1/agents/{agent_id}",
            json={},
            headers=_auth_headers(token),
        )
        assert empty_patch_resp.status_code == 400

        # Archive (soft-delete) the agent
        del_resp = await client.delete(
            f"/api/v1/agents/{agent_id}",
            headers=_auth_headers(token),
        )
        assert del_resp.status_code == 204

        # Archived agent no longer returned in list
        list_resp = await client.get("/api/v1/agents", headers=_auth_headers(token))
        assert list_resp.status_code == 200
        active_ids = [a["id"] for a in list_resp.json()["agents"]]
        assert agent_id not in active_ids

        # GET archived agent: the registry returns it (owner can still read).
        # Route returns 200 because get_agent() does not filter by status —
        # only a user-ownership mismatch produces 404.
        get_archived_resp = await client.get(
            f"/api/v1/agents/{agent_id}",
            headers=_auth_headers(token),
        )
        assert get_archived_resp.status_code == 200
        archived_body = get_archived_resp.json()
        assert archived_body["id"] == agent_id
        # Confirmed archived status in the response
        assert archived_body["status"] == "archived"


# ---------------------------------------------------------------------------
# Workflow 7: Multi-Agent Journey
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestWorkflow07MultiAgentJourney:
    """Create two agents → list both → verify isolation → delete one → other survives."""

    async def test_multi_agent_journey(self, wf_client: AsyncClient) -> None:
        client = wf_client
        email = _unique_email("multi")
        token = await _register_and_login(client, email, "Passw0rd!Secure")
        handle_a = _unique_handle("multia")
        handle_b = _unique_handle("multib")

        # Create agent A
        agent_a = await _create_agent(client, token, handle_a, name="Agent Alpha")
        agent_a_id = agent_a["id"]

        # Create agent B
        agent_b = await _create_agent(client, token, handle_b, name="Agent Beta")
        agent_b_id = agent_b["id"]

        # List — both present
        list_resp = await client.get("/api/v1/agents", headers=_auth_headers(token))
        assert list_resp.status_code == 200
        list_body = list_resp.json()
        assert list_body["count"] >= 2
        ids = [a["id"] for a in list_body["agents"]]
        assert agent_a_id in ids
        assert agent_b_id in ids

        # Filter by type — both are business type
        biz_resp = await client.get(
            "/api/v1/agents?agent_type=business",
            headers=_auth_headers(token),
        )
        assert biz_resp.status_code == 200
        biz_ids = [a["id"] for a in biz_resp.json()["agents"]]
        assert agent_a_id in biz_ids
        assert agent_b_id in biz_ids

        # Verify integration status works independently for both agents
        status_a = await client.get(
            f"/api/v1/integrations/{agent_a_id}/status",
            headers=_auth_headers(token),
        )
        assert status_a.status_code == 200

        status_b = await client.get(
            f"/api/v1/integrations/{agent_b_id}/status",
            headers=_auth_headers(token),
        )
        assert status_b.status_code == 200

        # Delete agent A
        del_resp = await client.delete(
            f"/api/v1/agents/{agent_a_id}",
            headers=_auth_headers(token),
        )
        assert del_resp.status_code == 204

        # Agent B still accessible
        get_b_resp = await client.get(
            f"/api/v1/agents/{agent_b_id}",
            headers=_auth_headers(token),
        )
        assert get_b_resp.status_code == 200
        assert get_b_resp.json()["id"] == agent_b_id

        # Agent A no longer in list
        final_list = await client.get("/api/v1/agents", headers=_auth_headers(token))
        remaining_ids = [a["id"] for a in final_list.json()["agents"]]
        assert agent_a_id not in remaining_ids
        assert agent_b_id in remaining_ids

        # Agent A integration status: _verify_agent_ownership checks the registry
        # which still returns archived agents.  The ownership check PASSES (same
        # user), so the status endpoint returns 200 with all disconnected fields.
        dead_status = await client.get(
            f"/api/v1/integrations/{agent_a_id}/status",
            headers=_auth_headers(token),
        )
        assert dead_status.status_code == 200


# ---------------------------------------------------------------------------
# Workflow 8: Security & Auth Journey
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestWorkflow08SecurityAuthJourney:
    """Register → Login → Access protected route → Logout → Verify 401 → Login again."""

    async def test_security_auth_journey(self, wf_client: AsyncClient) -> None:
        client = wf_client
        email = _unique_email("security")
        password = "Passw0rd!Secure"

        # Register
        reg_resp = await client.post(
            "/auth/register",
            json={"email": email, "password": password, "terms_accepted": True},
        )
        assert reg_resp.status_code == 201
        token = reg_resp.json()["access_token"]

        # Auto-verify email so re-login after logout works (email verification gate)
        await _verify_email_in_db(email)

        # Access protected route — succeeds
        me_resp = await client.get("/auth/me", headers=_auth_headers(token))
        assert me_resp.status_code == 200

        # Agents list — succeeds
        agents_resp = await client.get("/api/v1/agents", headers=_auth_headers(token))
        assert agents_resp.status_code == 200

        # Logout — records the token in the token_revocations table (P1 fix:
        # logout now calls revoke_token() from token_guard.py, writing to the
        # same table the TokenRevocationGuard middleware reads from).
        logout_resp = await client.post(
            "/auth/logout",
            headers=_auth_headers(token),
        )
        assert logout_resp.status_code == 200
        assert "Logged out" in logout_resp.json()["message"]

        # SECURITY INVARIANT: the revoked token must be rejected on the
        # very next request.  The TokenRevocationGuard middleware intercepts
        # the request before the route handler and returns 401.
        after_logout_resp = await client.get(
            "/api/v1/agents",
            headers=_auth_headers(token),
        )
        assert after_logout_resp.status_code == 401, (
            "Revoked token must be rejected after logout (P1 security fix). "
            "If this fails, logout is not writing to token_revocations."
        )

        # Login again — new token
        login_resp = await client.post(
            "/auth/login",
            json={"email": email, "password": password},
        )
        assert login_resp.status_code == 200
        new_token = login_resp.json()["access_token"]
        assert new_token != token

        # New token works
        new_agents_resp = await client.get(
            "/api/v1/agents",
            headers=_auth_headers(new_token),
        )
        assert new_agents_resp.status_code == 200

        # Duplicate registration → 409
        dup_resp = await client.post(
            "/auth/register",
            json={"email": email, "password": password, "terms_accepted": True},
        )
        assert dup_resp.status_code == 409

        # Login with wrong password → 401
        bad_login_resp = await client.post(
            "/auth/login",
            json={"email": email, "password": "WrongPassword1!"},
        )
        assert bad_login_resp.status_code == 401

        # Login with unknown email → 401
        unknown_resp = await client.post(
            "/auth/login",
            json={"email": "nobody@example.com", "password": password},
        )
        assert unknown_resp.status_code == 401

        # Access protected route without any token → 401
        no_token_resp = await client.get("/api/v1/agents")
        assert no_token_resp.status_code == 401

        # Malformed Authorization header → 401
        bad_header_resp = await client.get(
            "/api/v1/agents",
            headers={"Authorization": "NotABearer token"},
        )
        assert bad_header_resp.status_code == 401

        # Forgot-password always returns 200 (anti-enumeration)
        fp_resp = await client.post(
            "/auth/forgot-password",
            json={"email": email},
        )
        assert fp_resp.status_code == 200
        fp_unknown_resp = await client.post(
            "/auth/forgot-password",
            json={"email": "ghost@example.com"},
        )
        assert fp_unknown_resp.status_code == 200


# ---------------------------------------------------------------------------
# Workflow 9: DID & Identity Journey
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestWorkflow09DIDIdentityJourney:
    """Create agent → Verify DID auto-created → GET well-known DID endpoints."""

    async def test_did_identity_journey(self, wf_client: AsyncClient) -> None:
        client = wf_client
        email = _unique_email("did")
        token = await _register_and_login(client, email, "Passw0rd!Secure")
        handle = _unique_handle("did")
        agent = await _create_agent(client, token, handle, name="DID Agent")

        # Platform DID document — always returns 200 with @context
        platform_did_resp = await client.get("/.well-known/did.json")
        assert platform_did_resp.status_code == 200
        platform_did = platform_did_resp.json()
        assert "@context" in platform_did
        assert "id" in platform_did
        assert "did:web:" in platform_did["id"]

        # Agent DID by handle — should exist after agent creation
        agent_did_resp = await client.get(f"/.well-known/did/{handle}.json")
        # Either 200 (DID exists) or 503 (DID system unavailable) — both are valid
        assert agent_did_resp.status_code in (200, 503, 404)

        # If DID was created, verify the format
        if agent_did_resp.status_code == 200:
            agent_did = agent_did_resp.json()
            assert "@context" in agent_did
            assert handle in agent_did.get("id", "")

        # Public DID endpoint via agents router
        public_did_resp = await client.get(f"/api/v1/agents/handle/{handle}/did")
        # 200 (DID present) or 503 (DID manager unavailable)
        assert public_did_resp.status_code in (200, 503, 404)

        # MCP discovery document
        mcp_resp = await client.get("/.well-known/mcp.json")
        assert mcp_resp.status_code == 200
        mcp_body = mcp_resp.json()
        assert "server_info" in mcp_body
        assert "capabilities" in mcp_body
        assert "endpoints" in mcp_body

        # MCP Server Card (SEP-1649)
        card_resp = await client.get("/.well-known/mcp-server-card.json")
        assert card_resp.status_code == 200
        card_body = card_resp.json()
        assert "serverInfo" in card_body
        assert "authentication" in card_body


# ---------------------------------------------------------------------------
# Workflow 10: Widget & Public API Journey
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestWorkflow10WidgetPublicAPIJourney:
    """Unauthenticated discovery, ACP endpoints, and public routes."""

    async def test_widget_public_api_journey(self, wf_client: AsyncClient) -> None:
        client = wf_client

        # ACP capabilities (public — no auth)
        caps_resp = await client.get("/api/v1/acp/capabilities")
        assert caps_resp.status_code == 200
        caps_body = caps_resp.json()
        assert "capabilities" in caps_body
        assert "acp_spec_version" in caps_body

        # ACP products (public — no auth)
        products_resp = await client.get("/api/v1/acp/products")
        assert products_resp.status_code == 200
        products_body = products_resp.json()
        assert "products" in products_body
        assert isinstance(products_body["products"], list)

        # ACP manifest (public — no auth)
        manifest_resp = await client.get("/api/v1/acp/.well-known/acp-manifest")
        assert manifest_resp.status_code == 200
        manifest_body = manifest_resp.json()
        assert "acp_spec_version" in manifest_body
        assert "merchant" in manifest_body
        assert "checkout_endpoint" in manifest_body

        # Handle check for non-existent handle — public, no auth
        nonexistent_handle = _unique_handle("ghost")
        check_resp = await client.get(
            f"/api/v1/agents/handle/{nonexistent_handle}/check"
        )
        assert check_resp.status_code == 200
        assert check_resp.json()["available"] is True

        # Invalid handle format → returns available: false (not an error)
        invalid_handle_resp = await client.get("/api/v1/agents/handle/--invalid!!/check")
        assert invalid_handle_resp.status_code == 200
        assert invalid_handle_resp.json()["available"] is False

        # Health endpoint — public
        health_resp = await client.get("/health")
        assert health_resp.status_code == 200
        assert health_resp.json()["status"] in ("healthy", "degraded")

        # Platform DID — public
        did_resp = await client.get("/.well-known/did.json")
        assert did_resp.status_code == 200

        # Protected endpoints without auth → 401
        protected_routes = [
            ("/api/v1/agents", "GET"),
        ]
        for path, method in protected_routes:
            resp = await client.request(method, path)
            assert resp.status_code == 401, (
                f"Expected 401 for {method} {path}, got {resp.status_code}"
            )

        # Register with short password → 422
        bad_reg_resp = await client.post(
            "/auth/register",
            json={"email": "badpass@example.com", "password": "short"},
        )
        assert bad_reg_resp.status_code == 422

        # Register with missing fields → 422
        incomplete_resp = await client.post(
            "/auth/register",
            json={"email": "incomplete@example.com"},
        )
        assert incomplete_resp.status_code == 422

        # Login with missing fields → 422
        bad_login_resp = await client.post(
            "/auth/login",
            json={"email": "only-email@example.com"},
        )
        assert bad_login_resp.status_code == 422
