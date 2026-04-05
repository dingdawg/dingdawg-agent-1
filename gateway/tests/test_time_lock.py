"""Tests for isg_agent.core.time_lock — mandatory cooling periods for dangerous operations.

ALL tests are async (pytest asyncio_mode="auto" in pyproject.toml).

Covers:
- TimeLockEntry dataclass fields
- TimeLockManager in-memory mode: schedule, cancel, execute_ready, get_pending, get_entry, cleanup
- TimeLockManager SQLite mode: same operations persisted to disk
- Default delays: LOW=0, MEDIUM=0, HIGH=30, CRITICAL=60
- Zero-delay tiers execute immediately (status="executed")
- Non-zero-delay tiers pend (status="pending")
- Unknown risk tier raises ValueError (fail-closed)
- set_delay() configuration and negative delay rejection
- Cancel semantics: only pending + within cancellation window
- execute_ready() transitions pending entries past their execute_at time
- cleanup() removes old entries
- Time mocking via monkeypatch of _now_utc for deterministic time control
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from isg_agent.core import time_lock as time_lock_module
from isg_agent.core.time_lock import TimeLockEntry, TimeLockManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fixed_now(dt: datetime):
    """Return a factory function that returns a fixed datetime."""
    def _now() -> datetime:
        return dt
    return _now


# ---------------------------------------------------------------------------
# TimeLockEntry dataclass tests
# ---------------------------------------------------------------------------


class TestTimeLockEntry:
    """Tests for the TimeLockEntry dataclass."""

    def test_fields_accessible(self) -> None:
        """All fields on TimeLockEntry are accessible after construction."""
        entry = TimeLockEntry(
            id="abc-123",
            action_description="delete files",
            risk_tier="HIGH",
            created_at="2026-01-01T00:00:00+00:00",
            execute_at="2026-01-01T00:00:30+00:00",
            status="pending",
            cancellable_until="2026-01-01T00:00:25+00:00",
            callback_data={"key": "val"},
        )
        assert entry.id == "abc-123"
        assert entry.action_description == "delete files"
        assert entry.risk_tier == "HIGH"
        assert entry.status == "pending"
        assert entry.callback_data == {"key": "val"}

    def test_callback_data_defaults_to_none(self) -> None:
        """callback_data defaults to None when not provided."""
        entry = TimeLockEntry(
            id="x", action_description="a", risk_tier="LOW",
            created_at="t", execute_at="t", status="executed", cancellable_until="t",
        )
        assert entry.callback_data is None


# ---------------------------------------------------------------------------
# In-memory mode: schedule tests
# ---------------------------------------------------------------------------


class TestScheduleInMemory:
    """Tests for TimeLockManager.schedule() in memory mode."""

    async def test_low_tier_immediate_execution(self) -> None:
        """LOW tier has 0 delay — entry is created with status 'executed'."""
        mgr = TimeLockManager()
        entry = await mgr.schedule("read file", "LOW")
        assert entry.status == "executed"
        assert entry.risk_tier == "LOW"

    async def test_medium_tier_immediate_execution(self) -> None:
        """MEDIUM tier has 0 delay — entry is created with status 'executed'."""
        mgr = TimeLockManager()
        entry = await mgr.schedule("update config", "MEDIUM")
        assert entry.status == "executed"
        assert entry.risk_tier == "MEDIUM"

    async def test_high_tier_pending(self) -> None:
        """HIGH tier has 30s delay — entry is created with status 'pending'."""
        mgr = TimeLockManager()
        entry = await mgr.schedule("delete backup", "HIGH")
        assert entry.status == "pending"
        assert entry.risk_tier == "HIGH"

    async def test_critical_tier_pending(self) -> None:
        """CRITICAL tier has 60s delay — entry is created with status 'pending'."""
        mgr = TimeLockManager()
        entry = await mgr.schedule("drop production table", "CRITICAL")
        assert entry.status == "pending"
        assert entry.risk_tier == "CRITICAL"

    async def test_case_insensitive_tier(self) -> None:
        """Tier names are case-insensitive — 'low' is valid."""
        mgr = TimeLockManager()
        entry = await mgr.schedule("read file", "low")
        assert entry.risk_tier == "LOW"
        assert entry.status == "executed"

    async def test_unknown_tier_raises_value_error(self) -> None:
        """Unknown risk tier raises ValueError (fail-closed)."""
        mgr = TimeLockManager()
        with pytest.raises(ValueError, match="Unknown risk tier"):
            await mgr.schedule("dangerous action", "SUPER_SECRET")

    async def test_entry_has_uuid_id(self) -> None:
        """Scheduled entry gets a UUID-format id string."""
        mgr = TimeLockManager()
        entry = await mgr.schedule("test", "LOW")
        assert len(entry.id) == 36  # UUID4 format: 8-4-4-4-12

    async def test_callback_data_preserved(self) -> None:
        """callback_data is preserved on the scheduled entry."""
        mgr = TimeLockManager()
        data = {"target": "/tmp/file.txt"}
        entry = await mgr.schedule("delete file", "HIGH", callback_data=data)
        assert entry.callback_data == data


# ---------------------------------------------------------------------------
# In-memory mode: cancel tests
# ---------------------------------------------------------------------------


class TestCancelInMemory:
    """Tests for TimeLockManager.cancel() in memory mode."""

    async def test_cancel_pending_entry(self, monkeypatch) -> None:
        """A pending entry can be cancelled when within the cancellation window."""
        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        monkeypatch.setattr(time_lock_module, "_now_utc", _fixed_now(base_time))

        mgr = TimeLockManager()
        entry = await mgr.schedule("delete data", "CRITICAL")
        assert entry.status == "pending"

        # Cancel while still in the window (time hasn't advanced past cancellable_until)
        result = await mgr.cancel(entry.id)
        assert result is True

        updated = await mgr.get_entry(entry.id)
        assert updated is not None
        assert updated.status == "cancelled"

    async def test_cancel_nonexistent_entry(self) -> None:
        """Cancelling a non-existent entry returns False."""
        mgr = TimeLockManager()
        result = await mgr.cancel("nonexistent-id")
        assert result is False

    async def test_cancel_already_executed_entry(self) -> None:
        """Cancelling an already-executed entry returns False."""
        mgr = TimeLockManager()
        entry = await mgr.schedule("read file", "LOW")  # immediate execution
        assert entry.status == "executed"
        result = await mgr.cancel(entry.id)
        assert result is False

    async def test_cancel_past_window_fails(self, monkeypatch) -> None:
        """Cancelling a pending entry past the cancellation window returns False."""
        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        monkeypatch.setattr(time_lock_module, "_now_utc", _fixed_now(base_time))

        mgr = TimeLockManager()
        entry = await mgr.schedule("delete data", "CRITICAL")

        # Advance time past the cancellation window (60s - 5s buffer = 55s)
        future_time = base_time + timedelta(seconds=56)
        monkeypatch.setattr(time_lock_module, "_now_utc", _fixed_now(future_time))

        result = await mgr.cancel(entry.id)
        assert result is False


# ---------------------------------------------------------------------------
# In-memory mode: execute_ready tests
# ---------------------------------------------------------------------------


class TestExecuteReadyInMemory:
    """Tests for TimeLockManager.execute_ready() in memory mode."""

    async def test_execute_ready_after_delay(self, monkeypatch) -> None:
        """Pending entries become executed after their execute_at time passes."""
        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        monkeypatch.setattr(time_lock_module, "_now_utc", _fixed_now(base_time))

        mgr = TimeLockManager()
        entry = await mgr.schedule("risky operation", "HIGH")  # 30s delay
        assert entry.status == "pending"

        # Advance time past the 30s delay
        future_time = base_time + timedelta(seconds=31)
        monkeypatch.setattr(time_lock_module, "_now_utc", _fixed_now(future_time))

        executed = await mgr.execute_ready()
        assert len(executed) == 1
        assert executed[0].id == entry.id
        assert executed[0].status == "executed"

    async def test_execute_ready_before_delay(self, monkeypatch) -> None:
        """Pending entries are NOT executed before their execute_at time."""
        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        monkeypatch.setattr(time_lock_module, "_now_utc", _fixed_now(base_time))

        mgr = TimeLockManager()
        await mgr.schedule("risky operation", "HIGH")

        # Time hasn't advanced — still before execute_at
        executed = await mgr.execute_ready()
        assert len(executed) == 0

    async def test_execute_ready_skips_cancelled(self, monkeypatch) -> None:
        """Cancelled entries are not executed even after their time passes."""
        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        monkeypatch.setattr(time_lock_module, "_now_utc", _fixed_now(base_time))

        mgr = TimeLockManager()
        entry = await mgr.schedule("delete data", "HIGH")
        await mgr.cancel(entry.id)

        # Advance past delay
        monkeypatch.setattr(
            time_lock_module, "_now_utc",
            _fixed_now(base_time + timedelta(seconds=31)),
        )

        executed = await mgr.execute_ready()
        assert len(executed) == 0

    async def test_execute_ready_returns_empty_when_nothing_pending(self) -> None:
        """execute_ready returns empty list when no pending entries exist."""
        mgr = TimeLockManager()
        executed = await mgr.execute_ready()
        assert executed == []


# ---------------------------------------------------------------------------
# In-memory mode: get_pending, get_entry tests
# ---------------------------------------------------------------------------


class TestGetPendingAndEntry:
    """Tests for get_pending() and get_entry() in memory mode."""

    async def test_get_pending_returns_pending_entries(self) -> None:
        """get_pending returns entries with status 'pending' and future execute_at."""
        mgr = TimeLockManager()
        await mgr.schedule("task1", "HIGH")  # pending (30s delay)
        await mgr.schedule("task2", "LOW")   # executed (0 delay)

        pending = await mgr.get_pending()
        assert len(pending) == 1
        assert pending[0].action_description == "task1"

    async def test_get_entry_existing(self) -> None:
        """get_entry retrieves an existing entry by ID."""
        mgr = TimeLockManager()
        entry = await mgr.schedule("test", "LOW")
        retrieved = await mgr.get_entry(entry.id)
        assert retrieved is not None
        assert retrieved.id == entry.id

    async def test_get_entry_missing_returns_none(self) -> None:
        """get_entry returns None for a non-existent entry ID."""
        mgr = TimeLockManager()
        result = await mgr.get_entry("nonexistent-id")
        assert result is None


# ---------------------------------------------------------------------------
# In-memory mode: cleanup tests
# ---------------------------------------------------------------------------


class TestCleanupInMemory:
    """Tests for TimeLockManager.cleanup() in memory mode."""

    async def test_cleanup_removes_old_entries(self, monkeypatch) -> None:
        """cleanup removes entries older than the specified age."""
        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        monkeypatch.setattr(time_lock_module, "_now_utc", _fixed_now(base_time))

        mgr = TimeLockManager()
        await mgr.schedule("old task", "LOW")

        # Advance time by 2 days
        future_time = base_time + timedelta(days=2)
        monkeypatch.setattr(time_lock_module, "_now_utc", _fixed_now(future_time))

        removed = await mgr.cleanup(older_than_seconds=86400)  # 1 day
        assert removed == 1

    async def test_cleanup_preserves_recent_entries(self, monkeypatch) -> None:
        """cleanup does not remove entries that are younger than the cutoff."""
        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        monkeypatch.setattr(time_lock_module, "_now_utc", _fixed_now(base_time))

        mgr = TimeLockManager()
        await mgr.schedule("recent task", "LOW")

        removed = await mgr.cleanup(older_than_seconds=86400)
        assert removed == 0


# ---------------------------------------------------------------------------
# set_delay() configuration tests
# ---------------------------------------------------------------------------


class TestSetDelay:
    """Tests for TimeLockManager.set_delay() configuration."""

    async def test_set_custom_delay(self) -> None:
        """set_delay configures a custom delay for a tier."""
        mgr = TimeLockManager()
        mgr.set_delay("HIGH", 10.0)
        entry = await mgr.schedule("test", "HIGH")
        assert entry.status == "pending"

    async def test_set_zero_delay_makes_immediate(self) -> None:
        """Setting delay to 0 makes the tier execute immediately."""
        mgr = TimeLockManager()
        mgr.set_delay("CRITICAL", 0.0)
        entry = await mgr.schedule("test", "CRITICAL")
        assert entry.status == "executed"

    def test_negative_delay_raises(self) -> None:
        """set_delay with negative seconds raises ValueError."""
        mgr = TimeLockManager()
        with pytest.raises(ValueError, match="non-negative"):
            mgr.set_delay("HIGH", -5.0)


# ---------------------------------------------------------------------------
# SQLite mode tests
# ---------------------------------------------------------------------------


class TestSQLiteMode:
    """Tests for TimeLockManager with SQLite persistence."""

    async def test_schedule_persists_to_db(self, tmp_path: Path) -> None:
        """Entries scheduled in SQLite mode are retrievable after re-initialization."""
        db_path = tmp_path / "timelock.db"
        mgr1 = TimeLockManager(db_path=db_path)
        entry = await mgr1.schedule("persist test", "HIGH")

        mgr2 = TimeLockManager(db_path=db_path)
        retrieved = await mgr2.get_entry(entry.id)
        assert retrieved is not None
        assert retrieved.action_description == "persist test"

    async def test_cancel_in_sqlite(self, tmp_path: Path, monkeypatch) -> None:
        """Cancel works correctly with SQLite backend."""
        db_path = tmp_path / "cancel.db"
        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        monkeypatch.setattr(time_lock_module, "_now_utc", _fixed_now(base_time))

        mgr = TimeLockManager(db_path=db_path)
        entry = await mgr.schedule("test", "CRITICAL")
        result = await mgr.cancel(entry.id)
        assert result is True

        updated = await mgr.get_entry(entry.id)
        assert updated is not None
        assert updated.status == "cancelled"

    async def test_execute_ready_in_sqlite(self, tmp_path: Path, monkeypatch) -> None:
        """execute_ready works correctly with SQLite backend."""
        db_path = tmp_path / "execute.db"
        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        monkeypatch.setattr(time_lock_module, "_now_utc", _fixed_now(base_time))

        mgr = TimeLockManager(db_path=db_path)
        entry = await mgr.schedule("test", "HIGH")

        # Advance time past 30s delay
        monkeypatch.setattr(
            time_lock_module, "_now_utc",
            _fixed_now(base_time + timedelta(seconds=31)),
        )

        executed = await mgr.execute_ready()
        assert len(executed) == 1
        assert executed[0].status == "executed"

    async def test_cleanup_in_sqlite(self, tmp_path: Path, monkeypatch) -> None:
        """cleanup works correctly with SQLite backend."""
        db_path = tmp_path / "cleanup.db"
        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        monkeypatch.setattr(time_lock_module, "_now_utc", _fixed_now(base_time))

        mgr = TimeLockManager(db_path=db_path)
        await mgr.schedule("old task", "LOW")

        monkeypatch.setattr(
            time_lock_module, "_now_utc",
            _fixed_now(base_time + timedelta(days=2)),
        )

        removed = await mgr.cleanup(older_than_seconds=86400)
        assert removed == 1


# ---------------------------------------------------------------------------
# __repr__ test
# ---------------------------------------------------------------------------


class TestTimeLockManagerRepr:
    """Tests for TimeLockManager.__repr__()."""

    def test_repr_memory_mode(self) -> None:
        """__repr__ shows mode='memory' when no db_path."""
        mgr = TimeLockManager()
        r = repr(mgr)
        assert "memory" in r

    def test_repr_sqlite_mode(self, tmp_path: Path) -> None:
        """__repr__ shows mode='sqlite' when db_path is set."""
        mgr = TimeLockManager(db_path=tmp_path / "test.db")
        r = repr(mgr)
        assert "sqlite" in r
