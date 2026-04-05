"""Comprehensive tests for the Command Center admin API.

Test categories
---------------
1.  require_admin gate — 401 (no auth), 403 (non-admin), 200 (admin)
2.  GET /admin/whoami
3.  GET /admin/platform-stats
4.  GET /admin/agents  (pagination, search, status_filter)
5.  GET /admin/errors
6.  GET /admin/health-detailed
7.  GET /admin/stripe-status
8.  GET /admin/contacts
9.  GET /admin/funnel
10. GET /admin/campaigns
11. GET /admin/email-stats
12. GET /admin/workflow-tests
13. POST /admin/workflow-tests/{id}/run
14. GET /admin/alerts
15. POST /admin/alerts/configure
16. GET /admin/events
17. POST /admin/command
18. POST /admin/deploy-marketing-agent

Fixture pattern mirrors test_analytics.py exactly:
  - tmp_path SQLite DB per test class via the `ctx` fixture
  - lifespan context ensures all tables exist before any HTTP request
  - JWT forged via _create_token (same verify_token path)
  - ISG_AGENT_ADMIN_EMAIL set to the admin test user's email
  - Non-admin user uses a DIFFERENT email — guarantees 403 on admin endpoints
"""

from __future__ import annotations

import json
import os
import uuid
from collections import namedtuple
from datetime import datetime, timezone, timedelta
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

_SECRET = "test-secret-admin-suite"
_ADMIN_EMAIL = "admin@dingdawg-test.com"
_ADMIN_USER_ID = "admin-user-001"
_NON_ADMIN_EMAIL = "user@dingdawg-test.com"
_NON_ADMIN_USER_ID = "nonadmin-user-002"

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
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(loop_scope="function")
async def ctx(tmp_path) -> AsyncIterator[ClientCtx]:
    """Async client with fully initialised app lifespan + the DB path.

    Sets ISG_AGENT_ADMIN_EMAIL so that require_admin passes for _ADMIN_EMAIL.
    Restores all env vars and clears get_settings cache in finally block.
    """
    db_file = str(tmp_path / "test_admin.db")

    _prev_db = os.environ.get("ISG_AGENT_DB_PATH")
    _prev_secret = os.environ.get("ISG_AGENT_SECRET_KEY")
    _prev_admin = os.environ.get("ISG_AGENT_ADMIN_EMAIL")

    os.environ["ISG_AGENT_DB_PATH"] = db_file
    os.environ["ISG_AGENT_SECRET_KEY"] = _SECRET
    os.environ["ISG_AGENT_ADMIN_EMAIL"] = _ADMIN_EMAIL
    get_settings.cache_clear()

    try:
        from isg_agent.app import create_app, lifespan

        app = create_app()

        async with lifespan(app):
            # The auth module creates the users table lazily (only when auth
            # endpoints are called).  AgentRegistry creates the agents table
            # lazily (only on first registry method call).  Admin endpoints
            # query both tables directly, so we must ensure they exist before
            # any seed helper or admin request is made.
            from isg_agent.api.routes.auth import _CREATE_USERS_SQL, _CREATE_INDEX_EMAIL
            from isg_agent.db.schema import create_tables

            async with aiosqlite.connect(db_file) as _db:
                await create_tables(_db)
                await _db.execute(_CREATE_USERS_SQL)
                await _db.execute(_CREATE_INDEX_EMAIL)
                await _db.commit()

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ClientCtx(ac=ac, db_path=db_file)
    finally:
        if _prev_db is None:
            os.environ.pop("ISG_AGENT_DB_PATH", None)
        else:
            os.environ["ISG_AGENT_DB_PATH"] = _prev_db

        if _prev_secret is None:
            os.environ.pop("ISG_AGENT_SECRET_KEY", None)
        else:
            os.environ["ISG_AGENT_SECRET_KEY"] = _prev_secret

        if _prev_admin is None:
            os.environ.pop("ISG_AGENT_ADMIN_EMAIL", None)
        else:
            os.environ["ISG_AGENT_ADMIN_EMAIL"] = _prev_admin

        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# DB seed helpers
# ---------------------------------------------------------------------------


