"""Public agent profile endpoints.

Unauthenticated endpoints for discovering and interacting with agents.
These power the public agent card page, QR codes, and agent discovery.

All endpoints are PUBLIC -- no authentication required.
"""

from __future__ import annotations

import io
import json
import logging
import uuid
from datetime import datetime, timezone
from html import escape
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.responses import Response

from isg_agent.middleware.rate_limiter_middleware import public_rate_limit

__all__ = ["router"]

# ---------------------------------------------------------------------------
# ATR v1.0 — Agent Threat Response receipt data
# ---------------------------------------------------------------------------

ATR_VERSION = "1.0.0"

SAMPLE_RECEIPT: dict[str, object] = {
    "receipt_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "agent_id": "@compliance-bot",
    "decision": "DECLINE",
    "decision_reason": "Transaction exceeds single-payment threshold (USD 9,500 of USD 10,000 limit)",
    "timestamp": "2026-05-28T14:30:00Z",
    "subject_id": "a3f2b8c1d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0",
    "policy_version": "1.4.2",
    "confidence_score": 94,
    "parent_receipt_id": None,
    "verification_endpoint": "/api/v1/public/receipt/a1b2c3d4-e5f6-7890-abcd-ef1234567890",
}

RECEIPT_SCHEMA: dict[str, object] = {
    "title": "ATR v1.0 Receipt",
    "version": ATR_VERSION,
    "type": "object",
    "required": ["receipt_id", "agent_id", "decision", "timestamp", "subject_id"],
    "properties": {
        "receipt_id": {
            "type": "string",
            "format": "uuid",
            "description": "Unique receipt identifier (UUIDv4)",
        },
        "agent_id": {
            "type": "string",
            "description": "Issuing agent identifier (dingdawg handle or DID)",
        },
        "decision": {
            "type": "string",
            "enum": ["APPROVE", "DECLINE", "REVIEW"],
            "description": "The agent's decision",
        },
        "decision_reason": {
            "type": "string",
            "description": "Human-readable policy rule that fired",
        },
        "timestamp": {
            "type": "string",
            "format": "date-time",
            "description": "ISO 8601 UTC timestamp of the decision",
        },
        "subject_id": {
            "type": "string",
            "description": "SHA-256 hash of the subject identifier (PII-safe)",
        },
        "policy_version": {
            "type": "string",
            "pattern": "^\\d+\\.\\d+\\.\\d+$",
            "description": "Semantic version of the policy that governed this decision",
        },
        "confidence_score": {
            "type": "number",
            "minimum": 0,
            "maximum": 100,
            "description": "Agent's confidence in the decision (0-100)",
        },
        "parent_receipt_id": {
            "type": "string",
            "format": "uuid",
            "description": "Chain-of-custody link to parent receipt (null if root)",
        },
        "verification_endpoint": {
            "type": "string",
            "format": "uri",
            "description": "Self-referential URL for verifying this receipt",
        },
    },
}

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/public", tags=["public"])


# ---------------------------------------------------------------------------
# ATR auth helper
# ---------------------------------------------------------------------------


def _verify_atr_api_key(request: Request, *, require_configured: bool = False) -> bool:
    """Check X-API-Key header against configured ATR API key.

    If no key is configured (empty string) and ``require_configured`` is
    False, auth is skipped and the request is allowed. This supports local
    development where no API key is set, and keeps receipt reads public by
    design (third-party verification is the whole point of an audit trail).

    ``require_configured=True`` (used by the receipt WRITE path) instead
    treats an unconfigured key as a hard deny -- never open access. This
    endpoint mints entries in a compliance ledger; "convenient for local
    dev" must never mean "anyone can forge a receipt in production because
    nobody set an env var." A real production incident: ISG_AGENT_ATR_API_KEY
    was never configured on Railway, so every caller could POST a receipt
    for any agent_id, including agents that were never even approved.
    """
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        # Lifespan not run (e.g. bare test client) — fall back to the
        # cached settings singleton instead of failing closed on a
        # wiring detail.
        from isg_agent.config import get_settings

        settings = get_settings()
    if not settings.atr_api_key:
        return not require_configured
    header_key = request.headers.get("x-api-key", "")
    return header_key == settings.atr_api_key


