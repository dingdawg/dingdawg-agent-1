"""Agent management endpoints: CRUD, handle claiming, and DID resolution.

Provides the HTTP API for creating, listing, retrieving, updating, and
deleting user-owned agents.  Also exposes a public handle-availability
check endpoint and DID resolution endpoint.

All mutating endpoints require authentication via JWT Bearer token.
The handle-check and DID resolution endpoints are public (no auth required).
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from isg_agent.api.deps import CurrentUser, require_auth
from isg_agent.middleware.rate_limiter_middleware import auth_rate_limit, public_rate_limit
from isg_agent.agents.agent_registry import AgentRegistry
from isg_agent.agents.agent_types import VALID_AGENT_TYPES
from isg_agent.agents.handle_service import HandleService
from isg_agent.schemas.agents import (
    AgentCreate,
    AgentList,
    AgentResponse,
    AgentUpdate,
    HandleCheckResponse,
)

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


# ---------------------------------------------------------------------------
# Helpers: extract registries from app state
# ---------------------------------------------------------------------------


def _get_agent_registry(request: Request) -> AgentRegistry:
    """Extract the AgentRegistry from FastAPI app state.

    Raises 503 Service Unavailable if the registry is not yet initialised.
    """
    registry: Optional[AgentRegistry] = getattr(
        request.app.state, "agent_registry", None
    )
    if registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent registry not initialised. Server is starting up.",
        )
    return registry


def _get_handle_service(request: Request) -> HandleService:
    """Extract the HandleService from FastAPI app state.

    Raises 503 Service Unavailable if the service is not yet initialised.
    """
    handle_svc: Optional[HandleService] = getattr(
        request.app.state, "handle_service", None
    )
    if handle_svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Handle service not initialised. Server is starting up.",
        )
    return handle_svc


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
        config_json=getattr(agent, "config_json", None),
        branding_json=getattr(agent, "branding_json", None),
        status=agent.status.value,
        subscription_tier=agent.subscription_tier.value,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


# ---------------------------------------------------------------------------
# Public endpoint: handle availability check (no auth required)
# ---------------------------------------------------------------------------


@router.get(
    "/handle/{handle}/check",
    response_model=HandleCheckResponse,
    summary="Check if a handle is available",
)
@public_rate_limit()
async def check_handle_availability(
    handle: str,
    request: Request,
    response: Response,
) -> HandleCheckResponse:
    """Check whether a given @handle is available to claim.

    This endpoint is public — no authentication required.

    Returns 200 with ``available: true`` if the handle is free,
    ``available: false`` if it is already taken or reserved.
    """
    handle_svc = _get_handle_service(request)

    # Validate format first — invalid handles are never "available"
    valid, _ = HandleService.validate_handle(handle)
    if not valid:
        return HandleCheckResponse(handle=handle, available=False)

    available = await handle_svc.is_available(handle)
    return HandleCheckResponse(handle=handle, available=available)


# ---------------------------------------------------------------------------
# Authenticated endpoints: agent CRUD
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=AgentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new agent",
)
@auth_rate_limit()
async def create_agent(
    body: AgentCreate,
    request: Request,
    response: Response,
    user: CurrentUser = Depends(require_auth),
) -> AgentResponse:
    """Create a new personal or business agent for the authenticated user.

    The creation process:
    1. Validate handle naming rules.
    2. Check handle availability.
    3. Reserve the handle (atomic lock).
    4. Create the agent record.
    5. Claim the handle, binding it to the new agent.
    6. If any step after reservation fails, the handle is released.

    Returns 409 if the handle is already taken.
    Returns 422 if the handle format is invalid (caught by Pydantic).
    """
    registry = _get_agent_registry(request)
    handle_svc = _get_handle_service(request)

    handle = body.handle

    # Step 1: Validate handle naming rules
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
            detail=f"Handle '{handle}' is already taken.",
        )

    # Step 3: Reserve the handle
    reserved = await handle_svc.reserve_handle(handle)
    if not reserved:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Handle '{handle}' could not be reserved. It may have just been claimed.",
        )

    # Steps 4 + 5: Create agent and claim handle (release handle on failure)
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
            "create_agent: unexpected error after handle reservation "
            "for user=%s handle=%s: %s",
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
        # Agent exists but handle claim failed — release handle and log warning
        await handle_svc.release_handle(handle)
        logger.warning(
            "create_agent: handle claim failed after agent creation "
            "agent_id=%s handle=%s — handle released",
            agent.id,
            handle,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Agent created but handle claim failed. Please try again.",
        )

    # Step 6: Auto-create DID for the new agent (fail-open — never blocks creation)
    did_manager = getattr(request.app.state, "did_manager", None)
    if did_manager is not None:
        try:
            did_manager.create_did(handle=handle, owner_id=user.user_id)
            logger.info(
                "DID auto-created for agent: handle=%s user=%s",
                handle,
                user.user_id,
            )
        except ValueError as _did_val_err:
            # DID already exists for this handle — not an error on retry
            logger.debug(
                "DID already exists for handle=%s (skipping): %s", handle, _did_val_err
            )
        except Exception as _did_exc:
            logger.warning(
                "DID auto-creation failed for handle=%s (fail-open, agent created): %s",
                handle,
                _did_exc,
            )

    logger.info(
        "Agent created: id=%s handle=%s type=%s user=%s",
        agent.id,
        handle,
        body.agent_type,
        user.user_id,
    )
    return _agent_to_response(agent)


@router.get(
    "",
    response_model=AgentList,
    summary="List agents for the authenticated user",
)
@auth_rate_limit()
async def list_agents(
    request: Request,
    response: Response,
    agent_type: Optional[str] = None,
    user: CurrentUser = Depends(require_auth),
) -> AgentList:
    """Return all non-archived agents belonging to the authenticated user.

    Optionally filter by ``agent_type`` query parameter (``"personal"`` or ``"business"``).
    """
    registry = _get_agent_registry(request)

    # Validate agent_type filter if provided
    if agent_type is not None and agent_type not in VALID_AGENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "agent_type must be one of: "
                + ", ".join(f"'{t}'" for t in sorted(VALID_AGENT_TYPES))
            ),
        )

    agents = await registry.list_agents(user_id=user.user_id, agent_type=agent_type)
    items = [_agent_to_response(a) for a in agents]
    return AgentList(agents=items, count=len(items))


@router.get(
    "/{agent_id}",
    response_model=AgentResponse,
    summary="Get a single agent by ID",
)
@auth_rate_limit()
async def get_agent(
    agent_id: str,
    request: Request,
    response: Response,
    user: CurrentUser = Depends(require_auth),
) -> AgentResponse:
    """Retrieve a single agent by its UUID.

    Returns 404 if the agent does not exist or belongs to another user.
    """
    registry = _get_agent_registry(request)

    agent = await registry.get_agent(agent_id)
    if agent is None or agent.user_id != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent not found: {agent_id}",
        )

    return _agent_to_response(agent)


@router.patch(
    "/{agent_id}",
    response_model=AgentResponse,
    summary="Update an agent",
)
@auth_rate_limit()
async def update_agent(
    agent_id: str,
    body: AgentUpdate,
    request: Request,
    response: Response,
    user: CurrentUser = Depends(require_auth),
) -> AgentResponse:
    """Update mutable fields on an agent.

    Only the authenticated owner can update their agent.
    Returns 404 if the agent does not exist or belongs to another user.
    Returns 400 if no updatable fields are provided.
    """
    registry = _get_agent_registry(request)

    # Verify ownership
    agent = await registry.get_agent(agent_id)
    if agent is None or agent.user_id != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent not found: {agent_id}",
        )

    # Build update kwargs from non-None fields
    updates: dict[str, object] = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.branding_json is not None:
        updates["branding_json"] = body.branding_json
    if body.config_json is not None:
        updates["config_json"] = body.config_json

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No updatable fields provided.",
        )

    try:
        updated = await registry.update_agent(agent_id, **updates)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent not found: {agent_id}",
        )

    # Fetch the updated record to return
    refreshed = await registry.get_agent(agent_id)
    if refreshed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent not found after update: {agent_id}",
        )

    logger.info("Agent updated: id=%s user=%s fields=%s", agent_id, user.user_id, list(updates.keys()))
    return _agent_to_response(refreshed)


@router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Archive (soft-delete) an agent",
)
@auth_rate_limit()
async def delete_agent(
    agent_id: str,
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> Response:
    """Soft-delete an agent by setting its status to ``"archived"``.

    Only the authenticated owner can archive their agent.
    Returns 404 if the agent does not exist or belongs to another user.
    """
    registry = _get_agent_registry(request)

    # Verify ownership before archiving
    agent = await registry.get_agent(agent_id)
    if agent is None or agent.user_id != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent not found: {agent_id}",
        )

    archived = await registry.delete_agent(agent_id)
    if not archived:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent not found: {agent_id}",
        )

    logger.info("Agent archived: id=%s user=%s", agent_id, user.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Public endpoint: DID document resolution by handle
# ---------------------------------------------------------------------------


@router.get(
    "/handle/{handle}/did",
    summary="Resolve agent DID document by handle",
    tags=["agents", "did"],
)
@public_rate_limit()
async def get_agent_did_by_handle(
    handle: str,
    request: Request,
) -> JSONResponse:
    """Return the W3C DID Core 1.0 document for an agent identified by handle.

    This endpoint is PUBLIC — no authentication required.

    The DID format resolved is: ``did:web:app.dingdawg.com:agents:<handle>``

    Returns 404 if no DID exists for the given handle.
    Returns 503 if the DID system is unavailable.
    """
    did_manager = getattr(request.app.state, "did_manager", None)

    if did_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DID system unavailable",
        )

    agent_did = f"did:web:app.dingdawg.com:agents:{handle}"
    try:
        doc = did_manager.resolve_did(agent_did)
    except Exception as exc:
        logger.error(
            "DID resolution error for handle=%s: %s", handle, exc
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DID resolution failed",
        ) from exc

    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"DID not found for handle: {handle}",
        )

    logger.debug("Agent DID resolved: handle=%s", handle)
    return JSONResponse(
        content=doc.to_json(),
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=300",
            "Content-Type": "application/did+json",
        },
    )
