"""Comprehensive tests for isg_agent.capabilities.cap5_staff_ops.StaffOpsEngine.

Uses a real SQLite database (tempfile) for every test — no mocks of the DB layer.
The appointments table is created manually in setup since it lives outside the
business-ops schema but is read by cap5.

Test coverage:
- assign_staff: valid, overlap detection, non-overlapping multiple, missing appt
- set_schedule: valid (all days, boundary times), invalid day, invalid time format,
  start >= end, update existing
- get_schedule: ordered multi-entry, empty result
- record_payroll: valid, zero values OK, negative hours rejected, negative amount rejected
- approve_payroll: pending→approved, already approved rejected, not found rejected
- compute_utilization: with schedule + appointments, no schedule, multiple appts, revenue sum
- utilization_report: multiple staff aggregated, top performer, underutilized flagged,
  empty period
- unassign_staff: valid (rollback record created, row deleted), nonexistent returns error
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import os
from datetime import date, timedelta
from typing import Any, Dict

import pytest

from isg_agent.capabilities.cap5_staff_ops import StaffOpsEngine
from isg_agent.capabilities.shared.db_schema import ensure_tables


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_APPOINTMENTS_DDL = """
CREATE TABLE IF NOT EXISTS appointments (
    id          TEXT PRIMARY KEY,
    staff_id    TEXT,
    start_time  TEXT,
    end_time    TEXT,
    scheduled_at TEXT,
    status      TEXT DEFAULT 'scheduled',
    price_cents INTEGER DEFAULT 0
);
"""


def _create_db() -> str:
    """Create a fresh temp SQLite DB, apply all tables, return the path."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    ensure_tables(path)
    # appointments table is not in db_schema.py (it belongs to the core schema),
    # but cap5 queries it directly — create it here.
    conn = sqlite3.connect(path)
    conn.execute(_APPOINTMENTS_DDL)
    conn.commit()
    conn.close()
    return path


def _insert_appointment(
    db_path: str,
    appt_id: str,
    start_time: str,
    end_time: str,
    price_cents: int = 5000,
) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO appointments (id, start_time, end_time, price_cents) VALUES (?, ?, ?, ?)",
        (appt_id, start_time, end_time, price_cents),
    )
    conn.commit()
    conn.close()


def _insert_active_assignment(
    db_path: str,
    assignment_id: str,
    staff_id: str,
    appointment_id: str,
) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO staff_assignments (id, staff_id, appointment_id, assigned_at, status) "
        "VALUES (?, ?, ?, '2026-01-01T00:00:00', 'active')",
        (assignment_id, staff_id, appointment_id),
    )
    conn.commit()
    conn.close()


def _insert_schedule(
    db_path: str,
    staff_id: str,
    day_of_week: int,
    start_time: str,
    end_time: str,
) -> str:
    sched_id = f"sched_{staff_id}_{day_of_week}"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO staff_schedule (id, staff_id, day_of_week, start_time, end_time, is_available) "
        "VALUES (?, ?, ?, ?, ?, 1)",
        (sched_id, staff_id, day_of_week, start_time, end_time),
    )
    conn.commit()
    conn.close()
    return sched_id


def _insert_utilization(
    db_path: str,
    util_id: str,
    staff_id: str,
    date_key: str,
    utilization_pct: float,
    appointments_count: int,
    revenue_cents: int,
) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO resource_utilization "
        "(id, staff_id, date_key, utilization_pct, appointments_count, revenue_cents) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (util_id, staff_id, date_key, utilization_pct, appointments_count, revenue_cents),
    )
    conn.commit()
    conn.close()


def _get_row(db_path: str, table: str, row_id: str) -> Dict[str, Any] | None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,))  # noqa: S608
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_path():
    path = _create_db()
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture()
def engine(db_path):
    return StaffOpsEngine(db_path)


# ===========================================================================
# assign_staff
# ===========================================================================


