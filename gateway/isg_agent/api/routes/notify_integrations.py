"""Per-agent integration configuration endpoints.

Provides REST API routes so authenticated users can configure SendGrid
(email), Twilio (SMS), Vapi (voice), and Google Calendar integrations
per agent.  All routes require a valid JWT Bearer token via
``require_auth`` and verify that the authenticated user owns the agent.

Routes
------
POST   /api/v1/integrations/{agent_id}/email                 — configure SendGrid
GET    /api/v1/integrations/{agent_id}/email                 — get email status
DELETE /api/v1/integrations/{agent_id}/email                 — disconnect email

POST   /api/v1/integrations/{agent_id}/sms                   — configure Twilio
GET    /api/v1/integrations/{agent_id}/sms                   — get SMS status
DELETE /api/v1/integrations/{agent_id}/sms                   — disconnect SMS

POST   /api/v1/integrations/{agent_id}/vapi/configure        — configure Vapi voice
GET    /api/v1/integrations/{agent_id}/google-calendar/auth-url — Google OAuth URL
POST   /api/v1/integrations/google-calendar/callback         — OAuth code exchange (fixed URI)

POST   /api/v1/integrations/{agent_id}/disconnect            — generic disconnect
POST   /api/v1/integrations/{agent_id}/test                  — test email or SMS

GET    /api/v1/integrations/{agent_id}/status                — combined status

Design Note — Google OAuth Redirect URI
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Google requires pre-registered redirect URIs in the Cloud Console.  The
callback endpoint uses a FIXED path (no ``{agent_id}`` segment) so only
ONE URI needs to be registered.  The ``agent_id`` is round-tripped
through the OAuth ``state`` parameter with an HMAC signature to prevent
forgery.

Set the env var ``ISG_AGENT_GOOGLE_REDIRECT_URI`` to the production URL:
``https://<domain>/api/v1/integrations/google-calendar/callback``

Implementation Note
~~~~~~~~~~~~~~~~~~~
This module is a thin router that assembles sub-module routers.  All
business logic lives in ``isg_agent.api.routes.integrations.*``.
"""

from __future__ import annotations

from fastapi import APIRouter

from isg_agent.api.routes.integrations import email as _email_mod
from isg_agent.api.routes.integrations import google_calendar as _gcal_mod
from isg_agent.api.routes.integrations import management as _mgmt_mod
from isg_agent.api.routes.integrations import sms as _sms_mod
from isg_agent.api.routes.integrations import status as _status_mod
from isg_agent.api.routes.integrations import vapi as _vapi_mod
from isg_agent.api.routes.integrations import webhooks as _webhooks_mod

# Re-export helpers that test files reference directly via this module's path.
from isg_agent.api.routes.integrations.oauth_state import (
    _sign_oauth_state,
    _verify_oauth_state,
    sign_oauth_state,
    verify_oauth_state,
)

__all__ = ["router"]

router = APIRouter(
    prefix="/api/v1/integrations",
    tags=["notify-integrations"],
)

# Mount all sub-routers (order matters for FastAPI path matching:
# fixed paths before parameterised ones where ambiguous).
router.include_router(_gcal_mod.router)   # /google-calendar/callback (fixed) must come first
router.include_router(_email_mod.router)
router.include_router(_sms_mod.router)
router.include_router(_vapi_mod.router)
router.include_router(_status_mod.router)
router.include_router(_mgmt_mod.router)
router.include_router(_webhooks_mod.router)
