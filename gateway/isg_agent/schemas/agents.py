"""Pydantic schemas for agent management models.

Defines the API-facing DTOs for creating, listing, updating, and viewing
agents, handle availability checks, and template discovery.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from isg_agent.agents.agent_types import VALID_AGENT_TYPES

# Build a regex alternation from VALID_AGENT_TYPES so the Pydantic pattern
# stays in sync with the single source of truth automatically.
_AGENT_TYPE_PATTERN: str = "^(" + "|".join(sorted(VALID_AGENT_TYPES)) + ")$"

__all__ = [
    "AgentCreate",
    "AgentResponse",
    "AgentUpdate",
    "AgentList",
    "HandleCheckResponse",
    "TemplateResponse",
    "TemplateList",
]


class AgentCreate(BaseModel):
    """Request body for creating a new agent.

    Attributes
    ----------
    handle:
        Unique @handle for this agent (3-30 chars, lowercase letters/numbers/hyphens).
    name:
        Human-readable display name.
    agent_type:
        ``"personal"`` or ``"business"``.
    industry_type:
        Optional industry category (e.g. ``"restaurant"``, ``"salon"``).
    template_id:
        Optional UUID of a template to base this agent on.
    branding_json:
        JSON string of branding/theming settings.
    """

    handle: str = Field(
        ...,
        min_length=3,
        max_length=30,
        pattern="^[a-z][a-z0-9-]*[a-z0-9]$",
        description="Unique @handle (lowercase letters, numbers, hyphens; must start and end with a letter or number).",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Display name for the agent.",
    )
    agent_type: str = Field(
        ...,
        pattern=_AGENT_TYPE_PATTERN,
        description=(
            "Agent type. Valid values: "
            + ", ".join(f"'{t}'" for t in sorted(VALID_AGENT_TYPES))
            + "."
        ),
    )
    industry_type: Optional[str] = Field(
        default=None,
        description="Optional industry category slug.",
    )
    template_id: Optional[str] = Field(
        default=None,
        description="Optional template UUID to base this agent on.",
    )
    branding_json: Optional[str] = Field(
        default="{}",
        description="JSON string of branding/theming settings.",
    )


class AgentResponse(BaseModel):
    """Response representing a single agent.

    Attributes
    ----------
    id:
        Unique UUID for this agent.
    user_id:
        The owner (user) who created this agent.
    handle:
        The agent's unique @handle.
    name:
        Display name.
    agent_type:
        ``"personal"`` or ``"business"``.
    industry_type:
        Optional industry category.
    template_id:
        Optional template UUID used at creation time.
    status:
        Lifecycle status: ``"active"``, ``"suspended"``, or ``"archived"``.
    subscription_tier:
        Billing tier: ``"free"``, ``"starter"``, ``"pro"``, or ``"enterprise"``.
    created_at:
        ISO 8601 UTC creation timestamp.
    updated_at:
        ISO 8601 UTC last-update timestamp.
    """

    id: str
    user_id: str
    handle: str
    name: str
    agent_type: str
    industry_type: Optional[str] = None
    template_id: Optional[str] = None
    config_json: Optional[str] = None
    branding_json: Optional[str] = None
    status: str
    subscription_tier: str
    created_at: str
    updated_at: str


class AgentUpdate(BaseModel):
    """Request body for updating an existing agent.

    All fields are optional.  Only provided fields are updated.

    Attributes
    ----------
    name:
        New display name.
    branding_json:
        Updated JSON string of branding/theming settings.
    config_json:
        Updated JSON string of agent configuration.
    """

    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    branding_json: Optional[str] = None
    config_json: Optional[str] = None


class AgentList(BaseModel):
    """Response containing a list of agents.

    Attributes
    ----------
    agents:
        List of agent objects.
    count:
        Total number of agents returned.
    """

    agents: list[AgentResponse]
    count: int


class HandleCheckResponse(BaseModel):
    """Response for a handle availability check.

    Attributes
    ----------
    handle:
        The handle that was checked.
    available:
        True if the handle is available to claim, False otherwise.
    """

    handle: str
    available: bool


class TemplateResponse(BaseModel):
    """Response representing a single template.

    Attributes
    ----------
    id:
        Unique UUID for this template.
    name:
        Human-readable template name.
    agent_type:
        ``"personal"`` or ``"business"``.
    industry_type:
        Optional industry slug.
    capabilities:
        JSON array string listing what this agent can do.
    icon:
        Optional emoji icon representing this industry.
    """

    id: str
    name: str
    agent_type: str
    industry_type: Optional[str] = None
    capabilities: str
    icon: Optional[str] = None


class TemplateList(BaseModel):
    """Response containing a list of templates.

    Attributes
    ----------
    templates:
        List of template objects.
    count:
        Total number of templates returned.
    """

    templates: list[TemplateResponse]
    count: int
