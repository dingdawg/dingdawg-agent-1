"""Agent control endpoints: sessions, message processing, and agent triggers.

Provides the HTTP API for creating sessions, listing sessions,
sending messages, deleting sessions, and triggering agents from external
sources (email, SMS, calendar, cron, API).

Most endpoints require authentication via JWT Bearer token.
The trigger endpoint is PUBLIC — it is called by the inbound webhook
routes and may also be called by external systems.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from isg_agent.api.deps import CurrentUser, require_auth
from isg_agent.brain.agent import AgentResponse, AgentRuntime
from isg_agent.brain.session import SessionNotFoundError
from isg_agent.schemas.messages import ActionCard, MessageRequest, MessageResponse
from isg_agent.schemas.sessions import SessionCreate, SessionList, SessionResponse

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["agent"])


# ---------------------------------------------------------------------------
# Schemas for the trigger endpoint
# ---------------------------------------------------------------------------


class TriggerRequest(BaseModel):
    """Request body for POST /api/v1/agents/{agent_id}/trigger.

    Attributes
    ----------
    source:
        The originating channel — one of ``email``, ``sms``, ``calendar``,
        ``api``, or ``cron``.
    message:
        The message content to process.  Required; 1–10 000 characters.
    sender:
        The originating email address or phone number.  Defaults to ``""``.
    respond_to:
        Where to send the agent's reply — ``"email"``, ``"sms"``, or
        ``"none"`` (default).  When set to ``"email"`` or ``"sms"`` an
        outbound notification is queued via the skill_notifications table.
    """

    source: str = Field(..., pattern=r"^(email|sms|calendar|api|cron)$")
    message: str = Field(..., min_length=1, max_length=10000)
    sender: str = Field(default="", max_length=500)
    respond_to: str = Field(default="none", pattern=r"^(email|sms|none)$")


# ---------------------------------------------------------------------------
# Helper: get the AgentRuntime from app state
# ---------------------------------------------------------------------------


def _get_runtime(request: Request) -> AgentRuntime:
    """Extract the AgentRuntime from FastAPI app state.

    Raises 503 Service Unavailable if the runtime is not yet initialised.
    """
    runtime: Optional[AgentRuntime] = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent runtime not initialised. Server is starting up.",
        )
    return runtime


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new agent session",
)
async def create_session(
    body: SessionCreate,
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> SessionResponse:
    """Create a new conversation session for the authenticated user."""
    runtime = _get_runtime(request)
    session_mgr = runtime._sessions  # noqa: SLF001

    session = await session_mgr.create_session(user_id=user.user_id, agent_id=body.agent_id)
    logger.info("Session created: %s for user %s", session.session_id, user.user_id)

    return SessionResponse(
        session_id=session.session_id,
        user_id=session.user_id,
        created_at=session.created_at.isoformat(),
        updated_at=session.updated_at.isoformat(),
        message_count=session.message_count,
        total_tokens=session.total_tokens,
        status=session.status,
    )


@router.get(
    "/sessions",
    response_model=SessionList,
    summary="List sessions for the authenticated user",
)
async def list_sessions(
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> SessionList:
    """Return all sessions belonging to the authenticated user."""
    runtime = _get_runtime(request)
    session_mgr = runtime._sessions  # noqa: SLF001

    sessions = await session_mgr.list_sessions(user_id=user.user_id)

    items = [
        SessionResponse(
            session_id=s.session_id,
            user_id=s.user_id,
            created_at=s.created_at.isoformat(),
            updated_at=s.updated_at.isoformat(),
            message_count=s.message_count,
            total_tokens=s.total_tokens,
            status=s.status,
        )
        for s in sessions
    ]

    return SessionList(sessions=items, count=len(items))


@router.post(
    "/sessions/{session_id}/message",
    response_model=MessageResponse,
    summary="Send a message to an agent session",
)
async def send_message(
    session_id: str,
    body: MessageRequest,
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> MessageResponse:
    """Send a user message and receive the governed agent response.

    The message is processed through the full governance pipeline:
    governance gate -> LLM call -> audit record -> memory save.

    Returns 404 if the session does not exist.
    """
    runtime = _get_runtime(request)

    try:
        agent_response: AgentResponse = await runtime.process_message(
            session_id=session_id,
            user_message=body.content,
            user_id=user.user_id,
        )
    except SessionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )

    return MessageResponse(
        content=agent_response.content,
        session_id=agent_response.session_id,
        model_used=agent_response.model_used,
        input_tokens=agent_response.input_tokens,
        output_tokens=agent_response.output_tokens,
        governance_decision=agent_response.governance_decision,
        convergence_status=agent_response.convergence_status,
        halted=agent_response.halted,
        actions=[
            ActionCard(**a) for a in agent_response.extra.get("actions", [])
        ],
    )


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete an agent session",
)
async def delete_session(
    session_id: str,
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> Response:
    """Delete a session and its message history.

    Returns 404 if the session does not exist.
    """
    runtime = _get_runtime(request)
    session_mgr = runtime._sessions  # noqa: SLF001
    memory = runtime._memory  # noqa: SLF001

    # Verify session exists before deleting
    session = await session_mgr.get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )

    # Verify ownership
    if session.user_id != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )

    # Delete message history first, then session
    await memory.clear_session(session_id)
    await session_mgr.delete_session(session_id)
    logger.info("Session deleted: %s by user %s", session_id, user.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Public trigger endpoint (no JWT — called by inbound webhooks + external)
# ---------------------------------------------------------------------------


@router.post(
    "/agents/{agent_id}/trigger",
    status_code=status.HTTP_200_OK,
    summary="Trigger an agent from an external source",
)
async def trigger_agent(
    agent_id: str,
    body: TriggerRequest,
    request: Request,
) -> dict:
    """Trigger an agent to process a message from an external source.

    PUBLIC endpoint — no JWT required.  Called by the inbound webhook routes
    (SendGrid, Twilio, Google Calendar) and may also be invoked directly by
    external systems.

    Processing flow:
    1. Look up the agent by ``agent_id`` in the agent registry.
    2. Return 404 if the agent does not exist.
    3. Create a new session via the session manager.
    4. Process the message through the AgentRuntime.
    5. If ``respond_to`` is ``"email"`` or ``"sms"``, insert an outbound
       notification row into ``skill_notifications``.
    6. Return ``{"status": "processed", "session_id": ..., "response": ...,
       "response_queued": ...}``.

    Parameters
    ----------
    agent_id:
        The UUID of the target agent.
    body:
        The trigger request payload.
    request:
        The FastAPI request object (used to access app.state).

    Returns
    -------
    dict
        Processing result with status, session_id, response, and
        response_queued fields.

    Raises
    ------
    HTTPException 404
        If the agent_id is not found in the registry.
    HTTPException 503
        If the AgentRuntime is not yet initialised.
    """
    # -- Step 1: Validate agent exists --------------------------------------
    registry = getattr(request.app.state, "agent_registry", None)
    if registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent registry not initialised. Server is starting up.",
        )

    agent = await registry.get_agent(agent_id)
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent not found: {agent_id}",
        )

    # -- Step 2: Get runtime ------------------------------------------------
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent runtime not initialised. Server is starting up.",
        )

    # -- Step 3: Create session --------------------------------------------
    session_mgr = runtime._sessions  # noqa: SLF001
    synthetic_user_id = f"trigger:{body.source}:{body.sender or 'unknown'}"
    session = await session_mgr.create_session(
        user_id=synthetic_user_id,
        agent_id=agent_id,
    )

    # -- Step 4: Process message -------------------------------------------
    try:
        agent_response: AgentResponse = await runtime.process_message(
            session_id=session.session_id,
            user_message=body.message,
            user_id=synthetic_user_id,
        )
        response_content = agent_response.content
    except SessionNotFoundError:
        # Shouldn't happen right after creation — defensive fallback
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Session was not found immediately after creation.",
        )
    except Exception:
        logger.exception(
            "AgentRuntime failed to process trigger for agent_id=%s", agent_id
        )
        response_content = "Agent processed your request."

    # -- Step 5: Queue outbound notification if requested ------------------
    response_queued = False
    if body.respond_to in {"email", "sms"} and body.sender:
        try:
            import aiosqlite

            from isg_agent.config import get_settings

            settings = get_settings()
            db_path = settings.db_path

            async with aiosqlite.connect(db_path) as db:
                # Ensure skill_notifications table exists (idempotent DDL)
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS skill_notifications (
                        id          TEXT PRIMARY KEY,
                        agent_id    TEXT NOT NULL,
                        channel     TEXT NOT NULL,
                        recipient   TEXT NOT NULL,
                        body        TEXT NOT NULL,
                        status      TEXT NOT NULL DEFAULT 'pending',
                        created_at  TEXT NOT NULL
                    )
                """)
                import uuid
                from datetime import datetime, timezone

                await db.execute(
                    "INSERT INTO skill_notifications "
                    "(id, agent_id, channel, recipient, body, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?, 'pending', ?)",
                    (
                        str(uuid.uuid4()),
                        agent_id,
                        body.respond_to,
                        body.sender,
                        response_content,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                await db.commit()
            response_queued = True
        except Exception:
            logger.exception(
                "Failed to queue outbound notification for agent_id=%s", agent_id
            )
            response_queued = False

    logger.info(
        "Trigger processed: agent_id=%s source=%s respond_to=%s queued=%s",
        agent_id,
        body.source,
        body.respond_to,
        response_queued,
    )

    return {
        "status": "processed",
        "session_id": session.session_id,
        "response": response_content,
        "response_queued": response_queued,
    }
