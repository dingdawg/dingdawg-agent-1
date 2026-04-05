"""Trust ledger endpoints: view trust scores (Innovation #4).

Provides read-only access to the per-entity trust scores maintained by
the TrustLedger.  All endpoints require authentication.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from isg_agent.api.deps import CurrentUser, require_auth
from isg_agent.core.trust_ledger import TrustLedger, TrustLevel

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/trust", tags=["trust"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class TrustScoreResponse(BaseModel):
    """A single entity's trust score."""

    entity_id: str
    entity_type: str
    score: float
    level: str
    confidence: float
    total_successes: int
    total_failures: int


class TrustListResponse(BaseModel):
    """List of all trust scores."""

    scores: list[TrustScoreResponse]
    count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_trust_ledger(request: Request) -> TrustLedger:
    """Extract the TrustLedger from app state."""
    ledger: Optional[TrustLedger] = getattr(request.app.state, "trust_ledger", None)
    if ledger is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Trust ledger not initialised",
        )
    return ledger


def _score_to_response(score) -> TrustScoreResponse:
    """Convert a TrustScore to a response model."""
    return TrustScoreResponse(
        entity_id=score.entity_id,
        entity_type=score.entity_type,
        score=round(score.score, 4),
        level=score.level.name,
        confidence=round(score.confidence, 4),
        total_successes=score.total_successes,
        total_failures=score.total_failures,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=TrustListResponse,
    summary="List all trust scores",
)
async def list_trust_scores(
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> TrustListResponse:
    """Return all registered trust scores.

    Returns an empty list if no entities have been scored yet.
    """
    ledger = _get_trust_ledger(request)

    all_scores = []
    for level in TrustLevel:
        scores = ledger.get_scores_by_level(level)
        all_scores.extend(scores)

    response_scores = [_score_to_response(s) for s in all_scores]

    return TrustListResponse(scores=response_scores, count=len(response_scores))


@router.get(
    "/{entity_id}",
    response_model=TrustScoreResponse,
    summary="Get trust score for a specific entity",
)
async def get_trust_score(
    entity_id: str,
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> TrustScoreResponse:
    """Return the trust score for a specific entity.

    Creates a new score entry at neutral (0.5) if the entity has not
    been scored before.
    """
    ledger = _get_trust_ledger(request)
    score = ledger.get_or_create(entity_id)
    return _score_to_response(score)
