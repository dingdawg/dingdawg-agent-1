"""CLI invocation endpoints for the @dingdawg/cli package.

Provides the HTTP API that backs the ``dd`` terminal command:

    POST /api/v1/cli/invoke          — invoke an agent, returns SSE stream
    GET  /api/v1/cli/agents          — list user's agents (dd agents list)
    GET  /api/v1/cli/agents/{handle}/skills — list agent skills
    POST /api/v1/cli/device-code     — start OAuth device flow (public)
    POST /api/v1/cli/device-token    — poll for completed device flow (public)

Auth
----
All endpoints except device-code and device-token require a valid JWT Bearer
token **or** an ``X-DD-API-Key`` API key header.

The CLI hits the backend directly (full base_url), not via Next.js proxy, so
JWT or API key authentication is used — no cookie sessions.

SSE Format (cli/invoke)
-----------------------
Each chunk is emitted as::

    data: <text chunk>\\n\\n

Completion is signalled with::

    data: [DONE]\\n\\n

Metadata (source tagging) is prepended as::

    event: metadata\\n
    data: {"source": "cli", "agent_id": "...", "handle": "..."}\\n\\n
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
import uuid
from typing import AsyncIterator, Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from isg_agent.api.deps import CurrentUser, require_auth

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/cli", tags=["cli"])

# ---------------------------------------------------------------------------
# Device code store (SQLite-backed, initialised lazily)
# ---------------------------------------------------------------------------

_DB_PATH: str = "data/agent.db"
_SECRET_KEY: str = ""
_FRONTEND_URL: str = "https://app.dingdawg.com"

_DEVICE_CODE_TTL: int = 300  # 5 minutes


def _set_cli_config(
    db_path: str,
    secret_key: str,
    frontend_url: str = "https://app.dingdawg.com",
) -> None:
    """Set module-level CLI configuration (called from app startup)."""
    global _DB_PATH, _SECRET_KEY, _FRONTEND_URL  # noqa: PLW0603
    _DB_PATH = db_path
    _SECRET_KEY = secret_key
    _FRONTEND_URL = frontend_url


async def _ensure_device_codes_table(db_path: str) -> None:
    """Create the device_codes table if it does not exist."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS device_codes (
                device_code   TEXT PRIMARY KEY,
                user_code     TEXT NOT NULL,
                user_id       TEXT,
                status        TEXT NOT NULL DEFAULT 'pending',
                created_at    INTEGER NOT NULL,
                expires_at    INTEGER NOT NULL
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_device_codes_user "
            "ON device_codes(user_code)"
        )
        await db.commit()


# ---------------------------------------------------------------------------
# API key helper
# ---------------------------------------------------------------------------


async def _resolve_api_key_user(api_key: str, db_path: str) -> Optional[str]:
    """Resolve an X-DD-API-Key to a user_id.

    Looks up the api_keys table.  Returns None if the key is invalid.
    """
    try:
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT user_id FROM api_keys WHERE key_hash = ? AND revoked = 0",
                (api_key,),
            )
            row = await cursor.fetchone()
        if row:
            return row["user_id"]
    except Exception as exc:
        logger.debug("api_key lookup failed (table may not exist): %s", exc)
    return None


async def _get_cli_user(request: Request) -> CurrentUser:
    """Extract authenticated user from Bearer token OR X-DD-API-Key header.

    Raises HTTP 401 if neither is present or both are invalid.
    """
    # 1. Try Bearer token first (standard JWT)
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        db_path = _DB_PATH
        secret_key = _SECRET_KEY
        if not secret_key:
            from isg_agent.config import get_settings
            secret_key = get_settings().secret_key
        if not secret_key:
            raise RuntimeError("JWT secret key not configured — call configure() first")
        from isg_agent.api.routes.auth import verify_token
        payload = verify_token(token, secret_key)
        if payload is not None:
            user_id = str(payload.get("sub", ""))
            email = str(payload.get("email", ""))
            if user_id:
                return CurrentUser(user_id=user_id, email=email)

    # 2. Try X-DD-API-Key header
    api_key = request.headers.get("x-dd-api-key", "")
    if api_key:
        db_path = _DB_PATH
        user_id = await _resolve_api_key_user(api_key, db_path)
        if user_id:
            return CurrentUser(user_id=user_id, email="")

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Provide a Bearer token or X-DD-API-Key.",
        headers={"WWW-Authenticate": "Bearer"},
    )


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class CLIInvokeRequest(BaseModel):
    """Body for POST /api/v1/cli/invoke."""

    handle: str = Field(..., description="Agent handle, e.g. @mybusiness or mybusiness")
    message: str = Field(..., min_length=1, description="User message to send to the agent")
    skill: Optional[str] = Field(default=None, description="Explicit skill to invoke")
    action: Optional[str] = Field(default=None, description="Action within the skill")
    parameters: dict = Field(default_factory=dict, description="Skill parameters")
    source: Optional[str] = Field(default="cli", description="Source tag for analytics")


