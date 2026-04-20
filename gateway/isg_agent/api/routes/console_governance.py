"""Console governance endpoints — public read-only data for console.dingdawg.com.

Serves two endpoints consumed by the Operator Console frontend:
  GET /api/v1/console/governance/recent  → recent audit chain events
  GET /api/v1/console/telemetry/summary  → platform-level stat cards

Both are PUBLIC (no auth required) — they expose aggregate/anonymised
platform stats, not user-specific data.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta

import os

import aiosqlite
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

_CONSOLE_API_KEY = os.environ.get("CONSOLE_API_KEY", "")


def _check_console_key(request: Request) -> bool:
    """Return True if request carries the correct console API key."""
    if not _CONSOLE_API_KEY:
        # Key not configured — fail closed, never expose data
        return False
    provided = request.headers.get("X-Console-Key", "")
    return provided == _CONSOLE_API_KEY

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/console", tags=["console"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _relative_time(iso: str | None) -> str:
    if not iso:
        return "recently"
    try:
        ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        diff = datetime.now(timezone.utc) - ts
        secs = int(diff.total_seconds())
        if secs < 60:
            return "Just now"
        mins = secs // 60
        if mins < 60:
            return f"{mins}m ago"
        hrs = mins // 60
        if hrs < 24:
            return f"{hrs}h ago"
        days = hrs // 24
        if days < 30:
            return f"{days}d ago"
        return f"{days // 30}mo ago"
    except Exception:
        return "recently"


def _map_event_status(event_type: str, action: str) -> str:
    et = (event_type or "").lower()
    ac = (action or "").lower()
    if "block" in et or "violation" in et or "block" in ac or "deny" in ac:
        return "blocked"
    if "rollback" in et or "rollback" in ac or "revert" in ac:
        return "rollback"
    if "proof" in et or "attest" in et or "verify" in et or "audit" in et:
        return "proof"
    return "allowed"


def _truncate(s: str, n: int) -> str:
    if not s:
        return ""
    return s if len(s) <= n else s[: n - 1] + "…"


def _safe_details_title(details: str | None, event_type: str, action: str) -> str:
    """Extract a human-readable title from audit_chain details JSON."""
    if details:
        try:
            d = json.loads(details)
            # Look for common descriptive fields
            for key in ("message", "reason", "description", "summary", "task", "skill"):
                if key in d and isinstance(d[key], str) and d[key].strip():
                    return _truncate(d[key].strip(), 80)
        except Exception:
            pass
    # Fall back to event_type + action label
    label = " ".join(filter(None, [event_type, action])).replace("_", " ").title()
    return label or "Governance event"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/governance/recent")
async def governance_recent(request: Request) -> JSONResponse:
    """Return up to 10 recent audit chain events for the governance activity feed."""
    if not _check_console_key(request):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    try:
        db_path: str = request.app.state.settings.db_path
    except AttributeError:
        return JSONResponse(content=[], headers={"Cache-Control": "no-store"})

    try:
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT id, timestamp, event_type, actor, details, action, agent_id
                FROM audit_chain
                ORDER BY timestamp DESC
                LIMIT 10
                """
            )
            rows = await cursor.fetchall()
    except Exception:
        return JSONResponse(content=[], headers={"Cache-Control": "no-store"})

    items = []
    for row in rows:
        event_type = row["event_type"] or ""
        action = row["action"] or ""
        actor = row["actor"] or ""
        # Strip internal paths from actor field
        if "/home/" in actor or "Desktop" in actor:
            actor = "system"
        items.append({
            "id": f"ac-{row['id']}",
            "status": _map_event_status(event_type, action),
            "title": _safe_details_title(row["details"], event_type, action),
            "subtitle": actor or event_type.replace("_", " ") or "platform",
            "at": _relative_time(row["timestamp"]),
        })

    return JSONResponse(content=items, headers={"Cache-Control": "no-store"})


@router.get("/telemetry/summary")
async def telemetry_summary(request: Request) -> JSONResponse:
    """Return stat cards for the console dashboard stats row."""
    if not _check_console_key(request):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    try:
        db_path: str = request.app.state.settings.db_path
    except AttributeError:
        return _offline_fallback()

    try:
        async with aiosqlite.connect(db_path) as db:
            since_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

            audit_total = (await (await db.execute("SELECT COUNT(*) FROM audit_chain")).fetchone())[0]
            agents_total = (await (await db.execute("SELECT COUNT(*) FROM agents WHERE status='active'")).fetchone())[0]
            tasks_total = (await (await db.execute("SELECT COUNT(*) FROM agent_tasks")).fetchone())[0]
            audit_24h = (await (await db.execute(
                "SELECT COUNT(*) FROM audit_chain WHERE timestamp >= ?", (since_24h,)
            )).fetchone())[0]
            blocked = (await (await db.execute(
                "SELECT COUNT(*) FROM audit_chain WHERE event_type LIKE '%block%' OR action LIKE '%block%'"
            )).fetchone())[0]

    except Exception:
        return _offline_fallback()

    cards = [
        {
            "id": "audit",
            "label": "Audit Events",
            "value": str(audit_total),
            "meta": "total in chain",
            "tone": "green",
        },
        {
            "id": "agents",
            "label": "Active Agents",
            "value": str(agents_total),
            "meta": "on platform",
            "tone": "blue",
        },
        {
            "id": "tasks",
            "label": "Tasks Run",
            "value": str(tasks_total),
            "meta": "all time",
            "tone": "blue",
        },
        {
            "id": "activity",
            "label": "Activity (24h)",
            "value": str(audit_24h),
            "meta": "events today",
            "tone": "neutral" if audit_24h == 0 else "green",
        },
        {
            "id": "blocked",
            "label": "Blocked",
            "value": str(blocked),
            "meta": "governance enforced",
            "tone": "green" if blocked == 0 else "red",
        },
    ]

    return JSONResponse(content=cards, headers={"Cache-Control": "no-store"})


def _offline_fallback() -> JSONResponse:
    cards = [
        {"id": "audit",    "label": "Audit Events",   "value": "—", "meta": "connecting…", "tone": "neutral"},
        {"id": "agents",   "label": "Active Agents",  "value": "—", "meta": "connecting…", "tone": "neutral"},
        {"id": "tasks",    "label": "Tasks Run",       "value": "—", "meta": "connecting…", "tone": "neutral"},
        {"id": "activity", "label": "Activity (24h)",  "value": "—", "meta": "connecting…", "tone": "neutral"},
        {"id": "blocked",  "label": "Blocked",         "value": "—", "meta": "connecting…", "tone": "neutral"},
    ]
    return JSONResponse(content=cards, headers={"Cache-Control": "no-store"})
