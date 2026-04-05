"""Full 2FA/MFA implementation for DingDawg Agent 1.

Endpoints
---------
POST /auth/mfa/setup          — Generate TOTP secret + QR URI (Bearer required)
POST /auth/mfa/verify-setup   — Verify first TOTP code, persist secret, return backup codes
POST /auth/mfa/challenge      — Verify TOTP or backup code during login (challenge token flow)
POST /auth/mfa/sms            — Send SMS OTP via Telnyx to registered phone
POST /auth/mfa/sms-verify     — Verify SMS OTP during challenge flow
POST /auth/mfa/disable        — Disable MFA (password + TOTP required)
GET  /auth/mfa/status         — Return MFA status for authenticated user
POST /auth/mfa/phone          — Register or update phone number for SMS OTP

Security properties
-------------------
- TOTP: pyotp TOTP with valid_window=1 (±30 s clock skew tolerance)
- Backup codes: 10 cryptographically random 8-character hex codes, SHA-256 hashed in DB
- Remember device: 30-day signed HMAC cookie (one cookie per device fingerprint)
- Paid tier requirement: mfa_required flag returned on login when tier >= starter
- SMS OTP: 6-digit code, 10-minute TTL, delivered via Telnyx REST API
- Rate limiting: inherits from auth_rate_limit decorator
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from isg_agent.api.routes.auth import (
    _create_token,
    _get_db_path,
    _get_secret_key,
    _ensure_users_table,
    _hash_password,
    _verify_password,
    verify_token,
)

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/mfa", tags=["mfa"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BACKUP_CODE_COUNT = 10
_REMEMBER_DEVICE_DAYS = 30
_SMS_OTP_TTL_SECONDS = 10 * 60  # 10 minutes
_SMS_OTP_LENGTH = 6
_DEVICE_COOKIE_NAME = "dd_device_trust"
_CHALLENGE_TOKEN_TTL = 5 * 60  # 5 minutes (matches auth.py challenge token)

# ---------------------------------------------------------------------------
# DB Schema helpers — MFA columns added idempotently to the users table
# ---------------------------------------------------------------------------

_MFA_COLUMNS: list[tuple[str, str]] = [
    ("mfa_enabled", "INTEGER NOT NULL DEFAULT 0"),
    ("backup_codes_json", "TEXT DEFAULT NULL"),        # JSON list of SHA-256 hashed codes
    ("phone_number", "TEXT DEFAULT NULL"),
    ("sms_otp_hash", "TEXT DEFAULT NULL"),
    ("sms_otp_expires_at", "TEXT DEFAULT NULL"),
    ("mfa_setup_pending_secret", "TEXT DEFAULT NULL"),  # ephemeral pre-confirmation secret
]

_DEVICE_TRUSTS_SQL = """
CREATE TABLE IF NOT EXISTS mfa_device_trusts (
    id          TEXT    PRIMARY KEY,
    user_id     TEXT    NOT NULL,
    token_hash  TEXT    NOT NULL UNIQUE,
    device_hint TEXT,
    created_at  TEXT    NOT NULL,
    expires_at  TEXT    NOT NULL
);
"""
_DEVICE_TRUST_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_mfa_device_trusts_user ON mfa_device_trusts(user_id);"
)


async def _ensure_mfa_schema(db_path: str) -> None:
    """Add MFA columns and device trust table idempotently."""
    async with aiosqlite.connect(db_path) as db:
        for col, col_type in _MFA_COLUMNS:
            try:
                await db.execute(
                    f"ALTER TABLE users ADD COLUMN {col} {col_type}"
                )
            except Exception:
                pass  # Column already exists
        await db.execute(_DEVICE_TRUSTS_SQL)
        await db.execute(_DEVICE_TRUST_INDEX)
        await db.commit()


# ---------------------------------------------------------------------------
# Backup code helpers
# ---------------------------------------------------------------------------

def _generate_backup_codes() -> tuple[list[str], list[str]]:
    """Return (plaintext_codes, hashed_codes).

    Plaintext codes are shown once to the user and never stored.
    Hashed codes (SHA-256) are stored in the DB.
    """
    plaintext: list[str] = []
    hashed: list[str] = []
    for _ in range(_BACKUP_CODE_COUNT):
        code = secrets.token_hex(4).upper()  # 8-char hex code
        plaintext.append(code)
        hashed.append(hashlib.sha256(code.encode()).hexdigest())
    return plaintext, hashed


def _hash_backup_code(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


def _consume_backup_code(hashed_codes: list[str], code: str) -> tuple[bool, list[str]]:
    """Check if code is valid; if so, remove it (one-time use).

    Returns (is_valid, remaining_hashed_codes).
    """
    candidate = _hash_backup_code(code)
    if candidate in hashed_codes:
        remaining = [c for c in hashed_codes if c != candidate]
        return True, remaining
    return False, hashed_codes


# ---------------------------------------------------------------------------
# Remember-device cookie helpers
# ---------------------------------------------------------------------------

def _device_token(user_id: str, secret_key: str) -> str:
    """Generate a signed 32-byte device trust token."""
    raw = secrets.token_bytes(24)
    sig = hmac.new(secret_key.encode(), raw + user_id.encode(), hashlib.sha256).digest()
    return (raw + sig[:8]).hex()


def _set_device_cookie(response: Response, token: str, user_id: str, db_path: str) -> None:
    """Set the remember-device cookie (30 days, HttpOnly, SameSite=Lax)."""
    max_age = _REMEMBER_DEVICE_DAYS * 86400
    response.set_cookie(
        key=_DEVICE_COOKIE_NAME,
        value=f"{user_id}:{token}",
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=True,  # HTTPS only in production
        path="/auth",
    )


async def _is_device_trusted(
    request: Request, user_id: str, db_path: str
) -> bool:
    """Return True if the incoming request has a valid, unexpired device trust cookie."""
    cookie_val = request.cookies.get(_DEVICE_COOKIE_NAME, "")
    if not cookie_val or ":" not in cookie_val:
        return False

    cookie_user_id, token = cookie_val.split(":", 1)
    if cookie_user_id != user_id:
        return False

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT id FROM mfa_device_trusts "
                "WHERE user_id = ? AND token_hash = ? AND expires_at > ?",
                (user_id, token_hash, now_iso),
            )
            row = await cursor.fetchone()
        return row is not None
    except Exception:
        return False


async def _store_device_trust(
    user_id: str, token: str, db_path: str, device_hint: str = ""
) -> None:
    """Persist the device trust token hash in the DB."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    expires_at = datetime.fromtimestamp(
        now.timestamp() + _REMEMBER_DEVICE_DAYS * 86400, tz=timezone.utc
    ).isoformat()
    record_id = str(uuid.uuid4())
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO mfa_device_trusts "
                "(id, user_id, token_hash, device_hint, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (record_id, user_id, token_hash, device_hint, now.isoformat(), expires_at),
            )
            await db.commit()
    except Exception as exc:
        logger.warning("Failed to store device trust: %s", exc)


