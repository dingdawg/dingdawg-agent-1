"""API tests for per-agent email (SendGrid) and SMS (Twilio) integration routes.

Tests cover:
- POST /api/v1/integrations/{agent_id}/email  — configure (201, 404, 401, 422)
- GET  /api/v1/integrations/{agent_id}/email  — status (200, 404, 401)
- DELETE /api/v1/integrations/{agent_id}/email — disconnect (200, 404, 401)

- POST /api/v1/integrations/{agent_id}/sms   — configure (201, 404, 401, 422)
- GET  /api/v1/integrations/{agent_id}/sms   — status (200, 404, 401)
- DELETE /api/v1/integrations/{agent_id}/sms — disconnect (200, 404, 401)

- GET  /api/v1/integrations/{agent_id}/status — combined status (200, 404, 401)

Security: API key and Twilio credentials must NOT appear in GET responses.
Ownership: another user's agent must return 404.
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

_SECRET = "test-secret-notify-integrations-suite"
_USER_A = "user-notify-alpha"
_USER_B = "user-notify-beta"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(user_id: str, email: str = "notify@example.com") -> str:
    return _create_token(user_id=user_id, email=email, secret_key=_SECRET)


def _auth(user_id: str = _USER_A) -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_token(user_id)}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(tmp_path):
    """Async HTTP client with full app lifespan."""
    db_file = str(tmp_path / "test_notify_integrations.db")

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


async def _create_agent(client: AsyncClient, user_id: str = _USER_A, handle: str = "testnotify") -> str:
    """Create an agent and return its agent_id."""
    resp = await client.post(
        "/api/v1/agents",
        json={"handle": handle, "name": "Notify Test Agent", "agent_type": "business"},
        headers=_auth(user_id),
    )
    assert resp.status_code == 201, f"Agent creation failed: {resp.text}"
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# Email integration — POST /api/v1/integrations/{agent_id}/email
# ---------------------------------------------------------------------------


class TestConfigureEmail:
    """Tests for POST /api/v1/integrations/{agent_id}/email."""

    async def test_configure_email_returns_201(self, client) -> None:
        agent_id = await _create_agent(client)
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/email",
            json={"api_key": "SG.fake-key", "from_email": "hello@example.com", "from_name": "My Agent"},
            headers=_auth(),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["connected"] is True
        assert body["from_email"] == "hello@example.com"
        assert body["agent_id"] == agent_id

    async def test_configure_email_does_not_expose_api_key(self, client) -> None:
        agent_id = await _create_agent(client, handle="testnotify2")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/email",
            json={"api_key": "SG.supersecret", "from_email": "a@b.com"},
            headers=_auth(),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "api_key" not in body
        assert "SG.supersecret" not in str(body)

    async def test_configure_email_upserts_existing_config(self, client) -> None:
        agent_id = await _create_agent(client, handle="testnotify3")
        await client.post(
            f"/api/v1/integrations/{agent_id}/email",
            json={"api_key": "SG.key-v1", "from_email": "old@example.com"},
            headers=_auth(),
        )
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/email",
            json={"api_key": "SG.key-v2", "from_email": "new@example.com"},
            headers=_auth(),
        )
        assert resp.status_code == 201
        assert resp.json()["from_email"] == "new@example.com"

    async def test_configure_email_requires_auth(self, client) -> None:
        agent_id = await _create_agent(client, handle="testnotify4")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/email",
            json={"api_key": "SG.key", "from_email": "x@y.com"},
        )
        assert resp.status_code == 401

    async def test_configure_email_missing_api_key_returns_422(self, client) -> None:
        agent_id = await _create_agent(client, handle="testnotify5")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/email",
            json={"from_email": "x@y.com"},
            headers=_auth(),
        )
        assert resp.status_code == 422

    async def test_configure_email_missing_from_email_returns_422(self, client) -> None:
        agent_id = await _create_agent(client, handle="testnotify6")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/email",
            json={"api_key": "SG.key"},
            headers=_auth(),
        )
        assert resp.status_code == 422

    async def test_configure_email_unknown_agent_returns_404(self, client) -> None:
        resp = await client.post(
            "/api/v1/integrations/no-such-agent-id/email",
            json={"api_key": "SG.key", "from_email": "x@y.com"},
            headers=_auth(),
        )
        assert resp.status_code == 404

    async def test_configure_email_other_users_agent_returns_404(self, client) -> None:
        agent_id = await _create_agent(client, user_id=_USER_B, handle="testnotify7")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/email",
            json={"api_key": "SG.key", "from_email": "x@y.com"},
            headers=_auth(_USER_A),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Email integration — GET /api/v1/integrations/{agent_id}/email
# ---------------------------------------------------------------------------


class TestGetEmailConfig:
    """Tests for GET /api/v1/integrations/{agent_id}/email."""

    async def test_get_email_not_configured_returns_connected_false(self, client) -> None:
        agent_id = await _create_agent(client, handle="testnotify8")
        resp = await client.get(
            f"/api/v1/integrations/{agent_id}/email",
            headers=_auth(),
        )
        assert resp.status_code == 200
        assert resp.json()["connected"] is False

    async def test_get_email_after_configure_returns_connected_true(self, client) -> None:
        agent_id = await _create_agent(client, handle="testnotify9")
        await client.post(
            f"/api/v1/integrations/{agent_id}/email",
            json={"api_key": "SG.key", "from_email": "info@store.com", "from_name": "Store"},
            headers=_auth(),
        )
        resp = await client.get(
            f"/api/v1/integrations/{agent_id}/email",
            headers=_auth(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["connected"] is True
        assert body["from_email"] == "info@store.com"
        assert body["from_name"] == "Store"

    async def test_get_email_never_exposes_api_key(self, client) -> None:
        agent_id = await _create_agent(client, handle="testnotify10")
        await client.post(
            f"/api/v1/integrations/{agent_id}/email",
            json={"api_key": "SG.topsecret-key-abc", "from_email": "a@b.com"},
            headers=_auth(),
        )
        resp = await client.get(
            f"/api/v1/integrations/{agent_id}/email",
            headers=_auth(),
        )
        assert resp.status_code == 200
        body_str = str(resp.json())
        assert "topsecret-key-abc" not in body_str
        assert "api_key" not in body_str

    async def test_get_email_requires_auth(self, client) -> None:
        agent_id = await _create_agent(client, handle="testnotify11")
        resp = await client.get(f"/api/v1/integrations/{agent_id}/email")
        assert resp.status_code == 401

    async def test_get_email_unknown_agent_returns_404(self, client) -> None:
        resp = await client.get(
            "/api/v1/integrations/no-such-agent/email",
            headers=_auth(),
        )
        assert resp.status_code == 404

    async def test_get_email_other_users_agent_returns_404(self, client) -> None:
        agent_id = await _create_agent(client, user_id=_USER_B, handle="testnotify12")
        resp = await client.get(
            f"/api/v1/integrations/{agent_id}/email",
            headers=_auth(_USER_A),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Email integration — DELETE /api/v1/integrations/{agent_id}/email
# ---------------------------------------------------------------------------


class TestDisconnectEmail:
    """Tests for DELETE /api/v1/integrations/{agent_id}/email."""

    async def test_disconnect_email_returns_200(self, client) -> None:
        agent_id = await _create_agent(client, handle="testnotify13")
        await client.post(
            f"/api/v1/integrations/{agent_id}/email",
            json={"api_key": "SG.key", "from_email": "a@b.com"},
            headers=_auth(),
        )
        resp = await client.delete(
            f"/api/v1/integrations/{agent_id}/email",
            headers=_auth(),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "disconnected"

    async def test_disconnect_email_idempotent(self, client) -> None:
        agent_id = await _create_agent(client, handle="testnotify14")
        # Disconnect without ever configuring — should still return 200
        resp = await client.delete(
            f"/api/v1/integrations/{agent_id}/email",
            headers=_auth(),
        )
        assert resp.status_code == 200

    async def test_disconnect_email_clears_config(self, client) -> None:
        agent_id = await _create_agent(client, handle="testnotify15")
        await client.post(
            f"/api/v1/integrations/{agent_id}/email",
            json={"api_key": "SG.key", "from_email": "a@b.com"},
            headers=_auth(),
        )
        await client.delete(
            f"/api/v1/integrations/{agent_id}/email",
            headers=_auth(),
        )
        get_resp = await client.get(
            f"/api/v1/integrations/{agent_id}/email",
            headers=_auth(),
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["connected"] is False

    async def test_disconnect_email_requires_auth(self, client) -> None:
        agent_id = await _create_agent(client, handle="testnotify16")
        resp = await client.delete(f"/api/v1/integrations/{agent_id}/email")
        assert resp.status_code == 401

    async def test_disconnect_email_unknown_agent_returns_404(self, client) -> None:
        resp = await client.delete(
            "/api/v1/integrations/no-such-agent/email",
            headers=_auth(),
        )
        assert resp.status_code == 404

    async def test_disconnect_email_other_users_agent_returns_404(self, client) -> None:
        agent_id = await _create_agent(client, user_id=_USER_B, handle="testnotify17")
        resp = await client.delete(
            f"/api/v1/integrations/{agent_id}/email",
            headers=_auth(_USER_A),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# SMS integration — POST /api/v1/integrations/{agent_id}/sms
# ---------------------------------------------------------------------------


class TestConfigureSms:
    """Tests for POST /api/v1/integrations/{agent_id}/sms."""

    async def test_configure_sms_returns_201(self, client) -> None:
        agent_id = await _create_agent(client, handle="testsms1")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/sms",
            json={
                "account_sid": "ACfakeaccount",
                "auth_token": "faketokenvalue",
                "from_number": "+15550001234",
            },
            headers=_auth(),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["connected"] is True
        assert body["from_number"] == "+15550001234"
        assert body["agent_id"] == agent_id

    async def test_configure_sms_does_not_expose_credentials(self, client) -> None:
        agent_id = await _create_agent(client, handle="testsms2")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/sms",
            json={
                "account_sid": "ACsupersecretSID",
                "auth_token": "supersecrettoken",
                "from_number": "+15550001111",
            },
            headers=_auth(),
        )
        assert resp.status_code == 201
        body_str = str(resp.json())
        assert "ACsupersecretSID" not in body_str
        assert "supersecrettoken" not in body_str
        assert "account_sid" not in body_str
        assert "auth_token" not in body_str

    async def test_configure_sms_upserts_existing_config(self, client) -> None:
        agent_id = await _create_agent(client, handle="testsms3")
        await client.post(
            f"/api/v1/integrations/{agent_id}/sms",
            json={"account_sid": "AC1", "auth_token": "tok1", "from_number": "+15550000001"},
            headers=_auth(),
        )
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/sms",
            json={"account_sid": "AC2", "auth_token": "tok2", "from_number": "+15550000002"},
            headers=_auth(),
        )
        assert resp.status_code == 201
        assert resp.json()["from_number"] == "+15550000002"

    async def test_configure_sms_requires_auth(self, client) -> None:
        agent_id = await _create_agent(client, handle="testsms4")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/sms",
            json={"account_sid": "AC1", "auth_token": "tok", "from_number": "+1555"},
        )
        assert resp.status_code == 401

    async def test_configure_sms_missing_account_sid_returns_422(self, client) -> None:
        agent_id = await _create_agent(client, handle="testsms5")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/sms",
            json={"auth_token": "tok", "from_number": "+1555"},
            headers=_auth(),
        )
        assert resp.status_code == 422

    async def test_configure_sms_missing_from_number_returns_422(self, client) -> None:
        agent_id = await _create_agent(client, handle="testsms6")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/sms",
            json={"account_sid": "AC1", "auth_token": "tok"},
            headers=_auth(),
        )
        assert resp.status_code == 422

    async def test_configure_sms_unknown_agent_returns_404(self, client) -> None:
        resp = await client.post(
            "/api/v1/integrations/no-such-agent/sms",
            json={"account_sid": "AC1", "auth_token": "tok", "from_number": "+1555"},
            headers=_auth(),
        )
        assert resp.status_code == 404

    async def test_configure_sms_other_users_agent_returns_404(self, client) -> None:
        agent_id = await _create_agent(client, user_id=_USER_B, handle="testsms7")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/sms",
            json={"account_sid": "AC1", "auth_token": "tok", "from_number": "+1555"},
            headers=_auth(_USER_A),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# SMS integration — GET /api/v1/integrations/{agent_id}/sms
# ---------------------------------------------------------------------------


class TestGetSmsConfig:
    """Tests for GET /api/v1/integrations/{agent_id}/sms."""

    async def test_get_sms_not_configured_returns_connected_false(self, client) -> None:
        agent_id = await _create_agent(client, handle="testsms8")
        resp = await client.get(
            f"/api/v1/integrations/{agent_id}/sms",
            headers=_auth(),
        )
        assert resp.status_code == 200
        assert resp.json()["connected"] is False

    async def test_get_sms_after_configure_returns_connected_true(self, client) -> None:
        agent_id = await _create_agent(client, handle="testsms9")
        await client.post(
            f"/api/v1/integrations/{agent_id}/sms",
            json={"account_sid": "AC1", "auth_token": "tok", "from_number": "+15559876543"},
            headers=_auth(),
        )
        resp = await client.get(
            f"/api/v1/integrations/{agent_id}/sms",
            headers=_auth(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["connected"] is True
        assert body["from_number"] == "+15559876543"

    async def test_get_sms_never_exposes_credentials(self, client) -> None:
        agent_id = await _create_agent(client, handle="testsms10")
        await client.post(
            f"/api/v1/integrations/{agent_id}/sms",
            json={
                "account_sid": "ACsecretSIDvalue",
                "auth_token": "secretTokenValue99",
                "from_number": "+15559999999",
            },
            headers=_auth(),
        )
        resp = await client.get(
            f"/api/v1/integrations/{agent_id}/sms",
            headers=_auth(),
        )
        assert resp.status_code == 200
        body_str = str(resp.json())
        assert "ACsecretSIDvalue" not in body_str
        assert "secretTokenValue99" not in body_str
        assert "auth_token" not in body_str
        assert "account_sid" not in body_str

    async def test_get_sms_requires_auth(self, client) -> None:
        agent_id = await _create_agent(client, handle="testsms11")
        resp = await client.get(f"/api/v1/integrations/{agent_id}/sms")
        assert resp.status_code == 401

    async def test_get_sms_unknown_agent_returns_404(self, client) -> None:
        resp = await client.get(
            "/api/v1/integrations/no-such-agent/sms",
            headers=_auth(),
        )
        assert resp.status_code == 404

    async def test_get_sms_other_users_agent_returns_404(self, client) -> None:
        agent_id = await _create_agent(client, user_id=_USER_B, handle="testsms12")
        resp = await client.get(
            f"/api/v1/integrations/{agent_id}/sms",
            headers=_auth(_USER_A),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# SMS integration — DELETE /api/v1/integrations/{agent_id}/sms
# ---------------------------------------------------------------------------


class TestDisconnectSms:
    """Tests for DELETE /api/v1/integrations/{agent_id}/sms."""

    async def test_disconnect_sms_returns_200(self, client) -> None:
        agent_id = await _create_agent(client, handle="testsms13")
        await client.post(
            f"/api/v1/integrations/{agent_id}/sms",
            json={"account_sid": "AC1", "auth_token": "tok", "from_number": "+1555"},
            headers=_auth(),
        )
        resp = await client.delete(
            f"/api/v1/integrations/{agent_id}/sms",
            headers=_auth(),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "disconnected"

    async def test_disconnect_sms_idempotent(self, client) -> None:
        agent_id = await _create_agent(client, handle="testsms14")
        # Disconnect without ever configuring — should still return 200
        resp = await client.delete(
            f"/api/v1/integrations/{agent_id}/sms",
            headers=_auth(),
        )
        assert resp.status_code == 200

    async def test_disconnect_sms_clears_config(self, client) -> None:
        agent_id = await _create_agent(client, handle="testsms15")
        await client.post(
            f"/api/v1/integrations/{agent_id}/sms",
            json={"account_sid": "AC1", "auth_token": "tok", "from_number": "+1555"},
            headers=_auth(),
        )
        await client.delete(
            f"/api/v1/integrations/{agent_id}/sms",
            headers=_auth(),
        )
        get_resp = await client.get(
            f"/api/v1/integrations/{agent_id}/sms",
            headers=_auth(),
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["connected"] is False

    async def test_disconnect_sms_requires_auth(self, client) -> None:
        agent_id = await _create_agent(client, handle="testsms16")
        resp = await client.delete(f"/api/v1/integrations/{agent_id}/sms")
        assert resp.status_code == 401

    async def test_disconnect_sms_unknown_agent_returns_404(self, client) -> None:
        resp = await client.delete(
            "/api/v1/integrations/no-such-agent/sms",
            headers=_auth(),
        )
        assert resp.status_code == 404

    async def test_disconnect_sms_other_users_agent_returns_404(self, client) -> None:
        agent_id = await _create_agent(client, user_id=_USER_B, handle="testsms17")
        resp = await client.delete(
            f"/api/v1/integrations/{agent_id}/sms",
            headers=_auth(_USER_A),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Combined status — GET /api/v1/integrations/{agent_id}/status
# ---------------------------------------------------------------------------


class TestGetIntegrationStatus:
    """Tests for GET /api/v1/integrations/{agent_id}/status."""

    async def test_status_unconfigured_agent_returns_all_false(self, client) -> None:
        agent_id = await _create_agent(client, handle="teststatus1")
        resp = await client.get(
            f"/api/v1/integrations/{agent_id}/status",
            headers=_auth(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["agent_id"] == agent_id
        assert body["email"]["connected"] is False
        assert body["sms"]["connected"] is False
        assert body["calendar"]["connected"] is False
        assert body["voice"]["connected"] is False

    async def test_status_after_email_configure_shows_email_connected(self, client) -> None:
        agent_id = await _create_agent(client, handle="teststatus2")
        await client.post(
            f"/api/v1/integrations/{agent_id}/email",
            json={"api_key": "SG.key", "from_email": "test@example.com"},
            headers=_auth(),
        )
        resp = await client.get(
            f"/api/v1/integrations/{agent_id}/status",
            headers=_auth(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"]["connected"] is True
        assert body["email"]["from_email"] == "test@example.com"
        assert body["sms"]["connected"] is False

    async def test_status_after_sms_configure_shows_sms_connected(self, client) -> None:
        agent_id = await _create_agent(client, handle="teststatus3")
        await client.post(
            f"/api/v1/integrations/{agent_id}/sms",
            json={"account_sid": "AC1", "auth_token": "tok", "from_number": "+15550001234"},
            headers=_auth(),
        )
        resp = await client.get(
            f"/api/v1/integrations/{agent_id}/status",
            headers=_auth(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["sms"]["connected"] is True
        assert body["sms"]["from_number"] == "+15550001234"
        assert body["email"]["connected"] is False

    async def test_status_never_exposes_credentials(self, client) -> None:
        agent_id = await _create_agent(client, handle="teststatus4")
        await client.post(
            f"/api/v1/integrations/{agent_id}/email",
            json={"api_key": "SG.secretkey999", "from_email": "a@b.com"},
            headers=_auth(),
        )
        await client.post(
            f"/api/v1/integrations/{agent_id}/sms",
            json={"account_sid": "ACsecretSID", "auth_token": "secretAuthToken", "from_number": "+1555"},
            headers=_auth(),
        )
        resp = await client.get(
            f"/api/v1/integrations/{agent_id}/status",
            headers=_auth(),
        )
        assert resp.status_code == 200
        body_str = str(resp.json())
        assert "secretkey999" not in body_str
        assert "ACsecretSID" not in body_str
        assert "secretAuthToken" not in body_str
        assert "api_key" not in body_str
        assert "auth_token" not in body_str
        assert "account_sid" not in body_str

    async def test_status_requires_auth(self, client) -> None:
        agent_id = await _create_agent(client, handle="teststatus5")
        resp = await client.get(f"/api/v1/integrations/{agent_id}/status")
        assert resp.status_code == 401

    async def test_status_unknown_agent_returns_404(self, client) -> None:
        resp = await client.get(
            "/api/v1/integrations/no-such-agent/status",
            headers=_auth(),
        )
        assert resp.status_code == 404

    async def test_status_other_users_agent_returns_404(self, client) -> None:
        agent_id = await _create_agent(client, user_id=_USER_B, handle="teststatus6")
        resp = await client.get(
            f"/api/v1/integrations/{agent_id}/status",
            headers=_auth(_USER_A),
        )
        assert resp.status_code == 404
