"""Pydantic schemas for session management models.

Defines the API-facing DTOs for creating, listing, and viewing
agent conversation sessions.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

__all__ = [
    "SessionCreate",
    "SessionResponse",
    "SessionList",
]


class SessionCreate(BaseModel):
    """Request body for creating a new session.

    The session is implicitly owned by the authenticated user.
    No body fields are strictly required; the model allows an
    optional ``system_prompt`` override.

    Attributes
    ----------
    system_prompt:
        Optional custom system prompt for this session.
    """

    system_prompt: Optional[str] = Field(
        default=None,
        max_length=5_000,
        description="Optional custom system prompt override.",
    )
    agent_id: Optional[str] = Field(
        default=None,
        description="Optional agent ID to bind this session to a specific agent.",
    )


class SessionResponse(BaseModel):
    """Response representing a single session.

    Attributes
    ----------
    session_id:
        Unique session identifier.
    user_id:
        The user who owns this session.
    created_at:
        ISO 8601 UTC creation timestamp.
    updated_at:
        ISO 8601 UTC last-update timestamp.
    message_count:
        Total messages exchanged in this session.
    total_tokens:
        Total LLM tokens consumed by this session.
    status:
        Session lifecycle status: "active" or "closed".
    """

    session_id: str
    user_id: str
    created_at: str
    updated_at: str
    message_count: int = 0
    total_tokens: int = 0
    status: str = "active"


class SessionList(BaseModel):
    """Response containing a list of sessions.

    Attributes
    ----------
    sessions:
        List of session objects.
    count:
        Total number of sessions returned.
    """

    sessions: list[SessionResponse]
    count: int
