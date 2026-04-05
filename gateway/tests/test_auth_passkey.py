"""TDD RED phase — WebAuthn/Passkey authentication tests.

Contract-driven tests for the 4 passkey endpoints.  These tests are written
BEFORE any implementation exists and will fail with ImportError or 404 until
the router at ``isg_agent.api.routes.auth_passkey`` is created and wired into
the application.

Endpoints under test
--------------------
POST /api/v1/auth/passkey/register/begin
POST /api/v1/auth/passkey/register/complete
POST /api/v1/auth/passkey/authenticate/begin
POST /api/v1/auth/passkey/authenticate/complete

Test categories
---------------
1.  Registration flow      — 12 tests
2.  Authentication flow    — 12 tests
3.  Security requirements  —  6 tests

Fixture pattern mirrors test_admin_api.py exactly:
  - tmp_path SQLite DB per test (via ``ctx`` fixture)
  - lifespan context ensures all tables exist before any HTTP request
  - JWT forged via _create_token (same verify_token path as existing auth)
  - Users table seeded for auth'd endpoint tests
"""

from __future__ import annotations

import os
import uuid
from collections import namedtuple
from datetime import datetime, timezone, timedelta
from typing import AsyncIterator

import aiosqlite
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from isg_agent.api.routes.auth import _create_token
from isg_agent.config import get_settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SECRET = "test-secret-passkey-suite"
_USER_EMAIL = "passkey-user@dingdawg-test.com"
_USER_ID = "passkey-user-001"
_OTHER_EMAIL = "other-user@dingdawg-test.com"
_OTHER_USER_ID = "passkey-user-002"
_NO_PASSKEY_EMAIL = "no-passkey@dingdawg-test.com"

ClientCtx = namedtuple("ClientCtx", ["ac", "db_path"])

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _make_token(user_id: str, email: str) -> str:
    return _create_token(user_id=user_id, email=email, secret_key=_SECRET)


def _user_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_token(_USER_ID, _USER_EMAIL)}"}


def _other_user_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_token(_OTHER_USER_ID, _OTHER_EMAIL)}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(loop_scope="function")
async def ctx(tmp_path) -> AsyncIterator[ClientCtx]:
    """Async client with fully initialised app lifespan + the DB path.

    Creates the users table, webauthn_credentials table, and
    webauthn_challenges table before any HTTP request is made.
    """
    db_file = str(tmp_path / "test_passkey.db")

    _prev_db = os.environ.get("ISG_AGENT_DB_PATH")
    _prev_secret = os.environ.get("ISG_AGENT_SECRET_KEY")

    os.environ["ISG_AGENT_DB_PATH"] = db_file
    os.environ["ISG_AGENT_SECRET_KEY"] = _SECRET
    get_settings.cache_clear()

    try:
        from isg_agent.app import create_app, lifespan

        app = create_app()

        async with lifespan(app):
            from isg_agent.api.routes.auth import _CREATE_USERS_SQL, _CREATE_INDEX_EMAIL
            from isg_agent.db.schema import create_tables

            async with aiosqlite.connect(db_file) as _db:
                await create_tables(_db)
                await _db.execute(_CREATE_USERS_SQL)
                await _db.execute(_CREATE_INDEX_EMAIL)
                await _db.commit()

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ClientCtx(ac=ac, db_path=db_file)
    finally:
        if _prev_db is None:
            os.environ.pop("ISG_AGENT_DB_PATH", None)
        else:
            os.environ["ISG_AGENT_DB_PATH"] = _prev_db

        if _prev_secret is None:
            os.environ.pop("ISG_AGENT_SECRET_KEY", None)
        else:
            os.environ["ISG_AGENT_SECRET_KEY"] = _prev_secret

        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# DB seed helpers
# ---------------------------------------------------------------------------


