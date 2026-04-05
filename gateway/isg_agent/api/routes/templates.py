"""Template discovery endpoints.

Provides the HTTP API for listing and retrieving agent templates.
All endpoints are public — no authentication required — to allow
agent creation flows to discover available templates before a user
has configured their account.

Internal templates (agent_type == "enterprise") are used by DingDawg's
own operated agents and are never exposed via the public discovery API.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, status

from isg_agent.agents.agent_types import VALID_AGENT_TYPES
from isg_agent.templates.template_registry import TemplateRegistry
from isg_agent.schemas.agents import TemplateList, TemplateResponse

# Industry types that identify DingDawg's own operated agents.
# These templates contain proprietary configuration and must never be exposed
# via the public discovery API.
_INTERNAL_INDUSTRY_TYPES: frozenset[str] = frozenset({
    "dingdawg_support",
    "dingdawg_sales",
})

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/templates", tags=["templates"])


# ---------------------------------------------------------------------------
# Helper: extract template registry from app state
# ---------------------------------------------------------------------------


def _get_template_registry(request: Request) -> TemplateRegistry:
    """Extract the TemplateRegistry from FastAPI app state.

    Raises 503 Service Unavailable if the registry is not yet initialised.
    """
    registry: Optional[TemplateRegistry] = getattr(
        request.app.state, "template_registry", None
    )
    if registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Template registry not initialised. Server is starting up.",
        )
    return registry


def _template_to_response(template) -> TemplateResponse:  # type: ignore[no-untyped-def]
    """Convert a TemplateRecord to a TemplateResponse DTO."""
    return TemplateResponse(
        id=template.id,
        name=template.name,
        agent_type=template.agent_type,
        industry_type=template.industry_type,
        capabilities=template.capabilities,
        icon=template.icon,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=TemplateList,
    summary="List all available agent templates",
)
async def list_templates(
    request: Request,
    agent_type: Optional[str] = Query(
        default=None,
        description=(
            "Filter by agent type. Valid values: "
            + ", ".join(f"'{t}'" for t in sorted(VALID_AGENT_TYPES))
            + "."
        ),
    ),
    industry_type: Optional[str] = Query(
        default=None,
        description="Filter by industry slug (e.g. 'restaurant', 'salon').",
    ),
) -> TemplateList:
    """Return all seeded agent templates, with optional filtering.

    This endpoint is public — no authentication required.

    Query parameters:
    - ``agent_type``: filter to ``"personal"`` or ``"business"`` templates.
    - ``industry_type``: filter by industry slug (e.g. ``"restaurant"``).
    """
    registry = _get_template_registry(request)

    # Validate agent_type filter if provided
    if agent_type is not None and agent_type not in VALID_AGENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "agent_type must be one of: "
                + ", ".join(f"'{t}'" for t in sorted(VALID_AGENT_TYPES))
            ),
        )

    templates = await registry.list_templates(
        agent_type=agent_type,
        industry_type=industry_type,
    )
    # Strip internal-only templates from the public response.
    # DingDawg's own operated agent templates (identified by industry_type) must
    # not be discoverable via the public API — they contain proprietary configuration
    # including internal system names and competitive intelligence.
    public_templates = [t for t in templates if t.industry_type not in _INTERNAL_INDUSTRY_TYPES]
    items = [_template_to_response(t) for t in public_templates]
    return TemplateList(templates=items, count=len(items))


@router.get(
    "/{template_id}",
    response_model=TemplateResponse,
    summary="Get a single template by ID",
)
async def get_template(
    template_id: str,
    request: Request,
) -> TemplateResponse:
    """Retrieve a single template by its UUID.

    This endpoint is public — no authentication required.

    Returns 404 if no template with the given ID exists.
    """
    registry = _get_template_registry(request)

    template = await registry.get_template(template_id)
    # Return 404 for both missing templates and internal-only templates so
    # that internal template IDs cannot be enumerated via the public API.
    if template is None or template.industry_type in _INTERNAL_INDUSTRY_TYPES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found.",
        )

    return _template_to_response(template)
