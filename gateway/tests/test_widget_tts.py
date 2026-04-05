"""Widget TTS integration tests.

Since widget.js is vanilla JavaScript, we cannot unit-test the browser-side
TTS API directly from Python.  Instead these tests verify:

1. The /api/v1/widget/embed.js endpoint serves JavaScript that contains the
   TTS identifiers expected by the browser (speechSynthesis, speakText,
   voiceEnabled, localStorage key).

2. The other widget API endpoints (config, session, message) remain
   functional after TTS code was added to widget.js — no regression.

All tests use the ASGI TestClient pattern from test_api_marketplace.py.
No external services (Google, Twilio, etc.) are called.

Mocking strategy for message endpoint:
- The /message endpoint calls runtime.process_message which requires a
  full LLM call.  We skip full message-processing integration tests here
  (they live in real-world e2e specs) and focus on verifiable API surface:
  embed.js content, config endpoint, session creation.
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from isg_agent.config import get_settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SECRET = "test-secret-widget-tts-suite"
_USER_ID = "user_widget_tts_test"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mint_token(user_id: str = _USER_ID, email: str = "widget@test.example") -> str:
    """Mint a JWT for use in tests that need auth headers."""
    from isg_agent.api.routes.auth import _create_token
    return _create_token(user_id=user_id, email=email, secret_key=_SECRET)


def _auth_headers(user_id: str = _USER_ID) -> dict[str, str]:
    """Return Authorization headers for the given user_id."""
    return {"Authorization": f"Bearer {_mint_token(user_id)}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    """Async HTTP client with full app lifespan, isolated temp DB."""
    db_file = str(tmp_path / "test_widget_tts.db")
    monkeypatch.setenv("ISG_AGENT_DB_PATH", db_file)
    monkeypatch.setenv("ISG_AGENT_SECRET_KEY", _SECRET)
    get_settings.cache_clear()

    from isg_agent.app import create_app, lifespan

    app = create_app()

    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    get_settings.cache_clear()


async def _create_agent(client: AsyncClient, handle: str = "tts-widget-agent") -> tuple[str, str]:
    """Create an agent and return (agent_id, handle)."""
    resp = await client.post(
        "/api/v1/agents",
        json={
            "handle": handle,
            "name": "Widget TTS Test Agent",
            "agent_type": "business",
        },
        headers=_auth_headers(),
    )
    assert resp.status_code == 201, f"Agent creation failed: {resp.text}"
    data = resp.json()
    return data["id"], data["handle"]


# ---------------------------------------------------------------------------
# embed.js TTS content tests
# ---------------------------------------------------------------------------


class TestWidgetEmbedJsTtsContent:
    """Verify that embed.js includes all TTS identifiers after the feature was wired."""

    async def test_embed_js_returns_200(self, client: AsyncClient) -> None:
        """GET /api/v1/widget/embed.js returns HTTP 200."""
        resp = await client.get("/api/v1/widget/embed.js")
        assert resp.status_code == 200

    async def test_embed_js_content_type_is_javascript(self, client: AsyncClient) -> None:
        """embed.js is served with application/javascript content-type."""
        resp = await client.get("/api/v1/widget/embed.js")
        assert resp.status_code == 200
        assert "javascript" in resp.headers.get("content-type", "").lower()

    async def test_embed_js_contains_speechsynthesis(self, client: AsyncClient) -> None:
        """embed.js references speechSynthesis (Web Speech API entry point)."""
        resp = await client.get("/api/v1/widget/embed.js")
        assert resp.status_code == 200
        assert "speechSynthesis" in resp.text

    async def test_embed_js_contains_speak_text_function(self, client: AsyncClient) -> None:
        """embed.js defines the speakText function used to play TTS audio."""
        resp = await client.get("/api/v1/widget/embed.js")
        assert resp.status_code == 200
        assert "speakText" in resp.text

    async def test_embed_js_contains_voice_enabled_variable(self, client: AsyncClient) -> None:
        """embed.js defines the voiceEnabled flag that tracks TTS opt-in state."""
        resp = await client.get("/api/v1/widget/embed.js")
        assert resp.status_code == 200
        assert "voiceEnabled" in resp.text

    async def test_embed_js_contains_localStorage_voice_key(self, client: AsyncClient) -> None:
        """embed.js uses a localStorage key following the dd_widget_*_voice naming pattern."""
        resp = await client.get("/api/v1/widget/embed.js")
        assert resp.status_code == 200
        body = resp.text
        # Pattern: dd_widget_<handle>_voice stored in localStorage
        assert "dd_widget_" in body
        assert "_voice" in body

    async def test_embed_js_has_cache_control_header(self, client: AsyncClient) -> None:
        """embed.js is served with a cache-control header for performance."""
        resp = await client.get("/api/v1/widget/embed.js")
        assert resp.status_code == 200
        assert "cache-control" in resp.headers

    async def test_embed_js_has_cors_header(self, client: AsyncClient) -> None:
        """embed.js is served with CORS header so external sites can load it."""
        resp = await client.get("/api/v1/widget/embed.js")
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "*"

    async def test_embed_js_contains_tts_toggle_button_class(self, client: AsyncClient) -> None:
        """embed.js includes the voice-toggle button CSS class."""
        resp = await client.get("/api/v1/widget/embed.js")
        assert resp.status_code == 200
        assert "dd-widget-voice-toggle" in resp.text

    async def test_embed_js_contains_set_voice_enabled(self, client: AsyncClient) -> None:
        """embed.js defines setVoiceEnabled function for toggling TTS state."""
        resp = await client.get("/api/v1/widget/embed.js")
        assert resp.status_code == 200
        assert "setVoiceEnabled" in resp.text

    async def test_embed_js_non_empty(self, client: AsyncClient) -> None:
        """embed.js has substantial content (not an empty file or stub)."""
        resp = await client.get("/api/v1/widget/embed.js")
        assert resp.status_code == 200
        # Widget should be more than 1KB
        assert len(resp.text) > 1024


# ---------------------------------------------------------------------------
# Widget config endpoint — no regression
# ---------------------------------------------------------------------------


class TestWidgetConfigEndpoint:
    """Verify the widget config endpoint works after TTS code was added."""

    async def test_config_returns_404_for_unknown_handle(self, client: AsyncClient) -> None:
        """GET /api/v1/widget/{handle}/config returns 404 for an unknown agent."""
        resp = await client.get("/api/v1/widget/no-such-agent-handle/config")
        assert resp.status_code == 404

    async def test_config_returns_200_for_existing_agent(self, client: AsyncClient) -> None:
        """GET /api/v1/widget/{handle}/config returns 200 for a registered agent."""
        _, handle = await _create_agent(client, handle="cfg-widget-agent")
        resp = await client.get(f"/api/v1/widget/{handle}/config")
        assert resp.status_code == 200

    async def test_config_response_contains_agent_fields(self, client: AsyncClient) -> None:
        """Config response contains expected agent metadata fields."""
        _, handle = await _create_agent(client, handle="cfg-fields-agent")
        resp = await client.get(f"/api/v1/widget/{handle}/config")
        assert resp.status_code == 200
        body = resp.json()
        assert "agent_name" in body
        assert "handle" in body
        assert "greeting" in body
        assert "primary_color" in body
        assert "bubble_text" in body

    async def test_config_strips_at_prefix_from_handle(self, client: AsyncClient) -> None:
        """Config endpoint accepts @handle with the @ prefix and strips it."""
        _, handle = await _create_agent(client, handle="at-prefix-agent")
        resp = await client.get(f"/api/v1/widget/@{handle}/config")
        assert resp.status_code == 200

    async def test_config_has_cors_header(self, client: AsyncClient) -> None:
        """Config endpoint returns CORS header for cross-origin widget embedding."""
        _, handle = await _create_agent(client, handle="cfg-cors-agent")
        resp = await client.get(f"/api/v1/widget/{handle}/config")
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "*"


# ---------------------------------------------------------------------------
# Widget session creation endpoint — no regression
# ---------------------------------------------------------------------------


class TestWidgetSessionEndpoint:
    """Verify widget session creation works after TTS code was added."""

    async def test_session_returns_200_for_known_agent(self, client: AsyncClient) -> None:
        """POST /api/v1/widget/{handle}/session returns 200 for a known agent."""
        _, handle = await _create_agent(client, handle="sess-widget-agent")
        resp = await client.post(f"/api/v1/widget/{handle}/session", json={})
        assert resp.status_code == 200

    async def test_session_response_contains_session_id(self, client: AsyncClient) -> None:
        """Session creation response includes a session_id for subsequent messages."""
        _, handle = await _create_agent(client, handle="sess-id-agent")
        resp = await client.post(f"/api/v1/widget/{handle}/session", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert "session_id" in body
        assert body["session_id"]  # Non-empty

    async def test_session_response_contains_greeting(self, client: AsyncClient) -> None:
        """Session creation response includes a greeting_message."""
        _, handle = await _create_agent(client, handle="sess-greet-agent")
        resp = await client.post(f"/api/v1/widget/{handle}/session", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert "greeting_message" in body
        assert body["greeting_message"]  # Non-empty

    async def test_session_response_contains_visitor_id(self, client: AsyncClient) -> None:
        """Session creation response includes a visitor_id."""
        _, handle = await _create_agent(client, handle="sess-visitor-agent")
        resp = await client.post(f"/api/v1/widget/{handle}/session", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert "visitor_id" in body

    async def test_session_accepts_existing_visitor_id(self, client: AsyncClient) -> None:
        """Session creation accepts an existing visitor_id for session resumption."""
        _, handle = await _create_agent(client, handle="sess-resume-agent")
        visitor_id = "existing-visitor-abc123"
        resp = await client.post(
            f"/api/v1/widget/{handle}/session",
            json={"visitor_id": visitor_id},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["visitor_id"] == visitor_id

    async def test_session_returns_404_for_unknown_agent(self, client: AsyncClient) -> None:
        """POST /api/v1/widget/{handle}/session returns 404 for unknown agent."""
        resp = await client.post("/api/v1/widget/nonexistent-widget-handle/session", json={})
        assert resp.status_code == 404

    async def test_session_has_cors_header(self, client: AsyncClient) -> None:
        """Session endpoint returns CORS header for cross-origin widget embedding."""
        _, handle = await _create_agent(client, handle="sess-cors-agent")
        resp = await client.post(f"/api/v1/widget/{handle}/session", json={})
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "*"


# ---------------------------------------------------------------------------
# Widget message endpoint — no regression (structural only, no LLM)
# ---------------------------------------------------------------------------


class TestWidgetMessageEndpoint:
    """Verify the message endpoint request validation works after TTS was added."""

    async def test_message_returns_400_without_session_id(self, client: AsyncClient) -> None:
        """POST /api/v1/widget/{handle}/message returns 400 when session_id is missing."""
        _, handle = await _create_agent(client, handle="msg-nosess-agent")
        resp = await client.post(
            f"/api/v1/widget/{handle}/message",
            json={"message": "Hello"},
        )
        assert resp.status_code == 400

    async def test_message_returns_400_without_message(self, client: AsyncClient) -> None:
        """POST /api/v1/widget/{handle}/message returns 400 when message body is empty."""
        _, handle = await _create_agent(client, handle="msg-nomsg-agent")
        # Create a real session first
        sess_resp = await client.post(f"/api/v1/widget/{handle}/session", json={})
        session_id = sess_resp.json()["session_id"]

        resp = await client.post(
            f"/api/v1/widget/{handle}/message",
            json={"session_id": session_id, "message": ""},
        )
        assert resp.status_code == 400

    async def test_message_returns_400_for_invalid_json(self, client: AsyncClient) -> None:
        """POST /api/v1/widget/{handle}/message returns 400 for invalid JSON body."""
        _, handle = await _create_agent(client, handle="msg-badjson-agent")
        resp = await client.post(
            f"/api/v1/widget/{handle}/message",
            content=b"not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    async def test_message_returns_404_for_unknown_agent(self, client: AsyncClient) -> None:
        """POST /api/v1/widget/{handle}/message returns 404 for unknown agent."""
        resp = await client.post(
            "/api/v1/widget/no-agent-here/message",
            json={"session_id": "fake-sess", "message": "Hello"},
        )
        assert resp.status_code == 404