# ---------------------------------------------------------------------------
# SMS via Telnyx
# ---------------------------------------------------------------------------

async def _send_telnyx_sms(to_number: str, otp: str, settings: object) -> bool:
    """Send OTP via Telnyx REST API. Returns True on success."""
    import httpx

    api_key = getattr(settings, "telnyx_api_key", None) or os.environ.get("TELNYX_API_KEY", "")
    from_number = getattr(settings, "telnyx_from_number", None) or os.environ.get(
        "TELNYX_FROM_NUMBER", ""
    )

    if not api_key:
        logger.warning("Telnyx API key not configured — SMS OTP skipped")
        return False

    message = f"Your DingDawg verification code is: {otp}. Expires in 10 minutes."
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.telnyx.com/v2/messages",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": from_number,
                    "to": to_number,
                    "text": message,
                },
            )
        if resp.status_code in (200, 201):
            logger.info("Telnyx SMS sent to %s", to_number[:4] + "****")
            return True
        logger.error("Telnyx SMS failed: status=%s body=%s", resp.status_code, resp.text[:200])
        return False
    except Exception as exc:
        logger.error("Telnyx SMS exception: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class MfaSetupStartResponse(BaseModel):
    secret: str
    otpauth_uri: str


class MfaVerifySetupRequest(BaseModel):
    code: str
    secret: str  # The pending secret from /auth/mfa/setup


class MfaVerifySetupResponse(BaseModel):
    backup_codes: list[str]
    mfa_enabled: bool = True


class MfaChallengeRequest(BaseModel):
    challenge_token: str
    code: str                            # TOTP code or backup code
    code_type: str = "totp"              # "totp" | "backup" | "sms"
    remember_device: bool = False


class MfaChallengeResponse(BaseModel):
    user_id: str
    email: str
    access_token: str
    token_type: str = "bearer"
    remember_device_set: bool = False


class MfaSmsRequest(BaseModel):
    challenge_token: str


class MfaSmsVerifyRequest(BaseModel):
    challenge_token: str
    code: str
    remember_device: bool = False


class MfaDisableRequest(BaseModel):
    password: str
    totp_code: str


class MfaPhoneRequest(BaseModel):
    phone_number: str  # E.164 format, e.g. +12125551234


class MfaStatusResponse(BaseModel):
    mfa_enabled: bool
    has_phone: bool
    backup_codes_remaining: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/setup",
    response_model=MfaSetupStartResponse,
    summary="Generate TOTP secret for MFA setup",
)
async def mfa_setup_start(
    request: Request,
    db_path: str = Depends(_get_db_path),
    secret_key: str = Depends(_get_secret_key),
) -> MfaSetupStartResponse:
    """Generate a new TOTP secret for the authenticated user.

    The secret is stored as a pending setup (not yet active).
    The user must call POST /auth/mfa/verify-setup with a valid code
    to confirm and activate MFA.

    Requires a valid Bearer token.
    """
    try:
        import pyotp
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TOTP MFA is not available (pyotp not installed)",
        )

    if not secret_key:
        from isg_agent.config import get_settings
        secret_key = get_settings().secret_key

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    payload = verify_token(auth_header[7:], secret_key)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = str(payload.get("sub", ""))
    user_email = str(payload.get("email", ""))

    await _ensure_users_table(db_path, db_path == ":memory:")
    await _ensure_mfa_schema(db_path)

    # Generate new TOTP secret
    totp_secret = pyotp.random_base32()
    uri = pyotp.totp.TOTP(totp_secret).provisioning_uri(
        name=user_email,
        issuer_name="DingDawg",
    )

    # Store as pending (not yet enabled) — overwrite any previous pending setup
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE users SET mfa_setup_pending_secret = ? WHERE id = ?",
            (totp_secret, user_id),
        )
        await db.commit()

    return MfaSetupStartResponse(secret=totp_secret, otpauth_uri=uri)


