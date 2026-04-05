"""Inter-agent communications endpoints.

Provides the HTTP API for sending and receiving agent-to-agent messages
and managing multi-step transactions.

All endpoints require JWT Bearer authentication.  The encryption key for
each agent-pair is a server-generated random 32-byte secret stored in the
``comm_pair_secrets`` table.  On first contact between two agents the secret
is generated and persisted; subsequent calls retrieve it.  Handles are
public identifiers and are never used to derive encryption keys.

Authentication model
--------------------
The authenticated user is identified via their JWT.  The ``from_handle``
for outgoing messages is supplied by the caller in the request body
(the caller must own that agent — ownership check is advisory at this
stage as full handle→user linking requires a join the gateway can perform).

Endpoints
---------
- ``POST   /api/v1/comms/messages``                  — Send a message
- ``GET    /api/v1/comms/messages``                  — List received messages
- ``GET    /api/v1/comms/messages/{message_id}``     — Get + decrypt a message
- ``POST   /api/v1/comms/transactions``              — Start a transaction
- ``GET    /api/v1/comms/transactions/{txn_id}``     — Get transaction history
"""

from __future__ import annotations

import base64
import logging
import secrets
from datetime import datetime, timezone
from typing import Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from isg_agent.api.deps import CurrentUser, require_auth
from isg_agent.comms.agent_protocol import AgentProtocol
from isg_agent.comms.encryption import compute_hash
from isg_agent.comms.transaction import TransactionManager
from isg_agent.schemas.comms import (
    MessageDetail,
    MessageList,
    MessageResponse,
    MessageSend,
    TransactionCreate,
    TransactionResponse,
)

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/comms", tags=["communications"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_agent_protocol(request: Request) -> AgentProtocol:
    """Extract :class:`~isg_agent.comms.agent_protocol.AgentProtocol` from app state.

    Raises 503 if not yet initialised.
    """
    proto: Optional[AgentProtocol] = getattr(request.app.state, "agent_protocol", None)
    if proto is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent protocol not initialised. Server is starting up.",
        )
    return proto


def _get_transaction_manager(request: Request) -> TransactionManager:
    """Extract :class:`~isg_agent.comms.transaction.TransactionManager` from app state.

    Raises 503 if not yet initialised.
    """
    txn_mgr: Optional[TransactionManager] = getattr(
        request.app.state, "transaction_manager", None
    )
    if txn_mgr is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Transaction manager not initialised. Server is starting up.",
        )
    return txn_mgr


async def _get_or_create_pair_key(db_path: str, handle_a: str, handle_b: str) -> str:
    """Return (or create) a random shared secret for the given agent-handle pair.

    The secret is a cryptographically random 32-byte value stored in the
    ``comm_pair_secrets`` table.  The pair key is the two handles joined by
    ``"|"`` in sorted order so the lookup is symmetric: key(A→B) == key(B→A).

    On the first call for a pair a fresh secret is generated with
    :func:`secrets.token_bytes` and persisted.  Subsequent calls read the
    stored value.  The returned string is URL-safe base64 (44 chars) suitable
    for use as a Fernet key.

    Parameters
    ----------
    db_path:
        Filesystem path (or ``":memory:"`` URI) to the SQLite database.
    handle_a:
        First agent handle.
    handle_b:
        Second agent handle.

    Returns
    -------
    str
        A 44-character URL-safe base64 string — a stable, random Fernet key
        that is unique to this agent pair and never derivable from the handles.
    """
    # Canonical pair key: sorted so key(A,B) == key(B,A)
    pair_key = "|".join(sorted([handle_a, handle_b]))

    # Detect in-memory URI paths (used in tests)
    is_uri = db_path.startswith("file:")
    connect_kwargs: dict = {"uri": True} if is_uri else {}

    async with aiosqlite.connect(db_path, **connect_kwargs) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT secret_b64 FROM comm_pair_secrets WHERE pair_key = ?",
            (pair_key,),
        )
        row = await cursor.fetchone()
        if row is not None:
            return str(row["secret_b64"])

        # No secret yet — generate, persist, and return
        raw_32 = secrets.token_bytes(32)
        secret_b64 = base64.urlsafe_b64encode(raw_32).decode("utf-8")
        now_iso = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT OR IGNORE INTO comm_pair_secrets (pair_key, secret_b64, created_at) "
            "VALUES (?, ?, ?)",
            (pair_key, secret_b64, now_iso),
        )
        await db.commit()

        # Re-read to handle the race where two concurrent first-messages
        # both tried INSERT OR IGNORE — winner's value is the canonical one.
        cursor = await db.execute(
            "SELECT secret_b64 FROM comm_pair_secrets WHERE pair_key = ?",
            (pair_key,),
        )
        row = await cursor.fetchone()
        # row is guaranteed non-None here: we just inserted (or the winner did)
        return str(row["secret_b64"])  # type: ignore[index]


