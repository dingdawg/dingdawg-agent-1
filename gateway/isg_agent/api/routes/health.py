"""Health check and system status endpoints."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

import aiosqlite
from fastapi import APIRouter, Request, Response, status

__all__ = ["router"]

router = APIRouter(prefix="/api/v1", tags=["health"])

_START_TIME = time.monotonic()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uptime_seconds() -> float:
    return round(time.monotonic() - _START_TIME, 3)


def _get_database_path(request: Request) -> str:
    state = getattr(request.app, "state", None)
    if state is not None:
        for attr_name in ("database_path", "db_path", "sqlite_path"):
            value = getattr(state, attr_name, None)
            if isinstance(value, str) and value.strip():
                return value
    return os.getenv("DATABASE_URL") or os.getenv("SQLITE_PATH") or "data/app.db"


async def _check_sqlite(db_path: str) -> dict[str, Any]:
    started = time.monotonic()
    try:
        async with aiosqlite.connect(db_path, timeout=2.0) as db:
            await db.execute("PRAGMA quick_check;")
            cursor = await db.execute("SELECT 1;")
            row = await cursor.fetchone()
            await cursor.close()

        latency_ms = round((time.monotonic() - started) * 1000, 2)
        return {
            "status": "pass" if row and row[0] == 1 else "fail",
            "latency_ms": latency_ms,
        }
    except Exception as exc:
        latency_ms = round((time.monotonic() - started) * 1000, 2)
        return {
            "status": "fail",
            "latency_ms": latency_ms,
            "error": exc.__class__.__name__,
        }


@router.get("/live", status_code=status.HTTP_200_OK)
async def liveness() -> dict[str, Any]:
    return {
        "status": "pass",
        "service": "isg-agent",
        "timestamp": _utcnow_iso(),
        "uptime_seconds": _uptime_seconds(),
    }


@router.get("/ready")
async def readiness(request: Request, response: Response) -> dict[str, Any]:
    db_path = _get_database_path(request)
    sqlite_check = await _check_sqlite(db_path)

    overall_status = "pass" if sqlite_check["status"] == "pass" else "fail"
    response.status_code = (
        status.HTTP_200_OK
        if overall_status == "pass"
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )

    return {
        "status": overall_status,
        "service": "isg-agent",
        "timestamp": _utcnow_iso(),
        "uptime_seconds": _uptime_seconds(),
        "checks": {
            "database": sqlite_check,
        },
    }


@router.get("/health")
async def health_check(request: Request, response: Response) -> dict[str, Any]:
    db_path = _get_database_path(request)
    sqlite_check = await _check_sqlite(db_path)

    overall_status = "pass" if sqlite_check["status"] == "pass" else "fail"
    response.status_code = (
        status.HTTP_200_OK
        if overall_status == "pass"
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )

    return {
        "status": overall_status,
        "service": "isg-agent",
        "version": getattr(request.app, "version", "unknown"),
        "timestamp": _utcnow_iso(),
        "uptime_seconds": _uptime_seconds(),
        "checks": {
            "database": sqlite_check,
        },
    }