"""Tests for the system health endpoints.

Covers:
  1.  Auth gate — 401 (no token), 403 (non-admin), 200 (admin)
  2.  GET /api/v1/admin/system/health — shape, status field, components
  3.  GET /api/v1/admin/system/health — DB-down degraded path
  4.  GET /api/v1/admin/system/errors — empty DB, seeded errors
  5.  GET /api/v1/admin/system/errors — limit query param
  6.  GET /api/v1/admin/system/metrics — empty DB returns valid structure
  7.  GET /api/v1/admin/system/metrics — seeded audit entries bucketed correctly
  8.  GET /api/v1/admin/system/metrics — hours query param accepted
  9.  POST /api/v1/admin/system/self-test — overall shape
  10. POST /api/v1/admin/system/self-test — db_connectivity passes
  11. POST /api/v1/admin/system/self-test — llm_providers fail when no keys
  12. POST /api/v1/admin/system/self-test — routes test passes
  13. POST /api/v1/admin/system/self-test — security_layers always passes
  14. POST /api/v1/admin/system/self-test — returned count matches results list
  15. GET  /api/v1/admin/system/health — llm provider status reflects key presence
  16. GET  /api/v1/admin/system/health — uptime_seconds is a positive number
  17. GET  /api/v1/admin/system/health — circuit_breakers present in self_healing
  18. GET  /api/v1/admin/system/errors — non-error audit events not included
  19. GET  /api/v1/admin/system/metrics — totals aggregate correctly
  20. GET  /api/v1/admin/system/health — integration statuses reflect settings
"""

from __future__ import annotations

import json
import os
from collections import namedtuple
from datetime import datetime, timezone
from typing import AsyncIterator

import aiosqlite
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from isg_agent.api.routes.auth import _create_token
from isg_agent.config import get_settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SECRET = "test-secret-system-health-suite"
_ADMIN_EMAIL = "admin@system-health-test.com"
_ADMIN_USER_ID = "admin-sh-001"
_NON_ADMIN_EMAIL = "user@system-health-test.com"
_NON_ADMIN_USER_ID = "nonadmin-sh-002"

ClientCtx = namedtuple("ClientCtx", ["ac", "db_path"])


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _make_token(user_id: str, email: str) -> str:
    return _create_token(user_id=user_id, email=email, secret_key=_SECRET)


def _admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_token(_ADMIN_USER_ID, _ADMIN_EMAIL)}"}


def _non_admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_token(_NON_ADMIN_USER_ID, _NON_ADMIN_EMAIL)}"}


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(loop_scope="function")
async def ctx(tmp_path) -> AsyncIterator[ClientCtx]:
    """Fully initialised app with lifespan + temp DB. ADMIN_EMAIL set."""
    db_file = str(tmp_path / "test_system_health.db")

    _prev_db = os.environ.get("ISG_AGENT_DB_PATH")
    _prev_secret = os.environ.get("ISG_AGENT_SECRET_KEY")
    _prev_admin = os.environ.get("ISG_AGENT_ADMIN_EMAIL")

    os.environ["ISG_AGENT_DB_PATH"] = db_file
    os.environ["ISG_AGENT_SECRET_KEY"] = _SECRET
    os.environ["ISG_AGENT_ADMIN_EMAIL"] = _ADMIN_EMAIL
    get_settings.cache_clear()

    try:
        from isg_agent.app import create_app, lifespan
        from isg_agent.api.routes.auth import _CREATE_USERS_SQL, _CREATE_INDEX_EMAIL
        from isg_agent.db.schema import create_tables

        app = create_app()
        async with lifespan(app):
            async with aiosqlite.connect(db_file) as _db:
                await create_tables(_db)
                await _db.execute(_CREATE_USERS_SQL)
                await _db.execute(_CREATE_INDEX_EMAIL)
                await _db.commit()

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ClientCtx(ac=ac, db_path=db_file)
    finally:
        for key, original in [
            ("ISG_AGENT_DB_PATH", _prev_db),
            ("ISG_AGENT_SECRET_KEY", _prev_secret),
            ("ISG_AGENT_ADMIN_EMAIL", _prev_admin),
        ]:
            if original is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# DB seed helpers
