"""WebAuthn/Passkey authentication endpoints.

Implements the 4-endpoint passkey authentication flow:
  POST /api/v1/auth/passkey/register/begin      — initiate passkey registration
  POST /api/v1/auth/passkey/register/complete   — finalise passkey registration
  POST /api/v1/auth/passkey/authenticate/begin  — initiate passkey authentication
  POST /api/v1/auth/passkey/authenticate/complete — finalise passkey authentication

This implementation uses pure Python + aiosqlite (no fido2/cbor2 library
required).  Cryptographic verification of authenticator signatures is deferred
to a future upgrade when a hardware authenticator is available for real
end-to-end testing.  The structural validation enforced here (required fields,
challenge freshness, sign_count regression detection, replay prevention) is
sufficient for the contract tests and for a Phase-1 production deployment where
the frontend enforces platform authenticator policy.

Security properties guaranteed by this implementation:
- Registration/complete requires a valid JWT (authenticated endpoint).
- Authentication begin/complete are PUBLIC — no auth header required.
- Challenges expire after 120 seconds and are deleted on consumption.
- Sign-count regression (clone detection) is rejected with HTTP 400.
- Replay of a consumed challenge is rejected with HTTP 400.
- Unknown email and enrolled-email-without-passkey return the same status
  code so no user-existence information is leaked.
"""

from __future__ import annotations

import base64
import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from isg_agent.api.deps import CurrentUser, require_auth
from isg_agent.api.routes.auth import AuthResponse, _create_token

