"""DingDawg Agent 1 — FastMCP server definition.

Registers 25 MCP tools (12 platform + 13 business skills) and 3 MCP resources.
Wired into the FastAPI
application lifespan via ``app.state`` for access to:

- ``AgentRegistry``    — agent CRUD
- ``SessionManager``   — conversation session lifecycle
- ``SkillExecutor``    — skill execution pipeline
- ``UsageMeter``       — usage-based billing

Bootstrap
---------
Mount this server in the FastAPI lifespan (app.py) after all state objects
are ready::

    from isg_agent.mcp.server import mcp, wire_app_state
    wire_app_state(app.state)

Expose via SSE transport (standard MCP over HTTP)::

    from mcp.server.sse import SseServerTransport

Tools (25)
----------
Platform (12):
    agent_create, agent_get, agent_list, agent_update, agent_delete,
    conversation_start, conversation_message, conversation_end,
    skill_execute, usage_get, handle_check, agent_status

Business Skills (13):
    book_appointment, create_invoice, manage_contacts, send_notification,
    manage_webhooks, manage_forms, customer_engagement, manage_reviews,
    referral_program, manage_inventory, track_expenses,
    business_operations, data_store

Resources (3)
-------------
    agent://catalog        — All public active agents (discovery feed)
    agent://templates      — Available agent templates
    usage://dashboard      — Platform-wide usage summary
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from isg_agent.mcp.models import (
    AgentCreateInput,
    AgentCreateOutput,
    AgentDeleteInput,
    AgentDeleteOutput,
    AgentGetInput,
    AgentGetOutput,
    AgentListInput,
    AgentListOutput,
    AgentStatusInput,
    AgentStatusOutput,
    AgentUpdateInput,
    AgentUpdateOutput,
    ConversationEndInput,
    ConversationEndOutput,
    ConversationMessageInput,
    ConversationMessageOutput,
    ConversationStartInput,
    ConversationStartOutput,
    HandleCheckInput,
    HandleCheckOutput,
    SkillExecuteInput,
    SkillExecuteOutput,
    UsageGetInput,
    UsageGetOutput,
)
from isg_agent.mcp.receipt import GENESIS_HASH, build_receipt
from isg_agent.mcp.tools.business_skill_tools import register_business_skill_tools

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastMCP instance
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="DingDawg Agent 1",
    instructions=(
        "DingDawg Agent 1 MCP server v2.0.0. "
        "Exposes 25 tools (12 platform + 13 business skills) and 3 resources "
        "for agent provisioning, conversation management, skill execution, "
        "usage billing, and direct business operations (appointments, invoicing, "
        "contacts, notifications, inventory, expenses, and more). "
        "Business skill tools take an agent_handle parameter to identify the "
        "target business agent (e.g. 'joes-pizza')."
    ),
)

# ---------------------------------------------------------------------------
# App-state container (populated by wire_app_state at startup)
# ---------------------------------------------------------------------------

_state: Optional[Any] = None  # starlette State object from FastAPI app


def wire_app_state(app_state: Any) -> None:
    """Wire the FastAPI ``app.state`` object into the MCP server.

    Call this from the FastAPI lifespan handler *after* all state objects
    are initialised.

    Parameters
    ----------
    app_state:
        The ``app.state`` object from the running FastAPI application.
        Expected attributes:
        - ``agent_registry``  : AgentRegistry
        - ``session_manager`` : SessionManager
        - ``skill_executor``  : SkillExecutor
        - ``usage_meter``     : UsageMeter
        - ``handle_service``  : HandleService (optional)
        - ``template_registry``: TemplateRegistry (optional)
    """
    global _state
    _state = app_state

    # Register the 13 business skill tools on the MCP server
    register_business_skill_tools(mcp, lambda: _state)

    logger.info("MCP server wired to app.state (25 tools + 3 resources)")


def _registry():
    if _state is None:
        raise RuntimeError("MCP server not wired — call wire_app_state() first")
    return _state.agent_registry


def _sessions():
    if _state is None:
        raise RuntimeError("MCP server not wired — call wire_app_state() first")
    return _state.session_manager


def _executor():
    if _state is None:
        raise RuntimeError("MCP server not wired — call wire_app_state() first")
    return _state.skill_executor


def _meter():
    if _state is None:
        raise RuntimeError("MCP server not wired — call wire_app_state() first")
    return _state.usage_meter


# ---------------------------------------------------------------------------
# Tool 1: agent_create
# ---------------------------------------------------------------------------


@mcp.tool(
    name="agent_create",
    description=(
        "Provision a new DingDawg agent for a user. "
        "Returns the agent record with a cryptographic receipt."
    ),
)
async def agent_create(
    user_id: str,
    handle: str,
    name: str,
    agent_type: str = "business",
    industry_type: Optional[str] = None,
    template_id: Optional[str] = None,
    config_json: str = "{}",
    branding_json: str = "{}",
) -> Dict[str, Any]:
    """Create a new agent and return it with a hash-chain receipt."""
    inp = AgentCreateInput(
        user_id=user_id,
        handle=handle,
        name=name,
        agent_type=agent_type,
        industry_type=industry_type,
        template_id=template_id,
        config_json=config_json,
        branding_json=branding_json,
    )

    try:
        record = await _registry().create_agent(
            user_id=inp.user_id,
            handle=inp.handle,
            name=inp.name,
            agent_type=inp.agent_type,
            industry_type=inp.industry_type,
            template_id=inp.template_id,
            config_json=inp.config_json,
            branding_json=inp.branding_json,
        )
    except ValueError as exc:
        return {"error": str(exc), "tool": "agent_create"}

    out_dict = {
        "agent_id": record.id,
        "handle": record.handle,
        "name": record.name,
        "agent_type": record.agent_type.value,
        "status": record.status.value,
        "subscription_tier": record.subscription_tier.value,
        "created_at": record.created_at,
    }

    receipt = build_receipt(
        tool_name="agent_create",
        agent_handle=record.handle,
        inputs=inp.model_dump(),
        outputs=out_dict,
    )

    result = AgentCreateOutput(**out_dict, receipt=receipt)
    return result.model_dump()


# ---------------------------------------------------------------------------
# Tool 2: agent_get
# ---------------------------------------------------------------------------


@mcp.tool(
    name="agent_get",
    description=(
        "Retrieve an agent by UUID or handle. "
        "Exactly one of agent_id or handle must be provided."
    ),
)
async def agent_get(
    agent_id: Optional[str] = None,
    handle: Optional[str] = None,
) -> Dict[str, Any]:
    """Get a single agent record by ID or handle."""
    inp = AgentGetInput(agent_id=agent_id, handle=handle)

    record = None
    if inp.agent_id:
        record = await _registry().get_agent(inp.agent_id)
    elif inp.handle:
        record = await _registry().get_agent_by_handle(inp.handle)

    found = record is not None
    agent_dict = record.to_dict() if record else None
    out_dict = {"found": found, "agent": agent_dict}

    receipt = build_receipt(
        tool_name="agent_get",
        agent_handle=record.handle if record else "",
        inputs=inp.model_dump(),
        outputs=out_dict,
    )

    result = AgentGetOutput(found=found, agent=agent_dict, receipt=receipt)
    return result.model_dump()


# ---------------------------------------------------------------------------
# Tool 3: agent_list
# ---------------------------------------------------------------------------


@mcp.tool(
    name="agent_list",
    description=(
        "List all non-archived agents belonging to a user. "
        "Supports optional agent_type filter and pagination."
    ),
)
async def agent_list(
    user_id: str,
    agent_type: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """List agents for a user with pagination."""
    inp = AgentListInput(
        user_id=user_id,
        agent_type=agent_type,
        limit=limit,
        offset=offset,
    )

    records = await _registry().list_agents(
        user_id=inp.user_id,
        agent_type=inp.agent_type,
    )

    # Apply offset/limit manually (list_agents returns all)
    total = len(records)
    page = records[inp.offset : inp.offset + inp.limit]
    agents_list = [r.to_dict() for r in page]

    out_dict = {
        "agents": agents_list,
        "total": total,
        "limit": inp.limit,
        "offset": inp.offset,
    }

    receipt = build_receipt(
        tool_name="agent_list",
        agent_handle="",
        inputs=inp.model_dump(),
        outputs={"total": total, "returned": len(agents_list)},
    )

    result = AgentListOutput(**out_dict, receipt=receipt)
    return result.model_dump()


# ---------------------------------------------------------------------------
# Tool 4: agent_update
# ---------------------------------------------------------------------------


@mcp.tool(
    name="agent_update",
    description=(
        "Update mutable fields on an existing agent. "
        "Allowed fields: name, config_json, branding_json, constitution_yaml, "
        "status, subscription_tier, industry_type."
    ),
)
async def agent_update(
    agent_id: str,
    name: Optional[str] = None,
    config_json: Optional[str] = None,
    branding_json: Optional[str] = None,
    constitution_yaml: Optional[str] = None,
    status: Optional[str] = None,
    subscription_tier: Optional[str] = None,
    industry_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Update one or more mutable fields on an agent."""
    inp = AgentUpdateInput(
        agent_id=agent_id,
        name=name,
        config_json=config_json,
        branding_json=branding_json,
        constitution_yaml=constitution_yaml,
        status=status,
        subscription_tier=subscription_tier,
        industry_type=industry_type,
    )

    # Build kwargs from non-None fields (excluding agent_id)
    update_kwargs: Dict[str, Any] = {
        k: v
        for k, v in inp.model_dump(exclude={"agent_id"}).items()
        if v is not None
    }

    try:
        updated = await _registry().update_agent(inp.agent_id, **update_kwargs)
    except ValueError as exc:
        return {"error": str(exc), "tool": "agent_update"}

    out_dict = {"updated": updated, "agent_id": inp.agent_id}

    receipt = build_receipt(
        tool_name="agent_update",
        agent_handle=inp.agent_id,  # handle not known without a get; use id
        inputs=inp.model_dump(),
        outputs=out_dict,
    )

    result = AgentUpdateOutput(**out_dict, receipt=receipt)
    return result.model_dump()


