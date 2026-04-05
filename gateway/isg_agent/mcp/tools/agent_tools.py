"""MCP tool implementations for agent lifecycle management.

Provides four MCP-callable async tool functions:

- ``agent_create``   — create a new agent via AgentRegistry + HandleService
- ``agent_configure`` — update mutable agent fields via AgentRegistry.update_agent()
- ``agent_deploy``   — set agent status to active, return widget/API URLs
- ``agent_status``   — retrieve agent record + usage summary from UsageMeter

Each function is a standalone async function that accepts typed inputs,
calls the appropriate service layer, and returns an MCPReceipt dict.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from isg_agent.agents.agent_registry import AgentRegistry
from isg_agent.agents.agent_types import AgentRecord
from isg_agent.agents.handle_service import HandleService

__all__ = [
    "agent_create",
    "agent_configure",
    "agent_deploy",
    "agent_status",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Receipt builder
# ---------------------------------------------------------------------------

_RECEIPT_VERSION = "1.0"


def _build_receipt(
    tool: str,
    status: str,
    data: dict[str, Any],
    *,
    error: Optional[str] = None,
) -> dict[str, Any]:
    """Build a standardised MCPReceipt dictionary.

    Parameters
    ----------
    tool:
        Dot-namespaced tool identifier, e.g. ``"agent.create"``.
    status:
        ``"ok"`` on success, ``"error"`` on failure.
    data:
        Payload to include under the ``"data"`` key.
    error:
        Human-readable error description (only set when status == "error").

    Returns
    -------
    dict
        A receipt dict compatible with the MCP receipt protocol.
    """
    receipt: dict[str, Any] = {
        "receipt_version": _RECEIPT_VERSION,
        "tool": tool,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
    if error is not None:
        receipt["error"] = error
    return receipt


def _agent_record_to_dict(agent: AgentRecord) -> dict[str, Any]:
    """Serialize an AgentRecord to a plain dict for receipt payloads."""
    return {
        "id": agent.id,
        "user_id": agent.user_id,
        "handle": agent.handle,
        "name": agent.name,
        "agent_type": agent.agent_type.value,
        "industry_type": agent.industry_type,
        "template_id": agent.template_id,
        "status": agent.status.value,
        "subscription_tier": agent.subscription_tier.value,
        "created_at": agent.created_at,
        "updated_at": agent.updated_at,
    }


# ---------------------------------------------------------------------------
# agent.create
# ---------------------------------------------------------------------------


async def agent_create(
    *,
    user_id: str,
    handle: str,
    name: str,
    agent_type: str,
    industry_type: Optional[str] = None,
    template_id: Optional[str] = None,
    branding_json: str = "{}",
    config_json: str = "{}",
    agent_registry: AgentRegistry,
    handle_service: HandleService,
) -> dict[str, Any]:
    """Create a new agent and claim its handle.

    Wires into ``AgentRegistry.create_agent()`` and ``HandleService``.

    Parameters
    ----------
    user_id:
        Owner of the new agent.
    handle:
        Desired @handle (must pass HandleService validation).
    name:
        Display name for the agent.
    agent_type:
        Agent type string (e.g. ``"business"``).
    industry_type:
        Optional industry category.
    template_id:
        Optional template ID for prompt customisation.
    branding_json:
        JSON string of branding settings.
    config_json:
        JSON string of agent configuration.
    agent_registry:
        Injected ``AgentRegistry`` instance.
    handle_service:
        Injected ``HandleService`` instance.

    Returns
    -------
    dict
        MCPReceipt with created agent data on success, error details on failure.
    """
    tool_name = "agent.create"

    # Step 1: validate handle
    valid, reason = HandleService.validate_handle(handle)
    if not valid:
        return _build_receipt(
            tool_name,
            "error",
            {"handle": handle},
            error=f"Invalid handle: {reason}",
        )

    # Step 2: check availability
    try:
        available = await handle_service.is_available(handle)
    except Exception as exc:
        logger.error("agent_create: handle availability check failed: %s", exc)
        return _build_receipt(
            tool_name,
            "error",
            {"handle": handle},
            error=f"Handle availability check failed: {exc}",
        )

    if not available:
        return _build_receipt(
            tool_name,
            "error",
            {"handle": handle},
            error=f"Handle '{handle}' is already taken.",
        )

    # Step 3: reserve handle
    try:
        reserved = await handle_service.reserve_handle(handle)
    except Exception as exc:
        logger.error("agent_create: handle reservation failed: %s", exc)
        return _build_receipt(
            tool_name,
            "error",
            {"handle": handle},
            error=f"Handle reservation failed: {exc}",
        )

    if not reserved:
        return _build_receipt(
            tool_name,
            "error",
            {"handle": handle},
            error=f"Handle '{handle}' could not be reserved.",
        )

    # Step 4: create agent record
    try:
        agent = await agent_registry.create_agent(
            user_id=user_id,
            handle=handle,
            name=name,
            agent_type=agent_type,
            industry_type=industry_type,
            template_id=template_id,
            config_json=config_json,
            branding_json=branding_json,
        )
    except ValueError as exc:
        await handle_service.release_handle(handle)
        return _build_receipt(
            tool_name,
            "error",
            {"handle": handle},
            error=str(exc),
        )
    except Exception as exc:
        await handle_service.release_handle(handle)
        logger.error("agent_create: unexpected error creating agent: %s", exc)
        return _build_receipt(
            tool_name,
            "error",
            {"handle": handle},
            error=f"Agent creation failed: {exc}",
        )

    # Step 5: claim handle
    try:
        claimed = await handle_service.claim_handle(handle, agent.id)
    except Exception as exc:
        logger.error("agent_create: handle claim failed: %s", exc)
        claimed = False

    if not claimed:
        await handle_service.release_handle(handle)
        return _build_receipt(
            tool_name,
            "error",
            {"handle": handle, "agent_id": agent.id},
            error="Agent created but handle claim failed.",
        )

    logger.info(
        "agent_create: id=%s handle=%s type=%s user=%s",
        agent.id, handle, agent_type, user_id,
    )

    return _build_receipt(
        tool_name,
        "ok",
        {"agent": _agent_record_to_dict(agent)},
    )


# ---------------------------------------------------------------------------
# agent.configure
# ---------------------------------------------------------------------------


async def agent_configure(
    *,
    agent_id: str,
    agent_registry: AgentRegistry,
    name: Optional[str] = None,
    config_json: Optional[str] = None,
    branding_json: Optional[str] = None,
    industry_type: Optional[str] = None,
    constitution_yaml: Optional[str] = None,
    subscription_tier: Optional[str] = None,
) -> dict[str, Any]:
    """Update mutable configuration fields on an existing agent.

    Wires into ``AgentRegistry.update_agent()``.

    Parameters
    ----------
    agent_id:
        The UUID of the agent to configure.
    agent_registry:
        Injected ``AgentRegistry`` instance.
    name:
        New display name (optional).
    config_json:
        Updated JSON config string (optional).
    branding_json:
        Updated JSON branding string (optional).
    industry_type:
        Updated industry category (optional).
    constitution_yaml:
        Updated YAML constitution for governance (optional).
    subscription_tier:
        Updated subscription tier (optional).

    Returns
    -------
    dict
        MCPReceipt with updated agent data on success, error details on failure.
    """
    tool_name = "agent.configure"

    # Build kwargs — only pass fields that were explicitly provided
    updates: dict[str, Any] = {}
    if name is not None:
        updates["name"] = name
    if config_json is not None:
        updates["config_json"] = config_json
    if branding_json is not None:
        updates["branding_json"] = branding_json
    if industry_type is not None:
        updates["industry_type"] = industry_type
    if constitution_yaml is not None:
        updates["constitution_yaml"] = constitution_yaml
    if subscription_tier is not None:
        updates["subscription_tier"] = subscription_tier

    if not updates:
        return _build_receipt(
            tool_name,
            "error",
            {"agent_id": agent_id},
            error="No updatable fields provided.",
        )

    try:
        updated = await agent_registry.update_agent(agent_id, **updates)
    except ValueError as exc:
        return _build_receipt(
            tool_name,
            "error",
            {"agent_id": agent_id, "fields": list(updates.keys())},
            error=str(exc),
        )
    except Exception as exc:
        logger.error("agent_configure: unexpected error: %s", exc)
        return _build_receipt(
            tool_name,
            "error",
            {"agent_id": agent_id},
            error=f"Configure failed: {exc}",
        )

    if not updated:
        return _build_receipt(
            tool_name,
            "error",
            {"agent_id": agent_id},
            error=f"Agent not found: {agent_id}",
        )

    # Fetch refreshed record
    try:
        refreshed = await agent_registry.get_agent(agent_id)
    except Exception as exc:
        logger.error("agent_configure: get_agent after update failed: %s", exc)
        refreshed = None

    logger.info(
        "agent_configure: id=%s fields=%s",
        agent_id, list(updates.keys()),
    )

    return _build_receipt(
        tool_name,
        "ok",
        {
            "agent": _agent_record_to_dict(refreshed) if refreshed else None,
            "fields_updated": list(updates.keys()),
        },
    )


# ---------------------------------------------------------------------------
# agent.deploy
# ---------------------------------------------------------------------------

_BASE_WIDGET_URL = "https://app.dingdawg.com/widget"
_BASE_API_URL = "https://app.dingdawg.com/api/v1"


async def agent_deploy(
    *,
    agent_id: str,
    agent_registry: AgentRegistry,
) -> dict[str, Any]:
    """Set agent status to active and return widget/API endpoint URLs.

    Wires into ``AgentRegistry.update_agent()`` (status → active) and
    ``AgentRegistry.get_agent()`` for the refreshed record.

    Parameters
    ----------
    agent_id:
        The UUID of the agent to deploy.
    agent_registry:
        Injected ``AgentRegistry`` instance.

    Returns
    -------
    dict
        MCPReceipt with agent record, widget URL, and API URL on success.
    """
    tool_name = "agent.deploy"

    # Fetch agent to get handle for URL building
    try:
        agent = await agent_registry.get_agent(agent_id)
    except Exception as exc:
        logger.error("agent_deploy: get_agent failed: %s", exc)
        return _build_receipt(
            tool_name,
            "error",
            {"agent_id": agent_id},
            error=f"Failed to load agent: {exc}",
        )

    if agent is None:
        return _build_receipt(
            tool_name,
            "error",
            {"agent_id": agent_id},
            error=f"Agent not found: {agent_id}",
        )

    # Set status to active
    try:
        updated = await agent_registry.update_agent(agent_id, status="active")
    except ValueError as exc:
        return _build_receipt(
            tool_name,
            "error",
            {"agent_id": agent_id},
            error=str(exc),
        )
    except Exception as exc:
        logger.error("agent_deploy: update_agent status failed: %s", exc)
        return _build_receipt(
            tool_name,
            "error",
            {"agent_id": agent_id},
            error=f"Deploy failed: {exc}",
        )

    if not updated:
        return _build_receipt(
            tool_name,
            "error",
            {"agent_id": agent_id},
            error=f"Agent not found during deploy: {agent_id}",
        )

    # Fetch refreshed record
    try:
        deployed = await agent_registry.get_agent(agent_id)
    except Exception as exc:
        logger.error("agent_deploy: get_agent after deploy failed: %s", exc)
        deployed = agent  # fall back to pre-deploy snapshot

    handle = deployed.handle if deployed else agent.handle

    widget_url = f"{_BASE_WIDGET_URL}/{handle}"
    api_url = f"{_BASE_API_URL}/public/chat/{handle}"

    logger.info("agent_deploy: id=%s handle=%s deployed", agent_id, handle)

    return _build_receipt(
        tool_name,
        "ok",
        {
            "agent": _agent_record_to_dict(deployed) if deployed else None,
            "widget_url": widget_url,
            "api_url": api_url,
        },
    )


# ---------------------------------------------------------------------------
# agent.status
# ---------------------------------------------------------------------------


async def agent_status(
    *,
    agent_id: str,
    agent_registry: AgentRegistry,
    usage_meter: Optional[Any] = None,
    year_month: Optional[str] = None,
) -> dict[str, Any]:
    """Retrieve agent record and optional usage summary.

    Wires into ``AgentRegistry.get_agent()`` and optionally
    ``UsageMeter.get_usage_summary()``.

    Parameters
    ----------
    agent_id:
        The UUID of the agent to inspect.
    agent_registry:
        Injected ``AgentRegistry`` instance.
    usage_meter:
        Optional injected ``UsageMeter`` instance. If None, usage data
        is omitted from the receipt.
    year_month:
        Optional ``"YYYY-MM"`` string for usage summary. Defaults to
        the current month inside UsageMeter if not provided.

    Returns
    -------
    dict
        MCPReceipt with agent record and usage summary.
    """
    tool_name = "agent.status"

    # Fetch agent record
    try:
        agent = await agent_registry.get_agent(agent_id)
    except Exception as exc:
        logger.error("agent_status: get_agent failed: %s", exc)
        return _build_receipt(
            tool_name,
            "error",
            {"agent_id": agent_id},
            error=f"Failed to load agent: {exc}",
        )

    if agent is None:
        return _build_receipt(
            tool_name,
            "error",
            {"agent_id": agent_id},
            error=f"Agent not found: {agent_id}",
        )

    # Fetch usage summary if meter is available
    usage_summary: Optional[dict[str, Any]] = None
    if usage_meter is not None:
        try:
            usage_summary = await usage_meter.get_usage_summary(
                agent_id=agent_id,
                year_month=year_month,
            )
        except Exception as exc:
            logger.warning(
                "agent_status: get_usage_summary failed (non-blocking): %s", exc
            )
            usage_summary = {"error": str(exc)}

    return _build_receipt(
        tool_name,
        "ok",
        {
            "agent": _agent_record_to_dict(agent),
            "usage": usage_summary,
        },
    )
