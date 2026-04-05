"""Tests for the SelfHealingEngine and enhanced admin command/priorities endpoints.

Test categories
---------------
1.  SelfHealingEngine.get_system_status — shape and healthy baseline
2.  SelfHealingEngine.detect_issues — stripe test mode, missing env vars
3.  SelfHealingEngine.detect_issues — stale sessions detection
4.  SelfHealingEngine.auto_fix — unknown issue_id returns error, not exception
5.  SelfHealingEngine.auto_fix — stale_sessions removes old rows
6.  SelfHealingEngine.auto_fix — missing_tables triggers schema init
7.  SelfHealingEngine.run_diagnostics — returns full DiagnosticReport shape
8.  SelfHealingEngine.get_fix_history — accumulates records
9.  POST /admin/command — status command routes to self-healing engine
10. POST /admin/command — diagnose command returns full diagnostic
11. POST /admin/command — issues command returns issue list
12. POST /admin/command — fix command routes to engine
13. POST /admin/command — history command returns fix history
14. POST /admin/command — health command returns checks
15. POST /admin/command — errors command returns recent errors
16. POST /admin/command — env-check command returns var status, no values exposed
17. POST /admin/command — restart-check alias for diagnose
18. POST /admin/command — help returns all commands
19. POST /admin/command — unknown command returns help (not 4xx)
20. POST /admin/command — empty command returns 422
21. GET  /admin/priorities — non-admin returns 403
22. GET  /admin/priorities — admin returns correct shape
23. GET  /admin/priorities — stripe test mode appears as critical priority
24. GET  /admin/priorities — priorities are sorted critical-first
"""

from __future__ import annotations

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
from isg_agent.config import Settings, get_settings
from isg_agent.core.self_healing import SelfHealingEngine

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SECRET = "test-secret-self-healing"
_ADMIN_EMAIL = "admin@healing-test.com"
_ADMIN_USER_ID = "admin-healing-001"
_NON_ADMIN_EMAIL = "user@healing-test.com"
_NON_ADMIN_USER_ID = "nonadmin-healing-002"

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
    """Async HTTP client with fully initialised app lifespan + DB path.

    Mirrors the pattern in test_admin_api.py exactly.
    """
    db_file = str(tmp_path / "test_self_healing.db")

    _prev_db = os.environ.get("ISG_AGENT_DB_PATH")
    _prev_secret = os.environ.get("ISG_AGENT_SECRET_KEY")
    _prev_admin = os.environ.get("ISG_AGENT_ADMIN_EMAIL")
    # Stripe test key to exercise stripe-test-mode detection
    _prev_stripe = os.environ.get("ISG_AGENT_STRIPE_SECRET_KEY")

    os.environ["ISG_AGENT_DB_PATH"] = db_file
    os.environ["ISG_AGENT_SECRET_KEY"] = _SECRET
    os.environ["ISG_AGENT_ADMIN_EMAIL"] = _ADMIN_EMAIL
    os.environ["ISG_AGENT_STRIPE_SECRET_KEY"] = "sk_test_healing_fixture"
    get_settings.cache_clear()

    try:
        from isg_agent.app import create_app, lifespan

        app = create_app()
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ClientCtx(ac=ac, db_path=db_file)
    finally:
        _restore = {
            "ISG_AGENT_DB_PATH": _prev_db,
            "ISG_AGENT_SECRET_KEY": _prev_secret,
            "ISG_AGENT_ADMIN_EMAIL": _prev_admin,
            "ISG_AGENT_STRIPE_SECRET_KEY": _prev_stripe,
        }
        for var, val in _restore.items():
            if val is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = val
        get_settings.cache_clear()


@pytest_asyncio.fixture(loop_scope="function")
async def db_path(tmp_path) -> AsyncIterator[str]:
    """Bare DB path with app tables initialised — for direct engine tests."""
    db_file = str(tmp_path / "test_engine.db")

    _prev_db = os.environ.get("ISG_AGENT_DB_PATH")
    _prev_secret = os.environ.get("ISG_AGENT_SECRET_KEY")
    _prev_stripe = os.environ.get("ISG_AGENT_STRIPE_SECRET_KEY")

    os.environ["ISG_AGENT_DB_PATH"] = db_file
    os.environ["ISG_AGENT_SECRET_KEY"] = _SECRET
    os.environ["ISG_AGENT_STRIPE_SECRET_KEY"] = "sk_test_engine_fixture"
    get_settings.cache_clear()

    try:
        from isg_agent.app import create_app, lifespan

        app = create_app()
        async with lifespan(app):
            yield db_file
    finally:
        for var, val in [
            ("ISG_AGENT_DB_PATH", _prev_db),
            ("ISG_AGENT_SECRET_KEY", _prev_secret),
            ("ISG_AGENT_STRIPE_SECRET_KEY", _prev_stripe),
        ]:
            if val is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = val
        get_settings.cache_clear()


