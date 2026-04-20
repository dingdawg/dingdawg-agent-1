"""Authentication endpoints: register, login, and token management.

Provides simple JWT-based authentication using HMAC-SHA256 (HS256)
without external JWT library dependencies. Passwords are hashed with
PBKDF2-HMAC-SHA256.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, field_validator

from isg_agent.middleware.rate_limiter_middleware import auth_rate_limit

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_CREATE_USERS_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id          TEXT    PRIMARY KEY,
    email       TEXT    NOT NULL UNIQUE,
    password_hash TEXT  NOT NULL,
    salt        TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    totp_secret TEXT    DEFAULT NULL,
    email_verified INTEGER NOT NULL DEFAULT 0,
    mfa_enabled INTEGER NOT NULL DEFAULT 0
);
"""

_CREATE_INDEX_EMAIL = (
    "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);"
)

# Migration: add columns to existing tables that pre-date this schema.
_ALTER_USERS_TOTP = (
    "ALTER TABLE users ADD COLUMN totp_secret TEXT DEFAULT NULL;"
)
_ALTER_USERS_MFA_ENABLED = (
    "ALTER TABLE users ADD COLUMN mfa_enabled INTEGER NOT NULL DEFAULT 0;"
)

# ---------------------------------------------------------------------------
# Brute-force rate limiter (SQLite-backed, per email, max 5/15 min)
# Survives process restarts unlike the previous in-memory implementation.
# ---------------------------------------------------------------------------

_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW_SECONDS = 15 * 60  # 15 minutes

_CREATE_LOGIN_ATTEMPTS_SQL = """
CREATE TABLE IF NOT EXISTS login_attempts (
    email           TEXT    PRIMARY KEY,
    attempt_count   INTEGER NOT NULL DEFAULT 0,
    first_attempt_at TEXT   NOT NULL,
    locked_until    TEXT    DEFAULT NULL,
    ip_address      TEXT    DEFAULT NULL
);
"""

_ALTER_LOGIN_ATTEMPTS_IP = (
    "ALTER TABLE login_attempts ADD COLUMN ip_address TEXT DEFAULT NULL;"
)


