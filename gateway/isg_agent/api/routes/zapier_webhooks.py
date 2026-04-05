"""Zapier webhook-based triggers and actions for DingDawg Agent 1.

Provides REST endpoints for Zapier's REST Hook subscription model and
action endpoints that Zapier calls to perform operations.

Webhook Triggers (subscribe/unsubscribe):
    POST   /api/v1/zapier/hooks                         — Subscribe to events
    DELETE /api/v1/zapier/hooks/{hook_id}               — Unsubscribe
    GET    /api/v1/zapier/hooks/sample/{event_type}     — Sample data for field mapping

Actions:
    POST /api/v1/zapier/actions/create-task     — Create a task for the agent
    POST /api/v1/zapier/actions/send-message    — Send a message through the agent
    POST /api/v1/zapier/actions/create-booking  — Create a booking

Supported event types:
    new_booking      — Fires when agent books an appointment
    new_task         — Fires when a new task is created
    new_message      — Fires when a customer sends a message
    task_completed   — Fires when agent completes a task

All endpoints authenticate via X-API-Key header (same as existing Zapier
integration). Zapier sends this header after the user configures their
API key in the Zapier app.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiosqlite
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/zapier", tags=["zapier-webhooks"])

# ---------------------------------------------------------------------------
# Supported event types and their sample payloads
# ---------------------------------------------------------------------------

SUPPORTED_EVENTS = {"new_booking", "new_task", "new_message", "task_completed"}

_SAMPLE_PAYLOADS: Dict[str, Dict[str, Any]] = {
    "new_booking": {
        "id": "booking_sample_001",
        "agent_id": "agent_abc123",
        "contact_name": "Jane Doe",
        "contact_email": "jane@example.com",
        "contact_phone": "+15551234567",
        "title": "Consultation Call",
        "start_time": "2026-03-25T10:00:00Z",
        "end_time": "2026-03-25T11:00:00Z",
        "description": "Initial consultation for new project",
        "location": "Zoom",
        "status": "confirmed",
        "created_at": "2026-03-24T08:00:00Z",
    },
    "new_task": {
        "id": "task_sample_001",
        "agent_id": "agent_abc123",
        "title": "Follow up with client",
        "description": "Send proposal document to Jane Doe",
        "priority": "high",
        "status": "pending",
        "due_date": "2026-03-26T17:00:00Z",
        "assigned_to": "agent",
        "tags": ["follow-up", "proposal"],
        "created_at": "2026-03-24T08:00:00Z",
    },
    "new_message": {
        "id": "msg_sample_001",
        "agent_id": "agent_abc123",
        "sender_name": "Jane Doe",
        "sender_email": "jane@example.com",
        "channel": "web_chat",
        "body": "Hi, I'd like to schedule a meeting for next week.",
        "metadata": {"source": "widget", "page_url": "https://example.com/contact"},
        "created_at": "2026-03-24T08:00:00Z",
    },
    "task_completed": {
        "id": "task_sample_002",
        "agent_id": "agent_abc123",
        "title": "Send invoice to client",
        "description": "Invoice #1042 for March services",
        "priority": "normal",
        "status": "completed",
        "completed_at": "2026-03-24T14:30:00Z",
        "result": "Invoice sent successfully via email",
        "created_at": "2026-03-23T09:00:00Z",
    },
}


# ---------------------------------------------------------------------------
# Auth dependency (reuse from existing zapier.py)
# ---------------------------------------------------------------------------


async def _require_zapier_key(
    request: Request,
    x_api_key: Optional[str] = Header(None),
) -> dict:
    """Validate the Zapier API key. Returns key info or raises 401."""
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-Key header required",
        )

    try:
        from isg_agent.mcp.auth import validate_api_key

        settings = getattr(request.app.state, "settings", None)
        db_path = settings.db_path if settings else "isg_agent.db"
        key_info = await validate_api_key(x_api_key, db_path=db_path)
    except Exception as exc:
        logger.error("API key validation error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    if not key_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API key",
        )

    return key_info


# ---------------------------------------------------------------------------
# DB helpers — zapier_webhook_subscriptions table
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS zapier_webhook_subscriptions (
    id          TEXT    PRIMARY KEY,
    user_id     TEXT    NOT NULL,
    agent_id    TEXT,
    event_type  TEXT    NOT NULL,
    target_url  TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_zapier_webhook_subs_event
    ON zapier_webhook_subscriptions(event_type);
"""


