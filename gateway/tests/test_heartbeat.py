"""Tests for isg_agent.brain.heartbeat — run-result tracking and auto-recovery.

Covers:
  1. last_run_results is empty on a fresh scheduler
  2. run_once appends a result entry with correct shape
  3. run_once sets status="ok" on success
  4. run_once sets status="error" on failure and records error message
  5. Ring buffer is capped at 50 entries (oldest evicted)
  6. auto_recovered is empty on a fresh scheduler
  7. auto_recovered gets an entry when a previously-failing task recovers
  8. auto_recovered does NOT get an entry when first run succeeds (no prior failure)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from isg_agent.brain.heartbeat import HeartbeatScheduler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scheduler() -> HeartbeatScheduler:
    return HeartbeatScheduler(audit_chain=None)


async def _ok_task() -> None:
    """A task that always succeeds."""


async def _fail_task() -> None:
    """A task that always raises."""
    raise RuntimeError("deliberate test failure")


# ---------------------------------------------------------------------------
# 1. last_run_results is empty on fresh scheduler
# ---------------------------------------------------------------------------


def test_last_run_results_empty_on_init() -> None:
    scheduler = _make_scheduler()
    assert scheduler.last_run_results == []


# ---------------------------------------------------------------------------
# 2. run_once appends an entry with correct shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_once_appends_result_entry() -> None:
    scheduler = _make_scheduler()
    scheduler.register("ok_task", _ok_task, interval_seconds=60.0, timeout_seconds=5.0)

    await scheduler.run_once("ok_task")

    results = scheduler.last_run_results
    assert len(results) == 1
    entry = results[0]
    assert set(entry.keys()) >= {"timestamp", "task", "status", "duration_ms", "error"}
    assert entry["task"] == "ok_task"


# ---------------------------------------------------------------------------
# 3. status="ok" on success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_once_status_ok_on_success() -> None:
    scheduler = _make_scheduler()
    scheduler.register("ok_task", _ok_task, interval_seconds=60.0, timeout_seconds=5.0)

    await scheduler.run_once("ok_task")

    entry = scheduler.last_run_results[0]
    assert entry["status"] == "ok"
    assert entry["error"] == ""


# ---------------------------------------------------------------------------
# 4. status="error" on failure + error message captured
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_once_status_error_on_failure() -> None:
    scheduler = _make_scheduler()
    scheduler.register("fail_task", _fail_task, interval_seconds=60.0, timeout_seconds=5.0)

    await scheduler.run_once("fail_task")

    entry = scheduler.last_run_results[0]
    assert entry["status"] == "error"
    assert "deliberate test failure" in entry["error"]
    assert entry["task"] == "fail_task"


# ---------------------------------------------------------------------------
# 5. Ring buffer capped at 50 entries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ring_buffer_capped_at_50() -> None:
    scheduler = _make_scheduler()
    scheduler.register("ok_task", _ok_task, interval_seconds=60.0, timeout_seconds=5.0)

    # Run 60 times — should only keep last 50
    for _ in range(60):
        await scheduler.run_once("ok_task")

    results = scheduler.last_run_results
    assert len(results) == 50


# ---------------------------------------------------------------------------
# 6. auto_recovered empty on fresh scheduler
# ---------------------------------------------------------------------------


def test_auto_recovered_empty_on_init() -> None:
    scheduler = _make_scheduler()
    assert scheduler.auto_recovered == []


# ---------------------------------------------------------------------------
# 7. auto_recovered gets entry when previously-failing task recovers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_recovered_on_recovery() -> None:
    scheduler = _make_scheduler()

    # First run: fail
    scheduler.register("flaky_task", _fail_task, interval_seconds=60.0, timeout_seconds=5.0)
    await scheduler.run_once("flaky_task")

    # Re-register with a success callback (unregister + re-register simulates
    # a fixed task; alternatively swap the callback inline via the task object)
    task_obj = scheduler.get_task("flaky_task")
    assert task_obj is not None
    # Patch the callback directly to make it succeed on next run
    task_obj.callback = _ok_task  # type: ignore[assignment]

    await scheduler.run_once("flaky_task")

    recovered = scheduler.auto_recovered
    assert len(recovered) == 1
    entry = recovered[0]
    assert "flaky_task" in entry["issue"]
    assert "timestamp" in entry
    assert "action" in entry


# ---------------------------------------------------------------------------
# 8. auto_recovered NOT populated when first run immediately succeeds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_recovered_not_set_on_first_success() -> None:
    scheduler = _make_scheduler()
    scheduler.register("clean_task", _ok_task, interval_seconds=60.0, timeout_seconds=5.0)

    await scheduler.run_once("clean_task")

    # No prior failure — must not log a spurious recovery
    assert scheduler.auto_recovered == []