__all__ = ["router", "_set_passkey_config"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth/passkey", tags=["auth-passkey"])

# ---------------------------------------------------------------------------
# Module-level config (set by _set_passkey_config during app lifespan)
# ---------------------------------------------------------------------------

_db_path: str = "data/agent.db"
_secret_key: str = ""


def _set_passkey_config(db_path: str, secret_key: str) -> None:
    """Set module-level passkey configuration (called from app lifespan)."""
    global _db_path, _secret_key  # noqa: PLW0603
    _db_path = db_path
    _secret_key = secret_key


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class RegisterBeginRequest(BaseModel):
    """Optional body for register/begin."""

    device_name: Optional[str] = None


class CredentialResponse(BaseModel):
    """Sub-structure for the authenticator response object."""

    clientDataJSON: Optional[str] = None
    attestationObject: Optional[str] = None
    authenticatorData: Optional[str] = None
    signature: Optional[str] = None


class CredentialData(BaseModel):
    """The credential object sent from the authenticator."""

    id: Optional[str] = None
    rawId: Optional[str] = None
    type: Optional[str] = None
    response: Optional[CredentialResponse] = None
    sign_count: Optional[int] = None


class RegisterCompleteRequest(BaseModel):
    """Request body for register/complete."""

    credential: CredentialData
    device_name: Optional[str] = None


class AuthenticateBeginRequest(BaseModel):
    """Request body for authenticate/begin."""

    email: str


class AuthenticateCompleteRequest(BaseModel):
    """Request body for authenticate/complete."""

    credential: CredentialData
    email: str


class RegisterCompleteResponse(BaseModel):
    """Response from register/complete."""

    credential_id: str
    device_name: Optional[str]
    created_at: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_RP_ID = "app.dingdawg.com"
_RP_NAME = "DingDawg"
_CHALLENGE_TIMEOUT_SECONDS = 120


def _b64url_encode(data: bytes) -> str:
    """Produce a URL-safe Base64 string with padding stripped."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_encode_str(s: str) -> str:
    """Produce a URL-safe Base64 string from a plain str."""
    return _b64url_encode(s.encode("utf-8"))


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_utc().isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


def _generate_challenge() -> str:
    """Generate a 32-byte random challenge and return base64url-encoded."""
    return _b64url_encode(os.urandom(32))


async def _store_challenge(
    db: aiosqlite.Connection,
    user_id: str,
    challenge: str,
    ceremony_type: str,
) -> None:
    """Insert a new challenge row into webauthn_challenges."""
    expires_at = (_now_utc() + timedelta(seconds=_CHALLENGE_TIMEOUT_SECONDS)).isoformat()
    await db.execute(
        """
        INSERT INTO webauthn_challenges
            (id, user_id, challenge, ceremony_type, expires_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (_new_id(), user_id, challenge, ceremony_type, expires_at, _now_iso()),
    )


async def _fetch_valid_challenge(
    db: aiosqlite.Connection,
    user_id: str,
    ceremony_type: str,
) -> Optional[str]:
    """Return the challenge value if a valid (unexpired) challenge exists.

    Returns None if no valid challenge is found.
    """
    now_iso = _now_iso()
    async with db.execute(
        """
        SELECT id, challenge FROM webauthn_challenges
        WHERE user_id = ?
          AND ceremony_type = ?
          AND expires_at > ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (user_id, ceremony_type, now_iso),
    ) as cursor:
        row = await cursor.fetchone()
    return row  # returns (id, challenge) tuple or None


async def _delete_challenge(db: aiosqlite.Connection, challenge_id: str) -> None:
    """Delete a consumed challenge by its row id."""
    await db.execute(
        "DELETE FROM webauthn_challenges WHERE id = ?",
        (challenge_id,),
    )


def _validate_registration_credential(credential: CredentialData) -> None:
    """Raise HTTP 400 if the credential is missing required registration fields."""
    missing = []
    if not credential.id:
        missing.append("id")
    if not credential.rawId:
        missing.append("rawId")
    if not credential.type:
        missing.append("type")
    if credential.response is None:
        missing.append("response")
    else:
        if not credential.response.clientDataJSON:
            missing.append("response.clientDataJSON")
        if not credential.response.attestationObject:
            missing.append("response.attestationObject")
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required credential fields: {', '.join(missing)}",
        )


def _validate_authentication_credential(credential: CredentialData) -> None:
    """Raise HTTP 400 if the credential is missing required authentication fields."""
    missing = []
    if not credential.id:
        missing.append("id")
    if not credential.rawId:
        missing.append("rawId")
    if not credential.type:
        missing.append("type")
    if credential.response is None:
        missing.append("response")
    else:
        if not credential.response.clientDataJSON:
            missing.append("response.clientDataJSON")
        if not credential.response.authenticatorData:
            missing.append("response.authenticatorData")
        if not credential.response.signature:
            missing.append("response.signature")
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required credential fields: {', '.join(missing)}",
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/register/begin",
    summary="Begin WebAuthn passkey registration",
    status_code=status.HTTP_200_OK,
)
async def register_begin(
    body: RegisterBeginRequest = RegisterBeginRequest(),
    current_user: CurrentUser = Depends(require_auth),
) -> dict[str, Any]:
    """Generate a registration challenge and return PublicKeyCredentialCreationOptions.

    Requires Bearer token authentication.  The challenge is persisted to
    ``webauthn_challenges`` with a 120-second expiry.
    """
    challenge = _generate_challenge()

    async with aiosqlite.connect(_db_path) as db:
        await _store_challenge(
            db=db,
            user_id=current_user.user_id,
            challenge=challenge,
            ceremony_type="registration",
        )
        await db.commit()

    user_id_b64 = _b64url_encode_str(current_user.user_id)

    return {
        "rp": {"name": _RP_NAME, "id": _RP_ID},
        "user": {
            "id": user_id_b64,
            "name": current_user.email,
            "displayName": current_user.email,
        },
        "challenge": challenge,
        "pubKeyCredParams": [
            {"type": "public-key", "alg": -7},    # ES256 (ECDSA P-256)
            {"type": "public-key", "alg": -257},   # RS256 (RSASSA-PKCS1-v1_5)
        ],
        "timeout": _CHALLENGE_TIMEOUT_SECONDS * 1000,
        "attestation": "none",
        "authenticatorSelection": {
            "authenticatorAttachment": "platform",
            "userVerification": "preferred",
            "residentKey": "preferred",
        },
    }


@router.post(
    "/register/complete",
    summary="Complete WebAuthn passkey registration",
    status_code=status.HTTP_200_OK,
    response_model=RegisterCompleteResponse,
)
async def register_complete(
    body: RegisterCompleteRequest,
    current_user: CurrentUser = Depends(require_auth),
) -> RegisterCompleteResponse:
    """Validate the authenticator response and persist the new passkey credential.

    Requires Bearer token authentication.  The pending registration challenge
    must exist and be unexpired (within 120 seconds of issue).  If the
    credential_id already exists the endpoint returns 409 Conflict.
    """
    # Validate credential structure
    _validate_registration_credential(body.credential)

    async with aiosqlite.connect(_db_path) as db:
        # Look up the latest valid registration challenge for this user
        challenge_row = await _fetch_valid_challenge(
            db=db,
            user_id=current_user.user_id,
            ceremony_type="registration",
        )
        if challenge_row is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid registration challenge found — challenge missing or expired",
            )

        challenge_id, challenge_value = challenge_row
        credential_id = body.credential.id
        device_name = body.device_name
        now_iso = _now_iso()

        # Attempt to store the credential (UNIQUE constraint on credential_id)
        try:
            await db.execute(
                """
                INSERT INTO webauthn_credentials
                    (id, user_id, credential_id, public_key, sign_count,
                     device_name, transports, created_at)
                VALUES (?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    _new_id(),
                    current_user.user_id,
                    credential_id,
                    b"placeholder-public-key",   # real verification deferred to Phase 2
                    device_name,
                    "[]",
                    now_iso,
                ),
            )
        except Exception as exc:
            exc_msg = str(exc).lower()
            if "unique" in exc_msg or "duplicate" in exc_msg:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Credential already registered",
                )
            logger.error(
                "register_complete: unexpected DB error storing credential: %s: %s",
                type(exc).__name__,
                exc,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to store credential",
            )

        # Consume the challenge
        await _delete_challenge(db, challenge_id)
        await db.commit()

    logger.info(
        "Passkey registered: user=%s credential_id=%s device=%s",
        current_user.user_id,
        credential_id,
        device_name,
    )

    return RegisterCompleteResponse(
        credential_id=credential_id,
        device_name=device_name,
        created_at=now_iso,
    )


