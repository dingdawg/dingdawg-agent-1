"""Analytics API for agent owners.

Provides metrics, conversation stats, skill usage data, and
performance indicators for the business owner dashboard.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import Counter
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from isg_agent.api.deps import CurrentUser, require_auth

__all__ = ["router", "init_analytics_tables"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])

# ---------------------------------------------------------------------------
# Analytics events table (lightweight supplementary tracking)
# ---------------------------------------------------------------------------

_CREATE_ANALYTICS_EVENTS_SQL = """
CREATE TABLE IF NOT EXISTS analytics_events (
    id          TEXT PRIMARY KEY,
    agent_id    TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL
);
"""

_CREATE_INDEX_AGENT_TYPE = (
    "CREATE INDEX IF NOT EXISTS idx_analytics_agent_type "
    "ON analytics_events(agent_id, event_type);"
)

_CREATE_INDEX_CREATED = (
    "CREATE INDEX IF NOT EXISTS idx_analytics_created "
    "ON analytics_events(created_at);"
)

# Ensure memory_messages exists at startup so analytics routes never crash on
# a fresh deployment where MemoryStore._ensure_initialized has not run yet.
# This DDL is intentionally identical to MemoryStore._CREATE_TABLE_SQL so
# there is no schema drift: IF NOT EXISTS means whichever path runs first wins.
_CREATE_MEMORY_MESSAGES_SQL = """
CREATE TABLE IF NOT EXISTS memory_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    role        TEXT    NOT NULL,
    content     TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);
