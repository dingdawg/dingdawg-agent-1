"""Agentic Commerce Protocol (ACP) FastAPI route layer.

Wires the ACPCheckoutHandler into the FastAPI application, exposing
five endpoints under the ``/api/v1/acp`` prefix.

ACP spec version: 2026-01-30
Reference: https://github.com/agentic-commerce-protocol/agentic-commerce-protocol

Endpoint summary
----------------
POST   /api/v1/acp/checkout
    Create a new ACP checkout session.
    Authentication: BUSINESS tier (authenticated agent owners).

POST   /api/v1/acp/discount
    Apply a discount extension to an existing checkout session.
    Authentication: BUSINESS tier.

POST   /api/v1/acp/checkout/{session_id}/complete
    Complete a checkout session with payment data.
    Authentication: BUSINESS tier.

POST   /api/v1/acp/checkout/{session_id}/cancel
    Cancel an in-progress checkout session.
    Authentication: BUSINESS tier.

GET    /api/v1/acp/capabilities
    Return ACP capability advertisement for this platform.
    Authentication: PUBLIC (buyer agent discovery).

GET    /api/v1/acp/products
    Return the product catalog (available DingDawg plans).
    Authentication: PUBLIC (buyer agent discovery).

GET    /api/v1/acp/.well-known/acp-manifest
    ACP-compliant manifest document for automated discovery.
    Authentication: PUBLIC.

Tier isolation
--------------
- POST checkout / discount / complete / cancel   → _USER (authenticated)
- GET  capabilities / products / manifest        → _PUBLIC (no auth required)

This follows the same pattern as ``well_known.py``: public discovery
endpoints live under the ACP router but are freely accessible.

Error format
------------
All errors follow the ACP wire format from ACPError.to_dict():
    {"type": str, "code": str, "message": str, "param": str | null}

ACPError is mapped to HTTP status codes:
    invalid_request           → 400 / 404 (code == "not_found")
    request_not_idempotent    → 409
    processing_error          → 500
    service_unavailable       → 503
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from isg_agent.api.deps import CurrentUser, require_auth
from isg_agent.protocols.acp_handler import (
    ACPCheckoutHandler,
    ACPError,
    CancelCheckoutRequest,
    CompleteCheckoutRequest,
    CreateCheckoutRequest,
    UpdateCheckoutRequest,
    ACP_SPEC_VERSION,
)

__all__ = ["router"]

logger = logging.getLogger("isg_agent.api.routes.acp_routes")

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/v1/acp", tags=["acp"])

# ---------------------------------------------------------------------------
# Singleton ACPCheckoutHandler (one per process, merchant_id from env)
# ---------------------------------------------------------------------------
# The handler is intentionally module-level so it persists across requests
# within a single process.  In production, merchant_id is the Stripe Connect
# account ID configured on this deployment.
#
# CONCERN: The in-memory session store is not shared across Railway replicas.
# Until sessions are persisted to SQLite, horizontal scaling requires sticky
# sessions.  See acp_handler.py docstring for the production upgrade path.

_ACP_MERCHANT_ID: str = os.environ.get(
    "ISG_AGENT_ACP_MERCHANT_ID",
    os.environ.get("ISG_AGENT_STRIPE_MERCHANT_ID", "dingdawg_platform"),
)

_handler: Optional[ACPCheckoutHandler] = None


def _get_handler() -> ACPCheckoutHandler:
    """Return (or lazily create) the module-level ACPCheckoutHandler.

    Lazy construction lets tests override the merchant ID via environment
    variables before the first request.
    """
    global _handler  # noqa: PLW0603
    if _handler is None:
        merchant_id = os.environ.get(
            "ISG_AGENT_ACP_MERCHANT_ID",
            os.environ.get("ISG_AGENT_STRIPE_MERCHANT_ID", "dingdawg_platform"),
        )
        _handler = ACPCheckoutHandler(merchant_id=merchant_id)
        logger.info("ACP handler initialised — merchant_id=%s", merchant_id)
    return _handler


def _reset_handler() -> None:
    """Reset the module-level handler (test helper only)."""
    global _handler  # noqa: PLW0603
    _handler = None


# ---------------------------------------------------------------------------
# ACP error → HTTP status mapping
# ---------------------------------------------------------------------------

_ACP_ERROR_HTTP_STATUS: dict[str, int] = {
    "invalid_request": status.HTTP_400_BAD_REQUEST,
    "request_not_idempotent": status.HTTP_409_CONFLICT,
    "processing_error": status.HTTP_500_INTERNAL_SERVER_ERROR,
    "service_unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
}


def _acp_error_response(exc: ACPError) -> JSONResponse:
    """Convert an ACPError to an HTTP JSON response.

    Uses 404 for ``code == "not_found"`` (session not found) rather than
    the generic 400 so callers can distinguish missing resources from
    bad input.

    Parameters
    ----------
    exc:
        The ACPError raised by the handler.

    Returns
    -------
    JSONResponse
        ACP wire-format error body with the appropriate HTTP status code.
    """
    http_status = _ACP_ERROR_HTTP_STATUS.get(
        exc.error_type, status.HTTP_400_BAD_REQUEST
    )
    if exc.code == "not_found":
        http_status = status.HTTP_404_NOT_FOUND
    return JSONResponse(status_code=http_status, content={"error": exc.to_dict()})


# ---------------------------------------------------------------------------
# Request / response Pydantic models
# ---------------------------------------------------------------------------


class CheckoutLineItemRequest(BaseModel):
    """A single line item in a checkout request."""

    product_id: str = Field(..., min_length=1, description="Seller's product identifier.")
    title: str = Field(..., min_length=1, max_length=150, description="Display name.")
    quantity: int = Field(..., ge=1, description="Number of units (must be >= 1).")
    unit_amount: int = Field(..., ge=0, description="Price per unit in minor units (cents).")
    currency: Optional[str] = Field(
        default=None,
        min_length=3,
        max_length=3,
        description="ISO 4217 currency code (overrides session currency if set).",
    )


class CreateCheckoutBody(BaseModel):
    """Request body for POST /api/v1/acp/checkout."""

    line_items: list[CheckoutLineItemRequest] = Field(
        ..., min_length=1, description="Items to purchase (must not be empty)."
    )
    currency: str = Field(
        default="usd",
        min_length=3,
        max_length=3,
        description="ISO 4217 currency code for the session.",
    )
    idempotency_key: str = Field(
        ..., min_length=1, max_length=128, description="Unique key for idempotent retries."
    )
    merchant_id: Optional[str] = Field(
        default=None,
        description="Override merchant ID (defaults to platform merchant).",
    )


class ApplyDiscountBody(BaseModel):
    """Request body for POST /api/v1/acp/discount."""

    session_id: str = Field(..., min_length=1, description="Session to apply the discount to.")
    discount_code: str = Field(..., min_length=1, max_length=64, description="Discount code.")


class CompleteCheckoutBody(BaseModel):
    """Request body for POST /api/v1/acp/checkout/{session_id}/complete."""

    payment_data: dict[str, Any] = Field(
        ...,
        description=(
            "PSP payment data. Must include ``handler_id`` and ``payment_instrument``."
        ),
    )


class CancelCheckoutBody(BaseModel):
    """Request body for POST /api/v1/acp/checkout/{session_id}/cancel."""

    reason: Optional[str] = Field(
        default=None, max_length=500, description="Optional cancellation reason."
    )


# ---------------------------------------------------------------------------
# Helper: base URL extraction (same pattern as well_known.py)
# ---------------------------------------------------------------------------


def _get_base_url(request: Request) -> str:
    """Return the canonical public-facing base URL.

    Priority order (highest to lowest):
    1. ``ISG_AGENT_PUBLIC_URL`` / ``settings.public_url`` — explicitly
       configured canonical domain.  Must be set in production.
    2. Fallback: construct from request headers — local dev only.
    """
    from isg_agent.config import get_settings

    settings = get_settings()
    if settings.public_url:
        return settings.public_url.rstrip("/")
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", ""))
    if host:
        return f"{proto}://{host}"
    return str(request.base_url).rstrip("/")


# ---------------------------------------------------------------------------
# PUBLIC endpoints (buyer agent discovery — no auth required)
# ---------------------------------------------------------------------------


@router.get(
    "/capabilities",
    summary="ACP capability advertisement",
    response_description="ACPCapabilities block (spec v2026-01-30)",
)
async def get_capabilities() -> JSONResponse:
    """Return the ACP capability advertisement for this platform.

    Buyer agents (e.g. ChatGPT Instant Checkout) call this endpoint to
    discover which payment handlers and extensions DingDawg supports
    before initiating a checkout session.

    The response conforms to ACP spec v2026-01-30 ``capabilities`` block
    format::

        {
            "capabilities": {
                "payment": {"handlers": [...]},
                "extensions": ["discount"]
            },
            "acp_spec_version": "2026-01-30"
        }

    PUBLIC endpoint — no authentication required.

    Returns
    -------
    JSONResponse
        Capability advertisement with public CORS header and 5-minute cache.
    """
    handler = _get_handler()
    caps = handler.get_capabilities()
    return JSONResponse(
        content={
            "capabilities": caps.to_dict(),
            "acp_spec_version": ACP_SPEC_VERSION,
        },
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=300",
        },
    )


@router.get(
    "/products",
    summary="ACP product catalog",
    response_description="List of available DingDawg plans",
)
async def get_products() -> JSONResponse:
    """Return the product feed for buyer agents.

    Lists all DingDawg plans available for purchase via ACP.  Buyer agents
    use this feed to show product choices before initiating checkout.

    Each product follows the ACP product schema::

        {
            "id": str,
            "title": str,
            "description": str,
            "price": int,       # minor units (cents)
            "currency": str,    # ISO 4217 lowercase
            "availability": str # "in_stock" | "out_of_stock" | "preorder"
        }

    PUBLIC endpoint — no authentication required.

    Returns
    -------
    JSONResponse
        Product feed with ``products`` array and ``acp_spec_version`` field.
    """
    handler = _get_handler()
    products = handler.get_products()
    return JSONResponse(
        content={
            "products": [p.to_dict() for p in products],
            "count": len(products),
            "acp_spec_version": ACP_SPEC_VERSION,
        },
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=300",
        },
    )


@router.get(
    "/.well-known/acp-manifest",
    summary="ACP merchant manifest (discovery)",
    response_description="ACP-compliant merchant manifest for automated discovery",
)
async def acp_manifest(request: Request) -> JSONResponse:
    """Return the ACP merchant manifest for automated agent discovery.

    This document enables ACP-compatible buyer agents to discover this
    platform's checkout endpoint, capabilities, and supported extensions
    without any prior configuration.

    Document structure::

        {
            "acp_spec_version": "2026-01-30",
            "merchant": {...},
            "checkout_endpoint": "https://...",
            "capabilities": {...},
            "products_endpoint": "https://...",
            "extensions": ["discount"]
        }

    PUBLIC endpoint — no authentication required.
    Follows the same pattern as ``/.well-known/mcp.json``.

    Returns
    -------
    JSONResponse
        ACP manifest with public CORS header and 1-hour cache.
    """
    base_url = _get_base_url(request)
    handler = _get_handler()
    caps = handler.get_capabilities()

    manifest = {
        "acp_spec_version": ACP_SPEC_VERSION,
        "merchant": {
            "id": handler.merchant_id,
            "name": "DingDawg Agent Platform",
            "description": (
                "AI agent platform for businesses — "
                "claim your @handle, deploy in minutes. "
                "Supports ACP Instant Checkout (v2026-01-30)."
            ),
            "url": "https://dingdawg.com",
            "contact": "support@dingdawg.com",
        },
        "checkout_endpoint": f"{base_url}/api/v1/acp/checkout",
        "capabilities_endpoint": f"{base_url}/api/v1/acp/capabilities",
        "products_endpoint": f"{base_url}/api/v1/acp/products",
        "capabilities": caps.to_dict(),
        "extensions": caps.extensions,
        "currency": handler.currency,
        "compliance": {
            "openai_fee_percent": 4,
            "dingdawg_fee_per_action": 100,  # $1.00 in cents
            "note": (
                "OpenAI charges merchants 4% on Instant Checkout purchases. "
                "DingDawg's $1/action fee is additive."
            ),
        },
    }

    logger.debug("ACP manifest served to %s", request.client)
    return JSONResponse(
        content=manifest,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )


# ---------------------------------------------------------------------------
# AUTHENTICATED endpoints (BUSINESS tier — requires valid JWT)
# ---------------------------------------------------------------------------


@router.post(
    "/checkout",
    status_code=status.HTTP_201_CREATED,
    summary="Create ACP checkout session",
    response_description="New CheckoutSession in in_progress state",
)
async def create_checkout(
    body: CreateCheckoutBody,
    current_user: CurrentUser = Depends(require_auth),
) -> JSONResponse:
    """Create a new ACP checkout session.

    Idempotent on ``idempotency_key``.  Calling this endpoint twice with
    the same key returns the same session (HTTP 200) without creating a
    duplicate charge.

    Required fields:
    - ``line_items``: at least one item with ``product_id``, ``title``,
      ``quantity`` (>= 1), ``unit_amount`` (cents).
    - ``idempotency_key``: unique string for safe retries.

    Optional fields:
    - ``currency``: ISO 4217 code (default ``"usd"``).
    - ``merchant_id``: override the platform merchant (rarely needed).

    Returns
    -------
    JSONResponse (201 Created)
        Full CheckoutSession wire format including ``capabilities`` block.

    Raises
    ------
    400
        If line_items is empty or currency is invalid.
    422
        If the request body does not match the Pydantic schema.
    """
    handler = _get_handler()
    try:
        req = CreateCheckoutRequest(
            line_items=[item.model_dump(exclude_none=True) for item in body.line_items],
            currency=body.currency,
            idempotency_key=body.idempotency_key,
            merchant_id=body.merchant_id or handler.merchant_id,
        )
        session = handler.create_checkout_session(req)
    except ACPError as exc:
        return _acp_error_response(exc)
    except Exception as exc:
        logger.exception("ACP create_checkout unexpected error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error creating checkout session.",
        ) from exc

    logger.info(
        "ACP POST /checkout: session=%s user=%s total=%d %s",
        session.id,
        current_user.user_id,
        session.total,
        session.currency,
    )
    return JSONResponse(content=session.to_dict(), status_code=status.HTTP_201_CREATED)


@router.post(
    "/discount",
    status_code=status.HTTP_200_OK,
    summary="Apply discount extension to a checkout session",
    response_description="Updated CheckoutSession with discount applied",
)
async def apply_discount(
    body: ApplyDiscountBody,
    current_user: CurrentUser = Depends(require_auth),
) -> JSONResponse:
    """Apply a discount code to an existing checkout session.

    Implements the ACP v2026-01-30 ``"discount"`` extension.  The discount
    is applied by calling ``UpdateCheckoutSession`` under the hood, which
    recalculates the session total.

    Known discount codes (promotional):
    - ``SAVE10``       — 10% off
    - ``SAVE20``       — 20% off
    - ``FIRSTMONTH``   — 100% off (first month free)
    - ``AGENTLAUNCH``  — $5.00 off

    Unknown codes return the original total with no error (ACP spec allows
    sellers to silently ignore unrecognised codes).

    Returns
    -------
    JSONResponse (200 OK)
        Updated CheckoutSession wire format.

    Raises
    ------
    400
        If the session is in a terminal state.
    404
        If the session_id is not found.
    """
    handler = _get_handler()
    try:
        req = UpdateCheckoutRequest(
            session_id=body.session_id,
            discount_code=body.discount_code,
        )
        session = handler.update_checkout_session(req)
    except ACPError as exc:
        return _acp_error_response(exc)
    except Exception as exc:
        logger.exception("ACP apply_discount unexpected error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error applying discount.",
        ) from exc

    logger.info(
        "ACP POST /discount: session=%s code=%s discount=%d user=%s",
        session.id,
        body.discount_code,
        session.discount_amount,
        current_user.user_id,
    )
    return JSONResponse(content=session.to_dict(), status_code=status.HTTP_200_OK)


@router.post(
    "/checkout/{session_id}/complete",
    status_code=status.HTTP_200_OK,
    summary="Complete ACP checkout session with payment",
    response_description="Completed CheckoutSession with order_id",
)
async def complete_checkout(
    session_id: str,
    body: CompleteCheckoutBody,
    current_user: CurrentUser = Depends(require_auth),
) -> JSONResponse:
    """Complete an ACP checkout session by submitting payment.

    ``payment_data`` must include:
    - ``handler_id``: the payment handler to use (e.g. ``"card_tokenized"``).
    - ``payment_instrument``: PSP-specific payment credential (e.g.
      ``{"token": "tok_..."}``) obtained via the Delegated Payment Spec.

    On success the session transitions to ``completed`` and an ``order_id``
    is assigned.  Completed sessions are terminal — no further mutations are
    accepted.

    Returns
    -------
    JSONResponse (200 OK)
        Completed CheckoutSession with ``order_id``.

    Raises
    ------
    400
        If payment_data is missing required fields or session is not modifiable.
    404
        If the session_id is not found.
    """
    handler = _get_handler()
    try:
        req = CompleteCheckoutRequest(
            session_id=session_id,
            payment_data=body.payment_data,
        )
        session = handler.complete_checkout_session(req)
    except ACPError as exc:
        return _acp_error_response(exc)
    except Exception as exc:
        logger.exception("ACP complete_checkout unexpected error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error completing checkout session.",
        ) from exc

    logger.info(
        "ACP POST /checkout/%s/complete: order=%s user=%s total=%d",
        session_id,
        session.order_id,
        current_user.user_id,
        session.total,
    )
    return JSONResponse(content=session.to_dict(), status_code=status.HTTP_200_OK)


@router.post(
    "/checkout/{session_id}/cancel",
    status_code=status.HTTP_200_OK,
    summary="Cancel an ACP checkout session",
    response_description="Cancelled CheckoutSession",
)
async def cancel_checkout(
    session_id: str,
    body: CancelCheckoutBody,
    current_user: CurrentUser = Depends(require_auth),
) -> JSONResponse:
    """Cancel an in-progress ACP checkout session.

    Cancelled sessions are terminal — no further mutations are accepted.
    Calling this endpoint on an already-cancelled session returns 400.
    Calling on a completed session returns 400.

    Returns
    -------
    JSONResponse (200 OK)
        Cancelled CheckoutSession with ``status == "cancelled"``.

    Raises
    ------
    400
        If the session is already completed or cancelled.
    404
        If the session_id is not found.
    """
    handler = _get_handler()
    try:
        req = CancelCheckoutRequest(
            session_id=session_id,
            reason=body.reason,
        )
        session = handler.cancel_checkout_session(req)
    except ACPError as exc:
        return _acp_error_response(exc)
    except Exception as exc:
        logger.exception("ACP cancel_checkout unexpected error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error cancelling checkout session.",
        ) from exc

    logger.info(
        "ACP POST /checkout/%s/cancel: reason=%s user=%s",
        session_id,
        body.reason or "not provided",
        current_user.user_id,
    )
    return JSONResponse(content=session.to_dict(), status_code=status.HTTP_200_OK)
