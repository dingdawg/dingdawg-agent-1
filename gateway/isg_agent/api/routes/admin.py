"""Command Center admin API — platform-owner only endpoints.

All endpoints require the ``require_admin`` dependency which validates that
the authenticated user's email matches the ``ISG_AGENT_ADMIN_EMAIL``
environment variable.  Non-admin users receive HTTP 403.

Endpoints
---------
GET  /admin/whoami                — identity check
GET  /admin/platform-stats        — aggregate platform metrics
GET  /admin/agents                — cross-user agent list (paginated)
GET  /admin/errors                — aggregated error log from audit chain
GET  /admin/health-detailed       — uptime, DB size, memory usage
GET  /admin/integration-health    — per-integration connection status
GET  /admin/stripe-status         — Stripe mode + webhook status
GET  /admin/contacts              — cross-agent contacts
GET  /admin/funnel                — conversion funnel metrics
GET  /admin/campaigns             — campaign list (stub — initially empty)
GET  /admin/email-stats           — SendGrid delivery stats
GET  /admin/workflow-tests        — workflow test definitions + last results
POST /admin/workflow-tests/{id}/run — trigger a workflow test
GET  /admin/alerts                — alert feed
POST /admin/alerts/configure      — configure alert thresholds
GET  /admin/events                — calendar events
POST /admin/command               — MiLA admin command dispatcher (self-healing)
POST /admin/deploy-marketing-agent — deploy @dingdawg-marketing agent
GET  /admin/priorities            — ranked list of what needs attention right now
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import aiosqlite
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status

from isg_agent.api.deps import CurrentUser, require_admin
from isg_agent.config import Settings, get_settings

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

# SECURITY NOTE: Per-endpoint rate limiting for admin routes is deferred.
# Currently relying on middleware-level GranularRateLimiter.
# A stolen admin token can hit POST /admin/command in a tight loop.
# Priority: P2 — add @limiter.limit() decorators per endpoint.

# ---------------------------------------------------------------------------
# In-memory alert thresholds (reset on server restart — acceptable for v1)
# ---------------------------------------------------------------------------

_alert_thresholds: dict[str, Any] = {
    "error_rate_per_hour": 100,
    "failed_payment_count": 10,
    "security_event_count": 5,
}

# ---------------------------------------------------------------------------
# In-memory workflow test results store
# ---------------------------------------------------------------------------

_workflow_results: dict[str, dict[str, Any]] = {}

# ---------------------------------------------------------------------------
# In-memory acknowledged alert IDs (keyed by alert_id string)
# Resets on server restart — acceptable for v1 (alerts live in audit_chain).
# ---------------------------------------------------------------------------

_acknowledged_alerts: dict[str, str] = {}  # alert_id -> acknowledged_at ISO string

# ---------------------------------------------------------------------------
# Built-in workflow test definitions
# ---------------------------------------------------------------------------

_WORKFLOW_TESTS = [
    {
        "id": "health_check",
        "name": "Health Check",
        "description": "Hits the /health endpoint and verifies 200 OK response.",
        "category": "infrastructure",
    },
    {
        "id": "auth_flow",
        "name": "Auth Flow",
        "description": "Tests register → login → token round-trip.",
        "category": "auth",
    },
    {
        "id": "agent_create",
        "name": "Agent Creation Flow",
        "description": "Tests agent creation and handle claiming flow.",
        "category": "agents",
    },
    {
        "id": "stripe_webhook",
        "name": "Stripe Webhook Validation",
        "description": "Tests Stripe webhook signature validation logic.",
        "category": "payments",
    },
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """Return current UTC time as ISO-8601 string (no tzinfo — PP-109)."""
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _db_path(request: Request) -> str:
    """Extract db_path from app.state.settings or get_settings fallback."""
    settings: Optional[Settings] = getattr(
        getattr(request, "app", None) and request.app.state, "settings", None
    )
    if settings is None:
        settings = get_settings()
    return settings.db_path


def _settings(request: Request) -> Settings:
    """Extract Settings from app.state or get_settings fallback."""
    _s: Optional[Settings] = getattr(
        getattr(request, "app", None) and request.app.state, "settings", None
    )
    if _s is None:
        _s = get_settings()
    return _s


# ---------------------------------------------------------------------------
# GET /admin/whoami
# ---------------------------------------------------------------------------


@router.get("/whoami")
async def whoami(
    admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """Return admin identity confirmation."""
    return {
        "is_admin": True,
        "email": admin.email,
        "user_id": admin.user_id,
    }


# ---------------------------------------------------------------------------
# GET /admin/platform-stats
# ---------------------------------------------------------------------------


@router.get("/platform-stats")
async def platform_stats(
    request: Request,
    admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """Return aggregate platform metrics.

    Queries: users, agents, sessions (active 24h), audit_chain (errors 24h),
    memory_messages (total messages).
    """
    db = _db_path(request)
    cutoff = _now_iso()
    # ISO string 24h ago
    from datetime import timedelta

    cutoff_24h = (
        datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
    ).isoformat()

    stats: dict[str, Any] = {
        "total_users": 0,
        "total_agents": 0,
        "active_sessions_24h": 0,
        "error_count_24h": 0,
        "total_messages": 0,
    }

    try:
        async with aiosqlite.connect(db) as conn:
            # total_users
            row = await conn.execute_fetchall("SELECT COUNT(*) FROM users")
            if row:
                stats["total_users"] = row[0][0] or 0
    except Exception as exc:
        logger.error("admin platform_stats users query failed: %s", exc)

    try:
        async with aiosqlite.connect(db) as conn:
            row = await conn.execute_fetchall("SELECT COUNT(*) FROM agents")
            if row:
                stats["total_agents"] = row[0][0] or 0
    except Exception as exc:
        logger.error("admin platform_stats agents query failed: %s", exc)

    try:
        async with aiosqlite.connect(db) as conn:
            row = await conn.execute_fetchall(
                "SELECT COUNT(*) FROM agent_sessions WHERE updated_at >= ?",
                (cutoff_24h,),
            )
            if row:
                stats["active_sessions_24h"] = row[0][0] or 0
    except Exception as exc:
        logger.error("admin platform_stats sessions query failed: %s", exc)

    try:
        async with aiosqlite.connect(db) as conn:
            row = await conn.execute_fetchall(
                "SELECT COUNT(*) FROM audit_chain WHERE event_type = 'error' AND timestamp >= ?",
                (cutoff_24h,),
            )
            if row:
                stats["error_count_24h"] = row[0][0] or 0
    except Exception as exc:
        logger.error("admin platform_stats errors query failed: %s", exc)

    try:
        async with aiosqlite.connect(db) as conn:
            row = await conn.execute_fetchall("SELECT COUNT(*) FROM memory_messages")
            if row:
                stats["total_messages"] = row[0][0] or 0
    except Exception as exc:
        logger.error("admin platform_stats messages query failed: %s", exc)

    return stats


# ---------------------------------------------------------------------------
# GET /admin/agents
# ---------------------------------------------------------------------------


@router.get("/agents")
async def list_all_agents(
    request: Request,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    search: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None, alias="status"),
    admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """Return paginated list of ALL agents across all users.

    Joins agents with users to surface owner email, template name,
    last active timestamp, and message count.
    """
    db = _db_path(request)
    offset = (page - 1) * per_page

    where_clauses: list[str] = []
    params: list[Any] = []

    if search:
        where_clauses.append("(a.handle LIKE ? OR a.name LIKE ? OR u.email LIKE ?)")
        pattern = f"%{search}%"
        params.extend([pattern, pattern, pattern])

    if status:
        where_clauses.append("a.status = ?")
        params.append(status)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    agents: list[dict[str, Any]] = []
    total = 0

    try:
        async with aiosqlite.connect(db) as conn:
            count_row = await conn.execute_fetchall(
                f"""
                SELECT COUNT(*)
                FROM agents a
                LEFT JOIN users u ON a.user_id = u.id
                {where_sql}
                """,
                params,
            )
            if count_row:
                total = count_row[0][0] or 0

            rows = await conn.execute_fetchall(
                f"""
                SELECT a.id, a.handle, a.name, a.agent_type, a.status,
                       a.created_at, u.email AS owner_email,
                       at.name AS template_name
                FROM agents a
                LEFT JOIN users u ON a.user_id = u.id
                LEFT JOIN agent_templates at ON a.template_id = at.id
                {where_sql}
                ORDER BY a.created_at DESC
                LIMIT ? OFFSET ?
                """,
                [*params, per_page, offset],
            )
            for row in rows:
                agent_id = row[0]

                # last_active: MAX(created_at) from sessions for this agent
                last_active: Optional[str] = None
                try:
                    la_rows = await conn.execute_fetchall(
                        "SELECT MAX(created_at) FROM sessions WHERE agent_id = ?",
                        (agent_id,),
                    )
                    if la_rows and la_rows[0][0]:
                        last_active = la_rows[0][0]
                except Exception:
                    pass

                # message_count: COUNT from messages for this agent
                message_count = 0
                try:
                    mc_rows = await conn.execute_fetchall(
                        "SELECT COUNT(*) FROM messages WHERE agent_id = ?",
                        (agent_id,),
                    )
                    if mc_rows:
                        message_count = mc_rows[0][0] or 0
                except Exception:
                    pass

                agents.append({
                    "id": agent_id,
                    "handle": row[1],
                    "name": row[2],
                    "agent_type": row[3],
                    "status": row[4],
                    "created_at": row[5],
                    "owner_email": row[6] or "unknown",
                    "template_name": row[7],
                    "last_active": last_active,
                    "message_count": message_count,
                })
    except Exception as exc:
        logger.error("admin list_all_agents query failed: %s", exc)
        return {"agents": [], "total": 0, "page": page, "per_page": per_page}

    return {
        "agents": agents,
        "total": total,
        "page": page,
        "per_page": per_page,
    }


# ---------------------------------------------------------------------------
# POST /admin/agents/{agent_id}/suspend
# ---------------------------------------------------------------------------


@router.post("/agents/{agent_id}/suspend")
async def suspend_agent(
    agent_id: str,
    request: Request,
    admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """Suspend an agent by setting its status to 'suspended'."""
    db = _db_path(request)
    try:
        async with aiosqlite.connect(db) as conn:
            existing = await conn.execute_fetchall(
                "SELECT id FROM agents WHERE id = ?", (agent_id,)
            )
            if not existing:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Agent '{agent_id}' not found.",
                )
            await conn.execute(
                "UPDATE agents SET status = 'suspended', updated_at = ? WHERE id = ?",
                (_now_iso(), agent_id),
            )
            await conn.commit()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("admin suspend_agent failed for %s: %s", agent_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database error while suspending agent.",
        ) from exc

    return {"id": agent_id, "status": "suspended", "message": "Agent suspended"}


# ---------------------------------------------------------------------------
# POST /admin/agents/{agent_id}/activate
# ---------------------------------------------------------------------------


@router.post("/agents/{agent_id}/activate")
async def activate_agent(
    agent_id: str,
    request: Request,
    admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """Activate an agent by setting its status to 'active'."""
    db = _db_path(request)
    try:
        async with aiosqlite.connect(db) as conn:
            existing = await conn.execute_fetchall(
                "SELECT id FROM agents WHERE id = ?", (agent_id,)
            )
            if not existing:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Agent '{agent_id}' not found.",
                )
            await conn.execute(
                "UPDATE agents SET status = 'active', updated_at = ? WHERE id = ?",
                (_now_iso(), agent_id),
            )
            await conn.commit()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("admin activate_agent failed for %s: %s", agent_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database error while activating agent.",
        ) from exc

    return {"id": agent_id, "status": "active", "message": "Agent activated"}


# ---------------------------------------------------------------------------
# DELETE /admin/agents/{agent_id}
# ---------------------------------------------------------------------------


@router.delete("/agents/{agent_id}")
async def delete_agent_admin(
    agent_id: str,
    request: Request,
    admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """Soft-delete an agent by setting its status to 'archived'."""
    db = _db_path(request)
    try:
        async with aiosqlite.connect(db) as conn:
            existing = await conn.execute_fetchall(
                "SELECT id FROM agents WHERE id = ?", (agent_id,)
            )
            if not existing:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Agent '{agent_id}' not found.",
                )
            await conn.execute(
                "UPDATE agents SET status = 'archived', updated_at = ? WHERE id = ?",
                (_now_iso(), agent_id),
            )
            await conn.commit()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("admin delete_agent_admin failed for %s: %s", agent_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database error while archiving agent.",
        ) from exc

    return {"id": agent_id, "status": "archived", "message": "Agent deleted"}


# ---------------------------------------------------------------------------
# GET /admin/agents/template-distribution
# ---------------------------------------------------------------------------


@router.get("/agents/template-distribution")
async def agent_template_distribution(
    request: Request,
    admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """Return count of active agents grouped by agent_type."""
    db = _db_path(request)
    distribution: list[dict[str, Any]] = []
    try:
        async with aiosqlite.connect(db) as conn:
            rows = await conn.execute_fetchall(
                """
                SELECT agent_type, COUNT(*) AS count
                FROM agents
                WHERE status != 'archived'
                GROUP BY agent_type
                ORDER BY count DESC
                """
            )
            for row in rows:
                distribution.append({"agent_type": row[0], "count": row[1]})
    except Exception as exc:
        logger.error("admin agent_template_distribution query failed: %s", exc)

    return {"distribution": distribution}


# ---------------------------------------------------------------------------
# GET /admin/errors
# ---------------------------------------------------------------------------


@router.get("/errors")
async def error_log(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """Return aggregated error log from the audit chain plus client-side errors.

    Server errors: grouped by error message / endpoint, surfaces count + first/last seen.
    Client errors: individual rows from the client_errors table, newest first.
    """
    db = _db_path(request)
    errors: list[dict[str, Any]] = []

    # --- Server-side errors from audit_chain ---
    try:
        async with aiosqlite.connect(db) as conn:
            rows = await conn.execute_fetchall(
                """
                SELECT details, MIN(timestamp) AS first_seen, MAX(timestamp) AS last_seen,
                       COUNT(*) AS occurrence_count
                FROM audit_chain
                WHERE event_type IN ('error', 'ERROR', 'skill_error', 'request_error')
                GROUP BY details
                ORDER BY last_seen DESC
                LIMIT ?
                """,
                (limit,),
            )
            for row in rows:
                raw_details = row[0] or "{}"
                try:
                    details = json.loads(raw_details)
                except (json.JSONDecodeError, TypeError):
                    details = {"raw": raw_details}

                errors.append({
                    "id": f"server-{row[1]}",
                    "source": "server",
                    "message": details.get("error") or details.get("message") or raw_details[:200],
                    "endpoint": details.get("endpoint") or details.get("path") or "unknown",
                    "count": row[3],
                    "first_seen": row[1],
                    "last_seen": row[2],
                    "status": 0,
                    "details": details,
                })
    except Exception as exc:
        logger.error("admin error_log audit_chain query failed: %s", exc)

    # --- Client-side errors from client_errors table ---
    try:
        async with aiosqlite.connect(db) as conn:
            client_rows = await conn.execute_fetchall(
                """
                SELECT id, message, stack, url, error_type, component, extra, created_at
                FROM client_errors
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            for row in client_rows:
                try:
                    extra = json.loads(row[6] or "{}")
                except (json.JSONDecodeError, TypeError):
                    extra = {}
                errors.append({
                    "id": f"client-{row[0]}",
                    "source": "client",
                    "message": row[1] or "",
                    "stack": row[2],
                    "endpoint": row[3] or "unknown",
                    "error_type": row[4] or "js_error",
                    "component": row[5],
                    "count": 1,
                    "first_seen": row[7],
                    "last_seen": row[7],
                    "status": 0,
                    "extra": extra,
                })
    except Exception as exc:
        logger.error("admin error_log client_errors query failed: %s", exc)

    # Sort merged list by last_seen descending
    errors.sort(key=lambda e: e.get("last_seen") or "", reverse=True)

    return {"errors": errors, "total": len(errors)}


