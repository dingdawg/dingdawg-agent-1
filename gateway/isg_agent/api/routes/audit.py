"""Audit trail endpoints: list entries and verify chain integrity.

Provides read-only access to the SHA-256 hash-chained audit trail
and chain verification endpoint.  All endpoints require authentication.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from isg_agent.api.deps import CurrentUser, require_auth
from isg_agent.core.audit import AuditChain

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class AuditEntryResponse(BaseModel):
    """A single audit entry in the response."""

    id: int
    timestamp: str
    event_type: str
    actor: str
    details: dict
    entry_hash: str
    prev_hash: str


class AuditListResponse(BaseModel):
    """Paginated list of audit entries."""

    entries: list[AuditEntryResponse]
    total: int


class ChainVerifyResponse(BaseModel):
    """Result of chain integrity verification."""

    valid: bool
    length: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_audit_chain(request: Request) -> AuditChain:
    """Extract the AuditChain from app state."""
    chain: Optional[AuditChain] = getattr(request.app.state, "audit_chain", None)
    if chain is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audit chain not initialised",
        )
    return chain


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=AuditListResponse,
    summary="List audit trail entries",
)
async def list_audit_entries(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    event_type: Optional[str] = None,
    user: CurrentUser = Depends(require_auth),
) -> AuditListResponse:
    """Return paginated audit entries with optional event_type filter.

    Parameters
    ----------
    limit:
        Maximum entries to return (default 100, max 1000).
    offset:
        Number of entries to skip.
    event_type:
        Optional filter by event type (e.g. ``"governance_decision"``).
    """
    chain = _get_audit_chain(request)

    # Clamp limit to prevent abuse
    limit = min(max(1, limit), 1000)
    offset = max(0, offset)

    entries = await chain.get_entries(
        limit=limit,
        offset=offset,
        event_type_filter=event_type,
    )
    total = await chain.get_chain_length()

    response_entries = []
    for entry in entries:
        try:
            details = json.loads(entry.details)
        except (json.JSONDecodeError, TypeError):
            details = {"raw": entry.details}

        response_entries.append(
            AuditEntryResponse(
                id=entry.id,
                timestamp=entry.timestamp,
                event_type=entry.event_type,
                actor=entry.actor,
                details=details,
                entry_hash=entry.entry_hash,
                prev_hash=entry.prev_hash,
            )
        )

    return AuditListResponse(entries=response_entries, total=total)


@router.get(
    "/verify",
    response_model=ChainVerifyResponse,
    summary="Verify audit chain integrity",
)
async def verify_chain(
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> ChainVerifyResponse:
    """Verify the integrity of the entire audit hash chain.

    Recomputes every entry hash and checks that each ``prev_hash``
    matches the preceding entry's ``entry_hash``.

    Returns ``valid: true`` if the chain is intact, ``false`` if
    any entry has been tampered with.
    """
    chain = _get_audit_chain(request)
    valid = await chain.verify_chain()
    length = await chain.get_chain_length()

    return ChainVerifyResponse(valid=valid, length=length)