def _resolve_db_path(request: Request) -> str:
    """Return the configured SQLite path (app.state first, then settings)."""
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        from isg_agent.config import get_settings

        settings = get_settings()
    return str(settings.db_path or "")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_branding(agent_record: Any) -> dict[str, Any]:
    """Parse the branding_json field from an AgentRecord into a dict."""
    raw = getattr(agent_record, "branding_json", "{}")
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _parse_config(agent_record: Any) -> dict[str, Any]:
    """Parse the config_json field from an AgentRecord into a dict."""
    raw = getattr(agent_record, "config_json", "{}")
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _agent_to_public_dict(agent: Any) -> dict[str, Any]:
    """Convert an AgentRecord to a public-safe dictionary.

    Strips sensitive fields (user_id, config_json, constitution_yaml)
    and parses branding into top-level fields.
    """
    branding = _parse_branding(agent)
    config = _parse_config(agent)

    return {
        "handle": agent.handle,
        "name": agent.name,
        "description": config.get("description", ""),
        "industry": agent.industry_type or "",
        "agent_type": agent.agent_type.value,
        "avatar_url": branding.get("avatar_url", ""),
        "primary_color": branding.get("primary_color", "#7C3AED"),
        "greeting": config.get("greeting", f"Hi! I'm {agent.name}. How can I help?"),
        "created_at": agent.created_at,
    }


def _get_base_url(request: Request) -> str:
    """Return the canonical public-facing base URL.

    Priority order (highest to lowest):
    1. ``ISG_AGENT_PUBLIC_URL`` / ``settings.public_url`` — explicitly
       configured canonical domain (e.g. https://api.dingdawg.com).
       Must be set in production to prevent leaking the internal Railway
       hostname in agent card og:url tags, widget scripts, and QR codes.
    2. Fallback: construct from request headers — used only during local
       development where no PUBLIC_URL env var is set.
    """
    from isg_agent.config import get_settings

    settings = get_settings()
    if settings.public_url:
        return settings.public_url.rstrip("/")
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", ""))
    if host:
        return f"{proto}://{host}"
    return str(request.base_url).rstrip("/")


# ---------------------------------------------------------------------------
# Card HTML renderer
# ---------------------------------------------------------------------------


