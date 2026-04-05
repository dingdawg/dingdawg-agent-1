"""Decision trace endpoints: list traces and view explanations (Innovation #5).

Provides read-only access to the ExplainEngine's decision traces.
Each trace records WHAT was decided, WHY, and WHICH component made the
decision.  All endpoints require authentication.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from isg_agent.api.deps import CurrentUser, require_auth
from isg_agent.core.explain import ExplainEngine

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/explain", tags=["explain"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class TraceListResponse(BaseModel):
    """List of trace IDs."""

    trace_ids: list[str]
    count: int


class ExplainStepResponse(BaseModel):
    """A single step in a decision trace."""

    step_number: int
    decision: str
    reason: str
    component: str
    evidence: dict[str, Any]


class ExplainTraceResponse(BaseModel):
    """Full decision trace with human-readable explanation."""

    trace_id: str
    is_finalized: bool
    outcome: str
    steps: list[ExplainStepResponse]
    human_readable: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_explain_engine(request: Request) -> ExplainEngine:
    """Extract the ExplainEngine from app state."""
    engine: Optional[ExplainEngine] = getattr(request.app.state, "explain_engine", None)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Explain engine not initialised",
        )
    return engine


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=TraceListResponse,
    summary="List recent trace IDs",
)
async def list_traces(
    request: Request,
    limit: int = 50,
    user: CurrentUser = Depends(require_auth),
) -> TraceListResponse:
    """Return recent trace IDs (newest last).

    Parameters
    ----------
    limit:
        Maximum number of trace IDs to return (default 50, max 200).
    """
    engine = _get_explain_engine(request)
    limit = min(max(1, limit), 200)
    trace_ids = engine.list_traces(limit=limit)

    return TraceListResponse(trace_ids=trace_ids, count=len(trace_ids))


@router.get(
    "/{trace_id}",
    response_model=ExplainTraceResponse,
    summary="Get human-readable explanation for a trace",
)
async def get_explanation(
    trace_id: str,
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> ExplainTraceResponse:
    """Return a full decision trace with human-readable explanation.

    Returns 404 if the trace does not exist.
    """
    engine = _get_explain_engine(request)
    trace = engine.get_trace(trace_id)

    if trace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trace not found: {trace_id}",
        )

    steps = [
        ExplainStepResponse(
            step_number=s.step_number,
            decision=s.decision,
            reason=s.reason,
            component=s.component,
            evidence=s.evidence,
        )
        for s in trace.steps
    ]

    return ExplainTraceResponse(
        trace_id=trace.trace_id,
        is_finalized=trace.is_finalized,
        outcome=trace.outcome,
        steps=steps,
        human_readable=trace.to_human_readable(),
    )
