"""DD Main integration endpoints.

Provides a REST API so that DingDawg Main can register and manage its
businesses as Agent 1 agents.

All endpoints are protected by JWT Bearer authentication (``require_auth``).
The bridge is stored on ``app.state.ddmain_bridge`` after lifespan startup.

Routes
------
POST   /api/v1/integrations/ddmain/register              — register a business
POST   /api/v1/integrations/ddmain/sync                  — sync updates
GET    /api/v1/integrations/ddmain/businesses            — list registered
GET    /api/v1/integrations/ddmain/businesses/{id}       — get one mapping
DELETE /api/v1/integrations/ddmain/businesses/{id}       — unregister
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from isg_agent.api.deps import CurrentUser, require_auth
from isg_agent.integrations.ddmain_bridge import DDMainBridge
from isg_agent.schemas.integrations import (
    BusinessMappingList,
    BusinessMappingResponse,
    BusinessRegisterRequest,
    BusinessRegisterResponse,
    BusinessSyncRequest,
    BusinessSyncResponse,
)

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/integrations/ddmain",
    tags=["integrations"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_bridge(request: Request) -> DDMainBridge:
    """Extract the DDMainBridge from FastAPI app state.

    Raises 503 if not yet initialised (server is still starting up).
    """
    bridge: Optional[DDMainBridge] = getattr(request.app.state, "ddmain_bridge", None)
    if bridge is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DD Main integration bridge not initialised. Server is starting up.",
        )
    return bridge


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/register",
    response_model=BusinessRegisterResponse,
    status_code=status.HTTP_200_OK,
    summary="Register or update a DD Main business as an Agent 1 agent",
)
async def register_business(
    body: BusinessRegisterRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> BusinessRegisterResponse:
    """Register a DD Main business as an Agent 1 agent.

    If the business is already registered (same ``business_id``), updates
    the existing agent with the latest data.  Returns HTTP 200 in both cases
    (``is_new`` in the response body distinguishes create vs. update).

    Requires a valid JWT Bearer token.
    """
    bridge = _get_bridge(request)
    try:
        result = await bridge.register_business(body.model_dump())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    logger.info(
        "POST /integrations/ddmain/register: business_id=%s user=%s is_new=%s",
        body.business_id, current_user.user_id, result["is_new"],
    )
    return BusinessRegisterResponse(**result)


@router.post(
    "/sync",
    response_model=BusinessSyncResponse,
    status_code=status.HTTP_200_OK,
    summary="Sync DD Main business updates to Agent 1",
)
async def sync_business(
    body: BusinessSyncRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> BusinessSyncResponse:
    """Sync updates from DD Main to the corresponding Agent 1 agent.

    Only provided fields are updated.  Unknown fields are ignored.
    Returns 404 if the business is not yet registered.

    Requires a valid JWT Bearer token.
    """
    bridge = _get_bridge(request)
    try:
        result = await bridge.sync_business(
            business_id=body.business_id,
            updates=body.model_dump(exclude={"business_id"}, exclude_none=True),
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    logger.info(
        "POST /integrations/ddmain/sync: business_id=%s fields=%s user=%s",
        body.business_id, result["updated_fields"], current_user.user_id,
    )
    return BusinessSyncResponse(**result)


@router.get(
    "/businesses",
    response_model=BusinessMappingList,
    status_code=status.HTTP_200_OK,
    summary="List all registered DD Main businesses",
)
async def list_businesses(
    request: Request,
    limit: int = 50,
    current_user: CurrentUser = Depends(require_auth),
) -> BusinessMappingList:
    """Return all active DD Main businesses registered in Agent 1.

    Removed (unregistered) businesses are excluded.
    ``limit`` controls the maximum number of results (default 50, max 200).

    Requires a valid JWT Bearer token.
    """
    if limit < 1:
        limit = 1
    if limit > 200:
        limit = 200

    bridge = _get_bridge(request)
    rows = await bridge.list_registered_businesses(limit=limit)

    mappings = [BusinessMappingResponse(**row) for row in rows]
    return BusinessMappingList(businesses=mappings, count=len(mappings))


@router.get(
    "/businesses/{business_id}",
    response_model=BusinessMappingResponse,
    status_code=status.HTTP_200_OK,
    summary="Get the Agent 1 mapping for a specific DD Main business",
)
async def get_business(
    business_id: str,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> BusinessMappingResponse:
    """Return the mapping record for a specific DD Main business.

    Returns 404 if the business is not registered.

    Requires a valid JWT Bearer token.
    """
    bridge = _get_bridge(request)
    mapping = await bridge.get_agent_for_business(business_id)

    if mapping is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Business {business_id!r} is not registered in Agent 1.",
        )

    return BusinessMappingResponse(**mapping)


@router.delete(
    "/businesses/{business_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Unregister a DD Main business from Agent 1",
)
async def unregister_business(
    business_id: str,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> Response:
    """Unregister a DD Main business from Agent 1.

    Archives the Agent 1 agent, releases its @handle, and marks the mapping
    as ``removed``.  Returns 204 on success, 404 if not found.

    Requires a valid JWT Bearer token.
    """
    bridge = _get_bridge(request)
    removed = await bridge.unregister_business(business_id)

    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Business {business_id!r} is not registered in Agent 1 "
                "or has already been removed."
            ),
        )

    logger.info(
        "DELETE /integrations/ddmain/businesses/%s: unregistered by user=%s",
        business_id, current_user.user_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