class TestAssignStaff:
    def test_valid_assignment_returns_ok(self, engine, db_path):
        _insert_appointment(db_path, "appt-1", "2026-03-15T09:00:00", "2026-03-15T10:00:00")
        result = engine.assign_staff("staff-1", "appt-1")

        assert result["ok"] is True
        data = result["data"]
        assert data["staff_id"] == "staff-1"
        assert data["appointment_id"] == "appt-1"
        assert data["status"] == "active"
        assert data["id"].startswith("sa_")

    def test_valid_assignment_writes_row_to_db(self, engine, db_path):
        _insert_appointment(db_path, "appt-2", "2026-03-15T11:00:00", "2026-03-15T12:00:00")
        result = engine.assign_staff("staff-A", "appt-2")

        assert result["ok"] is True
        assignment_id = result["data"]["id"]
        row = _get_row(db_path, "staff_assignments", assignment_id)
        assert row is not None
        assert row["staff_id"] == "staff-A"
        assert row["appointment_id"] == "appt-2"

    def test_appointment_not_found_returns_error(self, engine, db_path):
        result = engine.assign_staff("staff-1", "nonexistent-appt")

        assert result["ok"] is False
        assert "not found" in result["error"].lower()

    def test_overlap_detection_returns_conflict_error(self, engine, db_path):
        # Insert two overlapping appointments (same staff, overlapping windows)
        _insert_appointment(db_path, "appt-A", "2026-03-15T09:00:00", "2026-03-15T11:00:00")
        _insert_appointment(db_path, "appt-B", "2026-03-15T10:00:00", "2026-03-15T12:00:00")

        # Assign staff to appt-A first
        r1 = engine.assign_staff("staff-X", "appt-A")
        assert r1["ok"] is True

        # Attempting to assign same staff to overlapping appt-B must fail
        r2 = engine.assign_staff("staff-X", "appt-B")
        assert r2["ok"] is False
        assert "overlap" in r2["error"].lower()
        assert r2["details"]["conflicting_appointment_id"] == "appt-A"

    def test_non_overlapping_second_assignment_succeeds(self, engine, db_path):
        # appt-M ends before appt-N starts — no overlap
        _insert_appointment(db_path, "appt-M", "2026-03-15T08:00:00", "2026-03-15T09:00:00")
        _insert_appointment(db_path, "appt-N", "2026-03-15T10:00:00", "2026-03-15T11:00:00")

        r1 = engine.assign_staff("staff-Y", "appt-M")
        assert r1["ok"] is True

        r2 = engine.assign_staff("staff-Y", "appt-N")
        assert r2["ok"] is True
        assert r2["data"]["appointment_id"] == "appt-N"

    def test_different_staff_can_share_same_appointment(self, engine, db_path):
        _insert_appointment(db_path, "appt-C", "2026-03-15T14:00:00", "2026-03-15T15:00:00")

        r1 = engine.assign_staff("staff-P", "appt-C")
        r2 = engine.assign_staff("staff-Q", "appt-C")

        assert r1["ok"] is True
        assert r2["ok"] is True

    def test_overlap_receipt_contains_intent_id(self, engine, db_path):
        _insert_appointment(db_path, "appt-D", "2026-03-15T09:00:00", "2026-03-15T11:00:00")
        _insert_appointment(db_path, "appt-E", "2026-03-15T09:30:00", "2026-03-15T10:30:00")
        engine.assign_staff("staff-Z", "appt-D")
        result = engine.assign_staff("staff-Z", "appt-E")

        assert result["ok"] is False
        assert "intent_id" in result["details"]

    def test_appointments_without_end_time_do_not_falsely_overlap(self, engine, db_path):
        # If appt has no end_time, overlap check is skipped — both assignments must succeed
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO appointments (id, start_time, end_time, price_cents) VALUES (?, ?, NULL, 0)",
            ("appt-no-end-1", "2026-03-15T09:00:00"),
        )
        conn.execute(
            "INSERT INTO appointments (id, start_time, end_time, price_cents) VALUES (?, ?, NULL, 0)",
            ("appt-no-end-2", "2026-03-15T09:30:00"),
        )
        conn.commit()
        conn.close()

        r1 = engine.assign_staff("staff-K", "appt-no-end-1")
        r2 = engine.assign_staff("staff-K", "appt-no-end-2")

        assert r1["ok"] is True
        assert r2["ok"] is True

    def test_success_receipt_has_rollback_available(self, engine, db_path):
        _insert_appointment(db_path, "appt-R1", "2026-03-15T08:00:00", "2026-03-15T09:00:00")
        result = engine.assign_staff("staff-R", "appt-R1")

        assert result["ok"] is True
        assert result["receipt"]["rollback_available"] is True
        assert result["receipt"]["outcome"] == "executed"


