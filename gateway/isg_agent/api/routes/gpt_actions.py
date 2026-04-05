"""GPT Actions endpoints for OpenAI Custom GPT integration.

Provides a simplified REST API namespace at /api/v1/gpt/ designed for
ChatGPT Custom GPT Actions. These endpoints are self-contained, use
simple request/response schemas, and include the OpenAPI spec endpoint.

Endpoints:
    GET  /api/v1/gpt/openapi.yaml     — OpenAPI 3.0 spec for GPT Actions
    GET  /api/v1/gpt/agents           — List public agents
    GET  /api/v1/gpt/agents/{handle}  — Get agent details by handle
    POST /api/v1/gpt/agents/{handle}/chat — Send a message to an agent
    POST /api/v1/gpt/agents/{handle}/skills/{skill}/execute — Execute a skill
    GET  /api/v1/gpt/templates        — List available agent templates

All endpoints are PUBLIC (no JWT) — GPT Actions use server-to-server
API key auth via the X-API-Key header. Authentication is optional for
read-only endpoints (agents, templates) and required for write operations.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Header, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/gpt", tags=["gpt-actions"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class AgentSummary(BaseModel):
    """Public agent summary for discovery."""
    handle: str
    name: str
    agent_type: str
    industry_type: Optional[str] = None
    description: Optional[str] = None
    skills: List[str] = Field(default_factory=list)


class AgentListResponse(BaseModel):
    """Response for agent listing."""
    agents: List[AgentSummary]
    total: int


class ChatRequest(BaseModel):
    """Chat message request."""
    message: str = Field(..., description="The user message to send to the agent")
    session_id: Optional[str] = Field(
        None, description="Existing session ID for conversation continuity"
    )


class ChatResponse(BaseModel):
    """Chat message response."""
    reply: str
    session_id: str
    agent_handle: str


class SkillExecuteRequest(BaseModel):
    """Skill execution request."""
    action: str = Field(..., description="The action to perform (e.g. schedule, list, create)")
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Action-specific parameters"
    )


class SkillExecuteResponse(BaseModel):
    """Skill execution response."""
    success: bool
    data: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class TemplateSummary(BaseModel):
    """Agent template summary."""
    template_id: str
    name: str
    agent_type: str
    industry_type: Optional[str] = None
    description: Optional[str] = None
    skills: List[str] = Field(default_factory=list)


class TemplateListResponse(BaseModel):
    """Response for template listing."""
    templates: List[TemplateSummary]
    total: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_registry(request: Request):
    """Get agent registry from app state."""
    registry = getattr(request.app.state, "agent_registry", None)
    if registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent registry not initialized",
        )
    return registry


async def _get_executor(request: Request):
    """Get skill executor from app state."""
    executor = getattr(request.app.state, "skill_executor", None)
    if executor is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Skill executor not initialized",
        )
    return executor


async def _validate_api_key(
    request: Request,
    x_api_key: Optional[str] = None,
) -> Optional[dict]:
    """Validate API key if provided. Returns key info or None."""
    if not x_api_key:
        return None
    try:
        from isg_agent.mcp.auth import validate_api_key
        settings = getattr(request.app.state, "settings", None)
        db_path = settings.db_path if settings else "isg_agent.db"
        return await validate_api_key(x_api_key, db_path=db_path)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# OpenAPI spec for GPT Actions
# ---------------------------------------------------------------------------


_OPENAPI_SPEC = """openapi: "3.0.0"
info:
  title: DingDawg Agent 1 API
  description: |
    DingDawg Agent 1 API for Custom GPT Actions. Interact with AI business
    agents that handle appointments, invoicing, contacts, and 10+ other
    business skills. Each agent has a unique @handle (e.g. @joes-pizza).
  version: "1.0.0"
servers:
  - url: https://app.dingdawg.com
    description: Production
  - url: http://localhost:8000
    description: Local development
