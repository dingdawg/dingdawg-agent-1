"""Combined integration status endpoint.

Routes
------
GET /api/v1/integrations/{agent_id}/status — all integration statuses
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, status

from isg_agent.api.deps import CurrentUser, require_auth

from ._deps import _get_agent_registry, _verify_agent_ownership

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/{agent_id}/status",
    status_code=status.HTTP_200_OK,
    summary="Get all integration statuses for an agent",
)
async def get_integration_status(
    agent_id: str,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    """Return a combined view of all integration statuses for an agent.

    Currently reports: email (SendGrid), sms (Twilio), calendar (Google),
    and voice (Vapi).  No credentials or secret values are exposed.

    Returns 404 if the agent does not exist or belongs to another user.
    """
    registry = _get_agent_registry(request)
    await _verify_agent_ownership(agent_id, current_user, registry)

    # Email status
    email_status: dict = {"connected": False, "from_email": None}
    sg = getattr(request.app.state, "sendgrid", None)
    if sg is not None:
        cfg = await sg.get_config(agent_id)
        if cfg is not None:
            email_status = {"connected": True, "from_email": cfg["from_email"]}

    # SMS status
    sms_status: dict = {"connected": False, "from_number": None}
    tw = getattr(request.app.state, "twilio", None)
    if tw is not None:
        cfg = await tw.get_config(agent_id)
        if cfg is not None:
            sms_status = {"connected": True, "from_number": cfg["from_number"]}

    # Google Calendar status
    calendar_status: dict = {"connected": False, "google_email": None}
    gcal = getattr(request.app.state, "google_calendar", None)
    if gcal is not None:
        creds = await gcal.get_credentials(agent_id)
        if creds is not None:
            calendar_status = {
                "connected": True,
                "google_email": creds.get("google_email"),
            }

    # Voice (Vapi) status
    voice_status: dict = {"connected": False, "vapi_assistant_id": None}
    vapi = getattr(request.app.state, "vapi", None)
    if vapi is not None:
        voice_cfg = await vapi.get_voice_config(agent_id)
        if voice_cfg is not None:
            voice_status = {
                "connected": True,
                "vapi_assistant_id": voice_cfg.get("vapi_assistant_id"),
            }

    # Webhooks: count active subscriptions from DB
    webhooks_list: list = []
    webhooks_count = 0
    try:
        import aiosqlite as _aiosqlite
        _db_path = str(getattr(request.app.state, "settings").db_path)
        async with _aiosqlite.connect(_db_path, timeout=5.0) as _db:
            _db.row_factory = _aiosqlite.Row
            _cur = await _db.execute(
                "SELECT id, url, events, auth_type, active, created_at "
                "FROM agent_webhooks WHERE agent_id = ? AND active = 1 ORDER BY created_at ASC",
                (agent_id,),
            )
            _rows = await _cur.fetchall()
            import json as _json
            for _row in _rows:
                try:
                    _events = _json.loads(_row["events"])
                except (ValueError, TypeError):
                    _events = []
                webhooks_list.append({
                    "id": _row["id"],
                    "url": _row["url"],
                    "events": _events,
                    "auth_type": _row["auth_type"],
                    "active": bool(_row["active"]),
                    "created_at": _row["created_at"],
                })
            webhooks_count = len(webhooks_list)
    except Exception as _wh_exc:
        # agent_webhooks table may not yet exist on older deployments — fail-open
        logger.debug("agent_webhooks query failed (non-fatal): %s", _wh_exc)

    # DD Main Bridge: check if any business is registered for this agent
    dd_main_connected = False
    try:
        _bridge = getattr(request.app.state, "ddmain_bridge", None)
        if _bridge is not None:
            _mapping = await _bridge.get_agent_for_business(agent_id)
            dd_main_connected = _mapping is not None
    except Exception as _ddm_exc:
        logger.debug("dd_main_bridge status check failed (non-fatal): %s", _ddm_exc)

    return {
        "agent_id": agent_id,
        # Backend-canonical keys
        "email": email_status,
        "sms": sms_status,
        "calendar": calendar_status,
        "voice": voice_status,
        # Frontend-expected keys (aliases)
        "sendgrid": {"connected": email_status.get("connected", False), "from_email": email_status.get("from_email")},
        "twilio": {"connected": sms_status.get("connected", False), "from_number": sms_status.get("from_number")},
        "google_calendar": {"connected": calendar_status.get("connected", False)},
        "vapi": {"connected": voice_status.get("connected", False)},
        "webhooks": {"active_count": webhooks_count, "webhooks": webhooks_list},
        "dd_main_bridge": {"connected": dd_main_connected},
        # Nango-managed providers (defaults until Nango env vars configured)
        "cronofy": {"connected": False},
        "zapier": {"connected": False},
        "stripe_connect": {"connected": False},
    }