# ===========================================================================
# set_schedule
# ===========================================================================


class TestSetSchedule:
    def test_valid_schedule_insert(self, engine, db_path):
        result = engine.set_schedule("staff-1", 0, "09:00", "17:00")

        assert result["ok"] is True
        data = result["data"]
        assert data["staff_id"] == "staff-1"
        assert data["day_of_week"] == 0
        assert data["start_time"] == "09:00"
        assert data["end_time"] == "17:00"
        assert data["is_available"] == 1

    def test_all_valid_days_accepted(self, engine, db_path):
        for day in range(7):
            result = engine.set_schedule(f"staff-day-{day}", day, "08:00", "16:00")
            assert result["ok"] is True, f"day {day} should be valid"

    def test_invalid_day_7_returns_error(self, engine, db_path):
        result = engine.set_schedule("staff-1", 7, "09:00", "17:00")

        assert result["ok"] is False
        assert "day_of_week" in result["error"].lower()

    def test_invalid_day_negative_returns_error(self, engine, db_path):
        result = engine.set_schedule("staff-1", -1, "09:00", "17:00")

        assert result["ok"] is False
        assert "day_of_week" in result["error"].lower()

    def test_invalid_time_format_missing_colon(self, engine, db_path):
        result = engine.set_schedule("staff-1", 1, "0900", "1700")

        assert result["ok"] is False
        assert "hh:mm" in result["error"].lower() or "format" in result["error"].lower()

    def test_invalid_time_format_letters(self, engine, db_path):
        result = engine.set_schedule("staff-1", 2, "AA:00", "17:00")

        assert result["ok"] is False

    def test_invalid_hour_out_of_range(self, engine, db_path):
        result = engine.set_schedule("staff-1", 3, "25:00", "26:00")

        assert result["ok"] is False

    def test_invalid_minute_out_of_range(self, engine, db_path):
        result = engine.set_schedule("staff-1", 4, "09:60", "17:00")

        assert result["ok"] is False

    def test_start_equal_to_end_returns_error(self, engine, db_path):
        result = engine.set_schedule("staff-1", 0, "09:00", "09:00")

        assert result["ok"] is False
        assert "earlier" in result["error"].lower() or "start_time" in result["error"].lower()

    def test_start_after_end_returns_error(self, engine, db_path):
        result = engine.set_schedule("staff-1", 0, "17:00", "09:00")

        assert result["ok"] is False

    def test_update_existing_schedule_entry(self, engine, db_path):
        # Insert first
        r1 = engine.set_schedule("staff-upd", 2, "08:00", "14:00")
        assert r1["ok"] is True
        original_id = r1["data"]["id"]

        # Update same staff/day — should reuse the same id
        r2 = engine.set_schedule("staff-upd", 2, "10:00", "18:00")
        assert r2["ok"] is True
        assert r2["data"]["id"] == original_id
        assert r2["data"]["start_time"] == "10:00"
        assert r2["data"]["end_time"] == "18:00"

    def test_boundary_times_midnight_to_midnight(self, engine, db_path):
        # 00:01 to 23:59 is the widest valid window
        result = engine.set_schedule("staff-bnd", 6, "00:01", "23:59")
        assert result["ok"] is True

    def test_receipt_outcome_is_executed(self, engine, db_path):
        result = engine.set_schedule("staff-rc", 1, "09:00", "17:00")
        assert result["ok"] is True
        assert result["receipt"]["outcome"] == "executed"


# ===========================================================================
# get_schedule
# ===========================================================================


