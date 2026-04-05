"""Tests for the health check endpoint."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from isg_agent import __version__
from isg_agent.api.app import create_app


@pytest.mark.asyncio
async def test_health_returns_ok() -> None:
    """GET /health returns status ok and current version."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] in ("healthy", "degraded")
    assert body["version"] == __version__
    assert "database" in body
