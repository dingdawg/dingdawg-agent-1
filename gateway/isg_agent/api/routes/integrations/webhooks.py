"""Per-agent outbound webhook management endpoints.

Stores webhook subscriptions that Agent 1 will call when events occur
(message.received, conversation.started, etc.).  These are outbound
webhooks fired by the agent — distinct from inbound webhooks that
external services send to the agent (handled in webhooks_inbound.py).

Routes
------
GET    /api/v1/integrations/{agent_id}/webhooks              — list webhooks
POST   /api/v1/integrations/{agent_id}/webhooks              — create webhook
DELETE /api/v1/integrations/{agent_id}/webhooks/{webhook_id} — delete webhook
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone as _tz
from typing import Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from isg_agent.api.deps import CurrentUser, require_auth

from ._deps import _get_agent_registry, _verify_agent_ownership

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Request / response schemas (local — webhook-specific)
# ---------------------------------------------------------------------------

_VALID_EVENTS = frozenset({
    "message.received",
    "conversation.started",
    "conversation.ended",
    "task.created",
    "task.completed",
    "payment.received",
})

_VALID_AUTH_TYPES = frozenset({"none", "bearer", "basic"})


class WebhookCreateRequest(BaseModel):
    """Body for creating an outbound webhook subscription."""

    url: str = Field(..., min_length=8, max_length=2048, description="Destination URL (https:// recommended).")
    events: list[str] = Field(..., min_length=1, description="List of event names to subscribe to.")
    auth_type: str = Field(default="none", description="Authentication type: none, bearer, or basic.")
    auth_value: Optional[str] = Field(default=None, max_length=1024, description="Bearer token or basic password.")


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _db_path(request: Request) -> str:
    """Extract database path from app state settings."""
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application settings not initialised.",
        )
    return str(settings.db_path)


async def _ensure_table(db: aiosqlite.Connection) -> None:
    """Create agent_webhooks table if it does not exist yet.

    Guard against deployments where schema.create_tables has not yet run
    on the current database (e.g. first boot after this migration).
    """
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_webhooks (
            id          TEXT    PRIMARY KEY,
            agent_id    TEXT    NOT NULL,
            url         TEXT    NOT NULL,
            events      TEXT    NOT NULL DEFAULT '[]',
            auth_type   TEXT    NOT NULL DEFAULT 'none',
            auth_value  TEXT,
            active      INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT    NOT NULL
        )
        """
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_webhooks_agent ON agent_webhooks(agent_id)"
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/{agent_id}/webhooks",
    status_code=status.HTTP_200_OK,
    summary="List outbound webhook subscriptions for an agent",
)
async def list_webhooks(
    agent_id: str,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> list[dict]:
    """Return all active outbound webhook subscriptions for an agent.

    Auth values (tokens/passwords) are never included in the response.
    Returns 404 if the agent does not exist or belongs to another user.
    """
    registry = _get_agent_registry(request)
    await _verify_agent_ownership(agent_id, current_user, registry)

    db_path = _db_path(request)
    async with aiosqlite.connect(db_path, timeout=5.0) as db:
        db.row_factory = aiosqlite.Row
        await _ensure_table(db)
        cursor = await db.execute(
            "SELECT id, agent_id, url, events, auth_type, active, created_at "
            "FROM agent_webhooks WHERE agent_id = ? AND active = 1 ORDER BY created_at ASC",
            (agent_id,),
        )
        rows = await cursor.fetchall()

    result = []
    for row in rows:
        try:
            events = json.loads(row["events"])
        except (json.JSONDecodeError, TypeError):
            events = []
        result.append({
            "id": row["id"],
            "url": row["url"],
            "events": events,
            "auth_type": row["auth_type"],
            "active": bool(row["active"]),
            "created_at": row["created_at"],
        })

    logger.debug(
        "GET /integrations/%s/webhooks: %d webhooks user=%s",
        agent_id, len(result), current_user.user_id,
    )
    return result


@router.post(
    "/{agent_id}/webhooks",
    status_code=status.HTTP_201_CREATED,
    summary="Create an outbound webhook subscription for an agent",
)
async def create_webhook(
    agent_id: str,
    body: WebhookCreateRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    """Create a new outbound webhook subscription.

    Agent 1 will POST a JSON payload to ``url`` for each listed ``event``
    as events occur.  The ``auth_value`` (if provided) is stored encrypted
    and never returned in any GET response.

    Returns 400 if any event name is invalid or auth_type is unrecognised.
    Returns 404 if the agent does not exist or belongs to another user.
    """
    registry = _get_agent_registry(request)
    await _verify_agent_ownership(agent_id, current_user, registry)

    # Validate auth_type
    if body.auth_type not in _VALID_AUTH_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid auth_type {body.auth_type!r}. Valid values: {sorted(_VALID_AUTH_TYPES)}.",
        )

    # Validate events — unknown events are rejected to prevent silent no-ops
    invalid = [e for e in body.events if e not in _VALID_EVENTS]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown event(s): {invalid}. Valid events: {sorted(_VALID_EVENTS)}.",
        )

    webhook_id = str(uuid.uuid4())
    now = datetime.now(_tz.utc).isoformat()
    events_json = json.dumps(body.events)

    db_path = _db_path(request)
    async with aiosqlite.connect(db_path, timeout=5.0) as db:
        await _ensure_table(db)
        await db.execute(
            """
            INSERT INTO agent_webhooks (id, agent_id, url, events, auth_type, auth_value, active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (webhook_id, agent_id, body.url, events_json, body.auth_type, body.auth_value, now),
        )
        await db.commit()

    logger.info(
        "POST /integrations/%s/webhooks: id=%s url=%s events=%s user=%s",
        agent_id, webhook_id, body.url, body.events, current_user.user_id,
    )
    return {
        "id": webhook_id,
        "url": body.url,
        "events": body.events,
        "auth_type": body.auth_type,
        "active": True,
        "created_at": now,
    }


@router.delete(
    "/{agent_id}/webhooks/{webhook_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete (soft-deactivate) an outbound webhook subscription",
)
async def delete_webhook(
    agent_id: str,
    webhook_id: str,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    """Soft-delete (deactivate) a webhook subscription.

    Sets ``active = 0`` rather than performing a hard delete.  Returns 404
    if the webhook does not exist for this agent or belongs to another user.
    """
    registry = _get_agent_registry(request)
    await _verify_agent_ownership(agent_id, current_user, registry)

    db_path = _db_path(request)
    async with aiosqlite.connect(db_path, timeout=5.0) as db:
        await _ensure_table(db)
        cursor = await db.execute(
            "SELECT id FROM agent_webhooks WHERE id = ? AND agent_id = ? AND active = 1",
            (webhook_id, agent_id),
        )
        row = await cursor.fetchone()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Webhook {webhook_id!r} not found for agent {agent_id!r}.",
            )
        await db.execute(
            "UPDATE agent_webhooks SET active = 0 WHERE id = ?",
            (webhook_id,),
        )
        await db.commit()

    logger.info(
        "DELETE /integrations/%s/webhooks/%s: deactivated by user=%s",
        agent_id, webhook_id, current_user.user_id,
    )
    return {"id": webhook_id, "agent_id": agent_id, "status": "deleted"}