def _make_settings(stripe_key: str = "sk_test_x", db_path: str = "") -> Settings:
    """Build a minimal Settings object for engine unit tests."""
    return Settings(
        secret_key=_SECRET,
        db_path=db_path,
        stripe_secret_key=stripe_key,
        sendgrid_api_key="",
    )


# ---------------------------------------------------------------------------
# Helper: seed stale sessions
# ---------------------------------------------------------------------------


async def _seed_stale_sessions(db: str, count: int = 5) -> None:
    """Insert `count` agent_sessions with updated_at > 8 days ago.

    Uses the real agent_sessions schema from isg_agent/brain/session.py:
        session_id TEXT PRIMARY KEY,
        user_id    TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        message_count INTEGER NOT NULL DEFAULT 0,
        total_tokens  INTEGER NOT NULL DEFAULT 0,
        status        TEXT NOT NULL DEFAULT 'active'
    """
    stale_ts = (
        datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=8)
    ).isoformat()
    async with aiosqlite.connect(db) as conn:
        for _ in range(count):
            sess_id = str(uuid.uuid4())
            await conn.execute(
                """
                INSERT OR IGNORE INTO agent_sessions
                    (session_id, user_id, created_at, updated_at, status)
                VALUES (?, 'user-stale-test', ?, ?, 'completed')
                """,
                (sess_id, stale_ts, stale_ts),
            )
        await conn.commit()


# ===========================================================================
# 1. SelfHealingEngine.get_system_status — shape and healthy baseline
# ===========================================================================


class TestGetSystemStatus:
    async def test_returns_expected_keys(self, db_path: str) -> None:
        s = _make_settings(db_path=db_path)
        engine = SelfHealingEngine(db_path=db_path, settings=s)
        result = await engine.get_system_status()
        expected_keys = {
            "status", "db_reachable", "db_size_bytes",
            "memory_rss_kb", "error_count_1h", "duration_ms", "checked_at",
        }
        assert expected_keys.issubset(result.keys())

    async def test_db_reachable_is_true_for_valid_db(self, db_path: str) -> None:
        s = _make_settings(db_path=db_path)
        engine = SelfHealingEngine(db_path=db_path, settings=s)
        result = await engine.get_system_status()
        assert result["db_reachable"] is True

    async def test_status_healthy_on_clean_db(self, db_path: str) -> None:
        s = _make_settings(db_path=db_path)
        engine = SelfHealingEngine(db_path=db_path, settings=s)
        result = await engine.get_system_status()
        # Clean DB with 0 errors → healthy
        assert result["status"] == "healthy"

    async def test_db_unreachable_returns_critical(self, tmp_path) -> None:
        s = _make_settings(db_path="/nonexistent/path/nowhere.db")
        engine = SelfHealingEngine(db_path="/nonexistent/path/nowhere.db", settings=s)
        result = await engine.get_system_status()
        assert result["db_reachable"] is False
        assert result["status"] == "critical"

    async def test_duration_ms_is_positive(self, db_path: str) -> None:
        s = _make_settings(db_path=db_path)
        engine = SelfHealingEngine(db_path=db_path, settings=s)
        result = await engine.get_system_status()
        assert result["duration_ms"] >= 0


# ===========================================================================
# 2. SelfHealingEngine.detect_issues — stripe test mode + missing env vars
# ===========================================================================


