"""Comprehensive tests for analytics API routes.

Covers all five analytics endpoints:
  GET /api/v1/analytics/dashboard/{agent_id}
  GET /api/v1/analytics/conversations/{agent_id}
  GET /api/v1/analytics/skills/{agent_id}
  GET /api/v1/analytics/contacts/{agent_id}/stats
  GET /api/v1/analytics/revenue/{agent_id}

Test strategy:
- Auth enforcement (no token → 401)
- Ownership enforcement (wrong user → 403)
- Empty-state correctness (all zeroes, correct shapes)
- Populated-state correctness (seeded rows returned accurately)
- Query parameter validation (days range, pagination, date_from/date_to)
- Cross-user isolation
- Response shape contract for every endpoint

Fixture pattern mirrors test_api_agents.py exactly:
  - tmp_path SQLite DB per test class via the `client` fixture
  - lifespan context ensures app.state + all tables are created before any
    DB seeder or HTTP request runs
  - `client` fixture yields a (AsyncClient, db_path) namedtuple so seeders
    always use the same DB path that the lifespan initialised
  - JWT forged via _create_token (exercises the same verify_token path)
  - Agents are created via HTTP POST after lifespan is active so the `agents`
    table is guaranteed to exist
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

_SECRET = "test-secret-analytics-suite"
_USER_OWNER = "user-owner-analytics-001"
_USER_OTHER = "user-other-analytics-002"

# Lightweight named tuple so fixtures can return (client, db_path) together
ClientCtx = namedtuple("ClientCtx", ["ac", "db_path"])


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _make_token(user_id: str, email: str = "test@example.com") -> str:
    """Create a valid JWT for test requests."""
    return _create_token(user_id=user_id, email=email, secret_key=_SECRET)


def _auth_headers(user_id: str) -> dict[str, str]:
    """Return Authorization Bearer headers for the given user."""
    return {"Authorization": f"Bearer {_make_token(user_id)}"}


# ---------------------------------------------------------------------------
# Direct-DB seed helpers
# All seeders accept db_path explicitly — they must only be called after the
# lifespan has run create_tables (i.e. after the client fixture has yielded).
# ---------------------------------------------------------------------------


async def _create_agent_via_api(ac: AsyncClient, handle: str, user_id: str) -> str:
    """POST /api/v1/agents and return the new agent_id.

    Creating via the API guarantees the `agents` table and all related tables
    exist (the lifespan must be running to reach this call).
    """
    resp = await ac.post(
        "/api/v1/agents",
        json={
            "handle": handle,
            "name": f"Agent {handle}",
            "agent_type": "business",
            "industry_type": "restaurant",
        },
        headers=_auth_headers(user_id),
    )
    assert resp.status_code == 201, f"Failed to create agent: {resp.text}"
    return resp.json()["id"]


async def _insert_session(
    db_path: str,
    user_id: str,
    agent_id: str,
    session_id: str | None = None,
    created_at: str | None = None,
) -> str:
    """Insert an agent_sessions row. Returns session_id.

    Creates the table if it does not exist yet — SessionManager._ensure_initialized
    is lazy and only runs on the first SessionManager operation, which may not
    have happened in tests that don't send chat messages through the runtime.
    """
    sid = session_id or uuid.uuid4().hex
    now = created_at or datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_sessions (
                session_id      TEXT PRIMARY KEY,
                user_id         TEXT NOT NULL,
                agent_id        TEXT,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL,
                message_count   INTEGER NOT NULL DEFAULT 0,
                total_tokens    INTEGER NOT NULL DEFAULT 0,
                status          TEXT NOT NULL DEFAULT 'active'
            )
            """
        )
        # memory_messages must also exist: the conversation_history route
        # queries it for every session it finds (preview + last_message_at).
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT NOT NULL,
                role        TEXT NOT NULL,
                content     TEXT NOT NULL,
                created_at  TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            INSERT OR IGNORE INTO agent_sessions
                (session_id, user_id, agent_id, created_at, updated_at,
                 message_count, total_tokens, status)
            VALUES (?, ?, ?, ?, ?, 0, 0, 'active')
            """,
            (sid, user_id, agent_id, now, now),
        )
        await db.commit()
    return sid


async def _insert_memory_message(
    db_path: str,
    session_id: str,
    role: str = "user",
    content: str = "hello world",
    created_at: str | None = None,
) -> None:
    """Insert a memory_messages row.

    Creates the table if it does not exist yet — MemoryStore._ensure_initialized
    is lazy and only runs on the first MemoryStore operation, which may not have
    happened in tests that don't send chat messages.
    """
    now = created_at or datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT NOT NULL,
                role        TEXT NOT NULL,
                content     TEXT NOT NULL,
                created_at  TEXT NOT NULL
            )
            """
        )
        await db.execute(
            "INSERT INTO memory_messages (session_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?)",
            (session_id, role, content, now),
        )
        await db.commit()


