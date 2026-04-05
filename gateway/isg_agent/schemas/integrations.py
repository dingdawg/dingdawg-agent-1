"""Pydantic schemas for the DD Main integration API.

Defines the request/response DTOs for registering, syncing, listing, and
unregistering DD Main businesses as Agent 1 agents.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

__all__ = [
    "BusinessRegisterRequest",
    "BusinessRegisterResponse",
    "BusinessSyncRequest",
    "BusinessSyncResponse",
    "BusinessMappingResponse",
    "BusinessMappingList",
]


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------


class BusinessRegisterRequest(BaseModel):
    """Request body for registering a DD Main business as an Agent 1 agent.

    Attributes
    ----------
    business_id:
        UUID string identifying the business in DD Main (required).
    name:
        Human-readable business display name (required).
    description:
        Optional short description used in the agent config.
    cuisine_type:
        Optional cuisine category (e.g. ``"Italian"``, ``"Mexican"``).
    address:
        Optional physical address stored in branding.
    logo_url:
        Optional URL of the business logo image.
    primary_color:
        Optional hex colour (e.g. ``"#FF5733"``) for branding.
    greeting:
        Optional custom greeting message the agent uses.
    handle_preference:
        Optional preferred @handle (3-30 chars, lowercase, hyphens).
        Falls back to auto-generated slug if unavailable or invalid.
    agentic_live:
        Whether this business's agent is live to customers.
    readiness_score:
        DD Main readiness score (0-100).
    offerings_count:
        Number of menu items / offerings in DD Main.
    """

    business_id: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="DD Main business UUID.",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Human-readable business name.",
    )
    description: Optional[str] = Field(default=None, max_length=1000)
    cuisine_type: Optional[str] = Field(default=None, max_length=100)
    address: Optional[str] = Field(default=None, max_length=500)
    logo_url: Optional[str] = Field(default=None, max_length=2048)
    primary_color: Optional[str] = Field(
        default=None,
        max_length=20,
        description="Hex colour string, e.g. '#FF5733'.",
    )
    greeting: Optional[str] = Field(default=None, max_length=500)
    handle_preference: Optional[str] = Field(
        default=None,
        min_length=3,
        max_length=30,
        description="Preferred @handle (lowercase letters, numbers, hyphens).",
    )
    agentic_live: Optional[bool] = Field(default=None)
    readiness_score: Optional[int] = Field(
        default=None,
        ge=0,
        le=100,
        description="DD Main readiness score (0-100).",
    )
    offerings_count: Optional[int] = Field(
        default=None,
        ge=0,
        description="Number of menu items / offerings.",
    )

    @field_validator("business_id")
    @classmethod
    def _strip_business_id(cls, v: str) -> str:
        return v.strip()

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        return v.strip()


class BusinessRegisterResponse(BaseModel):
    """Response after registering or updating a DD Main business.

    Attributes
    ----------
    agent_id:
        The Agent 1 UUID for this agent.
    handle:
        The @handle claimed for this agent.
    status:
        ``"created"`` if newly registered, ``"updated"`` if already existed.
    is_new:
        ``True`` if newly created, ``False`` if updated.
    """

    agent_id: str
    handle: str
    status: str
    is_new: bool


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


class BusinessSyncRequest(BaseModel):
    """Request body for syncing DD Main business updates to Agent 1.

    Attributes
    ----------
    business_id:
        DD Main business UUID identifying which business to sync.
    name:
        Updated display name (optional).
    description:
        Updated description (optional).
    cuisine_type:
        Updated cuisine category (optional).
    address:
        Updated address (optional).
    logo_url:
        Updated logo URL (optional).
    primary_color:
        Updated hex colour (optional).
    greeting:
        Updated greeting message (optional).
    agentic_live:
        Updated live status (optional).
    readiness_score:
        Updated readiness score 0-100 (optional).
    offerings_count:
        Updated offerings count (optional).
    """

    business_id: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="DD Main business UUID.",
    )
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=1000)
    cuisine_type: Optional[str] = Field(default=None, max_length=100)
    address: Optional[str] = Field(default=None, max_length=500)
    logo_url: Optional[str] = Field(default=None, max_length=2048)
    primary_color: Optional[str] = Field(default=None, max_length=20)
    greeting: Optional[str] = Field(default=None, max_length=500)
    agentic_live: Optional[bool] = Field(default=None)
    readiness_score: Optional[int] = Field(default=None, ge=0, le=100)
    offerings_count: Optional[int] = Field(default=None, ge=0)

    @field_validator("business_id")
    @classmethod
    def _strip_business_id(cls, v: str) -> str:
        return v.strip()


class BusinessSyncResponse(BaseModel):
    """Response after syncing a DD Main business.

    Attributes
    ----------
    agent_id:
        The Agent 1 UUID for this agent.
    handle:
        The @handle for this agent.
    updated_fields:
        List of field names that were updated.
    """

    agent_id: str
    handle: str
    updated_fields: List[str]


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------


class BusinessMappingResponse(BaseModel):
    """Response representing one DD Main → Agent 1 mapping.

    Attributes
    ----------
    business_id:
        DD Main business UUID.
    agent_id:
        Agent 1 agent UUID.
    handle:
        @handle of the Agent 1 agent.
    sync_status:
        One of ``"active"``, ``"paused"``, ``"removed"``.
    last_synced_at:
        ISO 8601 UTC timestamp of the last sync.
    created_at:
        ISO 8601 UTC timestamp when the mapping was first created.
    """

    business_id: str
    agent_id: str
    handle: str
    sync_status: str
    last_synced_at: str
    created_at: str


class BusinessMappingList(BaseModel):
    """Response containing a list of business mappings.

    Attributes
    ----------
    businesses:
        List of mapping objects.
    count:
        Total number returned.
    """

    businesses: List[BusinessMappingResponse]
    count: int