def _render_card_html(agent: dict[str, Any], base_url: str) -> str:
    """Render a standalone agent card HTML page.

    Parameters
    ----------
    agent:
        Public agent dict from ``_agent_to_public_dict``.
    base_url:
        The base URL for linking to widget JS and other resources.

    Returns
    -------
    str
        A complete, self-contained HTML document.
    """
    name = escape(agent.get("name", "Agent"))
    handle = escape(agent.get("handle", ""))
    description = escape(agent.get("description", ""))
    industry = escape(agent.get("industry", ""))
    color = escape(agent.get("primary_color", "#7C3AED"))
    greeting = escape(
        agent.get("greeting", f"Hi! I'm {name}. How can I help?")
    )
    avatar_url = escape(agent.get("avatar_url", ""))

    # Use avatar image if provided, otherwise emoji fallback
    if avatar_url:
        avatar_html = (
            f'<img src="{avatar_url}" alt="{name}" '
            f'style="width:80px;height:80px;border-radius:50%;object-fit:cover;">'
        )
    else:
        avatar_html = '<div class="avatar">&#x1F916;</div>'

    # Industry badge — only show if set
    badge_html = ""
    if industry:
        badge_html = f'<span class="badge">{industry}</span>'

    body_text = description or greeting

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{name} &mdash; DingDawg Agent</title>
    <meta name="description" content="{description or greeting}">
    <meta property="og:title" content="{name} &mdash; DingDawg Agent">
    <meta property="og:description" content="{description or greeting}">
    <meta property="og:type" content="website">
    <meta property="og:url" content="{base_url}/api/v1/public/agents/{handle}/card">
    <meta name="twitter:card" content="summary">
    <meta name="twitter:title" content="{name} &mdash; DingDawg Agent">
    <meta name="twitter:description" content="{description or greeting}">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, {color}22 0%, #f8f9fa 50%, {color}11 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        .card {{
            background: white;
            border-radius: 24px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.08), 0 4px 16px rgba(0,0,0,0.04);
            max-width: 440px;
            width: 100%;
            overflow: hidden;
            transition: transform 0.3s ease;
        }}
        .card:hover {{
            transform: translateY(-4px);
        }}
        .card-header {{
            background: linear-gradient(135deg, {color} 0%, {color}dd 100%);
            padding: 40px 32px;
            text-align: center;
            color: white;
            position: relative;
        }}
        .card-header::after {{
            content: '';
            position: absolute;
            bottom: -1px;
            left: 0;
            right: 0;
            height: 20px;
            background: white;
            border-radius: 24px 24px 0 0;
        }}
        .avatar {{
            width: 80px; height: 80px;
            border-radius: 50%;
            background: rgba(255,255,255,0.2);
            display: flex; align-items: center; justify-content: center;
            margin: 0 auto 16px;
            font-size: 36px;
            backdrop-filter: blur(8px);
            border: 3px solid rgba(255,255,255,0.3);
        }}
        .card-header h1 {{
            font-size: 24px;
            font-weight: 700;
            margin-bottom: 4px;
            letter-spacing: -0.02em;
        }}
        .handle {{
            opacity: 0.85;
            font-size: 14px;
            font-weight: 500;
        }}
        .badge {{
            display: inline-block;
            background: rgba(255,255,255,0.2);
            padding: 4px 14px;
            border-radius: 12px;
            font-size: 12px;
            margin-top: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            font-weight: 600;
            backdrop-filter: blur(4px);
        }}
        .card-body {{
            padding: 32px;
        }}
        .card-body p {{
            color: #555;
            line-height: 1.7;
            margin-bottom: 24px;
            font-size: 15px;
        }}
        .chat-btn {{
            display: block;
            width: 100%;
            padding: 16px;
            background: linear-gradient(135deg, {color} 0%, {color}dd 100%);
            color: white;
            border: none;
            border-radius: 14px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            text-align: center;
            text-decoration: none;
            transition: transform 0.2s, box-shadow 0.2s;
            letter-spacing: -0.01em;
        }}
        .chat-btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 8px 24px {color}44;
        }}
        .chat-btn:active {{
            transform: translateY(0);
        }}
        .powered {{
            text-align: center;
            padding: 16px 32px;
            font-size: 12px;
            color: #999;
            border-top: 1px solid #f0f0f0;
        }}
        .powered a {{
            color: #666;
            text-decoration: none;
            font-weight: 500;
        }}
        .powered a:hover {{
            color: {color};
        }}
        @media (max-width: 480px) {{
            body {{ padding: 12px; }}
            .card {{ border-radius: 20px; }}
            .card-header {{ padding: 32px 24px; }}
            .card-body {{ padding: 24px; }}
        }}
    </style>
</head>
<body>
    <div class="card">
        <div class="card-header">
            {avatar_html}
            <h1>{name}</h1>
            <div class="handle">@{handle}</div>
            {badge_html}
        </div>
        <div class="card-body">
            <p>{body_text}</p>
            <button class="chat-btn" onclick="openChat()">
                &#x1F4AC; Chat with {name}
            </button>
        </div>
        <div class="powered">
            Powered by <a href="https://dingdawg.com">DingDawg</a>
        </div>
    </div>
    <script>
        function openChat() {{
            var bubble = document.querySelector('.dd-widget-bubble');
            if (bubble) {{
                bubble.click();
                return;
            }}
            window.open('{base_url}/chat/{handle}', '_blank', 'noopener,noreferrer');
        }}
    </script>
    <script
            src="{base_url}/api/v1/widget/embed.js"
            data-agent="@{handle}"
            data-color="{color}"
            defer></script>
