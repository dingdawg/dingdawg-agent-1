"""Tests for isg_agent.api.routes.channels — ChannelRegistry and HTTP endpoints.

Covers:
- ChannelRegistry CRUD (register, unregister, get, list_all, set_connected, count)
- Channel dataclass (defaults, config, created_at)
- HTTP endpoints via TestClient (list, status, send)
- Authentication enforcement on send endpoint
- Error cases (404 not found, 503 not connected)
"""

from __future__ import annotations

import time
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from isg_agent.api.routes.channels import (
    Channel,
    ChannelListResponse,
    ChannelRegistry,
    ChannelResponse,
    ChannelStatusResponse,
    SendMessageRequest,
    SendMessageResponse,
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest_asyncio.fixture
async def channel_client() -> AsyncIterator[AsyncClient]:
    """Provide an async HTTP client with a pre-populated channel registry."""
    import os

    from isg_agent.app import create_app

    # Ensure the app uses the same secret key as _make_auth_header()
    old_secret = os.environ.get("ISG_AGENT_SECRET_KEY")
    os.environ["ISG_AGENT_SECRET_KEY"] = "test-secret-do-not-use-in-production"

    # Clear the cached settings so the new env var is picked up
    from isg_agent.config import get_settings

    get_settings.cache_clear()

    try:
        app = create_app()

        # Pre-populate a channel registry on app.state so tests are deterministic
        registry = ChannelRegistry()
        registry.register(Channel(id="web-1", type="web", name="Web Chat", connected=True))
        registry.register(
            Channel(id="discord-1", type="discord", name="Discord Bot", connected=False)
        )
        app.state.channel_registry = registry

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        if old_secret is None:
            os.environ.pop("ISG_AGENT_SECRET_KEY", None)
        else:
            os.environ["ISG_AGENT_SECRET_KEY"] = old_secret
        get_settings.cache_clear()


def _make_auth_header(
    user_id: str = "test-user",
    email: str = "test@example.com",
    secret_key: str = "test-secret-do-not-use-in-production",
) -> dict[str, str]:
    """Create a valid Bearer Authorization header for tests."""
    from isg_agent.api.routes.auth import _create_token

    token = _create_token(user_id=user_id, email=email, secret_key=secret_key)
    return {"Authorization": f"Bearer {token}"}


# ===========================================================================
# ChannelRegistry Unit Tests
# ===========================================================================


class TestChannelRegistry:
    """Tests for the in-memory ChannelRegistry."""

    def test_register_and_get(self) -> None:
        """A registered channel can be retrieved by ID."""
        registry = ChannelRegistry()
        ch = Channel(id="ch-1", type="web", name="Web")
        registry.register(ch)

        result = registry.get("ch-1")
        assert result is not None
        assert result.id == "ch-1"
        assert result.type == "web"
        assert result.name == "Web"

    def test_get_unknown_returns_none(self) -> None:
        """Getting an unregistered channel returns None."""
        registry = ChannelRegistry()
        assert registry.get("nonexistent") is None

    def test_unregister_removes_channel(self) -> None:
        """Unregistering a channel removes it from the registry."""
        registry = ChannelRegistry()
        registry.register(Channel(id="ch-1", type="web", name="Web"))
        assert registry.unregister("ch-1") is True
        assert registry.get("ch-1") is None

    def test_unregister_unknown_returns_false(self) -> None:
        """Unregistering a non-existent channel returns False."""
        registry = ChannelRegistry()
        assert registry.unregister("nope") is False

    def test_list_all_sorted(self) -> None:
        """list_all returns channels sorted by ID."""
        registry = ChannelRegistry()
        registry.register(Channel(id="z-channel", type="web", name="Z"))
        registry.register(Channel(id="a-channel", type="slack", name="A"))

        channels = registry.list_all()
        assert len(channels) == 2
        assert channels[0].id == "a-channel"
        assert channels[1].id == "z-channel"

    def test_set_connected(self) -> None:
        """set_connected updates the connection status."""
        registry = ChannelRegistry()
        registry.register(Channel(id="ch-1", type="web", name="Web", connected=False))

        assert registry.set_connected("ch-1", True) is True
        ch = registry.get("ch-1")
        assert ch is not None
        assert ch.connected is True

    def test_set_connected_unknown_returns_false(self) -> None:
        """set_connected returns False for non-existent channels."""
        registry = ChannelRegistry()
        assert registry.set_connected("nope", True) is False

    def test_count(self) -> None:
        """count returns the number of registered channels."""
        registry = ChannelRegistry()
        assert registry.count() == 0
        registry.register(Channel(id="a", type="web", name="A"))
        registry.register(Channel(id="b", type="slack", name="B"))
        assert registry.count() == 2

    def test_list_all_empty(self) -> None:
        """list_all on empty registry returns empty list."""
        registry = ChannelRegistry()
        assert registry.list_all() == []


class TestChannelDataclass:
    """Tests for the Channel dataclass."""

    def test_default_connected_false(self) -> None:
        """New channels are not connected by default."""
        ch = Channel(id="ch-1", type="web", name="Web")
        assert ch.connected is False

    def test_default_config_empty(self) -> None:
        """Default config is an empty dict."""
        ch = Channel(id="ch-1", type="web", name="Web")
        assert ch.config == {}

    def test_created_at_has_value(self) -> None:
        """created_at is auto-populated as an ISO 8601 string."""
        ch = Channel(id="ch-1", type="web", name="Web")
        assert ch.created_at  # non-empty
        assert "T" in ch.created_at  # ISO format

    def test_config_stored(self) -> None:
        """Custom config is stored on the channel."""
        ch = Channel(
            id="ch-1",
            type="discord",
            name="Discord",
            config={"token": "abc123", "guild_id": "123"},
        )
        assert ch.config["token"] == "abc123"
        assert ch.config["guild_id"] == "123"


# ===========================================================================
# HTTP Endpoint Tests
# ===========================================================================


class TestChannelEndpoints:
    """Tests for the /api/v1/channels HTTP endpoints."""

    async def test_list_channels_returns_all(self, channel_client: AsyncClient) -> None:
        """GET /api/v1/channels returns all registered channels."""
        resp = await channel_client.get("/api/v1/channels")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert len(data["channels"]) == 2

    async def test_list_channels_sorted_by_id(self, channel_client: AsyncClient) -> None:
        """Channels are returned sorted by ID."""
        resp = await channel_client.get("/api/v1/channels")
        channels = resp.json()["channels"]
        ids = [ch["id"] for ch in channels]
        assert ids == sorted(ids)

    async def test_channel_status_found(self, channel_client: AsyncClient) -> None:
        """GET /api/v1/channels/{id}/status returns status for known channel."""
        resp = await channel_client.get("/api/v1/channels/web-1/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "web-1"
        assert data["connected"] is True

    async def test_channel_status_disconnected(self, channel_client: AsyncClient) -> None:
        """Disconnected channel returns connected=False."""
        resp = await channel_client.get("/api/v1/channels/discord-1/status")
        assert resp.status_code == 200
        assert resp.json()["connected"] is False

    async def test_channel_status_not_found(self, channel_client: AsyncClient) -> None:
        """GET /api/v1/channels/{id}/status returns 404 for unknown channel."""
        resp = await channel_client.get("/api/v1/channels/unknown-99/status")
        assert resp.status_code == 404

    async def test_send_message_requires_auth(self, channel_client: AsyncClient) -> None:
        """POST /api/v1/channels/{id}/send requires authentication."""
        resp = await channel_client.post(
            "/api/v1/channels/web-1/send",
            json={"content": "Hello"},
        )
        assert resp.status_code == 401

    async def test_send_message_success(self, channel_client: AsyncClient) -> None:
        """POST /api/v1/channels/{id}/send returns success for connected channel."""
        headers = _make_auth_header()
        resp = await channel_client.post(
            "/api/v1/channels/web-1/send",
            json={"content": "Hello from test"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["sent"] is True
        assert data["channel_id"] == "web-1"
        assert data["message_id"]  # non-empty UUID

    async def test_send_message_channel_not_found(self, channel_client: AsyncClient) -> None:
        """POST /api/v1/channels/{id}/send returns 404 for unknown channel."""
        headers = _make_auth_header()
        resp = await channel_client.post(
            "/api/v1/channels/nonexistent/send",
            json={"content": "Hello"},
            headers=headers,
        )
        assert resp.status_code == 404

    async def test_send_message_channel_not_connected(
        self, channel_client: AsyncClient
    ) -> None:
        """POST /api/v1/channels/{id}/send returns 503 for disconnected channel."""
        headers = _make_auth_header()
        resp = await channel_client.post(
            "/api/v1/channels/discord-1/send",
            json={"content": "Hello"},
            headers=headers,
        )
        assert resp.status_code == 503

    async def test_send_message_empty_content_rejected(
        self, channel_client: AsyncClient
    ) -> None:
        """POST /api/v1/channels/{id}/send rejects empty content."""
        headers = _make_auth_header()
        resp = await channel_client.post(
            "/api/v1/channels/web-1/send",
            json={"content": ""},
            headers=headers,
        )
        assert resp.status_code == 422  # Pydantic validation error

    async def test_list_channels_no_auth_required(
        self, channel_client: AsyncClient
    ) -> None:
        """GET /api/v1/channels does not require authentication."""
        resp = await channel_client.get("/api/v1/channels")
        assert resp.status_code == 200


# ===========================================================================
# Pydantic Response Model Tests
# ===========================================================================


class TestChannelModels:
    """Tests for the Pydantic models used by channel endpoints."""

    def test_channel_response_fields(self) -> None:
        """ChannelResponse has the expected fields."""
        cr = ChannelResponse(
            id="ch-1",
            type="web",
            name="Web Chat",
            connected=True,
            created_at="2026-01-01T00:00:00+00:00",
        )
        assert cr.id == "ch-1"
        assert cr.type == "web"
        assert cr.connected is True

    def test_channel_status_response_fields(self) -> None:
        """ChannelStatusResponse has the expected fields."""
        csr = ChannelStatusResponse(
            id="ch-1", type="discord", name="Discord", connected=False
        )
        assert csr.connected is False

    def test_send_message_request_fields(self) -> None:
        """SendMessageRequest validates content constraints."""
        req = SendMessageRequest(content="Hello", metadata={"key": "value"})
        assert req.content == "Hello"
        assert req.metadata == {"key": "value"}

    def test_send_message_response_defaults(self) -> None:
        """SendMessageResponse has sensible defaults."""
        smr = SendMessageResponse(sent=True, channel_id="ch-1")
        assert smr.message_id == ""
        assert smr.error is None

    def test_channel_list_response(self) -> None:
        """ChannelListResponse wraps a list with count."""
        clr = ChannelListResponse(channels=[], count=0)
        assert clr.count == 0
        assert clr.channels == []
