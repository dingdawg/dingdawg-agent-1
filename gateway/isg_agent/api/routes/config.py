"""Configuration endpoint: read-only safe config view.

Returns non-sensitive configuration values for client introspection.
Secrets (API keys, secret keys) are NEVER exposed.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from isg_agent.api.deps import CurrentUser, require_auth
from isg_agent.config import Settings

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/config", tags=["config"])


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------


class SafeConfigResponse(BaseModel):
    """Non-sensitive configuration values.

    Secret values (API keys, HMAC keys, etc.) are NEVER included.
    """

    host: str
    port: int
    log_level: str
    max_sessions: int
    convergence_max_iterations: int
    convergence_max_tokens: int
    trust_score_initial: float
    enable_remote: bool
    stripe_configured: bool
    providers: list[str]


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=SafeConfigResponse,
    summary="Return safe (non-secret) configuration",
)
async def get_config(
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> SafeConfigResponse:
    """Return the current application configuration.

    Sensitive values (API keys, secret key, webhook secrets) are omitted.
    Only operational configuration is exposed.
    """
    settings: Optional[Settings] = getattr(request.app.state, "settings", None)
    if settings is None:
        from isg_agent.config import get_settings
        settings = get_settings()

    # Determine configured providers
    providers: list[str] = []
    if settings.openai_api_key:
        providers.append("openai")
    if settings.anthropic_api_key:
        providers.append("anthropic")
    if settings.inception_api_key:
        providers.append("mercury")

    # Check Stripe configuration
    stripe_configured = bool(
        getattr(request.app.state, "stripe_client", None) is not None
    )

    return SafeConfigResponse(
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        max_sessions=settings.max_sessions,
        convergence_max_iterations=settings.convergence_max_iterations,
        convergence_max_tokens=settings.convergence_max_tokens,
        trust_score_initial=settings.trust_score_initial,
        enable_remote=settings.enable_remote,
        stripe_configured=stripe_configured,
        providers=providers,
    )
