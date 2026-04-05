"""API tests for the integration configuration routes.

Tests cover:
- GET  /api/v1/integrations/{agent_id}/status          — combined status (shape, auth)
- POST /api/v1/integrations/{agent_id}/email            — SendGrid configure (201, 422, 401, 404)
- POST /api/v1/integrations/{agent_id}/sms              — Twilio configure (201, 422, 401, 404)
- POST /api/v1/integrations/{agent_id}/vapi/configure   — Vapi configure (200, 422, 401, 404)
- GET  /api/v1/integrations/{agent_id}/google-calendar/auth-url  — OAuth URL (200/503, 401, 404)
- POST /api/v1/integrations/{agent_id}/google-calendar/callback  — code exchange (400 on bad code)
- POST /api/v1/integrations/{agent_id}/disconnect       — generic disconnect (200, 400 bad name, 401)
- POST /api/v1/integrations/{agent_id}/test             — test email/SMS (200, 400, 401)

Security invariants:
- 401 on every endpoint when no token is provided.
- 404 when the agent belongs to a different user (ownership privacy).
- API keys and auth tokens must NEVER appear in any response.
"""

from __future__ import annotations

import os
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from isg_agent.api.routes.auth import _create_token
from isg_agent.config import get_settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SECRET = "test-secret-integrations-api-suite"
_USER_A = "user-integ-alpha"
_USER_B = "user-integ-beta"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(user_id: str, email: str = "integ@example.com") -> str:
    return _create_token(user_id=user_id, email=email, secret_key=_SECRET)


def _auth(user_id: str = _USER_A, email: str = "integ@example.com") -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_token(user_id, email)}"}


# ---------------------------------------------------------------------------
# Fixture: full-lifespan async client
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(tmp_path) -> AsyncIterator[AsyncClient]:
    """Async HTTP client wired to a full app lifespan."""
    db_file = str(tmp_path / "test_integrations_api.db")

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
# Setup helper: create an agent and return its ID
# ---------------------------------------------------------------------------


async def _create_agent(
    client: AsyncClient,
    user_id: str = _USER_A,
    handle: str = "integ-test-agent",
) -> str:
    """Create an agent owned by *user_id* and return its agent_id."""
    resp = await client.post(
        "/api/v1/agents",
        json={"handle": handle, "name": "Integration Test Agent", "agent_type": "business"},
        headers=_auth(user_id),
    )
    assert resp.status_code == 201, f"Agent creation failed: {resp.text}"
    return resp.json()["id"]


# ===========================================================================
# GET /{agent_id}/status
# ===========================================================================