class TestGetSchedule:
    def test_with_entries_returns_ordered_by_day(self, engine, db_path):
        # Insert out of order: Wed(2), Mon(0), Fri(4)
        _insert_schedule(db_path, "staff-sched", 2, "10:00", "18:00")
        _insert_schedule(db_path, "staff-sched", 0, "09:00", "17:00")
        _insert_schedule(db_path, "staff-sched", 4, "08:00", "16:00")

        result = engine.get_schedule("staff-sched")

        assert result["ok"] is True
        data = result["data"]
        assert data["staff_id"] == "staff-sched"
        assert data["entry_count"] == 3
        days = [e["day_of_week"] for e in data["schedule"]]
        assert days == sorted(days), "schedule entries must be ordered by day_of_week ASC"

    def test_empty_schedule_returns_empty_list(self, engine, db_path):
        result = engine.get_schedule("staff-no-schedule")

        assert result["ok"] is True
        data = result["data"]
        assert data["entry_count"] == 0
        assert data["schedule"] == []

    def test_single_entry_returned_correctly(self, engine, db_path):
        _insert_schedule(db_path, "staff-single", 3, "07:00", "15:00")

        result = engine.get_schedule("staff-single")

        assert result["ok"] is True
        assert result["data"]["entry_count"] == 1
        entry = result["data"]["schedule"][0]
        assert entry["day_of_week"] == 3
        assert entry["start_time"] == "07:00"
        assert entry["end_time"] == "15:00"

    def test_schedule_isolation_between_staff(self, engine, db_path):
        _insert_schedule(db_path, "staff-iso-A", 1, "09:00", "17:00")
        _insert_schedule(db_path, "staff-iso-B", 2, "10:00", "18:00")

        result_a = engine.get_schedule("staff-iso-A")
        result_b = engine.get_schedule("staff-iso-B")

        assert result_a["data"]["entry_count"] == 1
        assert result_b["data"]["entry_count"] == 1
        assert result_a["data"]["schedule"][0]["day_of_week"] == 1
        assert result_b["data"]["schedule"][0]["day_of_week"] == 2

    def test_receipt_outcome_is_executed(self, engine, db_path):
        result = engine.get_schedule("staff-rc")
        assert result["ok"] is True
        assert result["receipt"]["outcome"] == "executed"


# ===========================================================================
# record_payroll
# ===========================================================================


class TestRecordPayroll:
    def test_valid_record_returns_ok(self, engine, db_path):
        result = engine.record_payroll(
            "staff-pay", "2026-03-01", "2026-03-15", 80.0, 240000
        )

        assert result["ok"] is True
        data = result["data"]
        assert data["staff_id"] == "staff-pay"
        assert data["hours_worked"] == 80.0
        assert data["amount_cents"] == 240000
        assert data["status"] == "pending"
        assert data["id"].startswith("pay_")

    def test_valid_record_persisted_to_db(self, engine, db_path):
        result = engine.record_payroll(
            "staff-persist", "2026-03-01", "2026-03-15", 40.0, 120000
        )
        assert result["ok"] is True
        row = _get_row(db_path, "payroll_records", result["data"]["id"])
        assert row is not None
        assert row["staff_id"] == "staff-persist"
        assert row["amount_cents"] == 120000

    def test_zero_hours_accepted(self, engine, db_path):
        result = engine.record_payroll("staff-zero", "2026-03-01", "2026-03-15", 0.0, 0)
        assert result["ok"] is True

    def test_zero_amount_accepted(self, engine, db_path):
        result = engine.record_payroll("staff-zero2", "2026-03-01", "2026-03-15", 10.0, 0)
        assert result["ok"] is True

    def test_negative_hours_rejected(self, engine, db_path):
        result = engine.record_payroll("staff-neg", "2026-03-01", "2026-03-15", -1.0, 100)

        assert result["ok"] is False
        assert "hours_worked" in result["error"].lower()

    def test_negative_amount_rejected(self, engine, db_path):
        result = engine.record_payroll("staff-neg2", "2026-03-01", "2026-03-15", 40.0, -1)

        assert result["ok"] is False
        assert "amount_cents" in result["error"].lower()

    def test_multiple_payroll_records_same_staff(self, engine, db_path):
        r1 = engine.record_payroll("staff-multi", "2026-02-01", "2026-02-14", 80.0, 240000)
        r2 = engine.record_payroll("staff-multi", "2026-03-01", "2026-03-15", 80.0, 240000)

        assert r1["ok"] is True
        assert r2["ok"] is True
        assert r1["data"]["id"] != r2["data"]["id"]

    def test_receipt_outcome_is_executed(self, engine, db_path):
        result = engine.record_payroll("staff-rc", "2026-03-01", "2026-03-15", 10.0, 500)
        assert result["ok"] is True
        assert result["receipt"]["outcome"] == "executed"