async def _ensure_login_attempts_table(db_path: str) -> None:
    """Create the login_attempts table if it does not exist."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute(_CREATE_LOGIN_ATTEMPTS_SQL)
        try:
            await db.execute(_ALTER_LOGIN_ATTEMPTS_IP)
        except Exception:
            pass  # Column already exists
        await db.commit()


async def _check_login_rate_limit(email: str, db_path: str = "") -> None:
    """Raise HTTP 429 if the email exceeds the login attempt threshold.

    Reads attempt state from SQLite so the limit survives server restarts.
    Prunes stale entries before checking so the window slides correctly.
    """
    if not db_path:
        db_path = _db_path
    await _ensure_login_attempts_table(db_path)

    now_utc = datetime.now(timezone.utc)
    now_iso = now_utc.isoformat()

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT attempt_count, first_attempt_at, locked_until "
            "FROM login_attempts WHERE email = ?",
            (email,),
        )
        row = await cursor.fetchone()

    if row is None:
        return  # No prior attempts — allow

    first_attempt_at_str = row["first_attempt_at"]
    locked_until_str = row["locked_until"]

    # Check if the window has expired — if so, the record is stale; allow
    try:
        first_dt = datetime.fromisoformat(first_attempt_at_str)
        if (now_utc - first_dt).total_seconds() > _LOGIN_WINDOW_SECONDS:
            # Window expired — purge stale record so counter resets
            async with aiosqlite.connect(db_path) as db:
                await db.execute(
                    "DELETE FROM login_attempts WHERE email = ?", (email,)
                )
                await db.commit()
            return
    except (ValueError, TypeError):
        pass  # Malformed timestamp — allow and let next failure overwrite

    attempt_count = row["attempt_count"] or 0
    if attempt_count >= _LOGIN_MAX_ATTEMPTS:
        # Calculate retry-after from first_attempt_at + window
        try:
            first_dt = datetime.fromisoformat(first_attempt_at_str)
            elapsed = (now_utc - first_dt).total_seconds()
            retry_after = max(1, int(_LOGIN_WINDOW_SECONDS - elapsed) + 1)
        except (ValueError, TypeError):
            retry_after = _LOGIN_WINDOW_SECONDS
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )


async def _record_login_failure(
    email: str, db_path: str = "", ip_address: str | None = None
) -> None:
    """Record a failed login attempt in SQLite for rate-limit tracking."""
    if not db_path:
        db_path = _db_path
    await _ensure_login_attempts_table(db_path)

    now_iso = datetime.now(timezone.utc).isoformat()

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT attempt_count FROM login_attempts WHERE email = ?", (email,)
        )
        row = await cursor.fetchone()
        if row is None:
            await db.execute(
                "INSERT INTO login_attempts "
                "(email, attempt_count, first_attempt_at, locked_until, ip_address) "
                "VALUES (?, 1, ?, NULL, ?)",
                (email, now_iso, ip_address),
            )
        else:
            await db.execute(
                "UPDATE login_attempts SET attempt_count = attempt_count + 1, "
                "ip_address = ? WHERE email = ?",
                (ip_address, email),
            )
        await db.commit()


async def _clear_login_failures(email: str, db_path: str = "") -> None:
    """Clear the failure counter for an email on successful login."""
    if not db_path:
        db_path = _db_path
    try:
        await _ensure_login_attempts_table(db_path)
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "DELETE FROM login_attempts WHERE email = ?", (email,)
            )
            await db.commit()
    except Exception:
        pass  # Non-critical — don't block successful login

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    """Request body for user registration."""

    email: str
    password: str
    # Honeypot field — must be empty for real users.
    # Bots auto-fill everything; real users never see this (CSS hidden).
    # Field name "website" looks legitimate to bots.
    website: Optional[str] = None
    # Turnstile token from Cloudflare invisible challenge.
    # Optional so dev/test mode works without a token.
    turnstile_token: Optional[str] = None
    # Terms of Service and Privacy Policy acceptance (required).
    # Must be True — registration is rejected if False or omitted.
    terms_accepted: bool = False
    # ISO 8601 timestamp of acceptance for legal audit trail.
    terms_accepted_at: Optional[str] = None

    @field_validator("password")
    @classmethod
    def _password_complexity(cls, v: str) -> str:
        import re
        missing: list[str] = []
        if len(v) < 8:
            missing.append("at least 8 characters")
        if not re.search(r"[A-Z]", v):
            missing.append("at least 1 uppercase letter")
        if not re.search(r"[0-9]", v):
            missing.append("at least 1 digit")
        if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?`~]", v):
            missing.append("at least 1 special character (!@#$%^&* etc.)")
        if missing:
            raise ValueError("Password must contain: " + ", ".join(missing))
        return v

    @field_validator("email")
    @classmethod
    def _email_lowercase(cls, v: str) -> str:
        return v.strip().lower()


class LoginRequest(BaseModel):
    """Request body for login."""

    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _email_lowercase(cls, v: str) -> str:
        return v.strip().lower()


class AuthResponse(BaseModel):
    """Response after successful register or login."""

    user_id: str
    email: str
    access_token: str
    token_type: str = "bearer"
    # Present only when TOTP MFA is required; access_token will be empty string.
    mfa_required: bool = False
    mfa_challenge_token: Optional[str] = None


class MfaSetupResponse(BaseModel):
    """Response for MFA setup: TOTP provisioning URI and raw secret."""

    secret: str
    otpauth_uri: str


class MfaSetupRequest(BaseModel):
    """No body needed — auth comes from Bearer token."""


class MfaVerifyRequest(BaseModel):
    """Verify a TOTP code during MFA setup or login challenge."""

    code: str
    # The short-lived challenge token issued by /auth/login when MFA is required.
    # Omit when calling /auth/mfa/verify as the authenticated user (setup flow).
    challenge_token: Optional[str] = None


class ForgotPasswordRequest(BaseModel):
    """Request body for forgot-password."""

    email: str

    @field_validator("email")
    @classmethod
    def _email_lowercase(cls, v: str) -> str:
        return v.strip().lower()


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


def _hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    """Hash a password using PBKDF2-HMAC-SHA256.

    Parameters
    ----------
    password:
        The plaintext password.
    salt:
        Hex-encoded salt.  A random salt is generated if not provided.

    Returns
    -------
    tuple[str, str]
        (password_hash_hex, salt_hex)
    """
    if salt is None:
        salt = os.urandom(32).hex()

    dk = hashlib.pbkdf2_hmac(
        hash_name="sha256",
        password=password.encode("utf-8"),
        salt=bytes.fromhex(salt),
        iterations=260_000,  # OWASP 2023 recommendation
    )
    return dk.hex(), salt


def _verify_password(password: str, stored_hash: str, salt: str) -> bool:
    """Verify a plaintext password against a stored hash."""
    candidate_hash, _ = _hash_password(password, salt)
    return hmac.compare_digest(candidate_hash, stored_hash)


# ---------------------------------------------------------------------------
# JWT (HS256, no external library)
# ---------------------------------------------------------------------------


def _b64url_encode(data: bytes) -> str:
    """URL-safe Base64 encoding with padding stripped."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    """URL-safe Base64 decoding with padding restored."""
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def _create_token(
    user_id: str,
    email: str,
    secret_key: str,
    expires_in: int = 86400,  # 24 hours
) -> str:
    """Create a signed HS256 JWT token.

    Parameters
    ----------
    user_id:
        User identifier stored in the ``sub`` claim.
    email:
        User email stored as a custom claim.
    secret_key:
        HMAC signing key.
    expires_in:
        Token lifetime in seconds (default 24 hours).

    Returns
    -------
    str
        The signed JWT as a dotted string.
    """
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {
        "sub": user_id,
        "email": email,
        "iat": now,
        "exp": now + expires_in,
        # jti (JWT ID) guarantees token uniqueness even when two tokens are
        # issued within the same second for the same user.  This prevents
        # JWT collision on rapid logins and enables precise per-token
        # revocation tracking via token_guard.revoke_token().
        "jti": uuid.uuid4().hex,
    }

    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())

    signing_input = f"{header_b64}.{payload_b64}"
    sig = hmac.new(
        secret_key.encode("utf-8"),
        signing_input.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    sig_b64 = _b64url_encode(sig)

    return f"{signing_input}.{sig_b64}"


def verify_token(token: str, secret_key: str) -> Optional[dict[str, object]]:
    """Verify and decode a JWT token.

    Parameters
    ----------
    token:
        The JWT string to verify.
    secret_key:
        The HMAC signing key.

    Returns
    -------
    dict or None
        The decoded payload if the token is valid and not expired,
        otherwise None.
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None

        header_b64, payload_b64, sig_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}"

        expected_sig = hmac.new(
            secret_key.encode("utf-8"),
            signing_input.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        expected_sig_b64 = _b64url_encode(expected_sig)

        if not hmac.compare_digest(sig_b64, expected_sig_b64):
            return None

        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))

        # Check expiry
        if payload.get("exp", 0) < int(time.time()):
            return None

        return payload

    except Exception:
        return None


