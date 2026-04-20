"""MCP tools for skill execution and discovery.

Tools
-----
skill.execute  — Execute a named skill via SkillExecutor.execute()
skill.list     — List all registered skills with descriptions

Both tools return the standard ok/err envelope with an MCPReceipt
(action_type, triggered_by, timestamp, outcome).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from isg_agent.capabilities.shared.foundation import (
    err,
    iso_now,
    make_receipt,
    ok,
)

# SkillExecutor is closed-source IP excluded from Railway via .gitignore.
# Import only at type-check time; annotations are lazy strings at runtime
# because of `from __future__ import annotations` above.
if TYPE_CHECKING:
    from isg_agent.skills.executor import SkillExecutor

__all__ = [
    "SKILL_DESCRIPTIONS",
    "skill_execute",
    "skill_list",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Skill descriptions registry
# Human-readable descriptions for all built-in / well-known skills.
# Operators may extend this dict when registering custom skills.
# ---------------------------------------------------------------------------

SKILL_DESCRIPTIONS: dict[str, str] = {
    "web_search": "Search the web for current information on any topic.",
    "code_runner": "Execute Python code snippets in a sandboxed environment.",
    "file_reader": "Read and summarise the contents of uploaded files.",
    "send_email": "Compose and send an email via the configured mail provider.",
    "send_sms": "Send an SMS message via the configured Telnyx / SMS provider.",
    "calendar_create": "Create a new calendar event or appointment.",
    "calendar_list": "List upcoming calendar events for the agent owner.",
    "crm_create_contact": "Create or update a contact in the CRM.",
    "crm_list_contacts": "List and filter CRM contacts.",
    "invoice_create": "Generate and send a new invoice to a client.",
    "invoice_list": "List outstanding and paid invoices.",
    "payment_request": "Request payment from a client via Stripe.",
    "expense_tracker": "Record and categorise a business expense.",
    "appointment_book": "Book a new appointment for a client.",
    "appointment_cancel": "Cancel an existing appointment.",
    "appointment_reschedule": "Reschedule an existing appointment.",
    "review_request": "Send a review-request message to a recent client.",
    "lead_capture": "Capture a new lead from a conversation.",
    "knowledge_search": "Search the agent's knowledge base for information.",
    "weather": "Retrieve current weather for a given location.",
    "translate": "Translate text between languages.",
    "summarise": "Summarise a long document or conversation.",
    "image_analyse": "Describe or extract structured data from an image.",
    "tournament_create": "Create a gaming tournament via the gaming skill pack.",
    "match_record": "Record the result of a match in the gaming skill pack.",
    "loot_grant": "Grant loot or rewards in the gaming skill pack.",
}


# ---------------------------------------------------------------------------
# MCPReceipt builder (thin wrapper over make_receipt for MCP context)
# ---------------------------------------------------------------------------


def _mcp_receipt(
    action_type: str,
    triggered_by: str,
    outcome: str,
    *,
    timestamp: Optional[str] = None,
) -> dict[str, Any]:
    """Build an MCPReceipt dict using the shared foundation make_receipt."""
    return make_receipt(
        action_type=action_type,
        triggered_by=triggered_by,
        outcome=outcome,
        timestamp=timestamp or iso_now(),
    )


# ---------------------------------------------------------------------------
# Tool: skill.execute
# ---------------------------------------------------------------------------


async def skill_execute(
    executor: SkillExecutor,
    skill_name: str,
    parameters: Optional[dict[str, Any]] = None,
    timeout: Optional[float] = None,
    triggered_by: str = "mcp_tool",
) -> dict[str, Any]:
    """MCP tool: skill.execute

    Execute a named skill through the provided :class:`SkillExecutor`.

    Parameters
    ----------
    executor:
        The application's SkillExecutor instance (injected by the MCP
        dispatcher or FastAPI dependency).
    skill_name:
        Name of the skill to execute (must be registered in the executor).
    parameters:
        Key-value parameters forwarded to the skill handler.
    timeout:
        Optional execution timeout in seconds.  Falls back to the
        executor's default when omitted.
    triggered_by:
        Actor identifier for the receipt (default: ``"mcp_tool"``).

    Returns
    -------
    dict
        ``ok`` envelope on success::

            {
                "ok": True,
                "data": {
                    "skill_name": str,
                    "output": str,
                    "duration_ms": int,
                    "audit_id": str,
                },
                "receipt": MCPReceipt,
            }

        ``err`` envelope on failure::

            {
                "ok": False,
                "error": str,
                "receipt": MCPReceipt,
            }
    """
    action_type = "skill.execute"

    try:
        result = await executor.execute(
            skill_name=skill_name,
            parameters=parameters,
            timeout=timeout,
        )
    except Exception as exc:
        logger.error("skill.execute MCP tool raised unexpectedly: %s", exc)
        return err(
            action_type=action_type,
            triggered_by=triggered_by,
            message=f"Unexpected error during skill execution: {type(exc).__name__}: {exc}",
        )

    if not result.success:
        receipt = _mcp_receipt(action_type, triggered_by, "failed")
        return {
            "ok": False,
            "error": result.error or "Skill execution failed",
            "receipt": receipt,
            "data": {
                "skill_name": result.skill_name,
                "duration_ms": result.duration_ms,
                "audit_id": result.audit_id,
            },
        }

    receipt = _mcp_receipt(action_type, triggered_by, "executed")
    return ok(
        data={
            "skill_name": result.skill_name,
            "output": result.output,
            "duration_ms": result.duration_ms,
            "audit_id": result.audit_id,
        },
        receipt=receipt,
    )


# ---------------------------------------------------------------------------
# Tool: skill.list
# ---------------------------------------------------------------------------


async def skill_list(
    executor: SkillExecutor,
    triggered_by: str = "mcp_tool",
) -> dict[str, Any]:
    """MCP tool: skill.list

    Return all skills registered in the executor, enriched with descriptions
    from :data:`SKILL_DESCRIPTIONS`.

    Parameters
    ----------
    executor:
        The application's SkillExecutor instance.
    triggered_by:
        Actor identifier for the receipt.

    Returns
    -------
    dict
        ``ok`` envelope::

            {
                "ok": True,
                "data": {
                    "skills": [
                        {"name": str, "description": str},
                        ...
                    ],
                    "total": int,
                },
                "receipt": MCPReceipt,
            }
    """
    action_type = "skill.list"

    try:
        skill_names = await executor.list_skills()
    except Exception as exc:
        logger.error("skill.list MCP tool raised unexpectedly: %s", exc)
        return err(
            action_type=action_type,
            triggered_by=triggered_by,
            message=f"Failed to list skills: {type(exc).__name__}: {exc}",
        )

    skills = [
        {
            "name": name,
            "description": SKILL_DESCRIPTIONS.get(name, "No description available."),
        }
        for name in skill_names
    ]

    receipt = _mcp_receipt(action_type, triggered_by, "executed")
    return ok(
        data={
            "skills": skills,
            "total": len(skills),
        },
        receipt=receipt,
    )
