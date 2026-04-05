"""OAuth 2.0 Authorization Server endpoints for Zapier integration.

Implements the Authorization Code Grant flow (RFC 6749) so that Zapier
can authenticate DingDawg users and call API endpoints on their behalf.

Endpoints
---------
- GET  /auth/oauth/authorize — consent page, redirects to Zapier with auth code
- POST /auth/oauth/token     — exchanges auth code for access + refresh tokens
- POST /auth/oauth/refresh   — refreshes expired access tokens
- GET  /api/v1/me            — returns authenticated user info (Zapier test endpoint)

Environment Variables
---------------------
- ZAPIER_CLIENT_ID      — OAuth client identifier for the Zapier app
- ZAPIER_CLIENT_SECRET  — OAuth client secret for the Zapier app
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
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

__all__ = ["router", "_set_oauth_server_config"]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level configuration (set by app.py lifespan via _set_oauth_server_config)
# ---------------------------------------------------------------------------

_db_path: str = "data/agent.db"
_secret_key: str = ""

# ---------------------------------------------------------------------------
# OAuth client credentials from environment
# ---------------------------------------------------------------------------

_ZAPIER_REDIRECT_URI = "https://zapier.com/dashboard/auth/oauth/return/App238361CLIAPI/"


def _get_client_id() -> str:
    return os.environ.get("ZAPIER_CLIENT_ID", "")


def _get_client_secret() -> str:
    return os.environ.get("ZAPIER_CLIENT_SECRET", "")


def _set_oauth_server_config(db_path: str, secret_key: str) -> None:
    """Called by app.py lifespan to inject DB path and JWT secret."""
    global _db_path, _secret_key  # noqa: PLW0603
    _db_path = db_path
    _secret_key = secret_key


# ---------------------------------------------------------------------------
# SQL schema for OAuth artifacts
# ---------------------------------------------------------------------------

_CREATE_OAUTH_CODES_SQL = """
CREATE TABLE IF NOT EXISTS oauth_authorization_codes (
    code            TEXT    PRIMARY KEY,
    user_id         TEXT    NOT NULL,
    email           TEXT    NOT NULL,
    client_id       TEXT    NOT NULL,
    redirect_uri    TEXT    NOT NULL,
    scope           TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL,
    expires_at      REAL    NOT NULL,
    used            INTEGER NOT NULL DEFAULT 0
);
"""

_CREATE_OAUTH_REFRESH_TOKENS_SQL = """
CREATE TABLE IF NOT EXISTS oauth_refresh_tokens (
    token           TEXT    PRIMARY KEY,
    user_id         TEXT    NOT NULL,
    email           TEXT    NOT NULL,
    client_id       TEXT    NOT NULL,
    scope           TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL,
    expires_at      REAL    NOT NULL,
    revoked         INTEGER NOT NULL DEFAULT 0
);
"""


async def _ensure_oauth_tables() -> None:
    """Create OAuth tables if they do not exist."""
    async with aiosqlite.connect(_db_path) as db:
        await db.execute(_CREATE_OAUTH_CODES_SQL)
        await db.execute(_CREATE_OAUTH_REFRESH_TOKENS_SQL)
        await db.commit()


# ---------------------------------------------------------------------------
# JWT helpers (reuse the same HS256 implementation from auth.py)
# ---------------------------------------------------------------------------

def _b64url_encode(data: bytes) -> str:
    """URL-safe Base64 encoding with padding stripped."""
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    """URL-safe Base64 decoding with padding restored."""
    import base64
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def _create_oauth_access_token(
    user_id: str,
    email: str,
    secret_key: str,
    expires_in: int = 3600,  # 1 hour
    scope: str = "",
) -> str:
    """Create a signed HS256 JWT access token for OAuth clients.

    Includes an ``oauth`` claim set to True so downstream middleware can
    distinguish OAuth tokens from regular session tokens if needed.
    """
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {
        "sub": user_id,
        "email": email,
        "iat": now,
        "exp": now + expires_in,
        "jti": uuid.uuid4().hex,
        "oauth": True,
        "scope": scope,
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


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

# Auth-prefix router for OAuth authorization + token endpoints
_auth_router = APIRouter(prefix="/auth/oauth", tags=["oauth-server"])

# API-prefix router for the /me test endpoint
_api_router = APIRouter(prefix="/api/v1", tags=["oauth-server"])


# ---------------------------------------------------------------------------
# 1. GET /auth/oauth/authorize — Authorization endpoint
# ---------------------------------------------------------------------------

_CONSENT_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Authorize DingDawg</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #0a0a0a 0%, #1a1a2e 100%);
            color: #e0e0e0;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .card {{
            background: #1e1e2e;
            border: 1px solid #333;
            border-radius: 16px;
            padding: 2.5rem;
            max-width: 420px;
            width: 100%;
            text-align: center;
            box-shadow: 0 8px 32px rgba(0,0,0,0.4);
        }}
        .logo {{ font-size: 2rem; font-weight: 700; color: #ff6b35; margin-bottom: 0.5rem; }}
        .subtitle {{ color: #888; margin-bottom: 1.5rem; font-size: 0.95rem; }}
        .scope-box {{
            background: #2a2a3e;
            border-radius: 8px;
            padding: 1rem;
            margin-bottom: 1.5rem;
            text-align: left;
        }}
        .scope-item {{ padding: 0.3rem 0; color: #ccc; }}
        .scope-item::before {{ content: "\\2713 "; color: #4caf50; }}
        .email {{ color: #ff6b35; font-weight: 600; }}
        form {{ display: flex; gap: 0.75rem; justify-content: center; }}
        button {{
            padding: 0.75rem 2rem;
            border: none;
            border-radius: 8px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.1s;
        }}
        button:active {{ transform: scale(0.97); }}
        .btn-allow {{ background: #ff6b35; color: #fff; }}
        .btn-deny {{ background: #333; color: #aaa; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="logo">DingDawg</div>
        <div class="subtitle">Zapier wants to access your account</div>
        <p style="margin-bottom:1rem;">Signed in as <span class="email">{email}</span></p>
        <div class="scope-box">
            <div class="scope-item">Read your profile information</div>
            <div class="scope-item">Access your agents</div>
            <div class="scope-item">Manage sessions on your behalf</div>
        </div>
        <form method="POST" action="/auth/oauth/authorize">
            <input type="hidden" name="client_id" value="{client_id}" />
            <input type="hidden" name="redirect_uri" value="{redirect_uri}" />
            <input type="hidden" name="state" value="{state}" />
            <input type="hidden" name="scope" value="{scope}" />
            <input type="hidden" name="response_type" value="code" />
            <input type="hidden" name="action" value="deny" />
            <button type="submit" class="btn-deny" name="action" value="deny">Deny</button>
            <button type="submit" class="btn-allow" name="action" value="allow">Allow</button>
        </form>
    </div>
</body>
</html>"""


