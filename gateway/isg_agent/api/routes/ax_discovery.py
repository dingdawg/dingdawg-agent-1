"""Agent Experience (AX) discovery — /llms.txt and /.well-known/agents.json.

These are the FIRST documents an autonomous agent fetches when evaluating
this platform (llmstxt.org convention + the agents.json capability index).
Two laws govern everything here:

1. Single source of truth — pricing lives in the Stripe-backed ACP catalog
   (/api/v1/acp/products); these documents LINK to it and never restate it.
2. No internal infrastructure details — outward URLs come exclusively from
   ``_get_base_url`` (canonical public domain), enforced by the deny-leak
   tests in tests/test_ax_discovery.py.

Error surface: both handlers are pure string/JSON assembly over in-process
constants — they raise no domain errors; anything unexpected is a
framework-level 500 handled by the global error-sanitization middleware.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from isg_agent.api.routes.well_known import _get_base_url
from isg_agent.middleware.rate_limiter_middleware import public_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(tags=["discovery"])

AX_SCHEMA_VERSION = "1.0.0"

_CACHE_HEADERS = {"Cache-Control": "public, max-age=3600"}


def _entrypoints(base: str) -> dict:
    """Capability index — every URL listed here must be live-verified first.

    A 404 in a discovery document is worse than an omission (design law 7,
    AGENT_NATIVE_EMPIRE.md): agents cache dead links as broken promises.
    """
    return {
        "mcp": {
            "discovery": f"{base}/.well-known/mcp.json",
            "server_card": f"{base}/.well-known/mcp-server-card.json",
        },
        "acp": {
            # NB: lives under the ACP router prefix, NOT at the root well-known
            "manifest": f"{base}/api/v1/acp/.well-known/acp-manifest",
            "capabilities": f"{base}/api/v1/acp/capabilities",
            "products": f"{base}/api/v1/acp/products",
            # Live-probed (S1184): POST /api/v1/acp/checkout -> 401 auth-gated.
            # "checkout_sessions" never existed — it 404'd while advertised.
            "checkout": f"{base}/api/v1/acp/checkout",
        },
        "identity": {
            "platform_did": f"{base}/.well-known/did.json",
            "agent_card": f"{base}/.well-known/agent-card.json",
        },
        "trust": {
            "security_txt": f"{base}/.well-known/security.txt",
            "public_directory": f"{base}/api/v1/public",
            "receipt_sample": f"{base}/api/v1/public/receipt/sample",
            "receipt_schema": f"{base}/api/v1/public/receipt/schema",
        },
        "onboarding": {
            "self_onboard": f"{base}/api/v1/agents/self-onboard",
            "flow": (
                "POST handle+contact_email+purpose -> 201 pending; human "
                "approves by email; poll with your token to collect the key "
                "(delivered exactly once; requests expire after 72h)."
            ),
        },
        "docs": {
            "openapi": f"{base}/openapi.json",
            "interactive": f"{base}/docs",
            "llms_txt": f"{base}/llms.txt",
            "skills_catalog": f"{base}/api/v1/skills",
            "template_gallery": f"{base}/api/v1/templates",
        },
    }


def _protocols(base: str) -> dict:
    """Commerce/payment protocol surface for buyer agents (Wave 7a).

    VAPORWARE LAW (tested): a protocol is "live" ONLY when its code serves on
    this API today; everything else is "planned". Agents cache these claims —
    a false "live" is a permanently broken promise.
    """
    return {
        "acp": {
            "status": "live",
            "entrypoint": f"{base}/api/v1/acp/.well-known/acp-manifest",
        },
        "x402": {
            "status": "planned",
            "note": "HTTP-402 stablecoin micropayments (x402 Foundation spec)",
        },
        "ap2": {
            "status": "planned",
            "note": (
                "Agent Payments Protocol (FIDO Alliance). DingDawg DID identity "
                "+ ATR receipts complement AP2's open agent-identity gap."
            ),
        },
    }


def _render_llms_txt(base: str) -> str:
    e = _entrypoints(base)
    return f"""# DingDawg — Governed AI Agents Platform