class TestDetectIssues:
    async def test_stripe_test_mode_detected_as_critical(self, db_path: str) -> None:
        s = _make_settings(stripe_key="sk_test_abc123", db_path=db_path)
        engine = SelfHealingEngine(db_path=db_path, settings=s)
        issues = await engine.detect_issues()
        stripe_issues = [i for i in issues if i.issue_id == "stripe_test_mode"]
        assert len(stripe_issues) == 1
        assert stripe_issues[0].severity == "critical"

    async def test_stripe_live_key_no_stripe_issue(self, db_path: str) -> None:
        s = _make_settings(stripe_key="sk_live_real123", db_path=db_path)
        engine = SelfHealingEngine(db_path=db_path, settings=s)
        issues = await engine.detect_issues()
        stripe_issues = [i for i in issues if i.issue_id == "stripe_test_mode"]
        assert len(stripe_issues) == 0

    async def test_returns_list(self, db_path: str) -> None:
        s = _make_settings(db_path=db_path)
        engine = SelfHealingEngine(db_path=db_path, settings=s)
        issues = await engine.detect_issues()
        assert isinstance(issues, list)

    async def test_critical_issues_sort_first(self, db_path: str) -> None:
        """If both critical and warning issues exist, critical must come first."""
        s = _make_settings(stripe_key="sk_test_x", db_path=db_path)
        engine = SelfHealingEngine(db_path=db_path, settings=s)
        issues = await engine.detect_issues()
        if len(issues) >= 2:
            severity_order = {"critical": 0, "warning": 1, "info": 2}
            for i in range(len(issues) - 1):
                assert severity_order.get(issues[i].severity, 99) <= severity_order.get(
                    issues[i + 1].severity, 99
                )


# ===========================================================================
# 3. SelfHealingEngine.detect_issues — stale sessions detection
# ===========================================================================


class TestDetectIssuesStale:
    async def test_stale_sessions_detected_when_over_500(self, db_path: str) -> None:
        """Seed 501 stale sessions — issue should appear."""
        await _seed_stale_sessions(db_path, count=501)
        s = _make_settings(stripe_key="sk_live_x", db_path=db_path)
        engine = SelfHealingEngine(db_path=db_path, settings=s)
        issues = await engine.detect_issues()
        stale_issues = [i for i in issues if i.issue_id == "stale_sessions"]
        assert len(stale_issues) == 1
        assert stale_issues[0].auto_fixable is True

    async def test_stale_sessions_not_detected_below_500(self, db_path: str) -> None:
        """With only 5 stale sessions, issue should NOT appear."""
        await _seed_stale_sessions(db_path, count=5)
        s = _make_settings(stripe_key="sk_live_x", db_path=db_path)
        engine = SelfHealingEngine(db_path=db_path, settings=s)
        issues = await engine.detect_issues()
        stale_issues = [i for i in issues if i.issue_id == "stale_sessions"]
        assert len(stale_issues) == 0


# ===========================================================================
# 4. SelfHealingEngine.auto_fix — unknown issue_id returns error dict
# ===========================================================================


class TestAutoFixUnknown:
    async def test_unknown_issue_returns_success_false(self, db_path: str) -> None:
        s = _make_settings(db_path=db_path)
        engine = SelfHealingEngine(db_path=db_path, settings=s)
        result = await engine.auto_fix("totally_fake_issue_xyz")
        assert result["success"] is False
        assert "totally_fake_issue_xyz" in result["message"]

    async def test_unknown_issue_does_not_raise(self, db_path: str) -> None:
        s = _make_settings(db_path=db_path)
        engine = SelfHealingEngine(db_path=db_path, settings=s)
        # Must not raise — returns dict
        result = await engine.auto_fix("nonexistent")
        assert isinstance(result, dict)

    async def test_unknown_issue_result_has_required_keys(self, db_path: str) -> None:
        s = _make_settings(db_path=db_path)
        engine = SelfHealingEngine(db_path=db_path, settings=s)
        result = await engine.auto_fix("nonexistent")
        assert {"issue_id", "success", "message", "attempted_at", "duration_ms"}.issubset(
            result.keys()
        )


# ===========================================================================
# 5. SelfHealingEngine.auto_fix — stale_sessions removes old rows
# ===========================================================================


