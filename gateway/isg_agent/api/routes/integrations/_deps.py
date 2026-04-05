"""Shared FastAPI dependency helpers for the notify-integrations routes.

Each helper raises ``HTTPException(503)`` if the corresponding connector
has not been initialised on ``app.state``.  Ownership verification raises
``HTTPException(404)`` to avoid leaking whether an agent_id exists.

No route definitions in this file — pure helpers.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException, Request, status

from isg_agent.api.deps import CurrentUser
from isg_agent.agents.agent_registry import AgentRegistry
from isg_agent.integrations.email_sendgrid import SendGridConnector
from isg_agent.integrations.google_calendar import GoogleCalendarConnector
from isg_agent.integrations.sms_twilio import TwilioConnector
from isg_agent.integrations.voice_vapi import VapiConnector

logger = logging.getLogger(__name__)


def _get_sendgrid(request: Request) -> SendGridConnector:
    """Extract the SendGridConnector from FastAPI app state.

    Raises 503 if not yet initialised.
    """
    sg: Optional[SendGridConnector] = getattr(request.app.state, "sendgrid", None)
    if sg is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email integration not initialised. Server is starting up.",
        )
    return sg


def _get_twilio(request: Request) -> TwilioConnector:
    """Extract the TwilioConnector from FastAPI app state.

    Raises 503 if not yet initialised.
    """
    tw: Optional[TwilioConnector] = getattr(request.app.state, "twilio", None)
    if tw is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SMS integration not initialised. Server is starting up.",
        )
    return tw


def _get_agent_registry(request: Request) -> AgentRegistry:
    """Extract the AgentRegistry from FastAPI app state.

    Raises 503 if not yet initialised.
    """
    registry: Optional[AgentRegistry] = getattr(request.app.state, "agent_registry", None)
    if registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent registry not initialised. Server is starting up.",
        )
    return registry


def _get_vapi(request: Request) -> VapiConnector:
    """Extract the VapiConnector from FastAPI app state.

    Raises 503 if not yet initialised.
    """
    vapi: Optional[VapiConnector] = getattr(request.app.state, "vapi", None)
    if vapi is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice integration not initialised. Server is starting up.",
        )
    return vapi


def _get_google_calendar(request: Request) -> GoogleCalendarConnector:
    """Extract the GoogleCalendarConnector from FastAPI app state.

    Raises 503 if not yet initialised.
    """
    gcal: Optional[GoogleCalendarConnector] = getattr(request.app.state, "google_calendar", None)
    if gcal is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar integration not initialised. Server is starting up.",
        )
    return gcal


async def _verify_agent_ownership(
    agent_id: str,
    user: CurrentUser,
    registry: AgentRegistry,
) -> None:
    """Verify that *user* owns *agent_id*.

    Raises 404 if the agent does not exist or belongs to a different user
    (ownership is enforced by returning 404, not 403, to avoid leaking
    whether the agent_id exists at all).
    """
    agent = await registry.get_agent(agent_id)
    if agent is None or agent.user_id != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent not found: {agent_id}",
        )
