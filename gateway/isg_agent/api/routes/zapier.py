"""Zapier integration endpoints for DingDawg Agent 1.

Provides REST endpoints compatible with the Zapier Developer Platform:

Triggers (polling-based):
    GET /api/v1/zapier/triggers/new_appointment    — New appointments
    GET /api/v1/zapier/triggers/new_invoice         — New invoices
    GET /api/v1/zapier/triggers/new_contact          — New contacts
    GET /api/v1/zapier/triggers/new_message           — New messages/notifications

Actions:
    POST /api/v1/zapier/actions/book_appointment    — Book an appointment
    POST /api/v1/zapier/actions/create_invoice       — Create an invoice
    POST /api/v1/zapier/actions/send_message          — Send a notification
    POST /api/v1/zapier/actions/create_contact        — Create a contact

Auth:
    GET  /api/v1/zapier/auth/test                    — Test API key validity

All endpoints use X-API-Key header authentication via the MCP API key
system. Zapier sends this header automatically after the user configures
their API key in the Zapier app.

Trigger endpoints return arrays of objects sorted by created_at DESC.
Zapier uses the 'id' field for deduplication.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/zapier", tags=["zapier"])


# ---------------------------------------------------------------------------
# Auth dependency
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
# Request / Response models
# ---------------------------------------------------------------------------


class BookAppointmentRequest(BaseModel):
    """Request to book an appointment via Zapier."""
    agent_handle: str = Field(..., description="Agent handle (e.g. joes-pizza)")
    contact_name: str = Field(..., description="Customer name")
    contact_email: Optional[str] = Field(None, description="Customer email")
    contact_phone: Optional[str] = Field(None, description="Customer phone")
    title: str = Field(..., description="Appointment title")
    start_time: str = Field(..., description="Start time (ISO 8601)")
    end_time: Optional[str] = Field(None, description="End time (ISO 8601)")
    description: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None


class CreateInvoiceRequest(BaseModel):
    """Request to create an invoice via Zapier."""
    agent_handle: str = Field(..., description="Agent handle")
    client_name: str = Field(..., description="Client name")
    client_email: Optional[str] = None
    line_items: List[Dict[str, Any]] = Field(
        ..., description="Array of {description, quantity, unit_price_cents}"
    )
    tax_rate: float = Field(0.0, description="Tax rate as decimal (e.g. 0.08 for 8%)")
    due_date: Optional[str] = None
    currency: str = "USD"
    notes: Optional[str] = None


class SendMessageRequest(BaseModel):
    """Request to send a notification via Zapier."""
    agent_handle: str = Field(..., description="Agent handle")
    channel: str = Field(..., description="Channel: email, sms, push, or webhook")
    recipient: str = Field(..., description="Recipient address (email or phone)")
    subject: Optional[str] = None
    body: str = Field(..., description="Message body")
    priority: str = Field("normal", description="Priority: low, normal, high, urgent")


class CreateContactRequest(BaseModel):
    """Request to create a contact via Zapier."""
    agent_handle: str = Field(..., description="Agent handle")
    name: str = Field(..., description="Contact name")
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    notes: Optional[str] = None
    source: str = Field("zapier", description="Lead source")


class ZapierActionResponse(BaseModel):
    """Standard response for Zapier actions."""
    id: str
    success: bool
    data: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_agent(request: Request, handle: str) -> str:
    """Resolve agent handle to ID. Raises 404 if not found."""
    registry = getattr(request.app.state, "agent_registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="Agent registry not initialized")
    agent = await registry.get_agent_by_handle(handle)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent @{handle} not found")
    return agent.id


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
    output = {}
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


async def _query_recent(
    request: Request,
    table: str,
    agent_handle: Optional[str],
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Query recent records from a skill table for Zapier polling triggers.

    Returns records sorted by created_at DESC with 'id' field for dedup.
    """
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        return []

    import aiosqlite

    try:
        async with aiosqlite.connect(settings.db_path) as db:
            db.row_factory = aiosqlite.Row

            if agent_handle:
                # Resolve agent handle to ID
                registry = getattr(request.app.state, "agent_registry", None)
                if registry:
                    agent = await registry.get_agent_by_handle(agent_handle)
                    agent_id = agent.id if agent else None
                else:
                    agent_id = None

                if agent_id:
                    cur = await db.execute(
                        f"SELECT * FROM {table} WHERE agent_id = ? "
                        f"ORDER BY created_at DESC LIMIT ?",
                        (agent_id, limit),
                    )
                else:
                    cur = await db.execute(
                        f"SELECT * FROM {table} ORDER BY created_at DESC LIMIT ?",
                        (limit,),
                    )
            else:
                cur = await db.execute(
                    f"SELECT * FROM {table} ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )

            rows = await cur.fetchall()
            return [dict(row) for row in rows]
    except Exception as exc:
        logger.error("Zapier trigger query failed for %s: %s", table, exc)
        return []


# ---------------------------------------------------------------------------
# Auth test endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/auth/test",
    summary="Test API key validity (Zapier authentication test)",
)
async def auth_test(
    key_info: dict = Depends(_require_zapier_key),
) -> Dict[str, Any]:
    """Verify the API key is valid.

    Zapier calls this endpoint during app setup to verify credentials.
    Returns the user info associated with the key.
    """
    return {
        "authenticated": True,
        "user_id": key_info["user_id"],
        "key_name": key_info["name"],
    }