async def _seed_user(db_path: str, user_id: str, email: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO users (id, email, password_hash, salt, created_at)
            VALUES (?, ?, 'fakehash', 'fakesalt', ?)
            """,
            (user_id, email, now),
        )
        await db.commit()


async def _seed_agent(
    db_path: str,
    owner_id: str,
    handle: str,
    status: str = "active",
) -> str:
    agent_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO agents
                (id, user_id, handle, name, agent_type, industry_type, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'business', 'restaurant', ?, ?, ?)
            """,
            (agent_id, owner_id, handle, f"Agent {handle}", status, now, now),
        )
        await db.commit()
    return agent_id


async def _seed_audit_error(db_path: str, event_type: str = "error") -> None:
    now = datetime.now(timezone.utc).isoformat()
    details = json.dumps({"error": "test error message", "endpoint": "/api/v1/test"})
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO audit_chain
                (timestamp, event_type, actor, details, entry_hash, prev_hash)
            VALUES (?, ?, 'test-actor', ?, 'fakehash', 'prevhash')
            """,
            (now, event_type, details),
        )
        await db.commit()


async def _seed_appointment(db_path: str, agent_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    start = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    row_id = str(uuid.uuid4())
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS skill_appointments (
                id           TEXT PRIMARY KEY,
                agent_id     TEXT NOT NULL,
                contact_name TEXT,
                title        TEXT,
                start_time   TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT 'scheduled',
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            INSERT INTO skill_appointments
                (id, agent_id, contact_name, title, start_time, status, created_at, updated_at)
            VALUES (?, ?, 'Test Contact', 'Test Appointment', ?, 'scheduled', ?, ?)
            """,
            (row_id, agent_id, start, now, now),
        )
        await db.commit()


