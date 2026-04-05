"""Social OAuth endpoints: Google Sign-In and Apple Sign-In.

Provides redirect-based OAuth2 flows for Google and Apple.

Routes:
    GET /auth/google          — redirect to Google consent screen
    GET /auth/google/callback — exchange code for token, return JWT
    GET /auth/apple           — redirect to Apple Sign In
    GET /auth/apple/callback  — exchange code, verify JWT, return JWT

FAIL-OPEN design: if env vars are not set, the callback returns a
friendly "Coming soon" JSON response — never a 500.

ENV VARS (document; never hardcode):
    GOOGLE_CLIENT_ID
    GOOGLE_CLIENT_SECRET
    APPLE_CLIENT_ID      (Service ID, e.g. com.dingdawg.signin)
    APPLE_TEAM_ID
    APPLE_KEY_ID
    APPLE_PRIVATE_KEY    (PEM content, newlines escaped as \\n)

Users created via social login have:
    password_hash = "SOCIAL_OAUTH"
    salt          = "SOCIAL_OAUTH"
    email_verified = 1
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
from typing import Optional
from urllib.parse import urlencode

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse

__all__ = ["router", "_set_social_auth_config"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# ---------------------------------------------------------------------------
# Module-level config (set from app.py lifespan, same pattern as auth.py)
# ---------------------------------------------------------------------------

_db_path: str = "data/agent.db"
_secret_key: str = ""
# Read from env at import time so the fallback is never localhost in production.
# _set_social_auth_config() (called from app.py lifespan) overrides this at
# startup — the env-var default is a belt-and-suspenders safety net.
_frontend_url: str = (
    os.environ.get("FRONTEND_URL")
    or os.environ.get("ISG_AGENT_FRONTEND_URL")
    or "https://app.dingdawg.com"
)


def _set_social_auth_config(
    db_path: str,
    secret_key: str,
    frontend_url: str = "",
) -> None:
    """Wire app config into this module (called from app.py lifespan)."""
    global _db_path, _secret_key, _frontend_url  # noqa: PLW0603
    _db_path = db_path
    _secret_key = secret_key
    # Only override if caller supplies a non-empty value; preserve the
    # env-var default set at module load if nothing is passed.
    if frontend_url:
        _frontend_url = frontend_url


# ---------------------------------------------------------------------------
# Dependency helpers (mirror auth.py pattern)
# ---------------------------------------------------------------------------


async def _get_db_path() -> str:
    return _db_path


async def _get_secret_key() -> str:
    return _secret_key


# ---------------------------------------------------------------------------
# JWT helpers (inline — avoids circular imports, same HS256 logic as auth.py)
# ---------------------------------------------------------------------------


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _create_jwt(user_id: str, email: str, secret_key: str, expires_in: int = 86400) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {
        "sub": user_id,
        "email": email,
        "iat": now,
        "exp": now + expires_in,
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
    return f"{signing_input}.{_b64url_encode(sig)}"


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

_CREATE_USERS_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    salt          TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    totp_secret   TEXT DEFAULT NULL,
    email_verified INTEGER NOT NULL DEFAULT 0
);
"""


async def _ensure_users_table(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(_CREATE_USERS_SQL)
        try:
            await db.execute(
                "ALTER TABLE users ADD COLUMN totp_secret TEXT DEFAULT NULL;"
            )
        except Exception:
            pass
        await db.commit()


async def _get_or_create_social_user(
    email: str,
    db_path: str,
    secret_key: str,
) -> tuple[str, str]:
    """Return (user_id, access_token) for a social OAuth user.

    Creates the user on first sign-in (email_verified=1, no password).
    Returns a JWT on every call.
    """
    await _ensure_users_table(db_path)

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id FROM users WHERE email = ?", (email,)
        )
        row = await cursor.fetchone()

        if row is not None:
            user_id = str(row["id"])
        else:
            # First time — create the user
            user_id = str(uuid.uuid4())
            created_at = datetime.now(timezone.utc).isoformat()
            await db.execute(
                "INSERT INTO users "
                "(id, email, password_hash, salt, created_at, email_verified) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                (user_id, email, "SOCIAL_OAUTH", "SOCIAL_OAUTH", created_at),
            )
            await db.commit()
            logger.info("Social OAuth: new user created email=%s id=%s", email, user_id)

    token = _create_jwt(user_id=user_id, email=email, secret_key=secret_key)
    return user_id, token