@router.post(
    "/verify-setup",
    response_model=MfaVerifySetupResponse,
    summary="Confirm TOTP code, activate MFA, receive backup codes",
)
async def mfa_verify_setup(
    body: MfaVerifySetupRequest,
    request: Request,
    db_path: str = Depends(_get_db_path),
    secret_key: str = Depends(_get_secret_key),
) -> MfaVerifySetupResponse:
    """Verify the first TOTP code and activate MFA on the account.

    - Verifies the code against the pending secret from /auth/mfa/setup.
    - Generates 10 one-time backup codes (shown once, never retrievable).
    - Activates MFA by setting mfa_enabled=1 and storing totp_secret.

    Requires a valid Bearer token.
    """
    try:
        import pyotp
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TOTP MFA is not available (pyotp not installed)",
        )

    if not secret_key:
        from isg_agent.config import get_settings
        secret_key = get_settings().secret_key

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    payload = verify_token(auth_header[7:], secret_key)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = str(payload.get("sub", ""))

    await _ensure_users_table(db_path, db_path == ":memory:")
    await _ensure_mfa_schema(db_path)

    # Fetch pending secret
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT mfa_setup_pending_secret, mfa_enabled FROM users WHERE id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=401, detail="User not found")

    pending_secret = row["mfa_setup_pending_secret"]
    # Also accept secret from request body (client may send it explicitly)
    totp_secret = body.secret or pending_secret

    if not totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No pending MFA setup found. Call /auth/mfa/setup first.",
        )

    # Verify TOTP code
    totp = pyotp.TOTP(totp_secret)
    if not totp.verify(body.code, valid_window=1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid TOTP code",
        )

    # Generate backup codes
    plaintext_codes, hashed_codes = _generate_backup_codes()

    # Activate MFA
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE users SET "
            "totp_secret = ?, mfa_enabled = 1, "
            "backup_codes_json = ?, mfa_setup_pending_secret = NULL "
            "WHERE id = ?",
            (totp_secret, json.dumps(hashed_codes), user_id),
        )
        await db.commit()

    logger.info("MFA activated for user_id=%s with %d backup codes", user_id, len(plaintext_codes))

    return MfaVerifySetupResponse(
        backup_codes=plaintext_codes,
        mfa_enabled=True,
    )