async def _insert_audit_skill(
    db_path: str,
    actor: str,
    skill_name: str = "email_sender",
    status: str = "success",
    timestamp: str | None = None,
) -> None:
    """Insert a skill_execution audit_chain row.

    Uses only the columns defined in AuditChain._CREATE_TABLE_SQL:
    (timestamp, event_type, actor, details, entry_hash, prev_hash).
    The `action` column in schema.py's _AUDIT_CHAIN is NOT present in the
    table created by AuditChain._ensure_initialized — which runs first and
    wins the IF NOT EXISTS race.
    """
    now = timestamp or datetime.now(timezone.utc).isoformat()
    details = json.dumps({"skill": skill_name, "status": status, "duration_ms": 120})
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO audit_chain
                (timestamp, event_type, actor, details, entry_hash, prev_hash)
            VALUES (?, 'skill_execution', ?, ?, 'fakehash', 'prevhash')
            """,
            (now, actor, details),
        )
        await db.commit()


async def _insert_appointment(
    db_path: str,
    agent_id: str,
    status: str = "scheduled",
    start_time: str | None = None,
    updated_at: str | None = None,
) -> None:
    """Insert a skill_appointments row."""
    now = datetime.now(timezone.utc).isoformat()
    start = start_time or (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    upd = updated_at or now
    row_id = uuid.uuid4().hex
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO skill_appointments
                (id, agent_id, contact_name, title, start_time, status,
                 created_at, updated_at)
            VALUES (?, ?, 'Test Contact', 'Test Appt', ?, ?, ?, ?)
            """,
            (row_id, agent_id, start, status, now, upd),
        )
        await db.commit()


async def _insert_contact(
    db_path: str,
    agent_id: str,
    status: str = "active",
    source: str = "widget",
    created_at: str | None = None,
) -> None:
    """Insert a skill_contacts row."""
    now = created_at or datetime.now(timezone.utc).isoformat()
    row_id = uuid.uuid4().hex
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO skill_contacts
                (id, agent_id, name, email, source, status, created_at, updated_at)
            VALUES (?, ?, 'Test User', 'test@example.com', ?, ?, ?, ?)
            """,
            (row_id, agent_id, source, status, now, now),
        )
        await db.commit()


async def _insert_notification(
    db_path: str,
    agent_id: str,
    status: str = "sent",
) -> None:
    """Insert a skill_notifications row."""
    now = datetime.now(timezone.utc).isoformat()
    row_id = uuid.uuid4().hex
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO skill_notifications
                (id, agent_id, channel, recipient, body, status, created_at)
            VALUES (?, ?, 'email', 'r@example.com', 'body text', ?, ?)
            """,
            (row_id, agent_id, status, now),
        )
        await db.commit()