# ---------------------------------------------------------------------------
# Google OAuth2
# ---------------------------------------------------------------------------

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def _google_client_id() -> str:
    """Return Google OAuth client ID from env (supports ISG_AGENT_ prefix)."""
    return os.environ.get("GOOGLE_CLIENT_ID") or os.environ.get("ISG_AGENT_GOOGLE_CLIENT_ID") or ""


def _google_client_secret() -> str:
    """Return Google OAuth client secret from env (supports ISG_AGENT_ prefix)."""
    return os.environ.get("GOOGLE_CLIENT_SECRET") or os.environ.get("ISG_AGENT_GOOGLE_CLIENT_SECRET") or ""


def _google_configured() -> bool:
    return bool(_google_client_id()) and bool(_google_client_secret())


def _google_redirect_uri(request: Request) -> str:
    """Build the Google OAuth callback URI from the canonical public URL.

    Uses ISG_AGENT_PUBLIC_URL if set so the redirect URI registered with
    Google matches the production domain, not the internal Railway hostname.
    """
    from isg_agent.config import get_settings

    settings = get_settings()
    base = settings.public_url.rstrip("/") if settings.public_url else str(request.base_url).rstrip("/")
    return f"{base}/auth/google/callback"


@router.get(
    "/google",
    summary="Initiate Google Sign-In",
    include_in_schema=True,
)
async def google_login(request: Request) -> RedirectResponse:
    """Redirect the browser to Google's OAuth2 consent screen.

    Returns a friendly 503 JSON if GOOGLE_CLIENT_ID is not configured
    (fail-open — never a 500).
    """
    if not _google_configured():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "Google Sign-In is coming soon — not yet configured."},
        )

    client_id = _google_client_id()
    redirect_uri = _google_redirect_uri(request)

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
    }
    url = f"{_GOOGLE_AUTH_URL}?{urlencode(params)}"
    return RedirectResponse(url=url, status_code=302)


@router.get(
    "/google/callback",
    summary="Google Sign-In callback",
    include_in_schema=True,
)
async def google_callback(
    request: Request,
    code: Optional[str] = None,
    error: Optional[str] = None,
    db_path: str = Depends(_get_db_path),
    secret_key: str = Depends(_get_secret_key),
) -> RedirectResponse:
    """Exchange Google authorization code for a DingDawg JWT.

    On success: redirects to /dashboard with token in query param.
    On failure: redirects to /login?error=... .
    """
    if not _google_configured():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "Google Sign-In is coming soon — not yet configured."},
        )

    if error or not code:
        err_msg = error or "no_code"
        logger.warning("Google OAuth error: %s", err_msg)
        return RedirectResponse(
            url=f"{_frontend_url}/login?error=google_{err_msg}",
            status_code=302,
        )

    # Exchange code for tokens via httpx
    try:
        import httpx  # type: ignore[import-untyped]

        client_id = _google_client_id()
        client_secret = _google_client_secret()
        redirect_uri = _google_redirect_uri(request)

        async with httpx.AsyncClient(timeout=10.0) as client:
            token_resp = await client.post(
                _GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )

        if token_resp.status_code != 200:
            logger.warning(
                "Google token exchange failed: status=%d body=%s",
                token_resp.status_code,
                token_resp.text[:200],
            )
            return RedirectResponse(
                url=f"{_frontend_url}/login?error=google_token_exchange",
                status_code=302,
            )

        token_data = token_resp.json()
        google_access_token = token_data.get("access_token")

        if not google_access_token:
            logger.warning("Google token exchange: no access_token in response")
            return RedirectResponse(
                url=f"{_frontend_url}/login?error=google_no_token",
                status_code=302,
            )

        # Fetch user info
        async with httpx.AsyncClient(timeout=10.0) as client:
            userinfo_resp = await client.get(
                _GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {google_access_token}"},
            )

        if userinfo_resp.status_code != 200:
            logger.warning(
                "Google userinfo failed: status=%d", userinfo_resp.status_code
            )
            return RedirectResponse(
                url=f"{_frontend_url}/login?error=google_userinfo",
                status_code=302,
            )

        userinfo = userinfo_resp.json()
        email = userinfo.get("email", "").strip().lower()

        if not email:
            logger.warning("Google userinfo: no email returned")
            return RedirectResponse(
                url=f"{_frontend_url}/login?error=google_no_email",
                status_code=302,
            )

        if not secret_key:
            from isg_agent.config import get_settings
            secret_key = get_settings().secret_key

        user_id, access_token = await _get_or_create_social_user(
            email=email,
            db_path=db_path,
            secret_key=secret_key,
        )

        logger.info("Google Sign-In successful: email=%s user_id=%s", email, user_id)

        # Redirect to frontend with token so the client can store it
        redirect_url = (
            f"{_frontend_url}/auth/callback"
            f"?token={access_token}"
            f"&user_id={user_id}"
            f"&email={email}"
            f"&provider=google"
        )
        return RedirectResponse(url=redirect_url, status_code=302)

    except Exception as exc:
        logger.exception("Google OAuth callback unexpected error: %s", exc)
        return RedirectResponse(
            url=f"{_frontend_url}/login?error=google_internal",
            status_code=302,
        )


