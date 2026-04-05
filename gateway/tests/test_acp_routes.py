"""TDD test suite for ACP (Agentic Commerce Protocol) FastAPI routes.

Tests cover:
- Route registration (all 5 endpoint groups accessible)
- GET /api/v1/acp/capabilities  — PUBLIC, correct format
- GET /api/v1/acp/products      — PUBLIC, product feed
- GET /api/v1/acp/.well-known/acp-manifest — PUBLIC, discovery manifest
- POST /api/v1/acp/checkout     — create session (auth required, valid/invalid)
- POST /api/v1/acp/discount     — apply discount extension (auth required)
- POST /api/v1/acp/checkout/{id}/complete — complete session (auth required)
- POST /api/v1/acp/checkout/{id}/cancel  — cancel session (auth required)
- Tier isolation — PUBLIC routes work without auth, POST routes return 401 without auth
- Error handling — ACP error wire format for malformed requests and not-found
- Idempotency — duplicate create with same key returns same session
- Session state machine — cannot modify completed/cancelled sessions
- ACP spec compliance — acp_spec_version in all responses, capabilities block
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from isg_agent.api.routes.auth import _create_token
from isg_agent.config import get_settings

# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------

_SECRET = "test-secret-acp-routes-suite"
_USER_A = "user-acp-alpha"
_USER_B = "user-acp-beta"

_VALID_LINE_ITEMS = [
    {
        "product_id": "dingdawg_pro",
        "title": "DingDawg Pro Plan",
        "quantity": 1,
        "unit_amount": 2900,
    }
]

_VALID_PAYMENT_DATA = {
    "handler_id": "card_tokenized",
    "payment_instrument": {"token": "tok_test_12345"},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(user_id: str, email: str = "acp@example.com") -> str:
    return _create_token(user_id=user_id, email=email, secret_key=_SECRET)


def _auth(user_id: str = _USER_A) -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_token(user_id)}"}


def _idempotency_key() -> str:
    return f"test-idem-{uuid.uuid4().hex}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(tmp_path):
    """Async HTTP client with full app lifespan and isolated ACP handler."""
    db_file = str(tmp_path / "test_acp_routes.db")

    os.environ["ISG_AGENT_DB_PATH"] = db_file
    os.environ["ISG_AGENT_SECRET_KEY"] = _SECRET
    os.environ["ISG_AGENT_ACP_MERCHANT_ID"] = "test_merchant_acp"
    get_settings.cache_clear()

    # Reset module-level ACP handler so env override takes effect
    from isg_agent.api.routes.acp_routes import _reset_handler
    _reset_handler()

    from isg_agent.app import create_app, lifespan

    app = create_app()
    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    os.environ.pop("ISG_AGENT_DB_PATH", None)
    os.environ.pop("ISG_AGENT_SECRET_KEY", None)
    os.environ.pop("ISG_AGENT_ACP_MERCHANT_ID", None)
    get_settings.cache_clear()

    from isg_agent.api.routes.acp_routes import _reset_handler
    _reset_handler()


# ---------------------------------------------------------------------------
# Helper: create a checkout session via the API
# ---------------------------------------------------------------------------


async def _create_session(
    client: AsyncClient,
    *,
    line_items: list[dict] | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Create a checkout session and return the response body."""
    resp = await client.post(
        "/api/v1/acp/checkout",
        json={
            "line_items": line_items or _VALID_LINE_ITEMS,
            "currency": "usd",
            "idempotency_key": idempotency_key or _idempotency_key(),
        },
        headers=_auth(),
    )
    assert resp.status_code == 201, f"create_session failed: {resp.text}"
    return resp.json()


# ===========================================================================
# 1. Route Registration — verify all endpoint groups respond (not 404/405)
# ===========================================================================