</body>
</html>'''


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/agents")
@public_rate_limit()
async def list_public_agents(
    request: Request,
    industry: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> JSONResponse:
    """List all public agents (agent directory / marketplace).

    Optional filter by industry type.

    Parameters
    ----------
    industry:
        If given, only agents with this ``industry_type`` are returned.
    limit:
        Maximum number of results (1-100, default 20).
    offset:
        Number of results to skip for pagination.

    Returns
    -------
    JSONResponse
        ``{agents: [{handle, name, description, industry, ...}], total: int}``
    """
    agent_registry = getattr(request.app.state, "agent_registry", None)
    if agent_registry is None:
        raise HTTPException(status_code=503, detail="Agent registry not initialised")

    agents, total = await agent_registry.list_public_agents(
        industry_type=industry,
        limit=limit,
        offset=offset,
    )

    return JSONResponse(
        content={
            "agents": [_agent_to_public_dict(a) for a in agents],
            "total": total,
            "limit": limit,
            "offset": offset,
        },
        headers={"Access-Control-Allow-Origin": "*"},
    )


@router.get("/agents/{handle}")
@public_rate_limit()
async def get_agent_profile(request: Request, handle: str) -> JSONResponse:
    """Get a single agent's public profile.

    Parameters
    ----------
    handle:
        The unique ``@handle`` of the agent (with or without the ``@`` prefix).

    Returns
    -------
    JSONResponse
        Full public profile including capabilities, embed code, and chat URL.
    """
    handle = handle.lstrip("@")

    agent_registry = getattr(request.app.state, "agent_registry", None)
    if agent_registry is None:
        raise HTTPException(status_code=503, detail="Agent registry not initialised")

    agent = await agent_registry.get_agent_by_handle(handle)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    if agent.status.value != "active":
        raise HTTPException(status_code=404, detail="Agent not found")

    base_url = _get_base_url(request)
    profile = _agent_to_public_dict(agent)

    config = _parse_config(agent)

    # Add extended profile fields
    profile["capabilities"] = config.get("capabilities", [])
    profile["card_url"] = f"{base_url}/api/v1/public/agents/{handle}/card"
    profile["chat_url"] = f"{base_url}/chat/{handle}"
    profile["qr_url"] = f"{base_url}/api/v1/public/agents/{handle}/qr"
    profile["widget_embed_code"] = (
        f'<script src="{base_url}/api/v1/widget/embed.js" '
        f'data-agent="@{handle}" '
        f'data-color="{profile["primary_color"]}"></script>'
    )

    return JSONResponse(
        content=profile,
        headers={"Access-Control-Allow-Origin": "*"},
    )


@router.get("/agents/{handle}/card")
@public_rate_limit()
async def agent_card_page(request: Request, handle: str) -> HTMLResponse:
    """Render a standalone HTML agent card page.

    This is the shareable link -- a self-contained HTML page with:
    - Agent name, avatar, description
    - Industry badge
    - "Chat Now" button that opens the widget
    - Embedded widget auto-loaded
    - Open Graph meta tags for social sharing

    Parameters
    ----------
    handle:
        The unique ``@handle`` of the agent (with or without the ``@`` prefix).

    Returns
    -------
    HTMLResponse
        A complete, mobile-responsive HTML page.
    """
    handle = handle.lstrip("@")

    agent_registry = getattr(request.app.state, "agent_registry", None)
    if agent_registry is None:
        raise HTTPException(status_code=503, detail="Agent registry not initialised")

    agent = await agent_registry.get_agent_by_handle(handle)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    if agent.status.value != "active":
        raise HTTPException(status_code=404, detail="Agent not found")

    base_url = _get_base_url(request)
    agent_dict = _agent_to_public_dict(agent)
    html = _render_card_html(agent_dict, base_url)

    return HTMLResponse(
        content=html,
        headers={
            "Cache-Control": "public, max-age=300",
        },
    )


@router.get("/agents/{handle}/qr")
@public_rate_limit()
async def agent_qr_code(request: Request, handle: str) -> Response:
    """Generate a QR code linking to the agent's card page.

    Businesses print this on receipts, menus, business cards, etc.

    Parameters
    ----------
    handle:
        The unique ``@handle`` of the agent (with or without the ``@`` prefix).

    Returns
    -------
    Response
        PNG image of the QR code if a QR library is available,
        otherwise JSON with the card URL for manual QR generation.
    """
    handle = handle.lstrip("@")

    agent_registry = getattr(request.app.state, "agent_registry", None)
    if agent_registry is None:
        raise HTTPException(status_code=503, detail="Agent registry not initialised")

    agent = await agent_registry.get_agent_by_handle(handle)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    if agent.status.value != "active":
        raise HTTPException(status_code=404, detail="Agent not found")

    base_url = _get_base_url(request)
    card_url = f"{base_url}/api/v1/public/agents/{handle}/card"

    # Try segno first, then qrcode, fall back to JSON
    try:
        import segno  # type: ignore[import-untyped]

        qr = segno.make(card_url)
        buf = io.BytesIO()
        qr.save(buf, kind="png", scale=8, border=2)
        buf.seek(0)
        return Response(
            content=buf.getvalue(),
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=3600",
                "Access-Control-Allow-Origin": "*",
            },
        )
    except ImportError:
        pass

    try:
        import qrcode  # type: ignore[import-untyped]

        qr_img = qrcode.make(card_url)
        buf = io.BytesIO()
        qr_img.save(buf, format="PNG")
        buf.seek(0)
        return Response(
            content=buf.getvalue(),
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=3600",
                "Access-Control-Allow-Origin": "*",
            },
        )
    except ImportError:
        pass

    # Fallback: return the URL as JSON so the caller can generate
    # a QR code client-side
    return JSONResponse(
        content={
            "card_url": card_url,
            "message": (
                "QR code library not installed. "
                "Use the card_url to generate a QR code."
            ),
        },
        headers={"Access-Control-Allow-Origin": "*"},
    )


@router.get("/agents/{handle}/.well-known/agent.json")
@public_rate_limit()
async def agent_well_known(request: Request, handle: str) -> JSONResponse:
    """A2A/ACP-compatible agent discovery document.

    Standard agent identity document for agent-to-agent protocols.
    Follows the A2A v0.3 agent card specification.

    Parameters
    ----------
    handle:
        The unique ``@handle`` of the agent (with or without the ``@`` prefix).

    Returns
    -------
    JSONResponse
        Agent identity in A2A-compatible format.
    """
    handle = handle.lstrip("@")

    agent_registry = getattr(request.app.state, "agent_registry", None)
    if agent_registry is None:
        raise HTTPException(status_code=503, detail="Agent registry not initialised")

    agent = await agent_registry.get_agent_by_handle(handle)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    if agent.status.value != "active":
        raise HTTPException(status_code=404, detail="Agent not found")

    base_url = _get_base_url(request)
    config = _parse_config(agent)
    branding = _parse_branding(agent)

    return JSONResponse(
        content={
            "name": agent.name,
            "handle": f"@{agent.handle}",
            "description": config.get("description", ""),
            "url": f"{base_url}/api/v1/public/agents/{handle}/card",
            "provider": {
                "organization": "DingDawg",
                "url": "https://dingdawg.com",
            },
            "version": "1.0.0",
            "capabilities": config.get("capabilities", []),
            "skills": config.get("skills", []),
            "defaultInputModes": ["text"],
            "defaultOutputModes": ["text"],
            "endpoints": {
                "widget_config": f"{base_url}/api/v1/widget/{handle}/config",
                "widget_session": f"{base_url}/api/v1/widget/{handle}/session",
                "widget_message": f"{base_url}/api/v1/widget/{handle}/message",
                "public_profile": f"{base_url}/api/v1/public/agents/{handle}",
                "card_page": f"{base_url}/api/v1/public/agents/{handle}/card",
            },
            "protocols": {
                "a2a": "0.3",
                "dingdawg_widget": "1.0",
            },
            "authentication": {
                "schemes": ["anonymous"],
                "note": "Widget endpoints accept anonymous visitors",
            },
            "branding": {
                "primary_color": branding.get("primary_color", "#7C3AED"),
                "avatar_url": branding.get("avatar_url", ""),
            },
        },
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=3600",
        },
    )


# ---------------------------------------------------------------------------
# ATR v1.0 — Receipt endpoints
# ---------------------------------------------------------------------------


@router.get("/receipt/sample")
@public_rate_limit()
async def receipt_sample(request: Request) -> JSONResponse:
    """Return a static sample ATR v1.0 receipt.

    Demonstrates the receipt schema for fintech compliance outreach.
    Used as a sales artifact — regulators and bank partners can inspect
    the format before integration.

    Returns
    -------
    JSONResponse
        A static sample receipt conforming to the ATR v1.0 schema.
    """
    return JSONResponse(
        content=SAMPLE_RECEIPT,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.get("/receipt/schema")
@public_rate_limit()
async def receipt_schema(request: Request) -> JSONResponse:
    """Return the ATR v1.0 JSON Schema.

    The canonical schema for agent-driven decision receipts.
    Any system can validate a receipt against this schema.

    Returns
    -------
    JSONResponse
        The ATR v1.0 JSON Schema document.
    """
    return JSONResponse(
        content=RECEIPT_SCHEMA,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=300",
        },
    )


@router.post("/receipt")
@public_rate_limit()
async def create_receipt(request: Request) -> JSONResponse:
    """Create a new ATR v1.0 receipt.

    Stores a compliance receipt in the database. Returns the full
    receipt with a generated receipt_id and timestamp.

    Always requires a real X-API-Key header matching ISG_AGENT_ATR_API_KEY --
    unlike reads, an unconfigured key denies rather than opens this endpoint
    (this mints entries in a compliance ledger; it must never be forgeable).
    """
    if not _verify_atr_api_key(request, require_configured=True):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    body: dict[str, Any] = await request.json()
    agent_id: str = body.get("agent_id", "")
    decision: str = body.get("decision", "")
    decision_reason: str = body.get("decision_reason", "")
    subject_id: str = body.get("subject_id", "")
    policy_version: str | None = body.get("policy_version")
    confidence_score: int | None = body.get("confidence_score")
    parent_receipt_id: str | None = body.get("parent_receipt_id")

    if not agent_id:
        raise HTTPException(status_code=422, detail="agent_id is required")
    if decision not in ("APPROVE", "DECLINE", "REVIEW"):
        raise HTTPException(status_code=422, detail="decision must be APPROVE, DECLINE, or REVIEW")
    if not subject_id:
        raise HTTPException(status_code=422, detail="subject_id is required")
    if confidence_score is not None and not (0 <= confidence_score <= 100):
        raise HTTPException(status_code=422, detail="confidence_score must be 0-100")

    db_path = _resolve_db_path(request)
    if not db_path:
        # A receipt that is not persisted is not a receipt — fail loudly.
        raise HTTPException(status_code=503, detail="Database not configured")

    from isg_agent.db.receipts import persist_receipt

    receipt = await persist_receipt(
        db_path=db_path,
        base_url=_get_base_url(request),
        agent_id=agent_id,
        decision=decision,
        decision_reason=decision_reason,
        subject_id=subject_id,
        policy_version=policy_version,
        confidence_score=confidence_score,
        parent_receipt_id=parent_receipt_id,
    )

    return JSONResponse(
        content=receipt,
        status_code=201,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Location": str(receipt["verification_endpoint"]),
        },
    )


@router.get("/trust-score/{handle}")
@public_rate_limit()
async def trust_score(handle: str, request: Request) -> JSONResponse:
    """Public, PII-free trust summary of an agent's receipt trail (Wave 3).

    Buyer agents cite this before recommending a counterparty. An agent
    with no history reports ``score: null`` — unknown, never 0 or 100.
    """
    db_path = _resolve_db_path(request)
    if not db_path:
        raise HTTPException(status_code=503, detail="Database not configured")

    from isg_agent.db.receipts import trust_summary

    summary = await trust_summary(db_path=db_path, agent_id=handle)
    return JSONResponse(
        content=summary,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=60",
        },
    )


@router.get("/receipt/{receipt_id}")
@public_rate_limit()
async def get_receipt(request: Request, receipt_id: str) -> JSONResponse:
    """Retrieve an ATR v1.0 receipt by ID.

    Returns the full receipt record. Requires X-API-Key header
    if ISG_AGENT_ATR_API_KEY is configured.

    Parameters
    ----------
    receipt_id:
        The UUID of the receipt to retrieve.

    Returns
    -------
    JSONResponse
        The full receipt record or 404 if not found.
    """
    if not _verify_atr_api_key(request):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    db_path = _resolve_db_path(request)
    if not db_path:
        raise HTTPException(status_code=503, detail="Database not configured")

    import aiosqlite

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM atr_receipts WHERE receipt_id = ?", (receipt_id,)
        )
        row = await cursor.fetchone()

    if row is None:
        # Fallback: check if it matches the sample receipt
        if receipt_id == SAMPLE_RECEIPT["receipt_id"]:
            return JSONResponse(
                content=SAMPLE_RECEIPT,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Cache-Control": "public, max-age=300",
                },
            )
        raise HTTPException(status_code=404, detail="Receipt not found")

    receipt: dict[str, object] = {
        "receipt_id": row["receipt_id"],
        "agent_id": row["agent_id"],
        "decision": row["decision"],
        "decision_reason": row["decision_reason"],
        "timestamp": row["timestamp"],
        "subject_id": row["subject_id"],
        "policy_version": row["policy_version"],
        "confidence_score": row["confidence_score"],
        "parent_receipt_id": row["parent_receipt_id"],
        "verification_endpoint": row["verification_endpoint"],
    }

    return JSONResponse(
        content=receipt,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=60",
        },
    )
