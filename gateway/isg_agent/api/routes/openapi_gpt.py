"""GPT Actions OpenAPI spec endpoint.

Serves a filtered OpenAPI 3.1.0 specification containing ONLY the
public-facing endpoints suitable for GPT Custom Actions integration.

This is NOT the full FastAPI auto-generated spec (which includes 40+
internal/admin routes).  Instead it returns a hand-curated subset of
6 public endpoints that a GPT Action can call without authentication.

Endpoint: GET /api/v1/openapi-gpt.json
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

__all__ = ["router"]

router = APIRouter(tags=["openapi"])

# ---------------------------------------------------------------------------
# Production server URL — defaults to the canonical app domain.
# Override via OPENAPI_SERVER_URL env var if needed (e.g. staging).
# ---------------------------------------------------------------------------
_SERVER_URL = os.environ.get(
    "OPENAPI_SERVER_URL",
    "https://app.dingdawg.com",
)


def _build_gpt_openapi_spec() -> dict[str, Any]:
    """Build a minimal OpenAPI 3.1.0 spec for GPT Actions."""
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "DingDawg Agent 1 — Public API",
            "description": (
                "Public API for interacting with DingDawg AI agents. "
                "These endpoints require no authentication and are designed "
                "for GPT Custom Actions integration. Start a chat session "
                "with any agent, send messages, browse the agent directory, "
                "and discover available templates and industries."
            ),
            "version": "1.0.0",
            "contact": {
                "name": "DingDawg Support",
                "url": "https://dingdawg.com",
            },
        },
        "servers": [
            {
                "url": _SERVER_URL,
                "description": "Production server",
            },
        ],
        "paths": {
            # -- Widget: Start session -----------------------------------
            "/api/v1/widget/{handle}/session": {
                "post": {
                    "operationId": "startChatSession",
                    "summary": "Start a chat session with an agent",
                    "description": (
                        "Creates an anonymous chat session for a website visitor. "
                        "Returns a session_id and the agent's greeting message. "
                        "The session_id must be included in subsequent message requests."
                    ),
                    "parameters": [
                        {
                            "name": "handle",
                            "in": "path",
                            "required": True,
                            "description": "The agent's unique handle (without the @ prefix)",
                            "schema": {"type": "string", "example": "pizza-bot"},
                        },
                    ],
                    "requestBody": {
                        "required": False,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "visitor_id": {
                                            "type": "string",
                                            "description": "Optional visitor identifier for session continuity",
                                        },
                                    },
                                },
                            },
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Session created successfully",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "session_id": {
                                                "type": "string",
                                                "description": "Unique session identifier",
                                            },
                                            "visitor_id": {
                                                "type": "string",
                                                "description": "Visitor identifier (generated if not provided)",
                                            },
                                            "greeting_message": {
                                                "type": "string",
                                                "description": "The agent's greeting message",
                                            },
                                        },
                                        "required": ["session_id", "visitor_id", "greeting_message"],
                                    },
                                },
                            },
                        },
                        "404": {
                            "description": "Agent not found",
                        },
                    },
                },
            },
            # -- Widget: Send message ------------------------------------
            "/api/v1/widget/{handle}/message": {
                "post": {
                    "operationId": "sendMessage",
                    "summary": "Send a message to an agent and get a response",
                    "description": (
                        "Sends a user message to the agent and returns the agent's response. "
                        "Requires a valid session_id from startChatSession. "
                        "The message is processed through the full governed AI pipeline."
                    ),
                    "parameters": [
                        {
                            "name": "handle",
                            "in": "path",
                            "required": True,
                            "description": "The agent's unique handle (without the @ prefix)",
                            "schema": {"type": "string", "example": "pizza-bot"},
                        },
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "session_id": {
                                            "type": "string",
                                            "description": "Session ID from startChatSession",
                                        },
                                        "message": {
                                            "type": "string",
                                            "description": "The user's message text",
                                        },
                                        "visitor_id": {
                                            "type": "string",
                                            "description": "Optional visitor identifier",
                                        },
                                    },
                                    "required": ["session_id", "message"],
                                },
                            },
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Agent response",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "response": {
                                                "type": "string",
                                                "description": "The agent's reply",
                                            },
                                            "session_id": {
                                                "type": "string",
                                                "description": "Session identifier",
                                            },
                                        },
                                        "required": ["response", "session_id"],
                                    },
                                },
                            },
                        },
                        "400": {"description": "Missing session_id or message"},
                        "404": {"description": "Agent or session not found"},
                    },
                },
            },
            # -- Public: List agents -------------------------------------
            "/api/v1/public/agents": {
                "get": {
                    "operationId": "listAgents",
                    "summary": "List all public agents",
                    "description": (
                        "Returns a paginated list of all publicly available agents. "
                        "Use the industry parameter to filter by sector."
                    ),
                    "parameters": [
                        {
                            "name": "industry",
                            "in": "query",
                            "required": False,
                            "description": "Filter by industry type (e.g. restaurant, retail, healthcare)",
                            "schema": {"type": "string"},
                        },
                        {
                            "name": "limit",
                            "in": "query",
                            "required": False,
                            "description": "Max results to return (1-100, default 20)",
                            "schema": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
                        },
                        {
                            "name": "offset",
                            "in": "query",
                            "required": False,
                            "description": "Number of results to skip for pagination",
                            "schema": {"type": "integer", "default": 0, "minimum": 0},
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": "Agent list",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "agents": {
                                                "type": "array",
                                                "items": {"$ref": "#/components/schemas/PublicAgent"},
                                            },
                                            "total": {"type": "integer"},
                                            "limit": {"type": "integer"},
                                            "offset": {"type": "integer"},
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
            },
            # -- Public: Get agent profile -------------------------------
            "/api/v1/public/agents/{handle}": {
                "get": {
                    "operationId": "getAgentProfile",
                    "summary": "Get an agent's public profile",
                    "description": (
                        "Returns the full public profile for a single agent, "
                        "including capabilities, embed code, and chat URL."
                    ),
                    "parameters": [
                        {
                            "name": "handle",
                            "in": "path",
                            "required": True,
                            "description": "The agent's unique handle (without the @ prefix)",
                            "schema": {"type": "string", "example": "pizza-bot"},
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": "Agent profile",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/PublicAgent"},
                                },
                            },
                        },
                        "404": {"description": "Agent not found"},
                    },
                },
            },
            # -- Templates: List templates -------------------------------
            "/api/v1/templates": {
                "get": {
                    "operationId": "listTemplates",
                    "summary": "List all available agent templates",
                    "description": (
                        "Returns all agent templates that can be used to create new agents. "
                        "Optionally filter by agent_type (e.g. business, personal, creative)."
                    ),
                    "parameters": [
                        {
                            "name": "agent_type",
                            "in": "query",
                            "required": False,
                            "description": "Filter by agent type",
                            "schema": {"type": "string"},
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": "Template list",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "templates": {
                                                "type": "array",
                                                "items": {"$ref": "#/components/schemas/Template"},
                                            },
                                            "count": {"type": "integer"},
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
            },
            # -- Onboarding: List sectors --------------------------------
            "/api/v1/onboarding/sectors": {
                "get": {
                    "operationId": "listSectors",
                    "summary": "List all industries/sectors for agent creation",
                    "description": (
                        "Returns the available industry sectors with display metadata. "
                        "Used to show users what types of agents they can create."
                    ),
                    "responses": {
                        "200": {
                            "description": "Sectors list",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "sectors": {
                                                "type": "array",
                                                "items": {"$ref": "#/components/schemas/Sector"},
                                            },
                                            "count": {"type": "integer"},
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
        "components": {
            "schemas": {
                "PublicAgent": {
                    "type": "object",
                    "properties": {
                        "handle": {
                            "type": "string",
                            "description": "Unique agent handle",
                            "example": "pizza-bot",
                        },
                        "name": {
                            "type": "string",
                            "description": "Display name",
                            "example": "Pizza Palace Assistant",
                        },
                        "description": {
                            "type": "string",
                            "description": "Agent description",
                        },
                        "industry": {
                            "type": "string",
                            "description": "Industry type (e.g. restaurant, retail)",
                        },
                        "agent_type": {
                            "type": "string",
                            "description": "Agent category",
                            "enum": ["personal", "business", "creative", "developer", "education", "health", "finance", "gaming"],
                        },
                        "avatar_url": {
                            "type": "string",
                            "description": "URL to the agent's avatar image",
                        },
                        "primary_color": {
                            "type": "string",
                            "description": "Brand color hex code",
                            "example": "#7C3AED",
                        },
                        "greeting": {
                            "type": "string",
                            "description": "Agent's greeting message",
                        },
                        "created_at": {
                            "type": "string",
                            "description": "ISO 8601 creation timestamp",
                        },
                    },
                },
                "Template": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Template identifier",
                        },
                        "name": {
                            "type": "string",
                            "description": "Template name",
                        },
                        "agent_type": {
                            "type": "string",
                            "description": "Agent type this template creates",
                        },
                        "industry_type": {
                            "type": "string",
                            "description": "Industry this template is designed for",
                        },
                        "capabilities": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of capabilities this template provides",
                        },
                        "icon": {
                            "type": "string",
                            "description": "Emoji icon for the template",
                        },
                    },
                },
                "Sector": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Sector identifier",
                        },
                        "name": {
                            "type": "string",
                            "description": "Display name",
                        },
                        "agent_type": {
                            "type": "string",
                            "description": "Corresponding agent type",
                        },
                        "icon": {
                            "type": "string",
                            "description": "Emoji icon",
                        },
                        "description": {
                            "type": "string",
                            "description": "Sector description",
                        },
                        "popular": {
                            "type": "boolean",
                            "description": "Whether this is a popular/featured sector",
                        },
                    },
                },
            },
        },
    }


@router.get(
    "/api/v1/openapi-gpt.json",
    summary="GPT Actions OpenAPI spec",
    response_class=JSONResponse,
    include_in_schema=False,
)
async def gpt_openapi_spec() -> JSONResponse:
    """Serve a filtered OpenAPI spec for GPT Custom Actions.

    Returns a minimal OpenAPI 3.1.0 document containing only the 6
    public endpoints suitable for GPT integration.  This spec can be
    pasted directly into ChatGPT's "Actions" configuration.

    The endpoint itself is excluded from the auto-generated FastAPI
    OpenAPI spec (``include_in_schema=False``) to avoid recursion.
    """
    return JSONResponse(
        content=_build_gpt_openapi_spec(),
        media_type="application/json",
        headers={
            "Cache-Control": "public, max-age=3600",
            "Access-Control-Allow-Origin": "*",
        },
    )
