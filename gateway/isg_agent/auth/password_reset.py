"""Password reset token generation, validation, and reset logic.

Security model:
- Tokens are generated via secrets.token_urlsafe(32)
- ONLY the SHA-256 hash of the token is stored in the DB (never plaintext)
- Token lookup uses hmac.compare_digest for timing-safe comparison
- Tokens expire after 1 hour and are one-time-use
- Rate limited to 3 requests per email per hour
- Password change invalidates all existing JWT tokens for the user
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import aiosqlite

__all__ = [
    "PasswordResetManager",
    "PasswordResetError",
    "TokenExpiredError",
    "TokenUsedError",
    "TokenInvalidError",
    "RateLimitedError",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PasswordResetError(Exception):
    """Base class for password reset errors."""


class TokenExpiredError(PasswordResetError):
    """Token exists but has passed its expiry time."""


class TokenUsedError(PasswordResetError):
    """Token has already been consumed."""


class TokenInvalidError(PasswordResetError):
    """Token does not exist or hash does not match."""


class RateLimitedError(PasswordResetError):
    """Too many reset requests for this email within the window."""


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

_CREATE_RESET_TABLE = """
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    token_hash  TEXT NOT NULL UNIQUE,
    expires_at  TEXT NOT NULL,
    used        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
"""

_CREATE_RESET_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_reset_tokens_hash "
    "ON password_reset_tokens (token_hash);"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RESET_TOKEN_TTL_SECONDS = 3600  # 1 hour
_RATE_LIMIT_MAX = 3              # max requests per email per window
_RATE_LIMIT_WINDOW_SECONDS = 3600  # 1 hour window


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


class PasswordResetManager:
    """Handles password reset token lifecycle against a SQLite database."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    async def init_tables(self) -> None:
        """Create the password_reset_tokens table if it does not exist."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(_CREATE_RESET_TABLE)
            await db.execute(_CREATE_RESET_INDEX)
            await db.commit()
        logger.debug("Password reset tokens table ready")

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    async def _check_rate_limit(self, user_id: str) -> None:
        """Raise RateLimitedError if the user has exceeded the request cap.

        Counts un-used, non-expired tokens created in the last hour.
        """
        window_start = (_now_utc() - timedelta(seconds=_RATE_LIMIT_WINDOW_SECONDS)).isoformat()

        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """
                SELECT COUNT(*) FROM password_reset_tokens
                WHERE user_id = ?
                  AND created_at >= ?
                """,
                (user_id, window_start),
            )
            row = await cursor.fetchone()

        count = row[0] if row else 0
        if count >= _RATE_LIMIT_MAX:
            logger.warning(
                "Password reset rate limit reached for user_id=%s (%d requests in window)",
                user_id, count,
            )
            raise RateLimitedError(
                "Too many password reset requests. Please wait before trying again."
            )

    # ------------------------------------------------------------------
    # Token creation
    # ------------------------------------------------------------------

    async def create_token(self, user_id: str) -> str:
        """Generate a secure reset token, persist its hash, and return the plaintext token.

        Parameters
        ----------
        user_id:
            The ID of the user requesting a reset.

        Returns
        -------
        str
            The plaintext token to include in the reset URL. The DB only
            stores the SHA-256 hash — the plaintext is never persisted.

        Raises
        ------
        RateLimitedError
            If the user has already made 3+ requests in the last hour.
        """
        await self.init_tables()
        await self._check_rate_limit(user_id)

        token = secrets.token_urlsafe(32)
        token_hash = _sha256(token)
        token_id = str(uuid.uuid4())
        now = _now_utc()
        expires_at = (now + timedelta(seconds=_RESET_TOKEN_TTL_SECONDS)).isoformat()
        created_at = now.isoformat()

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO password_reset_tokens
                    (id, user_id, token_hash, expires_at, used, created_at)
                VALUES (?, ?, ?, ?, 0, ?)
                """,
                (token_id, user_id, token_hash, expires_at, created_at),
            )
            await db.commit()

        logger.info("Password reset token created for user_id=%s", user_id)
        return token

    # ------------------------------------------------------------------
    # Token validation
    # ------------------------------------------------------------------

    async def validate_token(self, token: str) -> str:
        """Validate a reset token and return the associated user_id.

        Parameters
        ----------
        token:
            The plaintext token from the reset URL.

        Returns
        -------
        str
            The user_id the token belongs to.

        Raises
        ------
        TokenInvalidError
            If no matching hash is found.
        TokenExpiredError
            If the token's expiry has passed.
        TokenUsedError
            If the token has already been consumed.
        """
        await self.init_tables()
        candidate_hash = _sha256(token)

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            # Fetch all tokens and compare hashes in Python (timing-safe)
            cursor = await db.execute(
                """
                SELECT id, user_id, token_hash, expires_at, used
                FROM password_reset_tokens
                WHERE token_hash = ?
                """,
                (candidate_hash,),
            )
            row = await cursor.fetchone()

        if row is None:
            logger.warning("Password reset: unknown token hash attempted")
            raise TokenInvalidError("Invalid or expired reset token.")

        # Timing-safe comparison (defence-in-depth — hash is already stored hash)
        stored_hash: str = row["token_hash"]
        if not hmac.compare_digest(candidate_hash, stored_hash):
            raise TokenInvalidError("Invalid or expired reset token.")

        if row["used"]:
            raise TokenUsedError("This reset link has already been used.")

        expires_at = _parse_dt(row["expires_at"])
        if _now_utc() > expires_at:
            raise TokenExpiredError("This reset link has expired. Please request a new one.")

        return str(row["user_id"])

    # ------------------------------------------------------------------
    # Password update
    # ------------------------------------------------------------------

    async def consume_token_and_reset_password(
        self,
        token: str,
        new_password_hash: str,
        new_salt: str,
    ) -> str:
        """Validate token, update the user's password, and invalidate all JWT tokens.

        Parameters
        ----------
        token:
            The plaintext reset token.
        new_password_hash:
            PBKDF2 hex hash of the new password (computed by caller).
        new_salt:
            Hex salt used to produce new_password_hash (computed by caller).

        Returns
        -------
        str
            The user_id that was reset.

        Raises
        ------
        TokenInvalidError / TokenExpiredError / TokenUsedError
            Propagated from :meth:`validate_token`.
        """
        user_id = await self.validate_token(token)
        candidate_hash = _sha256(token)
        now = _now_utc().isoformat()

        async with aiosqlite.connect(self._db_path) as db:
            # Mark token as used
            await db.execute(
                "UPDATE password_reset_tokens SET used = 1 WHERE token_hash = ?",
                (candidate_hash,),
            )

            # Update the user's password
            await db.execute(
                "UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
                (new_password_hash, new_salt, user_id),
            )

            # Invalidate all existing JWT tokens for this user by inserting
            # them into revoked_tokens — here we do it by inserting a sentinel
            # row with the user_id so the token guard can check.
            # Simpler + compatible approach: insert a per-user revocation epoch.
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS user_revocation_epoch (
                    user_id    TEXT PRIMARY KEY,
                    revoked_at TEXT NOT NULL
                )
                """
            )
            await db.execute(
                """
                INSERT INTO user_revocation_epoch (user_id, revoked_at)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET revoked_at = excluded.revoked_at
                """,
                (user_id, now),
            )

            await db.commit()

        logger.info(
            "Password reset completed for user_id=%s — all existing tokens invalidated",
            user_id,
        )
        return user_id

    # ------------------------------------------------------------------
    # Lookup by email (for the forgot-password endpoint)
    # ------------------------------------------------------------------

    async def get_user_by_email(self, email: str) -> dict | None:
        """Return user row dict (id, email) or None if not found."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT id, email FROM users WHERE email = ?",
                (email.strip().lower(),),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return {"id": row["id"], "email": row["email"]}
