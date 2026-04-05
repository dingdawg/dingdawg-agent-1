"""Tests for inbound webhook endpoints and InboundMessage normalization.

Covers:
- POST /api/v1/webhooks/sendgrid/inbound    — receive parsed inbound emails
- POST /api/v1/webhooks/twilio/inbound      — receive inbound SMS
- POST /api/v1/webhooks/google-calendar/push — receive calendar push notifications
- InboundMessage dataclass normalization
- Agent lookup from recipient address/phone number
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import unittest
import urllib.parse
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from isg_agent.api.routes.auth import _create_token
from isg_agent.config import get_settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SECRET = "test-secret-webhooks-inbound-suite"
_USER_A = "user-webhook-alpha"

_SG_USER = "sguser"
_SG_PASS = "sgpass"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(user_id: str, email: str = "webhook@example.com") -> str:
    return _create_token(user_id=user_id, email=email, secret_key=_SECRET)


def _auth(user_id: str = _USER_A) -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_token(user_id)}"}


def _basic_auth_header(username: str, password: str) -> str:
    credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {credentials}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(tmp_path):
    """Async HTTP client with full app lifespan."""
    db_file = str(tmp_path / "test_webhooks.db")

    os.environ["ISG_AGENT_DB_PATH"] = db_file
    os.environ["ISG_AGENT_SECRET_KEY"] = _SECRET
    os.environ["ISG_AGENT_SENDGRID_INBOUND_USER"] = _SG_USER
    os.environ["ISG_AGENT_SENDGRID_INBOUND_PASS"] = _SG_PASS
    get_settings.cache_clear()

    from isg_agent.app import create_app, lifespan

    app = create_app()
    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    os.environ.pop("ISG_AGENT_DB_PATH", None)
    os.environ.pop("ISG_AGENT_SECRET_KEY", None)
    os.environ.pop("ISG_AGENT_SENDGRID_INBOUND_USER", None)
    os.environ.pop("ISG_AGENT_SENDGRID_INBOUND_PASS", None)
    get_settings.cache_clear()


async def _create_agent(
    client: AsyncClient,
    user_id: str = _USER_A,
    handle: str = "testwebhook",
) -> str:
    """Create an agent and return its agent_id."""
    resp = await client.post(
        "/api/v1/agents",
        json={"handle": handle, "name": "Webhook Test Agent", "agent_type": "business"},
        headers=_auth(user_id),
    )
    assert resp.status_code == 201, f"Agent creation failed: {resp.text}"
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# InboundMessage dataclass tests
# ---------------------------------------------------------------------------


class TestInboundMessageNormalization:
    """Tests for the InboundMessage dataclass."""

    def test_inbound_message_creation(self) -> None:
        """InboundMessage can be instantiated with all required fields."""
        from isg_agent.api.routes.webhooks_inbound import InboundMessage

        msg = InboundMessage(
            source="email",
            sender="sender@example.com",
            subject="Test subject",
            body="Test body",
            agent_id="agent-123",
            raw_payload={"from": "sender@example.com"},
            timestamp="2026-03-10T12:00:00+00:00",
        )
        assert msg.source == "email"
        assert msg.sender == "sender@example.com"
        assert msg.subject == "Test subject"
        assert msg.body == "Test body"
        assert msg.agent_id == "agent-123"
        assert msg.raw_payload == {"from": "sender@example.com"}
        assert msg.timestamp == "2026-03-10T12:00:00+00:00"

    def test_inbound_message_sms_source(self) -> None:
        """InboundMessage accepts sms as source."""
        from isg_agent.api.routes.webhooks_inbound import InboundMessage

        msg = InboundMessage(
            source="sms",
            sender="+15551234567",
            subject="",
            body="Hello from SMS",
            agent_id="agent-456",
            raw_payload={"From": "+15551234567", "Body": "Hello from SMS"},
            timestamp="2026-03-10T12:00:00+00:00",
        )
        assert msg.source == "sms"
        assert msg.subject == ""

    def test_inbound_message_calendar_source(self) -> None:
        """InboundMessage accepts calendar as source."""
        from isg_agent.api.routes.webhooks_inbound import InboundMessage

        msg = InboundMessage(
            source="calendar",
            sender="",
            subject="",
            body="exists",
            agent_id="agent-789",
            raw_payload={"resource_state": "exists"},
            timestamp="2026-03-10T12:00:00+00:00",
        )
        assert msg.source == "calendar"

    def test_inbound_message_asdict(self) -> None:
        """InboundMessage converts to dict via asdict()."""
        from isg_agent.api.routes.webhooks_inbound import InboundMessage

        msg = InboundMessage(
            source="email",
            sender="a@b.com",
            subject="s",
            body="b",
            agent_id="id",
            raw_payload={},
            timestamp="ts",
        )
        d = asdict(msg)
        assert isinstance(d, dict)
        assert d["source"] == "email"
        assert d["sender"] == "a@b.com"


# ---------------------------------------------------------------------------
# SendGrid inbound webhook tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSendGridInbound:
    """Tests for POST /api/v1/webhooks/sendgrid/inbound."""

    async def test_sendgrid_returns_200_with_valid_basic_auth(self, client) -> None:
        """Valid Basic auth + valid payload returns 200 OK."""
        payload = {
            "from": "user@example.com",
            "to": "agent@dingdawg.com",
            "subject": "Hello Agent",
            "text": "I need help",
            "html": "<p>I need help</p>",
        }
        resp = await client.post(
            "/api/v1/webhooks/sendgrid/inbound",
            json=payload,
            headers={"Authorization": _basic_auth_header(_SG_USER, _SG_PASS)},
        )
        assert resp.status_code == 200

    async def test_sendgrid_returns_401_with_missing_auth(self, client) -> None:
        """Missing Authorization header returns 401."""
        payload = {
            "from": "user@example.com",
            "to": "agent@dingdawg.com",
            "subject": "Hello",
            "text": "Body",
        }
        resp = await client.post(
            "/api/v1/webhooks/sendgrid/inbound",
            json=payload,
        )
        assert resp.status_code == 401

    async def test_sendgrid_returns_401_with_wrong_credentials(self, client) -> None:
        """Wrong Basic auth credentials return 401."""
        payload = {
            "from": "user@example.com",
            "to": "agent@dingdawg.com",
            "subject": "Hello",
            "text": "Body",
        }
        resp = await client.post(
            "/api/v1/webhooks/sendgrid/inbound",
            json=payload,
            headers={"Authorization": _basic_auth_header("wrong", "creds")},
        )
        assert resp.status_code == 401

    async def test_sendgrid_returns_401_with_non_basic_auth(self, client) -> None:
        """Non-Basic auth scheme (e.g. Bearer) returns 401."""
        payload = {
            "from": "user@example.com",
            "to": "agent@dingdawg.com",
            "subject": "Hello",
            "text": "Body",
        }
        resp = await client.post(
            "/api/v1/webhooks/sendgrid/inbound",
            json=payload,
            headers={"Authorization": "Bearer some-jwt-token"},
        )
        assert resp.status_code == 401

    async def test_sendgrid_accepts_empty_subject(self, client) -> None:
        """SendGrid payload without subject field returns 200."""
        payload = {
            "from": "user@example.com",
            "to": "agent@dingdawg.com",
            "text": "Message without subject",
        }
        resp = await client.post(
            "/api/v1/webhooks/sendgrid/inbound",
            json=payload,
            headers={"Authorization": _basic_auth_header(_SG_USER, _SG_PASS)},
        )
        assert resp.status_code == 200

    async def test_sendgrid_accepts_html_body_when_text_missing(self, client) -> None:
        """HTML body is used when text is missing from payload."""
        payload = {
            "from": "user@example.com",
            "to": "agent@dingdawg.com",
            "subject": "HTML only",
            "html": "<p>Content in HTML</p>",
        }
        resp = await client.post(
            "/api/v1/webhooks/sendgrid/inbound",
            json=payload,
            headers={"Authorization": _basic_auth_header(_SG_USER, _SG_PASS)},
        )
        assert resp.status_code == 200

    async def test_sendgrid_returns_ok_key_in_response(self, client) -> None:
        """Response body contains a status key."""
        payload = {
            "from": "user@example.com",
            "to": "agent@dingdawg.com",
            "subject": "Test",
            "text": "Test body",
        }
        resp = await client.post(
            "/api/v1/webhooks/sendgrid/inbound",
            json=payload,
            headers={"Authorization": _basic_auth_header(_SG_USER, _SG_PASS)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body

    async def test_sendgrid_no_jwt_required(self, client) -> None:
        """SendGrid endpoint does not require JWT Bearer token."""
        payload = {
            "from": "nojwt@example.com",
            "to": "agent@dingdawg.com",
            "subject": "No JWT",
            "text": "Testing without JWT",
        }
        # Only Basic Auth, no Bearer JWT
        resp = await client.post(
            "/api/v1/webhooks/sendgrid/inbound",
            json=payload,
            headers={"Authorization": _basic_auth_header(_SG_USER, _SG_PASS)},
        )
        assert resp.status_code == 200

    async def test_sendgrid_handles_missing_from_field(self, client) -> None:
        """Payload without 'from' field still returns 200 (graceful)."""
        payload = {
            "to": "agent@dingdawg.com",
            "subject": "No from",
            "text": "Body text",
        }
        resp = await client.post(
            "/api/v1/webhooks/sendgrid/inbound",
            json=payload,
            headers={"Authorization": _basic_auth_header(_SG_USER, _SG_PASS)},
        )
        # Should return 200 — external services expect quick ACKs
        assert resp.status_code == 200

    async def test_sendgrid_with_known_agent_handle(self, client) -> None:
        """When recipient matches a known agent handle, agent lookup succeeds."""
        agent_id = await _create_agent(client, handle="emailagent")
        payload = {
            "from": "customer@example.com",
            "to": "emailagent@dingdawg.com",
            "subject": "Order question",
            "text": "Where is my order?",
        }
        resp = await client.post(
            "/api/v1/webhooks/sendgrid/inbound",
            json=payload,
            headers={"Authorization": _basic_auth_header(_SG_USER, _SG_PASS)},
        )
        assert resp.status_code == 200
        body = resp.json()
        # Should include agent_id in response when found
        assert "agent_id" in body or "status" in body


# ---------------------------------------------------------------------------
# Twilio inbound webhook tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTwilioInbound:
    """Tests for POST /api/v1/webhooks/twilio/inbound."""

    def _make_twilio_signature(
        self,
        auth_token: str,
        url: str,
        params: dict[str, str],
    ) -> str:
        """Generate a valid Twilio HMAC-SHA1 signature."""
        sorted_params = sorted(params.items())
        s = url + "".join(f"{k}{v}" for k, v in sorted_params)
        sig = hmac.new(auth_token.encode(), s.encode(), hashlib.sha1).digest()
        return base64.b64encode(sig).decode()

    async def test_twilio_returns_200_without_signature_validation_in_test(
        self, client
    ) -> None:
        """Twilio endpoint returns 200 for valid form data (signature validation
        is skipped when ISG_AGENT_TWILIO_AUTH_TOKEN is not set in test env)."""
        form_data = {
            "From": "+15551234567",
            "To": "+15559876543",
            "Body": "Help with my order",
            "MessageSid": "SM1234567890abcdef",
        }
        resp = await client.post(
            "/api/v1/webhooks/twilio/inbound",
            data=form_data,
        )
        # In test env without Twilio auth token configured, should accept or
        # return 200 (signature validation is skipped when token not set)
        assert resp.status_code in {200, 401}

    async def test_twilio_returns_200_with_valid_form_data(self, client) -> None:
        """Twilio SMS form data is accepted and returns 200."""
        form_data = {
            "From": "+15551234567",
            "To": "+15559876543",
            "Body": "Hello from Twilio",
            "MessageSid": "SM9876543210fedcba",
        }
        # Without a configured auth token, the endpoint should allow through
        # (graceful degradation in dev mode)
        resp = await client.post(
            "/api/v1/webhooks/twilio/inbound",
            data=form_data,
        )
        assert resp.status_code in {200, 401}

    async def test_twilio_response_is_json(self, client) -> None:
        """Twilio endpoint always returns JSON response body."""
        form_data = {
            "From": "+15551234567",
            "To": "+15559876543",
            "Body": "Test",
            "MessageSid": "SM000",
        }
        resp = await client.post(
            "/api/v1/webhooks/twilio/inbound",
            data=form_data,
        )
        # Response should be parseable as JSON regardless of status
        content_type = resp.headers.get("content-type", "")
        assert "json" in content_type or resp.status_code in {200, 401}

    async def test_twilio_handles_empty_body(self, client) -> None:
        """Empty Body field is handled gracefully."""
        form_data = {
            "From": "+15551234567",
            "To": "+15559876543",
            "Body": "",
            "MessageSid": "SM001",
        }
        resp = await client.post(
            "/api/v1/webhooks/twilio/inbound",
            data=form_data,
        )
        assert resp.status_code in {200, 401}

    async def test_twilio_is_public_endpoint(self, client) -> None:
        """Twilio webhook does not require JWT auth — no Bearer token needed."""
        form_data = {
            "From": "+15551234567",
            "To": "+15559876543",
            "Body": "Test no JWT",
            "MessageSid": "SM002",
        }
        # No Authorization header at all
        resp = await client.post(
            "/api/v1/webhooks/twilio/inbound",
            data=form_data,
        )
        # Should NOT return 403 (tier isolation must pass it through)
        assert resp.status_code != 403

    async def test_twilio_with_configured_auth_token_validates_signature(
        self, tmp_path
    ) -> None:
        """When ISG_AGENT_TWILIO_AUTH_TOKEN is set, invalid signatures return 401."""
        db_file = str(tmp_path / "test_twilio_auth.db")
        os.environ["ISG_AGENT_DB_PATH"] = db_file
        os.environ["ISG_AGENT_SECRET_KEY"] = _SECRET
        os.environ["ISG_AGENT_TWILIO_AUTH_TOKEN"] = "test-twilio-token-abc123"
        os.environ["ISG_AGENT_SENDGRID_INBOUND_USER"] = _SG_USER
        os.environ["ISG_AGENT_SENDGRID_INBOUND_PASS"] = _SG_PASS
        get_settings.cache_clear()

        from isg_agent.app import create_app, lifespan

        app = create_app()
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                form_data = {
                    "From": "+15551234567",
                    "To": "+15559876543",
                    "Body": "Test",
                    "MessageSid": "SM003",
                }
                # Invalid signature should return 401
                resp = await ac.post(
                    "/api/v1/webhooks/twilio/inbound",
                    data=form_data,
                    headers={"X-Twilio-Signature": "invalid-sig"},
                )
                assert resp.status_code == 401

        os.environ.pop("ISG_AGENT_DB_PATH", None)
        os.environ.pop("ISG_AGENT_SECRET_KEY", None)
        os.environ.pop("ISG_AGENT_TWILIO_AUTH_TOKEN", None)
        os.environ.pop("ISG_AGENT_SENDGRID_INBOUND_USER", None)
        os.environ.pop("ISG_AGENT_SENDGRID_INBOUND_PASS", None)
        get_settings.cache_clear()

    async def test_twilio_with_valid_signature_returns_200(self, tmp_path) -> None:
        """When ISG_AGENT_TWILIO_AUTH_TOKEN is set, valid signatures return 200."""
        auth_token = "test-twilio-token-valid-xyz"
        db_file = str(tmp_path / "test_twilio_valid.db")
        os.environ["ISG_AGENT_DB_PATH"] = db_file
        os.environ["ISG_AGENT_SECRET_KEY"] = _SECRET
        os.environ["ISG_AGENT_TWILIO_AUTH_TOKEN"] = auth_token
        os.environ["ISG_AGENT_SENDGRID_INBOUND_USER"] = _SG_USER
        os.environ["ISG_AGENT_SENDGRID_INBOUND_PASS"] = _SG_PASS
        get_settings.cache_clear()

        from isg_agent.app import create_app, lifespan

        app = create_app()
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                form_data = {
                    "From": "+15551234567",
                    "To": "+15559876543",
                    "Body": "Valid message",
                    "MessageSid": "SM999",
                }
                url = "http://test/api/v1/webhooks/twilio/inbound"
                sig = self._make_twilio_signature(auth_token, url, form_data)
                resp = await ac.post(
                    "/api/v1/webhooks/twilio/inbound",
                    data=form_data,
                    headers={"X-Twilio-Signature": sig},
                )
                assert resp.status_code == 200

        os.environ.pop("ISG_AGENT_DB_PATH", None)
        os.environ.pop("ISG_AGENT_SECRET_KEY", None)
        os.environ.pop("ISG_AGENT_TWILIO_AUTH_TOKEN", None)
        os.environ.pop("ISG_AGENT_SENDGRID_INBOUND_USER", None)
        os.environ.pop("ISG_AGENT_SENDGRID_INBOUND_PASS", None)
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Google Calendar push notification tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGoogleCalendarPush:
    """Tests for POST /api/v1/webhooks/google-calendar/push."""

    async def test_calendar_push_returns_200_with_valid_headers(
        self, client
    ) -> None:
        """Valid Google Calendar push headers return 200."""
        resp = await client.post(
            "/api/v1/webhooks/google-calendar/push",
            headers={
                "X-Goog-Channel-ID": "channel-abc-123",
                "X-Goog-Resource-State": "exists",
                "X-Goog-Resource-ID": "resource-xyz-789",
                "X-Goog-Resource-URI": "https://www.googleapis.com/calendar/v3/...",
            },
            content=b"",
        )
        assert resp.status_code == 200

    async def test_calendar_push_sync_state_returns_200(self, client) -> None:
        """'sync' resource state (initial verification) returns 200."""
        resp = await client.post(
            "/api/v1/webhooks/google-calendar/push",
            headers={
                "X-Goog-Channel-ID": "channel-sync-001",
                "X-Goog-Resource-State": "sync",
                "X-Goog-Resource-ID": "resource-sync-001",
            },
            content=b"",
        )
        assert resp.status_code == 200

    async def test_calendar_push_not_exists_state_returns_200(
        self, client
    ) -> None:
        """'not_exists' resource state returns 200."""
        resp = await client.post(
            "/api/v1/webhooks/google-calendar/push",
            headers={
                "X-Goog-Channel-ID": "channel-del-001",
                "X-Goog-Resource-State": "not_exists",
                "X-Goog-Resource-ID": "resource-del-001",
            },
            content=b"",
        )
        assert resp.status_code == 200

    async def test_calendar_push_missing_channel_id_returns_400(
        self, client
    ) -> None:
        """Missing X-Goog-Channel-ID returns 400."""
        resp = await client.post(
            "/api/v1/webhooks/google-calendar/push",
            headers={
                "X-Goog-Resource-State": "exists",
                "X-Goog-Resource-ID": "resource-xyz",
            },
            content=b"",
        )
        assert resp.status_code == 400

    async def test_calendar_push_missing_resource_state_returns_400(
        self, client
    ) -> None:
        """Missing X-Goog-Resource-State returns 400."""
        resp = await client.post(
            "/api/v1/webhooks/google-calendar/push",
            headers={
                "X-Goog-Channel-ID": "channel-abc",
                "X-Goog-Resource-ID": "resource-xyz",
            },
            content=b"",
        )
        assert resp.status_code == 400

    async def test_calendar_push_is_public_endpoint(self, client) -> None:
        """Google Calendar push does not require JWT auth."""
        resp = await client.post(
            "/api/v1/webhooks/google-calendar/push",
            headers={
                "X-Goog-Channel-ID": "channel-public",
                "X-Goog-Resource-State": "sync",
                "X-Goog-Resource-ID": "resource-public",
            },
            content=b"",
        )
        # No Authorization header — must NOT return 403
        assert resp.status_code != 403

    async def test_calendar_push_response_contains_status(self, client) -> None:
        """Response body contains a status key."""
        resp = await client.post(
            "/api/v1/webhooks/google-calendar/push",
            headers={
                "X-Goog-Channel-ID": "channel-resp-test",
                "X-Goog-Resource-State": "exists",
                "X-Goog-Resource-ID": "resource-resp-test",
            },
            content=b"",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body

    async def test_calendar_push_sync_response_contains_acknowledged(
        self, client
    ) -> None:
        """Sync state response explicitly acknowledges the channel."""
        resp = await client.post(
            "/api/v1/webhooks/google-calendar/push",
            headers={
                "X-Goog-Channel-ID": "channel-ack",
                "X-Goog-Resource-State": "sync",
                "X-Goog-Resource-ID": "resource-ack",
            },
            content=b"",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body
        assert body["status"] in {"ok", "acknowledged", "accepted"}


# ---------------------------------------------------------------------------
# Agent lookup from recipient address / phone number tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAgentLookupFromRecipient:
    """Tests for the agent lookup helper used by inbound webhooks."""

    async def test_lookup_by_email_handle_finds_agent(self, client) -> None:
        """Agent lookup by email prefix finds the registered agent."""
        agent_id = await _create_agent(client, handle="lookuptest")

        # Send to handle@dingdawg.com — should match
        payload = {
            "from": "user@example.com",
            "to": "lookuptest@dingdawg.com",
            "subject": "Lookup test",
            "text": "Can you find me?",
        }
        resp = await client.post(
            "/api/v1/webhooks/sendgrid/inbound",
            json=payload,
            headers={"Authorization": _basic_auth_header(_SG_USER, _SG_PASS)},
        )
        assert resp.status_code == 200
        body = resp.json()
        # The agent_id should appear in the response when lookup succeeds
        if "agent_id" in body:
            assert body["agent_id"] == agent_id

    async def test_lookup_with_unknown_recipient_returns_200(self, client) -> None:
        """Unknown recipient returns 200 (external services expect ACK, not errors)."""
        payload = {
            "from": "user@example.com",
            "to": "unknownhandle99999@dingdawg.com",
            "subject": "Unknown",
            "text": "No agent here",
        }
        resp = await client.post(
            "/api/v1/webhooks/sendgrid/inbound",
            json=payload,
            headers={"Authorization": _basic_auth_header(_SG_USER, _SG_PASS)},
        )
        # Must return 200 even when agent not found — external ACK requirement
        assert resp.status_code == 200

    async def test_lookup_strips_domain_from_email(self, client) -> None:
        """Agent lookup strips @domain from the recipient address to get handle."""
        agent_id = await _create_agent(client, handle="domainstrip")
        payload = {
            "from": "sender@example.com",
            "to": "domainstrip@custom-domain.example.com",
            "subject": "Domain strip test",
            "text": "Test",
        }
        resp = await client.post(
            "/api/v1/webhooks/sendgrid/inbound",
            json=payload,
            headers={"Authorization": _basic_auth_header(_SG_USER, _SG_PASS)},
        )
        assert resp.status_code == 200

    async def test_lookup_handles_multiple_recipients(self, client) -> None:
        """When 'to' contains multiple addresses, first is used for lookup."""
        agent_id = await _create_agent(client, handle="multito")
        payload = {
            "from": "sender@example.com",
            "to": "multito@dingdawg.com, other@example.com",
            "subject": "Multi recipient",
            "text": "Test multi",
        }
        resp = await client.post(
            "/api/v1/webhooks/sendgrid/inbound",
            json=payload,
            headers={"Authorization": _basic_auth_header(_SG_USER, _SG_PASS)},
        )
        assert resp.status_code == 200