# ===========================================================================
# approve_payroll
# ===========================================================================


class TestApprovePayroll:
    def _create_pending_payroll(self, engine, db_path, staff_id: str = "staff-apr") -> str:
        result = engine.record_payroll(staff_id, "2026-03-01", "2026-03-15", 80.0, 240000)
        assert result["ok"] is True
        return result["data"]["id"]

    def test_pending_to_approved(self, engine, db_path):
        payroll_id = self._create_pending_payroll(engine, db_path)
        result = engine.approve_payroll(payroll_id)

        assert result["ok"] is True
        data = result["data"]
        assert data["payroll_id"] == payroll_id
        assert data["status"] == "approved"

    def test_approval_writes_status_to_db(self, engine, db_path):
        payroll_id = self._create_pending_payroll(engine, db_path)
        engine.approve_payroll(payroll_id)

        row = _get_row(db_path, "payroll_records", payroll_id)
        assert row["status"] == "approved"

    def test_approval_creates_approval_queue_entry(self, engine, db_path):
        payroll_id = self._create_pending_payroll(engine, db_path)
        result = engine.approve_payroll(payroll_id)

        assert result["ok"] is True
        approval_queue_id = result["data"]["approval_queue_id"]
        assert approval_queue_id is not None
        row = _get_row(db_path, "approval_queue", approval_queue_id)
        assert row is not None

    def test_already_approved_returns_error(self, engine, db_path):
        payroll_id = self._create_pending_payroll(engine, db_path)
        engine.approve_payroll(payroll_id)
        result = engine.approve_payroll(payroll_id)

        assert result["ok"] is False
        assert "already approved" in result["error"].lower()

    def test_nonexistent_payroll_returns_error(self, engine, db_path):
        result = engine.approve_payroll("nonexistent-payroll-id")

        assert result["ok"] is False
        assert "not found" in result["error"].lower()

    def test_approval_writes_immutable_receipt(self, engine, db_path):
        payroll_id = self._create_pending_payroll(engine, db_path)
        result = engine.approve_payroll(payroll_id)

        assert result["ok"] is True
        immutable_receipt_id = result["data"]["immutable_receipt_id"]
        assert immutable_receipt_id is not None
        row = _get_row(db_path, "immutable_receipts", immutable_receipt_id)
        assert row is not None

    def test_receipt_has_approval_required_flag(self, engine, db_path):
        payroll_id = self._create_pending_payroll(engine, db_path)
        result = engine.approve_payroll(payroll_id)

        assert result["ok"] is True
        assert result["receipt"]["approval_required"] is True
        assert result["receipt"]["outcome"] == "executed"


# ===========================================================================
# compute_utilization
# ===========================================================================


