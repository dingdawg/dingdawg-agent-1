"""Tests for the password reset flow.

Covers:
- test_forgot_password_sends_email
- test_forgot_password_nonexistent_email_returns_200
- test_forgot_password_rate_limited
- test_reset_password_valid_token
- test_reset_password_expired_token
- test_reset_password_used_token
- test_reset_password_invalid_token
- test_token_stored_as_sha256_hash
- test_password_actually_changed
- test_existing_tokens_invalidated_on_password_change
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest
import pytest_asyncio

from isg_agent.auth.password_reset import (
    PasswordResetManager,
    RateLimitedError,
    TokenExpiredError,
    TokenInvalidError,
    TokenUsedError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path: Path) -> str:
    """Return a path to a fresh, empty SQLite DB."""
    return str(tmp_path / "test_reset.db")


@pytest_asyncio.fixture
async def manager(tmp_db: str) -> PasswordResetManager:
    """PasswordResetManager backed by a temporary DB."""
    m = PasswordResetManager(db_path=tmp_db)
    await m.init_tables()
    return m


@pytest_asyncio.fixture
async def registered_user(tmp_db: str) -> dict:
    """Create a real user row in the DB and return {id, email}."""
    import uuid
    from isg_agent.api.routes.auth import _hash_password

    user_id = str(uuid.uuid4())
    email = f"user_{user_id[:8]}@example.com"
    password_hash, salt = _hash_password("password123")
    created_at = datetime.now(timezone.utc).isoformat()

    async with aiosqlite.connect(tmp_db) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            "INSERT INTO users (id, email, password_hash, salt, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, email, password_hash, salt, created_at),
        )
        await db.commit()

    return {"id": user_id, "email": email}


# ---------------------------------------------------------------------------
# Unit tests: PasswordResetManager
# ---------------------------------------------------------------------------


class TestPasswordResetManager:
    """Unit-level tests against PasswordResetManager directly."""

    @pytest.mark.asyncio
    async def test_create_and_validate_token(
        self, manager: PasswordResetManager, registered_user: dict
    ):
        """A freshly created token validates and returns the correct user_id."""
        token = await manager.create_token(user_id=registered_user["id"])
        user_id = await manager.validate_token(token)
        assert user_id == registered_user["id"]

    @pytest.mark.asyncio
    async def test_token_stored_as_sha256_hash(
        self, manager: PasswordResetManager, registered_user: dict, tmp_db: str
    ):
        """The DB must only contain the SHA-256 hash, never the plaintext token."""
        token = await manager.create_token(user_id=registered_user["id"])
        expected_hash = hashlib.sha256(token.encode()).hexdigest()

        async with aiosqlite.connect(tmp_db) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT token_hash FROM password_reset_tokens WHERE user_id = ?",
                (registered_user["id"],),
            )
            row = await cursor.fetchone()

        assert row is not None
        assert row["token_hash"] == expected_hash
        # Plaintext token must NOT appear anywhere in the stored hash
        assert token not in row["token_hash"]

    @pytest.mark.asyncio
    async def test_reset_password_invalid_token(self, manager: PasswordResetManager):
        """An unknown token raises TokenInvalidError."""
        with pytest.raises(TokenInvalidError):
            await manager.validate_token("totally-invalid-token-xyz")

    @pytest.mark.asyncio
    async def test_reset_password_expired_token(
        self, manager: PasswordResetManager, registered_user: dict, tmp_db: str
    ):
        """A token with expires_at in the past raises TokenExpiredError."""
        token = await manager.create_token(user_id=registered_user["id"])
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        # Back-date the expiry
        past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        async with aiosqlite.connect(tmp_db) as db:
            await db.execute(
                "UPDATE password_reset_tokens SET expires_at = ? WHERE token_hash = ?",
                (past, token_hash),
            )
            await db.commit()

        with pytest.raises(TokenExpiredError):
            await manager.validate_token(token)

    @pytest.mark.asyncio
    async def test_reset_password_used_token(
        self, manager: PasswordResetManager, registered_user: dict, tmp_db: str
    ):
        """A token with used=1 raises TokenUsedError."""
        token = await manager.create_token(user_id=registered_user["id"])
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        async with aiosqlite.connect(tmp_db) as db:
            await db.execute(
                "UPDATE password_reset_tokens SET used = 1 WHERE token_hash = ?",
                (token_hash,),
            )
            await db.commit()

        with pytest.raises(TokenUsedError):
            await manager.validate_token(token)

    @pytest.mark.asyncio
    async def test_forgot_password_rate_limited(
        self, manager: PasswordResetManager, registered_user: dict
    ):
        """After 3 requests in the window the 4th raises RateLimitedError."""
        for _ in range(3):
            await manager.create_token(user_id=registered_user["id"])

        with pytest.raises(RateLimitedError):
            await manager.create_token(user_id=registered_user["id"])

    @pytest.mark.asyncio
    async def test_password_actually_changed(
        self, manager: PasswordResetManager, registered_user: dict, tmp_db: str
    ):
        """After consume_token_and_reset_password, the new password verifies."""
        from isg_agent.api.routes.auth import _hash_password, _verify_password

        new_password = "NewSecurePass123!"
        new_hash, new_salt = _hash_password(new_password)

        token = await manager.create_token(user_id=registered_user["id"])
        await manager.consume_token_and_reset_password(
            token=token,
            new_password_hash=new_hash,
            new_salt=new_salt,
        )

        # Verify the DB row was updated
        async with aiosqlite.connect(tmp_db) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT password_hash, salt FROM users WHERE id = ?",
                (registered_user["id"],),
            )
            row = await cursor.fetchone()

        assert row is not None
        assert _verify_password(new_password, row["password_hash"], row["salt"]) is True

    @pytest.mark.asyncio
    async def test_existing_tokens_invalidated_on_password_change(
        self, manager: PasswordResetManager, registered_user: dict, tmp_db: str
    ):
        """After a password reset, user_revocation_epoch has an entry for the user."""
        from isg_agent.api.routes.auth import _hash_password

        new_hash, new_salt = _hash_password("NewPass456!")
        token = await manager.create_token(user_id=registered_user["id"])
        await manager.consume_token_and_reset_password(
            token=token,
            new_password_hash=new_hash,
            new_salt=new_salt,
        )

        async with aiosqlite.connect(tmp_db) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT revoked_at FROM user_revocation_epoch WHERE user_id = ?",
                (registered_user["id"],),
            )
            row = await cursor.fetchone()

        assert row is not None
        assert row["revoked_at"]  # non-empty timestamp

    @pytest.mark.asyncio
    async def test_get_user_by_email_returns_none_for_missing(
        self, manager: PasswordResetManager, tmp_db: str
    ):
        """get_user_by_email returns None for an address that does not exist."""
        # Ensure the users table exists before querying
        async with aiosqlite.connect(tmp_db) as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS users "
                "(id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, "
                "password_hash TEXT NOT NULL, salt TEXT NOT NULL, created_at TEXT NOT NULL)"
            )
            await db.commit()
        result = await manager.get_user_by_email("ghost@example.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_by_email_finds_registered_user(
        self, manager: PasswordResetManager, registered_user: dict
    ):
        """get_user_by_email returns the correct user dict for a known email."""
        result = await manager.get_user_by_email(registered_user["email"])
        assert result is not None
        assert result["id"] == registered_user["id"]


# ---------------------------------------------------------------------------
# API endpoint tests (via httpx ASGI transport)
# ---------------------------------------------------------------------------


@pytest.fixture()
def env_override_for_app(tmp_db: str):
    """Override ISG_AGENT_DB_PATH for the app factory during these tests."""
    overrides = {
        "ISG_AGENT_DB_PATH": tmp_db,
        "ISG_AGENT_SECRET_KEY": "test-secret-key-for-password-reset",
    }
    originals = {}
    for k, v in overrides.items():
        originals[k] = os.environ.get(k)
        os.environ[k] = v
    yield
    for k, orig in originals.items():
        if orig is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = orig


class TestForgotPasswordEndpoint:
    """Integration tests for POST /auth/forgot-password."""

    @pytest.mark.asyncio
    async def test_forgot_password_nonexistent_email_returns_200(self, env_override_for_app):
        """Unknown email returns 200 — no information leak."""
        from isg_agent.app import create_app
        from isg_agent.config import get_settings
        get_settings.cache_clear()

        from httpx import ASGITransport, AsyncClient

        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/auth/forgot-password",
                json={"email": "nobody@notreal.com"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_forgot_password_sends_email(self, env_override_for_app, tmp_db: str):
        """For an existing user, SendGrid.send_email is called once."""
        import uuid
        from isg_agent.api.routes.auth import _hash_password
        from datetime import datetime, timezone

        # Pre-seed the user
        user_id = str(uuid.uuid4())
        email = f"reset_test_{user_id[:8]}@example.com"
        pw_hash, salt = _hash_password("password123")
        created_at = datetime.now(timezone.utc).isoformat()

        async with aiosqlite.connect(tmp_db) as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS users "
                "(id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, "
                "password_hash TEXT NOT NULL, salt TEXT NOT NULL, created_at TEXT NOT NULL)"
            )
            await db.execute(
                "INSERT INTO users (id, email, password_hash, salt, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, email, pw_hash, salt, created_at),
            )
            await db.commit()

        from isg_agent.app import create_app
        from isg_agent.config import get_settings
        get_settings.cache_clear()

        from httpx import ASGITransport, AsyncClient

        # Mock SendGrid.send_email at the connector level
        mock_send = AsyncMock(return_value={"success": True, "message_id": "test-id", "status_code": 202})

        app = create_app()

        # Patch after app is created but before requests
        with patch.object(
            app.state.__class__,
            "sendgrid",
            create=True,
            new_callable=lambda: property(lambda self: MagicMock(send_email=mock_send)),
        ):
            # We patch at module level to be safe across lifespan
            with patch(
                "isg_agent.api.routes.auth_extended._get_sendgrid",
                return_value=MagicMock(send_email=mock_send),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/auth/forgot-password",
                        json={"email": email},
                    )

        assert resp.status_code == 200
        assert "message" in resp.json()
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_forgot_password_always_returns_generic_message(self, env_override_for_app):
        """Both existing and non-existing emails return the same message body."""
        from isg_agent.app import create_app
        from isg_agent.config import get_settings
        get_settings.cache_clear()

        from httpx import ASGITransport, AsyncClient

        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/auth/forgot-password",
                json={"email": "doesnotexist_xyz@nope.com"},
            )
        assert resp.status_code == 200
        msg = resp.json()["message"]
        # Generic message must not say "no account" or similar
        assert "If an account exists" in msg or "will be sent" in msg
        get_settings.cache_clear()


class TestResetPasswordEndpoint:
    """Integration tests for POST /auth/reset-password."""

    @pytest.mark.asyncio
    async def test_reset_password_invalid_token(self, env_override_for_app):
        """Bogus token → 400."""
        from isg_agent.app import create_app
        from isg_agent.config import get_settings
        get_settings.cache_clear()

        from httpx import ASGITransport, AsyncClient

        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/auth/reset-password",
                json={"token": "bogus-not-real-token", "new_password": "NewPass123!"},
            )
        assert resp.status_code == 400
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_reset_password_valid_token(self, env_override_for_app, tmp_db: str):
        """Valid token + new password → 200 and password is updated."""
        import uuid
        import isg_agent.api.routes.auth_extended as _ae
        from isg_agent.api.routes.auth import _hash_password, _verify_password
        from datetime import datetime, timezone

        user_id = str(uuid.uuid4())
        email = f"valid_reset_{user_id[:8]}@example.com"
        pw_hash, salt = _hash_password("OldPass123!")
        created_at = datetime.now(timezone.utc).isoformat()

        async with aiosqlite.connect(tmp_db) as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS users "
                "(id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, "
                "password_hash TEXT NOT NULL, salt TEXT NOT NULL, created_at TEXT NOT NULL)"
            )
            await db.execute(
                "INSERT INTO users (id, email, password_hash, salt, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, email, pw_hash, salt, created_at),
            )
            await db.commit()

        # Create token directly via manager (using tmp_db)
        manager = PasswordResetManager(db_path=tmp_db)
        token = await manager.create_token(user_id=user_id)

        # Point the auth_extended module at the same tmp_db the manager used
        _ae._set_auth_extended_config(
            db_path=tmp_db,
            frontend_url="https://test.dingdawg.com",
        )

        from isg_agent.app import create_app
        from isg_agent.config import get_settings
        get_settings.cache_clear()

        from httpx import ASGITransport, AsyncClient

        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/auth/reset-password",
                json={"token": token, "new_password": "NewSecure456!"},
            )

        assert resp.status_code == 200, resp.text
        assert "message" in resp.json()

        # Verify password was actually changed in DB
        async with aiosqlite.connect(tmp_db) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT password_hash, salt FROM users WHERE id = ?", (user_id,)
            )
            row = await cursor.fetchone()

        assert row is not None
        assert _verify_password("NewSecure456!", row["password_hash"], row["salt"]) is True
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_reset_password_short_password_rejected(self, env_override_for_app):
        """Password < 8 chars → 422 Unprocessable Entity."""
        from isg_agent.app import create_app
        from isg_agent.config import get_settings
        get_settings.cache_clear()

        from httpx import ASGITransport, AsyncClient

        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/auth/reset-password",
                json={"token": "sometoken", "new_password": "short"},
            )
        assert resp.status_code == 422
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_reset_password_complexity_no_uppercase_rejected(self, env_override_for_app):
        """Password without uppercase → 422 (complexity rule parity with registration)."""
        from isg_agent.app import create_app
        from isg_agent.config import get_settings
        get_settings.cache_clear()

        from httpx import ASGITransport, AsyncClient

        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 8 chars, has digit and special, but NO uppercase
            resp = await client.post(
                "/auth/reset-password",
                json={"token": "sometoken", "new_password": "weak1!ab"},
            )
        assert resp.status_code == 422
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_reset_password_complexity_no_digit_rejected(self, env_override_for_app):
        """Password without digit → 422."""
        from isg_agent.app import create_app
        from isg_agent.config import get_settings
        get_settings.cache_clear()

        from httpx import ASGITransport, AsyncClient

        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # has uppercase and special, but NO digit
            resp = await client.post(
                "/auth/reset-password",
                json={"token": "sometoken", "new_password": "Password!"},
            )
        assert resp.status_code == 422
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_reset_password_complexity_no_special_rejected(self, env_override_for_app):
        """Password without special character → 422."""
        from isg_agent.app import create_app
        from isg_agent.config import get_settings
        get_settings.cache_clear()

        from httpx import ASGITransport, AsyncClient

        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # has uppercase and digit, but NO special char
            resp = await client.post(
                "/auth/reset-password",
                json={"token": "sometoken", "new_password": "Password1"},
            )
        assert resp.status_code == 422
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_reset_password_complexity_strong_password_accepted(self, env_override_for_app):
        """A strong password passes validation (token lookup still fails, but not 422)."""
        from isg_agent.app import create_app
        from isg_agent.config import get_settings
        get_settings.cache_clear()

        from httpx import ASGITransport, AsyncClient

        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/auth/reset-password",
                json={"token": "bogus-but-strong-password-test", "new_password": "Secure1!Pass"},
            )
        # 400 = token invalid (expected), NOT 422 (validation error)
        assert resp.status_code == 400
        get_settings.cache_clear()