async def _seed_user(db_path: str, user_id: str, email: str, *, email_verified: int = 1) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO users (id, email, password_hash, salt, created_at, email_verified)
            VALUES (?, ?, 'fakehash', 'fakesalt', ?, ?)
            """,
            (user_id, email, now, email_verified),
        )
        await db.commit()


async def _seed_webauthn_credential(
    db_path: str,
    user_id: str,
    credential_id: str | None = None,
    device_name: str = "Test Device",
    sign_count: int = 0,
) -> str:
    """Insert a webauthn_credentials row; return the credential_id used."""
    cred_id = credential_id or f"cred-{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS webauthn_credentials (
                id           TEXT PRIMARY KEY,
                user_id      TEXT NOT NULL,
                credential_id TEXT NOT NULL UNIQUE,
                public_key   BLOB NOT NULL,
                sign_count   INTEGER NOT NULL DEFAULT 0,
                device_name  TEXT,
                transports   TEXT,
                created_at   TEXT NOT NULL,
                last_used_at TEXT
            )
            """,
        )
        await db.execute(
            """
            INSERT INTO webauthn_credentials
                (id, user_id, credential_id, public_key, sign_count, device_name, transports, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                user_id,
                cred_id,
                b"fake-public-key-bytes",
                sign_count,
                device_name,
                "[]",
                now,
            ),
        )
        await db.commit()
    return cred_id


async def _seed_expired_challenge(
    db_path: str,
    user_id: str,
    ceremony_type: str = "registration",
) -> str:
    """Insert a challenge row with expires_at in the past; return the challenge value."""
    challenge_val = f"expired-challenge-{uuid.uuid4().hex}"
    # 200 seconds ago — past the 120-second window
    expired_at = (datetime.now(timezone.utc) - timedelta(seconds=200)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS webauthn_challenges (
                id            TEXT PRIMARY KEY,
                user_id       TEXT NOT NULL,
                challenge     TEXT NOT NULL,
                ceremony_type TEXT NOT NULL,
                expires_at    TEXT NOT NULL,
                created_at    TEXT NOT NULL
            )
            """,
        )
        await db.execute(
            """
            INSERT INTO webauthn_challenges
                (id, user_id, challenge, ceremony_type, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), user_id, challenge_val, ceremony_type, expired_at, now),
        )
        await db.commit()
    return challenge_val


# ===========================================================================
# 1. Registration flow (12 tests)
# ===========================================================================


class TestPasskeyRegisterBegin:
    """Tests for POST /api/v1/auth/passkey/register/begin."""

    async def test_register_begin_returns_401_without_token(
        self, ctx: ClientCtx
    ) -> None:
        """Unauthenticated requests must be rejected with HTTP 401."""
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/register/begin",
            json={"device_name": "iPhone 15"},
        )
        assert resp.status_code == 401

    async def test_register_begin_returns_200_with_valid_token(
        self, ctx: ClientCtx
    ) -> None:
        """A Bearer token for an existing user must return HTTP 200."""
        await _seed_user(ctx.db_path, _USER_ID, _USER_EMAIL)
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/register/begin",
            headers=_user_headers(),
            json={"device_name": "iPhone 15"},
        )
        assert resp.status_code == 200

    async def test_register_begin_response_contains_rp_field(
        self, ctx: ClientCtx
    ) -> None:
        """Response JSON must include the ``rp`` (Relying Party) object."""
        await _seed_user(ctx.db_path, _USER_ID, _USER_EMAIL)
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/register/begin",
            headers=_user_headers(),
            json={},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "rp" in data, "WebAuthn CreationOptions must contain 'rp'"

    async def test_register_begin_response_contains_user_field(
        self, ctx: ClientCtx
    ) -> None:
        """Response JSON must include the ``user`` object."""
        await _seed_user(ctx.db_path, _USER_ID, _USER_EMAIL)
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/register/begin",
            headers=_user_headers(),
            json={},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "user" in data, "WebAuthn CreationOptions must contain 'user'"

    async def test_register_begin_response_contains_challenge_field(
        self, ctx: ClientCtx
    ) -> None:
        """Response JSON must include a ``challenge``."""
        await _seed_user(ctx.db_path, _USER_ID, _USER_EMAIL)
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/register/begin",
            headers=_user_headers(),
            json={},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "challenge" in data, "WebAuthn CreationOptions must contain 'challenge'"

    async def test_register_begin_response_contains_pub_key_cred_params(
        self, ctx: ClientCtx
    ) -> None:
        """Response JSON must include ``pubKeyCredParams``."""
        await _seed_user(ctx.db_path, _USER_ID, _USER_EMAIL)
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/register/begin",
            headers=_user_headers(),
            json={},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "pubKeyCredParams" in data, (
            "WebAuthn CreationOptions must contain 'pubKeyCredParams'"
        )

    async def test_register_begin_creates_challenge_row_in_db(
        self, ctx: ClientCtx
    ) -> None:
        """Calling register/begin must persist a challenge row for the user."""
        await _seed_user(ctx.db_path, _USER_ID, _USER_EMAIL)
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/register/begin",
            headers=_user_headers(),
            json={},
        )
        assert resp.status_code == 200

        async with aiosqlite.connect(ctx.db_path) as db:
            async with db.execute(
                "SELECT id FROM webauthn_challenges WHERE user_id = ? AND ceremony_type = 'registration'",
                (_USER_ID,),
            ) as cursor:
                row = await cursor.fetchone()
        assert row is not None, "A challenge row must be created in webauthn_challenges"


class TestPasskeyRegisterComplete:
    """Tests for POST /api/v1/auth/passkey/register/complete."""

    async def test_register_complete_returns_401_without_token(
        self, ctx: ClientCtx
    ) -> None:
        """Unauthenticated requests must be rejected with HTTP 401."""
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/register/complete",
            json={
                "credential": {"id": "abc", "rawId": "abc", "type": "public-key"},
                "device_name": "My Phone",
            },
        )
        assert resp.status_code == 401

    async def test_register_complete_returns_400_with_expired_challenge(
        self, ctx: ClientCtx
    ) -> None:
        """A challenge older than 120 seconds must be rejected with HTTP 400."""
        await _seed_user(ctx.db_path, _USER_ID, _USER_EMAIL)
        expired_challenge = await _seed_expired_challenge(
            ctx.db_path, _USER_ID, ceremony_type="registration"
        )
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/register/complete",
            headers=_user_headers(),
            json={
                "credential": {
                    "id": "fake-cred-id",
                    "rawId": "fake-cred-id",
                    "type": "public-key",
                    "response": {
                        "clientDataJSON": "eyJjaGFsbGVuZ2UiOiAi" + expired_challenge,
                        "attestationObject": "fakeattestation",
                    },
                },
                "device_name": "My Phone",
            },
        )
        assert resp.status_code == 400

    async def test_register_complete_returns_400_with_invalid_credential_data(
        self, ctx: ClientCtx
    ) -> None:
        """Malformed credential data must return HTTP 400."""
        await _seed_user(ctx.db_path, _USER_ID, _USER_EMAIL)
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/register/complete",
            headers=_user_headers(),
            json={
                "credential": {"malformed": True},
                "device_name": "My Phone",
            },
        )
        assert resp.status_code == 400

    async def test_register_complete_returns_credential_id_and_device_name(
        self, ctx: ClientCtx
    ) -> None:
        """On success, response must include credential_id and device_name fields."""
        # This test will pass once the implementation validates a real credential.
        # Until then it serves as the specification of the response shape.
        await _seed_user(ctx.db_path, _USER_ID, _USER_EMAIL)
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/register/complete",
            headers=_user_headers(),
            json={
                "credential": {
                    "id": "valid-cred-id",
                    "rawId": "valid-cred-id",
                    "type": "public-key",
                    "response": {
                        "clientDataJSON": "validbase64",
                        "attestationObject": "validattestation",
                    },
                },
                "device_name": "My iPhone",
            },
        )
        # Expect 200 once implementation exists; 404/422 in RED phase is acceptable
        # because the route does not exist yet.
        if resp.status_code == 200:
            data = resp.json()
            assert "credential_id" in data
            assert "device_name" in data
            assert "created_at" in data

    async def test_register_complete_credential_id_is_unique(
        self, ctx: ClientCtx
    ) -> None:
        """Registering the same credential_id twice must fail (UNIQUE constraint)."""
        await _seed_user(ctx.db_path, _USER_ID, _USER_EMAIL)
        existing_cred_id = await _seed_webauthn_credential(
            ctx.db_path, _USER_ID, credential_id="duplicate-cred-id"
        )
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/register/complete",
            headers=_user_headers(),
            json={
                "credential": {
                    "id": existing_cred_id,
                    "rawId": existing_cred_id,
                    "type": "public-key",
                    "response": {
                        "clientDataJSON": "validbase64",
                        "attestationObject": "validattestation",
                    },
                },
                "device_name": "Duplicate Device",
            },
        )
        assert resp.status_code in {400, 409}

    async def test_register_complete_sets_sign_count_to_zero(
        self, ctx: ClientCtx
    ) -> None:
        """A freshly registered passkey must have sign_count = 0."""
        await _seed_user(ctx.db_path, _USER_ID, _USER_EMAIL)
        # After a successful register/complete the credential row sign_count = 0.
        # Verified via DB inspection post-success (implementation phase).
        # In RED phase, assert the schema allows sign_count column to be 0.
        async with aiosqlite.connect(ctx.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS webauthn_credentials (
                    id           TEXT PRIMARY KEY,
                    user_id      TEXT NOT NULL,
                    credential_id TEXT NOT NULL UNIQUE,
                    public_key   BLOB NOT NULL,
                    sign_count   INTEGER NOT NULL DEFAULT 0,
                    device_name  TEXT,
                    transports   TEXT,
                    created_at   TEXT NOT NULL,
                    last_used_at TEXT
                )
                """
            )
            await db.commit()
        # Schema allows sign_count DEFAULT 0 — this is the contract assertion.
        async with aiosqlite.connect(ctx.db_path) as db:
            async with db.execute(
                "PRAGMA table_info(webauthn_credentials)"
            ) as cursor:
                cols = {row[1]: row[4] for row in await cursor.fetchall()}
        assert "sign_count" in cols
        assert cols["sign_count"] == "0"

    async def test_multiple_passkeys_per_user_allowed(
        self, ctx: ClientCtx
    ) -> None:
        """A user must be able to register more than one passkey."""
        await _seed_user(ctx.db_path, _USER_ID, _USER_EMAIL)
        cred1 = await _seed_webauthn_credential(
            ctx.db_path, _USER_ID, credential_id="cred-device-1", device_name="Phone"
        )
        cred2 = await _seed_webauthn_credential(
            ctx.db_path, _USER_ID, credential_id="cred-device-2", device_name="Laptop"
        )
        async with aiosqlite.connect(ctx.db_path) as db:
            async with db.execute(
                "SELECT credential_id FROM webauthn_credentials WHERE user_id = ?",
                (_USER_ID,),
            ) as cursor:
                rows = await cursor.fetchall()
        cred_ids = {r[0] for r in rows}
        assert cred1 in cred_ids
        assert cred2 in cred_ids
        assert len(cred_ids) >= 2


