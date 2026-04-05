"""Tests for isg_agent.middleware.governance_middleware.GovernanceMiddleware.

TDD — tests written BEFORE implementation to drive the contract.

Covers:
- TestHighRiskDetection (6 tests): path+method pattern matching with wildcards
- TestGovernanceFlow (8 tests): cleared/denied/skip/context content
- TestFailureModes (6 tests): bridge unreachable, timeout, auth error, disabled
- TestMiddlewareIntegration (5 tests): ASGI wrapping, concurrency, header preservation

All tests use mocking — no live bridge connection or real database required.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_governance_result(
    *,
    cleared: bool = True,
    reason: str = "",
) -> dict[str, Any]:
    """Return a mock governance bridge result dict."""
    if cleared:
        return {
            "tool": "mila_governance_check",
            "result": "CLEARED: operation approved for product agent1",
            "is_error": False,
            "duration_ms": 8,
        }
    return {
        "tool": "mila_governance_check",
        "result": f"DENIED: {reason or 'governance policy violation'}",
        "is_error": True,
        "duration_ms": 5,
    }


async def _simple_handler(request: Request) -> PlainTextResponse:
    """A trivial ASGI handler used in integration tests."""
    return PlainTextResponse("ok")


async def _echo_handler(request: Request) -> JSONResponse:
    """Return the incoming headers as JSON for header-preservation tests."""
    return JSONResponse({"x-custom": request.headers.get("x-custom", "missing")})


# ---------------------------------------------------------------------------
# TestHighRiskDetection — 6 tests
# ---------------------------------------------------------------------------


class TestHighRiskDetection:
    """Verify that is_high_risk() correctly classifies paths and methods."""

    def _get_middleware(self):
        """Import and instantiate GovernanceMiddleware with a dummy app."""
        from isg_agent.middleware.governance_middleware import GovernanceMiddleware

        app = MagicMock()
        return GovernanceMiddleware(app, bridge_token="test-tok", enabled=True)

    def test_payment_post_is_high_risk(self) -> None:
        """POST /api/v1/payments must be detected as high-risk."""
        mw = self._get_middleware()
        assert mw.is_high_risk("/api/v1/payments", "POST") is True

    def test_payment_get_is_not_high_risk(self) -> None:
        """GET /api/v1/payments must NOT be high-risk (read-only)."""
        mw = self._get_middleware()
        assert mw.is_high_risk("/api/v1/payments", "GET") is False

    def test_admin_delete_is_high_risk(self) -> None:
        """DELETE /api/v1/admin/* must be detected as high-risk."""
        mw = self._get_middleware()
        assert mw.is_high_risk("/api/v1/admin", "DELETE") is True

    def test_regular_endpoint_not_high_risk(self) -> None:
        """GET /api/v1/sessions (ordinary read) must NOT be high-risk."""
        mw = self._get_middleware()
        assert mw.is_high_risk("/api/v1/sessions", "GET") is False

    def test_wildcard_path_matching(self) -> None:
        """Wildcard patterns like /api/v1/agents/*/settings must match."""
        mw = self._get_middleware()
        # e.g. /api/v1/agents/abc-123/settings with PUT should be high-risk
        assert mw.is_high_risk("/api/v1/agents/abc-123/settings", "PUT") is True

    def test_method_matching_is_case_insensitive(self) -> None:
        """Method matching must be case-insensitive (post == POST)."""
        mw = self._get_middleware()
        assert mw.is_high_risk("/api/v1/payments", "post") is True
        assert mw.is_high_risk("/api/v1/payments", "Post") is True
        assert mw.is_high_risk("/api/v1/payments", "POST") is True


# ---------------------------------------------------------------------------
# TestGovernanceFlow — 8 tests
# ---------------------------------------------------------------------------


class TestGovernanceFlow:
    """Verify the middleware request flow: high-risk → bridge call → allow/deny."""

    def _build_app_with_middleware(
        self,
        *,
        bridge_client_mock: MagicMock | None = None,
        enabled: bool = True,
    ) -> Starlette:
        """Return a Starlette ASGI app wrapped with GovernanceMiddleware."""
        from isg_agent.middleware.governance_middleware import GovernanceMiddleware

        app = Starlette(routes=[
            Route("/api/v1/payments", _simple_handler, methods=["POST", "GET"]),
            Route("/api/v1/sessions", _simple_handler, methods=["GET"]),
        ])
        mw = GovernanceMiddleware(
            app,
            bridge_token="test-tok",
            enabled=enabled,
        )
        if bridge_client_mock is not None:
            mw._bridge_client = bridge_client_mock
        return mw

    @pytest.mark.asyncio
    async def test_high_risk_request_calls_bridge_governance(self) -> None:
        """A POST to a high-risk path must call the bridge governance method."""
        bridge_mock = AsyncMock()
        bridge_mock.governance_check = AsyncMock(
            return_value=_make_governance_result(cleared=True)
        )

        app = self._build_app_with_middleware(bridge_client_mock=bridge_mock)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/payments")

        bridge_mock.governance_check.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleared_request_passes_through(self) -> None:
        """Governance CLEARED → request proceeds, response is 200."""
        bridge_mock = AsyncMock()
        bridge_mock.governance_check = AsyncMock(
            return_value=_make_governance_result(cleared=True)
        )

        app = self._build_app_with_middleware(bridge_client_mock=bridge_mock)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/payments")

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_denied_request_returns_403(self) -> None:
        """Governance DENIED → middleware returns 403 before handler executes."""
        bridge_mock = AsyncMock()
        bridge_mock.governance_check = AsyncMock(
            return_value=_make_governance_result(cleared=False, reason="policy block")
        )

        app = self._build_app_with_middleware(bridge_client_mock=bridge_mock)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/payments")

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_403_response_includes_denial_reason(self) -> None:
        """403 response body must contain the governance denial reason."""
        bridge_mock = AsyncMock()
        bridge_mock.governance_check = AsyncMock(
            return_value=_make_governance_result(
                cleared=False, reason="lockdown active"
            )
        )

        app = self._build_app_with_middleware(bridge_client_mock=bridge_mock)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/payments")

        body = resp.json()
        assert "governance" in body.get("detail", "").lower() or "denied" in body.get("detail", "").lower()

    @pytest.mark.asyncio
    async def test_non_high_risk_request_skips_governance(self) -> None:
        """A GET to a non-high-risk path must NOT call the bridge at all."""
        bridge_mock = AsyncMock()
        bridge_mock.governance_check = AsyncMock(
            return_value=_make_governance_result(cleared=True)
        )

        app = self._build_app_with_middleware(bridge_client_mock=bridge_mock)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/sessions")

        bridge_mock.governance_check.assert_not_called()
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_product_context_includes_agent1(self) -> None:
        """Governance call context must include product='agent1'."""
        captured: list[Any] = []

        async def _capturing_governance_check(tool, action, context):
            captured.append(context)
            return _make_governance_result(cleared=True)

        bridge_mock = AsyncMock()
        bridge_mock.governance_check = _capturing_governance_check

        app = self._build_app_with_middleware(bridge_client_mock=bridge_mock)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/api/v1/payments")

        assert len(captured) == 1
        assert captured[0].get("product") == "agent1"

    @pytest.mark.asyncio
    async def test_user_id_extracted_from_request(self) -> None:
        """If Authorization header is present, user_id must appear in context."""
        captured: list[Any] = []

        async def _capturing_governance_check(tool, action, context):
            captured.append(context)
            return _make_governance_result(cleared=True)

        bridge_mock = AsyncMock()
        bridge_mock.governance_check = _capturing_governance_check

        app = self._build_app_with_middleware(bridge_client_mock=bridge_mock)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/v1/payments",
                headers={"Authorization": "Bearer user-jwt-token-here"},
            )

        assert len(captured) == 1
        # user_id must be present in the context (may be the raw token or extracted sub)
        assert "user_id" in captured[0]

    @pytest.mark.asyncio
    async def test_timestamp_included_in_context(self) -> None:
        """Governance context must include a timestamp field."""
        captured: list[Any] = []

        async def _capturing_governance_check(tool, action, context):
            captured.append(context)
            return _make_governance_result(cleared=True)

        bridge_mock = AsyncMock()
        bridge_mock.governance_check = _capturing_governance_check

        app = self._build_app_with_middleware(bridge_client_mock=bridge_mock)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/api/v1/payments")

        assert len(captured) == 1
        assert "timestamp" in captured[0]


# ---------------------------------------------------------------------------
# TestFailureModes — 6 tests
# ---------------------------------------------------------------------------


class TestFailureModes:
    """Verify fail-open (soft mode) and disabled middleware behavior."""

    def _build_app_with_middleware(
        self,
        *,
        bridge_client_mock: MagicMock | None = None,
        enabled: bool = True,
    ) -> Any:
        """Return a GovernanceMiddleware-wrapped Starlette app."""
        from isg_agent.middleware.governance_middleware import GovernanceMiddleware

        inner = Starlette(routes=[
            Route("/api/v1/payments", _simple_handler, methods=["POST"]),
            Route("/api/v1/config", _simple_handler, methods=["PUT"]),
        ])
        mw = GovernanceMiddleware(inner, bridge_token="test-tok", enabled=enabled)
        if bridge_client_mock is not None:
            mw._bridge_client = bridge_client_mock
        return mw

    @pytest.mark.asyncio
    async def test_bridge_unreachable_allows_request(self) -> None:
        """If bridge is unreachable (connection error), request must PASS through (fail-open)."""
        from isg_agent.integrations.mila_bridge import MiLABridgeConnectionError

        bridge_mock = AsyncMock()
        bridge_mock.governance_check = AsyncMock(
            side_effect=MiLABridgeConnectionError("bridge is down")
        )

        app = self._build_app_with_middleware(bridge_client_mock=bridge_mock)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/payments")

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_bridge_timeout_allows_request_with_warning(self) -> None:
        """If bridge times out, request must PASS through (fail-open soft mode)."""
        from isg_agent.integrations.mila_bridge import MiLABridgeTimeoutError

        bridge_mock = AsyncMock()
        bridge_mock.governance_check = AsyncMock(
            side_effect=MiLABridgeTimeoutError("bridge timed out")
        )

        app = self._build_app_with_middleware(bridge_client_mock=bridge_mock)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/payments")

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_bridge_auth_error_allows_request_with_warning(self) -> None:
        """If bridge returns auth error (401), request must PASS through (fail-open)."""
        from isg_agent.integrations.mila_bridge import MiLABridgeAuthError

        bridge_mock = AsyncMock()
        bridge_mock.governance_check = AsyncMock(
            side_effect=MiLABridgeAuthError("bad token")
        )

        app = self._build_app_with_middleware(bridge_client_mock=bridge_mock)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/payments")

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_disabled_middleware_passes_everything(self) -> None:
        """When enabled=False, all requests (including high-risk) must pass without bridge call."""
        bridge_mock = AsyncMock()
        bridge_mock.governance_check = AsyncMock(
            return_value=_make_governance_result(cleared=True)
        )

        app = self._build_app_with_middleware(
            bridge_client_mock=bridge_mock, enabled=False
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/payments")

        bridge_mock.governance_check.assert_not_called()
        assert resp.status_code == 200

    def test_env_var_disables_middleware(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """GOVERNANCE_MIDDLEWARE_ENABLED=false env var must disable governance checks."""
        monkeypatch.setenv("GOVERNANCE_MIDDLEWARE_ENABLED", "false")

        from isg_agent.middleware.governance_middleware import GovernanceMiddleware

        app_mock = MagicMock()
        mw = GovernanceMiddleware(app_mock, bridge_token="tok")
        assert mw._enabled is False

    @pytest.mark.asyncio
    async def test_governance_decisions_are_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """Every governance decision (CLEARED or DENIED) must produce a log entry."""
        import logging

        bridge_mock = AsyncMock()
        bridge_mock.governance_check = AsyncMock(
            return_value=_make_governance_result(cleared=True)
        )

        from isg_agent.middleware.governance_middleware import GovernanceMiddleware

        inner = Starlette(routes=[
            Route("/api/v1/payments", _simple_handler, methods=["POST"]),
        ])
        mw = GovernanceMiddleware(inner, bridge_token="tok", enabled=True)
        mw._bridge_client = bridge_mock

        transport = ASGITransport(app=mw)
        with caplog.at_level(logging.INFO, logger="isg_agent.middleware.governance_middleware"):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post("/api/v1/payments")

        # At least one log record must mention governance
        governance_logs = [
            r for r in caplog.records
            if "governance" in r.message.lower() or "cleared" in r.message.lower()
        ]
        assert len(governance_logs) >= 1


# ---------------------------------------------------------------------------
# TestMiddlewareIntegration — 5 tests
# ---------------------------------------------------------------------------


class TestMiddlewareIntegration:
    """Verify correct ASGI wrapping, concurrency safety, and response preservation."""

    def _build_app(
        self,
        *,
        bridge_mock: MagicMock | None = None,
    ) -> Any:
        from isg_agent.middleware.governance_middleware import GovernanceMiddleware

        inner = Starlette(routes=[
            Route("/api/v1/payments", _simple_handler, methods=["POST", "GET"]),
            Route("/api/v1/sessions", _simple_handler, methods=["GET"]),
            Route("/api/v1/config", _simple_handler, methods=["PUT"]),
            Route("/echo", _echo_handler, methods=["GET"]),
        ])
        mw = GovernanceMiddleware(inner, bridge_token="tok", enabled=True)
        if bridge_mock is not None:
            mw._bridge_client = bridge_mock
        return mw

    @pytest.mark.asyncio
    async def test_middleware_wraps_fastapi_app_correctly(self) -> None:
        """GovernanceMiddleware must behave as a valid ASGI middleware (wraps app)."""
        bridge_mock = AsyncMock()
        bridge_mock.governance_check = AsyncMock(
            return_value=_make_governance_result(cleared=True)
        )
        app = self._build_app(bridge_mock=bridge_mock)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/sessions")

        # Must return a real HTTP response, not crash
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_multiple_requests_handled_independently(self) -> None:
        """Sequential requests to different endpoints must each be handled correctly."""
        bridge_mock = AsyncMock()
        bridge_mock.governance_check = AsyncMock(
            return_value=_make_governance_result(cleared=True)
        )
        app = self._build_app(bridge_mock=bridge_mock)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r1 = await client.get("/api/v1/sessions")   # non-high-risk
            r2 = await client.post("/api/v1/payments")  # high-risk, cleared
            r3 = await client.get("/api/v1/sessions")   # non-high-risk again

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r3.status_code == 200
        # Bridge should only be called for the high-risk request
        assert bridge_mock.governance_check.call_count == 1

    @pytest.mark.asyncio
    async def test_concurrent_requests_do_not_interfere(self) -> None:
        """Concurrent requests must not share state or corrupt each other."""
        call_count = 0

        async def _counting_governance_check(tool, action, context):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.01)  # simulate async work
            return _make_governance_result(cleared=True)

        bridge_mock = AsyncMock()
        bridge_mock.governance_check = _counting_governance_check

        app = self._build_app(bridge_mock=bridge_mock)
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Fire 5 concurrent high-risk requests
            tasks = [client.post("/api/v1/payments") for _ in range(5)]
            responses = await asyncio.gather(*tasks)

        # All 5 must succeed
        for resp in responses:
            assert resp.status_code == 200
        # Bridge called exactly once per request
        assert call_count == 5

    @pytest.mark.asyncio
    async def test_headers_preserved_through_middleware(self) -> None:
        """Custom request headers must be visible to the inner handler."""
        bridge_mock = AsyncMock()
        bridge_mock.governance_check = AsyncMock(
            return_value=_make_governance_result(cleared=True)
        )
        app = self._build_app(bridge_mock=bridge_mock)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/echo", headers={"x-custom": "preserved-value"})

        assert resp.status_code == 200
        assert resp.json().get("x-custom") == "preserved-value"

    @pytest.mark.asyncio
    async def test_response_body_unchanged_when_allowed(self) -> None:
        """When governance clears a request, the handler's original response body must be returned."""
        bridge_mock = AsyncMock()
        bridge_mock.governance_check = AsyncMock(
            return_value=_make_governance_result(cleared=True)
        )
        app = self._build_app(bridge_mock=bridge_mock)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/payments")

        # The simple handler returns plain text "ok"
        assert resp.text == "ok"