async def _ensure_table(db_path: str) -> None:
    """Ensure the webhook subscriptions table exists (idempotent)."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute(_CREATE_TABLE_SQL)
        await db.execute(_CREATE_INDEX_SQL)
        await db.commit()


async def _get_db_path(request: Request) -> str:
    """Extract db_path from app settings."""
    settings = getattr(request.app.state, "settings", None)
    return settings.db_path if settings else "isg_agent.db"


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class WebhookSubscribeRequest(BaseModel):
    """Zapier sends this when a user enables a Zap trigger."""

    hookUrl: str = Field(..., description="Zapier's webhook callback URL")
    event_type: str = Field(..., description="Event to subscribe to")
    agent_id: Optional[str] = Field(None, description="Agent ID to filter events")


class WebhookSubscribeResponse(BaseModel):
    """Returned to Zapier after successful subscription."""

    id: str = Field(..., description="Subscription ID (used for unsubscribe)")
    event_type: str
    target_url: str
    created_at: str


class CreateTaskRequest(BaseModel):
    """Request to create a task via Zapier action."""

    agent_id: str = Field(..., description="Agent ID")
    title: str = Field(..., description="Task title")
    description: Optional[str] = Field(None, description="Task description")
    priority: str = Field("normal", description="Priority: low, normal, high, urgent")
    due_date: Optional[str] = Field(None, description="Due date (ISO 8601)")
    tags: List[str] = Field(default_factory=list, description="Tags for the task")


class SendMessageRequest(BaseModel):
    """Request to send a message via Zapier action."""

    agent_id: str = Field(..., description="Agent ID")
    channel: str = Field("web_chat", description="Channel: web_chat, email, sms")
    recipient: str = Field(..., description="Recipient (email, phone, or session ID)")
    subject: Optional[str] = Field(None, description="Message subject (for email)")
    body: str = Field(..., description="Message body")


class CreateBookingRequest(BaseModel):
    """Request to create a booking via Zapier action."""

    agent_id: str = Field(..., description="Agent ID")
    contact_name: str = Field(..., description="Customer name")
    contact_email: Optional[str] = Field(None, description="Customer email")
    contact_phone: Optional[str] = Field(None, description="Customer phone")
    title: str = Field(..., description="Booking title")
    start_time: str = Field(..., description="Start time (ISO 8601)")
    end_time: Optional[str] = Field(None, description="End time (ISO 8601)")
    description: Optional[str] = Field(None, description="Booking description")
    location: Optional[str] = Field(None, description="Location or meeting link")


class ActionResponse(BaseModel):
    """Standard response for Zapier actions."""

    id: str
    success: bool
    data: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Webhook subscription endpoints (Triggers)
# ---------------------------------------------------------------------------


@router.post(
    "/hooks",
    response_model=WebhookSubscribeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Subscribe to webhook events (Zapier trigger setup)",
)
async def subscribe_webhook(
    body: WebhookSubscribeRequest,
    request: Request,
    key_info: dict = Depends(_require_zapier_key),
) -> WebhookSubscribeResponse:
    """Zapier calls this when a user turns on a Zap with a DingDawg trigger.

    Stores the webhook URL so we can POST events to it when they occur.
    """
    if body.event_type not in SUPPORTED_EVENTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported event_type '{body.event_type}'. "
                f"Supported: {sorted(SUPPORTED_EVENTS)}"
            ),
        )

    db_path = await _get_db_path(request)
    await _ensure_table(db_path)

    hook_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    user_id = key_info.get("user_id", "unknown")

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO zapier_webhook_subscriptions
                (id, user_id, agent_id, event_type, target_url, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (hook_id, user_id, body.agent_id, body.event_type, body.hookUrl, now),
        )
        await db.commit()

    logger.info(
        "Zapier webhook subscribed: id=%s event=%s user=%s",
        hook_id,
        body.event_type,
        user_id,
    )

    return WebhookSubscribeResponse(
        id=hook_id,
        event_type=body.event_type,
        target_url=body.hookUrl,
        created_at=now,
    )


@router.delete(
    "/hooks/{hook_id}",
    status_code=status.HTTP_200_OK,
    summary="Unsubscribe from webhook events (Zapier trigger teardown)",
)
async def unsubscribe_webhook(
    hook_id: str,
    request: Request,
    key_info: dict = Depends(_require_zapier_key),
) -> Dict[str, Any]:
    """Zapier calls this when a user turns off a Zap or deletes a trigger.

    Removes the stored webhook URL so events are no longer delivered.
    """
    db_path = await _get_db_path(request)
    await _ensure_table(db_path)

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "DELETE FROM zapier_webhook_subscriptions WHERE id = ?",
            (hook_id,),
        )
        await db.commit()
        deleted = cursor.rowcount

    if deleted == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Webhook subscription '{hook_id}' not found",
        )

    logger.info("Zapier webhook unsubscribed: id=%s", hook_id)
    return {"id": hook_id, "deleted": True}


@router.get(
    "/hooks/sample/{event_type}",
    summary="Sample data for Zapier field mapping",
)
async def sample_webhook_data(
    event_type: str,
    _key_info: dict = Depends(_require_zapier_key),
) -> List[Dict[str, Any]]:
    """Return sample payload for a given event type.

    Zapier calls this during trigger setup to discover available fields
    and show them in the Zap editor for mapping. Returns an array with
    one sample object.
    """
    if event_type not in SUPPORTED_EVENTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported event_type '{event_type}'. "
                f"Supported: {sorted(SUPPORTED_EVENTS)}"
            ),
        )

    return [_SAMPLE_PAYLOADS[event_type]]


# ---------------------------------------------------------------------------
# Webhook dispatch helper (called by internal event system)
# ---------------------------------------------------------------------------


async def dispatch_webhook_event(
    db_path: str,
    event_type: str,
    payload: Dict[str, Any],
    agent_id: Optional[str] = None,
) -> int:
    """Fan-out an event to all subscribed Zapier webhooks.

    Called by the internal event system (e.g., after a booking is created).
    Returns the number of webhooks successfully notified.

    Parameters
    ----------
    db_path:
        Path to the SQLite database.
    event_type:
        One of the SUPPORTED_EVENTS.
    payload:
        JSON-serializable event data to POST to each subscriber.
    agent_id:
        Optional agent ID to filter subscriptions.
    """
    import httpx

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        if agent_id:
            cursor = await db.execute(
                """
                SELECT id, target_url FROM zapier_webhook_subscriptions
                WHERE event_type = ? AND (agent_id = ? OR agent_id IS NULL)
                """,
                (event_type, agent_id),
            )
        else:
            cursor = await db.execute(
                "SELECT id, target_url FROM zapier_webhook_subscriptions WHERE event_type = ?",
                (event_type,),
            )

        subs = await cursor.fetchall()

    if not subs:
        return 0

    delivered = 0
    async with httpx.AsyncClient(timeout=10.0) as client:
        for sub in subs:
            target_url = sub["target_url"]
            try:
                resp = await client.post(target_url, json=payload)
                if resp.status_code < 400:
                    delivered += 1
                else:
                    logger.warning(
                        "Zapier webhook delivery failed: hook=%s url=%s status=%d",
                        sub["id"],
                        target_url,
                        resp.status_code,
                    )
            except Exception as exc:
                logger.error(
                    "Zapier webhook delivery error: hook=%s url=%s error=%s",
                    sub["id"],
                    target_url,
                    exc,
                )

    logger.info(
        "Zapier webhook dispatch: event=%s delivered=%d/%d",
        event_type,
        delivered,
        len(subs),
    )
    return delivered


# ---------------------------------------------------------------------------
# Action endpoints
# ---------------------------------------------------------------------------


async def _execute_skill(
    request: Request,
    skill_name: str,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Execute a skill and return parsed output."""
    executor = getattr(request.app.state, "skill_executor", None)
    if executor is None:
        raise HTTPException(status_code=503, detail="Skill executor not initialized")

    result = await executor.execute(skill_name=skill_name, parameters=params)
    output: Dict[str, Any] = {}
    if result.output:
        try:
            output = json.loads(result.output)
        except (json.JSONDecodeError, TypeError):
            output = {"raw": result.output}

    return {
        "success": result.success,
        "data": output,
        "error": result.error,
        "audit_id": result.audit_id,
    }


