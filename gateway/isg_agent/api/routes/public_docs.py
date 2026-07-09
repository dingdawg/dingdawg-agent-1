"""Curated public API documentation surface.

Serves a FILTERED OpenAPI contract at ``/openapi.json`` and a human-readable
Swagger UI page at ``/docs`` — in EVERY environment, including production.

Why not FastAPI's built-in docs?
--------------------------------
The auto-generated spec includes 290+ routes: admin, internal governance,
WebAuthn, MFA, CLI device-flow, Zapier/Nango plumbing, and inbound webhooks.
Exposing that publicly leaks internal architecture (IP) and widens the
attack surface.  The built-in docs are therefore disabled in ``app.py``
(``docs_url=None, openapi_url=None``) and replaced by this module, which
builds the spec from an explicit ALLOWLIST of buyer-facing routes.

Selection model (deny by default):
1. A route is included only if it matches a rule in ``PUBLIC_SPEC_RULES``
   (path prefix/exact + allowed HTTP methods).
2. Defense in depth: any selected path containing a marker from
   ``_DENY_MARKERS`` is dropped and logged, even if a rule matched it.

Also serves ``/.well-known/security.txt`` (RFC 9116).

Middleware compatibility (no locked-file changes needed):
- TierIsolationMiddleware passes non-API paths (``/docs``, ``/openapi.json``,
  ``/.well-known/*``) through unconditionally.
- route_validator's ``PUBLIC_PATH_PREFIXES`` already whitelists ``/docs``,
  ``/redoc``, ``/openapi.json`` and ``/.well-known``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.routing import APIRoute

from isg_agent.middleware.rate_limiter_middleware import public_rate_limit

__all__ = ["router", "build_public_openapi_schema"]

logger = logging.getLogger(__name__)

router = APIRouter(tags=["documentation"])

# ---------------------------------------------------------------------------
# Public surface allowlist
# ---------------------------------------------------------------------------
# Each rule: (path, allowed_methods_or_None, match_type)
#   match_type "exact"  — route path must equal the rule path
#   match_type "prefix" — route path must start with the rule path
#   methods None        — any method the route declares
#
# This is the ENTIRE public API contract.  Anything not listed here does
# not exist as far as the public spec is concerned.
PUBLIC_SPEC_RULES: tuple[tuple[str, frozenset[str] | None, str], ...] = (
    # System health (public liveness probe)
    ("/health", frozenset({"GET"}), "exact"),
    # Public agent directory, profiles, cards, QR codes, agent.json,
    # and ATR v1.0 governance receipts
    ("/api/v1/public/", None, "prefix"),
    ("/api/v1/public", frozenset({"GET"}), "exact"),
    # Skills catalog (read-only browsing)
    ("/api/v1/skills", frozenset({"GET"}), "prefix"),
    # Template gallery (public, used before account creation)
    ("/api/v1/templates", frozenset({"GET"}), "prefix"),
    # Agent handle availability check
    ("/api/v1/agents/handle", frozenset({"GET"}), "prefix"),
    # Agent self-onboarding (anonymous request + poll + email approve)
    ("/api/v1/agents/self-onboard", None, "prefix"),
    # Onboarding wizard public steps
    ("/api/v1/onboarding/sectors", frozenset({"GET"}), "exact"),
    ("/api/v1/onboarding/check-handle", frozenset({"GET"}), "prefix"),
    # Payments checkout surface (authenticated, but part of the contract)
    ("/api/v1/payments/create-checkout-session", frozenset({"POST"}), "exact"),
    # Platform discovery documents + security.txt
    ("/.well-known/", frozenset({"GET"}), "prefix"),
    # Agent-readable platform manifest (llmstxt.org convention)
    ("/llms.txt", frozenset({"GET"}), "exact"),
)

#: Defense in depth — a selected path containing any of these markers is
#: dropped from the public spec even if an allowlist rule matched it.
_DENY_MARKERS: tuple[str, ...] = (
    "admin",
    "internal",
    "console",
    "mfa",
    "passkey",
    "webauthn",
    "cli/",
    "zapier",
    "nango",
    "webhook",
    "comms",
    "finance",
    "audit",
    "trust",
    "attest",
    "compliance",
    "system",
)

_DEFAULT_PUBLIC_BASE = "https://api.dingdawg.com"

_SPEC_TITLE = "DingDawg Agent Platform — Public API"
_SPEC_DESCRIPTION = (
    "Public API for the DingDawg Agent Platform: agent discovery, "
    "public agent profiles and cards, the skills catalog, template "
    "gallery, onboarding, checkout, and ATR v1.0 governance receipts "
    "(verifiable agent decision audit records). "
    "Endpoints tagged `public` require no authentication. "
    "The checkout endpoint requires a Bearer token (JWT) obtained via "
    "account login. Receipt write/read-by-id endpoints require an "
    "`X-API-Key` header when the platform has an ATR API key configured."
)


def _public_base_url() -> str:
    """Canonical public base URL — never an internal hosting hostname."""
    from isg_agent.config import get_settings

    try:
        configured = (get_settings().public_url or "").rstrip("/")
    except Exception:  # pragma: no cover — settings should always load
        configured = ""
    if not configured or "railway" in configured.lower():
        return _DEFAULT_PUBLIC_BASE
    return configured


def _route_matches(path: str, methods: frozenset[str]) -> bool:
    """Return True if (path, methods) is allowed into the public spec."""
    for rule_path, rule_methods, match_type in PUBLIC_SPEC_RULES:
        if match_type == "exact":
            if path != rule_path:
                continue
        elif not path.startswith(rule_path):
            continue
        if rule_methods is not None and not (methods & rule_methods):
            continue
        return True
    return False


def build_public_openapi_schema(app: Any) -> dict[str, Any]:
    """Build the curated public OpenAPI schema from the live route table.

    Deny-by-default: only allowlisted routes are passed to FastAPI's
    ``get_openapi``; a marker denylist then drops anything suspicious.
    """
    from fastapi.openapi.utils import get_openapi

    from isg_agent.core.route_validator import iter_api_routes

    selected: list[APIRoute] = []
    for route in iter_api_routes(app.routes):
        if not route.include_in_schema:
            continue
        methods = frozenset(route.methods or set())
        if not _route_matches(route.path, methods):
            continue
        lowered = route.path.lower()
        denied = [m for m in _DENY_MARKERS if m in lowered]
        if denied:
            logger.warning(
                "public_docs: route %s matched allowlist but hit deny markers %s — dropped",
                route.path,
                denied,
            )
            continue
        selected.append(route)

    base_url = _public_base_url()
    schema = get_openapi(
        title=_SPEC_TITLE,
        version=getattr(app, "version", "1.0.0"),
        description=_SPEC_DESCRIPTION,
        routes=selected,
        servers=[{"url": base_url, "description": "Production"}],
    )
    schema.setdefault("info", {})["contact"] = {
        "name": "DingDawg Support",
        "email": "hello@dingdawg.com",
        "url": "https://dingdawg.com",
    }

    # -- Security schemes -------------------------------------------------
    components = schema.setdefault("components", {})
    schemes = components.setdefault("securitySchemes", {})
    schemes["bearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "JWT obtained from account login.",
    }
    schemes["atrApiKey"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": (
            "ATR receipt API key. Required for receipt creation and "
            "receipt retrieval by ID when the platform has an ATR API "
            "key configured; otherwise these endpoints are open."
        ),
    }

    paths = schema.get("paths", {})

    def _attach_security(path: str, method: str, requirement: dict[str, list[str]]) -> None:
        op = paths.get(path, {}).get(method)
        if op is not None:
            op["security"] = [requirement]

    _attach_security(
        "/api/v1/payments/create-checkout-session", "post", {"bearerAuth": []}
    )
    _attach_security("/api/v1/public/receipt", "post", {"atrApiKey": []})
    _attach_security(
        "/api/v1/public/receipt/{receipt_id}", "get", {"atrApiKey": []}
    )

    # -- Enrich the ATR receipt contract with real schemas ----------------
    try:
        from isg_agent.api.routes.public import RECEIPT_SCHEMA, SAMPLE_RECEIPT

        receipt_object_schema = {
            "type": "object",
            "required": RECEIPT_SCHEMA.get("required", []),
            "properties": RECEIPT_SCHEMA.get("properties", {}),
        }
        create_op = paths.get("/api/v1/public/receipt", {}).get("post")
        if create_op is not None:
            create_op["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["agent_id", "decision", "subject_id"],
                            "properties": RECEIPT_SCHEMA.get("properties", {}),
                        },
                        "example": {
                            k: v
                            for k, v in SAMPLE_RECEIPT.items()
                            if k not in ("receipt_id", "timestamp", "verification_endpoint")
                        },
                    }
                },
            }
            create_op.setdefault("responses", {})["201"] = {
                "description": "Receipt created",
                "content": {
                    "application/json": {
                        "schema": receipt_object_schema,
                        "example": SAMPLE_RECEIPT,
                    }
                },
            }
        get_op = paths.get("/api/v1/public/receipt/{receipt_id}", {}).get("get")
        if get_op is not None:
            get_op.setdefault("responses", {})["200"] = {
                "description": "The receipt record",
                "content": {
                    "application/json": {
                        "schema": receipt_object_schema,
                        "example": SAMPLE_RECEIPT,
                    }
                },
            }
    except Exception as exc:  # pragma: no cover — enrichment is best-effort
        logger.warning("public_docs: receipt schema enrichment failed: %s", exc)

    return schema


def _route_table_size(app: Any) -> int:
    """Count APIRoutes currently registered — the cache-validity fingerprint.

    Recurses into container routes (newer FastAPI include_router shape) via
    iter_api_routes; a flat isinstance scan undercounts to 1 in production.
    """
    from isg_agent.core.route_validator import iter_api_routes

    return sum(1 for _ in iter_api_routes(app.routes))


def _cached_schema(request: Request) -> dict[str, Any]:
    """Return the public schema, rebuilt whenever the route table drifts.

    A plain build-once cache pinned an EMPTY spec in production: the first
    build ran against a route table that was not yet fully populated, and
    the /health-only result was then served forever. Keying the cache on
    the live APIRoute count makes it self-healing — any drift (late mounts,
    early build, hot reload) triggers a rebuild on the next request.
    """
    app = request.app
    size = _route_table_size(app)
    cached = getattr(app.state, "public_openapi_schema", None)
    cached_size = getattr(app.state, "public_openapi_route_count", None)
    if cached is None or cached_size != size:
        if cached is not None:
            logger.warning(
                "public_docs: route table drifted (%s -> %s APIRoutes) — rebuilding public spec",
                cached_size, size,
            )
        cached = build_public_openapi_schema(app)
        cached.setdefault("info", {})["x-route-table-size"] = size
        app.state.public_openapi_schema = cached
        app.state.public_openapi_route_count = size
    return cached


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/openapi.json", include_in_schema=False)
@public_rate_limit()
async def public_openapi(request: Request) -> JSONResponse:
    """Serve the curated public OpenAPI 3.x contract."""
    return JSONResponse(
        content=_cached_schema(request),
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=300",
        },
    )


@router.get("/docs", include_in_schema=False)
@public_rate_limit()
async def public_docs(request: Request) -> HTMLResponse:
    """Serve Swagger UI bound to the curated public spec."""
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title=f"{_SPEC_TITLE} — Docs",
    )


@router.get(
    "/.well-known/security.txt",
    summary="Vulnerability disclosure policy (RFC 9116)",
    response_class=PlainTextResponse,
)
@public_rate_limit()
async def security_txt(request: Request) -> PlainTextResponse:
    """Serve the RFC 9116 security.txt vulnerability-disclosure document."""
    expires = (datetime.now(timezone.utc) + timedelta(days=365)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    base_url = _public_base_url()
    body = (
        "Contact: mailto:hello@dingdawg.com\n"
        f"Expires: {expires}\n"
        f"Canonical: {base_url}/.well-known/security.txt\n"
        "Preferred-Languages: en\n"
    )
    return PlainTextResponse(
        content=body,
        headers={"Cache-Control": "public, max-age=86400"},
    )