# ---------------------------------------------------------------------------
# Triggers (polling)
# ---------------------------------------------------------------------------


@router.get(
    "/triggers/new_appointment",
    summary="Trigger: new appointments (Zapier polling)",
)
async def trigger_new_appointment(
    request: Request,
    agent_handle: Optional[str] = None,
    key_info: dict = Depends(_require_zapier_key),
) -> List[Dict[str, Any]]:
    """Return recent appointments for Zapier deduplication polling.

    Zapier polls this endpoint periodically and uses the 'id' field to
    detect new items. Returns up to 50 recent appointments sorted by
    created_at DESC.
    """
    records = await _query_recent(request, "skill_appointments", agent_handle)
    # Parse JSON fields for Zapier
    for r in records:
        r.setdefault("id", r.get("id", ""))
    return records


@router.get(
    "/triggers/new_invoice",
    summary="Trigger: new invoices (Zapier polling)",
)
async def trigger_new_invoice(
    request: Request,
    agent_handle: Optional[str] = None,
    key_info: dict = Depends(_require_zapier_key),
) -> List[Dict[str, Any]]:
    """Return recent invoices for Zapier deduplication polling."""
    records = await _query_recent(request, "skill_invoices", agent_handle)
    for r in records:
        r.setdefault("id", r.get("id", ""))
        # Parse line_items JSON for Zapier
        if isinstance(r.get("line_items"), str):
            try:
                r["line_items"] = json.loads(r["line_items"])
            except json.JSONDecodeError:
                pass
    return records


@router.get(
    "/triggers/new_contact",
    summary="Trigger: new contacts (Zapier polling)",
)
async def trigger_new_contact(
    request: Request,
    agent_handle: Optional[str] = None,
    key_info: dict = Depends(_require_zapier_key),
) -> List[Dict[str, Any]]:
    """Return recent contacts for Zapier deduplication polling."""
    records = await _query_recent(request, "skill_contacts", agent_handle)
    for r in records:
        r.setdefault("id", r.get("id", ""))
        # Parse JSON fields
        for field in ("tags", "custom_fields"):
            if isinstance(r.get(field), str):
                try:
                    r[field] = json.loads(r[field])
                except json.JSONDecodeError:
                    pass
    return records


@router.get(
    "/triggers/new_message",
    summary="Trigger: new notifications/messages (Zapier polling)",
)
async def trigger_new_message(
    request: Request,
    agent_handle: Optional[str] = None,
    key_info: dict = Depends(_require_zapier_key),
) -> List[Dict[str, Any]]:
    """Return recent notifications for Zapier deduplication polling."""
    records = await _query_recent(request, "skill_notifications", agent_handle)
    for r in records:
        r.setdefault("id", r.get("id", ""))
        if isinstance(r.get("metadata"), str):
            try:
                r["metadata"] = json.loads(r["metadata"])
            except json.JSONDecodeError:
                pass
    return records


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


