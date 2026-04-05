"""Notification REST API — server-side notification persistence.

GET  /api/v1/notifications        — list recent notifications for user
POST /api/v1/notifications/{id}/read — mark notification as read
POST /api/v1/notifications/read-all  — mark all as read
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from isg_agent.api.deps import require_auth, CurrentUser

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: str
    type: str
    title: str
    body: str
    timestamp: str
    read: bool
    action_url: str | None = None
    agent_handle: str | None = None


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    request: Request,
    user: CurrentUser = Depends(require_auth),
    limit: int = 50,
):
    """List recent notifications for the authenticated user."""
    db: aiosqlite.Connection = request.app.state.db

    # Ensure table exists
    await db.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            type TEXT NOT NULL DEFAULT 'system',
            title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            timestamp TEXT NOT NULL,
            read INTEGER NOT NULL DEFAULT 0,
            action_url TEXT,
            agent_handle TEXT
        )
    """)
    await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_notifications_user
        ON notifications(user_id, timestamp DESC)
    """)
    await db.commit()

    cursor = await db.execute(
        "SELECT id, type, title, body, timestamp, read, action_url, agent_handle "
        "FROM notifications WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
        (user.user_id, limit),
    )
    rows = await cursor.fetchall()

    return [
        NotificationOut(
            id=r[0], type=r[1], title=r[2], body=r[3],
            timestamp=r[4], read=bool(r[5]),
            action_url=r[6], agent_handle=r[7],
        )
        for r in rows
    ]


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: str,
    request: Request,
    user: CurrentUser = Depends(require_auth),
):
    """Mark a single notification as read."""
    db: aiosqlite.Connection = request.app.state.db
    await db.execute(
        "UPDATE notifications SET read = 1 WHERE id = ? AND user_id = ?",
        (notification_id, user.user_id),
    )
    await db.commit()
    return {"status": "ok"}


@router.post("/read-all")
async def mark_all_read(
    request: Request,
    user: CurrentUser = Depends(require_auth),
):
    """Mark all notifications as read for this user."""
    db: aiosqlite.Connection = request.app.state.db
    await db.execute(
        "UPDATE notifications SET read = 1 WHERE user_id = ?",
        (user.user_id,),
    )
    await db.commit()
    return {"status": "ok"}