class TestComputeUtilization:
    def test_with_schedule_and_one_appointment(self, engine, db_path):
        # 2026-03-16 is a Monday (weekday=0)
        date_key = "2026-03-16"
        _insert_schedule(db_path, "staff-util", 0, "09:00", "17:00")  # 8 available hours
        _insert_appointment(db_path, "appt-util-1", "2026-03-16T10:00:00", "2026-03-16T11:00:00", price_cents=10000)
        engine.assign_staff("staff-util", "appt-util-1")

        result = engine.compute_utilization("staff-util", date_key)

        assert result["ok"] is True
        data = result["data"]
        assert data["staff_id"] == "staff-util"
        assert data["date_key"] == date_key
        assert data["available_hours"] == 8.0
        assert data["appointments_count"] == 1
        assert data["revenue_cents"] == 10000
        # 1 appt / (8 hours * 1.0 per hour) * 100 = 12.5%
        assert data["utilization_pct"] == pytest.approx(12.5)

    def test_with_multiple_appointments_revenue_summed(self, engine, db_path):
        date_key = "2026-03-16"
        _insert_schedule(db_path, "staff-multi-util", 0, "09:00", "17:00")
        _insert_appointment(db_path, "appt-mu-1", "2026-03-16T09:00:00", "2026-03-16T10:00:00", price_cents=5000)
        _insert_appointment(db_path, "appt-mu-2", "2026-03-16T11:00:00", "2026-03-16T12:00:00", price_cents=7500)
        _insert_appointment(db_path, "appt-mu-3", "2026-03-16T13:00:00", "2026-03-16T14:00:00", price_cents=6000)
        engine.assign_staff("staff-multi-util", "appt-mu-1")
        engine.assign_staff("staff-multi-util", "appt-mu-2")
        engine.assign_staff("staff-multi-util", "appt-mu-3")

        result = engine.compute_utilization("staff-multi-util", date_key)

        assert result["ok"] is True
        data = result["data"]
        assert data["appointments_count"] == 3
        assert data["revenue_cents"] == 18500
        # 3 / (8 * 1.0) * 100 = 37.5%
        assert data["utilization_pct"] == pytest.approx(37.5)

    def test_no_schedule_returns_zero_utilization(self, engine, db_path):
        # Staff has no schedule entry for Monday
        date_key = "2026-03-16"
        result = engine.compute_utilization("staff-no-sched", date_key)

        assert result["ok"] is True
        data = result["data"]
        assert data["available_hours"] == 0.0
        assert data["utilization_pct"] == 0.0

    def test_no_appointments_on_date_returns_zero_count(self, engine, db_path):
        date_key = "2026-03-16"
        _insert_schedule(db_path, "staff-empty", 0, "09:00", "17:00")

        result = engine.compute_utilization("staff-empty", date_key)

        assert result["ok"] is True
        data = result["data"]
        assert data["appointments_count"] == 0
        assert data["revenue_cents"] == 0
        assert data["utilization_pct"] == 0.0

    def test_appointments_on_different_date_excluded(self, engine, db_path):
        date_key = "2026-03-16"
        _insert_schedule(db_path, "staff-excl", 0, "09:00", "17:00")
        # Appointment on a different date
        _insert_appointment(db_path, "appt-other-day", "2026-03-17T10:00:00", "2026-03-17T11:00:00")
        engine.assign_staff("staff-excl", "appt-other-day")

        result = engine.compute_utilization("staff-excl", date_key)

        assert result["ok"] is True
        assert result["data"]["appointments_count"] == 0

    def test_result_persisted_to_resource_utilization(self, engine, db_path):
        date_key = "2026-03-16"
        _insert_schedule(db_path, "staff-persist-util", 0, "09:00", "17:00")

        result = engine.compute_utilization("staff-persist-util", date_key)
        assert result["ok"] is True

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM resource_utilization WHERE staff_id = ? AND date_key = ?",
            ("staff-persist-util", date_key),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["staff_id"] == "staff-persist-util"
        assert row["date_key"] == date_key

    def test_day_of_week_computed_correctly(self, engine, db_path):
        # 2026-03-16 is Monday (weekday=0), 2026-03-21 is Saturday (weekday=5)
        _insert_schedule(db_path, "staff-dow", 0, "09:00", "17:00")
        r_monday = engine.compute_utilization("staff-dow", "2026-03-16")
        r_saturday = engine.compute_utilization("staff-dow", "2026-03-21")

        assert r_monday["data"]["day_of_week"] == 0
        assert r_saturday["data"]["day_of_week"] == 5
        # Schedule only on Monday — Saturday has no schedule entry
        assert r_monday["data"]["available_hours"] == 8.0
        assert r_saturday["data"]["available_hours"] == 0.0

    def test_receipt_outcome_is_executed(self, engine, db_path):
        result = engine.compute_utilization("staff-rc-util", "2026-03-16")
        assert result["ok"] is True
        assert result["receipt"]["outcome"] == "executed"


# ===========================================================================
# utilization_report
# ===========================================================================