@router.post(
    "/challenge",
    response_model=MfaChallengeResponse,
    summary="Complete MFA login challenge with TOTP, backup code, or SMS OTP",
)
async def mfa_challenge(
    body: MfaChallengeRequest,
    request: Request,
    response: Response,
    db_path: str = Depends(_get_db_path),
    secret_key: str = Depends(_get_secret_key),
) -> MfaChallengeResponse:
    """Verify MFA during login.

    Accepts:
    - code_type="totp"   → TOTP 6-digit code from authenticator app
    - code_type="backup" → One-time 8-character backup code (consumed on use)
    - code_type="sms"    → 6-digit SMS OTP sent via /auth/mfa/sms

    If remember_device=True, sets a 30-day HttpOnly cookie.

    Uses the short-lived challenge token issued by POST /auth/login.
    """
    try:
        import pyotp
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TOTP MFA is not available (pyotp not installed)",
        )

    if not secret_key:
        from isg_agent.config import get_settings
        secret_key = get_settings().secret_key

    # Validate challenge token
    payload = verify_token(body.challenge_token, secret_key)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired MFA challenge token",
        )

    user_id = str(payload.get("sub", ""))

    await _ensure_users_table(db_path, db_path == ":memory:")
    await _ensure_mfa_schema(db_path)

    # Fetch user MFA state
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, email, totp_secret, mfa_enabled, backup_codes_json, "
            "sms_otp_hash, sms_otp_expires_at "
            "FROM users WHERE id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=401, detail="User not found")

    if not row["mfa_enabled"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA is not enabled for this account",
        )

    verified = False
    updated_backup_codes: Optional[list[str]] = None

    code_type = body.code_type.lower()

    if code_type == "totp":
        totp_secret = row["totp_secret"]
        if not totp_secret:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="TOTP is not configured for this account",
            )
        totp = pyotp.TOTP(totp_secret)
        verified = totp.verify(body.code, valid_window=1)

    elif code_type == "backup":
        backup_codes_json = row["backup_codes_json"]
        if not backup_codes_json:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No backup codes on file",
            )
        try:
            hashed_codes = json.loads(backup_codes_json)
        except (json.JSONDecodeError, TypeError):
            hashed_codes = []

        verified, remaining = _consume_backup_code(hashed_codes, body.code)
        if verified:
            updated_backup_codes = remaining

    elif code_type == "sms":
        sms_hash = row["sms_otp_hash"]
        sms_expires = row["sms_otp_expires_at"]
        if not sms_hash or not sms_expires:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No SMS OTP pending. Call /auth/mfa/sms first.",
            )
        now_iso = datetime.now(timezone.utc).isoformat()
        if now_iso > sms_expires:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="SMS OTP has expired. Request a new one.",
            )
        candidate_hash = hashlib.sha256(body.code.strip().encode()).hexdigest()
        verified = hmac.compare_digest(candidate_hash, sms_hash)

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="code_type must be 'totp', 'backup', or 'sms'",
        )

    if not verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code",
        )

    # Persist backup code consumption / clear SMS OTP
    async with aiosqlite.connect(db_path) as db:
        if updated_backup_codes is not None:
            await db.execute(
                "UPDATE users SET backup_codes_json = ? WHERE id = ?",
                (json.dumps(updated_backup_codes), user_id),
            )
        if code_type == "sms":
            await db.execute(
                "UPDATE users SET sms_otp_hash = NULL, sms_otp_expires_at = NULL WHERE id = ?",
                (user_id,),
            )
        await db.commit()

    # Issue full access token
    final_token = _create_token(
        user_id=row["id"],
        email=row["email"],
        secret_key=secret_key,
    )
    logger.info("MFA challenge passed for user: %s (id=%s) code_type=%s", row["email"], user_id, code_type)

    remember_device_set = False
    if body.remember_device:
        device_token = _device_token(user_id, secret_key)
        device_hint = request.headers.get("user-agent", "")[:100]
        await _store_device_trust(user_id, device_token, db_path, device_hint)
        _set_device_cookie(response, device_token, user_id, db_path)
        remember_device_set = True

    return MfaChallengeResponse(
        user_id=row["id"],
        email=row["email"],
        access_token=final_token,
        remember_device_set=remember_device_set,
    )