class DeviceCodeRequest(BaseModel):
    """Optional body for POST /api/v1/cli/device-code."""

    client_id: Optional[str] = Field(default=None, description="Optional CLI client identifier")


class DeviceTokenRequest(BaseModel):
    """Body for POST /api/v1/cli/device-token."""

    device_code: str = Field(..., description="The device_code returned by /cli/device-code")


# ---------------------------------------------------------------------------
# SSE streaming generator
# ---------------------------------------------------------------------------


async def _sse_agent_stream(
    handle: str,
    message: str,
    user_id: str,
    request: Request,
    skill: Optional[str] = None,
    action: Optional[str] = None,
    parameters: Optional[dict] = None,
    source: str = "cli",
) -> AsyncIterator[str]:
    """Yield SSE-formatted chunks from the agent runtime.

    Emits a metadata event first, then token chunks, then [DONE].
    Falls back to a single non-streaming response if the runtime does
    not support streaming.
    """
    # Resolve handle → agent record
    clean_handle = handle.lstrip("@")
    agent_registry = getattr(request.app.state, "agent_registry", None)
    if agent_registry is None:
        yield "event: error\ndata: {\"error\": \"Agent registry not initialised\"}\n\n"
        return

    agent = await agent_registry.get_agent_by_handle(clean_handle)
    if agent is None:
        yield (
            'event: error\n'
            f'data: {{"error": "Agent @{clean_handle} not found"}}\n\n'
        )
        return

    # Metadata event — tag with source='cli'
    metadata = {
        "source": source,
        "agent_id": agent.id,
        "handle": agent.handle,
        "skill": skill,
    }
    yield f"event: metadata\ndata: {json.dumps(metadata)}\n\n"

    session_manager = getattr(request.app.state, "session_manager", None)
    runtime = getattr(request.app.state, "runtime", None)

    if runtime is None:
        yield "event: error\ndata: {\"error\": \"Agent runtime not initialised\"}\n\n"
        return

    # Create or resume a CLI session (user_id prefixed with 'cli:' for analytics)
    cli_user_id = f"cli:{user_id}"

    if session_manager is not None:
        try:
            session = await session_manager.create_session(
                user_id=cli_user_id,
                agent_id=agent.id,
            )
            session_id = session.session_id
        except Exception as exc:
            logger.warning("CLI session creation failed: %s — using ephemeral id", exc)
            session_id = f"cli-ephemeral-{uuid.uuid4().hex[:8]}"
    else:
        session_id = f"cli-ephemeral-{uuid.uuid4().hex[:8]}"

    # If a skill is explicitly requested, try executing it first
    skill_text: Optional[str] = None
    if skill:
        skill_executor = getattr(request.app.state, "skill_executor", None)
        if skill_executor is not None:
            try:
                effective_params = dict(parameters or {})
                if action:
                    effective_params["action"] = action
                effective_params["agent_id"] = agent.id
                effective_params["user_id"] = user_id
                effective_params["source"] = source

                exec_result = await skill_executor.execute(
                    skill_name=skill,
                    parameters=effective_params,
                )
                if exec_result.success:
                    skill_text = exec_result.output
                else:
                    skill_text = f"Skill error: {exec_result.error}"
            except Exception as exc:
                logger.warning("CLI skill execution failed: %s", exc)
                skill_text = f"Skill {skill!r} could not be executed: {exc}"

    # Build full message for runtime (include skill output if any)
    full_message = message
    if skill_text is not None:
        full_message = f"{message}\n\n[Skill result: {skill_text}]"

    # Process via AgentRuntime (non-streaming path, then yield as single chunk)
    try:
        from isg_agent.brain.session import SessionNotFoundError

        agent_response = await runtime.process_message(
            session_id=session_id,
            user_message=full_message,
            user_id=cli_user_id,
        )
        # Stream the response content as SSE chunks
        content = agent_response.content or ""
        # Yield in ~80-char chunks to simulate streaming
        chunk_size = 80
        for i in range(0, max(len(content), 1), chunk_size):
            chunk = content[i : i + chunk_size]
            if chunk:
                yield f"data: {chunk}\n\n"

    except Exception as exc:
        logger.error("CLI invoke runtime error: %s", exc)
        yield f"event: error\ndata: {{\"error\": \"{str(exc)[:200]}\"}}\n\n"

    # Stream terminator
    yield "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/invoke",
    summary="Invoke an agent from the CLI (SSE stream)",
    status_code=200,
    response_class=StreamingResponse,
)
async def cli_invoke(
    body: CLIInvokeRequest,
    request: Request,
    user: CurrentUser = Depends(_get_cli_user),
) -> StreamingResponse:
    """Invoke an agent from the DingDawg CLI.

    Resolves ``@handle`` to an agent, creates/resumes a CLI session,
    processes the message through the governed AgentRuntime, and streams
    the response as Server-Sent Events.

    All invocations are tagged with ``source: "cli"`` for analytics.

    Auth
    ----
    Requires Bearer JWT **or** ``X-DD-API-Key`` header.

    Request body
    ------------
    ``{handle, message, skill?, action?, parameters?, source?}``

    Response
    --------
    ``text/event-stream``::

        event: metadata
        data: {"source": "cli", "agent_id": "...", "handle": "..."}

        data: Hello! How can I help you...

        data: [DONE]

    Raises
    ------
    404 if the agent @handle is not found.
    422 if message is empty.
    """
    # Validate message is non-empty (min_length=1 on the model handles this
    # but we add an explicit guard for empty strings after stripping)
    if not body.message.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="message must not be empty",
        )

    # Resolve handle BEFORE starting stream so we can return 404 immediately
    clean_handle = body.handle.lstrip("@")
    agent_registry = getattr(request.app.state, "agent_registry", None)
    if agent_registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent registry not initialised",
        )

    agent = await agent_registry.get_agent_by_handle(clean_handle)
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent @{clean_handle} not found",
        )

    return StreamingResponse(
        _sse_agent_stream(
            handle=body.handle,
            message=body.message,
            user_id=user.user_id,
            request=request,
            skill=body.skill,
            action=body.action,
            parameters=body.parameters,
            source=body.source or "cli",
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/agents",
    summary="List agents for the authenticated CLI user",
)
async def cli_list_agents(
    request: Request,
    user: CurrentUser = Depends(_get_cli_user),
) -> dict:
    """Return the authenticated user's agents, formatted for CLI display.

    Equivalent to ``dd agents list``.

    Response shape::

        {
            "agents": [
                {"id": "...", "handle": "mybiz", "name": "My Biz", ...}
            ],
            "count": 1
        }
    """
    agent_registry = getattr(request.app.state, "agent_registry", None)
    if agent_registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent registry not initialised",
        )

    agents = await agent_registry.list_agents(user_id=user.user_id)
    items = []
    for a in agents:
        items.append({
            "id": a.id,
            "handle": a.handle,
            "name": a.name,
            "agent_type": a.agent_type.value,
            "industry_type": a.industry_type or "",
            "status": a.status.value,
            "subscription_tier": a.subscription_tier.value,
            "created_at": a.created_at,
            "updated_at": a.updated_at,
        })

    return {"agents": items, "count": len(items)}


