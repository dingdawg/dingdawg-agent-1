"""Generic disconnect, test, and frontend-alias routes.

Routes
------
POST /api/v1/integrations/{agent_id}/disconnect           — disconnect any integration
POST /api/v1/integrations/{agent_id}/test                 — send test message
POST /api/v1/integrations/{agent_id}/sendgrid/configure   — alias for /email (frontend compat)
POST /api/v1/integrations/{agent_id}/twilio/configure     — alias for /sms (frontend compat)
POST /api/v1/integrations/{agent_id}/google-calendar/connect    — alias for /google-calendar/auth-url
POST /api/v1/integrations/{agent_id}/google-calendar/callback   — legacy per-agent callback (deprecated)
"""

from __future__ import annotations

import logging

import aiosqlite
from datetime import datetime, timezone as _tz
from fastapi import APIRouter, Depends, HTTPException, Request, status

from isg_agent.api.deps import CurrentUser, require_auth

from ._deps import (
    _get_agent_registry,
    _get_google_calendar,
    _get_sendgrid,
    _get_twilio,
    _get_vapi,
    _verify_agent_ownership,
)
from ._schemas import (
    DisconnectRequest,
    EmailConfigRequest,
    GoogleCalendarCallbackRequest,
    SmsConfigRequest,
    TestIntegrationRequest,
)
from .email import configure_email
from .google_calendar import google_calendar_auth_url, google_calendar_callback
from .sms import configure_sms

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Disconnect map
# ---------------------------------------------------------------------------

_DISCONNECT_MAP = {
    "google_calendar": "google_calendar",
    "calendar": "google_calendar",
    "sendgrid": "sendgrid",
    "email": "sendgrid",
    "twilio": "twilio",
    "sms": "twilio",
    "vapi": "vapi",
    "voice": "vapi",
    # DD Main bridge is a system-level connection managed via DDMainBridge.
    # The user cannot directly disconnect it from the integration hub —
    # returning success here is a no-op that avoids a confusing 400 error.
    "dd_main_bridge": "dd_main_bridge",
}

# ---------------------------------------------------------------------------
# Test map
# ---------------------------------------------------------------------------

_TEST_MAP = {
    "sendgrid": "sendgrid",
    "email": "sendgrid",
    "twilio": "twilio",
    "sms": "twilio",
}


# ---------------------------------------------------------------------------
# Disconnect endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/{agent_id}/disconnect",
    status_code=status.HTTP_200_OK,
    summary="Disconnect an integration for an agent",
)
async def disconnect_integration(
    agent_id: str,
    body: DisconnectRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    """Disconnect a named integration for an agent.

    Accepted ``integration`` values:
    ``google_calendar`` / ``calendar``, ``sendgrid`` / ``email``,
    ``twilio`` / ``sms``, ``vapi`` / ``voice``.

    Returns 404 if the agent does not exist or belongs to another user.
    Returns 400 if ``integration`` is not a recognised name.
    """
    registry = _get_agent_registry(request)
    await _verify_agent_ownership(agent_id, current_user, registry)

    canonical = _DISCONNECT_MAP.get(body.integration.lower())
    if canonical is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unknown integration {body.integration!r}. "
                f"Valid values: {sorted(set(_DISCONNECT_MAP.keys()))}."
            ),
        )

    if canonical == "sendgrid":
        sg = _get_sendgrid(request)
        await sg.disconnect(agent_id)

    elif canonical == "twilio":
        tw = _get_twilio(request)
        await tw.disconnect(agent_id)

    elif canonical == "google_calendar":
        gcal = _get_google_calendar(request)
        await gcal.disconnect(agent_id)

    elif canonical == "vapi":
        vapi = _get_vapi(request)
        await vapi.configure_agent(agent_id, {"first_message": "", "voice_model": ""})
        # VapiConnector has no disconnect() — soft-deactivate via direct DB update.
        now = datetime.now(_tz.utc).isoformat()
        try:
            async with aiosqlite.connect(
                str(getattr(request.app.state, "settings").db_path)
            ) as db:
                await db.execute(
                    "UPDATE integration_voice SET is_active=0, updated_at=? WHERE agent_id=?",
                    (now, agent_id),
                )
                await db.commit()
        except Exception as exc:
            logger.warning("Vapi disconnect soft-delete failed for agent %s: %s", agent_id, exc)

    elif canonical == "dd_main_bridge":
        # The DD Main Bridge is a system-level connection managed by DDMainBridge.
        # Per-user disconnect is not supported — log and return success as a no-op.
        logger.info(
            "POST /integrations/%s/disconnect: dd_main_bridge no-op for user=%s",
            agent_id, current_user.user_id,
        )

    logger.info(
        "POST /integrations/%s/disconnect: integration=%s user=%s",
        agent_id, canonical, current_user.user_id,
    )
    return {"agent_id": agent_id, "integration": body.integration, "status": "disconnected"}