@pytest.mark.asyncio
async def test_route_capabilities_registered(client):
    """GET /api/v1/acp/capabilities must be accessible (not 404/405)."""
    resp = await client.get("/api/v1/acp/capabilities")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_route_products_registered(client):
    """GET /api/v1/acp/products must be accessible."""
    resp = await client.get("/api/v1/acp/products")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_route_manifest_registered(client):
    """GET /api/v1/acp/.well-known/acp-manifest must be accessible."""
    resp = await client.get("/api/v1/acp/.well-known/acp-manifest")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_route_checkout_registered(client):
    """POST /api/v1/acp/checkout must be accessible (401 without auth, not 404)."""
    resp = await client.post("/api/v1/acp/checkout", json={})
    # Without auth → 401 or 422 (422 because Pydantic validates before auth dep on some routes)
    # Either is acceptable — the route IS registered
    assert resp.status_code in (401, 422), f"unexpected: {resp.status_code}"


@pytest.mark.asyncio
async def test_route_discount_registered(client):
    """POST /api/v1/acp/discount must be accessible (401 without auth)."""
    resp = await client.post("/api/v1/acp/discount", json={})
    assert resp.status_code in (401, 422)


@pytest.mark.asyncio
async def test_route_complete_registered(client):
    """POST /api/v1/acp/checkout/{session_id}/complete must be accessible."""
    resp = await client.post(
        "/api/v1/acp/checkout/acp_sess_nonexistent/complete",
        json={"payment_data": {}},
    )
    assert resp.status_code in (401, 422)


@pytest.mark.asyncio
async def test_route_cancel_registered(client):
    """POST /api/v1/acp/checkout/{session_id}/cancel must be accessible."""
    resp = await client.post(
        "/api/v1/acp/checkout/acp_sess_nonexistent/cancel",
        json={},
    )
    assert resp.status_code in (401, 422)


# ===========================================================================
# 2. GET /api/v1/acp/capabilities — PUBLIC, correct format
# ===========================================================================


@pytest.mark.asyncio
async def test_capabilities_public_no_auth_required(client):
    """Capabilities endpoint must respond 200 without any auth token."""
    resp = await client.get("/api/v1/acp/capabilities")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_capabilities_has_acp_spec_version(client):
    """Capabilities response must include acp_spec_version field."""
    resp = await client.get("/api/v1/acp/capabilities")
    data = resp.json()
    assert "acp_spec_version" in data
    assert data["acp_spec_version"] == "2026-01-30"


@pytest.mark.asyncio
async def test_capabilities_has_capabilities_block(client):
    """Capabilities response must include the ACP capabilities block."""
    resp = await client.get("/api/v1/acp/capabilities")
    data = resp.json()
    assert "capabilities" in data
    caps = data["capabilities"]
    assert "payment" in caps
    assert "handlers" in caps["payment"]
    assert "extensions" in caps


@pytest.mark.asyncio
async def test_capabilities_payment_handlers_present(client):
    """At least one payment handler must be declared."""
    resp = await client.get("/api/v1/acp/capabilities")
    handlers = resp.json()["capabilities"]["payment"]["handlers"]
    assert len(handlers) >= 1


@pytest.mark.asyncio
async def test_capabilities_handler_fields(client):
    """Each handler must have required ACP spec fields."""
    resp = await client.get("/api/v1/acp/capabilities")
    handler = resp.json()["capabilities"]["payment"]["handlers"][0]
    assert "id" in handler
    assert "name" in handler
    assert "version" in handler
    assert "psp" in handler
    assert "requires_delegate_payment" in handler


@pytest.mark.asyncio
async def test_capabilities_extensions_includes_discount(client):
    """Extensions list must include 'discount' (ACP v2026-01-30 requirement)."""
    resp = await client.get("/api/v1/acp/capabilities")
    extensions = resp.json()["capabilities"]["extensions"]
    assert "discount" in extensions


@pytest.mark.asyncio
async def test_capabilities_cors_header(client):
    """Capabilities endpoint must return public CORS header."""
    resp = await client.get("/api/v1/acp/capabilities")
    assert resp.headers.get("access-control-allow-origin") == "*"


# ===========================================================================
# 3. GET /api/v1/acp/products — PUBLIC, product feed
# ===========================================================================


@pytest.mark.asyncio
async def test_products_public_no_auth_required(client):
    """Products endpoint must respond 200 without auth."""
    resp = await client.get("/api/v1/acp/products")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_products_has_products_array(client):
    """Products response must include 'products' array."""
    resp = await client.get("/api/v1/acp/products")
    data = resp.json()
    assert "products" in data
    assert isinstance(data["products"], list)


