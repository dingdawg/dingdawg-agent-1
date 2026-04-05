"""Nango Connect routes — frontend calls these to initiate OAuth flows.

POST /api/v1/integrations/nango/connect   — get session token for Connect UI
GET  /api/v1/integrations/nango/status    — check connection status
DELETE /api/v1/integrations/nango/disconnect — revoke connection
GET  /api/v1/integrations/nango/config    — get public key for frontend
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from isg_agent.api.deps import require_auth, CurrentUser
from isg_agent.integrations.nango_bridge import (
    create_connection_session,
    get_connection,
    delete_connection,
    get_nango_provider,
    NANGO_PUBLIC_KEY,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/integrations/nango", tags=["nango"])


class ConnectRequest(BaseModel):
    integration_id: str  # e.g. "google_calendar", "stripe", "zapier"
    agent_id: str | None = None


class ConnectResponse(BaseModel):
    token: str | None = None
    public_key: str | None = None
    error: str | None = None


class StatusResponse(BaseModel):
    integration_id: str
    connected: bool
    provider: str | None = None
    metadata: dict | None = None


@router.get("/config")
async def get_nango_config():
    """Return Nango configuration status for frontend.

    Newer Nango versions use session tokens (from /connect endpoint)
    instead of a public key. This endpoint confirms Nango is configured.
    """
    from isg_agent.integrations.nango_bridge import NANGO_SECRET_KEY
    if not NANGO_SECRET_KEY:
        raise HTTPException(503, "Integration service not configured")
    return {"configured": True, "public_key": NANGO_PUBLIC_KEY or "session-token-mode"}


@router.post("/connect", response_model=ConnectResponse)
async def connect_integration(
    body: ConnectRequest,
    user: CurrentUser = Depends(require_auth),
):
    """Create a Nango session token for the frontend Connect UI.

    The frontend uses this token with nango.openConnectUI() to show
    the OAuth popup. After authorization, Nango stores the tokens.
    """
    provider = get_nango_provider(body.integration_id)
    if not provider:
        raise HTTPException(400, f"Unknown integration: {body.integration_id}")

    connection_id = f"{user.user_id}_{body.agent_id or 'default'}"

    result = await create_connection_session(
        provider=provider,
        connection_id=connection_id,
        end_user_id=user.email,
    )

    if "error" in result:
        return ConnectResponse(error=result["error"])

    return ConnectResponse(
        token=result.get("data", {}).get("token") or result.get("token"),
        public_key=NANGO_PUBLIC_KEY,
    )


@router.get("/status/{integration_id}", response_model=StatusResponse)
async def check_status(
    integration_id: str,
    user: CurrentUser = Depends(require_auth),
):
    """Check if a specific integration is connected for this user."""
    provider = get_nango_provider(integration_id)
    if not provider:
        raise HTTPException(400, f"Unknown integration: {integration_id}")

    connection_id = f"{user.user_id}_default"
    result = await get_connection(provider, connection_id)

    return StatusResponse(
        integration_id=integration_id,
        connected=result.get("connected", False),
        provider=provider,
        metadata=result if result.get("connected") else None,
    )


@router.delete("/disconnect/{integration_id}")
async def disconnect_integration(
    integration_id: str,
    user: CurrentUser = Depends(require_auth),
):
    """Disconnect an integration — revokes OAuth tokens."""
    provider = get_nango_provider(integration_id)
    if not provider:
        raise HTTPException(400, f"Unknown integration: {integration_id}")

    connection_id = f"{user.user_id}_default"
    success = await delete_connection(provider, connection_id)

    if not success:
        raise HTTPException(500, "Failed to disconnect integration")

    return {"status": "disconnected", "integration_id": integration_id}
