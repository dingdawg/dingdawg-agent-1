"""Marketplace API routes: community template listing, install, and review.

Provides the HTTP API for the DingDawg Agent 1 template marketplace:

Public (no auth):
  GET  /api/v1/marketplace/templates             — browse approved listings
  GET  /api/v1/marketplace/templates/{id}        — get single listing

Authenticated:
  POST /api/v1/marketplace/templates             — create listing
  PUT  /api/v1/marketplace/templates/{id}        — update listing (author only)
  POST /api/v1/marketplace/templates/{id}/submit — submit for review
  POST /api/v1/marketplace/templates/{id}/install — install template
  POST /api/v1/marketplace/templates/{id}/rate   — rate (must have installed)
  POST /api/v1/marketplace/templates/{id}/fork   — fork listing
  GET  /api/v1/marketplace/my-templates          — list own listings
  GET  /api/v1/marketplace/earnings              — creator earnings

Admin:
  POST /api/v1/marketplace/admin/{id}/approve    — approve listing
  POST /api/v1/marketplace/admin/{id}/reject     — reject listing with reason
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from isg_agent.api.deps import CurrentUser, get_current_user, require_auth
from isg_agent.templates.marketplace_registry import MarketplaceRegistry

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/marketplace", tags=["marketplace"])

# ---------------------------------------------------------------------------
# Admin user list — configurable via MARKETPLACE_ADMIN_USERS env var
# (comma-separated user IDs).  Falls back to empty list (no admins).
# ---------------------------------------------------------------------------

_ADMIN_USERS: set[str] = set(
    uid.strip()
    for uid in os.environ.get("MARKETPLACE_ADMIN_USERS", "").split(",")
    if uid.strip()
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class CreateListingRequest(BaseModel):
    """Request body for creating a new marketplace listing."""

    base_template_id: str
    display_name: str
    tagline: str = ""
    description_md: str = ""
    agent_type: str
    industry_type: Optional[str] = None
    price_cents: int = Field(default=0, ge=0)
    tags: list[str] = Field(default_factory=list)
    preview_json: dict[str, Any] = Field(default_factory=dict)


class UpdateListingRequest(BaseModel):
    """Request body for updating a draft/rejected listing."""

    display_name: Optional[str] = None
    tagline: Optional[str] = None
    description_md: Optional[str] = None
    agent_type: Optional[str] = None
    industry_type: Optional[str] = None
    price_cents: Optional[int] = Field(default=None, ge=0)
    tags: Optional[list[str]] = None
    preview_json: Optional[dict[str, Any]] = None


class InstallRequest(BaseModel):
    """Request body for installing a marketplace template."""

    agent_id: str
    payment_intent_id: Optional[str] = None


class RateRequest(BaseModel):
    """Request body for rating a marketplace template."""

    stars: int = Field(ge=1, le=5)
    review_text: Optional[str] = None


class ForkRequest(BaseModel):
    """Request body for forking a marketplace template."""

    display_name: str


class RejectRequest(BaseModel):
    """Request body for rejecting a marketplace template."""

    reason: str


# ---------------------------------------------------------------------------
# Helper: extract MarketplaceRegistry from app state
# ---------------------------------------------------------------------------


def _get_registry(request: Request) -> MarketplaceRegistry:
    """Extract the MarketplaceRegistry from FastAPI app state.

    Raises 503 Service Unavailable if not yet initialised.
    """
    registry: Optional[MarketplaceRegistry] = getattr(
        request.app.state, "marketplace_registry", None
    )
    if registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Marketplace registry not initialised. Server is starting up.",
        )
    return registry


def _require_admin(user: CurrentUser) -> None:
    """Raise 403 if the user is not in the admin list."""
    if _ADMIN_USERS and user.user_id not in _ADMIN_USERS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    # If _ADMIN_USERS is empty (not configured) we allow any authenticated
    # user to act as admin — suitable for early development / single-operator
    # deployments.  Set MARKETPLACE_ADMIN_USERS in production.


# ---------------------------------------------------------------------------
# Public endpoints (no auth)
# ---------------------------------------------------------------------------


@router.get(
    "/templates",
    summary="Browse marketplace listings",
)
async def list_listings(
    request: Request,
    agent_type: Optional[str] = Query(default=None),
    industry_type: Optional[str] = Query(default=None),
    sort: str = Query(default="newest", pattern="^(newest|oldest|top_rated|most_installed)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """Return a paginated list of approved marketplace listings.

    This endpoint is public — no authentication required.

    Query parameters:
    - ``agent_type``: filter by agent type
    - ``industry_type``: filter by industry slug
    - ``sort``: newest | oldest | top_rated | most_installed
    - ``page``: 1-based page number
    - ``page_size``: results per page (max 100)
    """
    registry = _get_registry(request)
    return await registry.list_listings(
        status="approved",
        agent_type=agent_type,
        industry_type=industry_type,
        sort=sort,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/templates/{listing_id}",
    summary="Get a single marketplace listing",
)
async def get_listing(
    listing_id: str,
    request: Request,
) -> dict[str, Any]:
    """Retrieve a single marketplace listing by ID.

    This endpoint is public — no authentication required.

    Returns 404 if the listing does not exist.
    """
    registry = _get_registry(request)
    listing = await registry.get_listing(listing_id)
    if listing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Listing not found: {listing_id}",
        )
    return listing


# ---------------------------------------------------------------------------
# Authenticated endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/templates",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new marketplace listing",
)
async def create_listing(
    body: CreateListingRequest,
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> dict[str, Any]:
    """Create a new marketplace listing in draft status.

    Requires authentication.
    """
    registry = _get_registry(request)
    try:
        listing = await registry.create_listing(
            base_template_id=body.base_template_id,
            author_user_id=user.user_id,
            display_name=body.display_name,
            tagline=body.tagline,
            description_md=body.description_md,
            agent_type=body.agent_type,
            industry_type=body.industry_type,
            price_cents=body.price_cents,
            tags=body.tags,
            preview_json=body.preview_json,
        )
    except Exception as exc:
        logger.error("create_listing error user=%s: %s", user.user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create listing.",
        ) from exc

    return listing


@router.put(
    "/templates/{listing_id}",
    summary="Update a draft or rejected marketplace listing",
)
async def update_listing(
    listing_id: str,
    body: UpdateListingRequest,
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> dict[str, Any]:
    """Update mutable fields on a draft or rejected listing.

    Only the author can update their own listing.
    Returns 403 if the requester is not the author.
    Returns 400 if the listing is not in an editable status.
    """
    registry = _get_registry(request)

    # Build kwargs from non-None fields only
    updates: dict[str, Any] = {}
    for field in (
        "display_name", "tagline", "description_md", "agent_type",
        "industry_type", "price_cents", "tags", "preview_json",
    ):
        val = getattr(body, field)
        if val is not None:
            updates[field] = val

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No updatable fields provided.",
        )

    try:
        updated = await registry.update_listing(
            listing_id=listing_id,
            author_user_id=user.user_id,
            **updates,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return updated


@router.post(
    "/templates/{listing_id}/submit",
    summary="Submit a listing for marketplace review",
)
async def submit_listing(
    listing_id: str,
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> dict[str, Any]:
    """Transition a draft or rejected listing to submitted status.

    Only the author can submit their listing.
    """
    registry = _get_registry(request)
    try:
        updated = await registry.submit_for_review(
            listing_id=listing_id,
            author_user_id=user.user_id,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return updated


@router.post(
    "/templates/{listing_id}/install",
    status_code=status.HTTP_201_CREATED,
    summary="Install a marketplace template",
)
async def install_template(
    listing_id: str,
    body: InstallRequest,
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> dict[str, Any]:
    """Record a template installation for the authenticated user.

    The target agent must be specified in the request body.
    For paid templates, provide the Stripe PaymentIntent ID.

    Returns 400 if the listing is not approved.
    """
    registry = _get_registry(request)
    try:
        install = await registry.install_template(
            listing_id=listing_id,
            installer_user_id=user.user_id,
            agent_id=body.agent_id,
            payment_intent_id=body.payment_intent_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.error("install_template error listing=%s user=%s: %s", listing_id, user.user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record installation.",
        ) from exc

    return install


@router.post(
    "/templates/{listing_id}/rate",
    summary="Rate a marketplace template",
)
async def rate_template(
    listing_id: str,
    body: RateRequest,
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> dict[str, Any]:
    """Add or update a star rating for a marketplace listing.

    The rating is upserted (one rating per user per listing).
    Returns 400 if stars is out of range or the listing does not exist.
    """
    registry = _get_registry(request)
    try:
        rating = await registry.rate_template(
            listing_id=listing_id,
            user_id=user.user_id,
            stars=body.stars,
            review_text=body.review_text,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return rating


@router.post(
    "/templates/{listing_id}/fork",
    status_code=status.HTTP_201_CREATED,
    summary="Fork a marketplace template",
)
async def fork_template(
    listing_id: str,
    body: ForkRequest,
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> dict[str, Any]:
    """Clone an approved listing into a new draft owned by the requester.

    Returns 400 if the source listing is not approved.
    """
    registry = _get_registry(request)
    try:
        fork = await registry.fork_template(
            listing_id=listing_id,
            forker_user_id=user.user_id,
            display_name=body.display_name,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return fork


@router.get(
    "/my-templates",
    summary="List the authenticated user's marketplace listings",
)
async def my_templates(
    request: Request,
    status_filter: Optional[str] = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(require_auth),
) -> dict[str, Any]:
    """Return all marketplace listings authored by the authenticated user.

    Optionally filter by status (draft, submitted, approved, etc.).
    """
    registry = _get_registry(request)
    result = await registry.list_listings(
        status=status_filter,
        page=page,
        page_size=page_size,
    )

    # Filter to this user's listings only
    result["items"] = [
        item for item in result["items"]
        if item.get("author_user_id") == user.user_id
    ]
    result["total"] = len(result["items"])
    return result


@router.get(
    "/earnings",
    summary="Get creator earnings for the authenticated user",
)
async def get_earnings(
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> dict[str, Any]:
    """Return aggregated earnings and install stats for the authenticated creator."""
    registry = _get_registry(request)
    return await registry.get_creator_earnings(user_id=user.user_id)


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/admin/{listing_id}/approve",
    summary="[Admin] Approve a marketplace listing",
)
async def admin_approve(
    listing_id: str,
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> dict[str, Any]:
    """Approve a submitted or under-review listing for public display.

    Requires admin access (user_id in MARKETPLACE_ADMIN_USERS env var).
    """
    _require_admin(user)
    registry = _get_registry(request)
    try:
        updated = await registry.approve(
            listing_id=listing_id,
            reviewer_id=user.user_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return updated


@router.post(
    "/admin/{listing_id}/reject",
    summary="[Admin] Reject a marketplace listing",
)
async def admin_reject(
    listing_id: str,
    body: RejectRequest,
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> dict[str, Any]:
    """Reject a submitted or under-review listing with a reason.

    Requires admin access (user_id in MARKETPLACE_ADMIN_USERS env var).
    The rejection reason is shown to the author so they can revise and resubmit.
    """
    _require_admin(user)
    registry = _get_registry(request)
    try:
        updated = await registry.reject(
            listing_id=listing_id,
            reviewer_id=user.user_id,
            reason=body.reason,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return updated
