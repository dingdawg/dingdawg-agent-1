"""Voice (Vapi) integration endpoint.

Routes
------
POST /api/v1/integrations/{agent_id}/vapi/configure — configure Vapi voice
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, status

from isg_agent.api.deps import CurrentUser, require_auth

from ._deps import _get_agent_registry, _get_vapi, _verify_agent_ownership
from ._schemas import VapiConfigRequest

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/{agent_id}/vapi/configure",
    status_code=status.HTTP_200_OK,
    summary="Configure Vapi voice for an agent",
)
async def configure_vapi(
    agent_id: str,
    body: VapiConfigRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    """Store per-agent Vapi voice configuration.

    Creates a Vapi assistant if an API key is configured on the server.
    Otherwise stores the configuration locally for later activation.

    Returns 404 if the agent does not exist or belongs to another user.
    """
    registry = _get_agent_registry(request)
    await _verify_agent_ownership(agent_id, current_user, registry)

    vapi = _get_vapi(request)
    result = await vapi.configure_agent(
        agent_id,
        {
            "voice_model": body.voice_model or "eleven_multilingual_v2",
            "first_message": body.first_message or "Hi! How can I help you today?",
        },
    )

    logger.info(
        "POST /integrations/%s/vapi/configure: status=%s user=%s",
        agent_id, result.get("status"), current_user.user_id,
    )
    return {
        "agent_id": agent_id,
        "configured": True,
        "status": result.get("status", "pending_activation"),
        "voice_model": body.voice_model,
    }
