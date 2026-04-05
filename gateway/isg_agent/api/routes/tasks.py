"""Task management and usage tracking endpoints.

Provides the HTTP API for creating, listing, retrieving, updating, and
cancelling agent tasks; and for querying per-agent usage stats.

Endpoints:
    POST   /api/v1/tasks/                        — create task
    GET    /api/v1/tasks/                        — list tasks
    GET    /api/v1/tasks/{task_id}               — get task detail
    PATCH  /api/v1/tasks/{task_id}               — update task
    DELETE /api/v1/tasks/{task_id}               — cancel task
    GET    /api/v1/tasks/usage/{agent_id}        — current period usage
    GET    /api/v1/tasks/usage/{agent_id}/history — usage history

All endpoints require authentication via JWT Bearer token.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from isg_agent.api.deps import CurrentUser, require_auth
from isg_agent.personal.life_services import LifeServices
from isg_agent.personal.task_manager import TaskManager
from isg_agent.schemas.tasks import (
    TaskCreate,
    TaskList,
    TaskResponse,
    TaskUpdate,
    TierLimitResponse,
    UsageHistory,
    UsageResponse,
)

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


# ---------------------------------------------------------------------------
# Helpers: extract services from app state
# ---------------------------------------------------------------------------


def _get_task_manager(request: Request) -> TaskManager:
    """Extract TaskManager from FastAPI app state.

    Raises 503 if not yet initialised.
    """
    mgr: Optional[TaskManager] = getattr(request.app.state, "task_manager", None)
    if mgr is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Task manager not initialised. Server is starting up.",
        )
    return mgr


def _get_life_services(request: Request) -> LifeServices:
    """Extract LifeServices from FastAPI app state.

    Raises 503 if not yet initialised.
    """
    svc: Optional[LifeServices] = getattr(request.app.state, "life_services", None)
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Life services not initialised. Server is starting up.",
        )
    return svc


def _task_to_response(row: dict) -> TaskResponse:  # type: ignore[type-arg]
    """Convert a raw task DB row dict to a TaskResponse DTO."""
    return TaskResponse(
        id=row["id"],
        agent_id=row["agent_id"],
        user_id=row["user_id"],
        task_type=row["task_type"],
        description=row["description"],
        status=row["status"],
        delegated_to=row.get("delegated_to"),
        result_json=row.get("result_json"),
        tokens_used=row.get("tokens_used", 0),
        cost_cents=row.get("cost_cents", 0),
        created_at=row["created_at"],
        completed_at=row.get("completed_at"),
    )


def _usage_to_response(row: dict) -> UsageResponse:  # type: ignore[type-arg]
    """Convert a raw usage_tracking DB row dict to a UsageResponse DTO."""
    return UsageResponse(
        id=row["id"],
        agent_id=row["agent_id"],
        period=row["period"],
        llm_tokens=row.get("llm_tokens", 0),
        api_calls=row.get("api_calls", 0),
        tasks_completed=row.get("tasks_completed", 0),
        transactions=row.get("transactions", 0),
        cost_cents=row.get("cost_cents", 0),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _current_period() -> str:
    """Return the current month as a YYYY-MM string."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