paths:
  /api/v1/gpt/agents:
    get:
      operationId: listAgents
      summary: List all public business agents
      description: Returns a list of all active public agents with their handles, types, and available skills.
      responses:
        "200":
          description: List of agents
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/AgentListResponse"
  /api/v1/gpt/agents/{handle}:
    get:
      operationId: getAgent
      summary: Get agent details by handle
      description: Get detailed information about a specific agent including its skills and configuration.
      parameters:
        - name: handle
          in: path
          required: true
          schema:
            type: string
          description: Agent handle without @ prefix (e.g. joes-pizza)
      responses:
        "200":
          description: Agent details
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/AgentSummary"
        "404":
          description: Agent not found
  /api/v1/gpt/agents/{handle}/chat:
    post:
      operationId: chatWithAgent
      summary: Send a message to an agent
      description: Send a chat message to a specific agent and receive a response. Optionally include a session_id for conversation continuity.
      parameters:
        - name: handle
          in: path
          required: true
          schema:
            type: string
          description: Agent handle without @ prefix
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/ChatRequest"
      responses:
        "200":
          description: Agent response
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/ChatResponse"
      security:
        - apiKey: []
  /api/v1/gpt/agents/{handle}/skills/{skill_name}/execute:
    post:
      operationId: executeSkill
      summary: Execute a business skill on an agent
      description: |
        Execute a specific business skill (e.g. appointments, invoicing, contacts)
        on the specified agent. Each skill supports multiple actions.

        Available skills and their actions:
        - appointments: schedule, cancel, reschedule, complete, list, get
        - invoicing: create, send, mark_paid, void, list, get
        - contacts: add, update, search, get, delete, list
        - notifications: send, list, cancel, get
        - inventory: add_product, update_stock, list, get, low_stock
        - expenses: record, list, get, categorize, report
        - business-ops: create_task, list_tasks, update_task, dashboard
        - webhooks: register, trigger, list, update
        - forms: create, list, get, submit, results
        - customer-engagement: add_points, get_loyalty, create_campaign
        - review-manager: request, list, get, respond
        - referral-program: create_campaign, generate_code, redeem
        - data-store: set, get, delete, list
      parameters:
        - name: handle
          in: path
          required: true
          schema:
            type: string
          description: Agent handle without @ prefix
        - name: skill_name
          in: path
          required: true
          schema:
            type: string
          description: Skill name (e.g. appointments, invoicing, contacts)
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/SkillExecuteRequest"
      responses:
        "200":
          description: Skill execution result
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/SkillExecuteResponse"
      security:
        - apiKey: []
  /api/v1/gpt/templates:
    get:
      operationId: listTemplates
      summary: List available agent templates
      description: Returns all available templates that can be used to create new agents with pre-configured skills.
      responses:
        "200":
          description: List of templates
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/TemplateListResponse"
components:
  schemas:
    AgentSummary:
      type: object
      properties:
        handle:
          type: string
          description: Agent handle (e.g. joes-pizza)
        name:
          type: string
          description: Display name
        agent_type:
          type: string
          description: Agent type (business, personal, etc.)
        industry_type:
          type: string
          nullable: true
          description: Industry category
        description:
          type: string
          nullable: true
        skills:
          type: array
          items:
            type: string
          description: List of available skill names
    AgentListResponse:
      type: object
      properties:
        agents:
          type: array
          items:
            $ref: "#/components/schemas/AgentSummary"
        total:
          type: integer
    ChatRequest:
      type: object
      required:
        - message
      properties:
        message:
          type: string
          description: The message to send to the agent
        session_id:
          type: string
          nullable: true
          description: Session ID for conversation continuity
    ChatResponse:
      type: object
      properties:
        reply:
          type: string
          description: The agent's response
        session_id:
          type: string
        agent_handle:
          type: string
    SkillExecuteRequest:
      type: object
      required:
        - action
      properties:
        action:
          type: string
          description: "Action to perform (e.g. schedule, list, create)"
        parameters:
          type: object
          description: Action-specific parameters
          additionalProperties: true
    SkillExecuteResponse:
      type: object
      properties:
        success:
          type: boolean
        data:
          type: object
          additionalProperties: true
        error:
          type: string
          nullable: true
    TemplateSummary:
      type: object
      properties:
        template_id:
          type: string
        name:
          type: string
        agent_type:
          type: string
        industry_type:
          type: string
          nullable: true
        description:
          type: string
          nullable: true
        skills:
          type: array
          items:
            type: string
    TemplateListResponse:
      type: object
      properties:
        templates:
          type: array
          items:
            $ref: "#/components/schemas/TemplateSummary"
        total:
          type: integer
  securitySchemes:
    apiKey:
      type: apiKey
      in: header
      name: X-API-Key
      description: DingDawg MCP API key for authenticated operations
