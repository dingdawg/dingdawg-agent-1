"""Email verification token generation, validation, and user flag management.

Security model:
- Tokens are generated via secrets.token_urlsafe(32)
- ONLY the SHA-256 hash of the token is stored in the DB (never plaintext)
- Token lookup uses hmac.compare_digest for timing-safe comparison
- Tokens expire after 24 hours and are one-time-use
- Unverified users can use the platform but cannot create agents
- Users can request a re-send (old token is NOT invalidated — multiple valid
  tokens may exist; the first one consumed wins)
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import aiosqlite

__all__ = [
    "EmailVerificationManager",
    "VerificationError",
    "VerificationTokenExpiredError",
    "VerificationTokenUsedError",
    "VerificationTokenInvalidError",
    "VerificationRateLimitedError",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class VerificationError(Exception):
    """Base class for email verification errors."""


class VerificationTokenExpiredError(VerificationError):
    """Token exists but has passed its expiry time."""


class VerificationTokenUsedError(VerificationError):
    """Token has already been consumed."""


class VerificationTokenInvalidError(VerificationError):
    """Token does not exist."""


class VerificationRateLimitedError(VerificationError):
    """Too many verification emails requested in the rate-limit window."""


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

_CREATE_VERIFICATION_TABLE = """
CREATE TABLE IF NOT EXISTS email_verification_tokens (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    token_hash  TEXT NOT NULL UNIQUE,
    expires_at  TEXT NOT NULL,
    used        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
"""

_CREATE_VERIFICATION_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_verification_tokens_hash "
    "ON email_verification_tokens (token_hash);"
)

_ALTER_USERS_EMAIL_VERIFIED = (
    "ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0;"
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VERIFICATION_TOKEN_TTL_SECONDS = 86400  # 24 hours

# Resend rate limit: 1 verification email per user per 5 minutes.
_RESEND_RATE_LIMIT_WINDOW_SECONDS = 300   # 5 minutes
_RESEND_RATE_LIMIT_MAX = 1                # max tokens in window


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256(token: str) -> str:
    """Return the hex SHA-256 digest of a token string."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(s: str) -> datetime:
    """Parse an ISO-8601 UTC string back to a datetime (tz-aware)."""
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class EmailVerificationManager:
    """Handles email verification token lifecycle against a SQLite database."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    async def init_tables(self) -> None:
        """Create email_verification_tokens table and add email_verified column."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(_CREATE_VERIFICATION_TABLE)
            await db.execute(_CREATE_VERIFICATION_INDEX)

            # Add email_verified column to users — idempotent via try/except
            try:
                await db.execute(_ALTER_USERS_EMAIL_VERIFIED)
            except Exception:
                # Column already exists — this is expected after first run
                pass

            await db.commit()
        logger.debug("Email verification tables ready")

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    async def _check_resend_rate_limit(self, user_id: str) -> None:
        """Raise VerificationRateLimitedError if user has hit the resend cap.

        Counts tokens created for this user within the last
        _RESEND_RATE_LIMIT_WINDOW_SECONDS seconds.  Allows at most
        _RESEND_RATE_LIMIT_MAX token creations per window.

        Note: the first verification email sent at registration is exempt
        because it is created before any rate-limit window starts.
        This check is called explicitly by the resend path; registration
        bypasses it via create_token_exempt().
        """
        window_start = (
            _now_utc() - timedelta(seconds=_RESEND_RATE_LIMIT_WINDOW_SECONDS)
        ).isoformat()

        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """
                SELECT COUNT(*) FROM email_verification_tokens
                WHERE user_id = ?
                  AND created_at >= ?
                """,
                (user_id, window_start),
            )
            row = await cursor.fetchone()

        count = row[0] if row else 0
        if count >= _RESEND_RATE_LIMIT_MAX:
            logger.warning(
                "Verification resend rate limit hit for user_id=%s (%d in window)",
                user_id,
                count,
            )
            raise VerificationRateLimitedError(
                "Too many verification emails requested. "
                "Please wait 5 minutes before requesting another."
            )

    # ------------------------------------------------------------------
    # Token creation
    # ------------------------------------------------------------------

    async def create_token(self, user_id: str, *, rate_limit: bool = False) -> str:
        """Generate a verification token, persist its hash, and return plaintext.

        Parameters
        ----------
        user_id:
            The ID of the user to verify.
        rate_limit:
            When True, enforce the resend rate limit (1 per 5 min) before
            creating the token.  Pass True from the resend endpoint; leave
            False (default) for the initial registration send.

        Returns
        -------
        str
            The plaintext token to embed in the verification URL.

        Raises
        ------
        VerificationRateLimitedError
            If rate_limit=True and the user has hit the resend cap.
        """
        await self.init_tables()

        if rate_limit:
            await self._check_resend_rate_limit(user_id)

        token = secrets.token_urlsafe(32)
        token_hash = _sha256(token)
        token_id = str(uuid.uuid4())
        now = _now_utc()
        expires_at = (now + timedelta(seconds=_VERIFICATION_TOKEN_TTL_SECONDS)).isoformat()
        created_at = now.isoformat()

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO email_verification_tokens
                    (id, user_id, token_hash, expires_at, used, created_at)
                VALUES (?, ?, ?, ?, 0, ?)
                """,
                (token_id, user_id, token_hash, expires_at, created_at),
            )
            await db.commit()

        logger.info("Email verification token created for user_id=%s", user_id)
        return token

    # ------------------------------------------------------------------
    # Token validation + consumption
    # ------------------------------------------------------------------

    async def verify_token(self, token: str) -> str:
        """Validate a verification token and mark the user's email as verified.

        Parameters
        ----------
        token:
            The plaintext token from the verification URL.

        Returns
        -------
        str
            The user_id whose email was verified.

        Raises
        ------
        VerificationTokenInvalidError
            If no matching hash is found.
        VerificationTokenExpiredError
            If the token's expiry has passed.
        VerificationTokenUsedError
            If the token has already been consumed.
        """
        await self.init_tables()
        candidate_hash = _sha256(token)

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT id, user_id, token_hash, expires_at, used
                FROM email_verification_tokens
                WHERE token_hash = ?
                """,
                (candidate_hash,),
            )
            row = await cursor.fetchone()

        if row is None:
            logger.warning("Email verification: unknown token hash attempted")
            raise VerificationTokenInvalidError("Invalid or expired verification link.")

        stored_hash: str = row["token_hash"]
        if not hmac.compare_digest(candidate_hash, stored_hash):
            raise VerificationTokenInvalidError("Invalid or expired verification link.")

        if row["used"]:
            raise VerificationTokenUsedError(
                "This verification link has already been used."
            )

        expires_at = _parse_dt(row["expires_at"])
        if _now_utc() > expires_at:
            raise VerificationTokenExpiredError(
                "This verification link has expired. Please request a new one."
            )

        user_id = str(row["user_id"])

        # Consume token and mark user as verified
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE email_verification_tokens SET used = 1 WHERE token_hash = ?",
                (candidate_hash,),
            )
            await db.execute(
                "UPDATE users SET email_verified = 1 WHERE id = ?",
                (user_id,),
            )
            await db.commit()

        logger.info("Email verified for user_id=%s", user_id)
        return user_id

    # ------------------------------------------------------------------
    # Status check
    # ------------------------------------------------------------------

    async def is_email_verified(self, user_id: str) -> bool:
        """Return True if the user's email_verified flag is set."""
        await self.init_tables()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT email_verified FROM users WHERE id = ?",
                (user_id,),
            )
            row = await cursor.fetchone()

        if row is None:
            return False
        return bool(row["email_verified"])