async def _insert_analytics_event(
    db_path: str,
    agent_id: str,
    event_type: str = "message",
    metadata: dict | None = None,
    created_at: str | None = None,
) -> None:
    """Insert an analytics_events row."""
    now = created_at or datetime.now(timezone.utc).isoformat()
    row_id = uuid.uuid4().hex
    meta = json.dumps(metadata or {})
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO analytics_events
                (id, agent_id, event_type, metadata, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (row_id, agent_id, event_type, meta, now),
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(loop_scope="function")
async def ctx(tmp_path) -> AsyncIterator[ClientCtx]:
    """Async client with fully initialised app lifespan + the DB path.

    Yields a ClientCtx(ac, db_path) namedtuple.  All direct-DB seeders
    must use ctx.db_path — this guarantees they operate on the same file
    that the lifespan initialised (schema already applied).

    Isolation guarantee: env-var overrides and the get_settings lru_cache
    are always cleaned up in a try/finally block, so a test failure or
    lifespan exception can never leak a stale DB path into the next test.
    """
    db_file = str(tmp_path / "test_analytics.db")

    # Stash any pre-existing values so we can restore them on teardown.
    _prev_db_path = os.environ.get("ISG_AGENT_DB_PATH")
    _prev_secret = os.environ.get("ISG_AGENT_SECRET_KEY")

    os.environ["ISG_AGENT_DB_PATH"] = db_file
    os.environ["ISG_AGENT_SECRET_KEY"] = _SECRET
    get_settings.cache_clear()

    try:
        from isg_agent.app import create_app, lifespan

        app = create_app()

        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ClientCtx(ac=ac, db_path=db_file)
    finally:
        # Always restore env and clear cache — even if setup or a test raises.
        if _prev_db_path is None:
            os.environ.pop("ISG_AGENT_DB_PATH", None)
        else:
            os.environ["ISG_AGENT_DB_PATH"] = _prev_db_path

        if _prev_secret is None:
            os.environ.pop("ISG_AGENT_SECRET_KEY", None)
        else:
            os.environ["ISG_AGENT_SECRET_KEY"] = _prev_secret

        get_settings.cache_clear()


@pytest_asyncio.fixture
async def owner_agent(ctx: ClientCtx) -> str:
    """Create an agent owned by _USER_OWNER via the API. Returns agent_id.

    Creating via HTTP POST guarantees all tables exist (lifespan already ran).
    """
    return await _create_agent_via_api(ctx.ac, "analytics-owner-agent", _USER_OWNER)


# ---------------------------------------------------------------------------
# Dashboard endpoint — GET /api/v1/analytics/dashboard/{agent_id}
# ---------------------------------------------------------------------------


class TestDashboardOverview:
    """Tests for GET /api/v1/analytics/dashboard/{agent_id}."""

    @pytest.mark.asyncio
    async def test_dashboard_requires_auth(self, ctx, owner_agent):
        """No token → 401."""
        resp = await ctx.ac.get(f"/api/v1/analytics/dashboard/{owner_agent}")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_dashboard_wrong_user_returns_403(self, ctx, owner_agent):
        """A user who does not own the agent receives 403."""
        resp = await ctx.ac.get(
            f"/api/v1/analytics/dashboard/{owner_agent}",
            headers=_auth_headers(_USER_OTHER),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_dashboard_nonexistent_agent_returns_403(self, ctx, owner_agent):
        """Requesting dashboard for a non-existent agent_id returns 403.

        `owner_agent` is included to guarantee AgentRegistry._ensure_initialized
        has run (and thus the agents table exists) before this request is made.
        """
        resp = await ctx.ac.get(
            "/api/v1/analytics/dashboard/no-such-agent-00000",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_dashboard_empty_state_correct_shape(self, ctx, owner_agent):
        """Empty DB returns all zeroes with correct top-level keys."""
        resp = await ctx.ac.get(
            f"/api/v1/analytics/dashboard/{owner_agent}",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["agent_id"] == owner_agent
        assert data["period"] == "last_7_days"

        # conversations
        assert "conversations" in data
        assert data["conversations"]["total"] == 0
        assert data["conversations"]["today"] == 0
        assert isinstance(data["conversations"]["trend"], (int, float))

        # messages
        assert "messages" in data
        assert data["messages"]["total"] == 0
        assert data["messages"]["avg_per_conversation"] == 0.0

        # skills
        assert "skills" in data
        assert data["skills"]["total_executions"] == 0
        assert data["skills"]["by_skill"] == {}
        assert data["skills"]["success_rate"] == 0.0

        # appointments
        assert "appointments" in data
        for key in ("scheduled", "completed", "cancelled", "upcoming"):
            assert data["appointments"][key] == 0

        # contacts
        assert "contacts" in data
        assert data["contacts"]["total"] == 0
        assert data["contacts"]["new_this_period"] == 0
        assert data["contacts"]["by_status"] == {}

        # notifications
        assert "notifications" in data
        for key in ("sent", "failed", "queued"):
            assert data["notifications"][key] == 0

        assert isinstance(data["top_topics"], list)
        assert isinstance(data["response_time_avg_ms"], (int, float))
        assert isinstance(data["active_hours"], dict)

    @pytest.mark.asyncio
    async def test_dashboard_counts_conversations(self, ctx, owner_agent):
        """Sessions created in the period increment conversations.total."""
        for _ in range(3):
            await _insert_session(ctx.db_path, _USER_OWNER, owner_agent)

        resp = await ctx.ac.get(
            f"/api/v1/analytics/dashboard/{owner_agent}",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["conversations"]["total"] == 3

    @pytest.mark.asyncio
    async def test_dashboard_counts_messages(self, ctx, owner_agent):
        """Messages linked to sessions appear in messages.total."""
        sid = await _insert_session(ctx.db_path, _USER_OWNER, owner_agent)
        await _insert_memory_message(ctx.db_path, sid, content="first message")
        await _insert_memory_message(ctx.db_path, sid, role="assistant", content="reply")

        resp = await ctx.ac.get(
            f"/api/v1/analytics/dashboard/{owner_agent}",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["messages"]["total"] == 2
        assert data["messages"]["avg_per_conversation"] == 2.0

    @pytest.mark.asyncio
    async def test_dashboard_skill_executions_aggregated(self, ctx, owner_agent):
        """Skill executions in audit_chain appear in skills.total_executions."""
        await _insert_audit_skill(ctx.db_path, _USER_OWNER, "email_sender", "success")
        await _insert_audit_skill(ctx.db_path, _USER_OWNER, "email_sender", "success")
        await _insert_audit_skill(ctx.db_path, _USER_OWNER, "calendar", "error")

        resp = await ctx.ac.get(
            f"/api/v1/analytics/dashboard/{owner_agent}",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        data = resp.json()
        # 3 total via user_id actor path
        assert data["skills"]["total_executions"] >= 3

    @pytest.mark.asyncio
    async def test_dashboard_appointments_counted(self, ctx, owner_agent):
        """Appointments of different statuses are counted separately."""
        await _insert_appointment(ctx.db_path, owner_agent, "scheduled")
        await _insert_appointment(ctx.db_path, owner_agent, "completed")
        await _insert_appointment(ctx.db_path, owner_agent, "cancelled")

        resp = await ctx.ac.get(
            f"/api/v1/analytics/dashboard/{owner_agent}",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["appointments"]["scheduled"] == 1
        assert data["appointments"]["completed"] == 1
        assert data["appointments"]["cancelled"] == 1

    @pytest.mark.asyncio
    async def test_dashboard_contacts_counted(self, ctx, owner_agent):
        """Contacts for the agent increment contacts.total."""
        await _insert_contact(ctx.db_path, owner_agent)
        await _insert_contact(ctx.db_path, owner_agent)

        resp = await ctx.ac.get(
            f"/api/v1/analytics/dashboard/{owner_agent}",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["contacts"]["total"] == 2

    @pytest.mark.asyncio
    async def test_dashboard_notifications_counted(self, ctx, owner_agent):
        """Notifications of each status are counted correctly."""
        await _insert_notification(ctx.db_path, owner_agent, "sent")
        await _insert_notification(ctx.db_path, owner_agent, "failed")
        await _insert_notification(ctx.db_path, owner_agent, "queued")

        resp = await ctx.ac.get(
            f"/api/v1/analytics/dashboard/{owner_agent}",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["notifications"]["sent"] == 1
        assert data["notifications"]["failed"] == 1
        assert data["notifications"]["queued"] == 1

    @pytest.mark.asyncio
    async def test_dashboard_response_time_from_analytics_events(self, ctx, owner_agent):
        """Analytics events with response_time_ms populate response_time_avg_ms."""
        await _insert_analytics_event(
            ctx.db_path, owner_agent, "message", {"response_time_ms": 200}
        )
        await _insert_analytics_event(
            ctx.db_path, owner_agent, "message", {"response_time_ms": 400}
        )

        resp = await ctx.ac.get(
            f"/api/v1/analytics/dashboard/{owner_agent}",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["response_time_avg_ms"] == 300.0

    @pytest.mark.asyncio
    async def test_dashboard_other_agents_contacts_not_counted(self, ctx):
        """Contacts belonging to a different agent are NOT counted."""
        agent_a = await _create_agent_via_api(ctx.ac, "dash-agent-a", _USER_OWNER)
        agent_b = await _create_agent_via_api(ctx.ac, "dash-agent-b", _USER_OWNER)

        # Insert contacts only for agent_b
        await _insert_contact(ctx.db_path, agent_b)

        resp = await ctx.ac.get(
            f"/api/v1/analytics/dashboard/{agent_a}",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        assert resp.json()["contacts"]["total"] == 0


# ---------------------------------------------------------------------------
# Conversations endpoint — GET /api/v1/analytics/conversations/{agent_id}
# ---------------------------------------------------------------------------


class TestConversationHistory:
    """Tests for GET /api/v1/analytics/conversations/{agent_id}."""

    @pytest.mark.asyncio
    async def test_conversations_requires_auth(self, ctx, owner_agent):
        """No token → 401."""
        resp = await ctx.ac.get(f"/api/v1/analytics/conversations/{owner_agent}")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_conversations_wrong_user_returns_403(self, ctx, owner_agent):
        """Non-owner gets 403."""
        resp = await ctx.ac.get(
            f"/api/v1/analytics/conversations/{owner_agent}",
            headers=_auth_headers(_USER_OTHER),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_conversations_empty_state(self, ctx, owner_agent):
        """Empty DB returns correct shape with total=0."""
        resp = await ctx.ac.get(
            f"/api/v1/analytics/conversations/{owner_agent}",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "conversations" in data
        assert "total" in data
        assert data["total"] == 0
        assert data["conversations"] == []

    @pytest.mark.asyncio
    async def test_conversations_lists_sessions(self, ctx, owner_agent):
        """Sessions show up in the conversation list with correct shape."""
        sid = await _insert_session(ctx.db_path, _USER_OWNER, owner_agent)
        await _insert_memory_message(ctx.db_path, sid, content="test question")

        resp = await ctx.ac.get(
            f"/api/v1/analytics/conversations/{owner_agent}",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["conversations"]) == 1
        conv = data["conversations"][0]
        assert "session_id" in conv
        assert "started_at" in conv
        assert "message_count" in conv
        assert "last_message_at" in conv
        assert "preview" in conv

    @pytest.mark.asyncio
    async def test_conversations_pagination_limit(self, ctx, owner_agent):
        """limit query parameter controls number of results returned."""
        for _ in range(5):
            await _insert_session(ctx.db_path, _USER_OWNER, owner_agent)

        resp = await ctx.ac.get(
            f"/api/v1/analytics/conversations/{owner_agent}",
            params={"limit": 2},
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert len(data["conversations"]) == 2

    @pytest.mark.asyncio
    async def test_conversations_pagination_offset(self, ctx, owner_agent):
        """offset query parameter skips earlier results."""
        for _ in range(4):
            await _insert_session(ctx.db_path, _USER_OWNER, owner_agent)

        resp = await ctx.ac.get(
            f"/api/v1/analytics/conversations/{owner_agent}",
            params={"limit": 10, "offset": 3},
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 4
        assert len(data["conversations"]) == 1

    @pytest.mark.asyncio
    async def test_conversations_date_from_filter(self, ctx, owner_agent):
        """date_from filters out sessions older than the cutoff."""
        old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        recent_ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()

        await _insert_session(ctx.db_path, _USER_OWNER, owner_agent, created_at=old_ts)
        await _insert_session(ctx.db_path, _USER_OWNER, owner_agent, created_at=recent_ts)

        resp = await ctx.ac.get(
            f"/api/v1/analytics/conversations/{owner_agent}",
            params={"date_from": cutoff},
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    @pytest.mark.asyncio
    async def test_conversations_date_to_filter(self, ctx, owner_agent):
        """date_to excludes sessions after the cutoff."""
        old_ts = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
        new_ts = datetime.now(timezone.utc).isoformat()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()

        await _insert_session(ctx.db_path, _USER_OWNER, owner_agent, created_at=old_ts)
        await _insert_session(ctx.db_path, _USER_OWNER, owner_agent, created_at=new_ts)

        resp = await ctx.ac.get(
            f"/api/v1/analytics/conversations/{owner_agent}",
            params={"date_to": cutoff},
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    @pytest.mark.asyncio
    async def test_conversations_preview_truncated_to_120_chars(self, ctx, owner_agent):
        """The preview field is at most 120 characters."""
        sid = await _insert_session(ctx.db_path, _USER_OWNER, owner_agent)
        long_content = "word " * 100  # well over 120 chars
        await _insert_memory_message(ctx.db_path, sid, content=long_content)

        resp = await ctx.ac.get(
            f"/api/v1/analytics/conversations/{owner_agent}",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        conv = resp.json()["conversations"][0]
        assert len(conv["preview"]) <= 120

    @pytest.mark.asyncio
    async def test_conversations_no_messages_returns_empty_list(self, ctx, owner_agent):
        """conversation_history returns empty list when no messages have been sent.

        Regression test for the latent production bug: on a fresh deployment
        where MemoryStore._ensure_initialized has never run, memory_messages
        does not exist.  The route must return HTTP 200 with an empty list
        rather than crashing with an OperationalError.

        This test deliberately does NOT call _insert_memory_message so that
        memory_messages is only created by init_analytics_tables (the fix).
        """
        resp = await ctx.ac.get(
            f"/api/v1/analytics/conversations/{owner_agent}",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["conversations"] == []

    @pytest.mark.asyncio
    async def test_conversations_sessions_exist_but_no_messages(self, ctx, owner_agent):
        """Sessions that have no messages produce conversations with empty preview.

        This tests the inner loop of conversation_history: when agent_sessions
        rows exist but memory_messages has no rows for those sessions (or the
        table was created empty by init_analytics_tables), the endpoint must
        return conversations with preview='' and last_message_at falling back
        to the session's updated_at — not an HTTP 500.
        """
        sid = await _insert_session(ctx.db_path, _USER_OWNER, owner_agent)

        resp = await ctx.ac.get(
            f"/api/v1/analytics/conversations/{owner_agent}",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["conversations"]) == 1
        conv = data["conversations"][0]
        assert conv["session_id"] == sid
        assert conv["preview"] == ""
        assert "last_message_at" in conv  # falls back to updated_at — must be present


# ---------------------------------------------------------------------------
# Skills endpoint — GET /api/v1/analytics/skills/{agent_id}
# ---------------------------------------------------------------------------


class TestSkillAnalytics:
    """Tests for GET /api/v1/analytics/skills/{agent_id}."""

    @pytest.mark.asyncio
    async def test_skills_requires_auth(self, ctx, owner_agent):
        """No token → 401."""
        resp = await ctx.ac.get(f"/api/v1/analytics/skills/{owner_agent}")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_skills_wrong_user_returns_403(self, ctx, owner_agent):
        """Non-owner gets 403."""
        resp = await ctx.ac.get(
            f"/api/v1/analytics/skills/{owner_agent}",
            headers=_auth_headers(_USER_OTHER),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_skills_empty_state(self, ctx, owner_agent):
        """No audit entries returns empty lists with correct keys."""
        resp = await ctx.ac.get(
            f"/api/v1/analytics/skills/{owner_agent}",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "by_skill" in data
        assert "daily" in data
        assert "top_actions" in data
        assert data["by_skill"] == []
        assert data["daily"] == []
        assert data["top_actions"] == []

    @pytest.mark.asyncio
    async def test_skills_response_shape(self, ctx, owner_agent):
        """by_skill items contain name, executions, success_rate, avg_duration_ms."""
        await _insert_audit_skill(ctx.db_path, _USER_OWNER, "email_sender", "success")

        resp = await ctx.ac.get(
            f"/api/v1/analytics/skills/{owner_agent}",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["by_skill"]) >= 1
        item = data["by_skill"][0]
        assert "name" in item
        assert "executions" in item
        assert "success_rate" in item
        assert "avg_duration_ms" in item

    @pytest.mark.asyncio
    async def test_skills_success_rate_calculated(self, ctx, owner_agent):
        """success_rate reflects the fraction of successful executions."""
        # 2 success, 1 error → 66.7%
        await _insert_audit_skill(ctx.db_path, _USER_OWNER, "calendar", "success")
        await _insert_audit_skill(ctx.db_path, _USER_OWNER, "calendar", "success")
        await _insert_audit_skill(ctx.db_path, _USER_OWNER, "calendar", "error")

        resp = await ctx.ac.get(
            f"/api/v1/analytics/skills/{owner_agent}",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        by_skill = resp.json()["by_skill"]
        calendar = next((s for s in by_skill if s["name"] == "calendar"), None)
        assert calendar is not None
        assert calendar["executions"] == 3
        assert calendar["success_rate"] == 66.7

    @pytest.mark.asyncio
    async def test_skills_daily_breakdown(self, ctx, owner_agent):
        """daily list contains date-aggregated execution counts."""
        today = datetime.now(timezone.utc).isoformat()
        await _insert_audit_skill(ctx.db_path, _USER_OWNER, "sms", "success", today)
        await _insert_audit_skill(ctx.db_path, _USER_OWNER, "sms", "success", today)

        resp = await ctx.ac.get(
            f"/api/v1/analytics/skills/{owner_agent}",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        daily = resp.json()["daily"]
        assert len(daily) >= 1
        today_entry = daily[-1]
        assert "date" in today_entry
        assert "executions" in today_entry
        assert today_entry["executions"] >= 2

    @pytest.mark.asyncio
    async def test_skills_days_query_parameter_excludes_old(self, ctx, owner_agent):
        """days=1 excludes executions older than 1 day."""
        old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        await _insert_audit_skill(
            ctx.db_path, _USER_OWNER, "old_skill", "success", old_ts
        )

        resp = await ctx.ac.get(
            f"/api/v1/analytics/skills/{owner_agent}",
            params={"days": 1},
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        names = [s["name"] for s in resp.json()["by_skill"]]
        assert "old_skill" not in names

    @pytest.mark.asyncio
    async def test_skills_sorted_by_executions_desc(self, ctx, owner_agent):
        """by_skill is sorted most-executed first."""
        for _ in range(3):
            await _insert_audit_skill(ctx.db_path, _USER_OWNER, "skill_a", "success")
        await _insert_audit_skill(ctx.db_path, _USER_OWNER, "skill_b", "success")

        resp = await ctx.ac.get(
            f"/api/v1/analytics/skills/{owner_agent}",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        by_skill = resp.json()["by_skill"]
        names = [s["name"] for s in by_skill]
        assert names.index("skill_a") < names.index("skill_b")

    @pytest.mark.asyncio
    async def test_skills_top_actions_shape(self, ctx, owner_agent):
        """top_actions items contain skill, action, and count fields."""
        await _insert_audit_skill(ctx.db_path, _USER_OWNER, "email_sender", "success")

        resp = await ctx.ac.get(
            f"/api/v1/analytics/skills/{owner_agent}",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        top = resp.json()["top_actions"]
        if top:
            item = top[0]
            assert "skill" in item
            assert "action" in item
            assert "count" in item


# ---------------------------------------------------------------------------
# Contacts stats endpoint — GET /api/v1/analytics/contacts/{agent_id}/stats
# ---------------------------------------------------------------------------


class TestContactStats:
    """Tests for GET /api/v1/analytics/contacts/{agent_id}/stats."""

    @pytest.mark.asyncio
    async def test_contact_stats_requires_auth(self, ctx, owner_agent):
        """No token → 401."""
        resp = await ctx.ac.get(f"/api/v1/analytics/contacts/{owner_agent}/stats")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_contact_stats_wrong_user_returns_403(self, ctx, owner_agent):
        """Non-owner gets 403."""
        resp = await ctx.ac.get(
            f"/api/v1/analytics/contacts/{owner_agent}/stats",
            headers=_auth_headers(_USER_OTHER),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_contact_stats_empty_state(self, ctx, owner_agent):
        """No contacts returns zeroes and empty dicts."""
        resp = await ctx.ac.get(
            f"/api/v1/analytics/contacts/{owner_agent}/stats",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["by_status"] == {}
        assert data["by_source"] == {}
        assert data["recent"] == []

    @pytest.mark.asyncio
    async def test_contact_stats_total_count(self, ctx, owner_agent):
        """total reflects all contacts for the agent."""
        await _insert_contact(ctx.db_path, owner_agent)
        await _insert_contact(ctx.db_path, owner_agent)
        await _insert_contact(ctx.db_path, owner_agent)

        resp = await ctx.ac.get(
            f"/api/v1/analytics/contacts/{owner_agent}/stats",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 3

    @pytest.mark.asyncio
    async def test_contact_stats_by_status(self, ctx, owner_agent):
        """by_status groups contacts by their status field."""
        await _insert_contact(ctx.db_path, owner_agent, status="active")
        await _insert_contact(ctx.db_path, owner_agent, status="active")
        await _insert_contact(ctx.db_path, owner_agent, status="inactive")

        resp = await ctx.ac.get(
            f"/api/v1/analytics/contacts/{owner_agent}/stats",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        by_status = resp.json()["by_status"]
        assert by_status.get("active") == 2
        assert by_status.get("inactive") == 1

    @pytest.mark.asyncio
    async def test_contact_stats_by_source(self, ctx, owner_agent):
        """by_source groups contacts by their source field."""
        await _insert_contact(ctx.db_path, owner_agent, source="widget")
        await _insert_contact(ctx.db_path, owner_agent, source="import")

        resp = await ctx.ac.get(
            f"/api/v1/analytics/contacts/{owner_agent}/stats",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        by_source = resp.json()["by_source"]
        assert by_source.get("widget") == 1
        assert by_source.get("import") == 1

    @pytest.mark.asyncio
    async def test_contact_stats_recent_list_capped_at_10(self, ctx, owner_agent):
        """recent returns at most 10 contacts."""
        for _ in range(15):
            await _insert_contact(ctx.db_path, owner_agent)

        resp = await ctx.ac.get(
            f"/api/v1/analytics/contacts/{owner_agent}/stats",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        assert len(resp.json()["recent"]) == 10

    @pytest.mark.asyncio
    async def test_contact_stats_recent_shape(self, ctx, owner_agent):
        """Each item in recent contains name, email, and added_at."""
        await _insert_contact(ctx.db_path, owner_agent)

        resp = await ctx.ac.get(
            f"/api/v1/analytics/contacts/{owner_agent}/stats",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        item = resp.json()["recent"][0]
        assert "name" in item
        assert "email" in item
        assert "added_at" in item

    @pytest.mark.asyncio
    async def test_contact_stats_other_agent_isolated(self, ctx):
        """Contacts from a different agent are not counted."""
        agent_a = await _create_agent_via_api(ctx.ac, "contacts-agent-a", _USER_OWNER)
        agent_b = await _create_agent_via_api(ctx.ac, "contacts-agent-b", _USER_OWNER)

        await _insert_contact(ctx.db_path, agent_b)

        resp = await ctx.ac.get(
            f"/api/v1/analytics/contacts/{agent_a}/stats",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


# ---------------------------------------------------------------------------
# Revenue endpoint — GET /api/v1/analytics/revenue/{agent_id}
# ---------------------------------------------------------------------------


class TestRevenueAnalytics:
    """Tests for GET /api/v1/analytics/revenue/{agent_id}."""

    @pytest.mark.asyncio
    async def test_revenue_requires_auth(self, ctx, owner_agent):
        """No token → 401."""
        resp = await ctx.ac.get(f"/api/v1/analytics/revenue/{owner_agent}")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_revenue_wrong_user_returns_403(self, ctx, owner_agent):
        """Non-owner gets 403."""
        resp = await ctx.ac.get(
            f"/api/v1/analytics/revenue/{owner_agent}",
            headers=_auth_headers(_USER_OTHER),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_revenue_empty_state(self, ctx, owner_agent):
        """No appointments or transactions returns zeroes."""
        resp = await ctx.ac.get(
            f"/api/v1/analytics/revenue/{owner_agent}",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "appointments_revenue" in data
        assert "transactions" in data
        assert "completed_appointments" in data
        assert "daily" in data
        assert data["appointments_revenue"] == 0.0
        assert data["transactions"] == 0
        assert data["completed_appointments"] == 0
        assert data["daily"] == []

    @pytest.mark.asyncio
    async def test_revenue_completed_appointments_counted(self, ctx, owner_agent):
        """completed_appointments counts appointments with status=completed in period."""
        period_ts = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        await _insert_appointment(
            ctx.db_path, owner_agent, status="completed", updated_at=period_ts
        )
        await _insert_appointment(
            ctx.db_path, owner_agent, status="completed", updated_at=period_ts
        )
        # scheduled should not appear in completed_appointments count
        await _insert_appointment(ctx.db_path, owner_agent, status="scheduled")

        resp = await ctx.ac.get(
            f"/api/v1/analytics/revenue/{owner_agent}",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["completed_appointments"] >= 2

    @pytest.mark.asyncio
    async def test_revenue_transaction_events_summed(self, ctx, owner_agent):
        """Transaction analytics_events with amount are summed into appointments_revenue."""
        await _insert_analytics_event(
            ctx.db_path, owner_agent, "transaction", {"amount": 50.0}
        )
        await _insert_analytics_event(
            ctx.db_path, owner_agent, "transaction", {"amount": 75.50}
        )

        resp = await ctx.ac.get(
            f"/api/v1/analytics/revenue/{owner_agent}",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["transactions"] == 2
        assert data["appointments_revenue"] == 125.50

    @pytest.mark.asyncio
    async def test_revenue_days_query_parameter_excludes_old(self, ctx, owner_agent):
        """days=1 excludes transactions older than 1 day."""
        old_ts = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        await _insert_analytics_event(
            ctx.db_path,
            owner_agent,
            "transaction",
            {"amount": 999.0},
            created_at=old_ts,
        )

        resp = await ctx.ac.get(
            f"/api/v1/analytics/revenue/{owner_agent}",
            params={"days": 1},
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["transactions"] == 0
        assert data["appointments_revenue"] == 0.0

    @pytest.mark.asyncio
    async def test_revenue_daily_list_shape(self, ctx, owner_agent):
        """daily items contain date, count, and revenue fields."""
        now = datetime.now(timezone.utc).isoformat()
        await _insert_appointment(
            ctx.db_path, owner_agent, status="completed", updated_at=now
        )

        resp = await ctx.ac.get(
            f"/api/v1/analytics/revenue/{owner_agent}",
            headers=_auth_headers(_USER_OWNER),
        )
        assert resp.status_code == 200
        daily = resp.json()["daily"]
        if daily:
            item = daily[0]
            assert "date" in item
            assert "count" in item
            assert "revenue" in item
