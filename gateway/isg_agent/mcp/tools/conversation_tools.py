"""MCP tool implementations for conversation / session management.

Provides three MCP-callable async tool functions:

- ``conversation_start``   — create a new session via SessionManager.create_session()
- ``conversation_send``    — process a message via AgentRuntime.process_message()
- ``conversation_history`` — retrieve stored messages via MemoryStore.get_messages()

Each function is a standalone async function that accepts typed inputs,
calls the appropriate service layer, and returns an MCPReceipt dict.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from isg_agent.brain.agent import AgentRuntime
from isg_agent.brain.session import SessionManager, SessionNotFoundError
from isg_agent.memory.store import MemoryStore

__all__ = [
    "conversation_start",
    "conversation_send",
    "conversation_history",
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
        Dot-namespaced tool identifier, e.g. ``"conversation.start"``.
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


# ---------------------------------------------------------------------------
# conversation.start
# ---------------------------------------------------------------------------


async def conversation_start(
    *,
    user_id: str,
    session_manager: SessionManager,
    agent_id: Optional[str] = None,
) -> dict[str, Any]:
    """Create a new conversation session for a user.

    Wires into ``SessionManager.create_session()``.

    Parameters
    ----------
    user_id:
        The user who owns this session.
    session_manager:
        Injected ``SessionManager`` instance.
    agent_id:
        Optional agent UUID to bind this session to a specific agent.
        When set, the runtime will use that agent's persona and skills.

    Returns
    -------
    dict
        MCPReceipt with session_id, user_id, agent_id, and created_at.
    """
    tool_name = "conversation.start"

    try:
        session = await session_manager.create_session(
            user_id=user_id,
            agent_id=agent_id,
        )
    except Exception as exc:
        logger.error("conversation_start: create_session failed: %s", exc)
        return _build_receipt(
            tool_name,
            "error",
            {"user_id": user_id, "agent_id": agent_id},
            error=f"Failed to create session: {exc}",
        )

    logger.info(
        "conversation_start: session_id=%s user_id=%s agent_id=%s",
        session.session_id, user_id, agent_id,
    )

    return _build_receipt(
        tool_name,
        "ok",
        {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "agent_id": session.agent_id,
            "status": session.status,
            "created_at": session.created_at.isoformat(),
        },
    )


# ---------------------------------------------------------------------------
# conversation.send
# ---------------------------------------------------------------------------


async def conversation_send(
    *,
    session_id: str,
    message: str,
    agent_runtime: AgentRuntime,
    user_id: Optional[str] = None,
) -> dict[str, Any]:
    """Send a message through the full governed agent pipeline.

    Wires into ``AgentRuntime.process_message()``, which runs governance,
    LLM inference, skill dispatch, audit recording, and memory persistence.

    Parameters
    ----------
    session_id:
        The session to send the message in.
    message:
        The user's text input.
    agent_runtime:
        Injected ``AgentRuntime`` instance.
    user_id:
        Optional user ID passed to governance context and skill isolation.

    Returns
    -------
    dict
        MCPReceipt with agent response content, governance decision,
        model used, token counts, audit hash, and convergence status.
    """
    tool_name = "conversation.send"

    if not message or not message.strip():
        return _build_receipt(
            tool_name,
            "error",
            {"session_id": session_id},
            error="Message cannot be empty.",
        )

    try:
        response = await agent_runtime.process_message(
            session_id=session_id,
            user_message=message,
            user_id=user_id,
        )
    except SessionNotFoundError as exc:
        return _build_receipt(
            tool_name,
            "error",
            {"session_id": session_id},
            error=str(exc),
        )
    except Exception as exc:
        logger.error(
            "conversation_send: process_message failed session=%s: %s",
            session_id, exc,
        )
        return _build_receipt(
            tool_name,
            "error",
            {"session_id": session_id},
            error=f"Message processing failed: {exc}",
        )

    return _build_receipt(
        tool_name,
        "ok",
        {
            "session_id": response.session_id,
            "content": response.content,
            "model_used": response.model_used,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "governance_decision": response.governance_decision,
            "audit_hash": response.audit_hash,
            "convergence_status": response.convergence_status,
            "halted": response.halted,
        },
    )


# ---------------------------------------------------------------------------
# conversation.history
# ---------------------------------------------------------------------------


async def conversation_history(
    *,
    session_id: str,
    memory_store: MemoryStore,
    limit: int = 50,
    agent_id: Optional[str] = None,
) -> dict[str, Any]:
    """Retrieve stored message history for a session.

    Wires into ``MemoryStore.get_messages()``.  Messages are returned
    in chronological order (oldest first).

    Parameters
    ----------
    session_id:
        The session whose history to retrieve.
    memory_store:
        Injected ``MemoryStore`` instance.
    limit:
        Maximum number of messages to return (default 50, max 200).
    agent_id:
        Optional agent UUID for agent-scoped message filtering.

    Returns
    -------
    dict
        MCPReceipt with a ``messages`` list and ``count`` integer.
        Each message has: ``id``, ``session_id``, ``role``,
        ``content``, ``created_at``.
    """
    tool_name = "conversation.history"

    # Clamp limit to a safe maximum
    limit = max(1, min(limit, 200))

    try:
        messages = await memory_store.get_messages(
            session_id=session_id,
            limit=limit,
            agent_id=agent_id,
        )
    except Exception as exc:
        logger.error(
            "conversation_history: get_messages failed session=%s: %s",
            session_id, exc,
        )
        return _build_receipt(
            tool_name,
            "error",
            {"session_id": session_id},
            error=f"Failed to retrieve message history: {exc}",
        )

    return _build_receipt(
        tool_name,
        "ok",
        {
            "session_id": session_id,
            "messages": messages,
            "count": len(messages),
            "limit": limit,
        },
    )
