"""Pydantic request/response models for the 12 DingDawg Agent 1 MCP tools.

Each tool pair follows the pattern <ToolName>Input / <ToolName>Output.
Also exports MCPReceipt — the tamper-evident hash-chain receipt model attached
to every tool response for cryptographic audit trail.

Tools covered (12):
    1.  agent_create          — Provision a new agent
    2.  agent_get             — Retrieve agent by ID or handle
    3.  agent_list            — List agents for a user
    4.  agent_update          — Mutate mutable agent fields
    5.  conversation_start    — Open a new session
    6.  conversation_message  — Send a message within a session
    7.  conversation_end      — Close/finalise a session
    8.  skill_execute         — Run a named skill
    9.  usage_get             — Query usage/billing for an agent
    10. handle_check          — Check handle availability
    11. agent_status          — Get live status of an agent
    12. agent_delete          — Soft-delete (archive) an agent
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Receipt model (hash-chain audit)
# ---------------------------------------------------------------------------


class MCPReceipt(BaseModel):
    """Tamper-evident hash-chain receipt attached to every MCP tool response.

    Each receipt hashes its own inputs + outputs and chains from the previous
    receipt, providing a cryptographically verifiable audit trail.

    Attributes
    ----------
    audit_id:
        UUID uniquely identifying this receipt.
    tool_name:
        The MCP tool that produced this receipt (e.g. ``"agent_create"``).
    agent_handle:
        The @handle of the agent targeted by the tool call.
    timestamp:
        ISO 8601 UTC timestamp of the invocation.
    input_hash:
        SHA-256 hex digest of the canonical JSON-encoded tool inputs.
    output_hash:
        SHA-256 hex digest of the canonical JSON-encoded tool outputs.
    prev_receipt_hash:
        SHA-256 hex digest of the previous receipt in the chain
        (``"0" * 64`` for the genesis receipt).
    receipt_hash:
        SHA-256 hex digest of the combination of all fields above —
        the authoritative chain link.
    verify_url:
        Public URL where the receipt can be independently verified.
    """

    audit_id: str = Field(..., description="UUID for this receipt")
    tool_name: str = Field(..., description="MCP tool name")
    agent_handle: str = Field(..., description="Target agent @handle")
    timestamp: str = Field(..., description="ISO 8601 UTC timestamp")
    input_hash: str = Field(..., description="SHA-256 of canonical inputs JSON")
    output_hash: str = Field(..., description="SHA-256 of canonical outputs JSON")
    prev_receipt_hash: str = Field(
        ..., description="SHA-256 of previous receipt (genesis = 64 zeros)"
    )
    receipt_hash: str = Field(..., description="SHA-256 chain link (self-hash)")
    verify_url: str = Field(..., description="URL to independently verify receipt")


# ---------------------------------------------------------------------------
# 1. agent_create
# ---------------------------------------------------------------------------


class AgentCreateInput(BaseModel):
    """Inputs for the ``agent_create`` MCP tool."""

    user_id: str = Field(..., description="Owner user ID")
    handle: str = Field(..., description="Desired unique @handle (no @-prefix)")
    name: str = Field(..., description="Display name for the agent")
    agent_type: str = Field(
        "business",
        description=(
            "Agent type: personal | business | b2b | a2a | compliance | "
            "enterprise | health | gaming | community | marketing"
        ),
    )
    industry_type: Optional[str] = Field(None, description="Industry category")
    template_id: Optional[str] = Field(None, description="Template to seed from")
    config_json: str = Field("{}", description="JSON string of agent configuration")
    branding_json: str = Field("{}", description="JSON string of branding settings")


class AgentCreateOutput(BaseModel):
    """Output from the ``agent_create`` MCP tool."""

    agent_id: str
    handle: str
    name: str
    agent_type: str
    status: str
    subscription_tier: str
    created_at: str
    receipt: MCPReceipt


# ---------------------------------------------------------------------------
# 2. agent_get
# ---------------------------------------------------------------------------


class AgentGetInput(BaseModel):
    """Inputs for the ``agent_get`` MCP tool."""

    agent_id: Optional[str] = Field(None, description="Lookup by agent UUID")
    handle: Optional[str] = Field(None, description="Lookup by @handle (no @-prefix)")

    model_config = {"extra": "forbid"}


class AgentGetOutput(BaseModel):
    """Output from the ``agent_get`` MCP tool."""

    found: bool
    agent: Optional[Dict[str, Any]] = None
    receipt: MCPReceipt


# ---------------------------------------------------------------------------
# 3. agent_list
# ---------------------------------------------------------------------------


class AgentListInput(BaseModel):
    """Inputs for the ``agent_list`` MCP tool."""

    user_id: str = Field(..., description="Filter agents by owner")
    agent_type: Optional[str] = Field(None, description="Filter by agent type")
    limit: int = Field(20, ge=1, le=100, description="Max results")
    offset: int = Field(0, ge=0, description="Pagination offset")


class AgentListOutput(BaseModel):
    """Output from the ``agent_list`` MCP tool."""

    agents: List[Dict[str, Any]]
    total: int
    limit: int
    offset: int
    receipt: MCPReceipt


# ---------------------------------------------------------------------------
# 4. agent_update
# ---------------------------------------------------------------------------


class AgentUpdateInput(BaseModel):
    """Inputs for the ``agent_update`` MCP tool."""

    agent_id: str = Field(..., description="Agent UUID to update")
    name: Optional[str] = None
    config_json: Optional[str] = None
    branding_json: Optional[str] = None
    constitution_yaml: Optional[str] = None
    status: Optional[str] = Field(
        None, description="active | suspended | archived"
    )
    subscription_tier: Optional[str] = Field(
        None, description="free | starter | growth | scale"
    )
    industry_type: Optional[str] = None


class AgentUpdateOutput(BaseModel):
    """Output from the ``agent_update`` MCP tool."""

    updated: bool
    agent_id: str
    receipt: MCPReceipt


# ---------------------------------------------------------------------------
# 5. conversation_start
# ---------------------------------------------------------------------------


class ConversationStartInput(BaseModel):
    """Inputs for the ``conversation_start`` MCP tool."""

    user_id: str = Field(..., description="User who owns this session")
    agent_id: Optional[str] = Field(
        None, description="Agent to attach to this session"
    )


class ConversationStartOutput(BaseModel):
    """Output from the ``conversation_start`` MCP tool."""

    session_id: str
    user_id: str
    agent_id: Optional[str]
    status: str
    created_at: str
    receipt: MCPReceipt


# ---------------------------------------------------------------------------
# 6. conversation_message
# ---------------------------------------------------------------------------


class ConversationMessageInput(BaseModel):
    """Inputs for the ``conversation_message`` MCP tool."""

    session_id: str = Field(..., description="Active session UUID")
    user_id: str = Field(..., description="Message sender user ID")
    content: str = Field(..., description="Message content (plain text or Markdown)")
    agent_id: Optional[str] = Field(
        None, description="Agent handle to route to (defaults to session agent)"
    )


class ConversationMessageOutput(BaseModel):
    """Output from the ``conversation_message`` MCP tool."""

    session_id: str
    message_id: str
    role: str
    content: str
    tokens_used: int
    receipt: MCPReceipt


# ---------------------------------------------------------------------------
# 7. conversation_end
# ---------------------------------------------------------------------------


class ConversationEndInput(BaseModel):
    """Inputs for the ``conversation_end`` MCP tool."""

    session_id: str = Field(..., description="Session UUID to close")
    user_id: str = Field(..., description="Owner of the session")


class ConversationEndOutput(BaseModel):
    """Output from the ``conversation_end`` MCP tool."""

    session_id: str
    closed: bool
    final_message_count: int
    total_tokens: int
    receipt: MCPReceipt


# ---------------------------------------------------------------------------
# 8. skill_execute
# ---------------------------------------------------------------------------


class SkillExecuteInput(BaseModel):
    """Inputs for the ``skill_execute`` MCP tool."""

    agent_id: str = Field(..., description="Agent that owns the skill")
    skill_name: str = Field(..., description="Registered skill name to execute")
    parameters: Dict[str, Any] = Field(
        default_factory=dict, description="Key-value parameters passed to the skill"
    )
    user_id: str = Field(
        "system", description="User requesting execution (for usage metering)"
    )


class SkillExecuteOutput(BaseModel):
    """Output from the ``skill_execute`` MCP tool."""

    success: bool
    skill_name: str
    output: Any
    error: Optional[str]
    duration_ms: float
    audit_id: str
    usage: Dict[str, Any]
    receipt: MCPReceipt


# ---------------------------------------------------------------------------
# 9. usage_get
# ---------------------------------------------------------------------------


class UsageGetInput(BaseModel):
    """Inputs for the ``usage_get`` MCP tool."""

    agent_id: str = Field(..., description="Agent to query usage for")
    year_month: Optional[str] = Field(
        None,
        description="Month in YYYY-MM format (defaults to current UTC month)",
    )


class UsageGetOutput(BaseModel):
    """Output from the ``usage_get`` MCP tool."""

    agent_id: str
    year_month: str
    total_actions: int
    free_actions: int
    billed_actions: int
    total_amount_cents: int
    remaining_free: int
    plan: str
    actions_included: int
    receipt: MCPReceipt


# ---------------------------------------------------------------------------
# 10. handle_check
# ---------------------------------------------------------------------------


class HandleCheckInput(BaseModel):
    """Inputs for the ``handle_check`` MCP tool."""

    handle: str = Field(
        ..., description="Handle to check for availability (no @-prefix)"
    )


class HandleCheckOutput(BaseModel):
    """Output from the ``handle_check`` MCP tool."""

    handle: str
    available: bool
    reason: Optional[str] = None
    receipt: MCPReceipt


# ---------------------------------------------------------------------------
# 11. agent_status
# ---------------------------------------------------------------------------


class AgentStatusInput(BaseModel):
    """Inputs for the ``agent_status`` MCP tool."""

    agent_id: str = Field(..., description="Agent UUID to query")


class AgentStatusOutput(BaseModel):
    """Output from the ``agent_status`` MCP tool."""

    agent_id: str
    handle: str
    status: str
    subscription_tier: str
    skill_count: int
    session_count: int
    usage_this_month: int
    receipt: MCPReceipt


# ---------------------------------------------------------------------------
# 12. agent_delete
# ---------------------------------------------------------------------------


class AgentDeleteInput(BaseModel):
    """Inputs for the ``agent_delete`` MCP tool."""

    agent_id: str = Field(..., description="Agent UUID to soft-delete (archive)")
    user_id: str = Field(
        ..., description="Owner user ID (used for ownership validation)"
    )


class AgentDeleteOutput(BaseModel):
    """Output from the ``agent_delete`` MCP tool."""

    agent_id: str
    deleted: bool
    receipt: MCPReceipt


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    # Receipt
    "MCPReceipt",
    # agent_create
    "AgentCreateInput",
    "AgentCreateOutput",
    # agent_get
    "AgentGetInput",
    "AgentGetOutput",
    # agent_list
    "AgentListInput",
    "AgentListOutput",
    # agent_update
    "AgentUpdateInput",
    "AgentUpdateOutput",
    # conversation_start
    "ConversationStartInput",
    "ConversationStartOutput",
    # conversation_message
    "ConversationMessageInput",
    "ConversationMessageOutput",
    # conversation_end
    "ConversationEndInput",
    "ConversationEndOutput",
    # skill_execute
    "SkillExecuteInput",
    "SkillExecuteOutput",
    # usage_get
    "UsageGetInput",
    "UsageGetOutput",
    # handle_check
    "HandleCheckInput",
    "HandleCheckOutput",
    # agent_status
    "AgentStatusInput",
    "AgentStatusOutput",
    # agent_delete
    "AgentDeleteInput",
    "AgentDeleteOutput",
]