@router.get(
    "/agents/{handle}/skills",
    summary="List skills available for an agent",
)
async def cli_agent_skills(
    handle: str,
    request: Request,
    user: CurrentUser = Depends(_get_cli_user),
) -> dict:
    """Return the list of skills registered on the platform.

    The response is agent-context-aware: if the agent has a sector or
    industry set, the skills are ordered by relevance.

    Equivalent to ``dd agents skills @handle``.

    Returns 404 if the handle does not exist.
    """
    # Strip @ prefix
    clean_handle = handle.lstrip("@")

    agent_registry = getattr(request.app.state, "agent_registry", None)
    if agent_registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent registry not initialised",
        )

    agent = await agent_registry.get_agent_by_handle(clean_handle)
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent @{clean_handle} not found",
        )

    # Fetch registered skill names from the executor
    skill_executor = getattr(request.app.state, "skill_executor", None)
    skill_names: list[str] = []
    if skill_executor is not None:
        try:
            skill_names = await skill_executor.list_skills()
        except Exception as exc:
            logger.warning("CLI skills list failed: %s", exc)

    # Build skill list with basic metadata
    skills = []
    skill_reputation = getattr(request.app.state, "skill_reputation", None)
    for name in skill_names:
        rep_score = 0.5
        if skill_reputation is not None:
            try:
                rep = await skill_reputation.get_reputation(name)
                rep_score = rep.score
            except Exception:
                pass
        skills.append({
            "name": name,
            "reputation_score": rep_score,
        })

    return {
        "agent_handle": agent.handle,
        "agent_name": agent.name,
        "skills": skills,
        "count": len(skills),
    }


