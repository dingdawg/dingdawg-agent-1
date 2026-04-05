"""OAuth2 endpoints for third-party service integrations.

Currently supports Google Calendar OAuth2 authorization flow:
  - ``GET /api/v1/oauth/google/authorize``  — generate authorization URL (auth required)
  - ``GET /api/v1/oauth/google/callback``   — handle Google's redirect (public)
  - ``GET /api/v1/oauth/google/status/{agent_id}`` — connection status (auth required)
  - ``DELETE /api/v1/oauth/google/disconnect/{agent_id}`` — remove connection (auth required)
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from isg_agent.api.deps import CurrentUser, require_auth
from isg_agent.config import get_settings

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/oauth", tags=["oauth"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sign_state(agent_id: str, secret_key: str) -> str:
    """Create a signed state parameter encoding the agent_id.

    Format: ``{agent_id}:{hmac_hex}``

    The HMAC prevents an attacker from forging a callback that associates
    tokens with an arbitrary agent.
    """
    sig = hmac.new(
        secret_key.encode("utf-8"),
        agent_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:16]
    return f"{agent_id}:{sig}"


def _verify_state(state: str, secret_key: str) -> str | None:
    """Verify and extract the agent_id from a signed state parameter.

    Returns the agent_id if the signature is valid, or None if tampered.
    """
    if ":" not in state:
        return None
    agent_id, sig = state.rsplit(":", 1)
    expected = hmac.new(
        secret_key.encode("utf-8"),
        agent_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:16]
    if not hmac.compare_digest(sig, expected):
        return None
    return agent_id


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/google/authorize")
async def google_authorize(
    request: Request,
    agent_id: str,
    user: CurrentUser = Depends(require_auth),
) -> dict[str, Any]:
    """Generate a Google OAuth2 authorization URL.

    Requires authentication. Returns ``{"auth_url": "https://accounts.google.com/..."}``
    that the frontend should redirect the user to.

    Query Parameters
    ----------------
    agent_id:
        The agent to associate the Google Calendar connection with.
    """
    settings = get_settings()

    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar integration is not configured",
        )

    redirect_uri = settings.google_redirect_uri
    if not redirect_uri:
        # Build from the canonical public URL, NOT request.base_url which
        # would expose the internal Railway hostname to Google's OAuth servers.
        base = settings.public_url.rstrip("/") if settings.public_url else str(request.base_url).rstrip("/")
        redirect_uri = f"{base}/api/v1/oauth/google/callback"

    state = _sign_state(agent_id, settings.secret_key)

    try:
        from google_auth_oauthlib.flow import Flow

        flow = Flow.from_client_config(
            client_config={
                "web": {
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            scopes=["https://www.googleapis.com/auth/calendar"],
            redirect_uri=redirect_uri,
        )

        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state=state,
        )

        return {"auth_url": auth_url}

    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Google OAuth libraries not installed. "
                "Install google-auth-oauthlib."
            ),
        )
    except Exception as exc:
        logger.error("Failed to generate Google OAuth URL: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate authorization URL",
        )


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: str,
    state: str,
) -> dict[str, Any]:
    """Handle Google OAuth2 callback.

    Exchanges the authorization code for tokens, retrieves the user's
    email, and stores credentials for the agent identified in *state*.

    This endpoint is public (no JWT required) because Google redirects
    the user's browser here after consent.
    """
    settings = get_settings()

    agent_id = _verify_state(state, settings.secret_key)
    if agent_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or tampered state parameter",
        )

    redirect_uri = settings.google_redirect_uri
    if not redirect_uri:
        base = settings.public_url.rstrip("/") if settings.public_url else str(request.base_url).rstrip("/")
        redirect_uri = f"{base}/api/v1/oauth/google/callback"

    try:
        from google_auth_oauthlib.flow import Flow

        flow = Flow.from_client_config(
            client_config={
                "web": {
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            scopes=["https://www.googleapis.com/auth/calendar"],
            redirect_uri=redirect_uri,
        )

        flow.fetch_token(code=code)
        creds = flow.credentials

        # Try to get the user's email from the id_token or userinfo
        google_email = None
        if hasattr(creds, "id_token") and creds.id_token:
            google_email = creds.id_token.get("email")

        token_expiry = creds.expiry.isoformat() if creds.expiry else None

        # Store credentials via the connector on app.state
        connector = getattr(request.app.state, "google_calendar", None)
        if connector is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Google Calendar connector not initialised",
            )

        await connector.store_credentials(agent_id, {
            "access_token": creds.token,
            "refresh_token": creds.refresh_token or "",
            "token_expiry": token_expiry,
            "google_email": google_email,
            "calendar_id": "primary",
        })

        return {
            "status": "connected",
            "agent_id": agent_id,
            "google_email": google_email,
            "message": "Google Calendar connected successfully",
        }

    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth libraries not installed",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Google OAuth callback failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to complete Google Calendar authorization",
        )


@router.get("/google/status/{agent_id}")
async def google_status(
    request: Request,
    agent_id: str,
    user: CurrentUser = Depends(require_auth),
) -> dict[str, Any]:
    """Check whether *agent_id* has an active Google Calendar connection.

    Returns ``{"connected": true/false, "google_email": "..." | null}``.
    """
    connector = getattr(request.app.state, "google_calendar", None)
    if connector is None:
        return {"connected": False, "google_email": None}

    creds = await connector.get_credentials(agent_id)
    if creds is None:
        return {"connected": False, "google_email": None}

    return {
        "connected": True,
        "google_email": creds.get("google_email"),
        "calendar_id": creds.get("calendar_id", "primary"),
    }


@router.delete("/google/disconnect/{agent_id}")
async def google_disconnect(
    request: Request,
    agent_id: str,
    user: CurrentUser = Depends(require_auth),
) -> dict[str, Any]:
    """Disconnect Google Calendar for *agent_id*.

    Soft-deletes the stored credentials so the agent can re-authorise later.
    """
    connector = getattr(request.app.state, "google_calendar", None)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar connector not initialised",
        )

    await connector.disconnect(agent_id)
    return {"status": "disconnected", "agent_id": agent_id}
