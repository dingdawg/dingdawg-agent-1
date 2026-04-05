"""Pydantic schemas for task management and usage tracking models.

Defines the API-facing DTOs for creating, listing, updating, and viewing
tasks and usage data.  Follows the same patterns as schemas/agents.py.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

__all__ = [
    "TaskCreate",
    "TaskResponse",
    "TaskUpdate",
    "TaskList",
    "UsageResponse",
    "UsageHistory",
    "TierLimitResponse",
]

# Valid task types and statuses (mirroring the DB CHECK constraints)
_VALID_TASK_TYPES = frozenset(
    {"errand", "purchase", "booking", "reminder", "email", "research"}
)
_VALID_STATUSES = frozenset(
    {"pending", "in_progress", "completed", "failed", "cancelled"}
)


class TaskCreate(BaseModel):
    """Request body for creating a new agent task.

    Attributes
    ----------
    task_type:
        Category of work: errand | purchase | booking | reminder | email | research
    description:
        Human-readable description of what the task should accomplish.
    agent_id:
        The agent that owns this task.  When omitted the route derives it
        from the authenticated user's primary agent.
    """

    task_type: str = Field(
        ...,
        description=(
            "Task category. One of: errand, purchase, booking, "
            "reminder, email, research."
        ),
    )
    description: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Human-readable description of the task.",
    )
    agent_id: Optional[str] = Field(
        default=None,
        description="Agent that owns this task (UUID).  Optional — uses requester's agent if omitted.",
    )


class TaskResponse(BaseModel):
    """Response representing a single agent task.

    Attributes
    ----------
    id:
        Unique UUID for this task.
    agent_id:
        The agent that owns this task.
    user_id:
        The user who created this task.
    task_type:
        Category: errand | purchase | booking | reminder | email | research.
    description:
        Human-readable task description.
    status:
        Lifecycle status: pending | in_progress | completed | failed | cancelled.
    delegated_to:
        Optional @handle of the business agent this was delegated to.
    result_json:
        Optional JSON string with task result data.
    tokens_used:
        LLM tokens consumed executing this task.
    cost_cents:
        Cost in cents incurred by this task.
    created_at:
        ISO 8601 UTC creation timestamp.
    completed_at:
        ISO 8601 UTC completion timestamp, or None if not yet complete.
    """

    id: str
    agent_id: str
    user_id: str
    task_type: str
    description: str
    status: str
    delegated_to: Optional[str] = None
    result_json: Optional[str] = None
    tokens_used: int
    cost_cents: int
    created_at: str
    completed_at: Optional[str] = None


class TaskUpdate(BaseModel):
    """Request body for updating a task.

    All fields are optional.  Only provided fields are updated.

    Attributes
    ----------
    status:
        New lifecycle status.
    result_json:
        Updated result data as a JSON string.
    delegated_to:
        @handle of the business agent to delegate to.
    tokens_used:
        Tokens consumed so far.
    cost_cents:
        Cost incurred so far in cents.
    """

    status: Optional[str] = Field(
        default=None,
        description="New status. One of: pending, in_progress, completed, failed, cancelled.",
    )
    result_json: Optional[str] = Field(
        default=None,
        description="JSON string with task result data.",
    )
    delegated_to: Optional[str] = Field(
        default=None,
        description="@handle of the business agent this task is delegated to.",
    )
    tokens_used: Optional[int] = Field(
        default=None,
        ge=0,
        description="LLM tokens used.",
    )
    cost_cents: Optional[int] = Field(
        default=None,
        ge=0,
        description="Cost in cents.",
    )


class TaskList(BaseModel):
    """Response containing a list of tasks.

    Attributes
    ----------
    tasks:
        List of task objects.
    count:
        Total number of tasks returned.
    """

    tasks: list[TaskResponse]
    count: int


class UsageResponse(BaseModel):
    """Response for a single usage period.

    Attributes
    ----------
    id:
        Row UUID.
    agent_id:
        The agent this usage belongs to.
    period:
        Month in YYYY-MM format (e.g. ``"2026-02"``).
    llm_tokens:
        Total LLM tokens consumed this period.
    api_calls:
        Total API calls made this period.
    tasks_completed:
        Total tasks completed this period.
    transactions:
        Total inter-agent transactions this period.
    cost_cents:
        Total cost incurred in cents this period.
    created_at:
        ISO 8601 UTC timestamp for row creation.
    updated_at:
        ISO 8601 UTC timestamp for last update.
    """

    id: str
    agent_id: str
    period: str
    llm_tokens: int
    api_calls: int
    tasks_completed: int
    transactions: int
    cost_cents: int
    created_at: str
    updated_at: str


class UsageHistory(BaseModel):
    """Response containing usage history for an agent.

    Attributes
    ----------
    agent_id:
        The agent this history belongs to.
    periods:
        List of usage period records, most recent first.
    count:
        Number of periods returned.
    """

    agent_id: str
    periods: list[UsageResponse]
    count: int


class TierLimitResponse(BaseModel):
    """Response for a tier limit check.

    Attributes
    ----------
    allowed:
        True if the agent is within its tier limits, False if limit exceeded.
    reason:
        Human-readable explanation (especially useful when allowed=False).
    current:
        Current tasks_completed count for this period.
    limit:
        Tier limit for tasks per month (-1 = unlimited).
    tier:
        The tier being checked.
    period:
        The period being checked.
    """

    allowed: bool
    reason: str
    current: int
    limit: int
    tier: str
    period: str