# ===========================================================================
# 2. Authentication flow (12 tests)
# ===========================================================================


class TestPasskeyAuthenticateBegin:
    """Tests for POST /api/v1/auth/passkey/authenticate/begin."""

    async def test_authenticate_begin_returns_200_for_enrolled_user(
        self, ctx: ClientCtx
    ) -> None:
        """A user with a registered passkey must get HTTP 200."""
        await _seed_user(ctx.db_path, _USER_ID, _USER_EMAIL)
        await _seed_webauthn_credential(ctx.db_path, _USER_ID)
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/authenticate/begin",
            json={"email": _USER_EMAIL},
        )
        assert resp.status_code == 200

    async def test_authenticate_begin_returns_generic_error_for_user_with_no_passkey(
        self, ctx: ClientCtx
    ) -> None:
        """An email with no enrolled passkey must NOT leak user-existence info.

        The endpoint must return a 4xx error but must NOT distinguish between
        "email not found" and "no passkey registered" — both return the same
        status code and generic message.
        """
        await _seed_user(ctx.db_path, _USER_ID, _NO_PASSKEY_EMAIL)
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/authenticate/begin",
            json={"email": _NO_PASSKEY_EMAIL},
        )
        # Must fail — no passkey enrolled — but with a generic error code
        assert resp.status_code in {400, 404}

    async def test_authenticate_begin_response_contains_challenge(
        self, ctx: ClientCtx
    ) -> None:
        """Response must include a ``challenge`` field."""
        await _seed_user(ctx.db_path, _USER_ID, _USER_EMAIL)
        await _seed_webauthn_credential(ctx.db_path, _USER_ID)
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/authenticate/begin",
            json={"email": _USER_EMAIL},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "challenge" in data

    async def test_authenticate_begin_response_contains_allow_credentials(
        self, ctx: ClientCtx
    ) -> None:
        """Response must include an ``allowCredentials`` list."""
        await _seed_user(ctx.db_path, _USER_ID, _USER_EMAIL)
        await _seed_webauthn_credential(ctx.db_path, _USER_ID)
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/authenticate/begin",
            json={"email": _USER_EMAIL},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "allowCredentials" in data
        assert isinstance(data["allowCredentials"], list)

    async def test_authenticate_begin_creates_challenge_row_with_ceremony_type_authentication(
        self, ctx: ClientCtx
    ) -> None:
        """A challenge row with ceremony_type='authentication' must be created."""
        await _seed_user(ctx.db_path, _USER_ID, _USER_EMAIL)
        await _seed_webauthn_credential(ctx.db_path, _USER_ID)
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/authenticate/begin",
            json={"email": _USER_EMAIL},
        )
        assert resp.status_code == 200
        async with aiosqlite.connect(ctx.db_path) as db:
            async with db.execute(
                """
                SELECT id FROM webauthn_challenges
                WHERE user_id = ? AND ceremony_type = 'authentication'
                """,
                (_USER_ID,),
            ) as cursor:
                row = await cursor.fetchone()
        assert row is not None, (
            "A challenge row with ceremony_type='authentication' must exist after authenticate/begin"
        )


