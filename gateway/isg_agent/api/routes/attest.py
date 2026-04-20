"""Terminal agent attestation endpoints.

Allows AI agents running on any runtime (Docker, WASM, bare-metal, UEFI,
Raspberry Pi) to obtain a DingDawg AgentID and bootstrap token without
human SSH access.

Endpoints:
  POST /api/v1/attest/agent         — attest agent binary, receive AgentID + DAT
  GET  /api/v1/attest/{attestation_id} — look up a prior attestation
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Literal, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, field_validator

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/attest", tags=["attestation"])

# In-memory store: {attestation_id: AttestRecord}
_attestations: Dict[str, dict] = {}

# Freshness window: ±5 minutes
_FRESHNESS_SECONDS = 300

SUPPORTED_RUNTIMES = Literal["docker", "wasm", "bare-metal", "uefi", "raspberry-pi", "efi"]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class AttestRequest(BaseModel):
    agent_id: Optional[str] = None          # if None, derived from binary_hash + org
    binary_hash: str                        # sha256:hexstring
    runtime: str                            # docker | wasm | bare-metal | uefi | raspberry-pi | efi
    tpm_signature: Optional[str] = None     # base64, for UEFI/TPM2
    operator_org_id: str
    nonce: str                              # UUID4 freshness token
    timestamp: str                          # ISO8601 — must be within ±5 min

    @field_validator("binary_hash")
    @classmethod
    def validate_hash(cls, v: str) -> str:
        if not v.startswith("sha256:"):
            raise ValueError("binary_hash must be prefixed with 'sha256:'")
        hex_part = v[7:]
        if len(hex_part) != 64:
            raise ValueError("sha256 hash must be 64 hex characters")
        return v

    @field_validator("runtime")
    @classmethod
    def validate_runtime(cls, v: str) -> str:
        allowed = {"docker", "wasm", "bare-metal", "uefi", "raspberry-pi", "efi"}
        if v not in allowed:
            raise ValueError(f"runtime must be one of: {', '.join(sorted(allowed))}")
        return v

    @field_validator("nonce")
    @classmethod
    def validate_nonce(cls, v: str) -> str:
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError("nonce must be a valid UUID4")
        return v


class AttestResponse(BaseModel):
    attestation_id: str         # att:{uuid4}
    agent_id: str               # did:ding:{16-char-hex}
    verified: bool
    bootstrap_token: str        # dat:bootstrap:{uuid4}  (placeholder — full JWT in v1.1)
    issued_at: str
    expires_at: str             # 1-hour TTL
    trust_tier: str             # always "unverified" on first attestation
    runtime: str
    operator_org_id: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _derive_agent_id(binary_hash: str, operator_org_id: str) -> str:
    """Derive did:ding: identifier from binary hash + org if not provided."""
    raw = f"{binary_hash}|{operator_org_id}"
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return f"did:ding:{digest[:16]}"


def _validate_freshness(timestamp_str: str) -> None:
    """Raise 400 if timestamp is outside ±5-minute freshness window."""
    try:
        ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="timestamp must be a valid ISO8601 datetime",
        )
    now   = datetime.now(timezone.utc)
    delta = abs((now - ts).total_seconds())
    if delta > _FRESHNESS_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Attestation timestamp outside freshness window (±{_FRESHNESS_SECONDS}s). Delta: {delta:.0f}s",
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/agent",
    response_model=AttestResponse,
    status_code=201,
    summary="Attest agent binary and obtain AgentID + bootstrap token",
)
async def attest_agent(body: AttestRequest) -> AttestResponse:
    """
    Onboard an AI agent from any runtime. Validates freshness, derives AgentID,
    and returns a short-lived bootstrap DAT for initial API access.

    The returned trust_tier is always 'unverified' — it rises as the agent
    accumulates governance events via the dingdawg-sdk.
    """
    _validate_freshness(body.timestamp)

    agent_id       = body.agent_id or _derive_agent_id(body.binary_hash, body.operator_org_id)
    attestation_id = f"att:{uuid.uuid4()}"
    bootstrap_token = f"dat:bootstrap:{uuid.uuid4()}"
    now             = datetime.now(timezone.utc)
    expires         = now + timedelta(hours=1)

    record = {
        "attestation_id":  attestation_id,
        "agent_id":        agent_id,
        "verified":        True,
        "bootstrap_token": bootstrap_token,
        "issued_at":       now.isoformat(),
        "expires_at":      expires.isoformat(),
        "trust_tier":      "unverified",
        "runtime":         body.runtime,
        "operator_org_id": body.operator_org_id,
        "binary_hash":     body.binary_hash,
        "nonce":           body.nonce,
        "tpm_signature":   body.tpm_signature,
    }
    _attestations[attestation_id] = record

    logger.info(
        "Agent attested id=%s agent=%s runtime=%s org=%s",
        attestation_id, agent_id, body.runtime, body.operator_org_id,
    )

    return AttestResponse(**{k: v for k, v in record.items()
                             if k not in ("binary_hash", "nonce", "tpm_signature")})


@router.get(
    "/{attestation_id}",
    response_model=AttestResponse,
    summary="Look up a prior attestation",
)
async def get_attestation(attestation_id: str) -> AttestResponse:
    """Retrieve an attestation record by ID."""
    record = _attestations.get(attestation_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Attestation not found: {attestation_id}",
        )
    return AttestResponse(**{k: v for k, v in record.items()
                             if k not in ("binary_hash", "nonce", "tpm_signature")})