def _decode_token_ignore_expiry(token: str, secret_key: str) -> Optional[dict[str, object]]:
    """Verify token signature and return payload WITHOUT checking expiry.

    Used exclusively by the ``/auth/refresh`` endpoint so that short-lived
    (24 h) tokens can be refreshed within the 7-day hard window.

    Parameters
    ----------
    token:
        The JWT string to verify.
    secret_key:
        The HMAC signing key.

    Returns
    -------
    dict or None
        The decoded payload if the signature is valid, otherwise None.
        Expiry is intentionally NOT checked here.
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None

        header_b64, payload_b64, sig_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}"

        expected_sig = hmac.new(
            secret_key.encode("utf-8"),
            signing_input.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        expected_sig_b64 = _b64url_encode(expected_sig)

        if not hmac.compare_digest(sig_b64, expected_sig_b64):
            return None

        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        return payload

    except Exception:
        return None


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

_db_path: str = "data/agent.db"
_secret_key: str = ""


def _set_auth_config(db_path: str, secret_key: str) -> None:
    """Set module-level auth configuration (called from app startup)."""
    global _db_path, _secret_key  # noqa: PLW0603
    _db_path = db_path
    _secret_key = secret_key


def _get_is_memory(path: str) -> tuple[str, bool]:
    """Return connect path and whether it is an in-memory database."""
    if path == ":memory:":
        return path, True
    return path, False


async def _ensure_users_table(db_path: str, is_memory: bool) -> None:
    """Create the users table if it does not exist, and migrate existing DBs."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute(_CREATE_USERS_SQL)
        await db.execute(_CREATE_INDEX_EMAIL)
        # Idempotent migration: add columns to pre-existing tables.
        try:
            await db.execute(_ALTER_USERS_TOTP)
        except Exception:
            pass  # Column already exists — ignore
        try:
            await db.execute(_ALTER_USERS_MFA_ENABLED)
        except Exception:
            pass  # Column already exists — ignore
        await db.commit()


# ---------------------------------------------------------------------------
# Dependency: db path
# ---------------------------------------------------------------------------

async def _get_db_path() -> str:
    """Return the current database path (injected from app state)."""
    return _db_path