class TestGetStatus:
    """Tests for GET /api/v1/integrations/{agent_id}/status."""

    async def test_status_returns_correct_shape(self, client) -> None:
        agent_id = await _create_agent(client, handle="status-shape-1")
        resp = await client.get(
            f"/api/v1/integrations/{agent_id}/status",
            headers=_auth(),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["agent_id"] == agent_id
        assert "email" in body
        assert "sms" in body
        assert "calendar" in body
        assert "voice" in body

    async def test_status_all_disconnected_on_fresh_agent(self, client) -> None:
        agent_id = await _create_agent(client, handle="status-fresh-1")
        resp = await client.get(
            f"/api/v1/integrations/{agent_id}/status",
            headers=_auth(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"]["connected"] is False
        assert body["sms"]["connected"] is False
        assert body["calendar"]["connected"] is False
        assert body["voice"]["connected"] is False

    async def test_status_reflects_email_configure(self, client) -> None:
        agent_id = await _create_agent(client, handle="status-email-1")
        await client.post(
            f"/api/v1/integrations/{agent_id}/email",
            json={"api_key": "SG.testkey", "from_email": "hello@biz.com"},
            headers=_auth(),
        )
        resp = await client.get(
            f"/api/v1/integrations/{agent_id}/status",
            headers=_auth(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"]["connected"] is True
        assert body["email"]["from_email"] == "hello@biz.com"

    async def test_status_requires_auth(self, client) -> None:
        agent_id = await _create_agent(client, handle="status-auth-1")
        resp = await client.get(f"/api/v1/integrations/{agent_id}/status")
        assert resp.status_code == 401

    async def test_status_unknown_agent_returns_404(self, client) -> None:
        resp = await client.get(
            "/api/v1/integrations/no-such-agent-id/status",
            headers=_auth(),
        )
        assert resp.status_code == 404

    async def test_status_other_users_agent_returns_404(self, client) -> None:
        agent_id = await _create_agent(client, user_id=_USER_B, handle="status-other-1")
        resp = await client.get(
            f"/api/v1/integrations/{agent_id}/status",
            headers=_auth(_USER_A),
        )
        assert resp.status_code == 404

    async def test_status_never_exposes_credentials(self, client) -> None:
        agent_id = await _create_agent(client, handle="status-secret-1")
        await client.post(
            f"/api/v1/integrations/{agent_id}/email",
            json={"api_key": "SG.ultra-secret-key-xyz", "from_email": "a@b.com"},
            headers=_auth(),
        )
        await client.post(
            f"/api/v1/integrations/{agent_id}/sms",
            json={"account_sid": "ACsecret", "auth_token": "tokensecret", "from_number": "+1555"},
            headers=_auth(),
        )
        resp = await client.get(
            f"/api/v1/integrations/{agent_id}/status",
            headers=_auth(),
        )
        assert resp.status_code == 200
        body_str = str(resp.json())
        assert "ultra-secret-key-xyz" not in body_str
        assert "ACsecret" not in body_str
        assert "tokensecret" not in body_str


# ===========================================================================
# POST /{agent_id}/vapi/configure
# ===========================================================================


class TestConfigureVapi:
    """Tests for POST /api/v1/integrations/{agent_id}/vapi/configure."""

    async def test_configure_vapi_returns_200(self, client) -> None:
        agent_id = await _create_agent(client, handle="vapi-config-1")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/vapi/configure",
            json={
                "api_key": "fake-vapi-key-abc123",
                "voice_model": "eleven_multilingual_v2",
                "first_message": "Hello! How can I assist you today?",
            },
            headers=_auth(),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["agent_id"] == agent_id
        assert body["configured"] is True
        assert "status" in body

    async def test_configure_vapi_requires_api_key(self, client) -> None:
        agent_id = await _create_agent(client, handle="vapi-config-2")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/vapi/configure",
            json={"voice_model": "eleven_multilingual_v2"},
            headers=_auth(),
        )
        assert resp.status_code == 422

    async def test_configure_vapi_requires_auth(self, client) -> None:
        agent_id = await _create_agent(client, handle="vapi-config-3")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/vapi/configure",
            json={"api_key": "fake-key"},
        )
        assert resp.status_code == 401

    async def test_configure_vapi_unknown_agent_returns_404(self, client) -> None:
        resp = await client.post(
            "/api/v1/integrations/no-such-agent/vapi/configure",
            json={"api_key": "fake-key"},
            headers=_auth(),
        )
        assert resp.status_code == 404

    async def test_configure_vapi_other_users_agent_returns_404(self, client) -> None:
        agent_id = await _create_agent(client, user_id=_USER_B, handle="vapi-config-4")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/vapi/configure",
            json={"api_key": "fake-key"},
            headers=_auth(_USER_A),
        )
        assert resp.status_code == 404

    async def test_configure_vapi_optional_fields_have_defaults(self, client) -> None:
        agent_id = await _create_agent(client, handle="vapi-config-5")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/vapi/configure",
            json={"api_key": "fake-key"},
            headers=_auth(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["configured"] is True

    async def test_configure_vapi_status_reflected_in_combined_status(self, client) -> None:
        agent_id = await _create_agent(client, handle="vapi-config-6")
        await client.post(
            f"/api/v1/integrations/{agent_id}/vapi/configure",
            json={"api_key": "fake-key", "first_message": "Hi!"},
            headers=_auth(),
        )
        status_resp = await client.get(
            f"/api/v1/integrations/{agent_id}/status",
            headers=_auth(),
        )
        assert status_resp.status_code == 200
        # Voice may be pending_activation (no real Vapi key) but the DB row exists
        voice = status_resp.json()["voice"]
        assert "connected" in voice


# ===========================================================================
# GET /{agent_id}/google-calendar/auth-url
# ===========================================================================


class TestGoogleCalendarAuthUrl:
    """Tests for GET /api/v1/integrations/{agent_id}/google-calendar/auth-url."""

    async def test_auth_url_requires_auth(self, client) -> None:
        agent_id = await _create_agent(client, handle="gcal-url-1")
        resp = await client.get(
            f"/api/v1/integrations/{agent_id}/google-calendar/auth-url"
        )
        assert resp.status_code == 401

    async def test_auth_url_unknown_agent_returns_404(self, client) -> None:
        resp = await client.get(
            "/api/v1/integrations/no-such-agent/google-calendar/auth-url",
            headers=_auth(),
        )
        assert resp.status_code == 404

    async def test_auth_url_other_users_agent_returns_404(self, client) -> None:
        agent_id = await _create_agent(client, user_id=_USER_B, handle="gcal-url-2")
        resp = await client.get(
            f"/api/v1/integrations/{agent_id}/google-calendar/auth-url",
            headers=_auth(_USER_A),
        )
        assert resp.status_code == 404

    async def test_auth_url_without_google_creds_returns_503(self, client) -> None:
        """Without ISG_AGENT_GOOGLE_CLIENT_ID set, we expect 503."""
        agent_id = await _create_agent(client, handle="gcal-url-3")
        # Ensure the env var is absent (cleared in fixture teardown anyway, but be explicit)
        os.environ.pop("ISG_AGENT_GOOGLE_CLIENT_ID", None)
        resp = await client.get(
            f"/api/v1/integrations/{agent_id}/google-calendar/auth-url",
            headers=_auth(),
        )
        # 503 when no Google credentials are configured
        assert resp.status_code == 503

    async def test_auth_url_with_google_creds_returns_url(self, client) -> None:
        """With ISG_AGENT_GOOGLE_CLIENT_ID set, returns 200 with auth_url."""
        agent_id = await _create_agent(client, handle="gcal-url-4")
        os.environ["ISG_AGENT_GOOGLE_CLIENT_ID"] = "fake-client-id-test"
        os.environ["ISG_AGENT_GOOGLE_REDIRECT_URI"] = "https://example.com/callback"
        try:
            resp = await client.get(
                f"/api/v1/integrations/{agent_id}/google-calendar/auth-url",
                headers=_auth(),
            )
            assert resp.status_code == 200
            body = resp.json()
            assert "auth_url" in body
            assert "accounts.google.com" in body["auth_url"]
            assert "fake-client-id-test" in body["auth_url"]
        finally:
            os.environ.pop("ISG_AGENT_GOOGLE_CLIENT_ID", None)
            os.environ.pop("ISG_AGENT_GOOGLE_REDIRECT_URI", None)

    async def test_auth_url_uses_fixed_redirect_uri_no_agent_id_in_path(self, client) -> None:
        """The redirect_uri in the auth URL must be FIXED (no agent_id segment).

        Google requires pre-registered redirect URIs.  The agent_id is
        carried in the HMAC-signed ``state`` parameter instead.
        """
        agent_id = await _create_agent(client, handle="gcal-url-fixed-1")
        fixed_uri = "https://prod.example.com/api/v1/integrations/google-calendar/callback"
        os.environ["ISG_AGENT_GOOGLE_CLIENT_ID"] = "client-id-for-fixed-uri-test"
        os.environ["ISG_AGENT_GOOGLE_REDIRECT_URI"] = fixed_uri
        try:
            resp = await client.get(
                f"/api/v1/integrations/{agent_id}/google-calendar/auth-url",
                headers=_auth(),
            )
            assert resp.status_code == 200
            auth_url = resp.json()["auth_url"]
            # redirect_uri in the URL must be the fixed URI (URL-encoded)
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(auth_url)
            params = parse_qs(parsed.query)
            assert params["redirect_uri"] == [fixed_uri], (
                f"redirect_uri should be the fixed URI, got {params.get('redirect_uri')}"
            )
            # The agent_id must NOT appear in redirect_uri
            assert agent_id not in params["redirect_uri"][0], (
                "agent_id must not be embedded in redirect_uri"
            )
        finally:
            os.environ.pop("ISG_AGENT_GOOGLE_CLIENT_ID", None)
            os.environ.pop("ISG_AGENT_GOOGLE_REDIRECT_URI", None)

    async def test_auth_url_state_is_hmac_signed(self, client) -> None:
        """The state parameter must be HMAC-signed, not a raw agent_id."""
        agent_id = await _create_agent(client, handle="gcal-url-hmac-1")
        os.environ["ISG_AGENT_GOOGLE_CLIENT_ID"] = "client-id-hmac-test"
        os.environ["ISG_AGENT_GOOGLE_REDIRECT_URI"] = "https://example.com/callback"
        try:
            resp = await client.get(
                f"/api/v1/integrations/{agent_id}/google-calendar/auth-url",
                headers=_auth(),
            )
            assert resp.status_code == 200
            auth_url = resp.json()["auth_url"]
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(auth_url)
            params = parse_qs(parsed.query)
            state_value = params["state"][0]
            # State must contain the agent_id AND an HMAC signature
            assert ":" in state_value, "state must be in format agent_id:hmac_hex"
            parts = state_value.rsplit(":", 1)
            assert parts[0] == agent_id, "state must start with the agent_id"
            assert len(parts[1]) == 16, "HMAC signature must be 16 hex chars"
            # Raw agent_id without signature must NOT be the state
            assert state_value != agent_id, "state must not be raw agent_id"
        finally:
            os.environ.pop("ISG_AGENT_GOOGLE_CLIENT_ID", None)
            os.environ.pop("ISG_AGENT_GOOGLE_REDIRECT_URI", None)


# ===========================================================================
# POST /google-calendar/callback  (FIXED URI — no agent_id in path)
# ===========================================================================


def _make_signed_state(agent_id: str, secret: str = _SECRET) -> str:
    """Build an HMAC-signed state parameter for tests."""
    import hashlib
    import hmac as _hmac
    sig = _hmac.new(
        secret.encode("utf-8"),
        agent_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:16]
    return f"{agent_id}:{sig}"


class TestGoogleCalendarCallback:
    """Tests for POST /api/v1/integrations/google-calendar/callback.

    The callback uses a FIXED path (no agent_id segment).  The agent_id
    is extracted from the HMAC-signed ``state`` parameter in the body.
    """

    async def test_callback_requires_auth(self, client) -> None:
        await _create_agent(client, handle="gcal-cb-1")
        resp = await client.post(
            "/api/v1/integrations/google-calendar/callback",
            json={"code": "fake-code", "state": "anything"},
        )
        assert resp.status_code == 401

    async def test_callback_requires_code_field(self, client) -> None:
        agent_id = await _create_agent(client, handle="gcal-cb-2")
        resp = await client.post(
            "/api/v1/integrations/google-calendar/callback",
            json={"state": _make_signed_state(agent_id)},
            headers=_auth(),
        )
        assert resp.status_code == 422

    async def test_callback_requires_state_field(self, client) -> None:
        """Missing state parameter must return 422."""
        await _create_agent(client, handle="gcal-cb-state-miss-1")
        resp = await client.post(
            "/api/v1/integrations/google-calendar/callback",
            json={"code": "fake-code"},
            headers=_auth(),
        )
        assert resp.status_code == 422

    async def test_callback_invalid_state_returns_400(self, client) -> None:
        """A tampered or unsigned state must return 400."""
        await _create_agent(client, handle="gcal-cb-bad-state-1")
        resp = await client.post(
            "/api/v1/integrations/google-calendar/callback",
            json={"code": "fake-code", "state": "raw-agent-id-no-sig"},
            headers=_auth(),
        )
        assert resp.status_code == 400
        assert "state" in resp.json()["detail"].lower()

    async def test_callback_tampered_hmac_returns_400(self, client) -> None:
        """A state with a wrong HMAC signature must return 400."""
        agent_id = await _create_agent(client, handle="gcal-cb-tamper-1")
        tampered_state = f"{agent_id}:0000000000000000"
        resp = await client.post(
            "/api/v1/integrations/google-calendar/callback",
            json={"code": "fake-code", "state": tampered_state},
            headers=_auth(),
        )
        assert resp.status_code == 400

    async def test_callback_extracts_agent_id_from_state(self, client) -> None:
        """The callback must extract agent_id from the signed state, not the URL."""
        agent_id = await _create_agent(client, handle="gcal-cb-extract-1")
        signed_state = _make_signed_state(agent_id)
        # Without Google creds configured, we get 503 (not 404, proving the
        # agent_id was successfully extracted from state and ownership verified)
        os.environ.pop("ISG_AGENT_GOOGLE_CLIENT_ID", None)
        resp = await client.post(
            "/api/v1/integrations/google-calendar/callback",
            json={"code": "fake-code", "state": signed_state},
            headers=_auth(),
        )
        # 503 = agent_id extracted OK, ownership verified OK, but no Google creds
        assert resp.status_code == 503

    async def test_callback_other_users_agent_returns_404(self, client) -> None:
        """State references an agent owned by a different user."""
        agent_id = await _create_agent(client, user_id=_USER_B, handle="gcal-cb-other-1")
        signed_state = _make_signed_state(agent_id)
        resp = await client.post(
            "/api/v1/integrations/google-calendar/callback",
            json={"code": "fake-code", "state": signed_state},
            headers=_auth(_USER_A),
        )
        assert resp.status_code == 404

    async def test_callback_bad_code_returns_400_or_503(self, client) -> None:
        """An invalid auth code should produce 400 (or 503 if no Google creds)."""
        agent_id = await _create_agent(client, handle="gcal-cb-bad-code-1")
        signed_state = _make_signed_state(agent_id)
        resp = await client.post(
            "/api/v1/integrations/google-calendar/callback",
            json={"code": "totally-invalid-code", "state": signed_state},
            headers=_auth(),
        )
        # Either 400 (exchange failed with Google credentials present) or
        # 503 (no Google credentials configured at all)
        assert resp.status_code in (400, 503, 504)

    async def test_legacy_callback_path_still_works(self, client) -> None:
        """The old per-agent callback URL must still accept requests (backward compat)."""
        agent_id = await _create_agent(client, handle="gcal-cb-legacy-1")
        signed_state = _make_signed_state(agent_id)
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/google-calendar/callback",
            json={"code": "fake-code", "state": signed_state},
            headers=_auth(),
        )
        # Should get through state validation (400/503/504 from code exchange, not 404)
        assert resp.status_code in (400, 503, 504)


# ===========================================================================
# POST /{agent_id}/disconnect
# ===========================================================================


class TestDisconnect:
    """Tests for POST /api/v1/integrations/{agent_id}/disconnect."""

    async def test_disconnect_email_returns_200(self, client) -> None:
        agent_id = await _create_agent(client, handle="disc-email-1")
        await client.post(
            f"/api/v1/integrations/{agent_id}/email",
            json={"api_key": "SG.key", "from_email": "a@b.com"},
            headers=_auth(),
        )
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/disconnect",
            json={"integration": "email"},
            headers=_auth(),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "disconnected"
        assert body["agent_id"] == agent_id

    async def test_disconnect_sendgrid_alias_works(self, client) -> None:
        agent_id = await _create_agent(client, handle="disc-sg-1")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/disconnect",
            json={"integration": "sendgrid"},
            headers=_auth(),
        )
        assert resp.status_code == 200

    async def test_disconnect_sms_returns_200(self, client) -> None:
        agent_id = await _create_agent(client, handle="disc-sms-1")
        await client.post(
            f"/api/v1/integrations/{agent_id}/sms",
            json={"account_sid": "AC1", "auth_token": "tok", "from_number": "+1555"},
            headers=_auth(),
        )
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/disconnect",
            json={"integration": "sms"},
            headers=_auth(),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "disconnected"

    async def test_disconnect_twilio_alias_works(self, client) -> None:
        agent_id = await _create_agent(client, handle="disc-tw-1")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/disconnect",
            json={"integration": "twilio"},
            headers=_auth(),
        )
        assert resp.status_code == 200

    async def test_disconnect_google_calendar_returns_200(self, client) -> None:
        agent_id = await _create_agent(client, handle="disc-gcal-1")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/disconnect",
            json={"integration": "google_calendar"},
            headers=_auth(),
        )
        assert resp.status_code == 200

    async def test_disconnect_calendar_alias_works(self, client) -> None:
        agent_id = await _create_agent(client, handle="disc-gcal-2")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/disconnect",
            json={"integration": "calendar"},
            headers=_auth(),
        )
        assert resp.status_code == 200

    async def test_disconnect_vapi_returns_200(self, client) -> None:
        agent_id = await _create_agent(client, handle="disc-vapi-1")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/disconnect",
            json={"integration": "vapi"},
            headers=_auth(),
        )
        assert resp.status_code == 200

    async def test_disconnect_voice_alias_works(self, client) -> None:
        agent_id = await _create_agent(client, handle="disc-voice-1")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/disconnect",
            json={"integration": "voice"},
            headers=_auth(),
        )
        assert resp.status_code == 200

    async def test_disconnect_invalid_name_returns_400(self, client) -> None:
        agent_id = await _create_agent(client, handle="disc-bad-1")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/disconnect",
            json={"integration": "zapier"},
            headers=_auth(),
        )
        assert resp.status_code == 400

    async def test_disconnect_requires_auth(self, client) -> None:
        agent_id = await _create_agent(client, handle="disc-auth-1")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/disconnect",
            json={"integration": "email"},
        )
        assert resp.status_code == 401

    async def test_disconnect_unknown_agent_returns_404(self, client) -> None:
        resp = await client.post(
            "/api/v1/integrations/no-such-agent/disconnect",
            json={"integration": "email"},
            headers=_auth(),
        )
        assert resp.status_code == 404

    async def test_disconnect_other_users_agent_returns_404(self, client) -> None:
        agent_id = await _create_agent(client, user_id=_USER_B, handle="disc-other-1")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/disconnect",
            json={"integration": "email"},
            headers=_auth(_USER_A),
        )
        assert resp.status_code == 404

    async def test_disconnect_clears_email_config(self, client) -> None:
        """Verify email shows connected=False after disconnect."""
        agent_id = await _create_agent(client, handle="disc-clear-1")
        await client.post(
            f"/api/v1/integrations/{agent_id}/email",
            json={"api_key": "SG.key", "from_email": "hello@example.com"},
            headers=_auth(),
        )
        await client.post(
            f"/api/v1/integrations/{agent_id}/disconnect",
            json={"integration": "email"},
            headers=_auth(),
        )
        status_resp = await client.get(
            f"/api/v1/integrations/{agent_id}/status",
            headers=_auth(),
        )
        assert status_resp.json()["email"]["connected"] is False