# ---------------------------------------------------------------------------
# Test endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/{agent_id}/test",
    status_code=status.HTTP_200_OK,
    summary="Send a test message via a configured integration",
)
async def test_integration(
    agent_id: str,
    body: TestIntegrationRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    """Send a test email or SMS to verify a configured integration.

    For ``sendgrid`` / ``email``: sends a test email to the currently
    authenticated user's email address.

    For ``twilio`` / ``sms``: returns instructions (live test SMS requires a
    verified destination number; production Twilio accounts require a registered
    recipient during the trial period).

    Returns 404 if the agent does not exist or belongs to another user.
    Returns 400 if the integration is not configured or the name is invalid.
    """
    registry = _get_agent_registry(request)
    await _verify_agent_ownership(agent_id, current_user, registry)

    canonical = _TEST_MAP.get(body.integration.lower())
    if canonical is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unknown integration {body.integration!r}. "
                f"Testable integrations: {sorted(set(_TEST_MAP.keys()))}."
            ),
        )

    if canonical == "sendgrid":
        sg = _get_sendgrid(request)
        cfg = await sg.get_config(agent_id)
        if cfg is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="SendGrid is not configured for this agent. Configure it first.",
            )
        to_email = current_user.email or cfg["from_email"]
        result = await sg.send_email(
            agent_id=agent_id,
            to_email=to_email,
            subject="DingDawg Agent — SendGrid test",
            body="Your SendGrid integration is working correctly.",
        )
        if result.get("success"):
            return {
                "agent_id": agent_id,
                "integration": "sendgrid",
                "success": True,
                "message": f"Test email sent to {to_email}.",
            }
        return {
            "agent_id": agent_id,
            "integration": "sendgrid",
            "success": False,
            "message": result.get("error", "SendGrid send failed."),
        }

    # canonical == "twilio"
    tw = _get_twilio(request)
    cfg = await tw.get_config(agent_id)
    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Twilio is not configured for this agent. Configure it first.",
        )
    logger.info(
        "POST /integrations/%s/test: twilio instructions returned user=%s",
        agent_id, current_user.user_id,
    )
    return {
        "agent_id": agent_id,
        "integration": "twilio",
        "success": True,
        "message": (
            f"Twilio is configured with from_number={cfg['from_number']!r}. "
            "To send a live test SMS, use the /api/v1/integrations/{agent_id}/sms/send "
            "endpoint with a verified destination number."
        ),
    }


# ---------------------------------------------------------------------------
# Frontend-compatible alias routes
# ---------------------------------------------------------------------------


@router.post(
    "/{agent_id}/sendgrid/configure",
    status_code=status.HTTP_201_CREATED,
    summary="Configure SendGrid (alias for /email)",
    include_in_schema=False,
)
async def configure_sendgrid_alias(
    agent_id: str,
    body: EmailConfigRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    return await configure_email(agent_id, body, request, current_user)


@router.post(
    "/{agent_id}/twilio/configure",
    status_code=status.HTTP_201_CREATED,
    summary="Configure Twilio (alias for /sms)",
    include_in_schema=False,
)
async def configure_twilio_alias(
    agent_id: str,
    body: SmsConfigRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    return await configure_sms(agent_id, body, request, current_user)


@router.post(
    "/{agent_id}/google-calendar/connect",
    status_code=status.HTTP_200_OK,
    summary="Initiate Google Calendar OAuth (alias for /google-calendar/auth-url)",
    include_in_schema=False,
)
async def google_calendar_connect_alias(
    agent_id: str,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    result = await google_calendar_auth_url(agent_id, request, current_user)
    return {"oauth_url": result.get("auth_url"), "message": "Redirect to OAuth URL to connect."}


@router.post(
    "/{agent_id}/google-calendar/callback",
    status_code=status.HTTP_200_OK,
    summary="Legacy Google Calendar OAuth callback (use /google-calendar/callback instead)",
    include_in_schema=False,
    deprecated=True,
)
async def google_calendar_callback_legacy(
    agent_id: str,
    body: GoogleCalendarCallbackRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    """Legacy callback that forwards to the fixed-path handler.

    The ``state`` field is required in the request body.  If the caller
    does not provide it, the request will fail with a 422 validation
    error, signalling that they need to update to the new endpoint.
    """
    return await google_calendar_callback(body, request, current_user)
