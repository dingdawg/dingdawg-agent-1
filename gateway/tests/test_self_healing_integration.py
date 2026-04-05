"""Integration tests for the self-healing + system health monitoring system.

Covers scenarios not addressed by test_self_healing.py and test_system_health.py:

1.  detect_issues — high error rate (>100) triggers critical issue
2.  detect_issues — elevated error rate (>20 <=100) triggers warning issue
3.  detect_issues — error rate below threshold produces no error_rate issue
4.  detect_issues — error rate at exactly 20 produces no issue (boundary)
5.  detect_issues — DB unreachable returns single critical issue immediately
6.  detect_issues — returns only db_unreachable when DB is down (early exit)
7.  detect_issues — stale session boundary: exactly 500 does NOT trigger (>500 required)
8.  detect_issues — 501 stale sessions triggers the issue
9.  detect_issues — Stripe key absent produces warning (not critical)
10. detect_issues — missing env vars detected (category=env, severity=critical)
11. detect_issues — env var present but whitespace-only counts as missing
12. auto_fix — history pruned at _MAX_FIX_HISTORY (200 entries cap)
13. auto_fix — stale_sessions on empty DB succeeds (0 deleted is still success)
14. auto_fix — stale_sessions with invalid DB path returns failure dict, not exception
15. auto_fix — fix history record has correct issue_id for stale_sessions
16. auto_fix — fix history record has correct issue_id for missing_tables
17. run_diagnostics — contains exactly 7 named checks
18. run_diagnostics — all check names are unique
19. run_diagnostics — all 7 expected check names are present
20. run_diagnostics — overall_status critical when DB unreachable
21. run_diagnostics — issues list in report matches standalone detect_issues output
22. get_system_status — error_count_1h > 50 produces degraded status
23. get_system_status — error_count_1h at exactly 50 is still healthy
24. get_system_status — error_count_1h value is returned in result dict
25. _compute_per_provider_error_rates — returns rates for seeded entries
26. _compute_per_provider_error_rates — returns empty dict on bad DB path
27. _compute_per_provider_error_rates — ignores entries with malformed JSON details
28. _compute_per_provider_error_rates — ignores unknown/none provider names
29. _compute_per_provider_error_rates — zero error rate when all entries are successes
30. system health endpoint — self_healing.auto_recovered list is present
31. system health endpoint — circuit_breakers database is CLOSED on healthy DB
32. system health endpoint — circuit_breakers has at least 3 entries
33. system health endpoint — all circuit breaker values are valid state strings
34. integration health check — check name present in diagnostics
35. integration health check — status is ok or unknown when no agent_integrations table
36. integration health check — message reflects connected integrations when table exists
37. self-test endpoint — stripe test mode result is pass (recognised format)
38. self-test endpoint — stripe missing is recorded as fail
39. self-test endpoint — all result entries have required keys
40. self-test endpoint — llm_providers fails when no API keys configured
41. self-test endpoint — result values are only "pass" or "fail"
42. self-test endpoint — duration_ms is non-negative for all results

NOTE on test structure: tests using the ``db_path`` fixture are written as
module-level functions (not class methods).  When pytest-asyncio runs async
methods inside a class under asyncio_mode=auto, all methods in the class share
the same event loop.  The ``db_path`` fixture runs a full app lifespan per
invocation — and the app's module-level DB singleton (engine.py) is NOT reset
between tests in the same event loop, causing the 2nd+ test in a class to
receive a fresh ``tmp_path`` but find an empty (schema-less) DB file.
Standalone functions each get an independent event loop, preventing this.
"""

from __future__ import annotations

import json
import os
import uuid
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