@router.post(
    "/actions/create-task",
    response_model=ActionResponse,
    summary="Action: create a task for the agent",
)
async def action_create_task(
    body: CreateTaskRequest,
    request: Request,
    key_info: dict = Depends(_require_zapier_key),
) -> ActionResponse:
    """Create a new task assigned to a DingDawg agent.

    Called by Zapier when a user's Zap fires this action (e.g., when a
    new row appears in Google Sheets, create a task in DingDawg).
    """
    params: Dict[str, Any] = {
        "action": "create",
        "agent_id": body.agent_id,
        "title": body.title,
        "priority": body.priority,
        "user_id": f"zapier:{key_info['user_id']}",
    }
    if body.description:
        params["description"] = body.description
    if body.due_date:
        params["due_date"] = body.due_date
    if body.tags:
        params["tags"] = body.tags

    result = await _execute_skill(request, "tasks", params)

    return ActionResponse(
        id=result["data"].get("id", result.get("audit_id", "")),
        success=result["success"],
        data=result["data"],
        error=result.get("error"),
    )


    # NOTE: /actions/send-message (hyphen) removed — duplicate of zapier.py /actions/send_message (underscore).
    # The canonical action is in zapier.py and matches zapier_app_definition.json.


@router.post(
    "/actions/create-booking",
    response_model=ActionResponse,
    summary="Action: create a booking",
)
async def action_create_booking(
    body: CreateBookingRequest,
    request: Request,
    key_info: dict = Depends(_require_zapier_key),
) -> ActionResponse:
    """Create a booking for a DingDawg agent.

    Called by Zapier when a user's Zap fires this action (e.g., when
    a Calendly event is created, mirror it as a DingDawg booking).
    """
    params: Dict[str, Any] = {
        "action": "schedule",
        "agent_id": body.agent_id,
        "contact_name": body.contact_name,
        "title": body.title,
        "start_time": body.start_time,
        "user_id": f"zapier:{key_info['user_id']}",
    }
    if body.contact_email:
        params["contact_email"] = body.contact_email
    if body.contact_phone:
        params["contact_phone"] = body.contact_phone
    if body.end_time:
        params["end_time"] = body.end_time
    if body.description:
        params["description"] = body.description
    if body.location:
        params["location"] = body.location

    result = await _execute_skill(request, "appointments", params)

    return ActionResponse(
        id=result["data"].get("id", result.get("audit_id", "")),
        success=result["success"],
        data=result["data"],
        error=result.get("error"),
    )
