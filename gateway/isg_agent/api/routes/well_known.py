"""MCP discoverability and DID identity endpoints.

Implements three complementary discovery standards:

1. /.well-known/mcp.json — Legacy-compatible MCP capability advertisement.
   Advertises supported protocols (mcp/1.0, a2a/0.3, ucp/1.0), authentication
   scheme, and canonical API endpoint URLs.

2. /.well-known/mcp-server-card.json — SEP-1649 MCP Server Card (2026 standard).
   Pre-connection discovery document for AI registries, orchestrators, and
   agent crawlers.  Conforms to the emerging MCP Server Card specification
   (github.com/modelcontextprotocol/modelcontextprotocol/issues/1649).

3. /.well-known/did.json — W3C DID Core 1.0 platform DID document.
   Resolves did:web:app.dingdawg.com to a DID document containing the
   platform's verification methods.

4. /.well-known/did/{handle}.json — Agent-specific DID document.
   Resolves did:web:app.dingdawg.com:agents:<handle> to the agent's
   DID document (Ed25519 public key, service endpoints).

All endpoints are PUBLIC — no authentication required.  Neither exposes
sensitive data, internal architecture, or business-specific configuration.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

__all__ = ["router", "_build_mcp_server_card", "_get_base_url"]

logger = logging.getLogger(__name__)

router = APIRouter(tags=["discovery"])

# ---------------------------------------------------------------------------
# Platform capability document (static — only base_url is dynamic)
# ---------------------------------------------------------------------------

_SCHEMA_VERSION = "1.0"
_SERVER_NAME = "DingDawg Agent Platform"
_SERVER_VERSION = "1.0.0"
_SERVER_DESCRIPTION = (
    "AI agent platform for businesses — claim your @handle, deploy in minutes"
)

_CAPABILITIES = {
    "tools": True,
    "resources": True,
    "prompts": False,
}

_AUTHENTICATION = {
    "type": "bearer",
    "token_url": "/auth/login",
}

_SUPPORTED_PROTOCOLS = ["mcp/1.0", "a2a/0.3", "ucp/1.0"]


def _get_base_url(request: Request) -> str:
    """Return the canonical public-facing base URL.

    Priority order (highest to lowest):
    1. ``ISG_AGENT_PUBLIC_URL`` / ``settings.public_url`` — explicitly
       configured canonical domain (e.g. https://api.dingdawg.com).
       This is the only correct source for outward-facing URLs such as
       MCP discovery docs, agent cards, and widget configs.  Never
       exposes internal Railway hostnames.
    2. Fallback: construct from request headers — used only during local
       development where no PUBLIC_URL env var is set.
    """
    from isg_agent.config import get_settings

    settings = get_settings()
    # Primary: use configured canonical public domain
    if settings.public_url:
        return settings.public_url.rstrip("/")
    # Fallback for local dev only — NOT suitable for production
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", ""))
    if host:
        return f"{proto}://{host}"
    return str(request.base_url).rstrip("/")


# ---------------------------------------------------------------------------
# /.well-known/mcp.json — legacy MCP capability advertisement
# ---------------------------------------------------------------------------


@router.get("/.well-known/mcp.json")
async def mcp_discovery(request: Request) -> JSONResponse:
    """Return the MCP capability advertisement document for this platform.

    Agent orchestrators, directories, and partner integrations fetch this
    endpoint to discover:
    - What the platform is and its version
    - Which MCP/A2A/UCP protocol versions are supported
    - How to authenticate (bearer token, token URL)
    - The canonical API endpoints for agents, skills, templates, and triggers

    The document format follows the emerging ``.well-known/mcp.json``
    convention (analogous to ``/.well-known/openid-configuration`` for OAuth).

    Returns
    -------
    JSONResponse
        MCP capability advertisement, ``Content-Type: application/json``,
        public CORS header, 1-hour cache.
    """
    base_url = _get_base_url(request)

    document: dict = {
        "schema_version": _SCHEMA_VERSION,
        "server_info": {
            "name": _SERVER_NAME,
            "version": _SERVER_VERSION,
            "description": _SERVER_DESCRIPTION,
        },
        "capabilities": _CAPABILITIES,
        "authentication": {
            **_AUTHENTICATION,
            "token_url": f"{base_url}{_AUTHENTICATION['token_url']}",
        },
        "endpoints": {
            "agents": f"{base_url}/api/v1/agents",
            "skills": f"{base_url}/api/v1/skills",
            "templates": f"{base_url}/api/v1/templates",
            "trigger": f"{base_url}/api/v1/agents/{{agent_id}}/trigger",
        },
        "supported_protocols": _SUPPORTED_PROTOCOLS,
    }

    logger.debug("MCP discovery document served to %s", request.client)

    return JSONResponse(
        content=document,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )


# ---------------------------------------------------------------------------
# MCP Server Card (SEP-1649) — 2026 standard for pre-connection discovery
# ---------------------------------------------------------------------------


def _build_mcp_server_card(base_url: str) -> dict:
    """Build a SEP-1649 MCP Server Card for DingDawg Agent Platform.

    Returns a dict conforming to the emerging MCP Server Card specification
    (https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1649).

    The card is publicly accessible and MUST NOT contain sensitive data.
    ``tools`` and ``resources`` are advertised as ``["dynamic"]`` because
    Agent 1 capabilities are agent-specific and must be discovered via MCP
    list operations after authentication.

    Parameters
    ----------
    base_url:
        Absolute base URL (scheme + host, no trailing slash).

    Returns
    -------
    dict
        SEP-1649 compliant MCP Server Card.
    """
    return {
        "$schema": "https://static.modelcontextprotocol.io/schemas/mcp-server-card/v1.json",
        "version": "1.0",
        "protocolVersion": "2025-11-25",
        "serverInfo": {
            "name": "dingdawg-agent-platform",
            "title": "DingDawg Agent Platform",
            "version": "1.0.0",
            "description": (
                "AI agent platform for businesses — claim your @handle, "
                "deploy a governed AI agent in minutes. "
                "Supports 16 universal skills, gaming sector, "
                "multi-channel delivery (voice, SMS, email, web widget)."
            ),
            "provider": {
                "organization": "DingDawg Inc.",
                "url": "https://dingdawg.com",
                "contact": "support@dingdawg.com",
            },
        },
        "transport": {
            "type": "streamable-http",
            "endpoint": f"{base_url}/api/v1/sessions",
        },
        "capabilities": {
            "tools": {},
            "resources": {},
            "prompts": {},
            "streaming": True,
            "pushNotifications": False,
            "stateTransitionHistory": False,
        },
        "authentication": {
            "required": True,
            "schemes": [
                {
                    "type": "bearer",
                    "description": "JWT Bearer token obtained from POST /auth/login",
                    "tokenEndpoint": f"{base_url}/auth/login",
                }
            ],
        },
        "tools": ["dynamic"],
        "resources": ["dynamic"],
        "prompts": [],
        "protocols": {
            "mcp": {"version": "2025-11-25", "status": "live"},
            "a2a": {"version": "0.3", "status": "live"},
            "ucp": {"version": "1.0", "status": "live"},
            "rest": {"version": "1.0", "status": "live", "basePath": "/api/v1"},
        },
        "discovery": {
            "legacyMcpCard": "/.well-known/mcp.json",
            "openapi": "/openapi.json",
            "skills": f"{base_url}/api/v1/skills",
            "templates": f"{base_url}/api/v1/templates",
        },
        "contact": {
            "email": "support@dingdawg.com",
            "legal": "https://dingdawg.com/terms",
        },
        "_meta": {
            "sep": "SEP-1649",
            "specStatus": "draft",
            "registeredAt": "https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1649",
        },
    }


@router.get("/.well-known/mcp-server-card.json")
async def mcp_server_card(request: Request) -> JSONResponse:
    """Return the SEP-1649 MCP Server Card for DingDawg Agent Platform.

    This endpoint implements SEP-1649 — the MCP ecosystem's emerging standard
    for pre-connection server discovery.  AI registries, orchestrators, and
    agent crawlers fetch this document to discover:

    - Server identity (name, version, provider)
    - MCP transport type and session endpoint URL
    - Advertised MCP capabilities (tools, resources, prompts)
    - Authentication requirements (bearer token, token endpoint URL)
    - Supported protocol versions (MCP, A2A, UCP, REST)
    - Cross-links to other discovery documents

    The ``tools`` and ``resources`` fields advertise ``["dynamic"]`` because
    Agent 1 capabilities are agent-specific and must be discovered via MCP
    list operations after authentication.

    SECURITY:
        This endpoint is fully public (no auth required).  It MUST NOT expose
        internal implementation details, pricing, or business-specific data.

    Returns
    -------
    JSONResponse
        SEP-1649 MCP Server Card, Content-Type: application/json,
        public CORS (*), 1-hour cache directive.
    """
    base_url = _get_base_url(request)
    card = _build_mcp_server_card(base_url)
    logger.debug("MCP server card (SEP-1649) served to %s", request.client)
    return JSONResponse(
        content=card,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )


# ---------------------------------------------------------------------------
# DID identity endpoints — W3C DID Core 1.0
# ---------------------------------------------------------------------------

_DID_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Cache-Control": "public, max-age=300",
    "X-Content-Type-Options": "nosniff",
    "Content-Type": "application/did+json",
}

_PLATFORM_DID = "did:web:app.dingdawg.com"


def _get_did_manager(request: Request):
    """Extract the DIDManager from app state. Returns None if unavailable."""
    return getattr(request.app.state, "did_manager", None)


@router.get("/.well-known/did.json")
async def platform_did_document(request: Request) -> JSONResponse:
    """Return the W3C DID Core 1.0 document for the DingDawg platform DID.

    Resolves ``did:web:app.dingdawg.com`` per the did:web spec:
    https://w3c-ccg.github.io/did-method-web/

    This endpoint is PUBLIC — no authentication required.

    Returns
    -------
    JSONResponse
        W3C DID document, Content-Type: application/did+json, public CORS.
    """
    did_manager = _get_did_manager(request)

    if did_manager is None:
        # DID system unavailable — return a minimal static platform DID document
        base_url = _get_base_url(request)
        doc: dict = {
            "@context": [
                "https://www.w3.org/ns/did/v1",
                "https://w3id.org/security/suites/ed25519-2020/v1",
            ],
            "id": _PLATFORM_DID,
            "controller": _PLATFORM_DID,
            "verificationMethod": [],
            "authentication": [],
            "assertionMethod": [],
            "service": [
                {
                    "id": f"{_PLATFORM_DID}#agent-platform",
                    "type": "AgentPlatformService",
                    "serviceEndpoint": f"{base_url}/api/v1/agents",
                }
            ],
        }
        logger.debug("Platform DID document served (static fallback) to %s", request.client)
        return JSONResponse(content=doc, headers=_DID_HEADERS)

    # Attempt to resolve from the local DID store; fall back to static doc
    try:
        resolved = did_manager.resolve_did(_PLATFORM_DID)
        if resolved is not None:
            doc = resolved.to_json()
        else:
            # Platform DID not in store — return the minimal static document
            base_url = _get_base_url(request)
            doc = {
                "@context": [
                    "https://www.w3.org/ns/did/v1",
                    "https://w3id.org/security/suites/ed25519-2020/v1",
                ],
                "id": _PLATFORM_DID,
                "controller": _PLATFORM_DID,
                "verificationMethod": [],
                "authentication": [],
                "assertionMethod": [],
                "service": [
                    {
                        "id": f"{_PLATFORM_DID}#agent-platform",
                        "type": "AgentPlatformService",
                        "serviceEndpoint": f"{base_url}/api/v1/agents",
                    }
                ],
            }
    except Exception as exc:
        logger.warning("DID resolution failed for platform DID (fail-open): %s", exc)
        base_url = _get_base_url(request)
        doc = {
            "@context": ["https://www.w3.org/ns/did/v1"],
            "id": _PLATFORM_DID,
            "controller": _PLATFORM_DID,
            "verificationMethod": [],
            "authentication": [],
            "assertionMethod": [],
            "service": [],
        }

    logger.debug("Platform DID document served to %s", request.client)
    return JSONResponse(content=doc, headers=_DID_HEADERS)


@router.get("/.well-known/agent-card.json", include_in_schema=False)
async def agent_card() -> JSONResponse:
    """A2A-compliant Agent Card for capability discovery.

    Implements the Google A2A (Agent-to-Agent) Agent Card specification.
    External agent orchestrators, directories, and partner integrations
    fetch this document to discover platform identity, capabilities, and
    available skills.

    This endpoint is PUBLIC — no authentication required.  It MUST NOT
    expose sensitive data, internal architecture, or business-specific config.

    Returns
    -------
    JSONResponse
        A2A Agent Card, Content-Type: application/json, public CORS (*),
        1-hour cache directive.
    """
    card: dict = {
        "name": "DingDawg Agent 1",
        "description": (
            "AI agent platform for small businesses — conversation, memory, "
            "payments, scheduling, marketing, client intelligence"
        ),
        "version": "1.0.0",
        "url": "https://app.dingdawg.com",
        "provider": {
            "organization": "Innovative Systems Global",
            "url": "https://dingdawg.com",
        },
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
        },
        "authentication": {
            "schemes": ["bearer"],
        },
        "skills": [
            {
                "id": "chat",
                "name": "Business Chat",
                "description": (
                    "Multi-turn conversation with persistent memory and "
                    "21 business-ops capabilities"
                ),
            },
            {
                "id": "appointments",
                "name": "Appointments",
                "description": (
                    "Schedule, reschedule, cancel appointments with Google Calendar sync"
                ),
            },
            {
                "id": "invoicing",
                "name": "Invoicing",
                "description": "Create, send, track invoices with payment reminders",
            },
            {
                "id": "client_intelligence",
                "name": "Client Intelligence",
                "description": "CLV scoring, churn prediction, client segmentation",
            },
            {
                "id": "marketing",
                "name": "Marketing",
                "description": (
                    "Campaign creation, SMS/email outreach, Google Business Profile sync"
                ),
            },
            {
                "id": "payments",
                "name": "Payments",
                "description": "Payment links, revenue forecasting, refund processing",
            },
            {
                "id": "staff_ops",
                "name": "Staff Operations",
                "description": "Staff assignment, scheduling, utilization tracking",
            },
        ],
    }

    logger.debug("A2A agent card served")
    return JSONResponse(
        content=card,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/.well-known/did/{handle}.json")
async def agent_did_document(handle: str, request: Request) -> JSONResponse:
    """Return the W3C DID Core 1.0 document for a specific agent handle.

    Resolves ``did:web:app.dingdawg.com:agents:<handle>`` per the did:web spec.
    The URL pattern follows the did:web path mapping convention:
    ``did:web:app.dingdawg.com:agents:myagent``
    → ``/.well-known/did/agents/myagent.json``
    → served at ``/.well-known/did/myagent.json`` for handle lookup.

    This endpoint is PUBLIC — no authentication required.

    Returns 404 if no DID exists for the given handle.
    Returns 503 if the DID system is unavailable.
    """
    did_manager = _get_did_manager(request)

    if did_manager is None:
        logger.warning(
            "Agent DID requested for handle=%s but DID manager unavailable", handle
        )
        return JSONResponse(
            status_code=503,
            content={"detail": "DID system unavailable"},
            headers={"Access-Control-Allow-Origin": "*"},
        )

    agent_did = f"did:web:app.dingdawg.com:agents:{handle}"
    try:
        doc = did_manager.resolve_did(agent_did)
    except Exception as exc:
        logger.error(
            "DID resolution error for handle=%s did=%s: %s",
            handle,
            agent_did,
            exc,
        )
        return JSONResponse(
            status_code=503,
            content={"detail": "DID resolution failed"},
            headers={"Access-Control-Allow-Origin": "*"},
        )

    if doc is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"DID not found for handle: {handle}"},
            headers={"Access-Control-Allow-Origin": "*"},
        )

    logger.debug("Agent DID document served: handle=%s did=%s", handle, agent_did)
    return JSONResponse(content=doc.to_json(), headers=_DID_HEADERS)
