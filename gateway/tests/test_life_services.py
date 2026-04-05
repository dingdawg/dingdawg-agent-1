"""Unit tests for LifeServices usage tracking and tier enforcement.

Tests cover:
- record_usage (first record creates row, subsequent calls increment counters)
- get_usage (returns row, returns None for unknown agent/period)
- get_usage_history (most recent periods first, limit respected)
- check_tier_limits (free tier hit, scale tier unlimited, within limit)
- get_purchase_history (filters by task_type=purchase, status=completed)
- get_booking_history (filters by task_type=booking, status=completed)
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from isg_agent.personal.life_services import LifeServices
from isg_agent.personal.task_manager import TaskManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def svc():
    """Provide a LifeServices instance backed by a fresh in-memory DB."""
    s = LifeServices(db_path=":memory:")
    yield s
    await s.close()


@pytest_asyncio.fixture
async def svc_with_tasks():
    """Provide a LifeServices instance that shares DB with a TaskManager.

    Both use the default ':memory:' URI uniqueness pattern, so we create
    them independently — LifeServices owns agent_tasks for history queries.
    """
    s = LifeServices(db_path=":memory:")
    yield s
    await s.close()


# ---------------------------------------------------------------------------
# record_usage
# ---------------------------------------------------------------------------


class TestRecordUsage:
    """Tests for LifeServices.record_usage."""

    @pytest.mark.asyncio
    async def test_record_creates_new_row(self, svc):
        """First record call inserts a new row."""
        row = await svc.record_usage("agent-1", "2026-02", llm_tokens=100, api_calls=5)
        assert row["agent_id"] == "agent-1"
        assert row["period"] == "2026-02"
        assert row["llm_tokens"] == 100
        assert row["api_calls"] == 5
        assert row["tasks_completed"] == 0

    @pytest.mark.asyncio
    async def test_record_increments_existing_row(self, svc):
        """Subsequent calls increment counters, not overwrite."""
        await svc.record_usage("agent-1", "2026-02", llm_tokens=100)
        await svc.record_usage("agent-1", "2026-02", llm_tokens=200, tasks_completed=1)
        row = await svc.get_usage("agent-1", "2026-02")
        assert row is not None
        assert row["llm_tokens"] == 300
        assert row["tasks_completed"] == 1

    @pytest.mark.asyncio
    async def test_record_isolates_by_period(self, svc):
        """Records for different periods are stored separately."""
        await svc.record_usage("agent-1", "2026-01", api_calls=10)
        await svc.record_usage("agent-1", "2026-02", api_calls=20)

        jan = await svc.get_usage("agent-1", "2026-01")
        feb = await svc.get_usage("agent-1", "2026-02")

        assert jan["api_calls"] == 10
        assert feb["api_calls"] == 20

    @pytest.mark.asyncio
    async def test_record_isolates_by_agent(self, svc):
        """Records for different agents are stored separately."""
        await svc.record_usage("agent-A", "2026-02", cost_cents=100)
        await svc.record_usage("agent-B", "2026-02", cost_cents=200)

        a = await svc.get_usage("agent-A", "2026-02")
        b = await svc.get_usage("agent-B", "2026-02")

        assert a["cost_cents"] == 100
        assert b["cost_cents"] == 200


# ---------------------------------------------------------------------------
# get_usage
# ---------------------------------------------------------------------------


class TestGetUsage:
    """Tests for LifeServices.get_usage."""

    @pytest.mark.asyncio
    async def test_get_usage_not_found_returns_none(self, svc):
        """get_usage returns None when no data exists for the agent/period."""
        result = await svc.get_usage("no-such-agent", "2026-02")
        assert result is None


# ---------------------------------------------------------------------------
# get_usage_history
# ---------------------------------------------------------------------------


class TestGetUsageHistory:
    """Tests for LifeServices.get_usage_history."""

    @pytest.mark.asyncio
    async def test_get_usage_history_most_recent_first(self, svc):
        """get_usage_history returns periods in descending order."""
        for month in ["2025-11", "2025-12", "2026-01", "2026-02"]:
            await svc.record_usage("agent-1", month, api_calls=1)

        history = await svc.get_usage_history("agent-1")
        periods = [r["period"] for r in history]
        assert periods == sorted(periods, reverse=True)

    @pytest.mark.asyncio
    async def test_get_usage_history_respects_limit(self, svc):
        """get_usage_history respects the limit parameter."""
        for month in ["2025-10", "2025-11", "2025-12", "2026-01", "2026-02"]:
            await svc.record_usage("agent-1", month, api_calls=1)

        history = await svc.get_usage_history("agent-1", limit=3)
        assert len(history) == 3

    @pytest.mark.asyncio
    async def test_get_usage_history_empty_returns_empty_list(self, svc):
        """get_usage_history returns an empty list when no data exists."""
        history = await svc.get_usage_history("never-seen-agent")
        assert history == []


# ---------------------------------------------------------------------------
# check_tier_limits
# ---------------------------------------------------------------------------


class TestCheckTierLimits:
    """Tests for LifeServices.check_tier_limits."""

    @pytest.mark.asyncio
    async def test_free_tier_within_limit(self, svc):
        """Free tier: 10 tasks completed is within the 50-task limit."""
        await svc.record_usage("agent-1", "2026-02", tasks_completed=10)
        result = await svc.check_tier_limits("agent-1", "free", "2026-02")
        assert result["allowed"] is True
        assert result["current"] == 10
        assert result["limit"] == 50

    @pytest.mark.asyncio
    async def test_free_tier_at_limit_is_blocked(self, svc):
        """Free tier: 50 tasks completed equals the limit — blocked."""
        await svc.record_usage("agent-1", "2026-02", tasks_completed=50)
        result = await svc.check_tier_limits("agent-1", "free", "2026-02")
        assert result["allowed"] is False
        assert result["current"] == 50
        assert result["limit"] == 50

    @pytest.mark.asyncio
    async def test_free_tier_over_limit_is_blocked(self, svc):
        """Free tier: 51 tasks completed exceeds the limit — blocked."""
        await svc.record_usage("agent-1", "2026-02", tasks_completed=51)
        result = await svc.check_tier_limits("agent-1", "free", "2026-02")
        assert result["allowed"] is False

    @pytest.mark.asyncio
    async def test_scale_tier_is_unlimited(self, svc):
        """Enterprise tier: even 99999 tasks completed is allowed (unlimited)."""
        await svc.record_usage("agent-1", "2026-02", tasks_completed=99999)
        result = await svc.check_tier_limits("agent-1", "enterprise", "2026-02")
        assert result["allowed"] is True
        assert result["limit"] == -1

    @pytest.mark.asyncio
    async def test_starter_tier_limits(self, svc):
        """Starter tier limit is 500 tasks/month."""
        await svc.record_usage("agent-1", "2026-02", tasks_completed=499)
        result = await svc.check_tier_limits("agent-1", "starter", "2026-02")
        assert result["allowed"] is True
        assert result["limit"] == 500

    @pytest.mark.asyncio
    async def test_no_usage_yet_is_allowed(self, svc):
        """No usage record yet — agent is within any tier limit (current=0)."""
        result = await svc.check_tier_limits("new-agent", "free", "2026-02")
        assert result["allowed"] is True
        assert result["current"] == 0

    @pytest.mark.asyncio
    async def test_invalid_tier_raises(self, svc):
        """An invalid tier value raises ValueError."""
        with pytest.raises(ValueError, match="Invalid tier"):
            await svc.check_tier_limits("agent-1", "platinum", "2026-02")

    @pytest.mark.asyncio
    async def test_response_includes_tier_and_period(self, svc):
        """check_tier_limits response includes tier and period fields."""
        result = await svc.check_tier_limits("agent-1", "pro", "2026-03")
        assert result["tier"] == "pro"
        assert result["period"] == "2026-03"


# ---------------------------------------------------------------------------
# get_purchase_history / get_booking_history
# ---------------------------------------------------------------------------


class TestHistoryMethods:
    """Tests for LifeServices.get_purchase_history and get_booking_history."""

    async def _seed_tasks(self, svc: LifeServices) -> None:
        """Seed tasks directly via the agent_tasks table."""
        import uuid
        from datetime import datetime, timezone
        import aiosqlite

        await svc._ensure_initialized()
        now = datetime.now(timezone.utc).isoformat()

        tasks = [
            (str(uuid.uuid4()), "agent-1", "user-1", "purchase", "Buy laptop", "completed", now),
            (str(uuid.uuid4()), "agent-1", "user-1", "purchase", "Buy headphones", "completed", now),
            (str(uuid.uuid4()), "agent-1", "user-1", "purchase", "Buy cable", "pending", now),
            (str(uuid.uuid4()), "agent-1", "user-1", "booking", "Book hotel", "completed", now),
            (str(uuid.uuid4()), "agent-1", "user-1", "booking", "Book flight", "failed", now),
            (str(uuid.uuid4()), "agent-1", "user-1", "errand", "Pick up dry cleaning", "completed", now),
        ]

        async with aiosqlite.connect(svc._connect_path, uri=svc._connect_uri) as db:
            for t in tasks:
                await db.execute(
                    "INSERT INTO agent_tasks "
                    "(id, agent_id, user_id, task_type, description, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    t,
                )
            await db.commit()

    @pytest.mark.asyncio
    async def test_purchase_history_filters_correctly(self, svc):
        """get_purchase_history returns only completed purchases."""
        await self._seed_tasks(svc)
        purchases = await svc.get_purchase_history("agent-1")
        # Only 2 completed purchases seeded
        assert len(purchases) == 2
        for p in purchases:
            assert p["task_type"] == "purchase"
            assert p["status"] == "completed"

    @pytest.mark.asyncio
    async def test_booking_history_filters_correctly(self, svc):
        """get_booking_history returns only completed bookings."""
        await self._seed_tasks(svc)
        bookings = await svc.get_booking_history("agent-1")
        # Only 1 completed booking seeded (flight is 'failed')
        assert len(bookings) == 1
        assert bookings[0]["task_type"] == "booking"
        assert bookings[0]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_purchase_history_empty_for_unknown_agent(self, svc):
        """get_purchase_history returns empty list for an unknown agent."""
        purchases = await svc.get_purchase_history("nobody")
        assert purchases == []

    @pytest.mark.asyncio
    async def test_booking_history_empty_for_unknown_agent(self, svc):
        """get_booking_history returns empty list for an unknown agent."""
        bookings = await svc.get_booking_history("nobody")
        assert bookings == []