# ---------------------------------------------------------------------------
# GET /admin/health-detailed
# ---------------------------------------------------------------------------


@router.get("/health-detailed")
async def health_detailed(
    request: Request,
    admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """Return detailed system health info.

    Includes process uptime, DB file size, memory usage (RSS via /proc/self/status),
    and per-endpoint request counts from audit chain.
    """
    db = _db_path(request)

    # Process uptime via /proc/self/stat (Linux) — graceful fallback
    uptime_seconds: Optional[float] = None
    try:
        with open("/proc/self/stat") as fh:
            fields = fh.read().split()
        # field index 21 = starttime (clock ticks since boot)
        # This gives relative start; for a wall-clock approach use process start approx
        start_ticks = int(fields[21])
        clock_ticks_per_sec = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
        boot_time_secs: Optional[float] = None
        try:
            with open("/proc/stat") as fh2:
                for line in fh2:
                    if line.startswith("btime "):
                        boot_time_secs = float(line.split()[1])
                        break
        except OSError:
            pass
        if boot_time_secs is not None:
            process_start_epoch = boot_time_secs + (start_ticks / clock_ticks_per_sec)
            uptime_seconds = time.time() - process_start_epoch
    except (OSError, IndexError, ValueError) as exc:
        logger.debug("Could not determine process uptime: %s", exc)

    # DB file size
    db_size_bytes: int = 0
    try:
        db_size_bytes = os.path.getsize(db)
    except OSError:
        pass

    # Memory usage (VmRSS from /proc/self/status)
    memory_rss_kb: int = 0
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    memory_rss_kb = int(line.split()[1])
                    break
    except (OSError, ValueError):
        pass

    # Per-endpoint request counts from audit chain
    endpoint_counts: dict[str, int] = {}
    try:
        async with aiosqlite.connect(db) as conn:
            rows = await conn.execute_fetchall(
                """
                SELECT event_type, COUNT(*) AS cnt
                FROM audit_chain
                GROUP BY event_type
                ORDER BY cnt DESC
                LIMIT 20
                """
            )
            for row in rows:
                endpoint_counts[row[0]] = row[1]
    except Exception as exc:
        logger.error("admin health_detailed audit query failed: %s", exc)

    return {
        "uptime_seconds": uptime_seconds,
        "db_size_bytes": db_size_bytes,
        "memory_rss_kb": memory_rss_kb,
        "avg_response_time_ms": None,  # placeholder — requires request timing middleware
        "audit_event_counts": endpoint_counts,
        "checked_at": _now_iso(),
    }


# ---------------------------------------------------------------------------
# GET /admin/integration-health
# ---------------------------------------------------------------------------


@router.get("/integration-health")
async def integration_health(
    request: Request,
    admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """Return per-integration connection status from the database."""
    db = _db_path(request)

    # Known integrations to surface in the dashboard
    known_integrations = [
        "sendgrid", "twilio", "google_calendar", "stripe", "vapi", "ddmain",
    ]

    integration_rows: list[dict[str, Any]] = []

    try:
        async with aiosqlite.connect(db) as conn:
            rows = await conn.execute_fetchall(
                """
                SELECT integration_type, COUNT(*) AS connected_count,
                       MAX(last_tested_at) AS last_test,
                       MAX(created_at) AS last_created
                FROM agent_integrations
                GROUP BY integration_type
                """
            )
            row_map: dict[str, dict[str, Any]] = {}
            for row in rows:
                row_map[row[0]] = {
                    "name": row[0],
                    "connected_count": row[1],
                    "last_test_result": row[2],
                    "webhook_success_rate": None,
                }

            for name in known_integrations:
                if name in row_map:
                    integration_rows.append(row_map[name])
                else:
                    integration_rows.append({
                        "name": name,
                        "connected_count": 0,
                        "last_test_result": None,
                        "webhook_success_rate": None,
                    })
    except Exception as exc:
        logger.error("admin integration_health query failed: %s", exc)
        for name in known_integrations:
            integration_rows.append({
                "name": name,
                "connected_count": 0,
                "last_test_result": None,
                "webhook_success_rate": None,
            })

    return {"integrations": integration_rows}


# ---------------------------------------------------------------------------
# GET /admin/stripe-status
# ---------------------------------------------------------------------------


@router.get("/stripe-status")
async def stripe_status(
    request: Request,
    admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """Return Stripe mode and webhook configuration status."""
    s = _settings(request)

    key = s.stripe_secret_key or ""
    if key.startswith("sk_live_"):
        mode = "live"
    elif key.startswith("sk_test_"):
        mode = "test"
    elif key:
        mode = "unknown"
    else:
        mode = "not_configured"

    webhook_configured = bool(s.stripe_webhook_secret)

    # Last Stripe event from audit chain
    db = _db_path(request)
    last_event: Optional[str] = None
    customer_count: int = 0

    try:
        async with aiosqlite.connect(db) as conn:
            rows = await conn.execute_fetchall(
                """
                SELECT timestamp FROM audit_chain
                WHERE event_type LIKE 'stripe%' OR event_type LIKE 'payment%'
                ORDER BY timestamp DESC LIMIT 1
                """
            )
            if rows:
                last_event = rows[0][0]
    except Exception as exc:
        logger.error("admin stripe_status last_event query failed: %s", exc)

    try:
        async with aiosqlite.connect(db) as conn:
            rows = await conn.execute_fetchall(
                "SELECT COUNT(DISTINCT user_id) FROM usage_records"
            )
            if rows:
                customer_count = rows[0][0] or 0
    except Exception as exc:
        logger.error("admin stripe_status customer_count query failed: %s", exc)

    return {
        "mode": mode,
        "webhook_configured": webhook_configured,
        "last_event": last_event,
        "customer_count": customer_count,
    }


# ---------------------------------------------------------------------------
# GET /admin/contacts
# ---------------------------------------------------------------------------


@router.get("/contacts")
async def list_all_contacts(
    request: Request,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    search: Optional[str] = Query(default=None),
    admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """Return cross-agent contacts with pagination."""
    db = _db_path(request)
    offset = (page - 1) * per_page

    where_clauses: list[str] = []
    params: list[Any] = []

    if search:
        where_clauses.append("(name LIKE ? OR email LIKE ?)")
        pattern = f"%{search}%"
        params.extend([pattern, pattern])

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    contacts: list[dict[str, Any]] = []
    total = 0

    try:
        async with aiosqlite.connect(db) as conn:
            count_row = await conn.execute_fetchall(
                f"SELECT COUNT(*) FROM skill_contacts {where_sql}", params
            )
            if count_row:
                total = count_row[0][0] or 0

            rows = await conn.execute_fetchall(
                f"""
                SELECT id, agent_id, name, email, source, status, created_at
                FROM skill_contacts
                {where_sql}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                [*params, per_page, offset],
            )
            for row in rows:
                contacts.append({
                    "id": row[0],
                    "agent_id": row[1],
                    "name": row[2],
                    "email": row[3],
                    "source": row[4],
                    "status": row[5],
                    "created_at": row[6],
                })
    except Exception as exc:
        logger.error("admin list_all_contacts query failed: %s", exc)

    return {"contacts": contacts, "total": total, "page": page, "per_page": per_page}


# ---------------------------------------------------------------------------
# GET /admin/funnel
# ---------------------------------------------------------------------------


@router.get("/funnel")
async def conversion_funnel(
    request: Request,
    admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """Return conversion funnel metrics.

    Registered → claimed_handle → active_subscriber → active_7d → churned_30d
    """
    from datetime import timedelta

    db = _db_path(request)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff_7d = (now - timedelta(days=7)).isoformat()
    cutoff_30d = (now - timedelta(days=30)).isoformat()

    funnel: dict[str, int] = {
        "registered_users": 0,
        "claimed_handles": 0,
        "active_subscribers": 0,
        "active_7d": 0,
        "churned_30d": 0,
    }

    try:
        async with aiosqlite.connect(db) as conn:
            row = await conn.execute_fetchall("SELECT COUNT(*) FROM users")
            if row:
                funnel["registered_users"] = row[0][0] or 0
    except Exception as exc:
        logger.error("admin funnel registered_users query failed: %s", exc)

    try:
        async with aiosqlite.connect(db) as conn:
            row = await conn.execute_fetchall("SELECT COUNT(*) FROM agent_handles")
            if row:
                funnel["claimed_handles"] = row[0][0] or 0
    except Exception as exc:
        logger.error("admin funnel claimed_handles query failed: %s", exc)

    try:
        async with aiosqlite.connect(db) as conn:
            row = await conn.execute_fetchall(
                "SELECT COUNT(DISTINCT user_id) FROM usage_records WHERE created_at >= ?",
                (cutoff_7d,),
            )
            if row:
                funnel["active_subscribers"] = row[0][0] or 0
    except Exception as exc:
        logger.error("admin funnel active_subscribers query failed: %s", exc)

    try:
        async with aiosqlite.connect(db) as conn:
            row = await conn.execute_fetchall(
                "SELECT COUNT(DISTINCT user_id) FROM agent_sessions WHERE updated_at >= ?",
                (cutoff_7d,),
            )
            if row:
                funnel["active_7d"] = row[0][0] or 0
    except Exception as exc:
        logger.error("admin funnel active_7d query failed: %s", exc)

    try:
        async with aiosqlite.connect(db) as conn:
            row = await conn.execute_fetchall(
                """
                SELECT COUNT(DISTINCT user_id) FROM agent_sessions
                WHERE updated_at < ? AND updated_at >= ?
                """,
                (cutoff_30d, (now - timedelta(days=60)).isoformat()),
            )
            if row:
                funnel["churned_30d"] = row[0][0] or 0
    except Exception as exc:
        logger.error("admin funnel churned_30d query failed: %s", exc)

    return funnel


# ---------------------------------------------------------------------------
# GET /admin/campaigns
# ---------------------------------------------------------------------------


@router.get("/campaigns")
async def list_campaigns(
    admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """Return campaign list.

    Stub endpoint — returns empty list initially.
    Will be populated as marketing_studio gets wired in.
    """
    return {"campaigns": [], "total": 0}


# ---------------------------------------------------------------------------
# GET /admin/email-stats
# ---------------------------------------------------------------------------


@router.get("/email-stats")
async def email_stats(
    request: Request,
    admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """Return SendGrid delivery stats aggregated from skill_notifications table."""
    db = _db_path(request)

    stats: dict[str, Any] = {
        "total_sent": 0,
        "total_delivered": 0,
        "total_failed": 0,
        "total_bounced": 0,
        "delivery_rate": 0.0,
        "by_status": {},
    }

    try:
        async with aiosqlite.connect(db) as conn:
            rows = await conn.execute_fetchall(
                """
                SELECT status, COUNT(*) AS cnt
                FROM skill_notifications
                WHERE channel = 'email'
                GROUP BY status
                """
            )
            by_status: dict[str, int] = {}
            for row in rows:
                by_status[row[0]] = row[1]

            stats["by_status"] = by_status
            stats["total_sent"] = sum(by_status.values())
            stats["total_delivered"] = by_status.get("sent", 0) + by_status.get("delivered", 0)
            stats["total_failed"] = by_status.get("failed", 0) + by_status.get("error", 0)
            stats["total_bounced"] = by_status.get("bounced", 0)
            if stats["total_sent"] > 0:
                stats["delivery_rate"] = round(stats["total_delivered"] / stats["total_sent"], 4)
    except Exception as exc:
        logger.error("admin email_stats query failed: %s", exc)

    return stats


# ---------------------------------------------------------------------------
# GET /admin/workflow-tests
# ---------------------------------------------------------------------------


@router.get("/workflow-tests")
async def list_workflow_tests(
    admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """Return workflow test definitions with last run results."""
    tests_with_results = []
    for test in _WORKFLOW_TESTS:
        last_result = _workflow_results.get(test["id"])
        tests_with_results.append({**test, "last_result": last_result})

    return {"tests": tests_with_results}


# ---------------------------------------------------------------------------
# POST /admin/workflow-tests/{test_id}/run
# ---------------------------------------------------------------------------


@router.post("/workflow-tests/{test_id}/run")
async def run_workflow_test(
    test_id: str,
    request: Request,
    admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """Trigger a specific workflow test by ID.

    Runs a lightweight in-process health check appropriate for each test type.
    Results are stored in the in-memory _workflow_results dict.
    """
    # Validate test_id
    valid_ids = {t["id"] for t in _WORKFLOW_TESTS}
    if test_id not in valid_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow test '{test_id}' not found. Valid IDs: {sorted(valid_ids)}",
        )

    started_at = _now_iso()
    result: dict[str, Any] = {
        "test_id": test_id,
        "started_at": started_at,
        "status": "unknown",
        "message": "",
        "duration_ms": 0,
    }

    t0 = time.monotonic()

    try:
        if test_id == "health_check":
            db = _db_path(request)
            async with aiosqlite.connect(db) as conn:
                await conn.execute_fetchall("SELECT 1")
            result["status"] = "passed"
            result["message"] = "DB connection healthy."

        elif test_id == "auth_flow":
            # Verify that auth routes are registered
            route_paths = [r.path for r in request.app.routes if hasattr(r, "path")]
            has_register = any("/auth/register" in p for p in route_paths)
            has_login = any("/auth/login" in p for p in route_paths)
            if has_register and has_login:
                result["status"] = "passed"
                result["message"] = "Auth routes /auth/register and /auth/login are registered."
            else:
                result["status"] = "failed"
                result["message"] = "One or more auth routes missing."

        elif test_id == "agent_create":
            route_paths = [r.path for r in request.app.routes if hasattr(r, "path")]
            has_agents = any("/api/v1/agents" in p for p in route_paths)
            if has_agents:
                result["status"] = "passed"
                result["message"] = "Agent creation route /api/v1/agents is registered."
            else:
                result["status"] = "failed"
                result["message"] = "Agent creation route not found."

        elif test_id == "stripe_webhook":
            s = _settings(request)
            if s.stripe_webhook_secret:
                result["status"] = "passed"
                result["message"] = "Stripe webhook secret is configured."
            else:
                result["status"] = "warning"
                result["message"] = "Stripe webhook secret is not configured — webhook validation will fail."

        else:
            result["status"] = "skipped"
            result["message"] = f"No runner implemented for test '{test_id}'."

    except Exception as exc:
        logger.error("Workflow test '%s' raised an exception: %s", test_id, exc)
        result["status"] = "error"
        result["message"] = f"Test raised exception: {type(exc).__name__}: {exc}"

    result["duration_ms"] = round((time.monotonic() - t0) * 1000, 2)
    result["completed_at"] = _now_iso()
    _workflow_results[test_id] = result

    return result


# ---------------------------------------------------------------------------
# GET /admin/alerts
# ---------------------------------------------------------------------------


@router.get("/alerts")
async def list_alerts(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """Return alert feed: errors, payment failures, security events from audit chain."""
    db = _db_path(request)
    alerts: list[dict[str, Any]] = []

    alert_event_types = (
        "error", "ERROR", "skill_error", "request_error",
        "payment_failed", "payment_error",
        "security_violation", "auth_failure", "rate_limit_exceeded",
        "tier_violation",
    )
    placeholders = ",".join("?" * len(alert_event_types))

    try:
        async with aiosqlite.connect(db) as conn:
            rows = await conn.execute_fetchall(
                f"""
                SELECT timestamp, event_type, actor, details
                FROM audit_chain
                WHERE event_type IN ({placeholders})
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (*alert_event_types, limit),
            )
            for row in rows:
                raw_details = row[3] or "{}"
                try:
                    details = json.loads(raw_details)
                except (json.JSONDecodeError, TypeError):
                    details = {"raw": raw_details[:500]}

                severity = "error"
                if "security" in (row[1] or "").lower() or "auth_failure" in (row[1] or ""):
                    severity = "critical"
                elif "payment" in (row[1] or "").lower():
                    severity = "warning"

                alerts.append({
                    "timestamp": row[0],
                    "event_type": row[1],
                    "actor": row[2],
                    "severity": severity,
                    "details": details,
                })
    except Exception as exc:
        logger.error("admin list_alerts query failed: %s", exc)

    return {"alerts": alerts, "total": len(alerts), "thresholds": _alert_thresholds}


# ---------------------------------------------------------------------------
# POST /admin/alerts/configure
# ---------------------------------------------------------------------------


@router.post("/alerts/configure")
async def configure_alerts(
    body: dict[str, Any] = Body(default={}),
    admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """Set alert thresholds.

    Accepted keys: error_rate_per_hour (int), failed_payment_count (int),
    security_event_count (int).  Unknown keys are silently ignored.
    """
    allowed_keys = {"error_rate_per_hour", "failed_payment_count", "security_event_count"}
    updated: dict[str, Any] = {}

    for key in allowed_keys:
        if key in body:
            val = body[key]
            if not isinstance(val, int) or val < 0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"'{key}' must be a non-negative integer.",
                )
            _alert_thresholds[key] = val
            updated[key] = val

    return {"updated": updated, "current_thresholds": dict(_alert_thresholds)}


# ---------------------------------------------------------------------------
# POST /admin/alerts/{alert_id}/acknowledge
# ---------------------------------------------------------------------------


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: str,
    admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """Mark an alert as acknowledged.

    Alert acknowledgements are stored in-memory (reset on server restart).
    This is acceptable for v1 since alerts are derived from audit_chain rows
    and re-generated on each page load.
    """
    if not alert_id or not alert_id.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="alert_id must not be empty.",
        )
    acknowledged_at = _now_iso()
    _acknowledged_alerts[alert_id] = acknowledged_at
    return {"alert_id": alert_id, "acknowledged": True, "acknowledged_at": acknowledged_at}


# ---------------------------------------------------------------------------
# GET /admin/events
# ---------------------------------------------------------------------------


@router.get("/events")
async def list_events(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """Return calendar events: deadlines, appointments from skill_appointments."""
    db = _db_path(request)
    events: list[dict[str, Any]] = []

    try:
        async with aiosqlite.connect(db) as conn:
            rows = await conn.execute_fetchall(
                """
                SELECT id, agent_id, contact_name, title, start_time, status, created_at
                FROM skill_appointments
                ORDER BY start_time ASC
                LIMIT ?
                """,
                (limit,),
            )
            for row in rows:
                events.append({
                    "id": row[0],
                    "agent_id": row[1],
                    "contact_name": row[2],
                    "title": row[3],
                    "start_time": row[4],
                    "status": row[5],
                    "created_at": row[6],
                    "event_type": "appointment",
                })
    except Exception as exc:
        logger.error("admin list_events query failed: %s", exc)

    return {"events": events, "total": len(events)}


# ---------------------------------------------------------------------------
# POST /admin/command
# ---------------------------------------------------------------------------


@router.post("/command")
async def admin_command(
    request: Request,
    body: dict[str, Any] = Body(...),
    admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """MiLA admin command dispatcher — routes to self-healing engine.

    Accepts {"command": "<cmd>"} and routes to the appropriate backend action.

    Commands
    --------
    status         — quick system health summary (fast path)
    diagnose       — full diagnostic report (all checks)
    issues         — list detected issues
    fix <issue_id> — attempt auto-fix for a detected issue
    history        — fix attempt history
    health         — detailed health metrics
    errors         — recent error summary
    restart-check  — verify all systems operational (alias for diagnose)
    env-check      — check critical env var presence (names only, not values)
    help           — list available commands
    stats          — platform stats (users, agents, sessions)
    test <name>    — run a named workflow test
    """
    from isg_agent.core.self_healing import SelfHealingEngine

    raw_command = body.get("command", "").strip()
    if not raw_command:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="'command' field is required and must not be empty.",
        )

    cmd_lower = raw_command.lower()
    s = _settings(request)
    engine = SelfHealingEngine(db_path=_db_path(request), settings=s)

    # --- status ---
    if cmd_lower == "status":
        result = await engine.get_system_status()
        # Normalise: the Command Center UI contract expects {"status": "operational"}
        # when the system is healthy.  Map "healthy" → "operational" so callers
        # using the command endpoint get a stable contract while the self-healing
        # engine is free to use its own vocabulary internally.
        if result.get("status") == "healthy":
            result = {**result, "status": "operational"}
        return {"command": raw_command, "response": result}

    # --- diagnose / restart-check ---
    if cmd_lower in ("diagnose", "restart-check"):
        result = await engine.run_diagnostics()
        return {"command": raw_command, "response": result}

    # --- issues ---
    if cmd_lower == "issues":
        issues = await engine.detect_issues()
        return {
            "command": raw_command,
            "response": {
                "count": len(issues),
                "issues": [
                    {
                        "issue_id": i.issue_id,
                        "category": i.category,
                        "severity": i.severity,
                        "title": i.title,
                        "description": i.description,
                        "auto_fixable": i.auto_fixable,
                        "detected_at": i.detected_at,
                    }
                    for i in issues
                ],
            },
        }

    # --- fix <issue_id> ---
    if cmd_lower.startswith("fix "):
        issue_id = raw_command[4:].strip()
        if not issue_id:
            return {
                "command": raw_command,
                "response": {"error": "Usage: fix <issue_id>. Run 'issues' to see issue IDs."},
            }
        result = await engine.auto_fix(issue_id)
        return {"command": raw_command, "response": result}

    # --- history ---
    if cmd_lower == "history":
        history = engine.get_fix_history()
        return {
            "command": raw_command,
            "response": {
                "count": len(history),
                "history": history,
            },
        }

    # --- health ---
    if cmd_lower == "health":
        result = await engine.run_diagnostics()
        # Return checks portion for a targeted health view
        return {
            "command": raw_command,
            "response": {
                "overall_status": result["overall_status"],
                "checks": result["checks"],
                "generated_at": result["generated_at"],
                "duration_ms": result["duration_ms"],
            },
        }

    # --- errors ---
    if cmd_lower == "errors":
        db = _db_path(request)
        recent: list[dict[str, Any]] = []
        try:
            async with aiosqlite.connect(db) as conn:
                rows = await conn.execute_fetchall(
                    """
                    SELECT timestamp, event_type, details
                    FROM audit_chain
                    WHERE event_type IN ('error','ERROR','skill_error','request_error')
                    ORDER BY timestamp DESC LIMIT 20
                    """
                )
                for row in rows:
                    try:
                        det = json.loads(row[2] or "{}")
                    except (json.JSONDecodeError, TypeError):
                        det = {}
                    recent.append({
                        "timestamp": row[0],
                        "event_type": row[1],
                        "message": det.get("error") or det.get("message") or "(no message)",
                    })
        except Exception as exc:
            logger.error("admin command errors query failed: %s", exc)
        return {"command": raw_command, "response": {"recent_errors": recent, "count": len(recent)}}

    # --- env-check ---
    if cmd_lower == "env-check":
        _CRITICAL_VARS = [
            "ISG_AGENT_SECRET_KEY",
            "ISG_AGENT_ADMIN_EMAIL",
            "ISG_AGENT_DB_PATH",
            "ISG_AGENT_STRIPE_SECRET_KEY",
            "ISG_AGENT_SENDGRID_API_KEY",
            "ISG_AGENT_TWILIO_ACCOUNT_SID",
            "ISG_AGENT_VAPI_API_KEY",
        ]
        env_status: list[dict[str, Any]] = []
        for var in _CRITICAL_VARS:
            val = os.environ.get(var, "")
            env_status.append({
                "var": var,
                "set": bool(val.strip()),
                # Never return the actual value — names only per security rule
            })
        missing = [e["var"] for e in env_status if not e["set"]]
        return {
            "command": raw_command,
            "response": {
                "vars": env_status,
                "missing_count": len(missing),
                "missing": missing,
                "checked_at": _now_iso(),
            },
        }

    # --- stats ---
    if cmd_lower == "stats":
        db = _db_path(request)
        cutoff_24h = (
            datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
        ).isoformat()
        stats: dict[str, int] = {
            "total_users": 0,
            "total_agents": 0,
            "active_sessions_24h": 0,
            "error_count_24h": 0,
        }
        for col, query in [
            ("total_users", "SELECT COUNT(*) FROM users"),
            ("total_agents", "SELECT COUNT(*) FROM agents"),
        ]:
            try:
                async with aiosqlite.connect(db) as conn:
                    row = await conn.execute_fetchall(query)
                    if row:
                        stats[col] = row[0][0] or 0
            except Exception as exc:
                logger.error("admin command stats query %s failed: %s", col, exc)
        try:
            async with aiosqlite.connect(db) as conn:
                row = await conn.execute_fetchall(
                    "SELECT COUNT(*) FROM agent_sessions WHERE updated_at >= ?",
                    (cutoff_24h,),
                )
                if row:
                    stats["active_sessions_24h"] = row[0][0] or 0
        except Exception as exc:
            logger.error("admin command stats sessions query failed: %s", exc)
        try:
            async with aiosqlite.connect(db) as conn:
                row = await conn.execute_fetchall(
                    """
                    SELECT COUNT(*) FROM audit_chain
                    WHERE event_type IN ('error','ERROR','skill_error','request_error')
                    AND timestamp >= ?
                    """,
                    (cutoff_24h,),
                )
                if row:
                    stats["error_count_24h"] = row[0][0] or 0
        except Exception as exc:
            logger.error("admin command stats errors query failed: %s", exc)
        return {"command": raw_command, "response": stats}

    # --- test <name> (legacy workflow test runner) ---
    if cmd_lower.startswith("test "):
        test_name = raw_command[5:].strip()
        valid_ids = {t["id"] for t in _WORKFLOW_TESTS}
        if test_name not in valid_ids:
            return {
                "command": raw_command,
                "response": {
                    "error": f"Unknown test '{test_name}'. Valid: {sorted(valid_ids)}",
                },
            }
        result = await run_workflow_test(test_name, request, admin)
        return {"command": raw_command, "response": result}

    # --- help ---
    if cmd_lower == "help":
        return {
            "command": raw_command,
            "response": {
                "help": (
                    "Available commands: status | diagnose | issues | fix <issue_id> | "
                    "history | health | errors | restart-check | env-check | "
                    "stats | test <test_id> | help\n\n"
                    "Or just ask me anything in natural language — I'll do my best to help."
                ),
                "workflow_tests": [t["id"] for t in _WORKFLOW_TESTS],
                "auto_fixable_issues": ["missing_tables", "stale_sessions"],
            },
        }

    # --- Natural language fallback (Claude Sonnet 4.6 via MiLA chat engine) ---
    from isg_agent.core.mila_chat import chat as mila_chat

    try:
        nl_response = await mila_chat(
            message=raw_command,
            db_path=_db_path(request),
            api_key=s.anthropic_api_key or None,
        )
        return {"command": raw_command, "response": nl_response}
    except Exception as exc:
        logger.error("MiLA NL chat failed: %s: %s", type(exc).__name__, exc)
        return {
            "command": raw_command,
            "response": (
                f"I couldn't process that as natural language (error: {type(exc).__name__}). "
                "Try a structured command: status, errors, health, help"
            ),
        }


# ---------------------------------------------------------------------------
# GET /admin/priorities
# ---------------------------------------------------------------------------


@router.get("/priorities")
async def get_priorities(
    request: Request,
    admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """What needs the owner's attention right now — ranked by urgency.

    Returns a ranked list of actionable items ordered by severity (critical first).
    Each item has a rank, category, title, description, recommended action,
    severity, and detection timestamp.

    Categories: revenue | health | security | integration | data
    Severity:   critical | warning | info
    """
    from isg_agent.core.self_healing import SelfHealingEngine

    s = _settings(request)
    engine = SelfHealingEngine(db_path=_db_path(request), settings=s)

    priorities: list[dict[str, Any]] = []
    now = _now_iso()

    # --- Priority 1: Stripe mode ---
    stripe_key = s.stripe_secret_key or ""
    if stripe_key.startswith("sk_test_"):
        priorities.append({
            "category": "revenue",
            "severity": "critical",
            "title": "Stripe is in TEST mode",
            "description": (
                "The Stripe secret key starts with sk_test_. No real payments can be "
                "processed. Every checkout attempt will use test card data only."
            ),
            "action": "Set ISG_AGENT_STRIPE_SECRET_KEY to your sk_live_... key in the Railway dashboard.",
            "detected_at": now,
        })
    elif not stripe_key:
        priorities.append({
            "category": "revenue",
            "severity": "critical",
            "title": "Stripe key not configured",
            "description": "ISG_AGENT_STRIPE_SECRET_KEY is not set. Payments are completely disabled.",
            "action": "Set ISG_AGENT_STRIPE_SECRET_KEY in Railway dashboard.",
            "detected_at": now,
        })

    # --- Priority 2: Missing critical env vars ---
    _CRITICAL_ENV = [
        "ISG_AGENT_SECRET_KEY",
        "ISG_AGENT_ADMIN_EMAIL",
        "ISG_AGENT_DB_PATH",
        "ISG_AGENT_STRIPE_SECRET_KEY",
        "ISG_AGENT_SENDGRID_API_KEY",
    ]
    missing_env = [v for v in _CRITICAL_ENV if not os.environ.get(v, "").strip()]
    if missing_env:
        priorities.append({
            "category": "health",
            "severity": "critical",
            "title": f"{len(missing_env)} critical env var(s) unset",
            "description": f"These env vars are missing: {missing_env}",
            "action": "Set the listed env vars in the Railway dashboard under Variables.",
            "detected_at": now,
        })

    # --- Priority 3: DB connectivity ---
    db_reachable = False
    try:
        async with aiosqlite.connect(_db_path(request), timeout=3.0) as conn:
            await conn.execute_fetchall("SELECT 1")
            db_reachable = True
    except Exception as exc:
        logger.error("admin get_priorities DB check: %s", exc)
        priorities.append({
            "category": "health",
            "severity": "critical",
            "title": "Database unreachable",
            "description": f"Cannot connect to the SQLite database: {type(exc).__name__}",
            "action": "Check DB volume mount in Railway. Verify ISG_AGENT_DB_PATH points to a writable path.",
            "detected_at": now,
        })

    # --- Priority 4: Error rate (last hour) ---
    if db_reachable:
        cutoff_1h = (
            datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
        ).isoformat()
        try:
            async with aiosqlite.connect(_db_path(request), timeout=3.0) as conn:
                rows = await conn.execute_fetchall(
                    """
                    SELECT COUNT(*) FROM audit_chain
                    WHERE event_type IN ('error','ERROR','skill_error','request_error')
                    AND timestamp >= ?
                    """,
                    (cutoff_1h,),
                )
                error_count_1h = rows[0][0] if rows else 0

            if error_count_1h > 100:
                priorities.append({
                    "category": "health",
                    "severity": "critical",
                    "title": f"High error rate: {error_count_1h} errors/hour",
                    "description": (
                        f"{error_count_1h} errors logged in the last hour. "
                        "System may be partially broken."
                    ),
                    "action": "Run 'errors' command or check /admin/errors for root cause.",
                    "detected_at": now,
                })
            elif error_count_1h > 20:
                priorities.append({
                    "category": "health",
                    "severity": "warning",
                    "title": f"Elevated error rate: {error_count_1h} errors/hour",
                    "description": f"{error_count_1h} errors in the last hour (elevated baseline).",
                    "action": "Monitor /admin/errors. Investigate if rate continues rising.",
                    "detected_at": now,
                })
        except Exception as exc:
            logger.error("admin get_priorities error_rate query failed: %s", exc)

    # --- Priority 5: Integration health ---
    if db_reachable:
        try:
            async with aiosqlite.connect(_db_path(request), timeout=3.0) as conn:
                rows = await conn.execute_fetchall(
                    "SELECT COUNT(*) FROM agent_integrations"
                )
                integration_count = rows[0][0] if rows else 0

            if integration_count == 0:
                priorities.append({
                    "category": "integration",
                    "severity": "info",
                    "title": "No integrations connected",
                    "description": (
                        "No agent integrations (SendGrid, Twilio, Stripe, etc.) are connected. "
                        "Agents cannot send emails, SMS, or process payments without integrations."
                    ),
                    "action": "Guide users to connect integrations via the /integrations UI.",
                    "detected_at": now,
                })
        except Exception as exc:
            logger.error("admin get_priorities integration check failed: %s", exc)

    # --- Priority 6: DB size ---
    db_size_bytes = 0
    try:
        db_size_bytes = os.path.getsize(_db_path(request))
    except OSError:
        pass

    db_size_mb = db_size_bytes // (1024 * 1024)
    if db_size_mb > 500:
        priorities.append({
            "category": "data",
            "severity": "info",
            "title": f"DB size: {db_size_mb} MB",
            "description": (
                f"The SQLite database is {db_size_mb} MB. Consider archiving old audit_chain "
                "records or migrating to PostgreSQL for continued growth."
            ),
            "action": "Run VACUUM on the DB or migrate to PostgreSQL via Railway add-on.",
            "detected_at": now,
        })

    # --- Priority 7: SendGrid not configured ---
    sendgrid_key = getattr(s, "sendgrid_api_key", "") or ""
    if not sendgrid_key:
        priorities.append({
            "category": "integration",
            "severity": "warning",
            "title": "SendGrid not configured",
            "description": "ISG_AGENT_SENDGRID_API_KEY is not set. Email delivery is disabled.",
            "action": "Set ISG_AGENT_SENDGRID_API_KEY in Railway dashboard.",
            "detected_at": now,
        })

    # Rank and sort (critical first, then warning, then info)
    _severity_order = {"critical": 0, "warning": 1, "info": 2}
    priorities.sort(key=lambda p: _severity_order.get(p["severity"], 99))
    for idx, p in enumerate(priorities, start=1):
        p["rank"] = idx

    # Overall system health
    if any(p["severity"] == "critical" for p in priorities):
        system_health = "critical"
    elif any(p["severity"] == "warning" for p in priorities):
        system_health = "degraded"
    else:
        system_health = "healthy"

    return {
        "priorities": priorities,
        "system_health": system_health,
        "total": len(priorities),
        "last_check": now,
    }


# ---------------------------------------------------------------------------
# POST /admin/deploy-marketing-agent
# ---------------------------------------------------------------------------


@router.post("/deploy-marketing-agent", status_code=status.HTTP_201_CREATED)
async def deploy_marketing_agent(
    request: Request,
    admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """Deploy a pre-configured DingDawg marketing agent.

    Creates an agent with handle @dingdawg-marketing owned by the admin user.
    Returns 409 if the agent already exists.
    """
    db = _db_path(request)
    handle = "dingdawg-marketing"
    agent_id = str(uuid.uuid4())
    now = _now_iso()

    # Check if handle already claimed
    try:
        async with aiosqlite.connect(db) as conn:
            existing = await conn.execute_fetchall(
                "SELECT id FROM agents WHERE handle = ? LIMIT 1", (handle,)
            )
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Agent with handle '@{handle}' already exists.",
                )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("admin deploy_marketing_agent existence check failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable during agent existence check.",
        ) from exc

    # Insert the marketing agent
    try:
        async with aiosqlite.connect(db) as conn:
            await conn.execute(
                """
                INSERT INTO agents
                    (id, user_id, handle, name, agent_type, industry_type,
                     status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    agent_id,
                    admin.user_id,
                    handle,
                    "DingDawg Marketing Agent",
                    "marketing",
                    "technology",
                    now,
                    now,
                ),
            )
            await conn.commit()
    except Exception as exc:
        logger.error("admin deploy_marketing_agent insert failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create marketing agent. See server logs.",
        ) from exc

    return {
        "agent_id": agent_id,
        "handle": handle,
        "name": "DingDawg Marketing Agent",
        "agent_type": "marketing",
        "status": "active",
        "owner_id": admin.user_id,
        "created_at": now,
        "message": f"Marketing agent '@{handle}' deployed successfully.",
    }


# ---------------------------------------------------------------------------
# POST /admin/client-errors
# ---------------------------------------------------------------------------


@router.post("/client-errors", status_code=status.HTTP_200_OK)
async def report_client_error(
    request: Request,
    admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """Store one or more client-side errors in SQLite for the Debug page.

    Accepts either a single ClientError object or a JSON array of them
    (the frontend errorReporter sends batches of up to 5).

    Each item is validated for required fields before insertion.  Malformed
    items are logged and skipped — the endpoint never returns 4xx for a
    partial batch so the frontend does not retry indefinitely.
    """
    db = _db_path(request)
    stored = 0
    skipped = 0

    try:
        body = await request.json()
    except Exception as exc:
        logger.error("admin report_client_error: invalid JSON body: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body must be a JSON object or array.",
        ) from exc

    # Normalise to list — frontend sends either a single object or an array
    items: list[Any] = body if isinstance(body, list) else [body]

    # Guard against oversized batches
    if len(items) > 20:
        items = items[:20]

    now = _now_iso()

    try:
        async with aiosqlite.connect(db) as conn:
            for item in items:
                if not isinstance(item, dict):
                    skipped += 1
                    continue
                message = item.get("message")
                if not message or not isinstance(message, str):
                    skipped += 1
                    continue

                stack = item.get("stack")
                if stack is not None:
                    stack = str(stack)[:4000]

                url = str(item.get("url") or "")[:2000]
                error_type = str(item.get("type") or item.get("error_type") or "js_error")[:64]
                component = item.get("component")
                if component is not None:
                    component = str(component)[:255]

                extra_raw = item.get("extra") or {}
                try:
                    extra_json = json.dumps(extra_raw) if isinstance(extra_raw, dict) else "{}"
                except (TypeError, ValueError):
                    extra_json = "{}"

                created_at = item.get("timestamp") or now

                try:
                    await conn.execute(
                        """
                        INSERT INTO client_errors
                            (message, stack, url, error_type, component, extra, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (message[:2000], stack, url, error_type, component, extra_json, created_at),
                    )
                    stored += 1
                except Exception as row_exc:
                    logger.error(
                        "admin report_client_error: row insert failed: %s", row_exc
                    )
                    skipped += 1

            await conn.commit()
    except Exception as exc:
        logger.error("admin report_client_error: db error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable. Client errors not stored.",
        ) from exc

    return {"stored": stored, "skipped": skipped}


# ---------------------------------------------------------------------------
# DELETE /admin/client-errors  (clear client error table)
# ---------------------------------------------------------------------------


@router.delete("/client-errors", status_code=status.HTTP_200_OK)
async def clear_client_errors(
    request: Request,
    admin: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """Delete all rows from client_errors table.

    Called by the Debug page 'Clear' button alongside the existing
    POST /admin/errors/clear which clears server-side audit_chain errors.
    """
    db = _db_path(request)
    deleted = 0

    try:
        async with aiosqlite.connect(db) as conn:
            cursor = await conn.execute("DELETE FROM client_errors")
            deleted = cursor.rowcount or 0
            await conn.commit()
    except Exception as exc:
        logger.error("admin clear_client_errors failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to clear client errors.",
        ) from exc

    return {"deleted": deleted, "cleared": True}