@pytest.mark.asyncio
async def test_products_count_matches(client):
    """Products 'count' must match len(products)."""
    resp = await client.get("/api/v1/acp/products")
    data = resp.json()
    assert data["count"] == len(data["products"])


@pytest.mark.asyncio
async def test_products_each_has_required_fields(client):
    """Each product must have ACP-required fields."""
    resp = await client.get("/api/v1/acp/products")
    for product in resp.json()["products"]:
        assert "id" in product
        assert "title" in product
        assert "price" in product
        assert "currency" in product
        assert "availability" in product


@pytest.mark.asyncio
async def test_products_has_at_least_one_plan(client):
    """At least one DingDawg plan must be in the feed."""
    resp = await client.get("/api/v1/acp/products")
    assert len(resp.json()["products"]) >= 1


@pytest.mark.asyncio
async def test_products_prices_are_integers(client):
    """Product prices must be integers (minor units — cents)."""
    resp = await client.get("/api/v1/acp/products")
    for product in resp.json()["products"]:
        assert isinstance(product["price"], int)


@pytest.mark.asyncio
async def test_products_acp_spec_version_present(client):
    """Products response must carry acp_spec_version."""
    resp = await client.get("/api/v1/acp/products")
    assert resp.json().get("acp_spec_version") == "2026-01-30"


# ===========================================================================
# 4. GET /api/v1/acp/.well-known/acp-manifest — PUBLIC
# ===========================================================================


@pytest.mark.asyncio
async def test_manifest_public_no_auth(client):
    """ACP manifest must respond 200 without auth."""
    resp = await client.get("/api/v1/acp/.well-known/acp-manifest")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_manifest_has_spec_version(client):
    """Manifest must declare acp_spec_version."""
    resp = await client.get("/api/v1/acp/.well-known/acp-manifest")
    assert resp.json().get("acp_spec_version") == "2026-01-30"


@pytest.mark.asyncio
async def test_manifest_has_merchant_block(client):
    """Manifest must include merchant identity block."""
    resp = await client.get("/api/v1/acp/.well-known/acp-manifest")
    data = resp.json()
    assert "merchant" in data
    merchant = data["merchant"]
    assert "id" in merchant
    assert "name" in merchant


@pytest.mark.asyncio
async def test_manifest_has_checkout_endpoint(client):
    """Manifest must include checkout_endpoint URL."""
    resp = await client.get("/api/v1/acp/.well-known/acp-manifest")
    data = resp.json()
    assert "checkout_endpoint" in data
    assert "/api/v1/acp/checkout" in data["checkout_endpoint"]


@pytest.mark.asyncio
async def test_manifest_has_capabilities(client):
    """Manifest must include capabilities block."""
    resp = await client.get("/api/v1/acp/.well-known/acp-manifest")
    assert "capabilities" in resp.json()


@pytest.mark.asyncio
async def test_manifest_cors_header(client):
    """Manifest must return public CORS header."""
    resp = await client.get("/api/v1/acp/.well-known/acp-manifest")
    assert resp.headers.get("access-control-allow-origin") == "*"


# ===========================================================================
# 5. POST /api/v1/acp/checkout — Create checkout session
# ===========================================================================


@pytest.mark.asyncio
async def test_checkout_create_returns_201(client):
    """Valid checkout request must return 201 Created."""
    resp = await client.post(
        "/api/v1/acp/checkout",
        json={
            "line_items": _VALID_LINE_ITEMS,
            "currency": "usd",
            "idempotency_key": _idempotency_key(),
        },
        headers=_auth(),
    )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_checkout_create_response_has_session_id(client):
    """Checkout response must include a session id."""
    data = await _create_session(client)
    assert "id" in data
    assert data["id"].startswith("acp_sess_")


@pytest.mark.asyncio
async def test_checkout_create_status_in_progress(client):
    """New checkout session must have status 'in_progress'."""
    data = await _create_session(client)
    assert data["status"] == "in_progress"