@_auth_router.get("/authorize")
async def oauth_authorize_get(
    request: Request,
    response_type: str = Query(...),
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    state: str = Query(""),
    scope: str = Query(""),
) -> HTMLResponse:
    """Show OAuth consent page.

    The user must already be logged in (Bearer token in cookie or header).
    If not authenticated, redirects to the login page with a return URL.
    """
    # Validate client_id
    if client_id != _get_client_id():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid client_id",
        )

    if response_type != "code":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only response_type=code is supported",
        )

    # Extract user from Bearer token
    user = await _extract_user_from_request(request)
    if user is None:
        # No valid session — show inline login form (Zapier opens this in a popup,
        # so we can't redirect to the frontend login page)
        login_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign in to DingDawg</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; background: #07111c; color: #f1f5f9; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }}
  .card {{ background: #0f1d2e; border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 32px; width: 100%; max-width: 380px; }}
  h2 {{ margin: 0 0 8px; font-size: 20px; }}
  p {{ color: #94a3b8; font-size: 14px; margin: 0 0 24px; }}
  label {{ display: block; font-size: 13px; color: #94a3b8; margin-bottom: 6px; }}
  input {{ width: 100%; padding: 10px 12px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.12); background: rgba(255,255,255,0.05); color: #f1f5f9; font-size: 16px; box-sizing: border-box; margin-bottom: 16px; }}
  input:focus {{ outline: none; border-color: #F6B400; }}
  button {{ width: 100%; padding: 12px; border-radius: 10px; border: none; background: #F6B400; color: #07111c; font-size: 15px; font-weight: 600; cursor: pointer; }}
  button:hover {{ filter: brightness(1.1); }}
  .err {{ color: #f87171; font-size: 13px; margin-bottom: 12px; display: none; }}
</style></head><body>
<div class="card">
  <h2>Sign in to DingDawg</h2>
  <p>Authorize Zapier to access your agent.</p>
  <div class="err" id="err"></div>
  <form id="f" method="POST" action="/auth/oauth/login-and-authorize">
    <label>Email</label><input type="email" name="email" required autofocus>
    <label>Password</label><input type="password" name="password" required>
    <input type="hidden" name="client_id" value="{client_id}">
    <input type="hidden" name="redirect_uri" value="{redirect_uri}">
    <input type="hidden" name="state" value="{state}">
    <input type="hidden" name="scope" value="{scope}">
    <button type="submit">Sign In & Authorize</button>
  </form>
</div></body></html>"""
        return HTMLResponse(content=login_html)

    html = _CONSENT_HTML.format(
        email=user["email"],
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
        scope=scope,
    )
    return HTMLResponse(content=html)


@_auth_router.post("/authorize")
async def oauth_authorize_post(request: Request) -> RedirectResponse:
    """Process the consent form submission.

    On allow: generates an auth code and redirects to Zapier callback.
    On deny: redirects with error=access_denied.
    """
    form = await request.form()
    action = form.get("action", "deny")
    client_id = str(form.get("client_id", ""))
    redirect_uri = str(form.get("redirect_uri", ""))
    state = str(form.get("state", ""))
    scope = str(form.get("scope", ""))

    # Validate client_id
    if client_id != _get_client_id():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid client_id",
        )

    if action != "allow":
        # User denied — redirect with error
        sep = "&" if "?" in redirect_uri else "?"
        deny_url = f"{redirect_uri}{sep}error=access_denied"
        if state:
            deny_url += f"&state={state}"
        return RedirectResponse(url=deny_url, status_code=302)

    # Extract user from Bearer token
    user = await _extract_user_from_request(request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    # Generate authorization code
    auth_code = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    expires_at = time.time() + 600  # 10 minutes

    await _ensure_oauth_tables()
    async with aiosqlite.connect(_db_path) as db:
        await db.execute(
            "INSERT INTO oauth_authorization_codes "
            "(code, user_id, email, client_id, redirect_uri, scope, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                auth_code,
                user["user_id"],
                user["email"],
                client_id,
                redirect_uri,
                scope,
                now.isoformat(),
                expires_at,
            ),
        )
        await db.commit()

    logger.info(
        "OAuth auth code issued — user_id=%s client_id=%s",
        user["user_id"],
        client_id[:8] + "...",
    )

    # Redirect to Zapier with code + state
    sep = "&" if "?" in redirect_uri else "?"
    callback_url = f"{redirect_uri}{sep}code={auth_code}"
    if state:
        callback_url += f"&state={state}"

    return RedirectResponse(url=callback_url, status_code=302)


@_auth_router.post("/login-and-authorize")
async def oauth_login_and_authorize(request: Request):
    """Combined login + authorize for Zapier popup (no frontend available).

    Accepts email + password from the inline login form, authenticates the user,
    generates an auth code, and redirects to Zapier callback in one step.
    """
    form = await request.form()
    email = str(form.get("email", "")).strip().lower()
    password = str(form.get("password", ""))
    client_id = str(form.get("client_id", ""))
    redirect_uri = str(form.get("redirect_uri", ""))
    state = str(form.get("state", ""))
    scope = str(form.get("scope", ""))

    # Validate client_id
    if client_id != _get_client_id():
        raise HTTPException(status_code=400, detail="Invalid client_id")

    # Authenticate user against the database
    async with aiosqlite.connect(_db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, email, password_hash, salt FROM users WHERE LOWER(email) = ?",
            (email,),
        )
        row = await cursor.fetchone()

    if row is None:
        return HTMLResponse(
            content=_login_error_html("No account found with that email.", client_id, redirect_uri, state, scope),
            status_code=200,
        )

    # Verify password using the same logic as auth.py
    from isg_agent.api.routes.auth import _verify_password
    if not _verify_password(password, row["password_hash"], row["salt"]):
        return HTMLResponse(
            content=_login_error_html("Incorrect password.", client_id, redirect_uri, state, scope),
            status_code=200,
        )

    # Authenticated — generate auth code
    user_id = str(row["id"])
    auth_code = secrets.token_urlsafe(48)
    expires_at = time.time() + 600

    await _ensure_oauth_tables()
    async with aiosqlite.connect(_db_path) as db:
        await db.execute(
            "INSERT INTO oauth_authorization_codes "
            "(code, user_id, email, client_id, redirect_uri, scope, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (auth_code, user_id, email, client_id, redirect_uri, scope,
             datetime.now(timezone.utc).isoformat(), expires_at),
        )
        await db.commit()

    logger.info("OAuth login+authorize — user=%s", email)

    # Redirect to Zapier with code
    sep = "&" if "?" in redirect_uri else "?"
    callback_url = f"{redirect_uri}{sep}code={auth_code}"
    if state:
        callback_url += f"&state={state}"
    return RedirectResponse(url=callback_url, status_code=302)


def _login_error_html(error: str, client_id: str, redirect_uri: str, state: str, scope: str) -> str:
    """Return the login form HTML with an error message."""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign in to DingDawg</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; background: #07111c; color: #f1f5f9; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }}
  .card {{ background: #0f1d2e; border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 32px; width: 100%; max-width: 380px; }}
  h2 {{ margin: 0 0 8px; font-size: 20px; }}
  p {{ color: #94a3b8; font-size: 14px; margin: 0 0 24px; }}
  label {{ display: block; font-size: 13px; color: #94a3b8; margin-bottom: 6px; }}
  input {{ width: 100%; padding: 10px 12px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.12); background: rgba(255,255,255,0.05); color: #f1f5f9; font-size: 16px; box-sizing: border-box; margin-bottom: 16px; }}
  input:focus {{ outline: none; border-color: #F6B400; }}
  button {{ width: 100%; padding: 12px; border-radius: 10px; border: none; background: #F6B400; color: #07111c; font-size: 15px; font-weight: 600; cursor: pointer; }}
  .err {{ color: #f87171; font-size: 13px; margin-bottom: 12px; }}
</style></head><body>
<div class="card">
  <h2>Sign in to DingDawg</h2>
  <p>Authorize Zapier to access your agent.</p>
  <div class="err">{error}</div>
  <form method="POST" action="/auth/oauth/login-and-authorize">
    <label>Email</label><input type="email" name="email" required autofocus>
    <label>Password</label><input type="password" name="password" required>
    <input type="hidden" name="client_id" value="{client_id}">
    <input type="hidden" name="redirect_uri" value="{redirect_uri}">
    <input type="hidden" name="state" value="{state}">
    <input type="hidden" name="scope" value="{scope}">
    <button type="submit">Sign In & Authorize</button>
  </form>
</div></body></html>"""


# ---------------------------------------------------------------------------
# 2. POST /auth/oauth/token — Token exchange endpoint
# ---------------------------------------------------------------------------

class TokenRequest(BaseModel):
    """OAuth token exchange request body."""
    grant_type: str
    code: Optional[str] = None
    redirect_uri: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    refresh_token: Optional[str] = None


@_auth_router.post("/token")
async def oauth_token(request: Request) -> JSONResponse:
    """Exchange an authorization code for access + refresh tokens.

    Also handles refresh_token grant type (Zapier sends both to this endpoint).

    Accepts both JSON body and form-encoded body (Zapier uses form-encoded).
    """
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        body = await request.json()
    else:
        # Form-encoded (standard OAuth)
        form = await request.form()
        body = dict(form)

    grant_type = body.get("grant_type", "")
    client_id = body.get("client_id", "")
    client_secret = body.get("client_secret", "")

    # Validate client credentials
    if not _validate_client_credentials(client_id, client_secret):
        return JSONResponse(
            status_code=401,
            content={"error": "invalid_client", "error_description": "Invalid client credentials"},
        )

    if grant_type == "authorization_code":
        return await _handle_authorization_code_grant(body, client_id)
    elif grant_type == "refresh_token":
        return await _handle_refresh_token_grant(body, client_id)
    else:
        return JSONResponse(
            status_code=400,
            content={"error": "unsupported_grant_type", "error_description": f"Grant type '{grant_type}' is not supported"},
        )


# ---------------------------------------------------------------------------
# 3. POST /auth/oauth/refresh — Dedicated refresh endpoint
# ---------------------------------------------------------------------------

@_auth_router.post("/refresh")
async def oauth_refresh(request: Request) -> JSONResponse:
    """Refresh an expired access token.

    Separate endpoint for clarity, but internally delegates to the same
    refresh logic as POST /auth/oauth/token with grant_type=refresh_token.
    """
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        body = await request.json()
    else:
        form = await request.form()
        body = dict(form)

    client_id = body.get("client_id", "")
    client_secret = body.get("client_secret", "")

    if not _validate_client_credentials(client_id, client_secret):
        return JSONResponse(
            status_code=401,
            content={"error": "invalid_client", "error_description": "Invalid client credentials"},
        )

    return await _handle_refresh_token_grant(body, client_id)


# ---------------------------------------------------------------------------
# 4. GET /api/v1/me — Authenticated user info (Zapier test endpoint)
# ---------------------------------------------------------------------------

@_api_router.get("/me")
async def oauth_me(request: Request) -> JSONResponse:
    """Return authenticated user info.

    Zapier calls this endpoint after obtaining an access token to verify
    the connection is working and to display the connected account.
    """
    user = await _extract_user_from_request(request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Fetch agent info for the user
    agent_info = await _get_user_agent_info(user["user_id"])

    return JSONResponse(content={
        "user_id": user["user_id"],
        "email": user["email"],
        "authenticated": True,
        "oauth": True,
        **agent_info,
    })


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_client_credentials(client_id: str, client_secret: str) -> bool:
    """Validate OAuth client_id and client_secret against env vars."""
    expected_id = _get_client_id()
    expected_secret = _get_client_secret()

    if not expected_id or not expected_secret:
        logger.error("ZAPIER_CLIENT_ID or ZAPIER_CLIENT_SECRET not configured")
        return False

    id_match = hmac.compare_digest(str(client_id), expected_id)
    secret_match = hmac.compare_digest(str(client_secret), expected_secret)
    return id_match and secret_match


async def _extract_user_from_request(request: Request) -> Optional[dict[str, str]]:
    """Extract user_id and email from a Bearer token in the request.

    Checks the Authorization header first, then falls back to a cookie.
    Returns None if no valid token is found.
    """
    token: Optional[str] = None

    # Check Authorization header
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]

    # Fallback: check cookie
    if not token:
        token = request.cookies.get("access_token")

    if not token or not _secret_key:
        return None

    from isg_agent.api.routes.auth import verify_token

    payload = verify_token(token=token, secret_key=_secret_key)
    if payload is None:
        return None

    user_id = str(payload.get("sub", ""))
    email = str(payload.get("email", ""))

    if not user_id:
        return None

    return {"user_id": user_id, "email": email}


async def _handle_authorization_code_grant(
    body: dict,
    client_id: str,
) -> JSONResponse:
    """Exchange an authorization code for access + refresh tokens."""
    code = body.get("code", "")
    redirect_uri = body.get("redirect_uri", "")

    if not code:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_request", "error_description": "Missing authorization code"},
        )

    await _ensure_oauth_tables()

    # Look up the authorization code
    async with aiosqlite.connect(_db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM oauth_authorization_codes WHERE code = ?",
            (code,),
        )
        row = await cursor.fetchone()

    if row is None:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_grant", "error_description": "Invalid authorization code"},
        )

    # Check if code was already used
    if row["used"]:
        logger.warning("OAuth auth code replay attempt — code=%s...", code[:12])
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_grant", "error_description": "Authorization code already used"},
        )

    # Check expiry
    if time.time() > row["expires_at"]:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_grant", "error_description": "Authorization code expired"},
        )

    # Validate client_id matches
    if row["client_id"] != client_id:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_grant", "error_description": "Client ID mismatch"},
        )

    # Validate redirect_uri matches (if provided)
    if redirect_uri and row["redirect_uri"] != redirect_uri:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_grant", "error_description": "Redirect URI mismatch"},
        )

    # Mark code as used
    async with aiosqlite.connect(_db_path) as db:
        await db.execute(
            "UPDATE oauth_authorization_codes SET used = 1 WHERE code = ?",
            (code,),
        )
        await db.commit()

    user_id = row["user_id"]
    email = row["email"]
    scope = row["scope"] or ""

    # Generate access token (JWT, 1 hour)
    access_token = _create_oauth_access_token(
        user_id=user_id,
        email=email,
        secret_key=_secret_key,
        expires_in=3600,
        scope=scope,
    )

    # Generate refresh token (random, 30 days)
    refresh_token = secrets.token_urlsafe(64)
    now = datetime.now(timezone.utc)
    refresh_expires_at = time.time() + (30 * 24 * 3600)  # 30 days

    async with aiosqlite.connect(_db_path) as db:
        await db.execute(
            "INSERT INTO oauth_refresh_tokens "
            "(token, user_id, email, client_id, scope, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                refresh_token,
                user_id,
                email,
                client_id,
                scope,
                now.isoformat(),
                refresh_expires_at,
            ),
        )
        await db.commit()

    logger.info(
        "OAuth tokens issued — user_id=%s grant=authorization_code",
        user_id,
    )

    return JSONResponse(content={
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": 3600,
        "refresh_token": refresh_token,
        "scope": scope,
    })


async def _handle_refresh_token_grant(
    body: dict,
    client_id: str,
) -> JSONResponse:
    """Refresh an expired access token using a refresh token."""
    refresh_token = body.get("refresh_token", "")

    if not refresh_token:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_request", "error_description": "Missing refresh_token"},
        )

    await _ensure_oauth_tables()

    # Look up refresh token
    async with aiosqlite.connect(_db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM oauth_refresh_tokens WHERE token = ?",
            (refresh_token,),
        )
        row = await cursor.fetchone()

    if row is None:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_grant", "error_description": "Invalid refresh token"},
        )

    if row["revoked"]:
        logger.warning("OAuth revoked refresh token used — user_id=%s", row["user_id"])
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_grant", "error_description": "Refresh token revoked"},
        )

    if time.time() > row["expires_at"]:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_grant", "error_description": "Refresh token expired"},
        )

    if row["client_id"] != client_id:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_grant", "error_description": "Client ID mismatch"},
        )

    user_id = row["user_id"]
    email = row["email"]
    scope = row["scope"] or ""

    # Issue new access token
    access_token = _create_oauth_access_token(
        user_id=user_id,
        email=email,
        secret_key=_secret_key,
        expires_in=3600,
        scope=scope,
    )

    logger.info(
        "OAuth access token refreshed — user_id=%s",
        user_id,
    )

    return JSONResponse(content={
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": 3600,
        "refresh_token": refresh_token,  # Return same refresh token
        "scope": scope,
    })


async def _get_user_agent_info(user_id: str) -> dict:
    """Fetch the user's primary agent info for the /me response."""
    try:
        async with aiosqlite.connect(_db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT id, handle, name, sector FROM agents WHERE owner_id = ? LIMIT 1",
                (user_id,),
            )
            row = await cursor.fetchone()

        if row:
            return {
                "agent_id": row["id"],
                "agent_handle": row["handle"],
                "agent_name": row["name"],
                "agent_sector": row["sector"] if "sector" in row.keys() else None,
            }
    except Exception as exc:
        logger.debug("Could not fetch agent info for /me: %s", exc)

    return {"agent_id": None, "agent_handle": None, "agent_name": None}


# ---------------------------------------------------------------------------
# Combined router — merge both sub-routers into one for app.include_router()
# ---------------------------------------------------------------------------

router = APIRouter(tags=["oauth-server"])
router.include_router(_auth_router)
router.include_router(_api_router)