"""

_CREATE_INDEX_MEMORY_SESSION = (
    "CREATE INDEX IF NOT EXISTS idx_memory_messages_session_id "
    "ON memory_messages(session_id);"
)

_CREATE_INDEX_MEMORY_TS = (
    "CREATE INDEX IF NOT EXISTS idx_memory_messages_created_at "
    "ON memory_messages(created_at);"
)


async def init_analytics_tables(db_path: str) -> None:
    """Create the analytics_events and memory_messages tables if they do not exist.

    memory_messages is created here (idempotent) so that analytics endpoints
    can query it safely on a fresh deployment before any chat message has
    been sent (MemoryStore uses lazy initialisation and would not have created
    the table yet).  Both CREATE TABLE statements use IF NOT EXISTS, so
    whichever path runs first wins and there is no schema drift.
    """
    async with aiosqlite.connect(db_path) as db:
        await db.execute(_CREATE_ANALYTICS_EVENTS_SQL)
        await db.execute(_CREATE_INDEX_AGENT_TYPE)
        await db.execute(_CREATE_INDEX_CREATED)
        await db.execute(_CREATE_MEMORY_MESSAGES_SQL)
        await db.execute(_CREATE_INDEX_MEMORY_SESSION)
        await db.execute(_CREATE_INDEX_MEMORY_TS)
        await db.commit()
    logger.info("Analytics tables initialised (analytics_events + memory_messages)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_db_path(request: Request) -> str:
    """Extract the database path from app state."""
    return request.app.state.settings.db_path


def _date_range(days: int = 7) -> tuple[str, str, str, str]:
    """Return (period_start, period_end, prev_start, prev_end) as ISO strings.

    ``period_start`` / ``period_end`` cover the last *days* days.
    ``prev_start`` / ``prev_end`` cover the *days* days before that
    (used for trend calculation).
    """
    now = datetime.now(timezone.utc)
    period_end = now.isoformat()
    period_start = (now - timedelta(days=days)).isoformat()
    prev_end = period_start
    prev_start = (now - timedelta(days=days * 2)).isoformat()
    return period_start, period_end, prev_start, prev_end


def _safe_pct_change(current: int, previous: int) -> float:
    """Compute percentage change, returning 0.0 when previous is zero."""
    if previous == 0:
        return 100.0 if current > 0 else 0.0
    return round(((current - previous) / previous) * 100, 1)


async def _scalar(db: aiosqlite.Connection, sql: str, params: tuple = ()) -> int:
    """Execute a query and return the first column of the first row as int."""
    cursor = await db.execute(sql, params)
    row = await cursor.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


async def _scalar_float(db: aiosqlite.Connection, sql: str, params: tuple = ()) -> float:
    """Execute a query and return the first column as float."""
    cursor = await db.execute(sql, params)
    row = await cursor.fetchone()
    return float(row[0]) if row and row[0] is not None else 0.0


async def _verify_agent_ownership(db_path: str, agent_id: str, user_id: str) -> None:
    """Raise HTTP 403 if the user does not own the given agent.

    Queries the agents table to confirm the agent exists (and is not
    archived) and that its user_id matches the requesting user.
    """
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT user_id FROM agents WHERE id = ? AND status != 'archived'",
            (agent_id,),
        )
        row = await cursor.fetchone()
    if row is None or row[0] != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not your agent",
        )


# ---------------------------------------------------------------------------
# Record analytics event (utility for other modules)
# ---------------------------------------------------------------------------


async def record_event(
    db_path: str,
    agent_id: str,
    event_type: str,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Insert an analytics event. Returns the event ID."""
    event_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    meta_str = json.dumps(metadata or {}, separators=(",", ":"))
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO analytics_events (id, agent_id, event_type, metadata, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (event_id, agent_id, event_type, meta_str, now),
        )
        await db.commit()
    return event_id


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/dashboard/{agent_id}",
    summary="Main dashboard overview for an agent owner",
)
async def dashboard_overview(
    request: Request,
    agent_id: str,
    user: CurrentUser = Depends(require_auth),
) -> dict[str, Any]:
    """Return a single payload with all dashboard data for the given agent.

    Queries across multiple tables (sessions, messages, audit, appointments,
    contacts, notifications) and returns aggregated metrics for the last 7 days.
    """
    db_path = _get_db_path(request)
    await _verify_agent_ownership(db_path, agent_id, user.user_id)
    period_start, period_end, prev_start, prev_end = _date_range(7)
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    ).isoformat()

    async with aiosqlite.connect(db_path) as db:
        # ---- Conversations ---------------------------------------------------
        conv_total = await _scalar(
            db,
            "SELECT COUNT(*) FROM agent_sessions "
            "WHERE (agent_id = ? OR user_id = ?) AND created_at >= ?",
            (agent_id, user.user_id, period_start),
        )
        conv_today = await _scalar(
            db,
            "SELECT COUNT(*) FROM agent_sessions "
            "WHERE (agent_id = ? OR user_id = ?) AND created_at >= ?",
            (agent_id, user.user_id, today_start),
        )
        conv_prev = await _scalar(
            db,
            "SELECT COUNT(*) FROM agent_sessions "
            "WHERE (agent_id = ? OR user_id = ?) AND created_at >= ? AND created_at < ?",
            (agent_id, user.user_id, prev_start, prev_end),
        )
        conv_trend = _safe_pct_change(conv_total, conv_prev)

        # ---- Messages --------------------------------------------------------
        # Get session IDs for this agent/user in the period
        cursor = await db.execute(
            "SELECT session_id FROM agent_sessions "
            "WHERE (agent_id = ? OR user_id = ?) AND created_at >= ?",
            (agent_id, user.user_id, period_start),
        )
        session_rows = await cursor.fetchall()
        session_ids = [r[0] for r in session_rows]

        msg_total = 0
        if session_ids:
            placeholders = ",".join("?" for _ in session_ids)
            msg_total = await _scalar(
                db,
                f"SELECT COUNT(*) FROM memory_messages WHERE session_id IN ({placeholders})",
                tuple(session_ids),
            )

        msg_avg = round(msg_total / conv_total, 1) if conv_total > 0 else 0.0

        # ---- Skills (from audit_chain) ----------------------------------------
        skill_total = await _scalar(
            db,
            "SELECT COUNT(*) FROM audit_chain "
            "WHERE event_type = 'skill_execution' AND actor = ? AND timestamp >= ?",
            (user.user_id, period_start),
        )
        # Also try agent_id as actor (skills may be recorded under agent_id)
        skill_total_agent = await _scalar(
            db,
            "SELECT COUNT(*) FROM audit_chain "
            "WHERE event_type = 'skill_execution' AND actor = ? AND timestamp >= ?",
            (agent_id, period_start),
        )
        skill_total = skill_total + skill_total_agent

        # Skill breakdown by name
        cursor = await db.execute(
            "SELECT details FROM audit_chain "
            "WHERE event_type = 'skill_execution' AND (actor = ? OR actor = ?) "
            "AND timestamp >= ?",
            (user.user_id, agent_id, period_start),
        )
        skill_rows = await cursor.fetchall()
        skill_counter: Counter[str] = Counter()
        skill_success = 0
        for (details_str,) in skill_rows:
            try:
                det = json.loads(details_str)
                skill_name = det.get("skill", det.get("skill_name", "unknown"))
                skill_counter[skill_name] += 1
                if det.get("status") == "success" or det.get("success") is True:
                    skill_success += 1
            except (json.JSONDecodeError, TypeError):
                pass

        by_skill = dict(skill_counter.most_common(20))
        success_rate = round(skill_success / skill_total * 100, 1) if skill_total > 0 else 0.0

        # ---- Appointments ----------------------------------------------------
        appt_scheduled = await _scalar(
            db,
            "SELECT COUNT(*) FROM skill_appointments WHERE agent_id = ? AND status = 'scheduled'",
            (agent_id,),
        )
        appt_completed = await _scalar(
            db,
            "SELECT COUNT(*) FROM skill_appointments WHERE agent_id = ? AND status = 'completed'",
            (agent_id,),
        )
        appt_cancelled = await _scalar(
            db,
            "SELECT COUNT(*) FROM skill_appointments WHERE agent_id = ? AND status = 'cancelled'",
            (agent_id,),
        )
        now_iso = datetime.now(timezone.utc).isoformat()
        appt_upcoming = await _scalar(
            db,
            "SELECT COUNT(*) FROM skill_appointments "
            "WHERE agent_id = ? AND status = 'scheduled' AND start_time > ?",
            (agent_id, now_iso),
        )

        # ---- Contacts --------------------------------------------------------
        contacts_total = await _scalar(
            db,
            "SELECT COUNT(*) FROM skill_contacts WHERE agent_id = ?",
            (agent_id,),
        )
        contacts_new = await _scalar(
            db,
            "SELECT COUNT(*) FROM skill_contacts WHERE agent_id = ? AND created_at >= ?",
            (agent_id, period_start),
        )
        cursor = await db.execute(
            "SELECT status, COUNT(*) FROM skill_contacts WHERE agent_id = ? GROUP BY status",
            (agent_id,),
        )
        contact_status_rows = await cursor.fetchall()
        by_status = {r[0]: r[1] for r in contact_status_rows}

        # ---- Notifications ---------------------------------------------------
        notif_sent = await _scalar(
            db,
            "SELECT COUNT(*) FROM skill_notifications WHERE agent_id = ? AND status = 'sent'",
            (agent_id,),
        )
        notif_failed = await _scalar(
            db,
            "SELECT COUNT(*) FROM skill_notifications WHERE agent_id = ? AND status = 'failed'",
            (agent_id,),
        )
        notif_queued = await _scalar(
            db,
            "SELECT COUNT(*) FROM skill_notifications WHERE agent_id = ? AND status = 'queued'",
            (agent_id,),
        )

        # ---- Top topics (simple word frequency from messages) -----------------
        top_topics: list[str] = []
        if session_ids:
            placeholders = ",".join("?" for _ in session_ids)
            cursor = await db.execute(
                f"SELECT content FROM memory_messages "
                f"WHERE session_id IN ({placeholders}) AND role = 'user' "
                f"ORDER BY created_at DESC LIMIT 200",
                tuple(session_ids),
            )
            msg_rows = await cursor.fetchall()
            word_counter: Counter[str] = Counter()
            stop_words = {
                "the", "a", "an", "is", "are", "was", "were", "be", "been",
                "being", "have", "has", "had", "do", "does", "did", "will",
                "would", "could", "should", "may", "might", "shall", "can",
                "i", "me", "my", "you", "your", "we", "our", "he", "she",
                "it", "they", "them", "their", "this", "that", "these",
                "those", "in", "on", "at", "to", "for", "of", "with",
                "and", "or", "but", "not", "no", "so", "if", "then",
                "than", "too", "very", "just", "about", "up", "out",
                "what", "when", "where", "how", "why", "who", "which",
                "all", "each", "every", "both", "few", "more", "most",
                "other", "some", "such", "only", "own", "same",
            }
            for (content,) in msg_rows:
                words = content.lower().split()
                for w in words:
                    cleaned = w.strip(".,!?;:\"'()[]{}").lower()
                    if len(cleaned) > 2 and cleaned not in stop_words:
                        word_counter[cleaned] += 1
            top_topics = [w for w, _ in word_counter.most_common(10)]

        # ---- Active hours ----------------------------------------------------
        active_hours: dict[str, int] = {}
        if session_ids:
            placeholders = ",".join("?" for _ in session_ids)
            cursor = await db.execute(
                f"SELECT created_at FROM memory_messages "
                f"WHERE session_id IN ({placeholders})",
                tuple(session_ids),
            )
            ts_rows = await cursor.fetchall()
            hour_counter: Counter[str] = Counter()
            for (ts,) in ts_rows:
                try:
                    dt = datetime.fromisoformat(ts)
                    hour_counter[str(dt.hour)] += 1
                except (ValueError, TypeError):
                    pass
            active_hours = dict(sorted(hour_counter.items(), key=lambda x: int(x[0])))

        # ---- Analytics events (response time, widget loads, etc.) -------------
        response_time_avg_ms = 0.0
        cursor = await db.execute(
            "SELECT metadata FROM analytics_events "
            "WHERE agent_id = ? AND event_type = 'message' AND created_at >= ?",
            (agent_id, period_start),
        )
        event_rows = await cursor.fetchall()
        response_times: list[float] = []
        for (meta_str,) in event_rows:
            try:
                meta = json.loads(meta_str)
                rt = meta.get("response_time_ms")
                if rt is not None:
                    response_times.append(float(rt))
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        if response_times:
            response_time_avg_ms = round(sum(response_times) / len(response_times), 1)

    return {
        "agent_id": agent_id,
        "period": "last_7_days",
        "conversations": {
            "total": conv_total,
            "today": conv_today,
            "trend": conv_trend,
        },
        "messages": {
            "total": msg_total,
            "avg_per_conversation": msg_avg,
        },
        "skills": {
            "total_executions": skill_total,
            "by_skill": by_skill,
            "success_rate": success_rate,
        },
        "appointments": {
            "scheduled": appt_scheduled,
            "completed": appt_completed,
            "cancelled": appt_cancelled,
            "upcoming": appt_upcoming,
        },
        "contacts": {
            "total": contacts_total,
            "new_this_period": contacts_new,
            "by_status": by_status,
        },
        "notifications": {
            "sent": notif_sent,
            "failed": notif_failed,
            "queued": notif_queued,
        },
        "top_topics": top_topics,
        "response_time_avg_ms": response_time_avg_ms,
        "active_hours": active_hours,
    }


