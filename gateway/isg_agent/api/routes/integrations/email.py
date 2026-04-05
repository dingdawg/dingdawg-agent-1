"""Email (SendGrid) integration endpoints.

Routes
------
POST   /api/v1/integrations/{agent_id}/email  — configure SendGrid
GET    /api/v1/integrations/{agent_id}/email  — get email status
DELETE /api/v1/integrations/{agent_id}/email  — disconnect email
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, status

from isg_agent.api.deps import CurrentUser, require_auth

from ._deps import _get_agent_registry, _get_sendgrid, _verify_agent_ownership
from ._schemas import EmailConfigRequest

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/{agent_id}/email",
    status_code=status.HTTP_201_CREATED,
    summary="Configure SendGrid email for an agent",
)
async def configure_email(
    agent_id: str,
    body: EmailConfigRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    """Store per-agent SendGrid configuration.

    Replaces any existing config for this agent (upsert semantics).
    Returns 201 on success with non-sensitive config details.
    Returns 404 if the agent does not exist or belongs to another user.

    The ``api_key`` is stored server-side and is **never** returned in
    any GET response.
    """
    registry = _get_agent_registry(request)
    await _verify_agent_ownership(agent_id, current_user, registry)

    sg = _get_sendgrid(request)
    result = await sg.configure(
        agent_id=agent_id,
        api_key=body.api_key,
        from_email=body.from_email,
        from_name=body.from_name or "",
    )

    logger.info(
        "POST /integrations/%s/email: configured by user=%s from_email=%s",
        agent_id, current_user.user_id, body.from_email,
    )
    return {
        "agent_id": agent_id,
        "connected": True,
        "from_email": result["from_email"],
    }


@router.get(
    "/{agent_id}/email",
    status_code=status.HTTP_200_OK,
    summary="Get email integration status for an agent",
)
async def get_email_config(
    agent_id: str,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    """Return the email integration status for an agent.

    Returns whether email is configured and the sender address.
    The ``api_key`` is **never** included in the response.
    Returns 404 if the agent does not exist or belongs to another user.
    """
    registry = _get_agent_registry(request)
    await _verify_agent_ownership(agent_id, current_user, registry)

    sg = _get_sendgrid(request)
    cfg = await sg.get_config(agent_id)

    if cfg is None:
        return {"agent_id": agent_id, "connected": False, "from_email": None, "from_name": None}

    return {
        "agent_id": agent_id,
        "connected": True,
        "from_email": cfg["from_email"],
        "from_name": cfg["from_name"],
    }


@router.delete(
    "/{agent_id}/email",
    status_code=status.HTTP_200_OK,
    summary="Disconnect email integration for an agent",
)
async def disconnect_email(
    agent_id: str,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    """Soft-delete the SendGrid configuration for an agent.

    Returns 200 with ``{"status": "disconnected"}`` whether or not email
    was previously configured (idempotent).
    Returns 404 if the agent does not exist or belongs to another user.
    """
    registry = _get_agent_registry(request)
    await _verify_agent_ownership(agent_id, current_user, registry)

    sg = _get_sendgrid(request)
    await sg.disconnect(agent_id)

    logger.info(
        "DELETE /integrations/%s/email: disconnected by user=%s",
        agent_id, current_user.user_id,
    )
    return {"agent_id": agent_id, "status": "disconnected"}
