"""Brand verification API routes.

Public endpoints (no auth required):
    POST  /api/v1/handles/verify-brand
    POST  /api/v1/handles/verify-brand/{request_id}/email
    POST  /api/v1/handles/verify-brand/{request_id}/email/verify
    POST  /api/v1/handles/verify-brand/{request_id}/dns/check
    POST  /api/v1/handles/verify-brand/{request_id}/meta/check
    POST  /api/v1/handles/verify-brand/{request_id}/social
    GET   /api/v1/handles/verify-brand/{request_id}/status

Admin-only endpoints (Bearer token with admin role required):
    GET   /api/v1/admin/brand-verifications?status=pending&limit=50
    POST  /api/v1/admin/brand-verifications/{request_id}/approve
    POST  /api/v1/admin/brand-verifications/{request_id}/deny

Admin auth uses the existing JWT dependency from isg_agent.api.deps.
Admin role is determined by a ``roles`` claim in the token that contains
``"admin"``, or by email matching the ``ISG_AGENT_ADMIN_EMAIL`` env var
(fallback for single-operator deployments).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator

from isg_agent.agents.brand_verification import BrandVerificationService
from isg_agent.api.deps import CurrentUser, require_auth

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(tags=["brand-verification"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class SubmitVerificationRequest(BaseModel):
    """Body for POST /api/v1/handles/verify-brand."""

    handle: str
    requester_email: str
    company_name: str
    company_domain: Optional[str] = None
    evidence_text: Optional[str] = None

    @field_validator("handle")
    @classmethod
    def _handle_lowercase(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("requester_email")
    @classmethod
    def _email_lowercase(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("company_name")
    @classmethod
    def _company_name_nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("company_name must not be empty")
        return v


class SubmitVerificationResponse(BaseModel):
    """Response for a successful verification submission."""

    request_id: str
    status: str
    dns_token: str
    meta_token: str
    email_verification_available: bool
    dns_instructions: Optional[str] = None
    meta_instructions: Optional[str] = None
    message: str


class InitiateEmailRequest(BaseModel):
    """Body for POST /email."""

    target_email: Optional[str] = None


class InitiateEmailResponse(BaseModel):
    """Response for email initiation."""

    sent: bool
    email_masked: str
    expires_in: int


class VerifyEmailCodeRequest(BaseModel):
    """Body for POST /email/verify."""

    code: str


class VerifyEmailCodeResponse(BaseModel):
    """Response for email code verification."""

    verified: bool
    score: int
    status: str
    auto_approved: bool


class DnsCheckResponse(BaseModel):
    """Response for DNS check."""

    verified: bool
    score: int
    status: str
    auto_approved: bool
    record_found: bool = False


class MetaCheckResponse(BaseModel):
    """Response for meta tag check."""

    verified: bool
    score: int
    status: str
    auto_approved: bool


class SocialProofRequest(BaseModel):
    """Body for POST /social."""

    twitter: Optional[str] = None
    linkedin: Optional[str] = None
    facebook: Optional[str] = None
    instagram: Optional[str] = None
    website: Optional[str] = None


class SocialProofResponse(BaseModel):
    """Response for social proof."""

    recorded: bool
    score: int
    links_count: int


class StatusResponse(BaseModel):
    """Public status check response (no internal tokens)."""

    request_id: str
    handle: str
    status: str
    verification_score: int
    signals_completed: list[str]
    created_at: str
    updated_at: Optional[str] = None
    company_name_masked: str


class AdminListResponse(BaseModel):
    """Response for the admin list endpoint."""

    requests: list[dict]
    total: int


class AdminApproveRequest(BaseModel):
    """Body for admin approve endpoint."""

    admin_notes: Optional[str] = None


class AdminDenyRequest(BaseModel):
    """Body for admin deny endpoint."""

    admin_notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers: extract service + admin guard
# ---------------------------------------------------------------------------


def _get_bvr_service(request: Request) -> BrandVerificationService:
    """Extract BrandVerificationService from app state."""
    svc: Optional[BrandVerificationService] = getattr(
        request.app.state, "brand_verification_service", None
    )
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Brand verification service not initialised.",
        )
    return svc


def _require_admin(current_user: CurrentUser) -> CurrentUser:
    """Raise 403 if the authenticated user is not an admin.

    Admin detection (in priority order):
    1. JWT ``email`` matches ISG_AGENT_ADMIN_EMAIL env var.
    2. JWT ``roles`` claim contains ``"admin"`` (future).
    """
    admin_email = os.environ.get("ISG_AGENT_ADMIN_EMAIL", "").strip().lower()
    if admin_email and current_user.email.lower() == admin_email:
        return current_user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin access required.",
    )


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/api/v1/handles/verify-brand",
    response_model=SubmitVerificationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a brand verification request for a protected handle",
)
async def submit_brand_verification(
    body: SubmitVerificationRequest,
    request: Request,
) -> SubmitVerificationResponse:
    """Submit a brand verification request.

    Use this endpoint when you want to claim a handle that contains a
    protected brand name (e.g. ``nike-downtown-store``) and you can prove
    you represent that brand.

    Returns dns_token + meta_token with instructions on how to complete
    the automated verification signals.

    Returns 400 if:
    - The handle is NOT brand-pattern-blocked (no verification needed).
    - A duplicate pending request from the same email already exists.
    - The email address is malformed.

    Returns 422 if request body validation fails (missing required fields).
    """
    svc = _get_bvr_service(request)
    try:
        result = await svc.submit_request(
            handle=body.handle,
            requester_email=body.requester_email,
            company_name=body.company_name,
            company_domain=body.company_domain,
            evidence_text=body.evidence_text,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return SubmitVerificationResponse(
        request_id=result["request_id"],
        status=result["status"],
        dns_token=result["dns_token"],
        meta_token=result["meta_token"],
        email_verification_available=result["email_verification_available"],
        dns_instructions=result.get("dns_instructions"),
        meta_instructions=result.get("meta_instructions"),
        message=result["message"],
    )


@router.post(
    "/api/v1/handles/verify-brand/{request_id}/email",
    response_model=InitiateEmailResponse,
    summary="Initiate domain email verification — sends a 6-digit code",
)
async def initiate_email_verification(
    request_id: str,
    body: InitiateEmailRequest,
    request: Request,
) -> InitiateEmailResponse:
    """Send a 6-digit verification code to a domain email address.

    The email must be at ``@company_domain`` — free providers like gmail,
    yahoo, etc. are rejected.

    Returns 400 if:
    - Request not found or in terminal state.
    - Email is from a free provider.
    - Email domain does not match company_domain.
    - Max attempts (5) reached.
    """
    svc = _get_bvr_service(request)
    try:
        result = await svc.initiate_email_verification(
            request_id=request_id,
            target_email=body.target_email,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return InitiateEmailResponse(
        sent=result["sent"],
        email_masked=result["email_masked"],
        expires_in=result["expires_in"],
    )


@router.post(
    "/api/v1/handles/verify-brand/{request_id}/email/verify",
    response_model=VerifyEmailCodeResponse,
    summary="Verify the 6-digit domain email code",
)
async def verify_email_code(
    request_id: str,
    body: VerifyEmailCodeRequest,
    request: Request,
) -> VerifyEmailCodeResponse:
    """Verify the 6-digit code sent to the domain email address.

    On success: awards 30 verification points, may trigger auto-approval.
    """
    svc = _get_bvr_service(request)
    try:
        result = await svc.verify_email_code(
            request_id=request_id,
            code=body.code,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return VerifyEmailCodeResponse(
        verified=result["verified"],
        score=result["score"],
        status=result["status"],
        auto_approved=result["auto_approved"],
    )


@router.post(
    "/api/v1/handles/verify-brand/{request_id}/dns/check",
    response_model=DnsCheckResponse,
    summary="Check DNS TXT record for domain ownership verification",
)
async def check_dns_verification(
    request_id: str,
    request: Request,
) -> DnsCheckResponse:
    """Check if the DNS TXT record exists for the verified domain.

    The user must have added a TXT record:
    ``_dingdawg-verify.{domain}`` with value ``{dns_token}``

    On success: awards 30 verification points, may trigger auto-approval.
    """
    svc = _get_bvr_service(request)
    try:
        result = await svc.check_dns_verification(request_id=request_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return DnsCheckResponse(
        verified=result["verified"],
        score=result["score"],
        status=result["status"],
        auto_approved=result["auto_approved"],
        record_found=result.get("record_found", False),
    )


@router.post(
    "/api/v1/handles/verify-brand/{request_id}/meta/check",
    response_model=MetaCheckResponse,
    summary="Check website meta tag for domain ownership verification",
)
async def check_meta_verification(
    request_id: str,
    request: Request,
) -> MetaCheckResponse:
    """Check if the website homepage contains the verification meta tag.

    The user must have added to their homepage ``<head>``:
    ``<meta name="dingdawg-verify" content="{meta_token}">``

    On success: awards 20 verification points, may trigger auto-approval.
    """
    svc = _get_bvr_service(request)
    try:
        result = await svc.check_meta_verification(request_id=request_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return MetaCheckResponse(
        verified=result["verified"],
        score=result["score"],
        status=result["status"],
        auto_approved=result["auto_approved"],
    )


@router.post(
    "/api/v1/handles/verify-brand/{request_id}/social",
    response_model=SocialProofResponse,
    summary="Submit social media links for social proof verification",
)
async def check_social_proof(
    request_id: str,
    body: SocialProofRequest,
    request: Request,
) -> SocialProofResponse:
    """Submit social media profile links for brand identity verification.

    Awards 10 pts if at least 2 links are provided. All links are stored
    for admin review regardless of point threshold.
    """
    svc = _get_bvr_service(request)
    try:
        social_links = {
            k: v
            for k, v in {
                "twitter": body.twitter,
                "linkedin": body.linkedin,
                "facebook": body.facebook,
                "instagram": body.instagram,
                "website": body.website,
            }.items()
            if v is not None
        }
        result = await svc.check_social_proof(
            request_id=request_id,
            social_links=social_links,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return SocialProofResponse(
        recorded=result["recorded"],
        score=result["score"],
        links_count=result["links_count"],
    )


@router.get(
    "/api/v1/handles/verify-brand/{request_id}/status",
    response_model=StatusResponse,
    summary="Check the status of a brand verification request (public-safe)",
)
async def get_verification_status(
    request_id: str,
    request: Request,
) -> StatusResponse:
    """Return the current status of a brand verification request.

    Public endpoint — submitters can check their request without logging in.
    Internal tokens, codes, and sensitive fields are excluded from the response.

    Returns 404 if the request_id does not exist.
    """
    svc = _get_bvr_service(request)
    record = await svc.get_status(request_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Verification request {request_id!r} not found.",
        )

    return StatusResponse(
        request_id=record["request_id"],
        handle=record["handle"],
        status=record["status"],
        verification_score=record["verification_score"],
        signals_completed=record["signals_completed"],
        created_at=record["created_at"],
        updated_at=record.get("updated_at"),
        company_name_masked=record["company_name_masked"],
    )


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/admin/brand-verifications",
    response_model=AdminListResponse,
    summary="[Admin] List brand verification requests",
)
async def admin_list_verifications(
    request: Request,
    verification_status: str = "pending",
    limit: int = 50,
    current_user: CurrentUser = Depends(require_auth),
) -> AdminListResponse:
    """List brand verification requests filtered by status.

    Requires admin authentication.

    Query params:
    - ``verification_status``: ``pending`` | ``approved`` | ``denied`` | ``expired``
      (default: ``pending``)
    - ``limit``: max records to return (default: 50, max: 200)
    """
    _require_admin(current_user)

    allowed_statuses = {
        "pending", "email_sent", "dns_pending", "verifying",
        "approved", "denied", "expired",
    }
    if verification_status not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"status must be one of {sorted(allowed_statuses)}",
        )
    if limit < 1 or limit > 200:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="limit must be between 1 and 200",
        )

    svc = _get_bvr_service(request)
    records = await svc.list_requests(status=verification_status, limit=limit)
    return AdminListResponse(requests=records, total=len(records))


@router.post(
    "/api/v1/admin/brand-verifications/{request_id}/approve",
    summary="[Admin] Approve a brand verification request",
)
async def admin_approve_verification(
    request_id: str,
    body: AdminApproveRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    """Approve a pending brand verification request.

    Sets status to ``approved`` and awards 100 pts.

    Returns 404 if the request does not exist.
    Returns 409 if request is already in a terminal state.
    """
    _require_admin(current_user)
    svc = _get_bvr_service(request)

    record = await svc.get_request(request_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Verification request {request_id!r} not found.",
        )
    if record["status"] in ("approved", "denied"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Request {request_id!r} is already in status "
                f"'{record['status']}' and cannot be approved."
            ),
        )

    result = await svc.admin_approve(
        request_id=request_id,
        admin_notes=body.admin_notes,
        reviewed_by=current_user.user_id,
    )

    if not result.get("approved"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Request could not be approved (may have changed state).",
        )

    logger.info(
        "Admin %s approved brand verification request %s for handle %s",
        current_user.user_id,
        request_id,
        record["handle"],
    )
    return {
        "approved": True,
        "handle": record["handle"],
        "request_id": request_id,
    }


@router.post(
    "/api/v1/admin/brand-verifications/{request_id}/deny",
    summary="[Admin] Deny a brand verification request",
)
async def admin_deny_verification(
    request_id: str,
    body: AdminDenyRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    """Deny a pending brand verification request.

    Sets status to ``denied``.

    Returns 404 if the request does not exist.
    Returns 409 if request is already in a terminal state.
    """
    _require_admin(current_user)
    svc = _get_bvr_service(request)

    record = await svc.get_request(request_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Verification request {request_id!r} not found.",
        )
    if record["status"] in ("approved", "denied"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Request {request_id!r} is already in status "
                f"'{record['status']}' and cannot be denied."
            ),
        )

    result = await svc.admin_deny(
        request_id=request_id,
        admin_notes=body.admin_notes,
        reviewed_by=current_user.user_id,
    )

    if not result.get("denied"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Request could not be denied (may have changed state).",
        )

    logger.info(
        "Admin %s denied brand verification request %s for handle %s",
        current_user.user_id,
        request_id,
        record["handle"],
    )
    return {"denied": True, "request_id": request_id}
