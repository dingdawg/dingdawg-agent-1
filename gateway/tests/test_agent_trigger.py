"""Tests for POST /api/v1/agents/{agent_id}/trigger endpoint.

Covers:
- Valid trigger with source=api (no respond_to)
- Valid trigger with respond_to=email
- Valid trigger with respond_to=sms
- 404 when agent_id not found
- 422 validation: invalid source, empty message, too-long message
- Trigger from email/sms/calendar/cron sources
- Response structure: status, session_id, response, response_queued
- Public endpoint (no JWT required)
- Graceful handling when runtime not available
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

_SECRET = "test-secret-agent-trigger-suite"
_USER_A = "user-trigger-alpha"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(user_id: str, email: str = "trigger@example.com") -> str:
    return _create_token(user_id=user_id, email=email, secret_key=_SECRET)


def _auth(user_id: str = _USER_A) -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_token(user_id)}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(tmp_path):
    """Async HTTP client with full app lifespan."""
    db_file = str(tmp_path / "test_agent_trigger.db")

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


async def _create_agent(
    client: AsyncClient,
    user_id: str = _USER_A,
    handle: str = "triggertest",
) -> str:
    """Create an agent and return its agent_id."""
    resp = await client.post(
        "/api/v1/agents",
        json={"handle": handle, "name": "Trigger Test Agent", "agent_type": "business"},
        headers=_auth(user_id),
    )
    assert resp.status_code == 201, f"Agent creation failed: {resp.text}"
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# TestAgentTrigger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAgentTrigger:
    """Tests for POST /api/v1/agents/{agent_id}/trigger."""

    async def test_trigger_returns_200_for_existing_agent(self, client) -> None:
        """Valid trigger request for existing agent returns 200."""
        agent_id = await _create_agent(client)
        resp = await client.post(
            f"/api/v1/agents/{agent_id}/trigger",
            json={
                "source": "api",
                "message": "Hello, trigger me",
                "sender": "test@example.com",
            },
        )
        assert resp.status_code == 200

    async def test_trigger_response_has_required_fields(self, client) -> None:
        """Response body contains status, session_id, response, response_queued."""
        agent_id = await _create_agent(client, handle="triggerfields")
        resp = await client.post(
            f"/api/v1/agents/{agent_id}/trigger",
            json={
                "source": "api",
                "message": "What can you do?",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body
        assert "session_id" in body
        assert "response" in body
        assert "response_queued" in body

    async def test_trigger_status_is_processed(self, client) -> None:
        """Response status is 'processed' on success."""
        agent_id = await _create_agent(client, handle="triggerstatus")
        resp = await client.post(
            f"/api/v1/agents/{agent_id}/trigger",
            json={
                "source": "email",
                "message": "Process this email",
                "sender": "customer@example.com",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "processed"

    async def test_trigger_returns_404_for_unknown_agent(self, client) -> None:
        """Trigger for non-existent agent returns 404."""
        resp = await client.post(
            "/api/v1/agents/nonexistent-agent-id-12345/trigger",
            json={
                "source": "api",
                "message": "Will not find me",
            },
        )
        assert resp.status_code == 404

    async def test_trigger_with_respond_to_none_returns_queued_false(
        self, client
    ) -> None:
        """respond_to=none means no response is queued."""
        agent_id = await _create_agent(client, handle="triggernone")
        resp = await client.post(
            f"/api/v1/agents/{agent_id}/trigger",
            json={
                "source": "api",
                "message": "No response needed",
                "respond_to": "none",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["response_queued"] is False

    async def test_trigger_with_respond_to_email_returns_queued_true_or_false(
        self, client
    ) -> None:
        """respond_to=email sets response_queued based on notification queue."""
        agent_id = await _create_agent(client, handle="triggeremail")
        resp = await client.post(
            f"/api/v1/agents/{agent_id}/trigger",
            json={
                "source": "email",
                "message": "Reply via email",
                "sender": "user@example.com",
                "respond_to": "email",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        # response_queued is True if notification was queued, False if skill_notifications not available
        assert isinstance(body["response_queued"], bool)

    async def test_trigger_with_respond_to_sms(self, client) -> None:
        """respond_to=sms is accepted."""
        agent_id = await _create_agent(client, handle="triggersms")
        resp = await client.post(
            f"/api/v1/agents/{agent_id}/trigger",
            json={
                "source": "sms",
                "message": "Reply via SMS",
                "sender": "+15551234567",
                "respond_to": "sms",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["response_queued"], bool)

    async def test_trigger_invalid_source_returns_422(self, client) -> None:
        """Invalid source value returns 422 Unprocessable Entity."""
        agent_id = await _create_agent(client, handle="triggerbadsource")
        resp = await client.post(
            f"/api/v1/agents/{agent_id}/trigger",
            json={
                "source": "invalid_source",
                "message": "Test",
            },
        )
        assert resp.status_code == 422

    async def test_trigger_empty_message_returns_422(self, client) -> None:
        """Empty message string returns 422."""
        agent_id = await _create_agent(client, handle="triggerempty")
        resp = await client.post(
            f"/api/v1/agents/{agent_id}/trigger",
            json={
                "source": "api",
                "message": "",
            },
        )
        assert resp.status_code == 422

    async def test_trigger_too_long_message_returns_422(self, client) -> None:
        """Message exceeding max length returns 422."""
        agent_id = await _create_agent(client, handle="triggerlongmsg")
        resp = await client.post(
            f"/api/v1/agents/{agent_id}/trigger",
            json={
                "source": "api",
                "message": "x" * 10001,
            },
        )
        assert resp.status_code == 422

    async def test_trigger_invalid_respond_to_returns_422(self, client) -> None:
        """Invalid respond_to value returns 422."""
        agent_id = await _create_agent(client, handle="triggerbadrespondto")
        resp = await client.post(
            f"/api/v1/agents/{agent_id}/trigger",
            json={
                "source": "api",
                "message": "Test",
                "respond_to": "telegram",
            },
        )
        assert resp.status_code == 422

    async def test_trigger_email_source_accepted(self, client) -> None:
        """source=email is a valid source."""
        agent_id = await _create_agent(client, handle="triggeremailsrc")
        resp = await client.post(
            f"/api/v1/agents/{agent_id}/trigger",
            json={"source": "email", "message": "Email trigger", "sender": "a@b.com"},
        )
        assert resp.status_code == 200

    async def test_trigger_sms_source_accepted(self, client) -> None:
        """source=sms is a valid source."""
        agent_id = await _create_agent(client, handle="triggersmssrc")
        resp = await client.post(
            f"/api/v1/agents/{agent_id}/trigger",
            json={"source": "sms", "message": "SMS trigger", "sender": "+15550000001"},
        )
        assert resp.status_code == 200

    async def test_trigger_calendar_source_accepted(self, client) -> None:
        """source=calendar is a valid source."""
        agent_id = await _create_agent(client, handle="triggercalsrc")
        resp = await client.post(
            f"/api/v1/agents/{agent_id}/trigger",
            json={"source": "calendar", "message": "Calendar event changed"},
        )
        assert resp.status_code == 200

    async def test_trigger_cron_source_accepted(self, client) -> None:
        """source=cron is a valid source."""
        agent_id = await _create_agent(client, handle="triggercronsrc")
        resp = await client.post(
            f"/api/v1/agents/{agent_id}/trigger",
            json={"source": "cron", "message": "Scheduled task"},
        )
        assert resp.status_code == 200

    async def test_trigger_is_public_no_jwt_required(self, client) -> None:
        """Trigger endpoint does NOT require JWT auth."""
        agent_id = await _create_agent(client, handle="triggerpublic")
        # No Authorization header
        resp = await client.post(
            f"/api/v1/agents/{agent_id}/trigger",
            json={
                "source": "api",
                "message": "Public trigger",
            },
        )
        # Must not return 401 or 403 — it's a public endpoint
        assert resp.status_code not in {401, 403}

    async def test_trigger_session_id_is_string(self, client) -> None:
        """session_id in response is a non-empty string."""
        agent_id = await _create_agent(client, handle="triggersessionid")
        resp = await client.post(
            f"/api/v1/agents/{agent_id}/trigger",
            json={"source": "api", "message": "Session test"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["session_id"], str)
        assert len(body["session_id"]) > 0

    async def test_trigger_response_is_string(self, client) -> None:
        """response in body is a string (the agent's reply)."""
        agent_id = await _create_agent(client, handle="triggerresponse")
        resp = await client.post(
            f"/api/v1/agents/{agent_id}/trigger",
            json={"source": "api", "message": "Hello agent"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["response"], str)

    async def test_trigger_default_sender_is_empty_string(self, client) -> None:
        """sender defaults to empty string when not provided."""
        agent_id = await _create_agent(client, handle="triggernosender")
        resp = await client.post(
            f"/api/v1/agents/{agent_id}/trigger",
            json={"source": "api", "message": "No sender provided"},
        )
        assert resp.status_code == 200

    async def test_trigger_default_respond_to_is_none(self, client) -> None:
        """respond_to defaults to 'none' when not provided."""
        agent_id = await _create_agent(client, handle="triggernorespond")
        resp = await client.post(
            f"/api/v1/agents/{agent_id}/trigger",
            json={"source": "api", "message": "Default respond_to"},
        )
        assert resp.status_code == 200
        body = resp.json()
        # Default respond_to=none → response_queued must be False
        assert body["response_queued"] is False

    async def test_trigger_missing_source_returns_422(self, client) -> None:
        """Missing required 'source' field returns 422."""
        agent_id = await _create_agent(client, handle="triggernomsg")
        resp = await client.post(
            f"/api/v1/agents/{agent_id}/trigger",
            json={"message": "No source"},
        )
        assert resp.status_code == 422

    async def test_trigger_missing_message_returns_422(self, client) -> None:
        """Missing required 'message' field returns 422."""
        agent_id = await _create_agent(client, handle="triggernomsg2")
        resp = await client.post(
            f"/api/v1/agents/{agent_id}/trigger",
            json={"source": "api"},
        )
        assert resp.status_code == 422

    async def test_trigger_with_long_sender_returns_422(self, client) -> None:
        """Sender exceeding max length (500 chars) returns 422."""
        agent_id = await _create_agent(client, handle="triggerlongsender")
        resp = await client.post(
            f"/api/v1/agents/{agent_id}/trigger",
            json={
                "source": "api",
                "message": "Test",
                "sender": "a" * 501,
            },
        )
        assert resp.status_code == 422

    async def test_trigger_multiple_calls_return_different_session_ids(
        self, client
    ) -> None:
        """Each trigger call creates a new session with a unique session_id."""
        agent_id = await _create_agent(client, handle="triggermulticall")
        payload = {"source": "api", "message": "First call"}
        r1 = await client.post(f"/api/v1/agents/{agent_id}/trigger", json=payload)
        r2 = await client.post(f"/api/v1/agents/{agent_id}/trigger", json=payload)
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["session_id"] != r2.json()["session_id"]

    async def test_trigger_tier_isolation_allows_through(self, client) -> None:
        """Tier isolation middleware passes trigger requests without JWT."""
        agent_id = await _create_agent(client, handle="triggertier")
        # No auth header — if tier isolation blocks, we'd get 403
        resp = await client.post(
            f"/api/v1/agents/{agent_id}/trigger",
            json={"source": "api", "message": "Tier test"},
        )
        assert resp.status_code != 403

    async def test_trigger_route_validator_includes_trigger_path(
        self, client
    ) -> None:
        """The route validator registers /trigger routes (no 503 from ungated path)."""
        agent_id = await _create_agent(client, handle="triggerroutecheck")
        resp = await client.post(
            f"/api/v1/agents/{agent_id}/trigger",
            json={"source": "api", "message": "Route validator test"},
        )
        # If route is ungated and strict mode, would return 403. In dev mode, 200.
        assert resp.status_code in {200, 404}
