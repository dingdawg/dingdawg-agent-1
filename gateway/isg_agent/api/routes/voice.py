"""Voice agent API routes.

Endpoints for configuring voice agents, managing phone numbers,
viewing call logs, and handling Vapi webhooks.

Routes
------
POST  /api/v1/voice/configure/{agent_id}  -- configure voice for an agent
GET   /api/v1/voice/config/{agent_id}     -- get voice configuration
POST  /api/v1/voice/phone/{agent_id}      -- assign a phone number
POST  /api/v1/voice/call/{agent_id}       -- initiate an outbound call
GET   /api/v1/voice/calls/{agent_id}      -- get call history
POST  /api/v1/voice/webhook/vapi          -- Vapi webhook (public)
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from isg_agent.api.deps import CurrentUser, require_auth
from isg_agent.integrations.voice_vapi import VapiConnector

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/voice",
    tags=["voice"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# Skill dispatch mapping: Vapi function name -> (skill_name, action)
_SKILL_MAP: dict[str, tuple[str, str]] = {
    "schedule_appointment": ("appointments", "schedule"),
    "check_availability": ("appointments", "list"),
    "save_contact": ("contacts", "add"),
    "lookup_information": ("data-store", "search"),
    "send_followup": ("notifications", "send"),
}


# ---------------------------------------------------------------------------
# Authenticated endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/configure/{agent_id}",
    status_code=status.HTTP_200_OK,
    summary="Configure voice capabilities for an agent",
)
async def configure_voice(
    agent_id: str,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    """Configure voice capabilities for an agent.

    Body: ``{first_message?, voice_model?, voice_id?, system_prompt?, server_url?}``

    If a Vapi API key is configured on the server, creates a Vapi assistant
    automatically.  Otherwise stores the configuration locally for later
    activation.
    """
    vapi = _get_vapi(request)
    body = await request.json()

    result = await vapi.configure_agent(agent_id, body)
    logger.info(
        "POST /voice/configure/%s: status=%s user=%s",
        agent_id, result.get("status"), current_user.user_id,
    )
    return result


@router.get(
    "/config/{agent_id}",
    status_code=status.HTTP_200_OK,
    summary="Get voice configuration for an agent",
)
async def get_voice_config(
    agent_id: str,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    """Get voice configuration for an agent.

    Returns 404 if voice is not configured.
    """
    vapi = _get_vapi(request)
    config = await vapi.get_voice_config(agent_id)

    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Voice not configured for agent {agent_id!r}.",
        )
    return config


@router.post(
    "/phone/{agent_id}",
    status_code=status.HTTP_200_OK,
    summary="Assign a phone number to an agent",
)
async def assign_phone(
    agent_id: str,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    """Assign a phone number to an agent via Vapi.

    Body: ``{area_code?: str}``

    Requires Vapi API key and a configured voice assistant.
    """
    vapi = _get_vapi(request)
    body = await request.json()
    area_code = body.get("area_code", "")

    result = await vapi.assign_phone_number(agent_id, area_code=area_code)

    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"],
        )

    logger.info(
        "POST /voice/phone/%s: number=%s user=%s",
        agent_id, result.get("phone_number"), current_user.user_id,
    )
    return result


@router.post(
    "/call/{agent_id}",
    status_code=status.HTTP_200_OK,
    summary="Initiate an outbound call",
)
async def make_call(
    agent_id: str,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    """Initiate an outbound call from the agent.

    Body: ``{to_number: str, context?: str}``
    """
    vapi = _get_vapi(request)
    body = await request.json()

    to_number = body.get("to_number", "")
    if not to_number:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="to_number is required.",
        )

    context = body.get("context", "")
    result = await vapi.make_outbound_call(agent_id, to_number, context=context)

    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"],
        )

    logger.info(
        "POST /voice/call/%s: call_id=%s user=%s",
        agent_id, result.get("call_id"), current_user.user_id,
    )
    return result


@router.get(
    "/calls/{agent_id}",
    status_code=status.HTTP_200_OK,
    summary="Get call history for an agent",
)
async def get_call_logs(
    agent_id: str,
    request: Request,
    limit: int = 50,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    """Get call history for an agent.

    Returns a list of call log entries, newest first.
    """
    vapi = _get_vapi(request)
    logs = await vapi.get_call_logs(agent_id, limit=limit)
    return {"agent_id": agent_id, "calls": logs, "count": len(logs)}


# ---------------------------------------------------------------------------
# Public webhook (no auth — Vapi calls this)
# ---------------------------------------------------------------------------


@router.post(
    "/webhook/vapi",
    status_code=status.HTTP_200_OK,
    summary="Handle Vapi webhook callbacks",
)
async def vapi_webhook(request: Request) -> dict:
    """Handle Vapi webhook callbacks.

    PUBLIC endpoint -- Vapi calls this when the voice agent needs to
    execute a function during a call, or to report call completion.

    Function-call flow:
    1. Vapi sends ``{message: {type: "function-call", functionCall: {...}}}``
    2. We map the function name to a DingDawg skill
    3. Execute the skill via our executor
    4. Return the result so Vapi speaks it to the caller

    End-of-call-report flow:
    1. Vapi sends ``{message: {type: "end-of-call-report"}, ...}``
    2. We log the call details (duration, transcript, cost)
    """
    body = await request.json()
    message = body.get("message", {})
    msg_type = message.get("type")

    if msg_type == "function-call":
        func_call = message.get("functionCall", {})
        func_name = func_call.get("name", "")
        params = func_call.get("parameters", {})

        if func_name in _SKILL_MAP:
            skill_name, action = _SKILL_MAP[func_name]

            # Build skill parameters
            skill_params = {"action": action, **params}

            # Execute via skill executor if available
            executor = getattr(request.app.state, "skill_executor", None)
            if executor is not None:
                try:
                    result = await executor.execute(skill_name, skill_params)
                    output = result.output if result.success else f"Sorry, I couldn't do that: {result.error}"
                    return {"result": output}
                except Exception:
                    logger.exception("Skill execution failed for voice function %s", func_name)
                    return {"result": "Sorry, something went wrong. Let me try a different approach."}

            return {"result": f"I received your request for {func_name}. Let me look into that."}

        return {"result": "I'm not sure how to help with that. Let me transfer you to someone who can."}

    if msg_type == "end-of-call-report":
        vapi = getattr(request.app.state, "vapi", None)
        if vapi is not None:
            try:
                await vapi.log_completed_call(body)
            except Exception:
                logger.exception("Failed to log completed call from Vapi webhook")
        return {"status": "ok"}

    # Other message types (status-update, transcript, etc.) — acknowledge
    return {"status": "ok"}