class TestAutoFixStaleSessions:
    async def test_fix_stale_sessions_succeeds(self, db_path: str) -> None:
        await _seed_stale_sessions(db_path, count=10)
        s = _make_settings(db_path=db_path)
        engine = SelfHealingEngine(db_path=db_path, settings=s)
        result = await engine.auto_fix("stale_sessions")
        assert result["success"] is True

    async def test_fix_stale_sessions_removes_rows(self, db_path: str) -> None:
        await _seed_stale_sessions(db_path, count=10)
        s = _make_settings(db_path=db_path)
        engine = SelfHealingEngine(db_path=db_path, settings=s)
        await engine.auto_fix("stale_sessions")
        # Count remaining stale sessions — should be 0
        stale_cutoff = (
            datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
        ).isoformat()
        async with aiosqlite.connect(db_path) as conn:
            rows = await conn.execute_fetchall(
                "SELECT COUNT(*) FROM agent_sessions WHERE updated_at < ?",
                (stale_cutoff,),
            )
        remaining = rows[0][0] if rows else -1
        assert remaining == 0

    async def test_fix_records_added_to_history(self, db_path: str) -> None:
        s = _make_settings(db_path=db_path)
        engine = SelfHealingEngine(db_path=db_path, settings=s)
        assert len(engine.get_fix_history()) == 0
        await engine.auto_fix("stale_sessions")
        assert len(engine.get_fix_history()) == 1


# ===========================================================================
# 6. SelfHealingEngine.auto_fix — missing_tables triggers schema init
# ===========================================================================


class TestAutoFixMissingTables:
    async def test_fix_missing_tables_returns_dict(self, db_path: str) -> None:
        s = _make_settings(db_path=db_path)
        engine = SelfHealingEngine(db_path=db_path, settings=s)
        result = await engine.auto_fix("missing_tables")
        assert isinstance(result, dict)
        assert result["issue_id"] == "missing_tables"


# ===========================================================================
# 7. SelfHealingEngine.run_diagnostics — full DiagnosticReport shape
# ===========================================================================


class TestRunDiagnostics:
    async def test_returns_expected_top_level_keys(self, db_path: str) -> None:
        s = _make_settings(db_path=db_path)
        engine = SelfHealingEngine(db_path=db_path, settings=s)
        result = await engine.run_diagnostics()
        assert {"overall_status", "checks", "issues", "generated_at", "duration_ms"}.issubset(
            result.keys()
        )

    async def test_checks_is_non_empty_list(self, db_path: str) -> None:
        s = _make_settings(db_path=db_path)
        engine = SelfHealingEngine(db_path=db_path, settings=s)
        result = await engine.run_diagnostics()
        assert isinstance(result["checks"], list)
        assert len(result["checks"]) > 0

    async def test_each_check_has_required_fields(self, db_path: str) -> None:
        s = _make_settings(db_path=db_path)
        engine = SelfHealingEngine(db_path=db_path, settings=s)
        result = await engine.run_diagnostics()
        for check in result["checks"]:
            assert {"name", "status", "message", "duration_ms", "checked_at"}.issubset(
                check.keys()
            )

    async def test_overall_status_is_valid_value(self, db_path: str) -> None:
        s = _make_settings(db_path=db_path)
        engine = SelfHealingEngine(db_path=db_path, settings=s)
        result = await engine.run_diagnostics()
        assert result["overall_status"] in ("healthy", "degraded", "critical")


# ===========================================================================
# 8. SelfHealingEngine.get_fix_history — accumulates records
# ===========================================================================


class TestGetFixHistory:
    async def test_empty_on_fresh_engine(self, db_path: str) -> None:
        s = _make_settings(db_path=db_path)
        engine = SelfHealingEngine(db_path=db_path, settings=s)
        assert engine.get_fix_history() == []

    async def test_accumulates_after_multiple_fixes(self, db_path: str) -> None:
        # Only known fixable issues are appended to history.
        # Unknown issue_ids return early without recording.
        s = _make_settings(db_path=db_path)
        engine = SelfHealingEngine(db_path=db_path, settings=s)
        await engine.auto_fix("stale_sessions")
        await engine.auto_fix("missing_tables")
        history = engine.get_fix_history()
        assert len(history) == 2

    async def test_history_records_have_expected_keys(self, db_path: str) -> None:
        s = _make_settings(db_path=db_path)
        engine = SelfHealingEngine(db_path=db_path, settings=s)
        await engine.auto_fix("stale_sessions")
        history = engine.get_fix_history()
        assert len(history) == 1
        rec = history[0]
        assert {"issue_id", "attempted_at", "success", "message", "duration_ms"}.issubset(
            rec.keys()
        )


# ===========================================================================
# 9-20. POST /admin/command — enhanced command routing (HTTP tests)
# ===========================================================================