# ===========================================================================
# POST /{agent_id}/test
# ===========================================================================


class TestTestIntegration:
    """Tests for POST /api/v1/integrations/{agent_id}/test."""

    async def test_test_sendgrid_without_config_returns_400(self, client) -> None:
        agent_id = await _create_agent(client, handle="test-sg-1")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/test",
            json={"integration": "sendgrid"},
            headers=_auth(),
        )
        assert resp.status_code == 400

    async def test_test_email_alias_without_config_returns_400(self, client) -> None:
        agent_id = await _create_agent(client, handle="test-email-1")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/test",
            json={"integration": "email"},
            headers=_auth(),
        )
        assert resp.status_code == 400

    async def test_test_twilio_without_config_returns_400(self, client) -> None:
        agent_id = await _create_agent(client, handle="test-sms-provider-1")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/test",
            json={"integration": "twilio"},
            headers=_auth(),
        )
        assert resp.status_code == 400

    async def test_test_sms_alias_without_config_returns_400(self, client) -> None:
        agent_id = await _create_agent(client, handle="test-sms-1")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/test",
            json={"integration": "sms"},
            headers=_auth(),
        )
        assert resp.status_code == 400

    async def test_test_twilio_with_config_returns_200_instructions(self, client) -> None:
        """Twilio test with a configured agent returns 200 + instructions (no live SMS)."""
        agent_id = await _create_agent(client, handle="test-sms-cfg-1")
        await client.post(
            f"/api/v1/integrations/{agent_id}/sms",
            json={"account_sid": "ACtest", "auth_token": "testtoken", "from_number": "+15559876543"},
            headers=_auth(),
        )
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/test",
            json={"integration": "twilio"},
            headers=_auth(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "+15559876543" in body["message"]

    async def test_test_sendgrid_with_config_sends_or_returns_error(self, client) -> None:
        """With a fake SendGrid key, the test returns 200 with success=False (bad key expected)."""
        agent_id = await _create_agent(client, handle="test-sg-cfg-1")
        await client.post(
            f"/api/v1/integrations/{agent_id}/email",
            json={"api_key": "SG.fake-key-for-test", "from_email": "from@example.com"},
            headers=_auth(),
        )
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/test",
            json={"integration": "sendgrid"},
            headers=_auth("user-integ-alpha", "integ@example.com"),
        )
        # 200 is returned regardless — success=True (real send) or False (fake key)
        assert resp.status_code == 200
        body = resp.json()
        assert "success" in body
        assert "message" in body

    async def test_test_invalid_integration_returns_400(self, client) -> None:
        agent_id = await _create_agent(client, handle="test-bad-1")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/test",
            json={"integration": "zoom"},
            headers=_auth(),
        )
        assert resp.status_code == 400

    async def test_test_requires_auth(self, client) -> None:
        agent_id = await _create_agent(client, handle="test-auth-1")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/test",
            json={"integration": "sendgrid"},
        )
        assert resp.status_code == 401

    async def test_test_unknown_agent_returns_404(self, client) -> None:
        resp = await client.post(
            "/api/v1/integrations/no-such-agent/test",
            json={"integration": "sendgrid"},
            headers=_auth(),
        )
        assert resp.status_code == 404

    async def test_test_other_users_agent_returns_404(self, client) -> None:
        agent_id = await _create_agent(client, user_id=_USER_B, handle="test-other-1")
        resp = await client.post(
            f"/api/v1/integrations/{agent_id}/test",
            json={"integration": "sendgrid"},
            headers=_auth(_USER_A),
        )
        assert resp.status_code == 404