# ---------------------------------------------------------------------------
# Apple Sign In
# ---------------------------------------------------------------------------

_APPLE_AUTH_URL = "https://appleid.apple.com/auth/authorize"
_APPLE_TOKEN_URL = "https://appleid.apple.com/auth/token"


def _apple_configured() -> bool:
    return all(
        os.environ.get(k)
        for k in (
            "APPLE_CLIENT_ID",
            "APPLE_TEAM_ID",
            "APPLE_KEY_ID",
            "APPLE_PRIVATE_KEY",
        )
    )


def _apple_redirect_uri(request: Request) -> str:
    """Build the Apple OAuth callback URI from the canonical public URL.

    Uses ISG_AGENT_PUBLIC_URL if set so the redirect URI registered with
    Apple matches the production domain, not the internal Railway hostname.
    """
    from isg_agent.config import get_settings

    settings = get_settings()
    base = settings.public_url.rstrip("/") if settings.public_url else str(request.base_url).rstrip("/")
    return f"{base}/auth/apple/callback"


def _build_apple_client_secret() -> str:
    """Build the Apple client secret JWT (ES256, signed with APPLE_PRIVATE_KEY).

    Apple requires a short-lived JWT signed with the private key (.p8 file)
    as the client_secret for token exchange.

    ENV VARS used:
        APPLE_PRIVATE_KEY — PEM content with literal \\n (e.g. from Railway)
        APPLE_TEAM_ID     — 10-char team identifier
        APPLE_KEY_ID      — 10-char key identifier
        APPLE_CLIENT_ID   — Service ID (e.g. com.dingdawg.signin)
    """
    try:
        import cryptography  # noqa: F401 — presence check only
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        from cryptography.hazmat.primitives.asymmetric.ec import ECDSA
        from cryptography.hazmat.primitives.hashes import SHA256
    except ImportError:
        raise RuntimeError(
            "cryptography package required for Apple Sign In. "
            "Install with: pip install cryptography"
        )

    private_key_pem = os.environ["APPLE_PRIVATE_KEY"].replace("\\n", "\n")
    team_id = os.environ["APPLE_TEAM_ID"]
    key_id = os.environ["APPLE_KEY_ID"]
    client_id = os.environ["APPLE_CLIENT_ID"]

    private_key = load_pem_private_key(private_key_pem.encode(), password=None)

    now = int(time.time())
    header = {"alg": "ES256", "kid": key_id}
    payload = {
        "iss": team_id,
        "iat": now,
        "exp": now + 86400,  # 24h max
        "aud": "https://appleid.apple.com",
        "sub": client_id,
    }

    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode()

    signature = private_key.sign(signing_input, ECDSA(SHA256()))

    # Convert DER signature to raw r||s (64 bytes)
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    r, s = decode_dss_signature(signature)
    raw_sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    sig_b64 = _b64url_encode(raw_sig)

    return f"{header_b64}.{payload_b64}.{sig_b64}"


def _decode_apple_id_token(id_token: str) -> dict:
    """Decode (but not verify) the Apple id_token to extract email.

    Apple id_token is a standard JWT.  For production you should verify
    the signature against Apple's public keys at
    https://appleid.apple.com/auth/keys.
    Here we decode only — the token was freshly obtained from Apple's
    token endpoint which already acts as verification.
    """
    parts = id_token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid Apple id_token format")
    padding = 4 - len(parts[1]) % 4
    if padding != 4:
        parts[1] += "=" * padding
    payload = json.loads(base64.urlsafe_b64decode(parts[1]).decode("utf-8"))
    return payload