@router.post(
    "/actions/book_appointment",
    response_model=ZapierActionResponse,
    summary="Action: book an appointment",
)
async def action_book_appointment(
    body: BookAppointmentRequest,
    request: Request,
    key_info: dict = Depends(_require_zapier_key),
) -> ZapierActionResponse:
    """Book a new appointment for a business agent via Zapier."""
    agent_id = await _resolve_agent(request, body.agent_handle)

    params = {
        "action": "schedule",
        "agent_id": agent_id,
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
    if body.notes:
        params["notes"] = body.notes

    result = await _execute_skill(request, "appointments", params)

    return ZapierActionResponse(
        id=result["data"].get("id", result.get("audit_id", "")),
        success=result["success"],
        data=result["data"],
        error=result.get("error"),
    )


@router.post(
    "/actions/create_invoice",
    response_model=ZapierActionResponse,
    summary="Action: create an invoice",
)
async def action_create_invoice(
    body: CreateInvoiceRequest,
    request: Request,
    key_info: dict = Depends(_require_zapier_key),
) -> ZapierActionResponse:
    """Create a new invoice for a business agent via Zapier."""
    agent_id = await _resolve_agent(request, body.agent_handle)

    params = {
        "action": "create",
        "agent_id": agent_id,
        "client_name": body.client_name,
        "line_items": body.line_items,
        "tax_rate": body.tax_rate,
        "currency": body.currency,
        "user_id": f"zapier:{key_info['user_id']}",
    }
    if body.client_email:
        params["client_email"] = body.client_email
    if body.due_date:
        params["due_date"] = body.due_date
    if body.notes:
        params["notes"] = body.notes

    result = await _execute_skill(request, "invoicing", params)

    return ZapierActionResponse(
        id=result["data"].get("id", result.get("audit_id", "")),
        success=result["success"],
        data=result["data"],
        error=result.get("error"),
    )


@router.post(
    "/actions/send_message",
    response_model=ZapierActionResponse,
    summary="Action: send a notification/message",
)
async def action_send_message(
    body: SendMessageRequest,
    request: Request,
    key_info: dict = Depends(_require_zapier_key),
) -> ZapierActionResponse:
    """Send a notification (email, SMS, push, webhook) via Zapier."""
    agent_id = await _resolve_agent(request, body.agent_handle)

    params = {
        "action": "send",
        "agent_id": agent_id,
        "channel": body.channel,
        "recipient": body.recipient,
        "body": body.body,
        "priority": body.priority,
        "user_id": f"zapier:{key_info['user_id']}",
    }
    if body.subject:
        params["subject"] = body.subject

    result = await _execute_skill(request, "notifications", params)

    return ZapierActionResponse(
        id=result["data"].get("id", result.get("audit_id", "")),
        success=result["success"],
        data=result["data"],
        error=result.get("error"),
    )


@router.post(
    "/actions/create_contact",
    response_model=ZapierActionResponse,
    summary="Action: create a CRM contact",
)
async def action_create_contact(
    body: CreateContactRequest,
    request: Request,
    key_info: dict = Depends(_require_zapier_key),
) -> ZapierActionResponse:
    """Create a new CRM contact for a business agent via Zapier."""
    agent_id = await _resolve_agent(request, body.agent_handle)

    params = {
        "action": "add",
        "agent_id": agent_id,
        "name": body.name,
        "source": body.source,
        "user_id": f"zapier:{key_info['user_id']}",
    }
    if body.email:
        params["email"] = body.email
    if body.phone:
        params["phone"] = body.phone
    if body.company:
        params["company"] = body.company
    if body.tags:
        params["tags"] = body.tags
    if body.notes:
        params["notes"] = body.notes

    result = await _execute_skill(request, "contacts", params)

    return ZapierActionResponse(
        id=result["data"].get("id", result.get("audit_id", "")),
        success=result["success"],
        data=result["data"],
        error=result.get("error"),
    )
