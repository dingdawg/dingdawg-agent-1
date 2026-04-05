"""Skill management endpoints: list, detail, execute, quarantine, approve.

Provides the HTTP API for managing skills in the agent platform.
All endpoints except listing require authentication.  Administrative
actions (quarantine, approve) require ADMIN role.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from isg_agent.api.deps import CurrentUser, require_auth, require_admin

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/skills", tags=["skills"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class SkillSummary(BaseModel):
    """Summary of a skill for list responses."""

    name: str
    version: str
    description: str
    author: str
    capabilities: list[str] = Field(default_factory=list)
    min_trust_score: float = 0.0
    reputation_score: float = 0.5
    is_trusted: bool = False
    is_quarantined: bool = False


class SkillDetail(SkillSummary):
    """Detailed skill information including parameters."""

    parameters: list[dict[str, Any]] = Field(default_factory=list)
    entry_point: str = ""
    event_count: int = 0
    last_updated: str = ""


class ExecuteRequest(BaseModel):
    """Request to execute a skill."""

    action: str = Field(default="", description="Action to perform within the skill")
    parameters: dict[str, Any] = Field(default_factory=dict)
    timeout: Optional[float] = Field(default=None, ge=1.0, le=300.0)


class ExecuteResponse(BaseModel):
    """Response from skill execution."""

    success: bool
    output: str
    error: Optional[str] = None
    duration_ms: int
    audit_id: str


class QuarantineRequest(BaseModel):
    """Request to quarantine a skill."""

    reason: str = Field(default="", max_length=500)


class ApproveResponse(BaseModel):
    """Response from skill approval."""

    skill_name: str
    status: str
    approved_by: str


class SkillListResponse(BaseModel):
    """List of skills with count."""

    skills: list[SkillSummary]
    count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_skill_reputation(request: Request):
    """Get SkillReputation from app state, or None."""
    return getattr(request.app.state, "skill_reputation", None)


def _get_quarantine_manager(request: Request):
    """Get QuarantineManager from app state, or None."""
    return getattr(request.app.state, "quarantine_manager", None)


def _get_skill_executor(request: Request):
    """Get SkillExecutor from app state, or None."""
    return getattr(request.app.state, "skill_executor", None)


def _get_governance_gate(request: Request):
    """Get GovernanceGate from app state, or None."""
    return getattr(request.app.state, "governance_gate", None)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=SkillListResponse,
    summary="List all available skills",
)
async def list_skills(request: Request) -> SkillListResponse:
    """Return all available skills with reputation scores.

    This endpoint does not require authentication.
    """
    reputation = _get_skill_reputation(request)
    quarantine = _get_quarantine_manager(request)
    executor = _get_skill_executor(request)

    skills: list[SkillSummary] = []

    if executor is not None:
        skill_names = await executor.list_skills()
        for name in skill_names:
            rep_score = 0.5
            is_trusted = False
            is_quarantined = False

            if reputation is not None:
                rep = await reputation.get_reputation(name)
                rep_score = rep.score
                is_trusted = rep.is_trusted

            if quarantine is not None:
                is_quarantined = await quarantine.is_quarantined(name)

            skills.append(
                SkillSummary(
                    name=name,
                    version="0.1.0",
                    description="",
                    author="unknown",
                    reputation_score=rep_score,
                    is_trusted=is_trusted,
                    is_quarantined=is_quarantined,
                )
            )

    return SkillListResponse(skills=skills, count=len(skills))


@router.get(
    "/{skill_name}",
    response_model=SkillDetail,
    summary="Get skill details and reputation",
)
async def get_skill(
    skill_name: str,
    request: Request,
) -> SkillDetail:
    """Return detailed information about a specific skill."""
    reputation = _get_skill_reputation(request)
    quarantine = _get_quarantine_manager(request)

    rep_score = 0.5
    is_trusted = False
    event_count = 0
    last_updated = ""

    if reputation is not None:
        rep = await reputation.get_reputation(skill_name)
        rep_score = rep.score
        is_trusted = rep.is_trusted
        event_count = rep.event_count
        last_updated = rep.last_updated

    is_quarantined = False
    if quarantine is not None:
        is_quarantined = await quarantine.is_quarantined(skill_name)

    return SkillDetail(
        name=skill_name,
        version="0.1.0",
        description="",
        author="unknown",
        reputation_score=rep_score,
        is_trusted=is_trusted,
        is_quarantined=is_quarantined,
        event_count=event_count,
        last_updated=last_updated,
    )


@router.post(
    "/{skill_name}/execute",
    response_model=ExecuteResponse,
    summary="Execute a skill (auth required, governance checked)",
)
async def execute_skill(
    skill_name: str,
    body: ExecuteRequest,
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> ExecuteResponse:
    """Execute a skill through the governance pipeline.

    The skill must not be quarantined.  A governance check is performed
    before execution.  The execution is sandboxed with timeout limits.
    """
    quarantine = _get_quarantine_manager(request)
    executor = _get_skill_executor(request)
    governance = _get_governance_gate(request)

    # Check quarantine
    if quarantine is not None:
        is_q = await quarantine.is_quarantined(skill_name)
        if is_q:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Skill {skill_name!r} is quarantined and cannot be executed",
            )

    # Governance check
    if governance is not None:
        from isg_agent.core.governance import GovernanceDecision

        result = await governance.evaluate(
            task_description=f"Execute skill: {skill_name}",
        )
        if result.decision == GovernanceDecision.HALT:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Governance gate halted execution: {result.reason}",
            )

    # Execute
    if executor is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Skill executor not available",
        )

    # Merge action into parameters so skill handlers can dispatch on it
    effective_params = {**body.parameters}
    if body.action:
        effective_params["action"] = body.action

    exec_result = await executor.execute(
        skill_name=skill_name,
        parameters=effective_params,
        timeout=body.timeout,
    )

    if not exec_result.success:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exec_result.error or "Skill execution failed",
        )

    return ExecuteResponse(
        success=exec_result.success,
        output=exec_result.output,
        error=exec_result.error,
        duration_ms=exec_result.duration_ms,
        audit_id=exec_result.audit_id,
    )


@router.post(
    "/{skill_name}/quarantine",
    status_code=status.HTTP_200_OK,
    summary="Quarantine a skill (admin only)",
)
async def quarantine_skill(
    skill_name: str,
    body: QuarantineRequest,
    request: Request,
    user: CurrentUser = Depends(require_admin),
) -> dict[str, str]:
    """Place a skill into quarantine.

    Requires admin authentication (owner-only).
    """
    quarantine = _get_quarantine_manager(request)
    if quarantine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Quarantine manager not available",
        )

    entry = await quarantine.quarantine(skill_name, body.reason)
    return {
        "skill_name": entry.skill_name,
        "status": entry.status.value,
        "reason": entry.reason,
    }


@router.post(
    "/{skill_name}/approve",
    response_model=ApproveResponse,
    summary="Approve a quarantined skill (admin only)",
)
async def approve_skill(
    skill_name: str,
    request: Request,
    user: CurrentUser = Depends(require_admin),
) -> ApproveResponse:
    """Release a skill from quarantine.

    Requires admin authentication (owner-only).
    """
    quarantine = _get_quarantine_manager(request)
    if quarantine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Quarantine manager not available",
        )

    entry = await quarantine.approve(skill_name, approved_by=user.user_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill {skill_name!r} is not in quarantine",
        )

    return ApproveResponse(
        skill_name=entry.skill_name,
        status=entry.status.value,
        approved_by=user.user_id,
    )