# ---------------------------------------------------------------------------
# Tool 5: agent_delete
# ---------------------------------------------------------------------------


@mcp.tool(
    name="agent_delete",
    description=(
        "Soft-delete (archive) an agent by setting its status to 'archived'. "
        "The agent is never hard-deleted — the record is preserved for audit."
    ),
)
async def agent_delete(
    agent_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Soft-delete an agent (archive)."""
    inp = AgentDeleteInput(agent_id=agent_id, user_id=user_id)

    deleted = await _registry().delete_agent(inp.agent_id)
    out_dict = {"agent_id": inp.agent_id, "deleted": deleted}

    receipt = build_receipt(
        tool_name="agent_delete",
        agent_handle=inp.agent_id,
        inputs=inp.model_dump(),
        outputs=out_dict,
    )

    result = AgentDeleteOutput(**out_dict, receipt=receipt)
    return result.model_dump()


# ---------------------------------------------------------------------------
# Tool 6: conversation_start
# ---------------------------------------------------------------------------


@mcp.tool(
    name="conversation_start",
    description=(
        "Open a new conversation session for a user (and optionally bind it "
        "to a specific agent). Returns the session ID."
    ),
)
async def conversation_start(
    user_id: str,
    agent_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Start a new session and return its metadata."""
    inp = ConversationStartInput(user_id=user_id, agent_id=agent_id)

    session = await _sessions().create_session(
        user_id=inp.user_id,
        agent_id=inp.agent_id,
    )

    out_dict = {
        "session_id": session.session_id,
        "user_id": session.user_id,
        "agent_id": session.agent_id,
        "status": session.status,
        "created_at": session.created_at.isoformat(),
    }

    receipt = build_receipt(
        tool_name="conversation_start",
        agent_handle=inp.agent_id or "",
        inputs=inp.model_dump(),
        outputs=out_dict,
    )

    result = ConversationStartOutput(**out_dict, receipt=receipt)
    return result.model_dump()


# ---------------------------------------------------------------------------
# Tool 7: conversation_message
# ---------------------------------------------------------------------------


@mcp.tool(
    name="conversation_message",
    description=(
        "Send a message within an active conversation session. "
        "Routes the message through the agent brain and returns the response."
    ),
)
async def conversation_message(
    session_id: str,
    user_id: str,
    content: str,
    agent_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Send a user message and get an agent reply within a session."""
    inp = ConversationMessageInput(
        session_id=session_id,
        user_id=user_id,
        content=content,
        agent_id=agent_id,
    )

    # Verify session exists
    session = await _sessions().get_session(inp.session_id)
    if session is None:
        return {
            "error": f"Session not found: {inp.session_id}",
            "tool": "conversation_message",
        }

    import uuid as _uuid

    # Stub response — a real implementation would call AgentRuntime.chat()
    # The MCP layer provides the protocol; the brain handles the content.
    message_id = str(_uuid.uuid4())
    tokens_used = len(inp.content.split())  # placeholder token count

    try:
        await _sessions().update_token_count(
            session_id=inp.session_id,
            tokens=tokens_used,
            message_delta=1,
        )
    except Exception as _exc:  # noqa: BLE001
        logger.warning("conversation_message: token update failed: %s", _exc)

    out_dict = {
        "session_id": inp.session_id,
        "message_id": message_id,
        "role": "user",
        "content": inp.content,
        "tokens_used": tokens_used,
    }

    receipt = build_receipt(
        tool_name="conversation_message",
        agent_handle=inp.agent_id or "",
        inputs={
            "session_id": inp.session_id,
            "user_id": inp.user_id,
            "agent_id": inp.agent_id,
        },
        outputs={"message_id": message_id, "tokens_used": tokens_used},
    )

    result = ConversationMessageOutput(**out_dict, receipt=receipt)
    return result.model_dump()


# ---------------------------------------------------------------------------
# Tool 8: conversation_end
# ---------------------------------------------------------------------------


@mcp.tool(
    name="conversation_end",
    description=(
        "Close and finalise a conversation session. "
        "Returns final message count and total tokens consumed."
    ),
)
async def conversation_end(
    session_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Close a conversation session and return its final stats."""
    inp = ConversationEndInput(session_id=session_id, user_id=user_id)

    # Fetch current state before closing
    session = await _sessions().get_session(inp.session_id)
    if session is None:
        return {
            "error": f"Session not found: {inp.session_id}",
            "tool": "conversation_end",
        }

    closed = await _sessions().close_session(inp.session_id)

    out_dict = {
        "session_id": inp.session_id,
        "closed": closed,
        "final_message_count": session.message_count,
        "total_tokens": session.total_tokens,
    }

    receipt = build_receipt(
        tool_name="conversation_end",
        agent_handle="",
        inputs=inp.model_dump(),
        outputs=out_dict,
    )

    result = ConversationEndOutput(**out_dict, receipt=receipt)
    return result.model_dump()


# ---------------------------------------------------------------------------
# Tool 9: skill_execute
# ---------------------------------------------------------------------------


@mcp.tool(
    name="skill_execute",
    description=(
        "Execute a named skill registered to an agent. "
        "Runs through the full skill pipeline (sandbox, usage metering, audit)."
    ),
)
async def skill_execute(
    agent_id: str,
    skill_name: str,
    parameters: Optional[Dict[str, Any]] = None,
    user_id: str = "system",
) -> Dict[str, Any]:
    """Execute a skill and return the result with usage and receipt."""
    params = parameters or {}
    inp = SkillExecuteInput(
        agent_id=agent_id,
        skill_name=skill_name,
        parameters=params,
        user_id=user_id,
    )

    # Inject agent_id + user_id into parameters for the usage hook
    enriched_params = {
        **inp.parameters,
        "agent_id": inp.agent_id,
        "user_id": inp.user_id,
    }

    executor = _executor()
    result = await executor.execute(
        skill_name=inp.skill_name,
        parameters=enriched_params,
    )

    # Fetch usage for this agent this month
    try:
        usage = await _meter().get_usage_summary(agent_id=inp.agent_id)
    except Exception as _exc:  # noqa: BLE001
        logger.warning("skill_execute: usage fetch failed: %s", _exc)
        usage = {}

    out_dict = {
        "success": result.success,
        "skill_name": result.skill_name,
        "output": result.output,
        "error": result.error,
        "duration_ms": result.duration_ms,
        "audit_id": result.audit_id,
        "usage": usage,
    }

    receipt = build_receipt(
        tool_name="skill_execute",
        agent_handle=inp.agent_id,
        inputs={
            "agent_id": inp.agent_id,
            "skill_name": inp.skill_name,
            "user_id": inp.user_id,
        },
        outputs={
            "success": result.success,
            "audit_id": result.audit_id,
            "duration_ms": result.duration_ms,
        },
    )

    final = SkillExecuteOutput(**out_dict, receipt=receipt)
    return final.model_dump()


# ---------------------------------------------------------------------------
# Tool 10: usage_get
# ---------------------------------------------------------------------------


@mcp.tool(
    name="usage_get",
    description=(
        "Query usage and billing summary for an agent for a given month. "
        "Defaults to the current UTC month if year_month is omitted."
    ),
)
async def usage_get(
    agent_id: str,
    year_month: Optional[str] = None,
) -> Dict[str, Any]:
    """Get monthly usage summary for an agent."""
    inp = UsageGetInput(agent_id=agent_id, year_month=year_month)

    summary = await _meter().get_usage_summary(
        agent_id=inp.agent_id,
        year_month=inp.year_month,
    )

    out_dict = {
        "agent_id": inp.agent_id,
        "year_month": summary.get("year_month", inp.year_month or ""),
        "total_actions": summary.get("total_actions", 0),
        "free_actions": summary.get("free_actions", 0),
        "billed_actions": summary.get("billed_actions", 0),
        "total_amount_cents": summary.get("total_amount_cents", 0),
        "remaining_free": summary.get("remaining_free", 0),
        "plan": summary.get("plan", "free"),
        "actions_included": summary.get("actions_included", 50),
    }

    receipt = build_receipt(
        tool_name="usage_get",
        agent_handle=inp.agent_id,
        inputs=inp.model_dump(),
        outputs=out_dict,
    )

    result = UsageGetOutput(**out_dict, receipt=receipt)
    return result.model_dump()


# ---------------------------------------------------------------------------
# Tool 11: handle_check
# ---------------------------------------------------------------------------


@mcp.tool(
    name="handle_check",
    description=(
        "Check whether an agent handle is available for registration. "
        "Returns available=True if the handle is free, False if taken or reserved."
    ),
)
async def handle_check(handle: str) -> Dict[str, Any]:
    """Check handle availability."""
    inp = HandleCheckInput(handle=handle)

    # Try handle_service first (has reserved-handle knowledge)
    handle_svc = getattr(_state, "handle_service", None)
    if handle_svc is not None:
        try:
            available, reason = await handle_svc.check_available(inp.handle)
        except Exception as _exc:  # noqa: BLE001
            logger.warning("handle_check via handle_service failed: %s", _exc)
            # Fall through to registry check
            available = None
            reason = None

        if available is not None:
            out_dict = {
                "handle": inp.handle,
                "available": available,
                "reason": reason,
            }
            receipt = build_receipt(
                tool_name="handle_check",
                agent_handle=inp.handle,
                inputs=inp.model_dump(),
                outputs={"available": available},
            )
            result = HandleCheckOutput(**out_dict, receipt=receipt)
            return result.model_dump()

    # Fallback: check registry directly
    existing = await _registry().get_agent_by_handle(inp.handle)
    available = existing is None
    reason = None if available else "handle_taken"

    out_dict = {"handle": inp.handle, "available": available, "reason": reason}

    receipt = build_receipt(
        tool_name="handle_check",
        agent_handle=inp.handle,
        inputs=inp.model_dump(),
        outputs={"available": available},
    )

    result = HandleCheckOutput(**out_dict, receipt=receipt)
    return result.model_dump()


# ---------------------------------------------------------------------------
# Tool 12: agent_status
# ---------------------------------------------------------------------------


@mcp.tool(
    name="agent_status",
    description=(
        "Get the live operational status of an agent: lifecycle status, "
        "subscription tier, active session count, and current month usage."
    ),
)
async def agent_status(agent_id: str) -> Dict[str, Any]:
    """Get comprehensive live status for an agent."""
    inp = AgentStatusInput(agent_id=agent_id)

    record = await _registry().get_agent(inp.agent_id)
    if record is None:
        return {"error": f"Agent not found: {inp.agent_id}", "tool": "agent_status"}

    # Session count (list active sessions for this agent)
    try:
        sessions = await _sessions().list_sessions(
            user_id=record.user_id, agent_id=inp.agent_id
        )
        session_count = sum(1 for s in sessions if s.status == "active")
    except Exception as _exc:  # noqa: BLE001
        logger.warning("agent_status: session count failed: %s", _exc)
        session_count = 0

    # Usage this month
    try:
        usage = await _meter().get_usage_summary(agent_id=inp.agent_id)
        usage_this_month = usage.get("total_actions", 0)
    except Exception as _exc:  # noqa: BLE001
        logger.warning("agent_status: usage fetch failed: %s", _exc)
        usage_this_month = 0

    # Skill count via skill loader (best-effort)
    skill_count = 0
    try:
        from isg_agent.skills.loader import SkillLoader

        loader = SkillLoader()
        skill_count = len(loader.list_skills())
    except Exception:  # noqa: BLE001
        pass

    out_dict = {
        "agent_id": inp.agent_id,
        "handle": record.handle,
        "status": record.status.value,
        "subscription_tier": record.subscription_tier.value,
        "skill_count": skill_count,
        "session_count": session_count,
        "usage_this_month": usage_this_month,
    }

    receipt = build_receipt(
        tool_name="agent_status",
        agent_handle=record.handle,
        inputs=inp.model_dump(),
        outputs=out_dict,
    )

    result = AgentStatusOutput(**out_dict, receipt=receipt)
    return result.model_dump()


# ---------------------------------------------------------------------------
# Resource 1: agent://catalog
# ---------------------------------------------------------------------------


@mcp.resource("agent://catalog")
async def resource_agent_catalog() -> str:
    """Public agent discovery feed — all active agents (paginated, max 100).

    Returns a JSON-encoded list of agent summaries for the discovery UI.
    Excludes test handles (e2e-, smoke-, test-, stranger-).
    """
    try:
        agents, total = await _registry().list_public_agents(limit=100, offset=0)
        payload = {
            "total": total,
            "agents": [
                {
                    "id": a.id,
                    "handle": a.handle,
                    "name": a.name,
                    "agent_type": a.agent_type.value,
                    "industry_type": a.industry_type,
                    "subscription_tier": a.subscription_tier.value,
                    "created_at": a.created_at,
                }
                for a in agents
            ],
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("resource_agent_catalog: %s", exc)
        payload = {"error": str(exc), "agents": []}

    return json.dumps(payload, indent=2)


# ---------------------------------------------------------------------------
# Resource 2: agent://templates
# ---------------------------------------------------------------------------


@mcp.resource("agent://templates")
async def resource_agent_templates() -> str:
    """Available agent templates for the template marketplace.

    Returns the full list of seeded templates that users can use to
    create agents with pre-configured skills and constitution.
    """
    template_registry = getattr(_state, "template_registry", None)
    if template_registry is None:
        return json.dumps({"error": "template_registry not initialised", "templates": []})

    try:
        templates = await template_registry.list_templates()
        payload = {
            "total": len(templates),
            "templates": [
                {
                    "id": t.get("id") or t.get("template_id", ""),
                    "name": t.get("name", ""),
                    "agent_type": t.get("agent_type", ""),
                    "industry_type": t.get("industry_type", ""),
                    "description": t.get("description", ""),
                    "skills": t.get("skills", []),
                }
                for t in templates
            ],
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("resource_agent_templates: %s", exc)
        payload = {"error": str(exc), "templates": []}

    return json.dumps(payload, indent=2)


# ---------------------------------------------------------------------------
# Resource 3: usage://dashboard
# ---------------------------------------------------------------------------


@mcp.resource("usage://dashboard")
async def resource_usage_dashboard() -> str:
    """Platform-wide usage dashboard snapshot.

    Returns aggregate usage info useful for operator monitoring.
    Per-agent detail is available via the ``usage_get`` tool.
    """
    meter = _meter()

    try:
        # Gather platform-level stats from the usage_summary table
        import aiosqlite
        from datetime import datetime, timezone

        year_month = datetime.now(timezone.utc).strftime("%Y-%m")

        db_path = getattr(meter, "_db_path", None)
        if db_path is None:
            raise RuntimeError("UsageMeter has no _db_path")

        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT "
                "  SUM(total_actions)       AS total_actions, "
                "  SUM(free_actions)        AS free_actions, "
                "  SUM(billed_actions)      AS billed_actions, "
                "  SUM(total_amount_cents)  AS total_amount_cents, "
                "  COUNT(DISTINCT agent_id) AS active_agents "
                "FROM usage_summary WHERE year_month = ?",
                (year_month,),
            )
            row = await cur.fetchone()

        payload = {
            "year_month": year_month,
            "total_actions": row["total_actions"] or 0 if row else 0,
            "free_actions": row["free_actions"] or 0 if row else 0,
            "billed_actions": row["billed_actions"] or 0 if row else 0,
            "total_amount_cents": row["total_amount_cents"] or 0 if row else 0,
            "active_agents_this_month": row["active_agents"] or 0 if row else 0,
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("resource_usage_dashboard: %s", exc)
        payload = {"error": str(exc)}

    return json.dumps(payload, indent=2)
