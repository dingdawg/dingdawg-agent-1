"""SMS (Twilio) integration endpoints.

Routes
------
POST   /api/v1/integrations/{agent_id}/sms  — configure Twilio
GET    /api/v1/integrations/{agent_id}/sms  — get SMS status
DELETE /api/v1/integrations/{agent_id}/sms  — disconnect SMS
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, status

from isg_agent.api.deps import CurrentUser, require_auth

from ._deps import _get_agent_registry, _get_twilio, _verify_agent_ownership
from ._schemas import SmsConfigRequest

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/{agent_id}/sms",
    status_code=status.HTTP_201_CREATED,
    summary="Configure Twilio SMS for an agent",
)
async def configure_sms(
    agent_id: str,
    body: SmsConfigRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    """Store per-agent Twilio configuration.

    Replaces any existing SMS config for this agent (upsert semantics).
    Returns 201 on success with non-sensitive config details.
    Returns 404 if the agent does not exist or belongs to another user.

    Neither ``account_sid`` nor ``auth_token`` are returned in any GET
    response.
    """
    registry = _get_agent_registry(request)
    await _verify_agent_ownership(agent_id, current_user, registry)

    tw = _get_twilio(request)
    result = await tw.configure(
        agent_id=agent_id,
        account_sid=body.account_sid,
        auth_token=body.auth_token,
        from_number=body.from_number,
    )

    logger.info(
        "POST /integrations/%s/sms: configured by user=%s from_number=%s",
        agent_id, current_user.user_id, body.from_number,
    )
    return {
        "agent_id": agent_id,
        "connected": True,
        "from_number": result["from_number"],
    }


@router.get(
    "/{agent_id}/sms",
    status_code=status.HTTP_200_OK,
    summary="Get SMS integration status for an agent",
)
async def get_sms_config(
    agent_id: str,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    """Return the SMS integration status for an agent.

    Returns whether SMS is configured and the source phone number.
    Credentials (``account_sid``, ``auth_token``) are **never** included
    in the response.
    Returns 404 if the agent does not exist or belongs to another user.
    """
    registry = _get_agent_registry(request)
    await _verify_agent_ownership(agent_id, current_user, registry)

    tw = _get_twilio(request)
    cfg = await tw.get_config(agent_id)

    if cfg is None:
        return {"agent_id": agent_id, "connected": False, "from_number": None}

    return {
        "agent_id": agent_id,
        "connected": True,
        "from_number": cfg["from_number"],
    }


@router.delete(
    "/{agent_id}/sms",
    status_code=status.HTTP_200_OK,
    summary="Disconnect SMS integration for an agent",
)
async def disconnect_sms(
    agent_id: str,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    """Soft-delete the Twilio configuration for an agent.

    Returns 200 with ``{"status": "disconnected"}`` whether or not SMS
    was previously configured (idempotent).
    Returns 404 if the agent does not exist or belongs to another user.
    """
    registry = _get_agent_registry(request)
    await _verify_agent_ownership(agent_id, current_user, registry)

    tw = _get_twilio(request)
    await tw.disconnect(agent_id)

    logger.info(
        "DELETE /integrations/%s/sms: disconnected by user=%s",
        agent_id, current_user.user_id,
    )
    return {"agent_id": agent_id, "status": "disconnected"}
