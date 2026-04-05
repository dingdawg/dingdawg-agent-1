"""Onboarding wizard endpoints for the DingDawg Agent 1 /claim flow.

Provides the HTTP API for the 3-step onboarding wizard:
- Sector discovery (public, no auth)
- Handle availability check (public, no auth, rate-limited)
- Agent claim / creation (auth required)

The sectors endpoint returns the 8 sectors (including Gaming as a mapped
variant of the 'business' agent_type) with visual metadata for the frontend
sector grid.

The check-handle endpoint duplicates the logic from the agents router but
adds a ``reason`` field explaining why an invalid handle is unavailable —
giving the frontend better UX feedback without extra round trips.

The claim endpoint wraps the full agent creation flow (validate → reserve →
create → claim) behind the onboarding-friendly request/response shape.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from isg_agent.agents.agent_types import VALID_AGENT_TYPES
from isg_agent.agents.handle_service import HandleService
from isg_agent.api.deps import CurrentUser, require_auth
from isg_agent.schemas.agents import AgentResponse

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/onboarding", tags=["onboarding"])

# ---------------------------------------------------------------------------
# Sector metadata (static, driven by VALID_AGENT_TYPES + Gaming special case)
# ---------------------------------------------------------------------------

_SECTORS = [
    {
        "id": "personal",
        "name": "Personal",
        "agent_type": "personal",
        "icon": "👤",
        "description": "Your private AI assistant for daily tasks, research, and productivity.",
        "popular": False,
    },
    {
        "id": "business",
        "name": "Business",
        "agent_type": "business",
        "icon": "🏪",
        "description": "An AI agent for your business — orders, customer service, scheduling.",
        "popular": True,
    },
    {
        "id": "b2b",
        "name": "B2B",
        "agent_type": "b2b",
        "icon": "🤝",
        "description": "Business-to-business workflows: procurement, vendor management, supply chain.",
        "popular": False,
    },
    {
        "id": "a2a",
        "name": "A2A",
        "agent_type": "a2a",
        "icon": "🔗",
        "description": "Agent-to-agent coordination: task orchestration, payment relay, automation.",
        "popular": False,
    },
    {
        "id": "compliance",
        "name": "Compliance",
        "agent_type": "compliance",
        "icon": "🛡️",
        "description": "Governance-first agents for regulated industries: FERPA, HIPAA, COPPA.",
        "popular": False,
    },
    {
        "id": "enterprise",
        "name": "Enterprise",
        "agent_type": "enterprise",
        "icon": "🏢",
        "description": "Multi-location coordination, field service dispatch, and enterprise ops.",
        "popular": False,
    },
    {
        "id": "health",
        "name": "Health",
        "agent_type": "health",
        "icon": "🏥",
        "description": "Patient scheduling, pharmacy refills, wellness coaching and care coordination.",
        "popular": False,
    },
    {
        "id": "gaming",
        "name": "Gaming",
        "agent_type": "business",  # Maps to 'business' until gaming AgentType lands
        "icon": "🎮",
        "description": "Game coaching, guild management, stream copilot, and tournament direction.",
        "popular": True,
    },
]


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class SectorItem(BaseModel):
    """A single sector entry returned by GET /api/v1/onboarding/sectors."""

    id: str
    name: str
    agent_type: str
    icon: str
    description: str
    popular: bool = False


class SectorList(BaseModel):
    """Response envelope for the sectors list."""

    sectors: list[SectorItem]
    count: int


class HandleAvailabilityResponse(BaseModel):
    """Response for GET /api/v1/onboarding/check-handle/{handle}.

    Extends the base HandleCheckResponse with an optional ``reason`` field
    that explains why a handle is unavailable (invalid format, reserved word,
    already taken, etc.).  The frontend uses this to show inline error messages
    without a second API call.
    """

    handle: str
    available: bool
    reason: Optional[str] = None


class ClaimAgentRequest(BaseModel):
    """Request body for POST /api/v1/onboarding/claim.

    The onboarding-specific create payload.  Accepts all 7 valid agent types
    (personal, business, b2b, a2a, compliance, enterprise, health).  Gaming
    is mapped to 'business' on the frontend before this call is made.
    """

    handle: str = Field(
        ...,
        min_length=3,
        max_length=30,
        pattern=r"^[a-z][a-z0-9-]*[a-z0-9]$",
        description="Unique @handle (lowercase letters, numbers, hyphens).",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Display name for the agent.",
    )
    agent_type: str = Field(
        ...,
        pattern="^(" + "|".join(sorted(VALID_AGENT_TYPES)) + ")$",
        description=(
            "Agent type. Valid values: "
            + ", ".join(f"'{t}'" for t in sorted(VALID_AGENT_TYPES))
        ),
    )
    industry_type: Optional[str] = Field(
        default=None,
        description="Optional industry category slug (e.g. 'restaurant', 'gaming').",
    )
    template_id: Optional[str] = Field(
        default=None,
        description="Optional template UUID to base the agent on.",
    )
    branding_json: Optional[str] = Field(
        default="{}",
        description="JSON string of branding/theming settings.",
    )


# ---------------------------------------------------------------------------
# Helpers: extract services from app state
# ---------------------------------------------------------------------------


def _get_handle_service(request: Request) -> HandleService:
    """Extract the HandleService from app state."""
    svc: Optional[HandleService] = getattr(request.app.state, "handle_service", None)
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Handle service not initialised.",
        )
    return svc


def _get_agent_registry(request: Request):  # type: ignore[return]
    """Extract the AgentRegistry from app state."""
    from isg_agent.agents.agent_registry import AgentRegistry

    registry: Optional[AgentRegistry] = getattr(
        request.app.state, "agent_registry", None
    )
    if registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent registry not initialised.",
        )
    return registry


def _agent_to_response(agent) -> AgentResponse:  # type: ignore[no-untyped-def]
    """Convert an AgentRecord to an AgentResponse DTO."""
    return AgentResponse(
        id=agent.id,
        user_id=agent.user_id,
        handle=agent.handle,
        name=agent.name,
        agent_type=agent.agent_type.value,
        industry_type=agent.industry_type,
        template_id=agent.template_id,
        status=agent.status.value,
        subscription_tier=agent.subscription_tier.value,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/onboarding/sectors
# ---------------------------------------------------------------------------


@router.get(
    "/sectors",
    response_model=SectorList,
    summary="List all onboarding sectors with display metadata",
)
async def list_sectors() -> SectorList:
    """Return all 8 sectors available in the onboarding wizard.

    This endpoint is public — no authentication required.

    Each sector includes:
    - ``id``: slug used for filtering templates
    - ``name``: human-readable display name
    - ``agent_type``: the VALID_AGENT_TYPES value this sector maps to
    - ``icon``: emoji icon for the sector card
    - ``description``: short description shown in the sector grid
    - ``popular``: True for sectors recommended for most users
    """
    items = [SectorItem(**s) for s in _SECTORS]
    return SectorList(sectors=items, count=len(items))


# ---------------------------------------------------------------------------
# GET /api/v1/onboarding/check-handle/{handle}
# ---------------------------------------------------------------------------


@router.get(
    "/check-handle/{handle}",
    response_model=HandleAvailabilityResponse,
    summary="Check handle availability for onboarding (public, no auth)",
)
async def check_handle_availability(
    handle: str,
    request: Request,
) -> HandleAvailabilityResponse:
    """Check whether a given @handle is available to claim.

    Public endpoint — no authentication required.  Called during the onboarding
    wizard step 3 (handle selection) with a 300ms debounce.

    Returns 200 in all cases:
    - ``available: true`` — handle is free to claim
    - ``available: false`` — handle is taken, reserved, or invalid format
    - ``reason`` — optional human-readable explanation (set when format is invalid)

    Handle naming rules (from HandleService.validate_handle):
    - 3–30 characters
    - Must start with a letter
    - May only contain lowercase letters, numbers, and hyphens
    - Cannot end with a hyphen
    - Cannot contain consecutive hyphens
    - Cannot be a reserved word (admin, system, etc.)
    """
    handle_svc = _get_handle_service(request)

    # Validate format first — invalid handles are never "available"
    valid, reason = HandleService.validate_handle(handle)
    if not valid:
        logger.debug("check_handle: invalid format handle=%s reason=%s", handle, reason)
        return HandleAvailabilityResponse(handle=handle, available=False, reason=reason)

    available = await handle_svc.is_available(handle)
    reason_msg = None if available else "This handle is already taken."
    logger.debug("check_handle: handle=%s available=%s", handle, available)
    return HandleAvailabilityResponse(
        handle=handle,
        available=available,
        reason=reason_msg,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/onboarding/claim
# ---------------------------------------------------------------------------


@router.post(
    "/claim",
    response_model=AgentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Claim a handle and create an agent (onboarding)",
)
async def claim_agent(
    body: ClaimAgentRequest,
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> AgentResponse:
    """Create a new agent via the onboarding wizard.

    AUTH REQUIRED — returns 401 if no valid JWT is present.

    This endpoint orchestrates the full agent creation flow:
    1. Validate handle naming rules (422 on invalid format)
    2. Check handle availability (409 if taken)
    3. Reserve the handle (atomic lock, 409 on race condition)
    4. Create the agent record in the database
    5. Claim the handle, binding it to the new agent

    If any step after reservation fails, the handle reservation is released
    so it can be retried.

    Returns 201 with the created AgentResponse on success.
    Returns 409 if the handle is already taken or just claimed by another user.
    Returns 422 if the handle format is invalid or required fields are missing.
    """
    registry = _get_agent_registry(request)
    handle_svc = _get_handle_service(request)

    handle = body.handle

    # Step 1: Validate handle format
    valid, reason = HandleService.validate_handle(handle)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid handle: {reason}",
        )

    # Step 2: Check availability
    available = await handle_svc.is_available(handle)
    if not available:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Handle '@{handle}' is already taken. Please choose a different handle.",
        )

    # Step 3: Reserve the handle (prevents race conditions)
    reserved = await handle_svc.reserve_handle(handle)
    if not reserved:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Handle '@{handle}' was just claimed. Please choose a different handle.",
        )

    # Steps 4 + 5: Create agent, claim handle (release on any failure)
    try:
        agent = await registry.create_agent(
            user_id=user.user_id,
            handle=handle,
            name=body.name,
            agent_type=body.agent_type,
            industry_type=body.industry_type,
            template_id=body.template_id,
            branding_json=body.branding_json or "{}",
        )
    except ValueError as exc:
        await handle_svc.release_handle(handle)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        await handle_svc.release_handle(handle)
        logger.error(
            "onboarding/claim: unexpected error for user=%s handle=%s: %s",
            user.user_id,
            handle,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create agent. Handle has been released.",
        ) from exc

    # Step 5: Claim the handle for the new agent
    claimed = await handle_svc.claim_handle(handle, agent.id)
    if not claimed:
        await handle_svc.release_handle(handle)
        logger.warning(
            "onboarding/claim: handle claim failed after agent creation "
            "agent_id=%s handle=%s — handle released",
            agent.id,
            handle,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Agent created but handle claim failed. Please try again.",
        )

    logger.info(
        "Onboarding claim: agent created id=%s handle=%s type=%s user=%s",
        agent.id,
        handle,
        body.agent_type,
        user.user_id,
    )
    return _agent_to_response(agent)