@pytest.mark.asyncio
async def test_checkout_create_response_has_capabilities(client):
    """Checkout response must include capabilities block (spec requirement)."""
    data = await _create_session(client)
    assert "capabilities" in data
    assert "payment" in data["capabilities"]


@pytest.mark.asyncio
async def test_checkout_create_total_calculated(client):
    """Session total must equal quantity * unit_amount."""
    data = await _create_session(client)
    # 1 × 2900 = 2900
    assert data["total"] == 2900


@pytest.mark.asyncio
async def test_checkout_requires_auth(client):
    """Checkout POST must return 401 without Authorization header."""
    resp = await client.post(
        "/api/v1/acp/checkout",
        json={
            "line_items": _VALID_LINE_ITEMS,
            "currency": "usd",
            "idempotency_key": _idempotency_key(),
        },
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_checkout_empty_line_items_returns_error(client):
    """Empty line_items must return 422 (Pydantic) or 400 (ACP error)."""
    resp = await client.post(
        "/api/v1/acp/checkout",
        json={
            "line_items": [],
            "currency": "usd",
            "idempotency_key": _idempotency_key(),
        },
        headers=_auth(),
    )
    assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_checkout_missing_idempotency_key_returns_422(client):
    """Missing idempotency_key must return 422 (Pydantic validation)."""
    resp = await client.post(
        "/api/v1/acp/checkout",
        json={
            "line_items": _VALID_LINE_ITEMS,
            "currency": "usd",
        },
        headers=_auth(),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_checkout_idempotency_same_key_returns_same_session(client):
    """Two requests with the same idempotency_key must return the same session."""
    key = _idempotency_key()
    resp1 = await client.post(
        "/api/v1/acp/checkout",
        json={"line_items": _VALID_LINE_ITEMS, "currency": "usd", "idempotency_key": key},
        headers=_auth(),
    )
    resp2 = await client.post(
        "/api/v1/acp/checkout",
        json={"line_items": _VALID_LINE_ITEMS, "currency": "usd", "idempotency_key": key},
        headers=_auth(),
    )
    assert resp1.status_code in (200, 201)
    assert resp2.status_code in (200, 201)
    assert resp1.json()["id"] == resp2.json()["id"]


@pytest.mark.asyncio
async def test_checkout_acp_spec_version_in_response(client):
    """Checkout response must carry acp_spec_version."""
    data = await _create_session(client)
    assert data.get("acp_spec_version") == "2026-01-30"


# ===========================================================================
# 6. POST /api/v1/acp/discount — Apply discount extension
# ===========================================================================


@pytest.mark.asyncio
async def test_discount_applies_to_session(client):
    """SAVE10 discount must reduce the session total by 10%."""
    session = await _create_session(client)
    original_total = session["total"]

    resp = await client.post(
        "/api/v1/acp/discount",
        json={"session_id": session["id"], "discount_code": "SAVE10"},
        headers=_auth(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["discount_amount"] > 0
    assert data["total"] < original_total


@pytest.mark.asyncio
async def test_discount_unknown_code_no_error(client):
    """Unknown discount code must return 200 with no discount applied."""
    session = await _create_session(client)
    resp = await client.post(
        "/api/v1/acp/discount",
        json={"session_id": session["id"], "discount_code": "UNKNOWNCODE"},
        headers=_auth(),
    )
    assert resp.status_code == 200
    assert resp.json()["discount_amount"] == 0


@pytest.mark.asyncio
async def test_discount_requires_auth(client):
    """Discount POST must return 401 without Authorization header."""
    session = await _create_session(client)
    resp = await client.post(
        "/api/v1/acp/discount",
        json={"session_id": session["id"], "discount_code": "SAVE10"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_discount_nonexistent_session_returns_404(client):
    """Discount on a non-existent session must return 404."""
    resp = await client.post(
        "/api/v1/acp/discount",
        json={"session_id": "acp_sess_doesnotexist", "discount_code": "SAVE10"},
        headers=_auth(),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_discount_missing_fields_returns_422(client):
    """Missing discount_code must return 422."""
    resp = await client.post(
        "/api/v1/acp/discount",
        json={"session_id": "some_session"},
        headers=_auth(),
    )
    assert resp.status_code == 422


# ===========================================================================
# 7. POST /api/v1/acp/checkout/{id}/complete
# ===========================================================================


@pytest.mark.asyncio
async def test_complete_session_returns_200(client):
    """Completing a session with valid payment_data must return 200."""
    session = await _create_session(client)
    resp = await client.post(
        f"/api/v1/acp/checkout/{session['id']}/complete",
        json={"payment_data": _VALID_PAYMENT_DATA},
        headers=_auth(),
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_complete_session_status_is_completed(client):
    """Completed session must have status 'completed'."""
    session = await _create_session(client)
    resp = await client.post(
        f"/api/v1/acp/checkout/{session['id']}/complete",
        json={"payment_data": _VALID_PAYMENT_DATA},
        headers=_auth(),
    )
    assert resp.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_complete_session_has_order_id(client):
    """Completed session must carry an order_id."""
    session = await _create_session(client)
    resp = await client.post(
        f"/api/v1/acp/checkout/{session['id']}/complete",
        json={"payment_data": _VALID_PAYMENT_DATA},
        headers=_auth(),
    )
    data = resp.json()
    assert "order_id" in data
    assert data["order_id"] is not None


@pytest.mark.asyncio
async def test_complete_requires_auth(client):
    """Complete endpoint must return 401 without auth."""
    session = await _create_session(client)
    resp = await client.post(
        f"/api/v1/acp/checkout/{session['id']}/complete",
        json={"payment_data": _VALID_PAYMENT_DATA},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_complete_nonexistent_session_returns_404(client):
    """Completing a non-existent session must return 404."""
    resp = await client.post(
        "/api/v1/acp/checkout/acp_sess_doesnotexist/complete",
        json={"payment_data": _VALID_PAYMENT_DATA},
        headers=_auth(),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_complete_missing_handler_id_returns_400(client):
    """Missing handler_id in payment_data must return ACP 400 error."""
    session = await _create_session(client)
    resp = await client.post(
        f"/api/v1/acp/checkout/{session['id']}/complete",
        json={"payment_data": {"payment_instrument": {"token": "tok_test"}}},
        headers=_auth(),
    )
    assert resp.status_code == 400
    assert "error" in resp.json()


@pytest.mark.asyncio
async def test_complete_already_completed_session_returns_400(client):
    """Completing an already-completed session must return 400."""
    session = await _create_session(client)
    session_id = session["id"]
    # Complete once
    await client.post(
        f"/api/v1/acp/checkout/{session_id}/complete",
        json={"payment_data": _VALID_PAYMENT_DATA},
        headers=_auth(),
    )
    # Complete again — should fail
    resp = await client.post(
        f"/api/v1/acp/checkout/{session_id}/complete",
        json={"payment_data": _VALID_PAYMENT_DATA},
        headers=_auth(),
    )
    assert resp.status_code == 400


# ===========================================================================
# 8. POST /api/v1/acp/checkout/{id}/cancel
# ===========================================================================


@pytest.mark.asyncio
async def test_cancel_session_returns_200(client):
    """Cancelling an in-progress session must return 200."""
    session = await _create_session(client)
    resp = await client.post(
        f"/api/v1/acp/checkout/{session['id']}/cancel",
        json={},
        headers=_auth(),
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_cancel_session_status_is_cancelled(client):
    """Cancelled session must have status 'cancelled'."""
    session = await _create_session(client)
    resp = await client.post(
        f"/api/v1/acp/checkout/{session['id']}/cancel",
        json={},
        headers=_auth(),
    )
    assert resp.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_with_reason(client):
    """Cancel with a reason must succeed and return the cancelled session."""
    session = await _create_session(client)
    resp = await client.post(
        f"/api/v1/acp/checkout/{session['id']}/cancel",
        json={"reason": "User changed their mind"},
        headers=_auth(),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_requires_auth(client):
    """Cancel endpoint must return 401 without auth."""
    session = await _create_session(client)
    resp = await client.post(
        f"/api/v1/acp/checkout/{session['id']}/cancel",
        json={},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_cancel_nonexistent_session_returns_404(client):
    """Cancelling a non-existent session must return 404."""
    resp = await client.post(
        "/api/v1/acp/checkout/acp_sess_doesnotexist/cancel",
        json={},
        headers=_auth(),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cancel_already_completed_session_returns_400(client):
    """Cancelling a completed session must return 400."""
    session = await _create_session(client)
    session_id = session["id"]
    # Complete first
    await client.post(
        f"/api/v1/acp/checkout/{session_id}/complete",
        json={"payment_data": _VALID_PAYMENT_DATA},
        headers=_auth(),
    )
    # Now cancel — should fail
    resp = await client.post(
        f"/api/v1/acp/checkout/{session_id}/cancel",
        json={},
        headers=_auth(),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_cancel_already_cancelled_session_returns_400(client):
    """Cancelling an already-cancelled session must return 400."""
    session = await _create_session(client)
    session_id = session["id"]
    # Cancel once
    await client.post(
        f"/api/v1/acp/checkout/{session_id}/cancel", json={}, headers=_auth()
    )
    # Cancel again
    resp = await client.post(
        f"/api/v1/acp/checkout/{session_id}/cancel", json={}, headers=_auth()
    )
    assert resp.status_code == 400


# ===========================================================================
# 9. ACP error wire format
# ===========================================================================


@pytest.mark.asyncio
async def test_error_response_has_error_key(client):
    """ACP errors must be wrapped in an 'error' key."""
    resp = await client.post(
        "/api/v1/acp/checkout/acp_sess_notfound/complete",
        json={"payment_data": _VALID_PAYMENT_DATA},
        headers=_auth(),
    )
    assert resp.status_code == 404
    assert "error" in resp.json()


@pytest.mark.asyncio
async def test_error_response_has_type_code_message(client):
    """ACP error body must have 'type', 'code', and 'message' fields."""
    resp = await client.post(
        "/api/v1/acp/checkout/acp_sess_notfound/complete",
        json={"payment_data": _VALID_PAYMENT_DATA},
        headers=_auth(),
    )
    error = resp.json()["error"]
    assert "type" in error
    assert "code" in error
    assert "message" in error


@pytest.mark.asyncio
async def test_error_type_is_acp_spec_value(client):
    """ACP error 'type' must be one of the four spec-defined values."""
    resp = await client.post(
        "/api/v1/acp/discount",
        json={"session_id": "acp_sess_notfound", "discount_code": "SAVE10"},
        headers=_auth(),
    )
    valid_types = {
        "invalid_request", "request_not_idempotent",
        "processing_error", "service_unavailable",
    }
    error_type = resp.json()["error"]["type"]
    assert error_type in valid_types


# ===========================================================================
# 10. Tier isolation — PUBLIC vs AUTHENTICATED
# ===========================================================================


@pytest.mark.asyncio
async def test_tier_capabilities_is_public(client):
    """GET capabilities must NOT require auth (no 401/403)."""
    resp = await client.get("/api/v1/acp/capabilities")
    assert resp.status_code not in (401, 403)


@pytest.mark.asyncio
async def test_tier_products_is_public(client):
    """GET products must NOT require auth."""
    resp = await client.get("/api/v1/acp/products")
    assert resp.status_code not in (401, 403)


@pytest.mark.asyncio
async def test_tier_manifest_is_public(client):
    """GET manifest must NOT require auth."""
    resp = await client.get("/api/v1/acp/.well-known/acp-manifest")
    assert resp.status_code not in (401, 403)


@pytest.mark.asyncio
async def test_tier_checkout_requires_user(client):
    """POST checkout without auth must return 401."""
    resp = await client.post(
        "/api/v1/acp/checkout",
        json={
            "line_items": _VALID_LINE_ITEMS,
            "currency": "usd",
            "idempotency_key": _idempotency_key(),
        },
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_tier_discount_requires_user(client):
    """POST discount without auth must return 401."""
    resp = await client.post(
        "/api/v1/acp/discount",
        json={"session_id": "acp_sess_x", "discount_code": "SAVE10"},
    )
    assert resp.status_code == 401
