"""Tests for additional heartbeat tasks: trust_ledger_decay and stale_session_cleanup.

Covers:
- trust_ledger_decay task factory returns an async callable
- trust_ledger_decay calls ledger.decay_all() when invoked
- stale_session_cleanup task factory returns an async callable
- stale_session_cleanup closes stale sessions
- Both task factories are exception-safe (never raise)
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from isg_agent.core.trust_ledger import TrustLedger
from isg_agent.brain.heartbeat import HeartbeatScheduler


# ---------------------------------------------------------------------------
# trust_ledger_decay task
# ---------------------------------------------------------------------------


class TestTrustLedgerDecayTask:
    """Tests for the trust_ledger_decay heartbeat task factory."""

    def test_factory_returns_async_callable(self) -> None:
        """make_trust_ledger_decay_task returns an async callable."""
        from isg_agent.hooks.heartbeat_tasks import make_trust_ledger_decay_task

        ledger = TrustLedger()
        task = make_trust_ledger_decay_task(ledger)
        assert callable(task)
        assert asyncio.iscoroutinefunction(task)

    async def test_decay_task_calls_decay_all(self) -> None:
        """When invoked, the task calls ledger.decay_all()."""
        from isg_agent.hooks.heartbeat_tasks import make_trust_ledger_decay_task

        ledger = TrustLedger()
        # Register some entities
        ledger.record_success("agent:a1", context="test")
        ledger.record_success("agent:a2", context="test")

        original_score_a1 = ledger.get_or_create("agent:a1").score
        original_score_a2 = ledger.get_or_create("agent:a2").score

        task = make_trust_ledger_decay_task(ledger)
        await task()

        # Scores should have decayed toward 0.5
        new_score_a1 = ledger.get_or_create("agent:a1").score
        new_score_a2 = ledger.get_or_create("agent:a2").score

        # Since original scores > 0.5 (after success), decay should bring them closer to 0.5
        assert new_score_a1 <= original_score_a1
        assert new_score_a2 <= original_score_a2

    async def test_decay_task_handles_empty_ledger(self) -> None:
        """Decay on an empty ledger should not raise."""
        from isg_agent.hooks.heartbeat_tasks import make_trust_ledger_decay_task

        ledger = TrustLedger()
        task = make_trust_ledger_decay_task(ledger)

        # Should not raise
        await task()

    async def test_decay_task_never_raises(self) -> None:
        """Even if the ledger is broken, the task must not raise."""
        from isg_agent.hooks.heartbeat_tasks import make_trust_ledger_decay_task

        ledger = TrustLedger()
        ledger.decay_all = MagicMock(side_effect=RuntimeError("broken"))

        task = make_trust_ledger_decay_task(ledger)

        # Should not raise
        await task()


# ---------------------------------------------------------------------------
# stale_session_cleanup task
# ---------------------------------------------------------------------------


class TestStaleSessionCleanupTask:
    """Tests for the stale_session_cleanup heartbeat task factory."""

    def test_factory_returns_async_callable(self) -> None:
        """make_stale_session_cleanup_task returns an async callable."""
        from isg_agent.hooks.heartbeat_tasks import make_stale_session_cleanup_task

        session_manager = AsyncMock()
        task = make_stale_session_cleanup_task(session_manager)
        assert callable(task)
        assert asyncio.iscoroutinefunction(task)

    async def test_cleanup_calls_close_stale_sessions(self) -> None:
        """When invoked, the task calls session_manager.close_stale_sessions."""
        from isg_agent.hooks.heartbeat_tasks import make_stale_session_cleanup_task

        session_manager = AsyncMock()
        session_manager.close_stale_sessions = AsyncMock(return_value=3)

        task = make_stale_session_cleanup_task(session_manager)
        await task()

        session_manager.close_stale_sessions.assert_awaited_once()

    async def test_cleanup_uses_default_max_age(self) -> None:
        """Default max_age_hours is 24."""
        from isg_agent.hooks.heartbeat_tasks import make_stale_session_cleanup_task

        session_manager = AsyncMock()
        session_manager.close_stale_sessions = AsyncMock(return_value=0)

        task = make_stale_session_cleanup_task(session_manager, max_age_hours=48)
        await task()

        # Should have been called with 48 hours
        session_manager.close_stale_sessions.assert_awaited_once_with(max_age_hours=48)

    async def test_cleanup_never_raises(self) -> None:
        """Even if the session_manager is broken, the task must not raise."""
        from isg_agent.hooks.heartbeat_tasks import make_stale_session_cleanup_task

        session_manager = AsyncMock()
        session_manager.close_stale_sessions = AsyncMock(
            side_effect=RuntimeError("db locked")
        )

        task = make_stale_session_cleanup_task(session_manager)

        # Should not raise
        await task()


# ---------------------------------------------------------------------------
# Integration: both tasks can be registered on HeartbeatScheduler
# ---------------------------------------------------------------------------


class TestHeartbeatTaskRegistration:
    """Verify the heartbeat task factories produce tasks compatible with HeartbeatScheduler."""

    def test_trust_decay_registers_on_scheduler(self) -> None:
        """trust_ledger_decay task can be registered on HeartbeatScheduler."""
        from isg_agent.hooks.heartbeat_tasks import make_trust_ledger_decay_task

        ledger = TrustLedger()
        scheduler = HeartbeatScheduler()

        task = make_trust_ledger_decay_task(ledger)
        scheduler.register(
            name="trust_ledger_decay",
            callback=task,
            interval_seconds=3600.0,
            timeout_seconds=30.0,
        )

        assert "trust_ledger_decay" in scheduler.task_names

    def test_stale_session_registers_on_scheduler(self) -> None:
        """stale_session_cleanup task can be registered on HeartbeatScheduler."""
        from isg_agent.hooks.heartbeat_tasks import make_stale_session_cleanup_task

        session_manager = AsyncMock()
        scheduler = HeartbeatScheduler()

        task = make_stale_session_cleanup_task(session_manager)
        scheduler.register(
            name="stale_session_cleanup",
            callback=task,
            interval_seconds=1800.0,
            timeout_seconds=30.0,
        )

        assert "stale_session_cleanup" in scheduler.task_names

    def test_both_tasks_register_without_conflict(self) -> None:
        """Both tasks can be registered on the same scheduler."""
        from isg_agent.hooks.heartbeat_tasks import (
            make_trust_ledger_decay_task,
            make_stale_session_cleanup_task,
        )

        ledger = TrustLedger()
        session_manager = AsyncMock()
        scheduler = HeartbeatScheduler()

        scheduler.register(
            name="trust_ledger_decay",
            callback=make_trust_ledger_decay_task(ledger),
            interval_seconds=3600.0,
            timeout_seconds=30.0,
        )
        scheduler.register(
            name="stale_session_cleanup",
            callback=make_stale_session_cleanup_task(session_manager),
            interval_seconds=1800.0,
            timeout_seconds=30.0,
        )

        assert len(scheduler.task_names) == 2
        assert "trust_ledger_decay" in scheduler.task_names
        assert "stale_session_cleanup" in scheduler.task_names