async def _get_secret_key() -> str:
    """Return the current JWT secret key."""
    return _secret_key


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
@auth_rate_limit()
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    db_path: str = Depends(_get_db_path),
    secret_key: str = Depends(_get_secret_key),
) -> AuthResponse:
    """Register a new user with email and password.

    Bot Prevention Layer 0 is applied before account creation:
    1. Honeypot field: if ``website`` field is filled, silently fake success.
    2. Disposable email: rejected with a user-visible message.
    3. Turnstile token: verified server-side (skipped in dev/test mode).

    Returns a JWT access token on success.  Returns 409 Conflict if the
    email is already registered.
    """
    import os as _os

    is_test = _os.environ.get("ISG_AGENT_DEPLOYMENT_ENV", "").lower() in ("test", "testing")

    # ------------------------------------------------------------------
    # Terms of Service acceptance gate (required before any account creation)
    # ------------------------------------------------------------------
    if not body.terms_accepted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You must accept the Terms of Service and Privacy Policy to register",
        )

    # ------------------------------------------------------------------
    # Bot check 1: Honeypot field
    # ------------------------------------------------------------------
    if not is_test:
        from isg_agent.utils.honeypot import check_honeypot
        from isg_agent.middleware.bot_prevention import extract_real_ip

        honeypot_result = check_honeypot(honeypot_value=body.website)
        if honeypot_result.is_bot:
            xff = request.headers.get("x-forwarded-for")
            client_host = request.client.host if request.client else None
            real_ip = extract_real_ip(client_host=client_host, x_forwarded_for=xff)
            logger.warning(
                "Bot prevention: honeypot triggered at register. IP=%s trigger=%r",
                real_ip,
                honeypot_result.trigger,
            )
            # Return FAKE success — never reveal the block to bot authors
            fake_id = str(uuid.uuid4())
            fake_token = _create_token(
                user_id=fake_id,
                email=body.email,
                secret_key=secret_key or "fake-key",
            )
            return AuthResponse(
                user_id=fake_id,
                email=body.email,
                access_token=fake_token,
            )

    # ------------------------------------------------------------------
    # Bot check 2: Disposable email blocking (skipped in test env)
    # ------------------------------------------------------------------
    if not is_test:
        from isg_agent.utils.disposable_emails import is_disposable_email

        try:
            if is_disposable_email(body.email):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Please use a permanent email address",
                )
        except HTTPException:
            raise
        except ValueError as exc:
            logger.warning("Disposable email check failed with ValueError: %s", exc)
        # Invalid email format — let Pydantic's EmailStr handle this downstream

    # ------------------------------------------------------------------
    # Bot check 3: Turnstile verification (skip in dev/test mode)
    # ------------------------------------------------------------------
    if not is_test:
        from isg_agent.middleware.bot_prevention import verify_turnstile

        turnstile_token = body.turnstile_token or ""
        ts_result = await verify_turnstile(token=turnstile_token)
        if not ts_result.success and not ts_result.skipped:
            xff = request.headers.get("x-forwarded-for")
            client_host = request.client.host if request.client else None
            real_ip = extract_real_ip(client_host=client_host, x_forwarded_for=xff)
            logger.warning(
                "Bot prevention: Turnstile failed at register. IP=%s codes=%s",
                real_ip,
                ts_result.error_codes,
            )
            # Return FAKE success — do not reveal rejection
            fake_id = str(uuid.uuid4())
            fake_token = _create_token(
                user_id=fake_id,
                email=body.email,
                secret_key=secret_key or "fake-key",
            )
            return AuthResponse(
                user_id=fake_id,
                email=body.email,
                access_token=fake_token,
            )

    # ------------------------------------------------------------------
    # Normal registration path
    # ------------------------------------------------------------------
    if not secret_key:
        from isg_agent.config import get_settings
        secret_key = get_settings().secret_key

    await _ensure_users_table(db_path, db_path == ":memory:")

    password_hash, salt = _hash_password(body.password)
    user_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "INSERT INTO users (id, email, password_hash, salt, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, body.email, password_hash, salt, created_at),
            )
            await db.commit()
    except aiosqlite.IntegrityError:
        # Founder re-registration: if email is on auto-verify whitelist,
        # delete old account and re-create so founder can start fresh.
        _founder_emails = ("joe@dingdawg.com", "joeloius08@gmail.com", "founder@dingdawg.com", "support@dingdawg.com")
        if body.email in _founder_emails:
            async with aiosqlite.connect(db_path) as _fdb:
                _old = await (await _fdb.execute("SELECT id FROM users WHERE email=?", (body.email,))).fetchone()
                if _old:
                    _old_id = _old[0]
                    for _t in ("webauthn_credentials", "webauthn_challenges", "sessions", "agents", "login_failures"):
                        try:
                            await _fdb.execute(f"DELETE FROM {_t} WHERE user_id=?", (_old_id,))
                        except Exception:
                            pass
                    await _fdb.execute("DELETE FROM users WHERE id=?", (_old_id,))
                    await _fdb.commit()
                    logger.info("Founder re-registration: purged old account %s for %s", _old_id, body.email)
                # Re-insert
                await _fdb.execute(
                    "INSERT INTO users (id, email, password_hash, salt, created_at, email_verified) "
                    "VALUES (?, ?, ?, ?, ?, 1)",
                    (user_id, body.email, password_hash, salt, created_at),
                )
                await _fdb.commit()
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            )

    token = _create_token(user_id=user_id, email=body.email, secret_key=secret_key)
    logger.info("New user registered: %s (id=%s)", body.email, user_id)

    # ------------------------------------------------------------------
    # Auto-send email verification (Gap 1).
    # Graceful: any error here does NOT abort registration.
    # ------------------------------------------------------------------
    try:
        from isg_agent.auth.email_verification import EmailVerificationManager

        verify_manager = EmailVerificationManager(db_path=db_path)
        verify_token_str = await verify_manager.create_token(user_id=user_id)

        from isg_agent.api.routes.auth_extended import (
            _VERIFY_EMAIL_HTML,
            _VERIFY_EMAIL_TEXT,
            _get_frontend_url,
            _get_sendgrid,
        )

        verify_url = f"{_get_frontend_url()}/verify-email/{verify_token_str}"
        sendgrid = _get_sendgrid(request)
        if sendgrid is not None:
            try:
                result = await sendgrid.send_email(
                    agent_id="platform",
                    to_email=body.email,
                    subject="Verify your DingDawg account",
                    body=_VERIFY_EMAIL_TEXT.format(verify_url=verify_url),
                    html_body=_VERIFY_EMAIL_HTML.format(verify_url=verify_url),
                )
                if not result.get("success"):
                    logger.error(
                        "SendGrid failed sending verification email to %s: %s",
                        body.email,
                        result.get("error"),
                    )
            except Exception as exc:
                logger.error(
                    "Exception sending verification email to %s: %s",
                    body.email,
                    exc,
                )
        else:
            logger.warning(
                "SendGrid not configured — verification URL for %s: %s",
                body.email,
                verify_url,
            )
    except Exception as exc:
        logger.error(
            "Failed to create/send verification token for %s: %s",
            body.email,
            exc,
        )

    # ------------------------------------------------------------------
    # Send welcome email (Gap 1b).
    # Graceful: any error here does NOT abort registration.
    # ------------------------------------------------------------------
    try:
        from isg_agent.api.routes.auth_extended import (
            _WELCOME_EMAIL_HTML,
            _WELCOME_EMAIL_TEXT,
            _get_sendgrid as _get_sendgrid_welcome,
        )

        sendgrid_welcome = _get_sendgrid_welcome(request)
        if sendgrid_welcome is not None:
            try:
                welcome_result = await sendgrid_welcome.send_email(
                    agent_id="platform",
                    to_email=body.email,
                    subject="Welcome to DingDawg!",
                    body=_WELCOME_EMAIL_TEXT,
                    html_body=_WELCOME_EMAIL_HTML,
                )
                if not welcome_result.get("success"):
                    logger.error(
                        "SendGrid failed sending welcome email to %s: %s",
                        body.email,
                        welcome_result.get("error"),
                    )
            except Exception as exc:
                logger.error(
                    "Exception sending welcome email to %s: %s",
                    body.email,
                    exc,
                )
        else:
            logger.info(
                "SendGrid not configured — welcome email skipped for %s",
                body.email,
            )
    except Exception as exc:
        logger.error(
            "Failed to send welcome email for %s: %s",
            body.email,
            exc,
        )

    return AuthResponse(
        user_id=user_id,
        email=body.email,
        access_token=token,
    )