@router.get(
    "/conversations/{agent_id}",
    summary="List recent conversations for an agent",
)
async def conversation_history(
    request: Request,
    agent_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    user: CurrentUser = Depends(require_auth),
) -> dict[str, Any]:
    """Return a paginated list of conversations (sessions) for the agent."""
    db_path = _get_db_path(request)
    await _verify_agent_ownership(db_path, agent_id, user.user_id)

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        # Build WHERE clause
        conditions = ["(agent_id = ? OR user_id = ?)"]
        params: list[Any] = [agent_id, user.user_id]

        if date_from:
            conditions.append("created_at >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("created_at <= ?")
            params.append(date_to)

        where = " AND ".join(conditions)

        # Total count
        total = await _scalar(
            db,
            f"SELECT COUNT(*) FROM agent_sessions WHERE {where}",
            tuple(params),
        )

        # Fetch sessions
        params_paginated = params + [limit, offset]
        cursor = await db.execute(
            f"SELECT session_id, user_id, created_at, updated_at, "
            f"message_count, total_tokens, status, agent_id "
            f"FROM agent_sessions WHERE {where} "
            f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
            tuple(params_paginated),
        )
        rows = await cursor.fetchall()

        conversations = []
        for row in rows:
            session_id = row["session_id"]
            # Get a message preview (first user message).
            # Guard against OperationalError on deployments where
            # memory_messages was not yet created by MemoryStore (belt and
            # suspenders — init_analytics_tables creates it at startup, but
            # this catch protects against any remaining edge cases).
            preview = ""
            try:
                preview_cursor = await db.execute(
                    "SELECT content FROM memory_messages "
                    "WHERE session_id = ? AND role = 'user' ORDER BY id ASC LIMIT 1",
                    (session_id,),
                )
                preview_row = await preview_cursor.fetchone()
                if preview_row:
                    preview = str(preview_row["content"])[:120]
            except aiosqlite.OperationalError as exc:
                logger.warning(
                    "conversation_history: memory_messages query failed for "
                    "session %s (table may not exist yet): %s",
                    session_id,
                    exc,
                )

            # Last message timestamp.
            last_message_at = row["updated_at"]
            try:
                last_cursor = await db.execute(
                    "SELECT created_at FROM memory_messages "
                    "WHERE session_id = ? ORDER BY id DESC LIMIT 1",
                    (session_id,),
                )
                last_row = await last_cursor.fetchone()
                if last_row:
                    last_message_at = str(last_row["created_at"])
            except aiosqlite.OperationalError as exc:
                logger.warning(
                    "conversation_history: memory_messages timestamp query failed "
                    "for session %s (table may not exist yet): %s",
                    session_id,
                    exc,
                )

            conversations.append({
                "session_id": session_id,
                "started_at": row["created_at"],
                "message_count": row["message_count"],
                "last_message_at": last_message_at,
                "preview": preview,
            })

    return {"conversations": conversations, "total": total}


@router.get(
    "/skills/{agent_id}",
    summary="Detailed skill usage analytics",
)
async def skill_analytics(
    request: Request,
    agent_id: str,
    days: int = Query(default=30, ge=1, le=365),
    user: CurrentUser = Depends(require_auth),
) -> dict[str, Any]:
    """Return detailed skill usage analytics from the audit chain."""
    db_path = _get_db_path(request)
    await _verify_agent_ownership(db_path, agent_id, user.user_id)
    period_start = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    async with aiosqlite.connect(db_path) as db:
        # Fetch all skill_execution audit entries for this agent/user
        cursor = await db.execute(
            "SELECT timestamp, details FROM audit_chain "
            "WHERE event_type = 'skill_execution' "
            "AND (actor = ? OR actor = ?) "
            "AND timestamp >= ? "
            "ORDER BY timestamp ASC",
            (user.user_id, agent_id, period_start),
        )
        rows = await cursor.fetchall()

    # Process into by_skill and daily aggregations
    skill_stats: dict[str, dict[str, Any]] = {}
    daily_counter: Counter[str] = Counter()
    action_counter: Counter[tuple[str, str]] = Counter()

    for ts, details_str in rows:
        try:
            det = json.loads(details_str)
        except (json.JSONDecodeError, TypeError):
            det = {}

        skill_name = det.get("skill", det.get("skill_name", "unknown"))
        action = det.get("action", "default")
        is_success = det.get("status") == "success" or det.get("success") is True
        duration = det.get("duration_ms", 0)

        # by_skill stats
        if skill_name not in skill_stats:
            skill_stats[skill_name] = {
                "name": skill_name,
                "executions": 0,
                "successes": 0,
                "total_duration_ms": 0,
            }
        skill_stats[skill_name]["executions"] += 1
        if is_success:
            skill_stats[skill_name]["successes"] += 1
        skill_stats[skill_name]["total_duration_ms"] += duration

        # Daily aggregation
        try:
            dt = datetime.fromisoformat(ts)
            day_str = dt.strftime("%Y-%m-%d")
            daily_counter[day_str] += 1
        except (ValueError, TypeError):
            pass

        # Action counter
        action_counter[(skill_name, action)] += 1

    # Build response
    by_skill = []
    for s in skill_stats.values():
        execs = s["executions"]
        by_skill.append({
            "name": s["name"],
            "executions": execs,
            "success_rate": round(s["successes"] / execs * 100, 1) if execs > 0 else 0.0,
            "avg_duration_ms": round(s["total_duration_ms"] / execs, 1) if execs > 0 else 0.0,
        })
    by_skill.sort(key=lambda x: x["executions"], reverse=True)

    daily = [{"date": d, "executions": c} for d, c in sorted(daily_counter.items())]

    top_actions = [
        {"skill": sk, "action": act, "count": cnt}
        for (sk, act), cnt in action_counter.most_common(20)
    ]

    return {
        "by_skill": by_skill,
        "daily": daily,
        "top_actions": top_actions,
    }


@router.get(
    "/contacts/{agent_id}/stats",
    summary="Contact/CRM statistics for an agent",
)
async def contact_stats(
    request: Request,
    agent_id: str,
    user: CurrentUser = Depends(require_auth),
) -> dict[str, Any]:
    """Return contact/CRM summary statistics for the agent."""
    db_path = _get_db_path(request)
    await _verify_agent_ownership(db_path, agent_id, user.user_id)

    async with aiosqlite.connect(db_path) as db:
        # Total contacts
        total = await _scalar(
            db,
            "SELECT COUNT(*) FROM skill_contacts WHERE agent_id = ?",
            (agent_id,),
        )

        # By status
        cursor = await db.execute(
            "SELECT status, COUNT(*) FROM skill_contacts WHERE agent_id = ? GROUP BY status",
            (agent_id,),
        )
        status_rows = await cursor.fetchall()
        by_status = {r[0]: r[1] for r in status_rows}

        # By source
        cursor = await db.execute(
            "SELECT COALESCE(source, 'unknown'), COUNT(*) FROM skill_contacts "
            "WHERE agent_id = ? GROUP BY source",
            (agent_id,),
        )
        source_rows = await cursor.fetchall()
        by_source = {r[0]: r[1] for r in source_rows}

        # Recent contacts (last 10)
        cursor = await db.execute(
            "SELECT name, email, created_at FROM skill_contacts "
            "WHERE agent_id = ? ORDER BY created_at DESC LIMIT 10",
            (agent_id,),
        )
        recent_rows = await cursor.fetchall()
        recent = [
            {"name": r[0], "email": r[1], "added_at": r[2]}
            for r in recent_rows
        ]

    return {
        "total": total,
        "by_status": by_status,
        "by_source": by_source,
        "recent": recent,
    }


@router.get(
    "/revenue/{agent_id}",
    summary="Revenue and billing analytics",
)
async def revenue_analytics(
    request: Request,
    agent_id: str,
    days: int = Query(default=30, ge=1, le=365),
    user: CurrentUser = Depends(require_auth),
) -> dict[str, Any]:
    """Return revenue analytics based on completed appointments and transactions."""
    db_path = _get_db_path(request)
    await _verify_agent_ownership(db_path, agent_id, user.user_id)
    period_start = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    async with aiosqlite.connect(db_path) as db:
        # Completed appointments in period
        completed = await _scalar(
            db,
            "SELECT COUNT(*) FROM skill_appointments "
            "WHERE agent_id = ? AND status = 'completed' AND updated_at >= ?",
            (agent_id, period_start),
        )

        # Simple revenue estimate: count completed appointments
        # In production this would come from actual payment records
        # For now, use analytics_events with event_type='transaction'
        cursor = await db.execute(
            "SELECT metadata FROM analytics_events "
            "WHERE agent_id = ? AND event_type = 'transaction' AND created_at >= ?",
            (agent_id, period_start),
        )
        tx_rows = await cursor.fetchall()
        total_revenue = 0.0
        for (meta_str,) in tx_rows:
            try:
                meta = json.loads(meta_str)
                total_revenue += float(meta.get("amount", 0))
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        transactions = len(tx_rows)

        # Daily breakdown
        daily_map: dict[str, dict[str, Any]] = {}

        # From completed appointments
        cursor = await db.execute(
            "SELECT updated_at FROM skill_appointments "
            "WHERE agent_id = ? AND status = 'completed' AND updated_at >= ? "
            "ORDER BY updated_at ASC",
            (agent_id, period_start),
        )
        appt_rows = await cursor.fetchall()
        for (ts,) in appt_rows:
            try:
                day = datetime.fromisoformat(ts).strftime("%Y-%m-%d")
                if day not in daily_map:
                    daily_map[day] = {"date": day, "count": 0, "revenue": 0.0}
                daily_map[day]["count"] += 1
            except (ValueError, TypeError):
                pass

        # From transaction events
        for (meta_str,) in tx_rows:
            try:
                meta = json.loads(meta_str)
                ts = meta.get("timestamp", "")
                amount = float(meta.get("amount", 0))
                day = datetime.fromisoformat(ts).strftime("%Y-%m-%d") if ts else ""
                if day:
                    if day not in daily_map:
                        daily_map[day] = {"date": day, "count": 0, "revenue": 0.0}
                    daily_map[day]["revenue"] += amount
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        daily = sorted(daily_map.values(), key=lambda x: x["date"])

    return {
        "appointments_revenue": round(total_revenue, 2),
        "transactions": transactions,
        "completed_appointments": completed,
        "daily": daily,
    }