class TestAdminCommandRouting:
    async def test_status_command_returns_200(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/command",
            json={"command": "status"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "response" in data
        assert "status" in data["response"]

    async def test_diagnose_command_returns_diagnostic_shape(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/command",
            json={"command": "diagnose"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        response = data["response"]
        assert "overall_status" in response
        assert "checks" in response

    async def test_issues_command_returns_list(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/command",
            json={"command": "issues"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "count" in data["response"]
        assert "issues" in data["response"]
        assert isinstance(data["response"]["issues"], list)

    async def test_fix_command_returns_fix_result(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/command",
            json={"command": "fix stale_sessions"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "issue_id" in data["response"]
        assert data["response"]["issue_id"] == "stale_sessions"

    async def test_fix_unknown_issue_returns_success_false(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/command",
            json={"command": "fix totally_nonexistent_xyz"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["response"]["success"] is False

    async def test_history_command_returns_history(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/command",
            json={"command": "history"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "count" in data["response"]
        assert "history" in data["response"]

    async def test_health_command_returns_checks(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/command",
            json={"command": "health"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "overall_status" in data["response"]
        assert "checks" in data["response"]

    async def test_errors_command_returns_recent_errors(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/command",
            json={"command": "errors"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "recent_errors" in data["response"]
        assert isinstance(data["response"]["recent_errors"], list)

    async def test_env_check_returns_var_status(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/command",
            json={"command": "env-check"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        response = data["response"]
        assert "vars" in response
        assert "missing_count" in response
        # Verify no actual secret values are returned
        for var_entry in response["vars"]:
            assert "value" not in var_entry
            assert "set" in var_entry

    async def test_restart_check_returns_diagnostic(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/command",
            json={"command": "restart-check"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "overall_status" in data["response"]

    async def test_help_command_lists_all_commands(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/command",
            json={"command": "help"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        help_text = data["response"].get("help", "")
        # All ten new commands must appear in help text
        for cmd in ("status", "diagnose", "issues", "fix", "history", "health",
                    "errors", "env-check", "restart-check"):
            assert cmd in help_text

    async def test_unknown_command_returns_help_not_4xx(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/command",
            json={"command": "xyzzy_not_a_command"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "help" in data["response"]

    async def test_empty_command_returns_422(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.post(
            "/api/v1/admin/command",
            json={"command": ""},
            headers=_admin_headers(),
        )
        assert resp.status_code == 422


# ===========================================================================
# 21-24. GET /admin/priorities
# ===========================================================================


class TestGetPriorities:
    async def test_non_admin_returns_403(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get(
            "/api/v1/admin/priorities",
            headers=_non_admin_headers(),
        )
        assert resp.status_code == 403

    async def test_unauthenticated_returns_401(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get("/api/v1/admin/priorities")
        assert resp.status_code == 401

    async def test_admin_returns_200_with_expected_shape(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get(
            "/api/v1/admin/priorities",
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "priorities" in data
        assert "system_health" in data
        assert "last_check" in data
        assert "total" in data

    async def test_stripe_test_key_appears_as_critical_priority(self, ctx: ClientCtx) -> None:
        """Fixture sets sk_test_healing_fixture — stripe_test_mode must appear."""
        resp = await ctx.ac.get(
            "/api/v1/admin/priorities",
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        priorities = data["priorities"]
        stripe_prios = [
            p for p in priorities
            if "stripe" in p.get("title", "").lower() or p.get("category") == "revenue"
        ]
        assert len(stripe_prios) >= 1
        assert stripe_prios[0]["severity"] == "critical"

    async def test_priorities_sorted_critical_first(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get(
            "/api/v1/admin/priorities",
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        priorities = data["priorities"]
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        for i in range(len(priorities) - 1):
            assert severity_order.get(priorities[i]["severity"], 99) <= severity_order.get(
                priorities[i + 1]["severity"], 99
            )

    async def test_each_priority_has_required_fields(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get(
            "/api/v1/admin/priorities",
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        for p in data["priorities"]:
            assert "rank" in p
            assert "category" in p
            assert "severity" in p
            assert "title" in p
            assert "description" in p
            assert "action" in p
            assert "detected_at" in p

    async def test_system_health_is_valid_value(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get(
            "/api/v1/admin/priorities",
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["system_health"] in ("healthy", "degraded", "critical")

    async def test_rank_starts_at_1(self, ctx: ClientCtx) -> None:
        resp = await ctx.ac.get(
            "/api/v1/admin/priorities",
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        if data["priorities"]:
            assert data["priorities"][0]["rank"] == 1