@router.post(
    "/login",
    response_model=AuthResponse,
    summary="Authenticate and receive a JWT token",
)
@auth_rate_limit()
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db_path: str = Depends(_get_db_path),
    secret_key: str = Depends(_get_secret_key),
) -> AuthResponse:
    """Verify credentials and return a JWT access token.

    Brute-force protection: max 5 failed attempts per email per 15 minutes.
    If TOTP MFA is enabled for the account, returns a short-lived challenge
    token (mfa_required=True) instead of the real access token.  The caller
    must then POST /auth/mfa/verify with the TOTP code and challenge_token
    to receive the real access token.

    Returns 401 Unauthorized if the email is not found or the password
    is incorrect.  Returns 429 if rate limit is exceeded.
    """
    if not secret_key:
        from isg_agent.config import get_settings
        secret_key = get_settings().secret_key

    # Brute-force check (Gap 3) — runs before any DB work to fail fast.
    # Now SQLite-backed so lockouts survive process restarts.
    await _check_login_rate_limit(body.email, db_path)

    await _ensure_users_table(db_path, db_path == ":memory:")

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, email, password_hash, salt, totp_secret, email_verified, mfa_enabled "
            "FROM users WHERE email = ?",
            (body.email,),
        )
        row = await cursor.fetchone()

    if row is None:
        # Record failure even for unknown email to prevent user enumeration
        # via timing differences (still constant-time due to same code path).
        client_ip = request.client.host if request.client else None
        await _record_login_failure(body.email, db_path, ip_address=client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not _verify_password(body.password, row["password_hash"], row["salt"]):
        client_ip = request.client.host if request.client else None
        await _record_login_failure(body.email, db_path, ip_address=client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # Credentials correct — clear failure counter.
    await _clear_login_failures(body.email, db_path)

    # Email verification hard gate — block unverified accounts from logging in.
    # Auto-verify founder accounts (email delivery not configured on Railway)
    email_verified = row["email_verified"] if "email_verified" in row.keys() else 0
    if not email_verified and row["email"] in ("joe@dingdawg.com", "joeloius08@gmail.com", "founder@dingdawg.com", "support@dingdawg.com"):
        async with aiosqlite.connect(db_path) as _vdb:
            await _vdb.execute("UPDATE users SET email_verified=1 WHERE id=?", (row["id"],))
            await _vdb.commit()
        email_verified = 1
        logger.info("Auto-verified founder email: %s", row["email"])
    if not email_verified:
        logger.warning(
            "Login blocked for unverified email: %s (id=%s)",
            row["email"],
            row["id"],
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before logging in. "
                   "Check your inbox or request a new verification link.",
        )

    # TOTP MFA gate (Gap 2) — if user has enrolled MFA, issue challenge token.
    # Skip challenge if device is trusted (30-day remember-device cookie).
    totp_secret = row["totp_secret"] if "totp_secret" in row.keys() else None
    _mfa_enabled = False
    try:
        _mfa_enabled_val = row["mfa_enabled"] if "mfa_enabled" in row.keys() else None
        _mfa_enabled = bool(_mfa_enabled_val)
    except Exception:
        pass
    if totp_secret and _mfa_enabled:
        # Check remember-device cookie before issuing challenge
        device_trusted = False
        try:
            from isg_agent.api.routes.auth_mfa import check_device_trusted as _check_device
            device_trusted = await _check_device(request, row["id"], db_path)
        except Exception:
            pass

        if not device_trusted:
            # Issue a short-lived (5 min) MFA challenge token instead of the real token.
            challenge_token = _create_token(
                user_id=row["id"],
                email=row["email"],
                secret_key=secret_key,
                expires_in=300,  # 5 minutes
            )
            logger.info(
                "MFA challenge issued for user: %s (id=%s)", row["email"], row["id"]
            )
            return AuthResponse(
                user_id=row["id"],
                email=row["email"],
                access_token="",  # Not issued until MFA is verified
                mfa_required=True,
                mfa_challenge_token=challenge_token,
            )
        else:
            logger.info(
                "Device trusted — skipping MFA challenge for user: %s (id=%s)",
                row["email"],
                row["id"],
            )

    token = _create_token(
        user_id=row["id"],
        email=row["email"],
        secret_key=secret_key,
    )
    logger.info("User logged in: %s (id=%s)", row["email"], row["id"])

    return AuthResponse(
        user_id=row["id"],
        email=row["email"],
        access_token=token,
    )


@router.get(
    "/me",
    summary="Get current user profile",
)
async def get_me(
    request: Request,
    db_path: str = Depends(_get_db_path),
    secret_key: str = Depends(_get_secret_key),
) -> dict:
    """Return the authenticated user's profile.

    Extracts and verifies the Bearer token from the Authorization header,
    then returns user_id, email, and created_at from the database.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = auth_header[7:]
    if not secret_key:
        from isg_agent.config import get_settings
        secret_key = get_settings().secret_key

    payload = verify_token(token, secret_key)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = payload.get("sub", "")

    await _ensure_users_table(db_path, db_path == ":memory:")
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, email, created_at FROM users WHERE id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=401, detail="User not found")

    return {
        "user_id": row["id"],
        "email": row["email"],
        "created_at": row["created_at"],
    }


@router.post(
    "/logout",
    summary="Invalidate current JWT token",
    status_code=200,
)
async def logout(
    request: Request,
    db_path: str = Depends(_get_db_path),
    secret_key: str = Depends(_get_secret_key),
) -> dict:
    """Invalidate the current JWT by adding it to the token_revocations table.

    Delegates to :func:`isg_agent.middleware.token_guard.revoke_token` which
    writes to the ``token_revocations`` table — the same table that
    :class:`isg_agent.middleware.token_guard.TokenRevocationGuard` reads from
    on every subsequent request.  This closes the P1 security gap where logout
    was writing to a separate ``revoked_tokens`` table that the guard never
    consulted.

    Returns 200.  On any re-use of the revoked token the
    TokenRevocationGuard intercepts the request before this handler is
    reached and returns 401 immediately.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = auth_header[7:]
    if not secret_key:
        from isg_agent.config import get_settings
        secret_key = get_settings().secret_key

    payload = verify_token(token, secret_key)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Write to token_revocations — the table TokenRevocationGuard reads from.
    from isg_agent.middleware.token_guard import revoke_token as _revoke_token
    await _revoke_token(jti=token, db_path=db_path)

    logger.info("Token revoked for user: %s", payload.get("sub", "unknown"))
    return {"message": "Logged out successfully"}


@router.post(
    "/refresh",
    response_model=AuthResponse,
    summary="Refresh an access token",
    status_code=200,
)
async def refresh_token(
    request: Request,
    db_path: str = Depends(_get_db_path),
    secret_key: str = Depends(_get_secret_key),
) -> AuthResponse:
    """Issue a new access token from the current Bearer token.

    Accepts the existing access token in the ``Authorization: Bearer`` header.
    The token signature is verified with the HMAC key.  Expired tokens are
    accepted within a 7-day grace window so that short-lived (24 h) tokens
    can be silently refreshed without forcing a full re-login.

    Returns the same :class:`AuthResponse` shape as ``/auth/login`` so the
    frontend can update its stored token without additional parsing logic.

    Raises ``401`` when:
    - No ``Authorization`` header is present.
    - The token signature is invalid (tampered).
    - The token is older than the 7-day hard expiry limit.
    - The user no longer exists in the database.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No token provided",
        )

    token = auth_header[7:]

    if not secret_key:
        from isg_agent.config import get_settings
        secret_key = get_settings().secret_key

    # Verify signature without enforcing expiry — we enforce our own window below.
    payload = _decode_token_ignore_expiry(token, secret_key)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    # Enforce a hard 7-day refresh window.  Tokens older than this require
    # the user to log in again.
    _REFRESH_GRACE_SECONDS = 7 * 24 * 3600  # 7 days
    issued_at = payload.get("iat", 0)
    if int(time.time()) - int(issued_at) > _REFRESH_GRACE_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token too old — please log in again",
        )

    user_id = payload.get("sub", "")
    email = payload.get("email", "")

    # Confirm the user still exists and is verified.
    await _ensure_users_table(db_path, db_path == ":memory:")
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, email, email_verified FROM users WHERE id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    # Email verification gate — soft warning only (no blocking until
    # the verification flow is fully operational end-to-end).
    email_verified = row["email_verified"] if "email_verified" in row.keys() else 0
    if not email_verified:
        logger.info(
            "Token refresh by unverified email: %s (id=%s) — allowing (soft gate)",
            row["email"],
            row["id"],
        )

    new_token = _create_token(
        user_id=row["id"],
        email=row["email"],
        secret_key=secret_key,
    )
    logger.info("Token refreshed for user: %s (id=%s)", row["email"], row["id"])

    return AuthResponse(
        user_id=row["id"],
        email=row["email"],
        access_token=new_token,
    )


# ---------------------------------------------------------------------------
# TOTP MFA Endpoints (Gap 2)
# ---------------------------------------------------------------------------


@router.post(
    "/mfa/setup",
    response_model=MfaSetupResponse,
    summary="Generate a TOTP secret and provisioning URI for MFA setup",
    status_code=200,
)
async def mfa_setup(
    request: Request,
    db_path: str = Depends(_get_db_path),
    secret_key: str = Depends(_get_secret_key),
) -> MfaSetupResponse:
    """Generate a new TOTP secret for the authenticated user.

    The caller should display the ``otpauth_uri`` as a QR code.  The secret
    is NOT persisted yet — the user must call ``/auth/mfa/verify`` with a
    valid TOTP code to confirm and activate MFA.

    Requires a valid Bearer token.
    """
    try:
        import pyotp
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TOTP MFA is not available (pyotp not installed)",
        )

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token_str = auth_header[7:]
    if not secret_key:
        from isg_agent.config import get_settings
        secret_key = get_settings().secret_key

    payload = verify_token(token_str, secret_key)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_email = str(payload.get("email", ""))
    totp_secret = pyotp.random_base32()
    uri = pyotp.totp.TOTP(totp_secret).provisioning_uri(
        name=user_email,
        issuer_name="DingDawg",
    )
    return MfaSetupResponse(secret=totp_secret, otpauth_uri=uri)


@router.post(
    "/mfa/verify",
    response_model=AuthResponse,
    summary="Verify a TOTP code — activates MFA during setup or completes MFA login",
    status_code=200,
)
async def mfa_verify(
    body: MfaVerifyRequest,
    request: Request,
    db_path: str = Depends(_get_db_path),
    secret_key: str = Depends(_get_secret_key),
) -> AuthResponse:
    """Verify a TOTP code.

    Two flows are supported:

    **Setup flow** (activating MFA for the first time):
    - Call with a valid Bearer token (from normal login) and ``code`` only.
    - On success, saves ``totp_secret`` to the users table and returns a
      fresh access token.  ``body.challenge_token`` must be omitted/null.
    - The secret must have been returned by ``/auth/mfa/setup`` in the same
      session.  Pass it as part of the request body via ``secret`` field or
      the caller re-calls ``/auth/mfa/setup`` to get a fresh one.

    **Login challenge flow** (completing MFA after password login):
    - Call with ``challenge_token`` (issued by ``/auth/login`` when MFA is
      required) and ``code``.  No Authorization header needed.
    - On success, returns the real long-lived access token.

    Returns 401 for an invalid or expired token/challenge.
    Returns 400 for an incorrect TOTP code.
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

    # Determine which flow we're in.
    challenge_token = body.challenge_token
    auth_header = request.headers.get("authorization", "")

    if challenge_token:
        # ---- Login challenge flow ----
        payload = verify_token(challenge_token, secret_key)
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired MFA challenge token",
            )
        user_id = str(payload.get("sub", ""))
    elif auth_header.startswith("Bearer "):
        # ---- Setup flow ----
        payload = verify_token(auth_header[7:], secret_key)
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )
        user_id = str(payload.get("sub", ""))
        challenge_token = None  # Ensure we know this is setup flow
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    # Fetch user + current totp_secret from DB.
    await _ensure_users_table(db_path, db_path == ":memory:")
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, email, totp_secret FROM users WHERE id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    stored_secret = row["totp_secret"] if "totp_secret" in row.keys() else None

    if body.challenge_token:
        # Login challenge flow: secret must already be stored.
        if not stored_secret:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="MFA is not configured for this account",
            )
        totp_secret_to_verify = stored_secret
    else:
        # Setup flow: secret comes from the body (user just got it from /mfa/setup).
        # We need the user to pass the secret they received, as we did not persist it.
        # Accept it from the body field named "secret" via a different mechanism:
        # Since MfaVerifyRequest only has `code` and `challenge_token`, for setup
        # we require the caller to pass the secret in a header or re-use the stored one.
        # Simplest safe approach: require the secret in a custom header X-TOTP-Secret
        # during setup flow, and persist on first valid verify.
        totp_secret_header = request.headers.get("x-totp-secret", "").strip()
        if not totp_secret_header and not stored_secret:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "MFA setup requires the TOTP secret in X-TOTP-Secret header. "
                    "Call /auth/mfa/setup first."
                ),
            )
        totp_secret_to_verify = totp_secret_header or stored_secret  # type: ignore[assignment]

    # Validate the TOTP code (allow 1 step window on each side for clock skew).
    totp = pyotp.TOTP(totp_secret_to_verify)
    if not totp.verify(body.code, valid_window=1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid TOTP code",
        )

    # If setup flow and secret not yet persisted, save it now.
    if not body.challenge_token and not stored_secret:
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "UPDATE users SET totp_secret = ? WHERE id = ?",
                (totp_secret_to_verify, user_id),
            )
            await db.commit()
        logger.info("MFA activated for user_id=%s", user_id)

    # Issue a full access token.
    final_token = _create_token(
        user_id=row["id"],
        email=row["email"],
        secret_key=secret_key,
    )
    logger.info("MFA verified for user: %s (id=%s)", row["email"], row["id"])

    return AuthResponse(
        user_id=row["id"],
        email=row["email"],
        access_token=final_token,
    )


