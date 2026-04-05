"""Google Calendar OAuth2 integration endpoints.

Routes
------
GET  /api/v1/integrations/{agent_id}/google-calendar/auth-url  — generate OAuth URL
POST /api/v1/integrations/google-calendar/callback             — exchange code for tokens (fixed URI)

Design note — Google OAuth Redirect URI
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Google requires pre-registered redirect URIs in the Cloud Console.  The
callback endpoint uses a FIXED path (no ``{agent_id}`` segment) so only
ONE URI needs to be registered.  The ``agent_id`` is round-tripped
through the OAuth ``state`` parameter with an HMAC signature to prevent
forgery.

Set the env var ``ISG_AGENT_GOOGLE_REDIRECT_URI`` to the production URL:
``https://<domain>/api/v1/integrations/google-calendar/callback``
"""

from __future__ import annotations

import logging
import os
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status

from isg_agent.api.deps import CurrentUser, require_auth

from ._deps import _get_agent_registry, _get_google_calendar, _verify_agent_ownership
from ._schemas import GoogleCalendarCallbackRequest
from .oauth_state import sign_oauth_state, verify_oauth_state

logger = logging.getLogger(__name__)

router = APIRouter()


def _resolve_google_settings() -> tuple[str, str, str]:
    """Return (client_id, client_secret, redirect_uri) from env or settings.

    Env vars take precedence; settings object is the fallback.
    """
    from isg_agent.config import get_settings as _get_settings

    client_id = os.environ.get("ISG_AGENT_GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("ISG_AGENT_GOOGLE_CLIENT_SECRET", "")
    redirect_uri = os.environ.get("ISG_AGENT_GOOGLE_REDIRECT_URI", "")

    if not client_id or not redirect_uri:
        _settings = _get_settings()
        client_id = client_id or _settings.google_client_id
        client_secret = client_secret or _settings.google_client_secret
        redirect_uri = redirect_uri or _settings.google_redirect_uri

    return client_id, client_secret, redirect_uri


def _resolve_secret_key() -> str:
    """Return the HMAC signing key from env or settings."""
    from isg_agent.config import get_settings as _get_settings

    return os.environ.get(
        "ISG_AGENT_SECRET_KEY",
        _get_settings().secret_key,
    )


@router.get(
    "/{agent_id}/google-calendar/auth-url",
    status_code=status.HTTP_200_OK,
    summary="Get Google OAuth2 authorization URL for Calendar integration",
)
async def google_calendar_auth_url(
    agent_id: str,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    """Generate the Google OAuth2 authorization URL for this agent.

    The frontend should redirect the user to ``auth_url``.  After the user
    grants access, Google redirects back to the **fixed** redirect URI with
    an authorization ``code`` and ``state`` query parameter.  The frontend
    captures both and POSTs them to the callback endpoint to complete the
    OAuth flow.

    The ``state`` parameter carries an HMAC-signed ``agent_id`` so only one
    redirect URI needs to be registered in the Google Cloud Console.

    Returns 404 if the agent does not exist or belongs to another user.
    Returns 503 if Google OAuth2 client credentials are not configured.
    """
    registry = _get_agent_registry(request)
    await _verify_agent_ownership(agent_id, current_user, registry)

    client_id, _client_secret, redirect_uri = _resolve_google_settings()

    if not client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth2 client credentials not configured.",
        )

    _secret_key = _resolve_secret_key()

    scopes = [
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/userinfo.email",
        "openid",
    ]

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "prompt": "consent",
        "state": sign_oauth_state(agent_id, _secret_key),
    }

    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    logger.info(
        "GET /integrations/%s/google-calendar/auth-url: user=%s",
        agent_id, current_user.user_id,
    )
    return {"agent_id": agent_id, "auth_url": auth_url}


@router.post(
    "/google-calendar/callback",
    status_code=status.HTTP_200_OK,
    summary="Complete Google Calendar OAuth2 flow by exchanging the authorization code",
)
async def google_calendar_callback(
    body: GoogleCalendarCallbackRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    """Exchange a Google OAuth2 authorization code for tokens.

    Call this endpoint after the user is redirected back from Google with
    ``code`` and ``state`` query parameters.  The ``state`` carries an
    HMAC-signed ``agent_id`` that was generated by the ``auth-url``
    endpoint, ensuring only one fixed redirect URI is needed in the
    Google Cloud Console.

    The tokens are stored securely per-agent and the access token is
    never returned to the caller.

    Returns 400 if the state parameter is missing, invalid, or tampered.
    Returns 404 if the agent does not exist or belongs to another user.
    Returns 400 if the code exchange fails (expired code, wrong redirect
    URI, etc.).
    """
    # --- Step 1: Verify the HMAC-signed state and extract agent_id ---
    _secret_key = _resolve_secret_key()

    agent_id = verify_oauth_state(body.state, _secret_key)
    if agent_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or tampered OAuth state parameter.",
        )

    # --- Step 2: Verify the authenticated user owns this agent ---
    registry = _get_agent_registry(request)
    await _verify_agent_ownership(agent_id, current_user, registry)

    # --- Step 3: Resolve Google OAuth credentials ---
    client_id, client_secret, redirect_uri = _resolve_google_settings()

    if not client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth2 client credentials not configured.",
        )

    # --- Step 4: Exchange the auth code for tokens ---
    try:
        async with httpx.AsyncClient(timeout=30.0) as http:
            resp = await http.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": body.code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Google token exchange timed out.",
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Google token exchange failed: {exc}",
        )

    if resp.status_code != 200:
        error_detail = resp.json().get("error_description", resp.text[:200])
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Google OAuth2 error: {error_detail}",
        )

    token_data = resp.json()
    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")

    if not access_token or not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google did not return a refresh token. Re-authorise with prompt=consent.",
        )

    # --- Step 5: Fetch the user's email (best-effort) ---
    google_email: Optional[str] = None
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            ui_resp = await http.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if ui_resp.status_code == 200:
            google_email = ui_resp.json().get("email")
    except Exception:
        pass  # non-fatal: email fetch failure must not break token storage

    # --- Step 6: Store credentials ---
    gcal = _get_google_calendar(request)
    await gcal.store_credentials(
        agent_id=agent_id,
        credentials={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_expiry": None,
            "google_email": google_email,
        },
    )

    logger.info(
        "POST /integrations/google-calendar/callback: agent=%s connected=%s user=%s",
        agent_id, bool(google_email), current_user.user_id,
    )
    return {
        "agent_id": agent_id,
        "connected": True,
        "google_email": google_email,
    }