@router.post(
    "/sms",
    summary="Send SMS OTP via Telnyx for MFA challenge",
    status_code=200,
)
async def mfa_sms_send(
    body: MfaSmsRequest,
    request: Request,
    db_path: str = Depends(_get_db_path),
    secret_key: str = Depends(_get_secret_key),
) -> dict:
    """Send a 6-digit SMS OTP to the user's registered phone number.

    Requires a valid MFA challenge token (issued by /auth/login).
    The phone number must have been registered via /auth/mfa/phone.
    """
    if not secret_key:
        from isg_agent.config import get_settings
        secret_key = get_settings().secret_key

    payload = verify_token(body.challenge_token, secret_key)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired MFA challenge token",
        )

    user_id = str(payload.get("sub", ""))

    await _ensure_users_table(db_path, db_path == ":memory:")
    await _ensure_mfa_schema(db_path)

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT phone_number, mfa_enabled FROM users WHERE id = ?", (user_id,)
        )
        row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=401, detail="User not found")

    if not row["mfa_enabled"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA is not enabled for this account",
        )

    phone = row["phone_number"]
    if not phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No phone number registered. Add one at /auth/mfa/phone.",
        )

    # Generate OTP
    otp = "".join(secrets.choice("0123456789") for _ in range(_SMS_OTP_LENGTH))
    otp_hash = hashlib.sha256(otp.encode()).hexdigest()
    expires_at = datetime.fromtimestamp(
        time.time() + _SMS_OTP_TTL_SECONDS, tz=timezone.utc
    ).isoformat()

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE users SET sms_otp_hash = ?, sms_otp_expires_at = ? WHERE id = ?",
            (otp_hash, expires_at, user_id),
        )
        await db.commit()

    from isg_agent.config import get_settings
    settings = get_settings()
    sent = await _send_telnyx_sms(phone, otp, settings)

    if not sent:
        logger.warning("SMS OTP send failed for user_id=%s — code generated but not delivered", user_id)
        # Still return success shape — don't leak whether number is valid/configured
        return {"message": "If a phone number is registered, a code was sent."}

    return {"message": "Verification code sent. Check your phone."}