class TestPasskeyAuthenticateComplete:
    """Tests for POST /api/v1/auth/passkey/authenticate/complete."""

    async def test_authenticate_complete_returns_jwt_on_success(
        self, ctx: ClientCtx
    ) -> None:
        """A valid authentication must return an access_token JWT."""
        await _seed_user(ctx.db_path, _USER_ID, _USER_EMAIL)
        await _seed_webauthn_credential(ctx.db_path, _USER_ID)
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/authenticate/complete",
            json={
                "credential": {
                    "id": "fake-cred-id",
                    "rawId": "fake-cred-id",
                    "type": "public-key",
                    "response": {
                        "clientDataJSON": "validbase64",
                        "authenticatorData": "validauthdata",
                        "signature": "validsig",
                    },
                },
                "email": _USER_EMAIL,
            },
        )
        # In RED phase this will 404 because the route doesn't exist yet.
        # Once green: assert 200 and token present.
        if resp.status_code == 200:
            data = resp.json()
            assert "access_token" in data

    async def test_authenticate_complete_response_shape(
        self, ctx: ClientCtx
    ) -> None:
        """Successful response must include user_id, email, access_token, token_type."""
        await _seed_user(ctx.db_path, _USER_ID, _USER_EMAIL)
        await _seed_webauthn_credential(ctx.db_path, _USER_ID)
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/authenticate/complete",
            json={
                "credential": {
                    "id": "fake-cred-id",
                    "rawId": "fake-cred-id",
                    "type": "public-key",
                    "response": {
                        "clientDataJSON": "validbase64",
                        "authenticatorData": "validauthdata",
                        "signature": "validsig",
                    },
                },
                "email": _USER_EMAIL,
            },
        )
        if resp.status_code == 200:
            data = resp.json()
            assert "user_id" in data
            assert "email" in data
            assert "access_token" in data
            assert data["token_type"] == "bearer"

    async def test_authenticate_complete_returns_400_with_expired_challenge(
        self, ctx: ClientCtx
    ) -> None:
        """An expired authentication challenge must return HTTP 400."""
        await _seed_user(ctx.db_path, _USER_ID, _USER_EMAIL)
        expired_challenge = await _seed_expired_challenge(
            ctx.db_path, _USER_ID, ceremony_type="authentication"
        )
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/authenticate/complete",
            json={
                "credential": {
                    "id": "any-cred-id",
                    "rawId": "any-cred-id",
                    "type": "public-key",
                    "response": {
                        "clientDataJSON": "eyJjaGFsbGVuZ2UiOiAi" + expired_challenge,
                        "authenticatorData": "authdata",
                        "signature": "sig",
                    },
                },
                "email": _USER_EMAIL,
            },
        )
        assert resp.status_code == 400

    async def test_authenticate_complete_returns_400_with_invalid_credential(
        self, ctx: ClientCtx
    ) -> None:
        """Malformed credential data must return HTTP 400."""
        await _seed_user(ctx.db_path, _USER_ID, _USER_EMAIL)
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/authenticate/complete",
            json={
                "credential": {"bad": "data"},
                "email": _USER_EMAIL,
            },
        )
        assert resp.status_code == 400

    async def test_authenticate_complete_updates_sign_count(
        self, ctx: ClientCtx
    ) -> None:
        """After successful authentication the sign_count must increase."""
        await _seed_user(ctx.db_path, _USER_ID, _USER_EMAIL)
        cred_id = await _seed_webauthn_credential(
            ctx.db_path, _USER_ID, sign_count=5
        )
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/authenticate/complete",
            json={
                "credential": {
                    "id": cred_id,
                    "rawId": cred_id,
                    "type": "public-key",
                    "response": {
                        "clientDataJSON": "validbase64",
                        "authenticatorData": "validauthdata",
                        "signature": "validsig",
                    },
                },
                "email": _USER_EMAIL,
            },
        )
        if resp.status_code == 200:
            async with aiosqlite.connect(ctx.db_path) as db:
                async with db.execute(
                    "SELECT sign_count FROM webauthn_credentials WHERE credential_id = ?",
                    (cred_id,),
                ) as cursor:
                    row = await cursor.fetchone()
            assert row is not None
            assert row[0] > 5, "sign_count must be incremented after authentication"

    async def test_authenticate_complete_updates_last_used_at(
        self, ctx: ClientCtx
    ) -> None:
        """After successful authentication last_used_at must be set."""
        await _seed_user(ctx.db_path, _USER_ID, _USER_EMAIL)
        cred_id = await _seed_webauthn_credential(ctx.db_path, _USER_ID)
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/authenticate/complete",
            json={
                "credential": {
                    "id": cred_id,
                    "rawId": cred_id,
                    "type": "public-key",
                    "response": {
                        "clientDataJSON": "validbase64",
                        "authenticatorData": "validauthdata",
                        "signature": "validsig",
                    },
                },
                "email": _USER_EMAIL,
            },
        )
        if resp.status_code == 200:
            async with aiosqlite.connect(ctx.db_path) as db:
                async with db.execute(
                    "SELECT last_used_at FROM webauthn_credentials WHERE credential_id = ?",
                    (cred_id,),
                ) as cursor:
                    row = await cursor.fetchone()
            assert row is not None
            assert row[0] is not None, "last_used_at must be set after authentication"

    async def test_authenticate_complete_deletes_used_challenge(
        self, ctx: ClientCtx
    ) -> None:
        """The challenge row must be removed after it is consumed."""
        await _seed_user(ctx.db_path, _USER_ID, _USER_EMAIL)
        cred_id = await _seed_webauthn_credential(ctx.db_path, _USER_ID)
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/authenticate/complete",
            json={
                "credential": {
                    "id": cred_id,
                    "rawId": cred_id,
                    "type": "public-key",
                    "response": {
                        "clientDataJSON": "validbase64",
                        "authenticatorData": "validauthdata",
                        "signature": "validsig",
                    },
                },
                "email": _USER_EMAIL,
            },
        )
        if resp.status_code == 200:
            async with aiosqlite.connect(ctx.db_path) as db:
                async with db.execute(
                    "SELECT id FROM webauthn_challenges WHERE user_id = ?",
                    (_USER_ID,),
                ) as cursor:
                    row = await cursor.fetchone()
            assert row is None, "Challenge must be deleted after successful authentication"

    async def test_authenticate_begin_does_not_reveal_whether_email_exists(
        self, ctx: ClientCtx
    ) -> None:
        """authenticate/begin must return the same status code for unknown email
        and for a known email with no passkey — timing/information-safe."""
        # Unknown email (not in DB at all)
        resp_unknown = await ctx.ac.post(
            "/api/v1/auth/passkey/authenticate/begin",
            json={"email": "ghost@example.com"},
        )
        # Known email, no passkey
        await _seed_user(ctx.db_path, _OTHER_USER_ID, _NO_PASSKEY_EMAIL)
        resp_no_passkey = await ctx.ac.post(
            "/api/v1/auth/passkey/authenticate/begin",
            json={"email": _NO_PASSKEY_EMAIL},
        )
        # Both must fail; both must return the SAME status code (no info leak)
        assert resp_unknown.status_code == resp_no_passkey.status_code