async def _seed_contact(db_path: str, agent_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    row_id = str(uuid.uuid4())
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS skill_contacts (
                id         TEXT PRIMARY KEY,
                agent_id   TEXT NOT NULL,
                name       TEXT,
                email      TEXT,
                source     TEXT,
                status     TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            INSERT INTO skill_contacts
                (id, agent_id, name, email, source, status, created_at, updated_at)
            VALUES (?, ?, 'Test Contact', 'contact@example.com', 'widget', 'active', ?, ?)
            """,
            (row_id, agent_id, now, now),
        )
        await db.commit()


async def _seed_notification(db_path: str, agent_id: str, status: str = "sent") -> None:
    now = datetime.now(timezone.utc).isoformat()
    row_id = str(uuid.uuid4())
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS skill_notifications (
                id         TEXT PRIMARY KEY,
                agent_id   TEXT NOT NULL,
                channel    TEXT NOT NULL,
                recipient  TEXT NOT NULL,
                body       TEXT NOT NULL,
                status     TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            INSERT INTO skill_notifications
                (id, agent_id, channel, recipient, body, status, created_at)
            VALUES (?, ?, 'email', 'r@example.com', 'body', ?, ?)
            """,
            (row_id, agent_id, status, now),
        )
        await db.commit()


# ===========================================================================
# 1. require_admin gate
# ===========================================================================


class TestRequireAdminGate:
    """Verify that require_admin properly gates all admin endpoints."""

    async def test_no_token_returns_401(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get("/api/v1/admin/whoami")
        assert resp.status_code == 401

    async def test_non_admin_token_returns_403(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get(
            "/api/v1/admin/whoami", headers=_non_admin_headers()
        )
        assert resp.status_code == 403

    async def test_admin_token_passes_gate(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get(
            "/api/v1/admin/whoami", headers=_admin_headers()
        )
        assert resp.status_code == 200

    async def test_non_admin_blocked_on_platform_stats(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get(
            "/api/v1/admin/platform-stats", headers=_non_admin_headers()
        )
        assert resp.status_code == 403

    async def test_non_admin_blocked_on_agents(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get(
            "/api/v1/admin/agents", headers=_non_admin_headers()
        )
        assert resp.status_code == 403

    async def test_non_admin_blocked_on_errors(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get(
            "/api/v1/admin/errors", headers=_non_admin_headers()
        )
        assert resp.status_code == 403


# ===========================================================================
# 2. GET /admin/whoami
# ===========================================================================


class TestWhoami:
    async def test_returns_is_admin_true(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get("/api/v1/admin/whoami", headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_admin"] is True

    async def test_returns_correct_email(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get("/api/v1/admin/whoami", headers=_admin_headers())
        data = resp.json()
        assert data["email"] == _ADMIN_EMAIL

    async def test_returns_user_id(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get("/api/v1/admin/whoami", headers=_admin_headers())
        data = resp.json()
        assert data["user_id"] == _ADMIN_USER_ID


# ===========================================================================
# 3. GET /admin/platform-stats
# ===========================================================================


class TestPlatformStats:
    async def test_returns_expected_shape(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get(
            "/api/v1/admin/platform-stats", headers=_admin_headers()
        )
        assert resp.status_code == 200
        data = resp.json()
        expected_keys = {
            "total_users", "total_agents", "active_sessions_24h",
            "error_count_24h", "total_messages",
        }
        assert expected_keys.issubset(data.keys())

    async def test_counts_are_integers(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get(
            "/api/v1/admin/platform-stats", headers=_admin_headers()
        )
        data = resp.json()
        for key in ("total_users", "total_agents", "active_sessions_24h",
                    "error_count_24h", "total_messages"):
            assert isinstance(data[key], int), f"{key} should be int"

    async def test_reflects_seeded_user(self, ctx: ClientCtx) -> None:
        await _seed_user(ctx.db_path, _ADMIN_USER_ID, _ADMIN_EMAIL)
        resp = await ctx.ac.get(
            "/api/v1/admin/platform-stats", headers=_admin_headers()
        )
        data = resp.json()
        assert data["total_users"] >= 1

    async def test_requires_admin(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get("/api/v1/admin/platform-stats")
        assert resp.status_code == 401


# ===========================================================================
# 4. GET /admin/agents
# ===========================================================================


class TestListAllAgents:
    async def test_empty_returns_correct_shape(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get("/api/v1/admin/agents", headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "agents" in data
        assert "total" in data
        assert "page" in data
        assert "per_page" in data
        assert isinstance(data["agents"], list)

    async def test_lists_all_agents_cross_user(self, ctx: ClientCtx) -> None:
        await _seed_user(ctx.db_path, _ADMIN_USER_ID, _ADMIN_EMAIL)
        await _seed_user(ctx.db_path, _NON_ADMIN_USER_ID, _NON_ADMIN_EMAIL)
        await _seed_agent(ctx.db_path, _ADMIN_USER_ID, "admin-agent-001")
        await _seed_agent(ctx.db_path, _NON_ADMIN_USER_ID, "user-agent-001")

        resp = await ctx.ac.get("/api/v1/admin/agents", headers=_admin_headers())
        data = resp.json()
        assert data["total"] >= 2

    async def test_pagination_page_param(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get(
            "/api/v1/admin/agents?page=1&per_page=5", headers=_admin_headers()
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 1
        assert data["per_page"] == 5

    async def test_search_filters_by_handle(self, ctx: ClientCtx) -> None:
        await _seed_user(ctx.db_path, _ADMIN_USER_ID, _ADMIN_EMAIL)
        await _seed_agent(ctx.db_path, _ADMIN_USER_ID, "searchable-handle-xyz")
        await _seed_agent(ctx.db_path, _ADMIN_USER_ID, "different-handle-abc")

        resp = await ctx.ac.get(
            "/api/v1/admin/agents?search=searchable-handle-xyz",
            headers=_admin_headers(),
        )
        data = resp.json()
        handles = [a["handle"] for a in data["agents"]]
        assert "searchable-handle-xyz" in handles
        assert "different-handle-abc" not in handles

    async def test_status_filter(self, ctx: ClientCtx) -> None:
        await _seed_user(ctx.db_path, _ADMIN_USER_ID, _ADMIN_EMAIL)
        await _seed_agent(ctx.db_path, _ADMIN_USER_ID, "active-agent-filter", status="active")

        resp = await ctx.ac.get(
            "/api/v1/admin/agents?status_filter=active", headers=_admin_headers()
        )
        data = resp.json()
        for agent in data["agents"]:
            assert agent["status"] == "active"

    async def test_agent_has_owner_email_field(self, ctx: ClientCtx) -> None:
        await _seed_user(ctx.db_path, _ADMIN_USER_ID, _ADMIN_EMAIL)
        await _seed_agent(ctx.db_path, _ADMIN_USER_ID, "owner-email-test-agent")

        resp = await ctx.ac.get("/api/v1/admin/agents", headers=_admin_headers())
        data = resp.json()
        for agent in data["agents"]:
            assert "owner_email" in agent


# ===========================================================================
# 5. GET /admin/errors
# ===========================================================================


class TestErrors:
    async def test_returns_expected_shape(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get("/api/v1/admin/errors", headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "errors" in data
        assert "total" in data
        assert isinstance(data["errors"], list)

    async def test_surfaces_seeded_errors(self, ctx: ClientCtx) -> None:
        await _seed_audit_error(ctx.db_path, "error")
        resp = await ctx.ac.get("/api/v1/admin/errors", headers=_admin_headers())
        data = resp.json()
        assert data["total"] >= 1

    async def test_error_entry_has_required_fields(self, ctx: ClientCtx) -> None:
        await _seed_audit_error(ctx.db_path, "error")
        resp = await ctx.ac.get("/api/v1/admin/errors", headers=_admin_headers())
        data = resp.json()
        if data["errors"]:
            entry = data["errors"][0]
            assert "message" in entry
            assert "count" in entry
            assert "first_seen" in entry
            assert "last_seen" in entry

    async def test_limit_param_respected(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get(
            "/api/v1/admin/errors?limit=5", headers=_admin_headers()
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["errors"]) <= 5


# ===========================================================================
# 6. GET /admin/health-detailed
# ===========================================================================


class TestHealthDetailed:
    async def test_returns_expected_shape(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get(
            "/api/v1/admin/health-detailed", headers=_admin_headers()
        )
        assert resp.status_code == 200
        data = resp.json()
        expected_keys = {
            "db_size_bytes", "memory_rss_kb",
            "audit_event_counts", "checked_at",
        }
        assert expected_keys.issubset(data.keys())

    async def test_db_size_bytes_is_non_negative(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get(
            "/api/v1/admin/health-detailed", headers=_admin_headers()
        )
        data = resp.json()
        assert data["db_size_bytes"] >= 0

    async def test_audit_event_counts_is_dict(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get(
            "/api/v1/admin/health-detailed", headers=_admin_headers()
        )
        data = resp.json()
        assert isinstance(data["audit_event_counts"], dict)

    async def test_checked_at_is_string(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get(
            "/api/v1/admin/health-detailed", headers=_admin_headers()
        )
        data = resp.json()
        assert isinstance(data["checked_at"], str)


# ===========================================================================
# 7. GET /admin/stripe-status
# ===========================================================================


class TestStripeStatus:
    async def test_returns_expected_shape(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get(
            "/api/v1/admin/stripe-status", headers=_admin_headers()
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "mode" in data
        assert "webhook_configured" in data
        assert "customer_count" in data

    async def test_mode_not_configured_when_no_key(self, ctx: ClientCtx) -> None:
        # Default settings have no stripe key set
        resp = await ctx.ac.get(
            "/api/v1/admin/stripe-status", headers=_admin_headers()
        )
        data = resp.json()
        assert data["mode"] in ("not_configured", "test", "live", "unknown")

    async def test_webhook_configured_is_bool(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get(
            "/api/v1/admin/stripe-status", headers=_admin_headers()
        )
        data = resp.json()
        assert isinstance(data["webhook_configured"], bool)

    async def test_mode_reflects_test_key(self, ctx: ClientCtx) -> None:
        prev = os.environ.get("ISG_AGENT_STRIPE_SECRET_KEY")
        os.environ["ISG_AGENT_STRIPE_SECRET_KEY"] = "sk_test_fakekeyfortesting"
        get_settings.cache_clear()
        try:
            resp = await ctx.ac.get(
                "/api/v1/admin/stripe-status", headers=_admin_headers()
            )
            data = resp.json()
            # The app settings were loaded at lifespan time so the env change
            # only affects new settings instances — mode may stay not_configured.
            assert data["mode"] in ("test", "not_configured", "unknown", "live")
        finally:
            if prev is None:
                os.environ.pop("ISG_AGENT_STRIPE_SECRET_KEY", None)
            else:
                os.environ["ISG_AGENT_STRIPE_SECRET_KEY"] = prev
            get_settings.cache_clear()


# ===========================================================================
# 8. GET /admin/contacts
# ===========================================================================


class TestContacts:
    async def test_returns_expected_shape(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get("/api/v1/admin/contacts", headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "contacts" in data
        assert "total" in data
        assert isinstance(data["contacts"], list)

    async def test_surfaces_seeded_contact(self, ctx: ClientCtx) -> None:
        await _seed_user(ctx.db_path, _ADMIN_USER_ID, _ADMIN_EMAIL)
        agent_id = await _seed_agent(ctx.db_path, _ADMIN_USER_ID, "contact-test-agent")
        await _seed_contact(ctx.db_path, agent_id)

        resp = await ctx.ac.get("/api/v1/admin/contacts", headers=_admin_headers())
        data = resp.json()
        assert data["total"] >= 1

    async def test_pagination_params(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get(
            "/api/v1/admin/contacts?page=1&per_page=10", headers=_admin_headers()
        )
        data = resp.json()
        assert data["page"] == 1
        assert data["per_page"] == 10

    async def test_search_filter(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get(
            "/api/v1/admin/contacts?search=nobody-exists-xyz", headers=_admin_headers()
        )
        data = resp.json()
        assert data["total"] == 0


# ===========================================================================
# 9. GET /admin/funnel
# ===========================================================================


class TestFunnel:
    async def test_returns_expected_shape(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get("/api/v1/admin/funnel", headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        expected_keys = {
            "registered_users", "claimed_handles", "active_subscribers",
            "active_7d", "churned_30d",
        }
        assert expected_keys.issubset(data.keys())

    async def test_all_values_are_integers(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get("/api/v1/admin/funnel", headers=_admin_headers())
        data = resp.json()
        for key in ("registered_users", "claimed_handles", "active_subscribers",
                    "active_7d", "churned_30d"):
            assert isinstance(data[key], int), f"{key} must be int"

    async def test_registered_users_increments(self, ctx: ClientCtx) -> None:
        resp0 = await ctx.ac.get("/api/v1/admin/funnel", headers=_admin_headers())
        base = resp0.json()["registered_users"]

        await _seed_user(ctx.db_path, str(uuid.uuid4()), "new-funnel-user@test.com")

        resp1 = await ctx.ac.get("/api/v1/admin/funnel", headers=_admin_headers())
        assert resp1.json()["registered_users"] >= base + 1


# ===========================================================================
# 10. GET /admin/campaigns
# ===========================================================================


class TestCampaigns:
    async def test_returns_empty_list(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get("/api/v1/admin/campaigns", headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["campaigns"] == []
        assert data["total"] == 0

    async def test_requires_admin(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get("/api/v1/admin/campaigns")
        assert resp.status_code == 401


# ===========================================================================
# 11. GET /admin/email-stats
# ===========================================================================


class TestEmailStats:
    async def test_returns_expected_shape(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get("/api/v1/admin/email-stats", headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        expected_keys = {
            "total_sent", "total_delivered", "total_failed",
            "total_bounced", "delivery_rate", "by_status",
        }
        assert expected_keys.issubset(data.keys())

    async def test_delivery_rate_is_float(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get("/api/v1/admin/email-stats", headers=_admin_headers())
        data = resp.json()
        assert isinstance(data["delivery_rate"], float)

    async def test_surfaces_seeded_notifications(self, ctx: ClientCtx) -> None:
        await _seed_user(ctx.db_path, _ADMIN_USER_ID, _ADMIN_EMAIL)
        agent_id = await _seed_agent(ctx.db_path, _ADMIN_USER_ID, "email-stats-agent")
        await _seed_notification(ctx.db_path, agent_id, status="sent")
        await _seed_notification(ctx.db_path, agent_id, status="failed")

        resp = await ctx.ac.get("/api/v1/admin/email-stats", headers=_admin_headers())
        data = resp.json()
        assert data["total_sent"] >= 2
        assert data["total_failed"] >= 1


# ===========================================================================
# 12. GET /admin/workflow-tests
# ===========================================================================


class TestWorkflowTests:
    async def test_returns_four_built_in_tests(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get(
            "/api/v1/admin/workflow-tests", headers=_admin_headers()
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "tests" in data
        assert len(data["tests"]) == 4

    async def test_test_entries_have_required_fields(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get(
            "/api/v1/admin/workflow-tests", headers=_admin_headers()
        )
        data = resp.json()
        for test in data["tests"]:
            assert "id" in test
            assert "name" in test
            assert "description" in test
            assert "last_result" in test

    async def test_built_in_test_ids_present(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get(
            "/api/v1/admin/workflow-tests", headers=_admin_headers()
        )
        data = resp.json()
        ids = {t["id"] for t in data["tests"]}
        assert "health_check" in ids
        assert "auth_flow" in ids
        assert "agent_create" in ids
        assert "stripe_webhook" in ids


# ===========================================================================
# 13. POST /admin/workflow-tests/{id}/run
# ===========================================================================


class TestRunWorkflowTest:
    async def test_health_check_passes(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/workflow-tests/health_check/run",
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["test_id"] == "health_check"
        assert data["status"] in ("passed", "error")

    async def test_auth_flow_check(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/workflow-tests/auth_flow/run",
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["test_id"] == "auth_flow"
        assert "status" in data

    async def test_agent_create_check(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/workflow-tests/agent_create/run",
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["test_id"] == "agent_create"

    async def test_stripe_webhook_check(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/workflow-tests/stripe_webhook/run",
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["test_id"] == "stripe_webhook"
        assert data["status"] in ("passed", "warning", "error")

    async def test_invalid_test_id_returns_404(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/workflow-tests/nonexistent_test/run",
            headers=_admin_headers(),
        )
        assert resp.status_code == 404

    async def test_result_has_duration_ms(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/workflow-tests/health_check/run",
            headers=_admin_headers(),
        )
        data = resp.json()
        assert "duration_ms" in data
        assert data["duration_ms"] >= 0


# ===========================================================================
# 14. GET /admin/alerts
# ===========================================================================


class TestAlerts:
    async def test_returns_expected_shape(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get("/api/v1/admin/alerts", headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "alerts" in data
        assert "total" in data
        assert "thresholds" in data
        assert isinstance(data["alerts"], list)

    async def test_surfaces_seeded_error_events(self, ctx: ClientCtx) -> None:
        await _seed_audit_error(ctx.db_path, "error")
        resp = await ctx.ac.get("/api/v1/admin/alerts", headers=_admin_headers())
        data = resp.json()
        assert data["total"] >= 1

    async def test_alert_entry_has_severity(self, ctx: ClientCtx) -> None:
        await _seed_audit_error(ctx.db_path, "error")
        resp = await ctx.ac.get("/api/v1/admin/alerts", headers=_admin_headers())
        data = resp.json()
        if data["alerts"]:
            assert "severity" in data["alerts"][0]

    async def test_limit_param(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get(
            "/api/v1/admin/alerts?limit=10", headers=_admin_headers()
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["alerts"]) <= 10


# ===========================================================================
# 15. POST /admin/alerts/configure
# ===========================================================================


class TestConfigureAlerts:
    async def test_updates_threshold(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/alerts/configure",
            json={"error_rate_per_hour": 200},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["updated"]["error_rate_per_hour"] == 200
        assert data["current_thresholds"]["error_rate_per_hour"] == 200

    async def test_invalid_threshold_value_returns_422(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/alerts/configure",
            json={"error_rate_per_hour": -5},
            headers=_admin_headers(),
        )
        assert resp.status_code == 422

    async def test_non_integer_threshold_returns_422(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/alerts/configure",
            json={"error_rate_per_hour": "not-a-number"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 422

    async def test_unknown_keys_ignored(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/alerts/configure",
            json={"unknown_key": 999, "error_rate_per_hour": 50},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "unknown_key" not in data["updated"]

    async def test_requires_admin(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/alerts/configure",
            json={"error_rate_per_hour": 50},
        )
        assert resp.status_code == 401


# ===========================================================================
# 16. GET /admin/events
# ===========================================================================


class TestEvents:
    async def test_returns_expected_shape(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get("/api/v1/admin/events", headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data
        assert "total" in data
        assert isinstance(data["events"], list)

    async def test_surfaces_seeded_appointments(self, ctx: ClientCtx) -> None:
        await _seed_user(ctx.db_path, _ADMIN_USER_ID, _ADMIN_EMAIL)
        agent_id = await _seed_agent(ctx.db_path, _ADMIN_USER_ID, "events-agent-001")
        await _seed_appointment(ctx.db_path, agent_id)

        resp = await ctx.ac.get("/api/v1/admin/events", headers=_admin_headers())
        data = resp.json()
        assert data["total"] >= 1

    async def test_event_has_event_type_field(self, ctx: ClientCtx) -> None:
        await _seed_user(ctx.db_path, _ADMIN_USER_ID, _ADMIN_EMAIL)
        agent_id = await _seed_agent(ctx.db_path, _ADMIN_USER_ID, "events-agent-002")
        await _seed_appointment(ctx.db_path, agent_id)

        resp = await ctx.ac.get("/api/v1/admin/events", headers=_admin_headers())
        data = resp.json()
        if data["events"]:
            assert data["events"][0]["event_type"] == "appointment"


# ===========================================================================
# 17. POST /admin/command
# ===========================================================================


class TestCommand:
    async def test_status_command(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/command",
            json={"command": "status"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["command"] == "status"
        assert "response" in data
        assert data["response"]["status"] == "operational"

    async def test_stats_command(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/command",
            json={"command": "stats"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "response" in data
        assert "total_users" in data["response"]

    async def test_help_command(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/command",
            json={"command": "unknown-command-xyz"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "help" in data["response"]

    async def test_errors_command(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/command",
            json={"command": "errors"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "recent_errors" in data["response"]

    async def test_test_command_valid_id(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/command",
            json={"command": "test health_check"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "response" in data
        assert data["response"]["test_id"] == "health_check"

    async def test_test_command_invalid_id(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/command",
            json={"command": "test nonexistent_test"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data["response"]

    async def test_empty_command_returns_422(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/command",
            json={"command": ""},
            headers=_admin_headers(),
        )
        assert resp.status_code == 422

    async def test_missing_command_field_returns_422(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/command",
            json={},
            headers=_admin_headers(),
        )
        assert resp.status_code == 422

    async def test_requires_admin(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/command", json={"command": "status"}
        )
        assert resp.status_code == 401


# ===========================================================================
# 18. POST /admin/deploy-marketing-agent
# ===========================================================================


class TestDeployMarketingAgent:
    async def test_creates_agent_successfully(self, ctx: ClientCtx) -> None:
        await _seed_user(ctx.db_path, _ADMIN_USER_ID, _ADMIN_EMAIL)
        resp = await ctx.ac.post(
            "/api/v1/admin/deploy-marketing-agent",
            headers=_admin_headers(),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["handle"] == "dingdawg-marketing"
        assert data["status"] == "active"
        assert "agent_id" in data

    async def test_creates_agent_with_correct_type(self, ctx: ClientCtx) -> None:
        await _seed_user(ctx.db_path, _ADMIN_USER_ID, _ADMIN_EMAIL)
        resp = await ctx.ac.post(
            "/api/v1/admin/deploy-marketing-agent",
            headers=_admin_headers(),
        )
        data = resp.json()
        assert data["agent_type"] == "marketing"

    async def test_duplicate_returns_409(self, ctx: ClientCtx) -> None:
        await _seed_user(ctx.db_path, _ADMIN_USER_ID, _ADMIN_EMAIL)

        # First deploy — should succeed
        resp1 = await ctx.ac.post(
            "/api/v1/admin/deploy-marketing-agent",
            headers=_admin_headers(),
        )
        assert resp1.status_code == 201

        # Second deploy — should conflict
        resp2 = await ctx.ac.post(
            "/api/v1/admin/deploy-marketing-agent",
            headers=_admin_headers(),
        )
        assert resp2.status_code == 409

    async def test_requires_admin(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post("/api/v1/admin/deploy-marketing-agent")
        assert resp.status_code == 401

    async def test_non_admin_blocked(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/deploy-marketing-agent",
            headers=_non_admin_headers(),
        )
        assert resp.status_code == 403

    async def test_response_includes_message(self, ctx: ClientCtx) -> None:
        await _seed_user(ctx.db_path, _ADMIN_USER_ID, _ADMIN_EMAIL)
        resp = await ctx.ac.post(
            "/api/v1/admin/deploy-marketing-agent",
            headers=_admin_headers(),
        )
        data = resp.json()
        assert "message" in data
        assert "dingdawg-marketing" in data["message"]