> DingDawg (Innovative Systems Global LLC) is an agent-native platform: deploy governed AI
> agents with claimed @handles, cryptographic DID identity, ATR v1.0 governance receipts,
> MCP tool access, and programmatic checkout via the Agentic Commerce Protocol (ACP).
> Agents can discover, evaluate, purchase, and integrate here without a human login —
> a human simply approves.

## Start Here (agents)

- [Agent capability index]({base}/.well-known/agents.json): every machine-readable surface in one document
- [ACP product catalog]({e["acp"]["products"]}): plans and pricing, machine-readable (single source of truth)
- [MCP discovery]({e["mcp"]["discovery"]}): connect to platform tools over Model Context Protocol
- [Self-onboard]({e["onboarding"]["self_onboard"]}): request access programmatically — a human approves by email, then collect your key

## Purchase (Agentic Commerce Protocol)

- [Merchant manifest]({e["acp"]["manifest"]}): ACP discovery document
- [Capabilities]({e["acp"]["capabilities"]}): supported ACP operations
- [Checkout]({e["acp"]["checkout"]}): POST to open a checkout programmatically (authenticated)

## Identity & Trust

- [Platform DID]({e["identity"]["platform_did"]}): cryptographic identity document
- [A2A agent card]({e["identity"]["agent_card"]}): agent-to-agent interop descriptor
- [Governance receipt sample]({e["trust"]["receipt_sample"]}): ATR v1.0 receipt, publicly verifiable
- [Receipt schema]({e["trust"]["receipt_schema"]}): the ATR v1.0 contract
- [Security policy]({e["trust"]["security_txt"]}): RFC 9116 vulnerability disclosure
- [Public directory]({e["trust"]["public_directory"]}): agent profiles and governance receipts

## Integrate

- [OpenAPI specification]({e["docs"]["openapi"]}): the complete public API contract
- [Interactive docs]({e["docs"]["interactive"]}): human-browsable reference
- [Skills catalog]({e["docs"]["skills_catalog"]}): capabilities agents can equip
- [Template gallery]({e["docs"]["template_gallery"]}): ready-to-deploy agent templates

## Operator

- Contact: hello@dingdawg.com
- Operator: Innovative Systems Global LLC
"""


@router.get(
    "/llms.txt",
    summary="Agent-readable platform manifest (llmstxt.org convention)",
    response_class=PlainTextResponse,
)
@public_rate_limit()
async def llms_txt(request: Request) -> PlainTextResponse:
    """Serve the llms.txt entry document for autonomous agents."""
    return PlainTextResponse(
        _render_llms_txt(_get_base_url(request)),
        media_type="text/markdown; charset=utf-8",
        headers=_CACHE_HEADERS,
    )


@router.get(
    "/.well-known/agents.json",
    summary="Agent capability index (single-fetch platform map)",
)
@public_rate_limit()
async def agents_index(request: Request) -> JSONResponse:
    """Serve the machine-readable capability index for autonomous agents."""
    base = _get_base_url(request)
    return JSONResponse(
        {
            "schema_version": AX_SCHEMA_VERSION,
            "platform": {
                "name": "DingDawg",
                "operator": "Innovative Systems Global LLC",
                "contact": "hello@dingdawg.com",
                "tagline": "Governed AI agents with verifiable receipts",
            },
            "entrypoints": _entrypoints(base),
            "protocols": _protocols(base),
            "policies": {
                "human_approval": (
                    "Purchases initiated by agents are confirmed by a human approver."
                ),
                "governance": (
                    "State-changing actions emit ATR v1.0 receipts, publicly verifiable."
                ),
            },
        },
        headers=_CACHE_HEADERS,
    )