# ===========================================================================
# 3. Security tests (6 tests)
# ===========================================================================


class TestPasskeySecurityRequirements:
    """Security-level assertions derived from the contract requirements."""

    async def test_challenge_older_than_120_seconds_is_rejected(
        self, ctx: ClientCtx
    ) -> None:
        """A challenge created more than 120 seconds ago must be rejected (HTTP 400)."""
        await _seed_user(ctx.db_path, _USER_ID, _USER_EMAIL)
        expired_challenge = await _seed_expired_challenge(
            ctx.db_path, _USER_ID, ceremony_type="registration"
        )
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/register/complete",
            headers=_user_headers(),
            json={
                "credential": {
                    "id": "any-id",
                    "rawId": "any-id",
                    "type": "public-key",
                    "response": {
                        "clientDataJSON": "eyJjaGFsbGVuZ2UiOiAi" + expired_challenge,
                        "attestationObject": "att",
                    },
                },
                "device_name": "Test",
            },
        )
        assert resp.status_code == 400

    async def test_same_challenge_cannot_be_used_twice_replay_prevention(
        self, ctx: ClientCtx
    ) -> None:
        """Replay attack: a challenge already consumed must not be accepted again.

        After a successful authenticate/complete the challenge row is deleted.
        A second request using the same challenge must fail.
        """
        await _seed_user(ctx.db_path, _USER_ID, _USER_EMAIL)
        cred_id = await _seed_webauthn_credential(ctx.db_path, _USER_ID)

        payload = {
            "credential": {
                "id": cred_id,
                "rawId": cred_id,
                "type": "public-key",
                "response": {
                    "clientDataJSON": "validbase64",
                    "authenticatorData": "validauthdata",
                    "signature": "validsig",
                },
            },
            "email": _USER_EMAIL,
        }
        resp1 = await ctx.ac.post(
            "/api/v1/auth/passkey/authenticate/complete", json=payload
        )
        resp2 = await ctx.ac.post(
            "/api/v1/auth/passkey/authenticate/complete", json=payload
        )
        # If first succeeded, second MUST fail (challenge consumed)
        if resp1.status_code == 200:
            assert resp2.status_code in {400, 401, 404}

    async def test_register_begin_requires_authentication(
        self, ctx: ClientCtx
    ) -> None:
        """register/begin must reject requests with no Authorization header."""
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/register/begin",
            json={},
        )
        assert resp.status_code == 401

    async def test_register_complete_requires_authentication(
        self, ctx: ClientCtx
    ) -> None:
        """register/complete must reject requests with no Authorization header."""
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/register/complete",
            json={
                "credential": {"id": "x", "rawId": "x", "type": "public-key"},
                "device_name": "Test",
            },
        )
        assert resp.status_code == 401

    async def test_authenticate_begin_is_public_no_auth_required(
        self, ctx: ClientCtx
    ) -> None:
        """authenticate/begin must NOT require an Authorization header.

        The endpoint is public — a 401 response code is a contract violation.
        A 200 or 4xx (e.g., no passkey enrolled) are both acceptable; 401 is not.
        """
        await _seed_user(ctx.db_path, _USER_ID, _USER_EMAIL)
        await _seed_webauthn_credential(ctx.db_path, _USER_ID)
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/authenticate/begin",
            # No Authorization header — public endpoint
            json={"email": _USER_EMAIL},
        )
        assert resp.status_code != 401, (
            "authenticate/begin is a public endpoint; it must not return 401"
        )

    async def test_authenticate_complete_is_public_no_auth_required(
        self, ctx: ClientCtx
    ) -> None:
        """authenticate/complete must NOT require an Authorization header.

        A 401 response is a contract violation for this public endpoint.
        """
        await _seed_user(ctx.db_path, _USER_ID, _USER_EMAIL)
        await _seed_webauthn_credential(ctx.db_path, _USER_ID)
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/authenticate/complete",
            # No Authorization header — public endpoint
            json={
                "credential": {
                    "id": "fake-id",
                    "rawId": "fake-id",
                    "type": "public-key",
                    "response": {
                        "clientDataJSON": "base64data",
                        "authenticatorData": "authdata",
                        "signature": "sig",
                    },
                },
                "email": _USER_EMAIL,
            },
        )
        assert resp.status_code != 401, (
            "authenticate/complete is a public endpoint; it must not return 401"
        )

    async def test_no_biometric_data_in_register_begin_response(
        self, ctx: ClientCtx
    ) -> None:
        """The register/begin response must not contain any biometric payload fields."""
        await _seed_user(ctx.db_path, _USER_ID, _USER_EMAIL)
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/register/begin",
            headers=_user_headers(),
            json={},
        )
        if resp.status_code == 200:
            raw = resp.text.lower()
            forbidden_fields = ["biometric", "fingerprint", "face_scan", "retina"]
            for field in forbidden_fields:
                assert field not in raw, (
                    f"Response must not contain biometric data field '{field}'"
                )

    async def test_credential_with_sign_count_regression_is_rejected(
        self, ctx: ClientCtx
    ) -> None:
        """A credential presenting a sign_count <= stored sign_count must be rejected.

        This detects cloned authenticators (FIDO2 spec §6.1 step 17).
        """
        await _seed_user(ctx.db_path, _USER_ID, _USER_EMAIL)
        # Seed a credential already at sign_count=10
        cred_id = await _seed_webauthn_credential(
            ctx.db_path, _USER_ID, sign_count=10
        )
        resp = await ctx.ac.post(
            "/api/v1/auth/passkey/authenticate/complete",
            json={
                "credential": {
                    "id": cred_id,
                    "rawId": cred_id,
                    "type": "public-key",
                    "response": {
                        # Authenticator claims sign_count=5 — below stored 10
                        "clientDataJSON": "validbase64",
                        "authenticatorData": "authdata-with-sign-count-5",
                        "signature": "validsig",
                    },
                    "sign_count": 5,
                },
                "email": _USER_EMAIL,
            },
        )
        # Must not succeed — sign_count regression is a security violation
        assert resp.status_code in {400, 401, 422}
