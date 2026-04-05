"""SSE streaming endpoint for the embeddable chat widget.

Provides POST /api/v1/widget/{agent_handle}/stream

This endpoint mirrors the existing /message endpoint but streams tokens
back to the client using Server-Sent Events (SSE) so the user sees words
appear in real-time rather than waiting for the full response.

SSE event format
----------------

Token event (one per LLM token chunk):
    event: token
    data: {"token": "Hello", "type": "token"}

Action event (zero or one, when LLM emits an ```action``` block):
    event: action
    data: {"type": "action", "skill": "contacts", "action": "add", "result": {...}}

Done event (always last):
    event: done
    data: {"type": "done", "full_response": "Hello there!", "action": null,
           "session_id": "...", "halted": false}

Error event (instead of done when something goes wrong mid-stream):
    event: error
    data: {"type": "error", "message": "Description of the error"}

CORS
----
All responses include ``Access-Control-Allow-Origin: *`` so the widget
can call this endpoint from any third-party site.

Rate limiting
-------------
Uses the same ``chat_rate_limit`` (30/minute) as the /message endpoint.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, AsyncGenerator, Optional

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import StreamingResponse

from isg_agent.middleware.rate_limiter_middleware import chat_rate_limit

__all__ = [
    "router",
    "_stream_llm_tokens",
    "_execute_skill_from_response",
    "_record_stream_usage",
]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/widget", tags=["widget-streaming"])

# ---------------------------------------------------------------------------
# SSE helper
# ---------------------------------------------------------------------------

_SSE_HEADERS: dict[str, str] = {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",          # disable nginx response buffering
    "Access-Control-Allow-Origin": "*",  # cross-origin widget support
}

_ACTION_PATTERN = re.compile(r"```action\s*\n(.*?)\n```", re.DOTALL)


def _sse_event(event: str, data: dict[str, Any]) -> str:
    """Format a single SSE event block.

    Parameters
    ----------
    event:
        SSE event name (e.g. "token", "done", "error", "action").
    data:
        Dictionary to JSON-encode into the ``data:`` line.

    Returns
    -------
    str
        A complete SSE event block including the trailing blank line.
    """
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ---------------------------------------------------------------------------
# Thin wrappers so tests can patch them independently
# ---------------------------------------------------------------------------


async def _stream_llm_tokens(
    runtime: Any,
    session_id: str,
    user_message: str,
    user_id: str,
) -> AsyncGenerator[str, None]:
    """Yield raw token strings from the LLM via the provider's stream() method.

    This is a thin shim around the AgentRuntime/OpenAIProvider so tests can
    patch it with a simple async generator without needing a full LLM key.

    The implementation replicates the prompt-building logic from
    ``AgentRuntime.process_message`` but calls ``provider.stream()``
    instead of ``provider.complete()``.  Governance, memory, and audit are
    still applied — only the LLM call is streaming.

    Parameters
    ----------
    runtime:
        The ``AgentRuntime`` stored on ``app.state.runtime``.
    session_id:
        Active session to stream into.
    user_message:
        The user's text input.
    user_id:
        Widget visitor identifier (used for multi-tenant isolation).

    Yields
    ------
    str
        Successive token strings from the LLM.
    """
    from isg_agent.brain.agent import _build_agent_preamble, _PROMPT_ARMOR, SKILL_DESCRIPTIONS
    from isg_agent.models.provider import LLMMessage

    # Load session
    session = await runtime._sessions.get_session(session_id)
    if session is None:
        from isg_agent.brain.session import SessionNotFoundError
        raise SessionNotFoundError(session_id)

    # Build system prompt — identical logic to AgentRuntime.process_message
    system_prompt = runtime._config.system_prompt
    if session.agent_id and runtime._agent_registry:
        try:
            agent_record = await runtime._agent_registry.get_agent(session.agent_id)
            if agent_record is not None:
                template_record = None
                if agent_record.template_id and runtime._template_registry:
                    template_record = await runtime._template_registry.get_template(
                        agent_record.template_id
                    )
                system_prompt = _build_agent_preamble(agent_record, template_record)
        except Exception as exc:
            logger.warning(
                "Failed to load agent preamble for streaming session %s: %s — using generic",
                session_id, exc,
            )

    system_content = _PROMPT_ARMOR + system_prompt
    # Add skill tool descriptions if available
    if runtime._skill_executor:
        skills = await runtime._skill_executor.list_skills()
        if skills:
            tool_lines = [
                "\n## Available Actions",
                "You can perform actions for the user by responding with a JSON action block.",
                "When you determine the user wants you to DO something (not just answer), respond with:",
                "```action",
                '{"skill": "skill-name", "action": "action-name", "parameters": {...}}',
                "```",
                "Available skills:",
                *[SKILL_DESCRIPTIONS.get(n, f"- {n}") for n in skills],
                "",
                "IMPORTANT: Only use an action when the user clearly wants you to perform a task.",
                "For questions and conversation, respond normally without action blocks.",
                "After performing an action, summarize what you did in natural language.",
            ]
            system_content = system_content + "\n".join(tool_lines)

    history = await runtime._memory.get_messages(
        session_id=session_id,
        limit=runtime._config.max_history_messages,
    )

    messages: list[LLMMessage] = [LLMMessage(role="system", content=system_content)]
    for hist_msg in history:
        role = str(hist_msg.get("role", "user"))
        content = str(hist_msg.get("content", ""))
        if role in ("user", "assistant", "system"):
            messages.append(LLMMessage(role=role, content=content))
    messages.append(LLMMessage(role="user", content=user_message))

    # Use the first provider in the fallback chain that supports stream()
    provider_names = runtime._registry.list_providers()
    if not provider_names:
        raise RuntimeError("No LLM provider registered")

    provider = runtime._registry.get(provider_names[0])
    async for token in provider.stream(
        messages,
        temperature=runtime._config.temperature,
        max_tokens=runtime._config.max_tokens,
    ):
        yield token


async def _execute_skill_from_response(
    runtime: Any,
    response_text: str,
    agent_id: Optional[str],
    user_id: Optional[str] = None,
) -> Optional[tuple[str, str, str]]:
    """Parse and execute a skill action block from an LLM response.

    Parameters
    ----------
    runtime:
        The ``AgentRuntime`` instance.
    response_text:
        The full assembled LLM response text to scan for action blocks.
    agent_id:
        Optional agent ID for multi-tenant data isolation.

    Returns
    -------
    tuple of (skill_name, action_name, result_json) or None
        None if the response contained no action block.
    """
    match = _ACTION_PATTERN.search(response_text)
    if not match:
        return None

    try:
        action_data = json.loads(match.group(1).strip())
    except json.JSONDecodeError:
        return None

    skill_name: str = action_data.get("skill", "")
    action_name: str = action_data.get("action", "")
    params: dict[str, Any] = action_data.get("parameters", {})

    if not skill_name or not action_name:
        return None

    if agent_id:
        params["agent_id"] = agent_id
    # Inject user_id so the billing hook receives the real visitor/user identity
    if user_id:
        params["user_id"] = user_id
    params["action"] = action_name

    if not runtime._skill_executor:
        return (skill_name, action_name, json.dumps({"error": "Skill executor not available"}))

    result = await runtime._skill_executor.execute(skill_name, params)
    result_str = result.output if result.success else json.dumps({"error": result.error})
    return (skill_name, action_name, result_str)


async def _record_stream_usage(
    request: Request,
    session_id: str,
    user_id: str,
    user_message: str,
    full_response: str,
    input_tokens: int,
    output_tokens: int,
    provider_name: str = "unknown",
) -> None:
    """Persist the streaming interaction to memory, session stats, and audit.

    This mirrors the persistence steps (8-10) in AgentRuntime.process_message.
    Called once at the end of a successful stream.  Errors are logged but
    never re-raised (best-effort, non-blocking).

    Parameters
    ----------
    request:
        The FastAPI request (used to access app.state components).
    session_id:
        The active session ID.
    user_id:
        Widget visitor user ID.
    user_message:
        The user's original message text.
    full_response:
        The fully assembled LLM response text.
    input_tokens:
        Estimated input token count.
    output_tokens:
        Estimated output token count (approximate — streaming doesn't give exact counts).
    provider_name:
        The canonical provider name for this stream (e.g. ``"openai"``).
        Defaults to ``"unknown"`` when the provider cannot be determined.
    """
    try:
        memory = request.app.state.memory_store
        await memory.save_message(session_id=session_id, role="user", content=user_message)
        await memory.save_message(session_id=session_id, role="assistant", content=full_response)
    except Exception as exc:
        logger.warning("Stream memory save failed (session=%s): %s", session_id, exc)

    try:
        session_manager = request.app.state.session_manager
        total_tokens = input_tokens + output_tokens
        from isg_agent.brain.session import SessionNotFoundError
        await session_manager.update_token_count(
            session_id=session_id,
            tokens=total_tokens,
            message_delta=2,
        )
    except Exception as exc:
        logger.warning("Stream session token update failed (session=%s): %s", session_id, exc)

    try:
        audit_chain = request.app.state.audit_chain
        await audit_chain.record(
            event_type="agent_stream_response",
            actor=f"session:{session_id}",
            details={
                "session_id": session_id,
                "user_id": user_id,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "streaming": True,
                "provider": provider_name,
            },
        )
    except Exception as exc:
        logger.warning("Stream audit record failed (session=%s): %s", session_id, exc)

    # Best-effort financial ledger record (LLM API cost for the stream)
    try:
        ledger = getattr(request.app.state, "ledger", None)
        if ledger is not None:
            # Approximate cost: 10 cents per 1k tokens (gpt-4o-mini estimate)
            token_cost_cents = max(1, (input_tokens + output_tokens) // 100)
            await ledger.record_cost(
                cost_type="api_cost",
                amount_cents=token_cost_cents,
                description=f"streaming LLM call session={session_id}",
                agent_id=user_id,
            )
    except Exception as exc:
        logger.warning("Stream ledger cost record failed (session=%s): %s", session_id, exc)


# ---------------------------------------------------------------------------
# CORS pre-flight support
# ---------------------------------------------------------------------------


@router.options("/{agent_handle}/stream")
async def widget_stream_preflight(
    request: Request,
    agent_handle: str,
) -> StreamingResponse:
    """Handle CORS OPTIONS preflight for the streaming endpoint.

    Cross-origin POST requests with Content-Type: application/json trigger
    a preflight.  We return the appropriate CORS headers so the browser
    allows the subsequent POST.
    """
    return StreamingResponse(
        content=iter([]),
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Access-Control-Max-Age": "86400",
        },
    )


# ---------------------------------------------------------------------------
# Main streaming endpoint
# ---------------------------------------------------------------------------


@router.post("/{agent_handle}/stream")
@chat_rate_limit()
async def widget_stream_message(
    request: Request,
    agent_handle: str,
) -> StreamingResponse:
    """Stream LLM tokens for a widget chat message using Server-Sent Events.

    PUBLIC endpoint — no JWT required.  Same audience as /widget/message.

    Request body
    ------------
    ``{session_id: str, message: str, visitor_id?: str}``

    Response
    --------
    ``text/event-stream`` — successive SSE events:
    - ``event: token`` for each LLM token chunk
    - ``event: action`` if the LLM invoked a skill
    - ``event: done`` as the final event
    - ``event: error`` on failure

    Parameters
    ----------
    request:
        FastAPI request (carries app.state components).
    agent_handle:
        The ``@handle`` of the target agent.
    """
    handle = agent_handle.lstrip("@")

    # -- Validate agent exists ----------------------------------------------
    agent_registry = request.app.state.agent_registry
    agent = await agent_registry.get_agent_by_handle(handle)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    # -- Parse body ---------------------------------------------------------
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    session_id: Optional[str] = body.get("session_id")
    message: str = (body.get("message") or "").strip()
    visitor_id: str = body.get("visitor_id") or f"visitor-{uuid.uuid4().hex[:8]}"

    if not session_id or not message:
        raise HTTPException(
            status_code=400,
            detail="session_id and message are required",
        )

    # -- Validate session exists before streaming ---------------------------
    session_manager = request.app.state.session_manager
    session = await session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    # -- Run governance gate ------------------------------------------------
    runtime = request.app.state.runtime
    from isg_agent.core.governance import GovernanceDecision, RiskTier

    task_description = (
        f"Process streaming widget message in session {session_id}: {message[:200]}"
    )
    governance_result = await runtime._governance.evaluate(
        task_description=task_description,
        risk_tier=RiskTier.LOW,
    )

    if governance_result.decision == GovernanceDecision.HALT:
        # Governance blocked — stream a single error event then done
        async def _halt_stream() -> AsyncGenerator[str, None]:
            yield _sse_event("error", {
                "type": "error",
                "message": (
                    "Your request has been blocked by the governance system. "
                    "Please rephrase your message and try again."
                ),
            })
            yield _sse_event("done", {
                "type": "done",
                "full_response": "",
                "action": None,
                "session_id": session_id,
                "halted": True,
            })

        return StreamingResponse(
            content=_halt_stream(),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    user_id = f"widget:{visitor_id}"

    # -- Build the SSE generator --------------------------------------------
    async def _sse_generator() -> AsyncGenerator[str, None]:
        full_response: list[str] = []
        action_info: Optional[dict[str, Any]] = None
        input_tokens = 0
        output_tokens = 0

        try:
            token_stream = _stream_llm_tokens(
                runtime=runtime,
                session_id=session_id,
                user_message=message,
                user_id=user_id,
            )

            async for token in token_stream:
                if not token:
                    continue
                full_response.append(token)
                yield _sse_event("token", {"token": token, "type": "token"})

            assembled = "".join(full_response)

            # Estimate token counts (rough approximation for billing)
            # Average English word ≈ 1.3 tokens; message/response word counts
            input_tokens = max(1, len(message.split()) * 2)
            output_tokens = max(1, len(assembled.split()))

            # Check for skill action block in the assembled response
            try:
                skill_result = await _execute_skill_from_response(
                    runtime=runtime,
                    response_text=assembled,
                    agent_id=user_id,
                    user_id=user_id,
                )
            except Exception as exc:
                logger.error(
                    "Skill dispatch error during streaming (session=%s): %s", session_id, exc
                )
                skill_result = None

            if skill_result is not None:
                skill_name, action_name, result_json = skill_result
                try:
                    result_data = json.loads(result_json)
                except (json.JSONDecodeError, ValueError):
                    result_data = result_json

                action_info = {
                    "skill": skill_name,
                    "action": action_name,
                    "result": result_data,
                }
                yield _sse_event("action", {
                    "type": "action",
                    "skill": skill_name,
                    "action": action_name,
                    "result": result_data,
                })

            # Resolve provider name from the registry for audit tagging
            _stream_provider_name = "unknown"
            try:
                _pnames = runtime._registry.list_providers()
                if _pnames:
                    _stream_provider_name = runtime._registry.get(_pnames[0]).provider_name
            except Exception as _pexc:
                logger.debug("Could not resolve stream provider name: %s", _pexc)

            # Persist interaction (best-effort — never blocks the stream)
            try:
                await _record_stream_usage(
                    request=request,
                    session_id=session_id,
                    user_id=user_id,
                    user_message=message,
                    full_response=assembled,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    provider_name=_stream_provider_name,
                )
            except Exception as exc:
                logger.warning(
                    "Stream usage record failed non-blocking (session=%s): %s", session_id, exc
                )

            yield _sse_event("done", {
                "type": "done",
                "full_response": assembled,
                "action": action_info,
                "session_id": session_id,
                "halted": False,
            })

        except Exception as exc:
            logger.error(
                "SSE stream error (session=%s handle=%s): %s",
                session_id, handle, exc,
            )
            # Try to yield what we have so the user sees partial content
            partial = "".join(full_response)
            if partial:
                yield _sse_event("error", {
                    "type": "error",
                    "message": "Response interrupted. Please try again.",
                    "partial": partial,
                })
            else:
                yield _sse_event("error", {
                    "type": "error",
                    "message": "Failed to generate a response. Please try again.",
                })

    return StreamingResponse(
        content=_sse_generator(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