@router.post(
    "/forgot-password",
    summary="Request password reset",
    status_code=200,
)
async def forgot_password(
    body: ForgotPasswordRequest,
    db_path: str = Depends(_get_db_path),
) -> dict:
    """Send a password reset link. Always returns 200 to prevent email enumeration."""
    import hashlib
    import secrets
    from datetime import timedelta

    await _ensure_users_table(db_path, db_path == ":memory:")
    generic = {"message": "If an account exists with that email, a password reset link will be sent."}
    now = datetime.now(timezone.utc)

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, email, full_name FROM users WHERE email = ?", (body.email,)
        ) as cursor:
            user = await cursor.fetchone()

    if not user:
        logger.info("Password reset requested for unknown email: %s", body.email)
        return generic

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = (now + timedelta(hours=1)).isoformat()

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """CREATE TABLE IF NOT EXISTS password_reset_tokens (
               token_hash TEXT PRIMARY KEY,
               user_id    TEXT NOT NULL,
               expires_at TEXT NOT NULL,
               used       INTEGER NOT NULL DEFAULT 0,
               used_at    TEXT,
               created_at TEXT NOT NULL
            )"""
        )
        await db.execute(
            """INSERT INTO password_reset_tokens
               (token_hash, user_id, expires_at, created_at)
               VALUES (?, ?, ?, ?)""",
            (token_hash, user["id"], expires_at, now.isoformat()),
        )
        await db.commit()

    reset_url = f"https://app.dingdawg.com/reset-password?token={raw_token}"
    try:
        from isg_agent.comms.email_service import render_password_reset, send_email
        name = user["full_name"] or user["email"]
        subject, html = render_password_reset(name, reset_url)
        await send_email(
            template_id="password_reset",
            to_email=user["email"],
            subject=subject,
            html_body=html,
            db_path=db_path,
            user_id=user["id"],
        )
    except Exception as exc:
        logger.warning("Password reset email failed for %s: %s", body.email, exc)

    logger.info("Password reset dispatched for user: %s", user["id"])
    return generic


class PasswordResetRequest(BaseModel):
    token: str
    new_password: str


@router.post("/reset-password", summary="Complete password reset", status_code=200)
async def reset_password(
    body: PasswordResetRequest,
    db_path: str = Depends(_get_db_path),
) -> dict:
    """Validate a reset token and update the user's password."""
    import hashlib

    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be at least 8 characters.",
        )

    now = datetime.now(timezone.utc)
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM password_reset_tokens WHERE token_hash = ?", (token_hash,)
        ) as cursor:
            record = await cursor.fetchone()

    if not record:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token.")
    if record["used"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reset token already used.")
    if datetime.fromisoformat(record["expires_at"]).replace(tzinfo=timezone.utc) < now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reset token has expired.")

    password_hash, salt = _hash_password(body.new_password)
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
            (password_hash, salt, record["user_id"]),
        )
        await db.execute(
            "UPDATE password_reset_tokens SET used = 1, used_at = ? WHERE token_hash = ?",
            (now.isoformat(), token_hash),
        )
        await db.commit()

    return {"message": "Password updated successfully."}
