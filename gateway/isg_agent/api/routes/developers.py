"""Developer API key issuance.

POST /v1/developers/signup — registers a developer and issues a dd_<uuid> API key.
The key is shown exactly once in the response and cannot be retrieved later.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import aiosqlite
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, EmailStr

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/developers", tags=["developers"])


class DeveloperSignupRequest(BaseModel):
    email: EmailStr
    name: str
    role: str = "consumer"
    company: str | None = None


class DeveloperSignupResponse(BaseModel):
    api_key: str
    user_id: str
    message: str


@router.post(
    "/signup",
    response_model=DeveloperSignupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a developer and issue an API key",
)
async def developer_signup(
    payload: DeveloperSignupRequest,
    request: Request,
) -> DeveloperSignupResponse:
    """Register a developer account and issue a ``dd_<uuid>`` API key.

    Creates a user record and customer profile atomically, then stores
    the API key via the MCP key system. The raw key is returned once
    and never stored in plaintext.
    """
    settings = getattr(request.app.state, "settings", None)
    db_path: str = settings.db_path if settings else "isg_agent.db"
    now = datetime.now(timezone.utc).isoformat()

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        # Reject duplicate email
        async with db.execute(
            "SELECT id FROM customers WHERE email = ?", (str(payload.email),)
        ) as cur:
            if await cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Email already registered.",
                )

        # Create user (no password — API key auth only)
        user_id = str(uuid.uuid4())
        await db.execute(
            """INSERT INTO users
               (id, email, password_hash, salt, created_at, email_verified, full_name)
               VALUES (?, ?, '', '', ?, 1, ?)""",
            (user_id, str(payload.email), now, payload.name),
        )

        # Create customer profile
        customer_id = str(uuid.uuid4())
        await db.execute(
            """INSERT INTO customers
               (id, user_id, email, full_name, company, role,
                signup_source, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'api', ?, ?)""",
            (customer_id, user_id, str(payload.email), payload.name,
             payload.company, payload.role, now, now),
        )

        await db.commit()

    # Generate and store API key
    raw_key = f"dd_{uuid.uuid4().hex}"
    try:
        from isg_agent.mcp.auth import create_api_key, ensure_mcp_keys_table
        await ensure_mcp_keys_table(db_path=db_path)
        await create_api_key(
            raw_key,
            user_id=user_id,
            name=f"{payload.name} — developer key",
            db_path=db_path,
        )
    except Exception as exc:
        logger.error("API key storage failed for user %s: %s", user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Account created but key storage failed. Contact support.",
        )

    # Send welcome email — non-blocking, failure does not fail signup
    try:
        from isg_agent.comms.email_service import render_welcome, send_email
        subject, html = render_welcome(payload.name)
        await send_email(
            template_id="welcome",
            to_email=str(payload.email),
            subject=subject,
            html_body=html,
            db_path=db_path,
            customer_id=customer_id,
            user_id=user_id,
        )
    except Exception as exc:
        logger.warning("Welcome email failed for %s: %s", payload.email, exc)

    return DeveloperSignupResponse(
        api_key=raw_key,
        user_id=user_id,
        message="API key issued. Store it securely — it will not be shown again.",
    )