import aiosqlite
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from isg_agent.api.routes.auth import _create_token
from isg_agent.api.routes.system_health import _compute_per_provider_error_rates
from isg_agent.config import Settings, get_settings
from isg_agent.core.self_healing import (
    SelfHealingEngine,
    _MAX_FIX_HISTORY,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SECRET = "test-secret-sh-integration"
_ADMIN_EMAIL = "admin@sh-integration-test.com"
_ADMIN_USER_ID = "admin-shi-001"
_NON_ADMIN_EMAIL = "user@sh-integration-test.com"
_NON_ADMIN_USER_ID = "nonadmin-shi-002"

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
# Settings factory
# ---------------------------------------------------------------------------


def _make_settings(stripe_key: str = "sk_test_x", db_path: str = "") -> Settings:
    """Build a minimal Settings object for direct engine unit tests."""
    return Settings(
        secret_key=_SECRET,
        db_path=db_path,
        stripe_secret_key=stripe_key,
        sendgrid_api_key="",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(loop_scope="function")
async def db_path(tmp_path) -> AsyncIterator[str]:
    """Fully initialised DB path for direct engine tests.

    Creates the database schema directly — bypassing lifespan entirely — to
    avoid the module-level DB singleton contamination that occurs when
    multiple tests run in the same pytest worker process.

    The core schema (schema.create_tables) plus the lazily-created tables
    that SelfHealingEngine queries (agent_sessions, memory_messages) are
    created via explicit DDL imported from their canonical source modules.
    This approach is hermetic: each test gets an isolated DB with known
    schema, regardless of what other tests or fixtures have run before it.
    """
    db_file = str(tmp_path / "test_shi_engine.db")

    _prev_db = os.environ.get("ISG_AGENT_DB_PATH")
    _prev_secret = os.environ.get("ISG_AGENT_SECRET_KEY")
    _prev_stripe = os.environ.get("ISG_AGENT_STRIPE_SECRET_KEY")

    os.environ["ISG_AGENT_DB_PATH"] = db_file
    os.environ["ISG_AGENT_SECRET_KEY"] = _SECRET
    os.environ["ISG_AGENT_STRIPE_SECRET_KEY"] = "sk_test_shi_fixture"
    get_settings.cache_clear()

    # Import DDL strings from canonical source modules — single source of truth.
    from isg_agent.db.schema import create_tables
    from isg_agent.brain.session import (
        _CREATE_TABLE_SQL as _AGENT_SESSIONS_DDL,
        _CREATE_INDEX_USER_SQL as _AGENT_SESSIONS_IDX_USER,
        _CREATE_INDEX_STATUS_SQL as _AGENT_SESSIONS_IDX_STATUS,
    )
    from isg_agent.memory.store import (
        _CREATE_TABLE_SQL as _MEMORY_MESSAGES_DDL,
    )

    async with aiosqlite.connect(db_file) as conn:
        # Core schema (audit_chain, agents, agent_handles, etc.)
        await create_tables(conn)
        # Lazy-init tables that SelfHealingEngine queries directly
        await conn.execute(_AGENT_SESSIONS_DDL)
        await conn.execute(_AGENT_SESSIONS_IDX_USER)
        await conn.execute(_AGENT_SESSIONS_IDX_STATUS)
        await conn.execute(_MEMORY_MESSAGES_DDL)
        await conn.commit()

    try:
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


@pytest_asyncio.fixture(loop_scope="function")
async def ctx(tmp_path) -> AsyncIterator[ClientCtx]:
    """HTTP client with fully initialised app lifespan + DB path."""
    db_file = str(tmp_path / "test_shi_http.db")

    _prev_db = os.environ.get("ISG_AGENT_DB_PATH")
    _prev_secret = os.environ.get("ISG_AGENT_SECRET_KEY")
    _prev_admin = os.environ.get("ISG_AGENT_ADMIN_EMAIL")
    _prev_stripe = os.environ.get("ISG_AGENT_STRIPE_SECRET_KEY")

    os.environ["ISG_AGENT_DB_PATH"] = db_file
    os.environ["ISG_AGENT_SECRET_KEY"] = _SECRET
    os.environ["ISG_AGENT_ADMIN_EMAIL"] = _ADMIN_EMAIL
    os.environ["ISG_AGENT_STRIPE_SECRET_KEY"] = "sk_test_shi_http_fixture"
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


# ---------------------------------------------------------------------------
# DB seed helpers
# ---------------------------------------------------------------------------


async def _seed_audit_errors(db: str, count: int, event_type: str = "error") -> None:
    """Insert ``count`` error-type audit entries with timestamps in the last hour."""
    now_iso = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    async with aiosqlite.connect(db) as conn:
        for i in range(count):
            await conn.execute(
                """
                INSERT INTO audit_chain
                    (timestamp, event_type, actor, details, entry_hash, prev_hash)
                VALUES (?, ?, 'test-actor', ?, ?, ?)
                """,
                (
                    now_iso,
                    event_type,
                    json.dumps({"error": f"test error {i}"}),
                    f"hash-err-{i}-{uuid.uuid4().hex[:8]}",
                    f"prev-hash-{i}",
                ),
            )
        await conn.commit()


async def _seed_stale_sessions(db: str, count: int) -> None:
    """Insert ``count`` sessions last updated 8 days ago (stale threshold = 7 days)."""
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
                VALUES (?, 'user-stale', ?, ?, 'completed')
                """,
                (sess_id, stale_ts, stale_ts),
            )
        await conn.commit()


async def _seed_agent_response(
    db: str,
    provider: str,
    is_error: bool = False,
    event_type: str = "agent_response",
) -> None:
    """Seed one agent_response audit entry for per-provider error rate tests."""
    now_iso = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    det: dict = {"provider": provider}
    if is_error:
        det["llm_error"] = "connection timeout"
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            """
            INSERT INTO audit_chain
                (timestamp, event_type, actor, details, entry_hash, prev_hash)
            VALUES (?, ?, 'test-actor', ?, ?, 'prevhash')
            """,
            (now_iso, event_type, json.dumps(det), str(uuid.uuid4())),
        )
        await conn.commit()


# ===========================================================================
# 1-4. detect_issues — error rate thresholds
# ===========================================================================


async def test_high_error_rate_critical(db_path: str) -> None:
    """More than 100 errors in the last hour must trigger a critical issue."""
    await _seed_audit_errors(db_path, count=101)
    s = _make_settings(stripe_key="sk_live_real", db_path=db_path)
    engine = SelfHealingEngine(db_path=db_path, settings=s)
    issues = await engine.detect_issues()
    err_issues = [i for i in issues if i.issue_id == "high_error_rate"]
    assert len(err_issues) == 1
    assert err_issues[0].severity == "critical"


async def test_elevated_error_rate_warning(db_path: str) -> None:
    """Between 21 and 100 errors triggers an elevated_error_rate warning."""
    await _seed_audit_errors(db_path, count=25)
    s = _make_settings(stripe_key="sk_live_real", db_path=db_path)
    engine = SelfHealingEngine(db_path=db_path, settings=s)
    issues = await engine.detect_issues()
    err_issues = [i for i in issues if i.issue_id == "elevated_error_rate"]
    assert len(err_issues) == 1
    assert err_issues[0].severity == "warning"


async def test_low_error_rate_no_issue(db_path: str) -> None:
    """Fewer than 20 errors must not trigger any error-rate issue."""
    await _seed_audit_errors(db_path, count=5)
    s = _make_settings(stripe_key="sk_live_real", db_path=db_path)
    engine = SelfHealingEngine(db_path=db_path, settings=s)
    issues = await engine.detect_issues()
    err_issues = [
        i for i in issues
        if i.issue_id in ("high_error_rate", "elevated_error_rate")
    ]
    assert len(err_issues) == 0


async def test_error_rate_threshold_at_exactly_20_no_issue(db_path: str) -> None:
    """Exactly 20 errors is at the boundary — no issue (threshold is >20)."""
    await _seed_audit_errors(db_path, count=20)
    s = _make_settings(stripe_key="sk_live_real", db_path=db_path)
    engine = SelfHealingEngine(db_path=db_path, settings=s)
    issues = await engine.detect_issues()
    err_issues = [
        i for i in issues
        if i.issue_id in ("high_error_rate", "elevated_error_rate")
    ]
    assert len(err_issues) == 0


# ===========================================================================
# 5-6. detect_issues — DB unreachable path
# ===========================================================================


async def test_detect_issues_db_unreachable_critical() -> None:
    """When DB path is invalid, detect_issues returns a single critical issue."""
    s = _make_settings(db_path="/nonexistent/path/nowhere.db")
    engine = SelfHealingEngine(db_path="/nonexistent/path/nowhere.db", settings=s)
    issues = await engine.detect_issues()
    db_issues = [i for i in issues if i.issue_id == "db_unreachable"]
    assert len(db_issues) == 1
    assert db_issues[0].severity == "critical"
    assert db_issues[0].auto_fixable is False


async def test_detect_issues_db_unreachable_early_exit() -> None:
    """When DB is unreachable, detect_issues returns early — first issue is db_unreachable."""
    s = _make_settings(db_path="/nonexistent/path/nowhere.db")
    engine = SelfHealingEngine(db_path="/nonexistent/path/nowhere.db", settings=s)
    issues = await engine.detect_issues()
    assert len(issues) >= 1
    assert issues[0].issue_id == "db_unreachable"


# ===========================================================================
# 7-8. detect_issues — stale session count boundaries
# ===========================================================================


async def test_exactly_500_stale_sessions_no_issue(db_path: str) -> None:
    """Threshold is >500 — exactly 500 stale sessions must NOT produce the issue."""
    await _seed_stale_sessions(db_path, count=500)
    s = _make_settings(stripe_key="sk_live_x", db_path=db_path)
    engine = SelfHealingEngine(db_path=db_path, settings=s)
    issues = await engine.detect_issues()
    stale_issues = [i for i in issues if i.issue_id == "stale_sessions"]
    assert len(stale_issues) == 0


async def test_501_stale_sessions_triggers_issue(db_path: str) -> None:
    """501 stale sessions must trigger the stale_sessions issue."""
    await _seed_stale_sessions(db_path, count=501)
    s = _make_settings(stripe_key="sk_live_x", db_path=db_path)
    engine = SelfHealingEngine(db_path=db_path, settings=s)
    issues = await engine.detect_issues()
    stale_issues = [i for i in issues if i.issue_id == "stale_sessions"]
    assert len(stale_issues) == 1


# ===========================================================================
# 9-11. detect_issues — Stripe absent; missing/empty env vars
# ===========================================================================


async def test_stripe_key_absent_produces_warning(db_path: str) -> None:
    """Empty stripe key must produce a warning-level stripe_test_mode issue."""
    s = _make_settings(stripe_key="", db_path=db_path)
    engine = SelfHealingEngine(db_path=db_path, settings=s)
    issues = await engine.detect_issues()
    stripe_issues = [i for i in issues if i.issue_id == "stripe_test_mode"]
    assert len(stripe_issues) == 1
    assert stripe_issues[0].severity == "warning"


async def test_missing_env_var_detected(db_path: str) -> None:
    """When a critical env var is absent, missing_env_vars issue must appear."""
    original = os.environ.pop("ISG_AGENT_SENDGRID_API_KEY", None)
    try:
        s = _make_settings(db_path=db_path)
        engine = SelfHealingEngine(db_path=db_path, settings=s)
        issues = await engine.detect_issues()
        env_issues = [i for i in issues if i.issue_id == "missing_env_vars"]
        assert len(env_issues) >= 1
        assert env_issues[0].severity == "critical"
        assert env_issues[0].category == "env"
    finally:
        if original is not None:
            os.environ["ISG_AGENT_SENDGRID_API_KEY"] = original


async def test_empty_env_var_counts_as_missing(db_path: str) -> None:
    """A whitespace-only env var must be treated as missing."""
    original = os.environ.get("ISG_AGENT_SENDGRID_API_KEY")
    os.environ["ISG_AGENT_SENDGRID_API_KEY"] = "   "
    try:
        s = _make_settings(db_path=db_path)
        engine = SelfHealingEngine(db_path=db_path, settings=s)
        issues = await engine.detect_issues()
        env_issues = [i for i in issues if i.issue_id == "missing_env_vars"]
        assert len(env_issues) >= 1
    finally:
        if original is None:
            os.environ.pop("ISG_AGENT_SENDGRID_API_KEY", None)
        else:
            os.environ["ISG_AGENT_SENDGRID_API_KEY"] = original


# ===========================================================================
# 12-16. auto_fix — history pruning; bad DB path; correct issue_ids
# ===========================================================================


async def test_history_pruned_at_max_fix_history(db_path: str) -> None:
    """After _MAX_FIX_HISTORY + N calls the history list stays capped at MAX."""
    s = _make_settings(db_path=db_path)
    engine = SelfHealingEngine(db_path=db_path, settings=s)
    for _ in range(_MAX_FIX_HISTORY + 5):
        await engine.auto_fix("stale_sessions")
    assert len(engine.get_fix_history()) == _MAX_FIX_HISTORY


async def test_fix_stale_sessions_empty_db_succeeds(db_path: str) -> None:
    """Fixing stale sessions when none exist must succeed (0 deleted is valid)."""
    s = _make_settings(db_path=db_path)
    engine = SelfHealingEngine(db_path=db_path, settings=s)
    result = await engine.auto_fix("stale_sessions")
    assert result["success"] is True
    assert "0" in result["message"] or "Deleted" in result["message"]


async def test_fix_stale_sessions_bad_db_returns_failure_dict(tmp_path) -> None:
    """When the DB path is in a non-existent directory, fix returns a failure dict."""
    bad_path = str(tmp_path / "nonexistent_dir" / "bad.db")
    s = _make_settings(db_path=bad_path)
    engine = SelfHealingEngine(db_path=bad_path, settings=s)
    result = await engine.auto_fix("stale_sessions")
    assert isinstance(result, dict)
    assert result["success"] is False
    assert result["issue_id"] == "stale_sessions"


async def test_stale_sessions_history_issue_id_correct(db_path: str) -> None:
    """Fix history entry for stale_sessions must record the correct issue_id."""
    s = _make_settings(db_path=db_path)
    engine = SelfHealingEngine(db_path=db_path, settings=s)
    await engine.auto_fix("stale_sessions")
    history = engine.get_fix_history()
    assert len(history) == 1
    assert history[0]["issue_id"] == "stale_sessions"


async def test_missing_tables_history_issue_id_correct(db_path: str) -> None:
    """Fix history entry for missing_tables must record the correct issue_id."""
    s = _make_settings(db_path=db_path)
    engine = SelfHealingEngine(db_path=db_path, settings=s)
    await engine.auto_fix("missing_tables")
    history = engine.get_fix_history()
    assert len(history) == 1
    assert history[0]["issue_id"] == "missing_tables"


# ===========================================================================
# 17-21. run_diagnostics — check count, uniqueness, overall_status scenarios
# ===========================================================================


async def test_diagnostics_contains_7_checks(db_path: str) -> None:
    """Exactly 7 health checks must be present in every diagnostic report."""
    s = _make_settings(db_path=db_path)
    engine = SelfHealingEngine(db_path=db_path, settings=s)
    result = await engine.run_diagnostics()
    assert len(result["checks"]) == 7


async def test_all_check_names_are_unique(db_path: str) -> None:
    """No two health checks may share the same name."""
    s = _make_settings(db_path=db_path)
    engine = SelfHealingEngine(db_path=db_path, settings=s)
    result = await engine.run_diagnostics()
    names = [c["name"] for c in result["checks"]]
    assert len(names) == len(set(names)), f"Duplicate check names: {names}"


async def test_known_check_names_present(db_path: str) -> None:
    """All 7 expected check names must be present in the diagnostic report."""
    expected_names = {
        "db_connectivity",
        "required_tables",
        "error_rate_1h",
        "memory_usage",
        "disk_space",
        "stripe_config",
        "integration_health",
    }
    s = _make_settings(db_path=db_path)
    engine = SelfHealingEngine(db_path=db_path, settings=s)
    result = await engine.run_diagnostics()
    actual_names = {c["name"] for c in result["checks"]}
    assert expected_names == actual_names


async def test_overall_critical_when_db_unreachable() -> None:
    """overall_status must be 'critical' when the database is unreachable."""
    s = _make_settings(db_path="/nonexistent/path/nowhere.db")
    engine = SelfHealingEngine(db_path="/nonexistent/path/nowhere.db", settings=s)
    result = await engine.run_diagnostics()
    assert result["overall_status"] == "critical"


async def test_issues_in_report_match_detect_issues(db_path: str) -> None:
    """Issue IDs in the diagnostic report must match a standalone detect_issues call."""
    s = _make_settings(stripe_key="sk_test_match", db_path=db_path)
    engine = SelfHealingEngine(db_path=db_path, settings=s)
    standalone_issues = await engine.detect_issues()
    report = await engine.run_diagnostics()
    report_issue_ids = {i["issue_id"] for i in report["issues"]}
    standalone_issue_ids = {i.issue_id for i in standalone_issues}
    assert report_issue_ids == standalone_issue_ids


# ===========================================================================
# 22-24. get_system_status — degraded/healthy based on error_count_1h
# ===========================================================================


async def test_error_count_over_50_produces_degraded(db_path: str) -> None:
    """51+ errors in the last hour must set status to 'degraded'."""
    await _seed_audit_errors(db_path, count=51)
    s = _make_settings(db_path=db_path)
    engine = SelfHealingEngine(db_path=db_path, settings=s)
    result = await engine.get_system_status()
    assert result["status"] == "degraded"


async def test_error_count_at_exactly_50_is_healthy(db_path: str) -> None:
    """Threshold is >50 — exactly 50 errors must not degrade status."""
    await _seed_audit_errors(db_path, count=50)
    s = _make_settings(db_path=db_path)
    engine = SelfHealingEngine(db_path=db_path, settings=s)
    result = await engine.get_system_status()
    assert result["status"] == "healthy"


async def test_error_count_returned_in_result(db_path: str) -> None:
    """error_count_1h in the result dict must reflect the number of seeded errors."""
    await _seed_audit_errors(db_path, count=3)
    s = _make_settings(db_path=db_path)
    engine = SelfHealingEngine(db_path=db_path, settings=s)
    result = await engine.get_system_status()
    assert result["error_count_1h"] >= 3


# ===========================================================================
# 25-29. _compute_per_provider_error_rates — unit tests
# ===========================================================================


async def test_provider_rates_returns_rates_for_seeded_entries(db_path: str) -> None:
    """1 success + 1 error for openai must produce a 0.5 error rate."""
    cutoff = (
        datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    ).isoformat()
    await _seed_agent_response(db_path, provider="openai", is_error=False)
    await _seed_agent_response(db_path, provider="openai", is_error=True)
    rates = await _compute_per_provider_error_rates(db_path, cutoff)
    assert "openai" in rates
    assert rates["openai"] == 0.5


async def test_provider_rates_returns_empty_dict_on_bad_db() -> None:
    """An unreachable DB path must return an empty dict, not raise."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    rates = await _compute_per_provider_error_rates("/nonexistent/bad_path.db", cutoff)
    assert rates == {}


async def test_provider_rates_ignores_malformed_json_details(db_path: str) -> None:
    """Rows with non-JSON details must be skipped without raising."""
    now_iso = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            """
            INSERT INTO audit_chain
                (timestamp, event_type, actor, details, entry_hash, prev_hash)
            VALUES (?, 'agent_response', 'test-actor', ?, 'hash-malform', 'prev')
            """,
            (now_iso, "not valid json {{{"),
        )
        await conn.commit()

    cutoff = (
        datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    ).isoformat()
    rates = await _compute_per_provider_error_rates(db_path, cutoff)
    assert isinstance(rates, dict)


async def test_provider_rates_ignores_unknown_provider_names(db_path: str) -> None:
    """Providers named 'none' or 'unknown' must be excluded from the result."""
    cutoff = (
        datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    ).isoformat()
    await _seed_agent_response(db_path, provider="none", is_error=False)
    await _seed_agent_response(db_path, provider="unknown", is_error=False)
    rates = await _compute_per_provider_error_rates(db_path, cutoff)
    assert "none" not in rates
    assert "unknown" not in rates


async def test_provider_rates_zero_for_all_successes(db_path: str) -> None:
    """When all entries for a provider are successes, error rate must be 0.0."""
    cutoff = (
        datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    ).isoformat()
    await _seed_agent_response(db_path, provider="anthropic", is_error=False)
    await _seed_agent_response(db_path, provider="anthropic", is_error=False)
    rates = await _compute_per_provider_error_rates(db_path, cutoff)
    assert rates.get("anthropic") == 0.0


# ===========================================================================
# 30. System health endpoint — auto_recovered list
# ===========================================================================


async def test_auto_recovered_list_present(ctx: ClientCtx) -> None:
    """auto_recovered key must exist and be a list in every health response."""
    resp = await ctx.ac.get("/api/v1/admin/system/health", headers=_admin_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert "auto_recovered" in data["self_healing"]
    assert isinstance(data["self_healing"]["auto_recovered"], list)


# ===========================================================================
# 31-33. Circuit breaker state assertions
# ===========================================================================


async def test_circuit_breakers_database_closed_on_healthy_db(ctx: ClientCtx) -> None:
    """database circuit breaker must be CLOSED when the DB is reachable."""
    resp = await ctx.ac.get("/api/v1/admin/system/health", headers=_admin_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data["self_healing"]["circuit_breakers"]["database"] == "CLOSED"


async def test_circuit_breakers_has_multiple_entries(ctx: ClientCtx) -> None:
    """At least 3 circuit breaker entries must be present (openai, stripe, database)."""
    resp = await ctx.ac.get("/api/v1/admin/system/health", headers=_admin_headers())
    assert resp.status_code == 200
    data = resp.json()
    cbs = data["self_healing"]["circuit_breakers"]
    assert len(cbs) >= 3


async def test_circuit_breaker_values_are_valid_states(ctx: ClientCtx) -> None:
    """Every circuit breaker value must be CLOSED, OPEN, or HALF_OPEN."""
    valid_states = {"CLOSED", "OPEN", "HALF_OPEN"}
    resp = await ctx.ac.get("/api/v1/admin/system/health", headers=_admin_headers())
    assert resp.status_code == 200
    data = resp.json()
    for name, state in data["self_healing"]["circuit_breakers"].items():
        assert state in valid_states, (
            f"Circuit breaker '{name}' has invalid state '{state}'"
        )


# ===========================================================================
# 34-36. Integration health check
# ===========================================================================


async def test_integration_health_check_name_in_diagnostics(db_path: str) -> None:
    """The 'integration_health' check must appear in every diagnostic report."""
    s = _make_settings(db_path=db_path)
    engine = SelfHealingEngine(db_path=db_path, settings=s)
    result = await engine.run_diagnostics()
    names = [c["name"] for c in result["checks"]]
    assert "integration_health" in names


async def test_integration_health_check_ok_or_unknown_on_empty(db_path: str) -> None:
    """When agent_integrations table is absent or empty, check reports ok or unknown.

    The agent_integrations table is not part of the core schema (schema.py)
    and may not exist in a fresh test DB.  The self_healing check fails-open
    and returns 'unknown' when the table is absent, or 'ok' when empty.
    Both outcomes are valid — we assert neither is an error-level status.
    """
    s = _make_settings(db_path=db_path)
    engine = SelfHealingEngine(db_path=db_path, settings=s)
    result = await engine.run_diagnostics()
    int_check = next(
        (c for c in result["checks"] if c["name"] == "integration_health"), None
    )
    assert int_check is not None
    assert int_check["status"] in ("ok", "unknown"), (
        f"Expected 'ok' or 'unknown', got '{int_check['status']}'"
    )


async def test_integration_health_check_ok_with_table_present(db_path: str) -> None:
    """When agent_integrations table exists and has rows, check reports 'ok'
    and the message references the integration type.
    """
    # Create the table inline — it is not part of the core schema
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_integrations (
                id               TEXT PRIMARY KEY,
                agent_id         TEXT NOT NULL,
                integration_type TEXT NOT NULL,
                config_json      TEXT NOT NULL DEFAULT '{}',
                created_at       TEXT NOT NULL,
                updated_at       TEXT NOT NULL
            )
            """
        )
        await conn.execute(
            """
            INSERT OR IGNORE INTO agent_integrations
                (id, agent_id, integration_type, config_json, created_at, updated_at)
            VALUES ('int-1', 'agent-1', 'stripe', '{}',
                    datetime('now'), datetime('now'))
            """
        )
        await conn.commit()

    s = _make_settings(db_path=db_path)
    engine = SelfHealingEngine(db_path=db_path, settings=s)
    result = await engine.run_diagnostics()
    int_check = next(
        (c for c in result["checks"] if c["name"] == "integration_health"), None
    )
    assert int_check is not None
    assert int_check["status"] == "ok"
    assert "stripe" in int_check["message"].lower()


# ===========================================================================
# 37-42. self-test endpoint integration tests
# ===========================================================================


async def test_self_test_stripe_test_mode_is_pass(ctx: ClientCtx) -> None:
    """A sk_test_ Stripe key is a recognised format — test must be 'pass'."""
    resp = await ctx.ac.post(
        "/api/v1/admin/system/self-test", headers=_admin_headers()
    )
    assert resp.status_code == 200
    data = resp.json()
    stripe_result = next(
        (r for r in data["results"] if r["test"] == "stripe"), None
    )
    assert stripe_result is not None
    assert stripe_result["result"] == "pass"
    assert "TEST" in stripe_result["message"]


async def test_self_test_stripe_missing_is_fail(tmp_path) -> None:
    """When no Stripe key is set, the stripe self-test must report 'fail'."""
    db_file = str(tmp_path / "self_test_no_stripe.db")

    _prev_db = os.environ.get("ISG_AGENT_DB_PATH")
    _prev_secret = os.environ.get("ISG_AGENT_SECRET_KEY")
    _prev_admin = os.environ.get("ISG_AGENT_ADMIN_EMAIL")
    _prev_stripe = os.environ.get("ISG_AGENT_STRIPE_SECRET_KEY")

    os.environ["ISG_AGENT_DB_PATH"] = db_file
    os.environ["ISG_AGENT_SECRET_KEY"] = _SECRET
    os.environ["ISG_AGENT_ADMIN_EMAIL"] = _ADMIN_EMAIL
    os.environ.pop("ISG_AGENT_STRIPE_SECRET_KEY", None)
    get_settings.cache_clear()

    try:
        from isg_agent.app import create_app, lifespan

        app = create_app()
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.post(
                    "/api/v1/admin/system/self-test",
                    headers={
                        "Authorization": (
                            f"Bearer {_make_token(_ADMIN_USER_ID, _ADMIN_EMAIL)}"
                        )
                    },
                )
                data = resp.json()
                stripe_result = next(
                    (r for r in data["results"] if r["test"] == "stripe"), None
                )
                assert stripe_result is not None
                assert stripe_result["result"] == "fail"
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


async def test_self_test_all_result_entries_have_required_keys(
    ctx: ClientCtx,
) -> None:
    """Every result entry must have test, result, message, and duration_ms keys."""
    resp = await ctx.ac.post(
        "/api/v1/admin/system/self-test", headers=_admin_headers()
    )
    assert resp.status_code == 200
    data = resp.json()
    required_keys = {"test", "result", "message", "duration_ms"}
    for entry in data["results"]:
        assert required_keys.issubset(entry.keys()), (
            f"Result entry missing keys: {required_keys - set(entry.keys())}"
        )


async def test_self_test_llm_providers_fails_with_no_keys(ctx: ClientCtx) -> None:
    """In the test environment with no LLM API keys, llm_providers must fail."""
    resp = await ctx.ac.post(
        "/api/v1/admin/system/self-test", headers=_admin_headers()
    )
    assert resp.status_code == 200
    data = resp.json()
    llm_result = next(
        (r for r in data["results"] if r["test"] == "llm_providers"), None
    )
    assert llm_result is not None
    assert llm_result["result"] == "fail"
    msg_lower = llm_result["message"].lower()
    assert "no llm" in msg_lower or "providers" in msg_lower


async def test_self_test_result_values_are_pass_or_fail(ctx: ClientCtx) -> None:
    """All result entries must have a result value of exactly 'pass' or 'fail'."""
    resp = await ctx.ac.post(
        "/api/v1/admin/system/self-test", headers=_admin_headers()
    )
    assert resp.status_code == 200
    data = resp.json()
    for entry in data["results"]:
        assert entry["result"] in ("pass", "fail"), (
            f"Unexpected result value '{entry['result']}' on test '{entry['test']}'"
        )


async def test_self_test_duration_ms_non_negative_for_all_results(
    ctx: ClientCtx,
) -> None:
    """duration_ms must be >= 0 for every test result entry."""
    resp = await ctx.ac.post(
        "/api/v1/admin/system/self-test", headers=_admin_headers()
    )
    assert resp.status_code == 200
    data = resp.json()
    for entry in data["results"]:
        assert entry["duration_ms"] >= 0, (
            f"Negative duration_ms on test '{entry['test']}'"
        )


# ===========================================================================
# 43. _REQUIRED_TABLES registry — skill_notifications membership
# ===========================================================================


class TestRequiredTablesRegistry:
    async def test_required_tables_includes_skill_notifications(
        self, ctx: ClientCtx
    ) -> None:
        """skill_notifications must be in _REQUIRED_TABLES after schema fix."""
        from isg_agent.core.self_healing import _REQUIRED_TABLES

        assert "skill_notifications" in _REQUIRED_TABLES