"""


@router.get(
    "/openapi.yaml",
    response_class=Response,
    summary="OpenAPI 3.0 spec for GPT Actions configuration",
)
async def get_openapi_spec():
    """Return the OpenAPI 3.0 YAML spec for configuring GPT Actions.

    Copy this spec into the Custom GPT Actions configuration in ChatGPT
    to enable GPT-powered interaction with DingDawg business agents.
    """
    return Response(
        content=_OPENAPI_SPEC,
        media_type="text/yaml",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/agents",
    response_model=AgentListResponse,
    summary="List all public business agents",
)
async def list_agents(request: Request) -> AgentListResponse:
    """List all active public agents for discovery by GPT."""
    registry = await _get_registry(request)

    try:
        agents, total = await registry.list_public_agents(limit=100, offset=0)
    except Exception:
        # Fallback: list_public_agents may not exist on all registry versions
        try:
            agents = await registry.list_agents(user_id=None)
            total = len(agents)
        except Exception as exc:
            logger.error("Failed to list agents: %s", exc)
            return AgentListResponse(agents=[], total=0)

    summaries = []
    for a in agents:
        config = {}
        try:
            raw = getattr(a, "config_json", "{}")
            config = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except Exception:
            pass

        summaries.append(AgentSummary(
            handle=a.handle,
            name=a.name,
            agent_type=a.agent_type.value if hasattr(a.agent_type, "value") else str(a.agent_type),
            industry_type=getattr(a, "industry_type", None),
            description=config.get("description"),
            skills=config.get("skills", []),
        ))

    return AgentListResponse(agents=summaries, total=total)


@router.get(
    "/agents/{handle}",
    response_model=AgentSummary,
    summary="Get agent details by handle",
)
async def get_agent(handle: str, request: Request) -> AgentSummary:
    """Get detailed information about a specific agent."""
    registry = await _get_registry(request)
    agent = await registry.get_agent_by_handle(handle)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent @{handle} not found")

    config = {}
    try:
        raw = getattr(agent, "config_json", "{}")
        config = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception:
        pass

    # Get registered skills from executor
    skills = config.get("skills", [])
    if not skills:
        executor = getattr(request.app.state, "skill_executor", None)
        if executor:
            try:
                skills = await executor.list_skills()
            except Exception:
                pass

    return AgentSummary(
        handle=agent.handle,
        name=agent.name,
        agent_type=agent.agent_type.value if hasattr(agent.agent_type, "value") else str(agent.agent_type),
        industry_type=getattr(agent, "industry_type", None),
        description=config.get("description"),
        skills=skills,
    )


@router.post(
    "/agents/{handle}/chat",
    response_model=ChatResponse,
    summary="Send a message to an agent",
)
async def chat_with_agent(
    handle: str,
    body: ChatRequest,
    request: Request,
    x_api_key: Optional[str] = Header(None),
) -> ChatResponse:
    """Send a chat message to a specific agent and get a response.

    Requires X-API-Key header for authentication. Creates a new session
    if session_id is not provided.
    """
    # API key validation for write operations
    key_info = await _validate_api_key(request, x_api_key)
    if not key_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid X-API-Key header required for chat operations",
        )

    registry = await _get_registry(request)
    agent = await registry.get_agent_by_handle(handle)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent @{handle} not found")

    # Get or create session
    session_mgr = getattr(request.app.state, "session_manager", None)
    runtime = getattr(request.app.state, "runtime", None)

    session_id = body.session_id or str(uuid.uuid4())

    if runtime:
        try:
            # Create session if new
            if not body.session_id and session_mgr:
                session = await session_mgr.create_session(
                    user_id=f"gpt:{key_info['user_id']}",
                    agent_id=agent.id,
                )
                session_id = session.session_id

            # Process message through AgentRuntime
            response = await runtime.process_message(
                session_id=session_id,
                user_message=body.message,
                user_id=f"gpt:{key_info['user_id']}",
            )
            reply = response.content if hasattr(response, "content") else str(response)
        except Exception as exc:
            logger.error("Chat processing failed: %s", exc)
            reply = f"I encountered an error processing your message. Please try again."
    else:
        reply = (
            f"Agent @{handle} is available but the runtime is not initialized. "
            f"Your message: {body.message}"
        )

    return ChatResponse(
        reply=reply,
        session_id=session_id,
        agent_handle=handle,
    )


@router.post(
    "/agents/{handle}/skills/{skill_name}/execute",
    response_model=SkillExecuteResponse,
    summary="Execute a business skill on an agent",
)
async def execute_skill(
    handle: str,
    skill_name: str,
    body: SkillExecuteRequest,
    request: Request,
    x_api_key: Optional[str] = Header(None),
) -> SkillExecuteResponse:
    """Execute a specific business skill on the given agent.

    Requires X-API-Key header for authentication.
    """
    key_info = await _validate_api_key(request, x_api_key)
    if not key_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid X-API-Key header required for skill execution",
        )

    registry = await _get_registry(request)
    agent = await registry.get_agent_by_handle(handle)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent @{handle} not found")

    executor = await _get_executor(request)

    # Build parameters
    params = {
        **body.parameters,
        "action": body.action,
        "agent_id": agent.id,
        "user_id": f"gpt:{key_info['user_id']}",
    }

    try:
        result = await executor.execute(skill_name=skill_name, parameters=params)
    except Exception as exc:
        logger.error("Skill execution failed: %s", exc)
        return SkillExecuteResponse(
            success=False,
            error=f"Execution error: {type(exc).__name__}: {exc}",
        )

    output = {}
    if result.output:
        try:
            output = json.loads(result.output)
        except (json.JSONDecodeError, TypeError):
            output = {"raw": result.output}

    return SkillExecuteResponse(
        success=result.success,
        data=output,
        error=result.error,
    )


@router.get(
    "/templates",
    response_model=TemplateListResponse,
    summary="List available agent templates",
)
async def list_templates(request: Request) -> TemplateListResponse:
    """List all available agent templates for creating new agents."""
    template_registry = getattr(request.app.state, "template_registry", None)

    if template_registry is None:
        return TemplateListResponse(templates=[], total=0)

    try:
        templates = await template_registry.list_templates()
    except Exception as exc:
        logger.error("Failed to list templates: %s", exc)
        return TemplateListResponse(templates=[], total=0)

    summaries = [
        TemplateSummary(
            template_id=t.get("id") or t.get("template_id", ""),
            name=t.get("name", ""),
            agent_type=t.get("agent_type", ""),
            industry_type=t.get("industry_type"),
            description=t.get("description"),
            skills=t.get("skills", []),
        )
        for t in templates
    ]

    return TemplateListResponse(templates=summaries, total=len(summaries))
