"""FastAPI dependency injection providers.

Provides shared dependencies for route handlers: database, settings,
authentication, and current-user extraction from JWT tokens.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from isg_agent.config import Settings, get_settings
from isg_agent.db.engine import Database, get_db

__all__ = [
    "get_db",
    "get_settings",
    "get_current_user",
    "require_auth",
    "require_admin",
    "CurrentUser",
]

logger = logging.getLogger(__name__)

_security = HTTPBearer(auto_error=False)


class CurrentUser:
    """Authenticated user context extracted from a JWT token.

    Attributes
    ----------
    user_id:
        The ``sub`` claim from the token.
    email:
        The ``email`` claim from the token.
    """

    __slots__ = ("user_id", "email")

    def __init__(self, user_id: str, email: str) -> None:
        self.user_id = user_id
        self.email = email

    def __repr__(self) -> str:
        return f"CurrentUser(user_id={self.user_id!r}, email={self.email!r})"


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security),
    settings: Settings = Depends(get_settings),
) -> Optional[CurrentUser]:
    """Extract the current user from the Authorization Bearer token.

    Returns None if no token is provided (unauthenticated request).
    Returns None if the token is invalid or expired.

    Parameters
    ----------
    credentials:
        The HTTP Bearer credentials extracted from the Authorization header.
    settings:
        Application settings (provides the JWT secret key).

    Returns
    -------
    CurrentUser or None
    """
    if credentials is None:
        return None

    from isg_agent.api.routes.auth import verify_token

    payload = verify_token(token=credentials.credentials, secret_key=settings.secret_key)
    if payload is None:
        return None

    user_id = str(payload.get("sub", ""))
    email = str(payload.get("email", ""))

    if not user_id:
        return None

    return CurrentUser(user_id=user_id, email=email)


async def require_auth(
    current_user: Optional[CurrentUser] = Depends(get_current_user),
) -> CurrentUser:
    """Dependency that requires an authenticated user.

    Raises 401 Unauthorized if no valid token is present.

    Parameters
    ----------
    current_user:
        The result of :func:`get_current_user`.

    Returns
    -------
    CurrentUser
        The authenticated user.

    Raises
    ------
    HTTPException
        401 if the user is not authenticated.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user


async def require_admin(
    current_user: CurrentUser = Depends(require_auth),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    """Dependency that requires the authenticated user to be the platform admin.

    Checks JWT email against ISG_AGENT_ADMIN_EMAIL env var.
    Returns 403 if not admin.

    Parameters
    ----------
    current_user:
        The result of :func:`require_auth`.
    settings:
        Application settings (unused directly; kept for DI symmetry).

    Returns
    -------
    CurrentUser
        The authenticated admin user.

    Raises
    ------
    HTTPException
        403 if the user is not the designated platform admin.
    """
    admin_email = os.environ.get("ISG_AGENT_ADMIN_EMAIL", "")
    if not admin_email or (current_user.email or "").lower() != admin_email.lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user