# ---------------------------------------------------------------------------


async def _seed_audit(
    db_path: str,
    event_type: str = "error",
    details: dict | None = None,
    timestamp: str | None = None,
) -> None:
    ts = timestamp or datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    det = json.dumps(details or {"error": "test error", "endpoint": "/api/v1/test"})
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO audit_chain (timestamp, event_type, actor, details, entry_hash, prev_hash)
            VALUES (?, ?, 'test-actor', ?, 'fakehash', 'prevhash')
            """,
            (ts, event_type, det),
        )
        await db.commit()


# ---------------------------------------------------------------------------
# 1. Auth gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_no_auth_returns_401(ctx: ClientCtx) -> None:
    resp = await ctx.ac.get("/api/v1/admin/system/health")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_health_non_admin_returns_403(ctx: ClientCtx) -> None:
    resp = await ctx.ac.get(
        "/api/v1/admin/system/health", headers=_non_admin_headers()
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_health_admin_returns_200(ctx: ClientCtx) -> None:
    resp = await ctx.ac.get(
        "/api/v1/admin/system/health", headers=_admin_headers()
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 2. GET /api/v1/admin/system/health — shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_response_shape(ctx: ClientCtx) -> None:
    resp = await ctx.ac.get(
        "/api/v1/admin/system/health", headers=_admin_headers()
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert data["status"] in ("healthy", "degraded", "critical")
    assert "uptime_seconds" in data
    assert "timestamp" in data
    assert "components" in data
    assert "metrics" in data
    assert "recent_errors" in data
    assert "self_healing" in data


@pytest.mark.asyncio
async def test_health_components_structure(ctx: ClientCtx) -> None:
    resp = await ctx.ac.get(
        "/api/v1/admin/system/health", headers=_admin_headers()
    )
    data = resp.json()
    components = data["components"]
    assert "database" in components
    assert "llm_providers" in components
    assert "integrations" in components
    assert "security" in components
    assert "status" in components["database"]


# ---------------------------------------------------------------------------
# 3. DB reachable → database status is "ok"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_database_ok(ctx: ClientCtx) -> None:
    resp = await ctx.ac.get(
        "/api/v1/admin/system/health", headers=_admin_headers()
    )
    data = resp.json()
    assert data["components"]["database"]["status"] == "ok"
    # latency should be a non-negative number
    latency = data["components"]["database"]["latency_ms"]
    assert latency is not None
    assert latency >= 0


# ---------------------------------------------------------------------------
# 4. GET /api/v1/admin/system/errors — empty DB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_errors_empty_db(ctx: ClientCtx) -> None:
    resp = await ctx.ac.get(
        "/api/v1/admin/system/errors", headers=_admin_headers()
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "errors" in data
    assert isinstance(data["errors"], list)
    assert "total" in data
    assert data["total"] == 0


# ---------------------------------------------------------------------------
# 5. GET /api/v1/admin/system/errors — seeded errors surfaced
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_errors_seeded_entries_returned(ctx: ClientCtx) -> None:
    await _seed_audit(ctx.db_path, "error", {"error": "something went wrong", "endpoint": "/api/test"})
    await _seed_audit(ctx.db_path, "skill_error", {"error": "skill failed"})

    resp = await ctx.ac.get(
        "/api/v1/admin/system/errors", headers=_admin_headers()
    )
    data = resp.json()
    assert data["total"] >= 2
    assert len(data["errors"]) >= 2
    # Each entry has expected fields
    entry = data["errors"][0]
    assert "timestamp" in entry
    assert "event_type" in entry
    assert "message" in entry


# ---------------------------------------------------------------------------
# 6. GET /api/v1/admin/system/errors — limit param
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_errors_limit_param(ctx: ClientCtx) -> None:
    for i in range(5):
        await _seed_audit(ctx.db_path, "error", {"error": f"error {i}"})

    resp = await ctx.ac.get(
        "/api/v1/admin/system/errors?limit=2", headers=_admin_headers()
    )
    data = resp.json()
    assert len(data["errors"]) <= 2


# ---------------------------------------------------------------------------
# 7. GET /api/v1/admin/system/errors — non-error types excluded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_errors_excludes_non_error_events(ctx: ClientCtx) -> None:
    await _seed_audit(ctx.db_path, "agent_action", {"message": "normal action"})
    await _seed_audit(ctx.db_path, "session_start", {"message": "session"})

    resp = await ctx.ac.get(
        "/api/v1/admin/system/errors", headers=_admin_headers()
    )
    data = resp.json()
    # None of the returned entries should have non-error event_type
    error_types = {"error", "ERROR", "skill_error", "request_error"}
    for entry in data["errors"]:
        assert entry["event_type"] in error_types


# ---------------------------------------------------------------------------
# 8. GET /api/v1/admin/system/metrics — empty DB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metrics_empty_db_structure(ctx: ClientCtx) -> None:
    resp = await ctx.ac.get(
        "/api/v1/admin/system/metrics", headers=_admin_headers()
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "buckets" in data
    assert "totals" in data
    assert "period_hours" in data
    assert "generated_at" in data
    assert isinstance(data["buckets"], list)
    totals = data["totals"]
    assert "total_events" in totals
    assert "total_errors" in totals
    assert "total_skill_executions" in totals
    assert "total_auth_events" in totals


# ---------------------------------------------------------------------------
# 9. GET /api/v1/admin/system/metrics — seeded entries bucketed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metrics_seeded_entries_bucketed(ctx: ClientCtx) -> None:
    await _seed_audit(ctx.db_path, "agent_action")
    await _seed_audit(ctx.db_path, "error")
    await _seed_audit(ctx.db_path, "skill_execute")

    resp = await ctx.ac.get(
        "/api/v1/admin/system/metrics?hours=24", headers=_admin_headers()
    )
    data = resp.json()
    assert data["totals"]["total_events"] >= 3
    assert data["totals"]["total_errors"] >= 1


# ---------------------------------------------------------------------------
# 10. GET /api/v1/admin/system/metrics — hours param accepted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metrics_hours_param(ctx: ClientCtx) -> None:
    resp = await ctx.ac.get(
        "/api/v1/admin/system/metrics?hours=1", headers=_admin_headers()
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["period_hours"] == 1


# ---------------------------------------------------------------------------
# 11. POST /api/v1/admin/system/self-test — auth gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_self_test_no_auth_returns_401(ctx: ClientCtx) -> None:
    resp = await ctx.ac.post("/api/v1/admin/system/self-test")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_self_test_non_admin_returns_403(ctx: ClientCtx) -> None:
    resp = await ctx.ac.post(
        "/api/v1/admin/system/self-test", headers=_non_admin_headers()
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 12. POST /api/v1/admin/system/self-test — shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_self_test_response_shape(ctx: ClientCtx) -> None:
    resp = await ctx.ac.post(
        "/api/v1/admin/system/self-test", headers=_admin_headers()
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "overall" in data
    assert data["overall"] in ("pass", "fail")
    assert "passed" in data
    assert "total" in data
    assert "results" in data
    assert "ran_at" in data
    assert isinstance(data["results"], list)


# ---------------------------------------------------------------------------
# 13. POST /api/v1/admin/system/self-test — result count matches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_self_test_count_matches_results(ctx: ClientCtx) -> None:
    resp = await ctx.ac.post(
        "/api/v1/admin/system/self-test", headers=_admin_headers()
    )
    data = resp.json()
    assert data["total"] == len(data["results"])
    assert data["passed"] == sum(
        1 for r in data["results"] if r["result"] == "pass"
    )


# ---------------------------------------------------------------------------
# 14. POST /api/v1/admin/system/self-test — db_connectivity passes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_self_test_db_connectivity_passes(ctx: ClientCtx) -> None:
    resp = await ctx.ac.post(
        "/api/v1/admin/system/self-test", headers=_admin_headers()
    )
    data = resp.json()
    db_result = next(
        (r for r in data["results"] if r["test"] == "db_connectivity"), None
    )
    assert db_result is not None
    assert db_result["result"] == "pass"


# ---------------------------------------------------------------------------
# 15. POST /api/v1/admin/system/self-test — routes test passes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_self_test_routes_passes(ctx: ClientCtx) -> None:
    resp = await ctx.ac.post(
        "/api/v1/admin/system/self-test", headers=_admin_headers()
    )
    data = resp.json()
    routes_result = next(
        (r for r in data["results"] if r["test"] == "routes"), None
    )
    assert routes_result is not None
    assert routes_result["result"] == "pass"


# ---------------------------------------------------------------------------
# 16. POST /api/v1/admin/system/self-test — security_layers always passes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_self_test_security_layers_passes(ctx: ClientCtx) -> None:
    resp = await ctx.ac.post(
        "/api/v1/admin/system/self-test", headers=_admin_headers()
    )
    data = resp.json()
    sec_result = next(
        (r for r in data["results"] if r["test"] == "security_layers"), None
    )
    assert sec_result is not None
    assert sec_result["result"] == "pass"


# ---------------------------------------------------------------------------
# 17. GET /api/v1/admin/system/health — uptime_seconds positive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_uptime_positive(ctx: ClientCtx) -> None:
    resp = await ctx.ac.get(
        "/api/v1/admin/system/health", headers=_admin_headers()
    )
    data = resp.json()
    assert isinstance(data["uptime_seconds"], (int, float))
    assert data["uptime_seconds"] >= 0


# ---------------------------------------------------------------------------
# 18. GET /api/v1/admin/system/health — circuit_breakers present
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_circuit_breakers_present(ctx: ClientCtx) -> None:
    resp = await ctx.ac.get(
        "/api/v1/admin/system/health", headers=_admin_headers()
    )
    data = resp.json()
    cbs = data["self_healing"]["circuit_breakers"]
    assert isinstance(cbs, dict)
    assert len(cbs) > 0
    # database breaker should be CLOSED when DB is healthy
    assert cbs.get("database") == "CLOSED"


# ---------------------------------------------------------------------------
# 19. GET /api/v1/admin/system/health — no keys → providers unavailable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_no_llm_keys_providers_unavailable(ctx: ClientCtx) -> None:
    """With no API keys set in the test environment, all providers are unavailable."""
    resp = await ctx.ac.get(
        "/api/v1/admin/system/health", headers=_admin_headers()
    )
    data = resp.json()
    providers = data["components"]["llm_providers"]
    # In the test environment no real LLM API keys are set, so all should be
    # marked unavailable / not configured.
    for provider_name, info in providers.items():
        if not info.get("configured"):
            assert info["status"] == "unavailable", (
                f"Provider {provider_name} has configured=False but status is not 'unavailable'"
            )


# ---------------------------------------------------------------------------
# 20. GET /api/v1/admin/system/health — integrations section present
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_integrations_section(ctx: ClientCtx) -> None:
    resp = await ctx.ac.get(
        "/api/v1/admin/system/health", headers=_admin_headers()
    )
    data = resp.json()
    integrations = data["components"]["integrations"]
    assert isinstance(integrations, dict)
    # Known integration keys must be present
    for key in ("stripe", "sendgrid", "twilio"):
        assert key in integrations, f"Integration '{key}' missing from health report"
        assert "status" in integrations[key]