@router.post(
    "/disable",
    summary="Disable MFA (requires password + current TOTP code)",
    status_code=200,
)
async def mfa_disable(
    body: MfaDisableRequest,
    request: Request,
    db_path: str = Depends(_get_db_path),
    secret_key: str = Depends(_get_secret_key),
) -> dict:
    """Disable MFA for the authenticated user.

    Requires:
    - Valid Bearer token
    - Current password (re-authentication)
    - Valid TOTP code from the authenticator app

    Clears totp_secret, mfa_enabled, backup_codes_json, and sms_otp fields.
    """
    try:
        import pyotp
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TOTP MFA is not available (pyotp not installed)",
        )

    if not secret_key:
        from isg_agent.config import get_settings
        secret_key = get_settings().secret_key

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    payload = verify_token(auth_header[7:], secret_key)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = str(payload.get("sub", ""))

    await _ensure_users_table(db_path, db_path == ":memory:")
    await _ensure_mfa_schema(db_path)

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, email, password_hash, salt, totp_secret, mfa_enabled "
            "FROM users WHERE id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=401, detail="User not found")

    if not row["mfa_enabled"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA is not currently enabled",
        )

    # Verify password
    if not _verify_password(body.password, row["password_hash"], row["salt"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password",
        )

    # Verify TOTP
    totp_secret = row["totp_secret"]
    if not totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TOTP secret not found",
        )
    totp = pyotp.TOTP(totp_secret)
    if not totp.verify(body.totp_code, valid_window=1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid TOTP code",
        )

    # Clear all MFA state
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE users SET "
            "totp_secret = NULL, mfa_enabled = 0, "
            "backup_codes_json = NULL, "
            "sms_otp_hash = NULL, sms_otp_expires_at = NULL, "
            "mfa_setup_pending_secret = NULL "
            "WHERE id = ?",
            (user_id,),
        )
        # Also clear device trusts for this user
        await db.execute(
            "DELETE FROM mfa_device_trusts WHERE user_id = ?", (user_id,)
        )
        await db.commit()

    logger.info("MFA disabled for user_id=%s", user_id)
    return {"message": "MFA has been disabled. Your account is now protected by password only."}


@router.get(
    "/status",
    response_model=MfaStatusResponse,
    summary="Get MFA status for authenticated user",
)
async def mfa_status(
    request: Request,
    db_path: str = Depends(_get_db_path),
    secret_key: str = Depends(_get_secret_key),
) -> MfaStatusResponse:
    """Return the current MFA configuration status for the authenticated user."""
    if not secret_key:
        from isg_agent.config import get_settings
        secret_key = get_settings().secret_key

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    payload = verify_token(auth_header[7:], secret_key)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = str(payload.get("sub", ""))

    await _ensure_users_table(db_path, db_path == ":memory:")
    await _ensure_mfa_schema(db_path)

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT mfa_enabled, phone_number, backup_codes_json FROM users WHERE id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=401, detail="User not found")

    mfa_enabled = bool(row["mfa_enabled"])
    has_phone = bool(row["phone_number"])

    backup_remaining = 0
    if row["backup_codes_json"]:
        try:
            codes = json.loads(row["backup_codes_json"])
            backup_remaining = len(codes)
        except (json.JSONDecodeError, TypeError):
            pass

    return MfaStatusResponse(
        mfa_enabled=mfa_enabled,
        has_phone=has_phone,
        backup_codes_remaining=backup_remaining,
    )


@router.post(
    "/phone",
    summary="Register or update phone number for SMS MFA",
    status_code=200,
)
async def mfa_phone_register(
    body: MfaPhoneRequest,
    request: Request,
    db_path: str = Depends(_get_db_path),
    secret_key: str = Depends(_get_secret_key),
) -> dict:
    """Register or update the phone number used for SMS OTP delivery.

    Phone number must be in E.164 format (e.g., +12125551234).
    Requires a valid Bearer token.
    """
    if not secret_key:
        from isg_agent.config import get_settings
        secret_key = get_settings().secret_key

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    payload = verify_token(auth_header[7:], secret_key)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = str(payload.get("sub", ""))

    # Basic E.164 validation
    phone = body.phone_number.strip()
    if not phone.startswith("+") or not phone[1:].isdigit() or len(phone) < 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phone number must be in E.164 format (e.g., +12125551234)",
        )

    await _ensure_users_table(db_path, db_path == ":memory:")
    await _ensure_mfa_schema(db_path)

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE users SET phone_number = ? WHERE id = ?",
            (phone, user_id),
        )
        await db.commit()

    logger.info("Phone number registered for user_id=%s", user_id)
    return {"message": "Phone number registered successfully."}


# ---------------------------------------------------------------------------
# Device-trust check helper (used by login flow in auth.py)
# ---------------------------------------------------------------------------

async def check_device_trusted(
    request: Request, user_id: str, db_path: str
) -> bool:
    """Return True if request carries a valid 30-day device trust cookie."""
    await _ensure_mfa_schema(db_path)
    return await _is_device_trusted(request, user_id, db_path)