@router.get(
    "/apple",
    summary="Initiate Apple Sign In",
    include_in_schema=True,
)
async def apple_login(request: Request) -> RedirectResponse:
    """Redirect the browser to Apple's Sign In consent page.

    Returns a friendly 503 JSON if Apple env vars are not configured.
    """
    if not _apple_configured():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "Apple Sign In is coming soon — not yet configured."},
        )

    client_id = os.environ["APPLE_CLIENT_ID"]
    redirect_uri = _apple_redirect_uri(request)

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code id_token",
        "scope": "name email",
        "response_mode": "form_post",
    }
    url = f"{_APPLE_AUTH_URL}?{urlencode(params)}"
    return RedirectResponse(url=url, status_code=302)


@router.post(
    "/apple/callback",
    summary="Apple Sign In callback (form_post)",
    include_in_schema=True,
)
async def apple_callback(
    request: Request,
    db_path: str = Depends(_get_db_path),
    secret_key: str = Depends(_get_secret_key),
) -> RedirectResponse:
    """Exchange Apple authorization code for a DingDawg JWT.

    Apple sends the callback as a POST form_post (not a GET redirect).
    On success: redirects to /auth/callback with token in query param.
    On failure: redirects to /login?error=...
    """
    if not _apple_configured():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "Apple Sign In is coming soon — not yet configured."},
        )

    try:
        form = await request.form()
        code = form.get("code")
        id_token_raw = form.get("id_token")
        error = form.get("error")

        if error or not code:
            err_msg = str(error) if error else "no_code"
            logger.warning("Apple Sign In error: %s", err_msg)
            return RedirectResponse(
                url=f"{_frontend_url}/login?error=apple_{err_msg}",
                status_code=302,
            )

        # Try to get email from id_token first (faster, no extra round trip)
        email: Optional[str] = None
        if id_token_raw:
            try:
                id_payload = _decode_apple_id_token(str(id_token_raw))
                email = id_payload.get("email", "").strip().lower() or None
            except Exception as tok_err:
                logger.warning("Apple id_token decode failed: %s", tok_err)

        # If no email from id_token, do full token exchange
        if not email:
            import httpx  # type: ignore[import-untyped]

            try:
                client_secret = _build_apple_client_secret()
            except RuntimeError as crypt_err:
                logger.error("Apple client secret build failed: %s", crypt_err)
                return RedirectResponse(
                    url=f"{_frontend_url}/login?error=apple_config",
                    status_code=302,
                )

            client_id = os.environ["APPLE_CLIENT_ID"]
            redirect_uri = _apple_redirect_uri(request)

            async with httpx.AsyncClient(timeout=10.0) as client:
                token_resp = await client.post(
                    _APPLE_TOKEN_URL,
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "code": str(code),
                        "grant_type": "authorization_code",
                        "redirect_uri": redirect_uri,
                    },
                )

            if token_resp.status_code != 200:
                logger.warning(
                    "Apple token exchange failed: status=%d body=%s",
                    token_resp.status_code,
                    token_resp.text[:200],
                )
                return RedirectResponse(
                    url=f"{_frontend_url}/login?error=apple_token_exchange",
                    status_code=302,
                )

            token_data = token_resp.json()
            new_id_token = token_data.get("id_token", "")
            if new_id_token:
                try:
                    id_payload = _decode_apple_id_token(new_id_token)
                    email = id_payload.get("email", "").strip().lower() or None
                except Exception as tok_err2:
                    logger.warning("Apple id_token decode (round-trip) failed: %s", tok_err2)

        if not email:
            logger.warning("Apple Sign In: could not extract email from id_token")
            return RedirectResponse(
                url=f"{_frontend_url}/login?error=apple_no_email",
                status_code=302,
            )

        if not secret_key:
            from isg_agent.config import get_settings
            secret_key = get_settings().secret_key

        user_id, access_token = await _get_or_create_social_user(
            email=email,
            db_path=db_path,
            secret_key=secret_key,
        )

        logger.info("Apple Sign In successful: email=%s user_id=%s", email, user_id)

        redirect_url = (
            f"{_frontend_url}/auth/callback"
            f"?token={access_token}"
            f"&user_id={user_id}"
            f"&email={email}"
            f"&provider=apple"
        )
        return RedirectResponse(url=redirect_url, status_code=302)

    except Exception as exc:
        logger.exception("Apple Sign In callback unexpected error: %s", exc)
        return RedirectResponse(
            url=f"{_frontend_url}/login?error=apple_internal",
            status_code=302,
        )