class TestUtilizationReport:
    def _today_key(self) -> str:
        from isg_agent.capabilities.shared.foundation import utc_now
        return utc_now().date().isoformat()

    def test_empty_period_returns_zero_staff(self, engine, db_path):
        result = engine.utilization_report("biz-1", period_days=7)

        assert result["ok"] is True
        data = result["data"]
        assert data["staff_count"] == 0
        assert data["per_staff"] == []
        assert data["overall_avg_utilization_pct"] == 0.0
        assert data["top_performer"] is None
        assert data["underutilized_staff"] == []

    def test_multiple_staff_aggregated(self, engine, db_path):
        today = self._today_key()
        _insert_utilization(db_path, "u1", "staff-A", today, 80.0, 4, 20000)
        _insert_utilization(db_path, "u2", "staff-B", today, 40.0, 2, 10000)

        result = engine.utilization_report("biz-1", period_days=1)

        assert result["ok"] is True
        data = result["data"]
        assert data["staff_count"] == 2

        staff_ids = {s["staff_id"] for s in data["per_staff"]}
        assert "staff-A" in staff_ids
        assert "staff-B" in staff_ids

    def test_top_performer_identified(self, engine, db_path):
        today = self._today_key()
        _insert_utilization(db_path, "u3", "staff-top", today, 90.0, 9, 45000)
        _insert_utilization(db_path, "u4", "staff-low", today, 30.0, 3, 15000)

        result = engine.utilization_report("biz-1", period_days=1)

        assert result["ok"] is True
        top = result["data"]["top_performer"]
        assert top is not None
        assert top["staff_id"] == "staff-top"

    def test_underutilized_flagged_below_50_pct(self, engine, db_path):
        today = self._today_key()
        _insert_utilization(db_path, "u5", "staff-over", today, 75.0, 6, 30000)
        _insert_utilization(db_path, "u6", "staff-under", today, 25.0, 2, 10000)

        result = engine.utilization_report("biz-1", period_days=1)

        assert result["ok"] is True
        underutilized_ids = [s["staff_id"] for s in result["data"]["underutilized_staff"]]
        assert "staff-under" in underutilized_ids
        assert "staff-over" not in underutilized_ids

    def test_overall_average_computed_correctly(self, engine, db_path):
        today = self._today_key()
        _insert_utilization(db_path, "u7", "staff-C", today, 60.0, 6, 30000)
        _insert_utilization(db_path, "u8", "staff-D", today, 40.0, 4, 20000)

        result = engine.utilization_report("biz-1", period_days=1)

        assert result["ok"] is True
        # avg of 60.0 and 40.0 = 50.0
        assert result["data"]["overall_avg_utilization_pct"] == pytest.approx(50.0)

    def test_entries_outside_period_excluded(self, engine, db_path):
        today = self._today_key()
        old_date = (date.fromisoformat(today) - timedelta(days=30)).isoformat()
        _insert_utilization(db_path, "u9", "staff-old", old_date, 100.0, 10, 50000)

        result = engine.utilization_report("biz-1", period_days=7)

        assert result["ok"] is True
        assert result["data"]["staff_count"] == 0

    def test_multiple_days_per_staff_averaged(self, engine, db_path):
        today = self._today_key()
        yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
        _insert_utilization(db_path, "u10", "staff-E", today, 80.0, 4, 20000)
        _insert_utilization(db_path, "u11", "staff-E", yesterday, 60.0, 3, 15000)

        result = engine.utilization_report("biz-1", period_days=2)

        assert result["ok"] is True
        assert result["data"]["staff_count"] == 1
        staff_entry = result["data"]["per_staff"][0]
        assert staff_entry["staff_id"] == "staff-E"
        assert staff_entry["days_tracked"] == 2
        assert staff_entry["avg_utilization_pct"] == pytest.approx(70.0)
        assert staff_entry["total_appointments"] == 7

    def test_period_start_and_end_keys_in_response(self, engine, db_path):
        result = engine.utilization_report("biz-1", period_days=7)

        assert result["ok"] is True
        data = result["data"]
        assert "period_start" in data
        assert "period_end" in data
        assert data["period_days"] == 7
        assert data["business_id"] == "biz-1"

    def test_exactly_50_pct_is_not_underutilized(self, engine, db_path):
        today = self._today_key()
        _insert_utilization(db_path, "u12", "staff-border", today, 50.0, 5, 25000)

        result = engine.utilization_report("biz-1", period_days=1)

        assert result["ok"] is True
        underutilized_ids = [s["staff_id"] for s in result["data"]["underutilized_staff"]]
        assert "staff-border" not in underutilized_ids

    def test_receipt_outcome_is_executed(self, engine, db_path):
        result = engine.utilization_report("biz-rc", period_days=1)
        assert result["ok"] is True
        assert result["receipt"]["outcome"] == "executed"


