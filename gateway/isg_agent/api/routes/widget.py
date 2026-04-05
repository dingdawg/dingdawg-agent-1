"""Widget API routes for embeddable chat.

Provides endpoints for the JavaScript chat widget to:
1. Load agent configuration (name, avatar, colors, greeting)
2. Create anonymous chat sessions
3. Send/receive messages
4. Serve the widget JavaScript bundle

All widget endpoints are PUBLIC -- website visitors are anonymous and have
no authentication token.  Session isolation is enforced by unique session IDs
and visitor IDs rather than JWTs.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

from isg_agent.middleware.rate_limiter_middleware import limiter

__all__ = ["router"]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Widget-specific rate-limit key: extract session_id from cached body,
# fall back to client IP so anonymous visitors still get per-IP limiting.
# ---------------------------------------------------------------------------

async def _widget_session_key(request: Request) -> str:
    """Rate-limit key for widget message endpoint: per session_id."""
    try:
        body = await request.json()
        session_id = body.get("session_id")
        if session_id:
            return f"widget_msg:{session_id}"
    except Exception:
        pass
    # Fallback to client IP
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return f"widget_msg:{forwarded.split(',')[0].strip()}"
    if request.client:
        return f"widget_msg:{request.client.host}"
    return "widget_msg:unknown"

router = APIRouter(prefix="/api/v1/widget", tags=["widget"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_branding(agent_record: Any) -> dict[str, Any]:
    """Parse the branding_json field from an AgentRecord into a dict."""
    raw = getattr(agent_record, "branding_json", "{}")
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _parse_config(agent_record: Any) -> dict[str, Any]:
    """Parse the config_json field from an AgentRecord into a dict."""
    raw = getattr(agent_record, "config_json", "{}")
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        return {}


# ---------------------------------------------------------------------------
# Widget embed endpoint (serves widget.js)
# ---------------------------------------------------------------------------


@router.get("/embed.js")
async def widget_embed_js(request: Request) -> Response:
    """Serve the embeddable widget JavaScript.

    Returns the widget.js file as ``application/javascript`` with a
    one-hour public cache header.  The file is read from the ``static/``
    directory relative to the ``isg_agent`` package root.
    """
    static_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "static",
    )
    widget_path = os.path.join(static_dir, "widget.js")

    try:
        with open(widget_path, "r", encoding="utf-8") as f:
            js_content = f.read()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Widget script not found")

    return Response(
        content=js_content,
        media_type="application/javascript",
        headers={
            "Cache-Control": "public, max-age=3600",
            "Access-Control-Allow-Origin": "*",
        },
    )


# ---------------------------------------------------------------------------
# Widget configuration
# ---------------------------------------------------------------------------


@router.get("/{agent_handle}/config")
async def widget_config(request: Request, agent_handle: str) -> JSONResponse:
    """Get widget configuration for an agent.

    PUBLIC endpoint -- no auth required.

    Returns the agent's display name, avatar URL, primary colour,
    greeting message, and bubble text so the widget can render itself
    to match the business's brand.

    Parameters
    ----------
    agent_handle:
        The unique ``@handle`` of the agent (with or without the ``@`` prefix).
    """
    # Strip optional @ prefix
    handle = agent_handle.lstrip("@")

    agent_registry = request.app.state.agent_registry
    agent = await agent_registry.get_agent_by_handle(handle)

    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    branding = _parse_branding(agent)
    config = _parse_config(agent)

    return JSONResponse(
        content={
            "agent_name": agent.name,
            "handle": agent.handle,
            "greeting": config.get("greeting", "Hello! How can I help you today?"),
            "avatar_url": branding.get("avatar_url", ""),
            "primary_color": branding.get("primary_color", "#7C3AED"),
            "bubble_text": config.get("bubble_text", "Chat with us"),
            "agent_type": agent.agent_type.value,
            "industry_type": agent.industry_type or "",
        },
        headers={"Access-Control-Allow-Origin": "*"},
    )


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------


@router.post("/{agent_handle}/session")
async def widget_create_session(
    request: Request,
    agent_handle: str,
) -> JSONResponse:
    """Create an anonymous chat session for a website visitor.

    PUBLIC endpoint -- no auth required (widget visitors are anonymous).

    The session is tied to the agent's ID and a generated visitor ID.
    The visitor can resume the session later by providing the same
    ``session_id`` (persisted in localStorage by the widget).

    Body (optional)
    ----
    ``{visitor_id?: str}``

    Returns
    -------
    ``{session_id: str, greeting_message: str}``
    """
    handle = agent_handle.lstrip("@")

    agent_registry = request.app.state.agent_registry
    agent = await agent_registry.get_agent_by_handle(handle)

    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Parse optional body — reject malformed JSON with 422
    raw_body = await request.body()
    if raw_body and raw_body.strip():
        try:
            body = json.loads(raw_body)
        except (json.JSONDecodeError, ValueError):
            raise HTTPException(
                status_code=422,
                detail="Malformed JSON in request body",
            )
        if not isinstance(body, dict):
            raise HTTPException(
                status_code=422,
                detail="Request body must be a JSON object",
            )
    else:
        body = {}

    visitor_id = body.get("visitor_id") or f"visitor-{uuid.uuid4().hex[:8]}"

    # Create a lightweight session using SessionManager
    session_manager = request.app.state.session_manager
    session = await session_manager.create_session(
        user_id=f"widget:{visitor_id}",
        agent_id=agent.id,
    )

    # Build greeting from agent config
    config = _parse_config(agent)
    greeting = config.get("greeting", "Hello! How can I help you today?")

    return JSONResponse(
        content={
            "session_id": session.session_id,
            "visitor_id": visitor_id,
            "greeting_message": greeting,
        },
        headers={"Access-Control-Allow-Origin": "*"},
    )


# ---------------------------------------------------------------------------
# Message processing
# ---------------------------------------------------------------------------


@router.post("/{agent_handle}/message")
@limiter.limit("10/minute", key_func=_widget_session_key)
async def widget_send_message(
    request: Request,
    agent_handle: str,
) -> JSONResponse:
    """Send a message from the widget and get an agent response.

    PUBLIC endpoint.

    Body
    ----
    ``{session_id: str, message: str, visitor_id?: str}``

    Returns
    -------
    ``{response: str, session_id: str}``

    The message is processed through the full governed AgentRuntime
    pipeline (governance gate, LLM, audit trail, memory persistence).
    """
    handle = agent_handle.lstrip("@")

    # Validate agent exists
    agent_registry = request.app.state.agent_registry
    agent = await agent_registry.get_agent_by_handle(handle)

    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Parse body
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    session_id = body.get("session_id")
    message = (body.get("message") or "").strip()
    visitor_id = body.get("visitor_id", f"visitor-{uuid.uuid4().hex[:8]}")

    if not session_id or not message:
        raise HTTPException(
            status_code=400,
            detail="session_id and message are required",
        )

    # Process through the governed AgentRuntime pipeline
    runtime = request.app.state.runtime

    try:
        from isg_agent.brain.session import SessionNotFoundError

        result = await runtime.process_message(
            session_id=session_id,
            user_message=message,
            user_id=f"widget:{visitor_id}",
        )
    except SessionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Session not found or expired",
        )
    except Exception:
        logger.exception(
            "Widget message processing failed for session %s", session_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to process message",
        )

    # Guard against empty responses reaching the widget
    response_text = result.content
    if not response_text or not response_text.strip():
        logger.warning(
            "Empty agent response for widget session %s", session_id,
        )
        response_text = "I'm working on that — could you try again in a moment?"

    return JSONResponse(
        content={
            "response": response_text,
            "session_id": result.session_id,
            "halted": result.halted,
        },
        headers={"Access-Control-Allow-Origin": "*"},
    )
