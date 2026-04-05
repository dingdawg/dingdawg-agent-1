"""Tests for the full MFA/2FA implementation.

Coverage:
- POST /auth/mfa/setup        — generate TOTP secret
- POST /auth/mfa/verify-setup — confirm TOTP + activate + return backup codes
- POST /auth/mfa/challenge    — TOTP / backup / SMS code verification during login
- POST /auth/mfa/sms          — send SMS OTP (Telnyx, mocked)
- POST /auth/mfa/disable      — disable MFA with password + TOTP
- GET  /auth/mfa/status       — MFA status for authenticated user
- POST /auth/mfa/phone        — register phone number
- Login flow: mfa_required response when MFA is enabled
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from isg_agent.app import create_app
from tests.conftest import verify_user_email

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PASSWORD = "Secure#Pass1"
_SECRET_KEY = "test-secret-do-not-use-in-production"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique_email() -> str:
    """Generate a unique email per call to avoid cross-test DB collisions."""
    return f"mfa_{uuid.uuid4().hex[:8]}@dingdawg.com"


async def _register_and_verify(
    client: AsyncClient, db_path: str
) -> tuple[str, str]:
    """Register user, verify email, return (access_token, email)."""
    email = _unique_email()
    reg = await client.post(
        "/auth/register",
        json={
            "email": email,
            "password": _PASSWORD,
            "terms_accepted": True,
            "terms_accepted_at": "2026-01-01T00:00:00Z",
        },
    )
    assert reg.status_code == 201, f"register failed: {reg.text}"
    await verify_user_email(db_path, email)
    login = await client.post("/auth/login", json={"email": email, "password": _PASSWORD})
    assert login.status_code == 200, f"login failed: {login.text}"
    return login.json()["access_token"], email


async def _enable_mfa(
    client: AsyncClient, token: str
) -> tuple[str, list[str]]:
    """Complete MFA setup. Returns (totp_secret, backup_codes)."""
    import pyotp

    setup_resp = await client.post(
        "/auth/mfa/setup",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert setup_resp.status_code == 200, setup_resp.text
    secret = setup_resp.json()["secret"]

    code = pyotp.TOTP(secret).now()
    verify_resp = await client.post(
        "/auth/mfa/verify-setup",
        headers={"Authorization": f"Bearer {token}"},
        json={"secret": secret, "code": code},
    )
    assert verify_resp.status_code == 200, verify_resp.text
    backup_codes: list[str] = verify_resp.json()["backup_codes"]
    assert len(backup_codes) == 10
    return secret, backup_codes


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client_with_db(tmp_path):
    """AsyncClient + db_path for MFA tests.

    Uses the lifespan context manager pattern (same as test_security_edge_cases.py)
    to ensure app.py wires _set_auth_config, _set_passkey_config, etc. before tests run.
    """
    from isg_agent.config import get_settings
    from isg_agent.app import create_app as _create_app, lifespan

    db_path = str(tmp_path / "test.db")
    prev_env: dict[str, str | None] = {}

    overrides = {
        "ISG_AGENT_DB_PATH": db_path,
        "ISG_AGENT_SECRET_KEY": _SECRET_KEY,
        "ISG_AGENT_DEPLOYMENT_ENV": "test",
    }
    for k, v in overrides.items():
        prev_env[k] = os.environ.get(k)
        os.environ[k] = v

    get_settings.cache_clear()

    app = _create_app()

    try:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                yield c, db_path
    finally:
        for k, original in prev_env.items():
            if original is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = original
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Tests: setup flow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mfa_setup_requires_bearer(client_with_db):
    """POST /auth/mfa/setup without Bearer → 401."""
    client, _ = client_with_db
    resp = await client.post("/auth/mfa/setup", json={})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_mfa_setup_returns_secret_and_uri(client_with_db):
    """POST /auth/mfa/setup with valid Bearer returns secret + otpauth URI."""
    client, db_path = client_with_db
    token, _ = await _register_and_verify(client, db_path)

    resp = await client.post(
        "/auth/mfa/setup",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "secret" in data
    assert data["otpauth_uri"].startswith("otpauth://totp/")
    assert "DingDawg" in data["otpauth_uri"]


@pytest.mark.asyncio
async def test_mfa_verify_setup_activates_mfa_and_returns_backup_codes(client_with_db):
    """Full setup flow activates MFA and returns 10 backup codes."""
    client, db_path = client_with_db
    token, _ = await _register_and_verify(client, db_path)
    secret, backup_codes = await _enable_mfa(client, token)

    assert len(backup_codes) == 10
    for code in backup_codes:
        assert len(code) == 8  # 8-char hex

    status_resp = await client.get(
        "/auth/mfa/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status_resp.status_code == 200
    assert status_resp.json()["mfa_enabled"] is True
    assert status_resp.json()["backup_codes_remaining"] == 10


@pytest.mark.asyncio
async def test_mfa_verify_setup_rejects_wrong_code(client_with_db):
    """POST /auth/mfa/verify-setup with wrong code → 400."""
    client, db_path = client_with_db
    token, _ = await _register_and_verify(client, db_path)

    setup_resp = await client.post(
        "/auth/mfa/setup",
        headers={"Authorization": f"Bearer {token}"},
    )
    secret = setup_resp.json()["secret"]

    verify_resp = await client.post(
        "/auth/mfa/verify-setup",
        headers={"Authorization": f"Bearer {token}"},
        json={"secret": secret, "code": "000000"},
    )
    assert verify_resp.status_code == 400


# ---------------------------------------------------------------------------
# Tests: login challenge flow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_login_returns_mfa_challenge_when_mfa_enabled(client_with_db):
    """Login returns mfa_required=True + challenge_token when MFA is active."""
    client, db_path = client_with_db
    token, email = await _register_and_verify(client, db_path)
    await _enable_mfa(client, token)

    login_resp = await client.post(
        "/auth/login", json={"email": email, "password": _PASSWORD}
    )
    assert login_resp.status_code == 200
    data = login_resp.json()
    assert data["mfa_required"] is True
    assert data["access_token"] == ""
    assert data.get("mfa_challenge_token")


@pytest.mark.asyncio
async def test_mfa_challenge_totp_success(client_with_db):
    """POST /auth/mfa/challenge with valid TOTP issues real access token."""
    import pyotp
    client, db_path = client_with_db
    token, email = await _register_and_verify(client, db_path)
    secret, _ = await _enable_mfa(client, token)

    login_resp = await client.post(
        "/auth/login", json={"email": email, "password": _PASSWORD}
    )
    challenge_token = login_resp.json()["mfa_challenge_token"]

    resp = await client.post(
        "/auth/mfa/challenge",
        json={
            "challenge_token": challenge_token,
            "code": pyotp.TOTP(secret).now(),
            "code_type": "totp",
            "remember_device": False,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["access_token"]
    assert data["user_id"]
    assert data["email"] == email


@pytest.mark.asyncio
async def test_mfa_challenge_totp_wrong_code_rejected(client_with_db):
    """POST /auth/mfa/challenge with wrong TOTP → 400."""
    client, db_path = client_with_db
    token, email = await _register_and_verify(client, db_path)
    await _enable_mfa(client, token)

    login_resp = await client.post(
        "/auth/login", json={"email": email, "password": _PASSWORD}
    )
    challenge_token = login_resp.json()["mfa_challenge_token"]

    resp = await client.post(
        "/auth/mfa/challenge",
        json={
            "challenge_token": challenge_token,
            "code": "000000",
            "code_type": "totp",
            "remember_device": False,
        },
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_mfa_challenge_backup_code_success_and_consumed(client_with_db):
    """Backup code works once and is consumed on use."""
    client, db_path = client_with_db
    token, email = await _register_and_verify(client, db_path)
    _, backup_codes = await _enable_mfa(client, token)

    # Use first backup code
    login_resp = await client.post(
        "/auth/login", json={"email": email, "password": _PASSWORD}
    )
    challenge_token = login_resp.json()["mfa_challenge_token"]

    resp = await client.post(
        "/auth/mfa/challenge",
        json={
            "challenge_token": challenge_token,
            "code": backup_codes[0],
            "code_type": "backup",
            "remember_device": False,
        },
    )
    assert resp.status_code == 200, resp.text

    # Status should show 9 remaining
    new_token = resp.json()["access_token"]
    status_resp = await client.get(
        "/auth/mfa/status",
        headers={"Authorization": f"Bearer {new_token}"},
    )
    assert status_resp.json()["backup_codes_remaining"] == 9

    # Reuse same code → 400
    login_resp2 = await client.post(
        "/auth/login", json={"email": email, "password": _PASSWORD}
    )
    challenge_token2 = login_resp2.json()["mfa_challenge_token"]

    resp2 = await client.post(
        "/auth/mfa/challenge",
        json={
            "challenge_token": challenge_token2,
            "code": backup_codes[0],  # already consumed
            "code_type": "backup",
            "remember_device": False,
        },
    )
    assert resp2.status_code == 400


@pytest.mark.asyncio
async def test_mfa_challenge_invalid_challenge_token_rejected(client_with_db):
    """POST /auth/mfa/challenge with tampered challenge token → 401."""
    client, _ = client_with_db
    resp = await client.post(
        "/auth/mfa/challenge",
        json={
            "challenge_token": "not.a.valid.jwt",
            "code": "123456",
            "code_type": "totp",
            "remember_device": False,
        },
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tests: disable
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mfa_disable_requires_correct_password(client_with_db):
    """POST /auth/mfa/disable with wrong password → 401."""
    import pyotp
    client, db_path = client_with_db
    token, _ = await _register_and_verify(client, db_path)
    secret, _ = await _enable_mfa(client, token)

    resp = await client.post(
        "/auth/mfa/disable",
        headers={"Authorization": f"Bearer {token}"},
        json={"password": "WrongPass1!", "totp_code": pyotp.TOTP(secret).now()},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_mfa_disable_success(client_with_db):
    """POST /auth/mfa/disable with correct creds disables MFA."""
    import pyotp
    client, db_path = client_with_db
    token, email = await _register_and_verify(client, db_path)
    secret, _ = await _enable_mfa(client, token)

    resp = await client.post(
        "/auth/mfa/disable",
        headers={"Authorization": f"Bearer {token}"},
        json={"password": _PASSWORD, "totp_code": pyotp.TOTP(secret).now()},
    )
    assert resp.status_code == 200, resp.text

    # Status should now show disabled
    status_resp = await client.get(
        "/auth/mfa/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status_resp.json()["mfa_enabled"] is False

    # Login should return direct token (no MFA challenge)
    login_resp = await client.post(
        "/auth/login", json={"email": email, "password": _PASSWORD}
    )
    assert login_resp.status_code == 200
    assert not login_resp.json().get("mfa_required", False)
    assert login_resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Tests: phone registration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_phone_registration_requires_e164(client_with_db):
    """POST /auth/mfa/phone with invalid format → 400."""
    client, db_path = client_with_db
    token, _ = await _register_and_verify(client, db_path)

    resp = await client.post(
        "/auth/mfa/phone",
        headers={"Authorization": f"Bearer {token}"},
        json={"phone_number": "5551234"},  # no + country prefix
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_phone_registration_valid_e164(client_with_db):
    """POST /auth/mfa/phone with valid E.164 → 200 + status shows has_phone."""
    client, db_path = client_with_db
    token, _ = await _register_and_verify(client, db_path)

    resp = await client.post(
        "/auth/mfa/phone",
        headers={"Authorization": f"Bearer {token}"},
        json={"phone_number": "+12125551234"},
    )
    assert resp.status_code == 200

    status_resp = await client.get(
        "/auth/mfa/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status_resp.json()["has_phone"] is True


# ---------------------------------------------------------------------------
# Tests: status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mfa_status_unauthenticated_rejected(client_with_db):
    """GET /auth/mfa/status without Bearer → 401."""
    client, _ = client_with_db
    resp = await client.get("/auth/mfa/status")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_mfa_status_returns_disabled_for_new_user(client_with_db):
    """New user has MFA disabled by default."""
    client, db_path = client_with_db
    token, _ = await _register_and_verify(client, db_path)

    resp = await client.get(
        "/auth/mfa/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["mfa_enabled"] is False
    assert data["has_phone"] is False
    assert data["backup_codes_remaining"] == 0


# ---------------------------------------------------------------------------
# Tests: SMS (Telnyx mocked / skipped — no API key in tests)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mfa_sms_requires_valid_challenge_token(client_with_db):
    """POST /auth/mfa/sms with invalid token → 401."""
    client, _ = client_with_db
    resp = await client.post(
        "/auth/mfa/sms",
        json={"challenge_token": "bad.token.here"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_mfa_sms_no_phone_registered_returns_400(client_with_db):
    """SMS send when no phone registered → 400."""
    client, db_path = client_with_db
    token, email = await _register_and_verify(client, db_path)
    await _enable_mfa(client, token)

    login_resp = await client.post(
        "/auth/login", json={"email": email, "password": _PASSWORD}
    )
    challenge_token = login_resp.json()["mfa_challenge_token"]

    resp = await client.post(
        "/auth/mfa/sms",
        json={"challenge_token": challenge_token},
    )
    assert resp.status_code == 400