def _row_to_message_response(row: dict) -> MessageResponse:  # type: ignore[type-arg]
    """Convert a raw DB message dict to a :class:`MessageResponse` DTO."""
    return MessageResponse(
        id=row["id"],
        from_agent=row["from_agent"],
        to_agent=row["to_agent"],
        message_type=row["message_type"],
        status=row["status"],
        governance_hash=row.get("governance_hash"),
        created_at=row["created_at"],
    )


def _row_to_message_detail(
    row: dict,  # type: ignore[type-arg]
    payload: dict,  # type: ignore[type-arg]
) -> MessageDetail:
    """Convert a raw DB row + decrypted payload to a :class:`MessageDetail` DTO."""
    return MessageDetail(
        id=row["id"],
        from_agent=row["from_agent"],
        to_agent=row["to_agent"],
        message_type=row["message_type"],
        status=row["status"],
        governance_hash=row.get("governance_hash"),
        created_at=row["created_at"],
        payload=payload,
    )


# ---------------------------------------------------------------------------
# Message endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send a message from the authenticated user's agent to another agent",
)
async def send_message(
    body: MessageSend,
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> MessageResponse:
    """Send an encrypted message from one agent to another.

    The ``from_handle`` is derived from the authenticated user's context via
    the ``X-Agent-Handle`` header (optional) or falls back to a handle
    constructed from the user's ID for MVP purposes.

    The encryption key is derived deterministically from the sorted pair of
    handles so both parties can independently reconstruct it.
    """
    proto = _get_agent_protocol(request)

    # Resolve sender handle: honour explicit header, fall back to user_id slug
    from_handle: str = (
        request.headers.get("X-Agent-Handle", "").strip()
        or f"user-{user.user_id[:8]}"
    )

    encryption_key = await _get_or_create_pair_key(
        proto._db_path, from_handle, body.to_handle
    )

    try:
        message_id = await proto.send_message(
            from_handle=from_handle,
            to_handle=body.to_handle,
            message_type=body.message_type,
            payload=body.payload,
            encryption_key=encryption_key,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    record = await proto.get_message(message_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Message was stored but could not be retrieved.",
        )

    logger.info(
        "comms.send_message: id=%s from=%s to=%s type=%s",
        message_id,
        from_handle,
        body.to_handle,
        body.message_type,
    )
    return _row_to_message_response(record)


@router.get(
    "/messages",
    response_model=MessageList,
    summary="List received messages for the user's agent",
)
async def list_messages(
    request: Request,
    msg_status: str = Query(default="sent", alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(require_auth),
) -> MessageList:
    """Return messages received by the authenticated user's agent.

    Query parameters
    ----------------
    status:
        Filter by message status (default ``"sent"``).
    limit:
        Maximum number of messages to return (1–200, default 50).
    """
    proto = _get_agent_protocol(request)

    agent_handle: str = (
        request.headers.get("X-Agent-Handle", "").strip()
        or f"user-{user.user_id[:8]}"
    )

    try:
        rows = await proto.receive_messages(
            agent_handle=agent_handle,
            status=msg_status,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    messages = [_row_to_message_response(row) for row in rows]
    return MessageList(messages=messages, count=len(messages))


@router.get(
    "/messages/{message_id}",
    response_model=MessageDetail,
    summary="Get and decrypt a specific message",
)
async def get_message_detail(
    message_id: str,
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> MessageDetail:
    """Retrieve a single message and return its decrypted payload.

    The encryption key is re-derived from the sender and recipient handles
    stored on the message record.  The authenticated user must be either
    the sender or the recipient.
    """
    proto = _get_agent_protocol(request)

    record = await proto.get_message(message_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Message not found: {message_id}",
        )

    # Authorisation: user must be sender or recipient (handle prefix check for MVP)
    user_handle_prefix = f"user-{user.user_id[:8]}"
    explicit_handle = request.headers.get("X-Agent-Handle", "").strip()
    user_handles = {user_handle_prefix, explicit_handle} - {""}

    is_participant = (
        record["from_agent"] in user_handles
        or record["to_agent"] in user_handles
    )
    if not is_participant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a participant in this message.",
        )

    encryption_key = await _get_or_create_pair_key(
        proto._db_path, record["from_agent"], record["to_agent"]
    )

    try:
        payload = await proto.decrypt_payload(message_id, encryption_key)
    except (ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Could not decrypt message: {exc}",
        ) from exc

    # Mark as delivered when explicitly fetched
    await proto.update_status(message_id, "delivered")

    return _row_to_message_detail(record, payload)


# ---------------------------------------------------------------------------
# Transaction endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/transactions",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a new transaction",
)
async def create_transaction(
    body: TransactionCreate,
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> MessageResponse:
    """Initiate a transaction by sending the first ``"request"`` message.

    Returns the initial request message metadata.  The ``id`` field
    is the ``transaction_id`` to use in subsequent calls.
    """
    txn_mgr = _get_transaction_manager(request)

    from_handle: str = (
        request.headers.get("X-Agent-Handle", "").strip()
        or f"user-{user.user_id[:8]}"
    )

    encryption_key = await _get_or_create_pair_key(
        txn_mgr.protocol._db_path, from_handle, body.to_handle
    )

    try:
        transaction_id = await txn_mgr.create_transaction(
            from_handle=from_handle,
            to_handle=body.to_handle,
            transaction_type=body.transaction_type,
            request_payload=body.payload,
            encryption_key=encryption_key,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    record = await txn_mgr.protocol.get_message(transaction_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Transaction was created but initial message not found.",
        )

    logger.info(
        "comms.create_transaction: txn=%s from=%s to=%s type=%s",
        transaction_id,
        from_handle,
        body.to_handle,
        body.transaction_type,
    )
    return _row_to_message_response(record)


@router.get(
    "/transactions/{transaction_id}",
    response_model=TransactionResponse,
    summary="Get full transaction history",
)
async def get_transaction(
    transaction_id: str,
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> TransactionResponse:
    """Return all messages in a transaction with decrypted payloads.

    The authenticated user must be a participant (sender or recipient of
    the originating request message).
    """
    txn_mgr = _get_transaction_manager(request)
    proto = txn_mgr.protocol

    original = await proto.get_message(transaction_id)
    if original is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction not found: {transaction_id}",
        )

    # Authorisation: must be a participant
    user_handle_prefix = f"user-{user.user_id[:8]}"
    explicit_handle = request.headers.get("X-Agent-Handle", "").strip()
    user_handles = {user_handle_prefix, explicit_handle} - {""}

    is_participant = (
        original["from_agent"] in user_handles
        or original["to_agent"] in user_handles
    )
    if not is_participant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a participant in this transaction.",
        )

    encryption_key = await _get_or_create_pair_key(
        proto._db_path, original["from_agent"], original["to_agent"]
    )

    try:
        history = await txn_mgr.get_transaction_history(
            transaction_id=transaction_id,
            encryption_key=encryption_key,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    messages_out = [
        _row_to_message_detail(
            row={k: v for k, v in msg.items() if k != "payload"},
            payload=msg.get("payload", {}),
        )
        for msg in history
    ]

    logger.info(
        "comms.get_transaction: txn=%s steps=%d user=%s",
        transaction_id,
        len(messages_out),
        user.user_id,
    )

    return TransactionResponse(
        transaction_id=transaction_id,
        status=original["status"],
        messages=messages_out,
    )
