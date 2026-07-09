"""Agent self-onboarding — the approval-layer inversion (Wave 2).

An anonymous agent requests access; a human approves via an emailed link;
the key is created only at delivery time and handed to the agent exactly
once. Security properties, in order of importance:

* No key exists before human approval; nothing to leak or revoke early.
* No raw key or token is ever stored — SHA-256 hashes only.
* The approval token travels only in the owner's email; the poll token
  only in the agent's 201 response. Neither can substitute for the other.

Error surface (declared): 422 malformed handle/email (boundary), 409 handle
already requested, 404 unknown request id, 403 wrong poll/approval token.
Email-send failure is logged and does not fail the request (developers.py
precedent) — the human can be re-mailed; the state row is the truth.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timezone

import aiosqlite
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field

from isg_agent.middleware.rate_limiter_middleware import public_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS agent_onboard_requests (
    id                  TEXT PRIMARY KEY,
    handle              TEXT NOT NULL UNIQUE,
    contact_email       TEXT NOT NULL,
    purpose             TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending',
    poll_token_hash     TEXT NOT NULL,
    approval_token_hash TEXT NOT NULL,
    user_id             TEXT,
    created_at          TEXT NOT NULL,
    approved_at         TEXT
);
"""


class SelfOnboardRequest(BaseModel):
    handle: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,31}$")
    contact_email: EmailStr
    purpose: str = Field(min_length=8, max_length=500)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _db_path(request: Request) -> str:
    settings = getattr(request.app.state, "settings", None)
    return settings.db_path if settings else "isg_agent.db"


def _base_url(request: Request) -> str:
    settings = getattr(request.app.state, "settings", None)
    public = getattr(settings, "public_url", "") or ""
    return public.rstrip("/") or str(request.base_url).rstrip("/")


async def _send_approval_email(*, to_email: str, subject: str, html_body: str, db_path: str) -> None:
    """Seam for tests; production delegates to the comms email service."""
    from isg_agent.comms.email_service import send_email

    await send_email(
        template_id="agent_onboard_approval",
        to_email=to_email,
        subject=subject,
        html_body=html_body,
        db_path=db_path,
    )


@router.post("/self-onboard", status_code=status.HTTP_201_CREATED,
             summary="Agent requests platform access (human approves by email)")
@public_rate_limit()
async def self_onboard(payload: SelfOnboardRequest, request: Request) -> JSONResponse:
    """Create a pending onboarding request and email the human approver."""
    db_path = _db_path(request)
    request_id = str(uuid.uuid4())
    poll_token = secrets.token_urlsafe(32)
    approval_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc).isoformat()

    async with aiosqlite.connect(db_path) as db:
        await db.execute(_TABLE_DDL)
        async with db.execute(
            "SELECT id FROM agent_onboard_requests WHERE handle = ?", (payload.handle,)
        ) as cur:
            if await cur.fetchone():
                raise HTTPException(status.HTTP_409_CONFLICT, "Handle already requested.")
        await db.execute(
            """INSERT INTO agent_onboard_requests
               (id, handle, contact_email, purpose, status,
                poll_token_hash, approval_token_hash, created_at)
               VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)""",
            (request_id, payload.handle, str(payload.contact_email), payload.purpose,
             _hash(poll_token), _hash(approval_token), now),
        )
        await db.commit()

    approve_url = (
        f"{_base_url(request)}/api/v1/agents/self-onboard/{request_id}/approve"
        f"?token={approval_token}"
    )
    try:
        await _send_approval_email(
            to_email=str(payload.contact_email),
            subject=f"Approve agent @{payload.handle} on DingDawg",
            html_body=(
                f"<p>An AI agent requested access as <b>@{payload.handle}</b>.</p>"
                f"<p>Purpose: {payload.purpose}</p>"
                f'<p><a href="{approve_url}">Approve this agent</a> — '
                f"only approve if you initiated this.</p>"
            ),
            db_path=db_path,
        )
    except Exception as exc:  # email failure must not orphan the request
        logger.warning("approval email failed for %s: %s", payload.handle, exc)

    return JSONResponse(
        {"request_id": request_id, "status": "pending", "poll_token": poll_token},
        status_code=status.HTTP_201_CREATED,
    )


#: Approval window — stale authority dies. A pending request older than
#: this answers 410 on both approve and poll (oracle finding S1182: an
#: approval link must not stay live in an inbox forever).
REQUEST_TTL_HOURS = 72


async def _load_request(db: aiosqlite.Connection, request_id: str) -> aiosqlite.Row:
    await db.execute(_TABLE_DDL)
    db.row_factory = aiosqlite.Row
    async with db.execute(
        "SELECT * FROM agent_onboard_requests WHERE id = ?", (request_id,)
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown onboarding request.")
    if row["status"] == "pending":
        try:
            created = datetime.fromisoformat(row["created_at"])
            age_h = (datetime.now(timezone.utc) - created).total_seconds() / 3600
        except ValueError:
            age_h = float("inf")  # unparseable age = stale (fail closed)
        if age_h > REQUEST_TTL_HOURS:
            raise HTTPException(
                status.HTTP_410_GONE,
                f"Onboarding request expired after {REQUEST_TTL_HOURS}h — submit a new one.",
            )
    return row


@router.get("/self-onboard/{request_id}/approve",
            summary="Human approves the agent (link from email)")
@public_rate_limit()
async def approve(request_id: str, token: str, request: Request) -> JSONResponse:
    """Flip the request to approved. Idempotent; key is created at delivery."""
    async with aiosqlite.connect(_db_path(request)) as db:
        row = await _load_request(db, request_id)
        if _hash(token) != row["approval_token_hash"]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid approval token.")
        if row["status"] == "pending":
            await db.execute(
                "UPDATE agent_onboard_requests SET status='approved', approved_at=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), request_id),
            )
            await db.commit()
    return JSONResponse({"request_id": request_id, "status": "approved",
                         "message": "Agent approved. It can now collect its key."})


@router.get("/self-onboard/{request_id}",
            summary="Agent polls its onboarding status (key delivered once)")
@public_rate_limit()
async def poll(request_id: str, poll_token: str, request: Request) -> JSONResponse:
    """Report status; on first poll after approval, mint + deliver the key."""
    db_path = _db_path(request)
    async with aiosqlite.connect(db_path) as db:
        row = await _load_request(db, request_id)
        if _hash(poll_token) != row["poll_token_hash"]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid poll token.")
        if row["status"] != "approved":
            return JSONResponse({"request_id": request_id, "status": row["status"]})

        # First (and only) delivery: create user + key now, never store raw.
        from isg_agent.mcp.auth import create_api_key, ensure_mcp_keys_table

        user_id = str(uuid.uuid4())
        raw_key = f"dd_{uuid.uuid4().hex}"
        await ensure_mcp_keys_table(db_path=db_path)
        await create_api_key(
            raw_key,
            user_id=user_id,
            name=f"@{row['handle']} — self-onboarded agent key",
            db_path=db_path,
            agent_id=row["handle"],
        )
        await db.execute(
            "UPDATE agent_onboard_requests SET status='delivered', user_id=? WHERE id=?",
            (user_id, request_id),
        )
        await db.commit()

    return JSONResponse(
        {"request_id": request_id, "status": "approved", "api_key": raw_key,
         "message": "Store this key securely — it will not be shown again."}
    )