# ===========================================================================
# unassign_staff
# ===========================================================================


class TestUnassignStaff:
    def _assign(self, engine, db_path, staff_id: str, appt_id: str) -> str:
        """Helper: insert appointment, assign staff, return assignment_id."""
        _insert_appointment(db_path, appt_id, "2026-03-15T09:00:00", "2026-03-15T10:00:00")
        result = engine.assign_staff(staff_id, appt_id)
        assert result["ok"] is True
        return result["data"]["id"]

    def test_valid_unassign_returns_ok(self, engine, db_path):
        assignment_id = self._assign(engine, db_path, "staff-un1", "appt-un1")
        result = engine.unassign_staff(assignment_id)

        assert result["ok"] is True
        data = result["data"]
        assert data["assignment_id"] == assignment_id
        assert data["deleted"] is True

    def test_row_deleted_from_db(self, engine, db_path):
        assignment_id = self._assign(engine, db_path, "staff-un2", "appt-un2")
        engine.unassign_staff(assignment_id)

        row = _get_row(db_path, "staff_assignments", assignment_id)
        assert row is None

    def test_rollback_record_created(self, engine, db_path):
        assignment_id = self._assign(engine, db_path, "staff-un3", "appt-un3")
        result = engine.unassign_staff(assignment_id)

        assert result["ok"] is True
        rollback_id = result["data"]["rollback_id"]
        assert rollback_id is not None
        assert rollback_id.startswith("rb_")
        row = _get_row(db_path, "rollbacks", rollback_id)
        assert row is not None
        assert row["entity_type"] == "staff_assignment"
        assert row["entity_id"] == assignment_id

    def test_rollback_record_contains_previous_state(self, engine, db_path):
        assignment_id = self._assign(engine, db_path, "staff-un4", "appt-un4")
        result = engine.unassign_staff(assignment_id)

        rollback_id = result["data"]["rollback_id"]
        row = _get_row(db_path, "rollbacks", rollback_id)
        prev_state = json.loads(row["previous_state_json"])
        assert prev_state["id"] == assignment_id
        assert prev_state["staff_id"] == "staff-un4"
        assert prev_state["appointment_id"] == "appt-un4"

    def test_previous_state_in_response_data(self, engine, db_path):
        assignment_id = self._assign(engine, db_path, "staff-un5", "appt-un5")
        result = engine.unassign_staff(assignment_id)

        prev = result["data"]["previous_state"]
        assert prev["id"] == assignment_id
        assert prev["staff_id"] == "staff-un5"

    def test_nonexistent_assignment_returns_error(self, engine, db_path):
        result = engine.unassign_staff("nonexistent-assignment-id")

        assert result["ok"] is False
        assert "not found" in result["error"].lower()

    def test_double_unassign_second_call_returns_error(self, engine, db_path):
        assignment_id = self._assign(engine, db_path, "staff-un6", "appt-un6")
        engine.unassign_staff(assignment_id)
        result = engine.unassign_staff(assignment_id)

        assert result["ok"] is False
        assert "not found" in result["error"].lower()

    def test_immutable_receipt_written_on_unassign(self, engine, db_path):
        assignment_id = self._assign(engine, db_path, "staff-un7", "appt-un7")
        engine.unassign_staff(assignment_id)

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM immutable_receipts WHERE action_type = ?",
            ("unassign_staff",),
        ).fetchall()
        conn.close()
        assert len(rows) >= 1

    def test_receipt_has_rollback_available(self, engine, db_path):
        assignment_id = self._assign(engine, db_path, "staff-un8", "appt-un8")
        result = engine.unassign_staff(assignment_id)

        assert result["ok"] is True
        assert result["receipt"]["rollback_available"] is True
        assert result["receipt"]["outcome"] == "executed"
