"""Bridge and channel management endpoints.

Provides the HTTP API for managing communication channels (Discord,
Slack, Telegram, web).  Uses an in-memory channel registry for MVP
with a clean interface for future database backing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from isg_agent.api.deps import CurrentUser, require_auth

__all__ = ["router", "ChannelRegistry"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/channels", tags=["channels"])


# ---------------------------------------------------------------------------
# Channel data models
# ---------------------------------------------------------------------------


@dataclass
class Channel:
    """A communication channel.

    Attributes
    ----------
    id:
        Unique channel identifier.
    type:
        Channel type: ``"discord"``, ``"slack"``, ``"telegram"``, ``"web"``.
    name:
        Human-readable channel name.
    connected:
        Whether the channel is currently connected.
    config:
        Channel-specific configuration (tokens, webhook URLs, etc.).
    created_at:
        ISO 8601 UTC timestamp of channel creation.
    """

    id: str
    type: str
    name: str
    connected: bool = False
    config: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class ChannelRegistry:
    """In-memory channel registry.

    Provides CRUD operations for managing communication channels.
    Thread-safe for async access (single-writer pattern via dict operations).
    """

    def __init__(self) -> None:
        self._channels: dict[str, Channel] = {}

    def register(self, channel: Channel) -> None:
        """Register a new channel."""
        self._channels[channel.id] = channel

    def unregister(self, channel_id: str) -> bool:
        """Remove a channel.  Returns True if it existed."""
        return self._channels.pop(channel_id, None) is not None

    def get(self, channel_id: str) -> Optional[Channel]:
        """Get a channel by ID.  Returns None if not found."""
        return self._channels.get(channel_id)

    def list_all(self) -> list[Channel]:
        """Return all registered channels."""
        return sorted(self._channels.values(), key=lambda c: c.id)

    def set_connected(self, channel_id: str, connected: bool) -> bool:
        """Update a channel's connection status.  Returns False if not found."""
        ch = self._channels.get(channel_id)
        if ch is None:
            return False
        ch.connected = connected
        return True

    def count(self) -> int:
        """Return the number of registered channels."""
        return len(self._channels)


# ---------------------------------------------------------------------------
# Pydantic models for API
# ---------------------------------------------------------------------------


class ChannelResponse(BaseModel):
    """Channel information returned by API."""

    id: str
    type: str
    name: str
    connected: bool
    created_at: str


class ChannelStatusResponse(BaseModel):
    """Channel connection status."""

    id: str
    type: str
    name: str
    connected: bool


class SendMessageRequest(BaseModel):
    """Request to send a message through a channel."""

    content: str = Field(..., min_length=1, max_length=4096)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SendMessageResponse(BaseModel):
    """Response from sending a message."""

    sent: bool
    channel_id: str
    message_id: str = ""
    error: Optional[str] = None


class ChannelListResponse(BaseModel):
    """List of channels with count."""

    channels: list[ChannelResponse]
    count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_channel_registry(request: Request) -> ChannelRegistry:
    """Get ChannelRegistry from app state, creating one if needed."""
    registry: Optional[ChannelRegistry] = getattr(
        request.app.state, "channel_registry", None
    )
    if registry is None:
        registry = ChannelRegistry()
        request.app.state.channel_registry = registry
    return registry


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=ChannelListResponse,
    summary="List registered channels",
)
async def list_channels(request: Request) -> ChannelListResponse:
    """Return all registered communication channels."""
    registry = _get_channel_registry(request)
    channels = registry.list_all()

    items = [
        ChannelResponse(
            id=ch.id,
            type=ch.type,
            name=ch.name,
            connected=ch.connected,
            created_at=ch.created_at,
        )
        for ch in channels
    ]

    return ChannelListResponse(channels=items, count=len(items))


@router.get(
    "/{channel_id}/status",
    response_model=ChannelStatusResponse,
    summary="Get channel connection status",
)
async def get_channel_status(
    channel_id: str,
    request: Request,
) -> ChannelStatusResponse:
    """Return the connection status of a specific channel."""
    registry = _get_channel_registry(request)
    channel = registry.get(channel_id)

    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Channel not found: {channel_id!r}",
        )

    return ChannelStatusResponse(
        id=channel.id,
        type=channel.type,
        name=channel.name,
        connected=channel.connected,
    )


@router.post(
    "/{channel_id}/send",
    response_model=SendMessageResponse,
    summary="Send a message through a channel",
)
async def send_message(
    channel_id: str,
    body: SendMessageRequest,
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> SendMessageResponse:
    """Send a message through a specific channel.

    Requires authentication.  The channel must be registered and connected.
    """
    registry = _get_channel_registry(request)
    channel = registry.get(channel_id)

    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Channel not found: {channel_id!r}",
        )

    if not channel.connected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Channel {channel_id!r} is not connected",
        )

    # In MVP: log the message and return success
    # In production: dispatch to the channel's messaging API
    import uuid

    message_id = str(uuid.uuid4())
    logger.info(
        "Message sent to channel %s by user %s: %d chars",
        channel_id,
        user.user_id,
        len(body.content),
    )

    # Record to audit chain if available
    audit_chain = getattr(request.app.state, "audit_chain", None)
    if audit_chain is not None:
        await audit_chain.record(
            event_type="channel_message_sent",
            actor=user.user_id,
            details={
                "channel_id": channel_id,
                "channel_type": channel.type,
                "message_id": message_id,
                "content_length": len(body.content),
            },
        )

    return SendMessageResponse(
        sent=True,
        channel_id=channel_id,
        message_id=message_id,
    )
