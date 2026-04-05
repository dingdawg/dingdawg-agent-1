"""Financial Analytics API routes.

Provides the HTTP API for owner-level financial visibility:

All routes require JWT authentication.
Admin routes additionally require the user ID to be in FINANCE_ADMIN_USERS
(or MARKETPLACE_ADMIN_USERS as fallback) env var.

Routes:
  GET  /api/v1/finance/summary?period=today|week|month|year|all&sector=&tier=
  GET  /api/v1/finance/margins
  GET  /api/v1/finance/trend?days=30
  GET  /api/v1/finance/transactions?limit=100&offset=0&tx_type=&direction=&start_date=&end_date=
  PUT  /api/v1/finance/cost-rates/{cost_type}
  GET  /api/v1/finance/cost-rates
  GET  /api/v1/finance/health

All endpoints are admin-gated: only users listed in FINANCE_ADMIN_USERS
(comma-separated user IDs) may access them.  If FINANCE_ADMIN_USERS is
empty, falls back to MARKETPLACE_ADMIN_USERS.  If both are empty, any
authenticated user may access the endpoints — suitable for single-operator
deployments.  Set FINANCE_ADMIN_USERS in production.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from isg_agent.api.deps import CurrentUser, require_auth
from isg_agent.finance.ledger import FinancialLedger

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/finance", tags=["finance"])

# ---------------------------------------------------------------------------
# Admin user list
# ---------------------------------------------------------------------------

def _load_admin_users() -> set[str]:
    """Load admin user IDs from environment variables.

    Reads FINANCE_ADMIN_USERS first, falls back to MARKETPLACE_ADMIN_USERS.
    Returns an empty set if neither is set (all authenticated users are allowed).
    """
    finance_admins = os.environ.get("FINANCE_ADMIN_USERS", "").strip()
    if finance_admins:
        return {uid.strip() for uid in finance_admins.split(",") if uid.strip()}

    # Fallback: reuse marketplace admin list
    marketplace_admins = os.environ.get("MARKETPLACE_ADMIN_USERS", "").strip()
    if marketplace_admins:
        return {uid.strip() for uid in marketplace_admins.split(",") if uid.strip()}

    return set()


_ADMIN_USERS: set[str] = _load_admin_users()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class UpdateCostRateRequest(BaseModel):
    """Request body for updating a cost rate."""

    rate_cents: int = Field(ge=0, description="Cost per unit in integer cents")
    unit: str = Field(description="Unit description (e.g. 'per_1k_tokens')")
    description: Optional[str] = Field(
        default=None,
        description="Human-readable description of what this cost covers",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_ledger(request: Request) -> FinancialLedger:
    """Extract the FinancialLedger from FastAPI app state.

    Raises 503 Service Unavailable if not yet initialised.
    """
    ledger: Optional[FinancialLedger] = getattr(request.app.state, "ledger", None)
    if ledger is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Financial ledger not initialised. Server is starting up.",
        )
    return ledger


def _require_finance_admin(user: CurrentUser) -> None:
    """Raise 403 if the user is not in the finance admin list.

    If _ADMIN_USERS is empty (not configured), any authenticated user is
    allowed — suitable for single-operator deployments.
    """
    if _ADMIN_USERS and user.user_id not in _ADMIN_USERS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Finance admin access required. Set FINANCE_ADMIN_USERS env var.",
        )


def _validate_period(period: str) -> None:
    """Raise 400 if period is not a recognised value."""
    valid = {"today", "week", "month", "year", "all"}
    if period not in valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid period {period!r}. Must be one of: {', '.join(sorted(valid))}",
        )


def _validate_direction(direction: Optional[str]) -> None:
    """Raise 400 if direction is provided but invalid."""
    if direction is not None and direction not in ("revenue", "cost"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="direction must be 'revenue' or 'cost'",
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/health",
    summary="Quick P&L health snapshot",
)
async def finance_health(
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> dict[str, Any]:
    """Return a quick P&L snapshot for today, month-to-date, and all time.

    Useful as a fast dashboard widget. All amounts in integer cents.

    Requires authentication and finance admin access.
    """
    _require_finance_admin(user)
    ledger = _get_ledger(request)
    try:
        return await ledger.get_health_snapshot()
    except Exception as exc:
        logger.error("finance_health error user=%s: %s", user.user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve financial health snapshot.",
        ) from exc


@router.get(
    "/summary",
    summary="Financial summary for a period",
)
async def get_summary(
    request: Request,
    period: str = Query(default="today", description="today|week|month|year|all"),
    sector: Optional[str] = Query(default=None),
    tier: Optional[str] = Query(default=None),
    user: CurrentUser = Depends(require_auth),
) -> dict[str, Any]:
    """Return financial summary (revenue, cost, profit, margin) for a period.

    Optionally filter by sector and/or subscription tier.

    All monetary values are in integer cents.

    Requires authentication and finance admin access.
    """
    _require_finance_admin(user)
    _validate_period(period)
    ledger = _get_ledger(request)
    try:
        return await ledger.get_summary(period=period, sector=sector, tier=tier)
    except Exception as exc:
        logger.error("get_summary error user=%s period=%s: %s", user.user_id, period, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve financial summary.",
        ) from exc


@router.get(
    "/margins",
    summary="Margin analysis by sector and tier",
)
async def get_margins(
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> dict[str, Any]:
    """Return detailed margin breakdown per sector and subscription tier.

    Shows exactly where money is being made and lost.
    All amounts in integer cents.

    Requires authentication and finance admin access.
    """
    _require_finance_admin(user)
    ledger = _get_ledger(request)
    try:
        return await ledger.get_margins()
    except Exception as exc:
        logger.error("get_margins error user=%s: %s", user.user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve margin analysis.",
        ) from exc


@router.get(
    "/trend",
    summary="Daily revenue/cost/profit trend",
)
async def get_trend(
    request: Request,
    days: int = Query(default=30, ge=1, le=365, description="Number of past days"),
    user: CurrentUser = Depends(require_auth),
) -> list[dict[str, Any]]:
    """Return daily P&L trend data for charting.

    Returns a list sorted oldest to newest.
    Each entry includes: date, revenue_cents, cost_cents, profit_cents, margin_pct.

    Requires authentication and finance admin access.
    """
    _require_finance_admin(user)
    ledger = _get_ledger(request)
    try:
        return await ledger.get_daily_trend(days=days)
    except Exception as exc:
        logger.error("get_trend error user=%s days=%d: %s", user.user_id, days, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve daily trend.",
        ) from exc


@router.get(
    "/transactions",
    summary="Paginated transaction list",
)
async def get_transactions(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    tx_type: Optional[str] = Query(default=None),
    direction: Optional[str] = Query(default=None),
    agent_id: Optional[str] = Query(default=None),
    start_date: Optional[str] = Query(default=None, description="ISO date e.g. 2026-01-01"),
    end_date: Optional[str] = Query(default=None, description="ISO date e.g. 2026-01-31"),
    user: CurrentUser = Depends(require_auth),
) -> dict[str, Any]:
    """Return paginated financial transactions with optional filters.

    Filters:
    - tx_type: filter by transaction type constant
    - direction: 'revenue' or 'cost'
    - agent_id: filter by specific agent
    - start_date / end_date: ISO date strings for date range

    Returns: { total, offset, limit, items: [...] }

    Requires authentication and finance admin access.
    """
    _require_finance_admin(user)
    _validate_direction(direction)
    ledger = _get_ledger(request)
    try:
        return await ledger.get_transactions(
            limit=limit,
            offset=offset,
            tx_type=tx_type,
            direction=direction,
            agent_id=agent_id,
            start_date=start_date,
            end_date=end_date,
        )
    except Exception as exc:
        logger.error("get_transactions error user=%s: %s", user.user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve transactions.",
        ) from exc


@router.get(
    "/cost-rates",
    summary="List all configured cost rates",
)
async def list_cost_rates(
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> list[dict[str, Any]]:
    """Return all cost rates configured in the system.

    Cost rates define per-unit costs used for margin calculation.
    All rates in integer cents.

    Requires authentication and finance admin access.
    """
    _require_finance_admin(user)
    ledger = _get_ledger(request)
    try:
        return await ledger.get_cost_rates()
    except Exception as exc:
        logger.error("list_cost_rates error user=%s: %s", user.user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve cost rates.",
        ) from exc


@router.put(
    "/cost-rates/{cost_type}",
    summary="Update a cost rate",
)
async def update_cost_rate(
    cost_type: str,
    body: UpdateCostRateRequest,
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> dict[str, Any]:
    """Create or update a cost rate entry.

    Parameters:
    - cost_type: unique key (e.g. 'openai_api', 'stripe_percentage')
    - rate_cents: integer cents per unit
    - unit: what one unit is (e.g. 'per_1k_tokens', 'per_month')
    - description: optional human-readable note

    Requires authentication and finance admin access.
    """
    _require_finance_admin(user)
    ledger = _get_ledger(request)
    try:
        await ledger.update_cost_rate(
            cost_type=cost_type,
            rate_cents=body.rate_cents,
            unit=body.unit,
            description=body.description,
        )
        # Return the updated rate
        rates = await ledger.get_cost_rates()
        updated = next((r for r in rates if r["cost_type"] == cost_type), None)
        if updated is None:
            # Shouldn't happen, but handle gracefully
            return {"cost_type": cost_type, "rate_cents": body.rate_cents, "unit": body.unit}
        return updated
    except Exception as exc:
        logger.error(
            "update_cost_rate error user=%s cost_type=%s: %s",
            user.user_id, cost_type, exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update cost rate.",
        ) from exc
