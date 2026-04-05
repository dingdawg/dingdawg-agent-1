"""MCP tools for analytics dashboard queries.

Tools
-----
analytics.dashboard — Query analytics_events, memory_messages, and
                       audit_chain tables and return a unified dashboard
                       payload for the given agent.

Returns the standard ok/err envelope with an MCPReceipt.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import aiosqlite

from isg_agent.capabilities.shared.foundation import (
    err,
    iso_now,
    make_receipt,
    ok,
)

__all__ = ["analytics_dashboard"]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mcp_receipt(
    action_type: str,
    triggered_by: str,
    outcome: str,
    *,
    timestamp: Optional[str] = None,
) -> dict[str, Any]:
    """Build an MCPReceipt dict using the shared foundation make_receipt."""
    return make_receipt(
        action_type=action_type,
        triggered_by=triggered_by,
        outcome=outcome,
        timestamp=timestamp or iso_now(),
    )


async def _scalar(
    db: aiosqlite.Connection,
    sql: str,
    params: tuple = (),
) -> int:
    """Execute a query and return the first column of the first row as int."""
    cursor = await db.execute(sql, params)
    row = await cursor.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _date_range(days: int = 7) -> tuple[str, str, str, str]:
    """Return (period_start, period_end, prev_start, prev_end) as ISO strings."""
    now = datetime.now(timezone.utc)
    period_end = now.isoformat()
    period_start = (now - timedelta(days=days)).isoformat()
    prev_end = period_start
    prev_start = (now - timedelta(days=days * 2)).isoformat()
    return period_start, period_end, prev_start, prev_end


def _safe_pct_change(current: int, previous: int) -> float:
    """Compute percentage change; return 0.0 when previous is zero."""
    if previous == 0:
        return 100.0 if current > 0 else 0.0
    return round(((current - previous) / previous) * 100, 1)


# ---------------------------------------------------------------------------
# Tool: analytics.dashboard
# ---------------------------------------------------------------------------


async def analytics_dashboard(
    db_path: str,
    agent_id: str,
    days: int = 7,
    triggered_by: str = "mcp_tool",
) -> dict[str, Any]:
    """MCP tool: analytics.dashboard

    Query ``analytics_events``, ``memory_messages``, and ``audit_chain``
    tables to build a unified dashboard payload for the given agent.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.
    agent_id:
        The agent whose analytics to retrieve.
    days:
        Look-back window in days (default 7).  Must be between 1 and 365.
    triggered_by:
        Actor identifier for the MCPReceipt (default ``"mcp_tool"``).

    Returns
    -------
    dict
        ``ok`` envelope on success::

            {
                "ok": True,
                "data": {
                    "agent_id": str,
                    "period_days": int,
                    "conversations": {"total": int, "today": int, "trend_pct": float},
                    "messages": {"total": int, "avg_per_conversation": float},
                    "skills": {
                        "total_executions": int,
                        "by_skill": {name: count},
                        "success_rate": float,
                    },
                    "analytics_events": {"total": int, "by_type": {type: count}},
                    "response_time_avg_ms": float,
                    "top_topics": [str, ...],
                    "active_hours": {hour_str: count},
                },
                "receipt": MCPReceipt,
            }

        ``err`` envelope on failure.
    """
    action_type = "analytics.dashboard"

    if not (1 <= days <= 365):
        return err(
            action_type=action_type,
            triggered_by=triggered_by,
            message=f"days must be between 1 and 365, got {days}",
        )

    period_start, period_end, prev_start, prev_end = _date_range(days)
    today_start = (
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .isoformat()
    )

    try:
        async with aiosqlite.connect(db_path) as db:
            # ------------------------------------------------------------------
            # Conversations (agent_sessions)
            # ------------------------------------------------------------------
            conv_total = await _scalar(
                db,
                "SELECT COUNT(*) FROM agent_sessions "
                "WHERE agent_id = ? AND created_at >= ?",
                (agent_id, period_start),
            )
            conv_today = await _scalar(
                db,
                "SELECT COUNT(*) FROM agent_sessions "
                "WHERE agent_id = ? AND created_at >= ?",
                (agent_id, today_start),
            )
            conv_prev = await _scalar(
                db,
                "SELECT COUNT(*) FROM agent_sessions "
                "WHERE agent_id = ? AND created_at >= ? AND created_at < ?",
                (agent_id, prev_start, prev_end),
            )
            conv_trend = _safe_pct_change(conv_total, conv_prev)

            # ------------------------------------------------------------------
            # Messages (memory_messages via session IDs)
            # ------------------------------------------------------------------
            cursor = await db.execute(
                "SELECT session_id FROM agent_sessions "
                "WHERE agent_id = ? AND created_at >= ?",
                (agent_id, period_start),
            )
            session_rows = await cursor.fetchall()
            session_ids = [r[0] for r in session_rows]

            msg_total = 0
            top_topics: list[str] = []
            active_hours: dict[str, int] = {}

            if session_ids:
                placeholders = ",".join("?" for _ in session_ids)

                msg_total = await _scalar(
                    db,
                    f"SELECT COUNT(*) FROM memory_messages "
                    f"WHERE session_id IN ({placeholders})",
                    tuple(session_ids),
                )

                # Top topics — simple word-frequency over recent user messages
                cursor = await db.execute(
                    f"SELECT content FROM memory_messages "
                    f"WHERE session_id IN ({placeholders}) AND role = 'user' "
                    f"ORDER BY created_at DESC LIMIT 200",
                    tuple(session_ids),
                )
                msg_rows = await cursor.fetchall()
                _STOP_WORDS = frozenset(
                    {
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
                )
                word_counter: Counter[str] = Counter()
                for (content,) in msg_rows:
                    for w in content.lower().split():
                        cleaned = w.strip(".,!?;:\"'()[]{}").lower()
                        if len(cleaned) > 2 and cleaned not in _STOP_WORDS:
                            word_counter[cleaned] += 1
                top_topics = [w for w, _ in word_counter.most_common(10)]

                # Active hours
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
                active_hours = dict(
                    sorted(hour_counter.items(), key=lambda x: int(x[0]))
                )

            msg_avg = round(msg_total / conv_total, 1) if conv_total > 0 else 0.0

            # ------------------------------------------------------------------
            # Skills (audit_chain)
            # ------------------------------------------------------------------
            skill_total = await _scalar(
                db,
                "SELECT COUNT(*) FROM audit_chain "
                "WHERE event_type = 'skill_execution' AND actor = ? "
                "AND timestamp >= ?",
                (agent_id, period_start),
            )

            cursor = await db.execute(
                "SELECT details FROM audit_chain "
                "WHERE event_type = 'skill_execution' AND actor = ? "
                "AND timestamp >= ?",
                (agent_id, period_start),
            )
            skill_rows = await cursor.fetchall()
            skill_counter: Counter[str] = Counter()
            skill_success_count = 0
            for (details_str,) in skill_rows:
                try:
                    det = json.loads(details_str)
                    skill_name = det.get("skill", det.get("skill_name", "unknown"))
                    skill_counter[skill_name] += 1
                    if det.get("status") == "success" or det.get("success") is True:
                        skill_success_count += 1
                except (json.JSONDecodeError, TypeError):
                    pass

            by_skill = dict(skill_counter.most_common(20))
            skill_success_rate = (
                round(skill_success_count / skill_total * 100, 1)
                if skill_total > 0
                else 0.0
            )

            # ------------------------------------------------------------------
            # Analytics events (analytics_events table)
            # ------------------------------------------------------------------
            ae_total = await _scalar(
                db,
                "SELECT COUNT(*) FROM analytics_events "
                "WHERE agent_id = ? AND created_at >= ?",
                (agent_id, period_start),
            )
            cursor = await db.execute(
                "SELECT event_type, COUNT(*) FROM analytics_events "
                "WHERE agent_id = ? AND created_at >= ? GROUP BY event_type",
                (agent_id, period_start),
            )
            ae_type_rows = await cursor.fetchall()
            by_event_type = {r[0]: r[1] for r in ae_type_rows}

            # Response time — from analytics_events metadata
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
            response_time_avg_ms = (
                round(sum(response_times) / len(response_times), 1)
                if response_times
                else 0.0
            )

    except Exception as exc:
        logger.error(
            "analytics.dashboard MCP tool failed for agent_id=%s: %s",
            agent_id,
            exc,
        )
        return err(
            action_type=action_type,
            triggered_by=triggered_by,
            message=f"Dashboard query failed: {type(exc).__name__}: {exc}",
        )

    receipt = _mcp_receipt(action_type, triggered_by, "executed")
    return ok(
        data={
            "agent_id": agent_id,
            "period_days": days,
            "conversations": {
                "total": conv_total,
                "today": conv_today,
                "trend_pct": conv_trend,
            },
            "messages": {
                "total": msg_total,
                "avg_per_conversation": msg_avg,
            },
            "skills": {
                "total_executions": skill_total,
                "by_skill": by_skill,
                "success_rate": skill_success_rate,
            },
            "analytics_events": {
                "total": ae_total,
                "by_type": by_event_type,
            },
            "response_time_avg_ms": response_time_avg_ms,
            "top_topics": top_topics,
            "active_hours": active_hours,
        },
        receipt=receipt,
    )