# ---------------------------------------------------------------------------
# Task CRUD endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new agent task",
)
async def create_task(
    body: TaskCreate,
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> TaskResponse:
    """Create a new task for the authenticated user's agent.

    The ``agent_id`` in the request body is optional.  If omitted, the
    ``user_id`` from the JWT is used as a fallback agent identifier.

    Returns 422 if the task_type is not a recognised value.
    """
    mgr = _get_task_manager(request)

    agent_id = body.agent_id or user.user_id

    try:
        task_id = await mgr.create_task(
            agent_id=agent_id,
            user_id=user.user_id,
            task_type=body.task_type,
            description=body.description,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    task = await mgr.get_task(task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Task was created but could not be retrieved.",
        )

    logger.info(
        "Task created: id=%s agent=%s type=%s user=%s",
        task_id,
        agent_id,
        body.task_type,
        user.user_id,
    )

    # Fire Zapier webhook for new task
    try:
        from isg_agent.api.routes.zapier_webhooks import dispatch_webhook_event
        db_path = str(request.app.state.db_path) if hasattr(request.app.state, "db_path") else ""
        await dispatch_webhook_event(db_path, "new_task", task, agent_id=agent_id)
    except Exception:
        logger.debug("Zapier webhook dispatch skipped (non-fatal)")

    return _task_to_response(task)


@router.get(
    "",
    response_model=TaskList,
    summary="List tasks for the authenticated user's agent",
)
async def list_tasks(
    request: Request,
    agent_id: Optional[str] = None,
    task_status: Optional[str] = None,
    user: CurrentUser = Depends(require_auth),
) -> TaskList:
    """Return tasks belonging to the agent.

    If ``agent_id`` is not provided, tasks for the authenticated user
    (user_id used as agent_id fallback) are returned.

    Optional ``task_status`` filter: pending | in_progress | completed | failed | cancelled.
    """
    mgr = _get_task_manager(request)

    effective_agent_id = agent_id or user.user_id

    try:
        tasks = await mgr.list_tasks(
            agent_id=effective_agent_id,
            status=task_status,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    items = [_task_to_response(t) for t in tasks]
    return TaskList(tasks=items, count=len(items))


@router.get(
    "/{task_id}",
    response_model=TaskResponse,
    summary="Get a task by ID",
)
async def get_task(
    task_id: str,
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> TaskResponse:
    """Retrieve a single task by its UUID.

    Returns 404 if the task does not exist or belongs to another user.
    """
    mgr = _get_task_manager(request)

    task = await mgr.get_task(task_id)
    if task is None or task["user_id"] != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task not found: {task_id}",
        )

    return _task_to_response(task)


@router.patch(
    "/{task_id}",
    response_model=TaskResponse,
    summary="Update a task",
)
async def update_task(
    task_id: str,
    body: TaskUpdate,
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> TaskResponse:
    """Update mutable fields on a task.

    Only the authenticated owner can update their task.
    Returns 404 if the task does not exist or belongs to another user.
    Returns 400 if no updatable fields are provided.
    """
    mgr = _get_task_manager(request)

    # Verify ownership
    task = await mgr.get_task(task_id)
    if task is None or task["user_id"] != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task not found: {task_id}",
        )

    # Build update kwargs from non-None fields
    updates: dict[str, object] = {}
    if body.status is not None:
        updates["status"] = body.status
    if body.result_json is not None:
        updates["result_json"] = body.result_json
    if body.delegated_to is not None:
        updates["delegated_to"] = body.delegated_to
    if body.tokens_used is not None:
        updates["tokens_used"] = body.tokens_used
    if body.cost_cents is not None:
        updates["cost_cents"] = body.cost_cents

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No updatable fields provided.",
        )

    try:
        updated = await mgr.update_task(task_id, **updates)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task not found: {task_id}",
        )

    refreshed = await mgr.get_task(task_id)
    if refreshed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task not found after update: {task_id}",
        )

    logger.info(
        "Task updated: id=%s user=%s fields=%s",
        task_id,
        user.user_id,
        list(updates.keys()),
    )

    # Fire Zapier webhook for task completion
    if body.status == "completed" and refreshed:
        try:
            from isg_agent.api.routes.zapier_webhooks import dispatch_webhook_event
            db_path = str(request.app.state.db_path) if hasattr(request.app.state, "db_path") else ""
            await dispatch_webhook_event(db_path, "task_completed", dict(refreshed), agent_id=refreshed.get("agent_id"))
        except Exception:
            logger.debug("Zapier webhook dispatch skipped (non-fatal)")
    return _task_to_response(refreshed)


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Cancel a task",
)
async def cancel_task(
    task_id: str,
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> Response:
    """Cancel a task by setting its status to ``"cancelled"``.

    Only the authenticated owner can cancel their task.
    Returns 404 if the task does not exist or belongs to another user.
    """
    mgr = _get_task_manager(request)

    # Verify ownership
    task = await mgr.get_task(task_id)
    if task is None or task["user_id"] != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task not found: {task_id}",
        )

    cancelled = await mgr.cancel_task(task_id)
    if not cancelled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task not found: {task_id}",
        )

    logger.info("Task cancelled: id=%s user=%s", task_id, user.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Usage endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/usage/{agent_id}",
    response_model=UsageResponse,
    summary="Get current period usage for an agent",
)
async def get_current_usage(
    agent_id: str,
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> UsageResponse:
    """Return usage data for the current month.

    If no usage has been recorded yet this period, returns a zeroed-out
    usage record (not 404) for a consistent client experience.
    """
    svc = _get_life_services(request)
    period = _current_period()

    usage = await svc.get_usage(agent_id, period)
    if usage is None:
        # Return a synthetic zeroed record so clients always get a response
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        return UsageResponse(
            id="",
            agent_id=agent_id,
            period=period,
            llm_tokens=0,
            api_calls=0,
            tasks_completed=0,
            transactions=0,
            cost_cents=0,
            created_at=now_iso,
            updated_at=now_iso,
        )

    return _usage_to_response(usage)


@router.get(
    "/usage/{agent_id}/history",
    response_model=UsageHistory,
    summary="Get usage history for an agent",
)
async def get_usage_history(
    agent_id: str,
    request: Request,
    limit: int = 12,
    user: CurrentUser = Depends(require_auth),
) -> UsageHistory:
    """Return usage history for an agent, most recent periods first.

    ``limit`` defaults to 12 (1 year of monthly data).
    """
    svc = _get_life_services(request)

    if limit < 1 or limit > 120:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="limit must be between 1 and 120.",
        )

    periods = await svc.get_usage_history(agent_id, limit=limit)
    items = [_usage_to_response(p) for p in periods]
    return UsageHistory(agent_id=agent_id, periods=items, count=len(items))