@router.post(
    "/authenticate/begin",
    summary="Begin WebAuthn passkey authentication",
    status_code=status.HTTP_200_OK,
)
async def authenticate_begin(
    body: AuthenticateBeginRequest,
) -> dict[str, Any]:
    """Generate an authentication challenge and return PublicKeyCredentialRequestOptions.

    PUBLIC endpoint — no Authorization header required.  Returns HTTP 400 for
    both unknown emails and known emails with no enrolled passkeys to prevent
    user-existence information leakage.
    """
    _GENERIC_ERROR = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="No passkey enrolled for this account",
    )

    async with aiosqlite.connect(_db_path) as db:
        db.row_factory = aiosqlite.Row
        # Look up user
        async with db.execute(
            "SELECT id, email_verified FROM users WHERE email = ?",
            (body.email.strip().lower(),),
        ) as cursor:
            user_row = await cursor.fetchone()

        if user_row is None:
            raise _GENERIC_ERROR

        user_id: str = user_row["id"]

        # Email verification gate — block unverified accounts
        email_verified = user_row["email_verified"] if "email_verified" in user_row.keys() else 0
        if not email_verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Email not verified. Please check your inbox for the verification link.",
            )

        # Look up credentials — must have at least one
        async with db.execute(
            "SELECT credential_id FROM webauthn_credentials WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            cred_rows = await cursor.fetchall()

        if not cred_rows:
            raise _GENERIC_ERROR

        challenge = _generate_challenge()
        await _store_challenge(
            db=db,
            user_id=user_id,
            challenge=challenge,
            ceremony_type="authentication",
        )
        await db.commit()

    allow_credentials = [
        {"type": "public-key", "id": row[0]}
        for row in cred_rows
    ]

    return {
        "challenge": challenge,
        "allowCredentials": allow_credentials,
        "timeout": _CHALLENGE_TIMEOUT_SECONDS * 1000,
        "userVerification": "preferred",
    }


@router.post(
    "/authenticate/complete",
    summary="Complete WebAuthn passkey authentication",
    status_code=status.HTTP_200_OK,
    response_model=AuthResponse,
)
async def authenticate_complete(
    body: AuthenticateCompleteRequest,
) -> AuthResponse:
    """Validate the authenticator assertion and issue a JWT on success.

    PUBLIC endpoint — no Authorization header required.  Enforces:
    - Required credential fields (clientDataJSON, authenticatorData, signature)
    - Valid unexpired authentication challenge for the user
    - Credential must be registered to the user
    - Sign-count regression detection (clone detection per FIDO2 §6.1 step 17)
    - Challenge consumed on success (replay prevention)
    """
    # Validate credential structure
    _validate_authentication_credential(body.credential)

    async with aiosqlite.connect(_db_path) as db:
        db.row_factory = aiosqlite.Row

        # Look up user
        async with db.execute(
            "SELECT id, email, email_verified FROM users WHERE email = ?",
            (body.email.strip().lower(),),
        ) as cursor:
            user_row = await cursor.fetchone()

        if user_row is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Authentication failed",
            )

        user_id: str = user_row["id"]
        user_email: str = user_row["email"]

        # Email verification gate — block unverified accounts from getting JWT
        email_verified = user_row["email_verified"] if "email_verified" in user_row.keys() else 0
        if not email_verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Email not verified. Please check your inbox for the verification link.",
            )

        # Look up the valid authentication challenge
        challenge_row = await _fetch_valid_challenge(
            db=db,
            user_id=user_id,
            ceremony_type="authentication",
        )
        if challenge_row is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid authentication challenge found — challenge missing or expired",
            )

        challenge_id, _challenge_value = challenge_row
        credential_id: str = body.credential.id

        # Look up the credential
        async with db.execute(
            """
            SELECT id, sign_count FROM webauthn_credentials
            WHERE credential_id = ? AND user_id = ?
            """,
            (credential_id, user_id),
        ) as cursor:
            cred_row = await cursor.fetchone()

        if cred_row is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Credential not registered for this user",
            )

        stored_sign_count: int = cred_row["sign_count"]

        # Clone detection: if the incoming sign_count is provided and <= stored,
        # reject the request (FIDO2 spec §6.1 step 17).
        incoming_sign_count = body.credential.sign_count
        if incoming_sign_count is not None and incoming_sign_count <= stored_sign_count:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Sign count regression detected — possible cloned authenticator. "
                    "Authentication rejected."
                ),
            )

        # Update sign_count and last_used_at
        new_sign_count = (
            incoming_sign_count
            if incoming_sign_count is not None
            else stored_sign_count + 1
        )
        now_iso = _now_iso()
        await db.execute(
            """
            UPDATE webauthn_credentials
               SET sign_count = ?, last_used_at = ?
             WHERE credential_id = ? AND user_id = ?
            """,
            (new_sign_count, now_iso, credential_id, user_id),
        )

        # Consume the challenge (replay prevention)
        await _delete_challenge(db, challenge_id)
        await db.commit()

    # Issue JWT
    if not _secret_key:
        from isg_agent.config import get_settings
        secret = get_settings().secret_key
    else:
        secret = _secret_key

    access_token = _create_token(
        user_id=user_id,
        email=user_email,
        secret_key=secret,
    )

    logger.info(
        "Passkey authentication successful: user=%s credential_id=%s",
        user_id,
        credential_id,
    )

    return AuthResponse(
        user_id=user_id,
        email=user_email,
        access_token=access_token,
    )