@router.post(
    "/device-code",
    summary="Start OAuth device flow — generate device code (public)",
)
async def cli_device_code(
    body: DeviceCodeRequest,
    request: Request,
) -> dict:
    """Generate a device code for the CLI OAuth device flow.

    This is a **public** endpoint — no auth required.

    The CLI displays the ``verification_url`` and ``user_code`` to the user,
    who opens the URL in a browser to complete authentication.

    The CLI then polls ``POST /api/v1/cli/device-token`` every 5 seconds
    until the user completes the browser flow.

    Response::

        {
            "device_code": "...",
            "user_code": "XXXX-XXXX",
            "verification_url": "https://app.dingdawg.com/device?code=XXXX-XXXX",
            "expires_in": 300,
            "interval": 5
        }
    """
    db_path = _DB_PATH

    await _ensure_device_codes_table(db_path)

    device_code = secrets.token_urlsafe(32)
    # Human-readable 8-char code with hyphen (XXXX-XXXX)
    raw = secrets.token_hex(4).upper()
    user_code = f"{raw[:4]}-{raw[4:]}"

    now = int(time.time())
    expires_at = now + _DEVICE_CODE_TTL

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO device_codes
                (device_code, user_code, user_id, status, created_at, expires_at)
            VALUES (?, ?, NULL, 'pending', ?, ?)
            """,
            (device_code, user_code, now, expires_at),
        )
        await db.commit()

    frontend_url = _FRONTEND_URL
    verification_url = f"{frontend_url}/device?code={user_code}"

    logger.info("CLI device code created: user_code=%s expires=%s", user_code, expires_at)

    return {
        "device_code": device_code,
        "user_code": user_code,
        "verification_url": verification_url,
        "expires_in": _DEVICE_CODE_TTL,
        "interval": 5,
    }


@router.post(
    "/device-token",
    summary="Poll for OAuth device flow completion (public)",
)
async def cli_device_token(
    body: DeviceTokenRequest,
    request: Request,
) -> dict:
    """Exchange a device code for a JWT token after browser confirmation.

    This is a **public** endpoint — no auth required.

    The CLI polls this endpoint every 5 seconds after calling
    ``/cli/device-code``.

    Status codes
    ------------
    * **200** — Browser auth completed; returns ``access_token``.
    * **202** — Browser auth still pending (``authorization_pending``).
    * **400** — Device code expired or already used.
    * **401** — Device code not recognised.
    """
    db_path = _DB_PATH

    await _ensure_device_codes_table(db_path)

    now = int(time.time())

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM device_codes WHERE device_code = ?",
            (body.device_code,),
        )
        row = await cursor.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid device_code",
        )

    if row["expires_at"] < now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device code expired. Please run 'dd login' again.",
        )

    if row["status"] == "used":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device code already used.",
        )

    if row["status"] == "pending":
        # Browser has not yet confirmed — tell CLI to keep polling
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=202,
            content={
                "status": "authorization_pending",
                "message": "Waiting for browser confirmation. Keep polling.",
                "interval": 5,
            },
        )

    # status == 'authorized': issue JWT
    user_id = row["user_id"]
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device code has no associated user. Please re-authenticate.",
        )

    secret_key = _SECRET_KEY
    if not secret_key:
        from isg_agent.config import get_settings
        secret_key = get_settings().secret_key
    if not secret_key:
        raise RuntimeError("JWT secret key not configured — call configure() first")

    # Fetch user email for the token
    email = ""
    try:
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT email FROM users WHERE id = ?",
                (user_id,),
            )
            user_row = await cursor.fetchone()
            if user_row:
                email = user_row["email"]
    except Exception as exc:
        logger.warning("Could not fetch user email for device token: %s", exc)

    from isg_agent.api.routes.auth import _create_token
    access_token = _create_token(
        user_id=user_id,
        email=email,
        secret_key=secret_key,
        expires_in=86400 * 30,  # 30-day CLI token
    )

    # Mark device code as used
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE device_codes SET status = 'used' WHERE device_code = ?",
            (body.device_code,),
        )
        await db.commit()

    logger.info("CLI device token issued for user_id=%s", user_id)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": 86400 * 30,
        "user_id": user_id,
        "email": email,
    }
