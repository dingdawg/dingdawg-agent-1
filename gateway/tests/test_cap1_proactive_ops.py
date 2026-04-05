"""Comprehensive tests for cap1_proactive_ops.ProactiveOpsEngine.

Uses real SQLite via tempfile — no mocks for the DB layer.
Each test creates its own isolated database, initialised with ensure_tables().
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator

import pytest

from isg_agent.capabilities.shared.db_schema import ensure_tables
from isg_agent.capabilities.cap1_proactive_ops import ProactiveOpsEngine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

UTC = timezone.utc


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _make_appointments_table(conn: sqlite3.Connection) -> None:
    """Create the optional appointments table (not in ensure_tables)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS appointments (
            id          TEXT PRIMARY KEY,
            business_id TEXT,
            client_id   TEXT,
            service     TEXT,
            start_time  TEXT,
            status      TEXT DEFAULT 'scheduled'
        )
        """
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db() -> Generator[str, None, None]:
    """Yield a path to a fresh temp SQLite DB with all capability tables."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    ensure_tables(db_path)
    yield db_path
    # Cleanup
    for suffix in ("", "-wal", "-shm"):
        p = db_path + suffix
        if os.path.exists(p):
            os.unlink(p)


@pytest.fixture()
def engine(tmp_db: str) -> ProactiveOpsEngine:
    return ProactiveOpsEngine(db_path=tmp_db)


# ---------------------------------------------------------------------------
# Convenience DB writers
# ---------------------------------------------------------------------------


def _insert_payment(
    db_path: str,
    *,
    record_id: str,
    client_id: str = "client_1",
    amount_cents: int = 5000,
    currency: str = "usd",
    status: str = "pending",
    created_at: str | None = None,
    paid_at: str | None = None,
) -> None:
    if created_at is None:
        created_at = _iso(_utc_now())
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO payment_link_records
            (id, client_id, amount_cents, currency, status, created_at, paid_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (record_id, client_id, amount_cents, currency, status, created_at, paid_at),
    )
    conn.commit()
    conn.close()


def _insert_thread(
    db_path: str,
    *,
    thread_id: str,
    client_id: str = "client_1",
    channel: str = "sms",
    status: str = "active",
    missed_at: str | None = None,
    recovered_at: str | None = None,
) -> None:
    started_at = _iso(_utc_now() - timedelta(hours=2))
    last_message_at = _iso(_utc_now() - timedelta(hours=1))
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO conversation_threads
            (id, client_id, channel, status, started_at, last_message_at,
             missed_at, recovered_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            thread_id,
            client_id,
            channel,
            status,
            started_at,
            last_message_at,
            missed_at,
            recovered_at,
        ),
    )
    conn.commit()
    conn.close()


def _insert_appointment(
    db_path: str,
    *,
    appt_id: str,
    business_id: str = "biz_1",
    client_id: str = "client_1",
    service: str = "Haircut",
    start_time: str | None = None,
    status: str = "scheduled",
) -> None:
    if start_time is None:
        start_time = _iso(_utc_now())
    conn = sqlite3.connect(db_path)
    _make_appointments_table(conn)
    conn.execute(
        """
        INSERT INTO appointments (id, business_id, client_id, service, start_time, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (appt_id, business_id, client_id, service, start_time, status),
    )
    conn.commit()
    conn.close()


def _insert_trigger(
    db_path: str,
    *,
    trigger_id: str,
    trigger_type: str,
    condition_json: str = "{}",
    enabled: int = 1,
    last_checked_at: str | None = None,
    last_fired_at: str | None = None,
) -> None:
    created_at = _iso(_utc_now())
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO trigger_monitors
            (id, trigger_type, condition_json, enabled,
             last_checked_at, last_fired_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            trigger_id,
            trigger_type,
            condition_json,
            enabled,
            last_checked_at,
            last_fired_at,
            created_at,
        ),
    )
    conn.commit()
    conn.close()


# ===========================================================================
# 1. morning_pulse
# ===========================================================================


class TestMorningPulse:
    """Tests for ProactiveOpsEngine.morning_pulse."""

    def test_returns_ok_envelope(self, engine: ProactiveOpsEngine, tmp_db: str) -> None:
        result = engine.morning_pulse("biz_1")
        assert result["ok"] is True
        assert "data" in result
        assert "receipt" in result

    def test_receipt_fields(self, engine: ProactiveOpsEngine, tmp_db: str) -> None:
        result = engine.morning_pulse("biz_1")
        receipt = result["receipt"]
        assert receipt["action_type"] == "morning_pulse"
        assert receipt["outcome"] == "executed"
        assert receipt["rollback_available"] is True

    def test_no_appointments_table_appointment_count_zero(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        """When appointments table does not exist, count is 0 and list is empty."""
        result = engine.morning_pulse("biz_1")
        data = result["data"]
        assert data["appointment_count"] == 0
        assert data["appointments"] == []

    def test_with_appointments_table_no_rows(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        """Appointments table exists but no rows for today → count 0."""
        conn = sqlite3.connect(tmp_db)
        _make_appointments_table(conn)
        conn.close()

        result = engine.morning_pulse("biz_1")
        data = result["data"]
        assert data["appointment_count"] == 0
        assert data["appointments"] == []

    def test_with_appointments_today(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        """Today's appointments are included in the pulse."""
        today_iso = _iso(_utc_now().replace(hour=10, minute=0, second=0, microsecond=0))
        _insert_appointment(
            tmp_db,
            appt_id="appt_1",
            business_id="biz_1",
            start_time=today_iso,
            status="scheduled",
        )
        result = engine.morning_pulse("biz_1")
        data = result["data"]
        assert data["appointment_count"] == 1
        assert len(data["appointments"]) == 1
        assert data["appointments"][0]["id"] == "appt_1"

    def test_appointments_only_for_this_business(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        """Appointments belonging to a different business_id are excluded."""
        today_iso = _iso(_utc_now().replace(hour=9, minute=0, second=0, microsecond=0))
        _insert_appointment(
            tmp_db,
            appt_id="appt_other",
            business_id="biz_OTHER",
            start_time=today_iso,
        )
        result = engine.morning_pulse("biz_1")
        assert result["data"]["appointment_count"] == 0

    def test_pending_payments_included(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        _insert_payment(tmp_db, record_id="pay_1", status="pending")
        result = engine.morning_pulse("biz_1")
        data = result["data"]
        assert data["pending_payment_count"] == 1
        assert data["pending_payments"][0]["id"] == "pay_1"
        assert "Follow up on 1 pending payment(s)." in data["action_items"]

    def test_multiple_pending_payments(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        for i in range(3):
            _insert_payment(tmp_db, record_id=f"pay_{i}", status="pending")
        result = engine.morning_pulse("biz_1")
        data = result["data"]
        assert data["pending_payment_count"] == 3

    def test_paid_payments_not_counted_as_pending(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        _insert_payment(tmp_db, record_id="pay_paid", status="paid")
        result = engine.morning_pulse("biz_1")
        assert result["data"]["pending_payment_count"] == 0

    def test_overdue_payments_older_than_24h(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        old_ts = _iso(_utc_now() - timedelta(hours=25))
        _insert_payment(
            tmp_db, record_id="pay_old", status="pending", created_at=old_ts
        )
        result = engine.morning_pulse("biz_1")
        data = result["data"]
        assert data["overdue_invoice_count"] == 1
        assert data["overdue_invoices"][0]["id"] == "pay_old"
        assert "Escalate 1 overdue invoice(s) (>24 h)." in data["action_items"]

    def test_recent_pending_payment_not_overdue(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        recent_ts = _iso(_utc_now() - timedelta(hours=1))
        _insert_payment(
            tmp_db, record_id="pay_new", status="pending", created_at=recent_ts
        )
        result = engine.morning_pulse("biz_1")
        assert result["data"]["overdue_invoice_count"] == 0

    def test_missed_threads_included(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        _insert_thread(
            tmp_db,
            thread_id="thread_1",
            status="active",
            missed_at=_iso(_utc_now() - timedelta(hours=1)),
            recovered_at=None,
        )
        result = engine.morning_pulse("biz_1")
        data = result["data"]
        assert data["unread_message_count"] == 1
        assert data["unread_messages"][0]["id"] == "thread_1"
        assert "Respond to 1 unread conversation thread(s)." in data["action_items"]

    def test_recovered_thread_not_included(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        _insert_thread(
            tmp_db,
            thread_id="thread_recovered",
            status="active",
            missed_at=_iso(_utc_now() - timedelta(hours=2)),
            recovered_at=_iso(_utc_now() - timedelta(hours=1)),
        )
        result = engine.morning_pulse("biz_1")
        assert result["data"]["unread_message_count"] == 0

    def test_thread_without_missed_at_not_counted(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        _insert_thread(
            tmp_db,
            thread_id="thread_no_miss",
            status="active",
            missed_at=None,
            recovered_at=None,
        )
        result = engine.morning_pulse("biz_1")
        assert result["data"]["unread_message_count"] == 0

    def test_action_items_empty_when_nothing_outstanding(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        result = engine.morning_pulse("biz_1")
        assert result["data"]["action_items"] == []

    def test_pulse_persisted_to_morning_pulse_log(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        engine.morning_pulse("biz_1")
        conn = sqlite3.connect(tmp_db)
        rows = conn.execute("SELECT * FROM morning_pulse_log").fetchall()
        conn.close()
        assert len(rows) == 1

    def test_pulse_upserts_on_same_date(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        """Calling morning_pulse twice on same date updates — does not duplicate."""
        engine.morning_pulse("biz_1")
        engine.morning_pulse("biz_1")
        conn = sqlite3.connect(tmp_db)
        rows = conn.execute("SELECT * FROM morning_pulse_log").fetchall()
        conn.close()
        assert len(rows) == 1

    def test_pulse_date_field(self, engine: ProactiveOpsEngine, tmp_db: str) -> None:
        result = engine.morning_pulse("biz_1")
        today = _utc_now().strftime("%Y-%m-%d")
        assert result["data"]["pulse_date"] == today

    def test_business_id_in_summary(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        result = engine.morning_pulse("my_business_42")
        assert result["data"]["business_id"] == "my_business_42"

    def test_all_action_items_present(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        """All four action items fire when every condition is met."""
        today_iso = _iso(_utc_now().replace(hour=11, minute=0, second=0, microsecond=0))
        _insert_appointment(
            tmp_db, appt_id="appt_a1", business_id="biz_1", start_time=today_iso
        )
        _insert_payment(tmp_db, record_id="pay_p1", status="pending")
        old_ts = _iso(_utc_now() - timedelta(hours=30))
        _insert_payment(
            tmp_db, record_id="pay_old", status="pending", created_at=old_ts
        )
        _insert_thread(
            tmp_db,
            thread_id="thread_m1",
            status="active",
            missed_at=_iso(_utc_now() - timedelta(hours=1)),
        )
        result = engine.morning_pulse("biz_1")
        items = result["data"]["action_items"]
        assert any("appointment" in i for i in items)
        assert any("pending payment" in i for i in items)
        assert any("overdue invoice" in i for i in items)
        assert any("unread conversation thread" in i for i in items)


# ===========================================================================
# 2. check_triggers
# ===========================================================================


class TestCheckTriggers:
    """Tests for ProactiveOpsEngine.check_triggers."""

    def test_no_triggers_returns_empty_list(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        result = engine.check_triggers("biz_1")
        assert result["ok"] is True
        assert result["data"] == []

    def test_disabled_triggers_not_evaluated(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        _insert_trigger(
            tmp_db,
            trigger_id="trg_disabled",
            trigger_type="payment_overdue",
            enabled=0,
        )
        result = engine.check_triggers("biz_1")
        assert result["data"] == []

    def test_last_checked_at_updated_even_when_not_fired(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        """last_checked_at must be set regardless of firing."""
        _insert_trigger(
            tmp_db,
            trigger_id="trg_check",
            trigger_type="payment_overdue",
            enabled=1,
        )
        engine.check_triggers("biz_1")
        conn = sqlite3.connect(tmp_db)
        row = conn.execute(
            "SELECT last_checked_at FROM trigger_monitors WHERE id = ?",
            ("trg_check",),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] is not None  # timestamp was written

    def test_payment_overdue_trigger_fires(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        old_ts = _iso(_utc_now() - timedelta(hours=50))
        _insert_payment(
            tmp_db,
            record_id="pay_over",
            status="pending",
            created_at=old_ts,
            amount_cents=9900,
        )
        _insert_trigger(
            tmp_db,
            trigger_id="trg_po",
            trigger_type="payment_overdue",
            condition_json=json.dumps({"hours_overdue": 48}),
        )
        result = engine.check_triggers("biz_1")
        fired = result["data"]
        assert len(fired) == 1
        assert fired[0]["trigger_id"] == "trg_po"
        assert fired[0]["trigger_type"] == "payment_overdue"
        assert fired[0]["fired"] is True
        assert fired[0]["details"]["overdue_count"] == 1
        assert fired[0]["details"]["total_overdue_cents"] == 9900

    def test_payment_overdue_trigger_does_not_fire_when_no_overdue(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        recent_ts = _iso(_utc_now() - timedelta(hours=1))
        _insert_payment(
            tmp_db, record_id="pay_fresh", status="pending", created_at=recent_ts
        )
        _insert_trigger(
            tmp_db,
            trigger_id="trg_po2",
            trigger_type="payment_overdue",
            condition_json=json.dumps({"hours_overdue": 48}),
        )
        result = engine.check_triggers("biz_1")
        assert result["data"] == []

    def test_no_show_followup_trigger_fires(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        recent_iso = _iso(_utc_now() - timedelta(hours=1))
        _insert_appointment(
            tmp_db,
            appt_id="appt_ns",
            business_id="biz_1",
            start_time=recent_iso,
            status="no_show",
        )
        _insert_trigger(
            tmp_db,
            trigger_id="trg_ns",
            trigger_type="no_show_followup",
            condition_json=json.dumps({"hours_back": 24}),
        )
        result = engine.check_triggers("biz_1")
        fired = result["data"]
        assert len(fired) == 1
        assert fired[0]["trigger_type"] == "no_show_followup"
        assert fired[0]["details"]["no_show_count"] == 1
        assert "appt_ns" in fired[0]["details"]["appointment_ids"]

    def test_no_show_trigger_does_not_fire_without_appointments_table(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        _insert_trigger(
            tmp_db,
            trigger_id="trg_ns2",
            trigger_type="no_show_followup",
        )
        result = engine.check_triggers("biz_1")
        # No appointments table → should not fire
        assert result["data"] == []

    def test_rebooking_reminder_trigger_fires(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        old_iso = _iso(_utc_now() - timedelta(days=40))
        _insert_appointment(
            tmp_db,
            appt_id="appt_old",
            business_id="biz_1",
            client_id="client_lapsed",
            start_time=old_iso,
            status="completed",
        )
        _insert_trigger(
            tmp_db,
            trigger_id="trg_reb",
            trigger_type="rebooking_reminder",
            condition_json=json.dumps({"days_since_last_visit": 30}),
        )
        result = engine.check_triggers("biz_1")
        fired = result["data"]
        assert len(fired) == 1
        assert fired[0]["trigger_type"] == "rebooking_reminder"
        assert fired[0]["details"]["client_count"] == 1

    def test_rebooking_reminder_does_not_fire_for_recent_visit(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        recent_iso = _iso(_utc_now() - timedelta(days=5))
        _insert_appointment(
            tmp_db,
            appt_id="appt_recent",
            business_id="biz_1",
            client_id="client_active",
            start_time=recent_iso,
            status="completed",
        )
        _insert_trigger(
            tmp_db,
            trigger_id="trg_reb2",
            trigger_type="rebooking_reminder",
            condition_json=json.dumps({"days_since_last_visit": 30}),
        )
        result = engine.check_triggers("biz_1")
        assert result["data"] == []

    def test_review_request_trigger_fires(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        # Completed appointment more than 2 hours ago today
        completed_iso = _iso(_utc_now() - timedelta(hours=3))
        _insert_appointment(
            tmp_db,
            appt_id="appt_done",
            business_id="biz_1",
            start_time=completed_iso,
            status="completed",
        )
        _insert_trigger(
            tmp_db,
            trigger_id="trg_rev",
            trigger_type="review_request",
            condition_json=json.dumps({"hours_after_completion": 2}),
        )
        result = engine.check_triggers("biz_1")
        fired = result["data"]
        assert len(fired) == 1
        assert fired[0]["trigger_type"] == "review_request"
        assert fired[0]["details"]["eligible_count"] == 1

    def test_review_request_does_not_fire_too_soon(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        just_now = _iso(_utc_now() - timedelta(minutes=30))
        _insert_appointment(
            tmp_db,
            appt_id="appt_fresh",
            business_id="biz_1",
            start_time=just_now,
            status="completed",
        )
        _insert_trigger(
            tmp_db,
            trigger_id="trg_rev2",
            trigger_type="review_request",
            condition_json=json.dumps({"hours_after_completion": 2}),
        )
        result = engine.check_triggers("biz_1")
        assert result["data"] == []

    def test_multiple_triggers_all_four_fire(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        # payment overdue
        old_ts = _iso(_utc_now() - timedelta(hours=60))
        _insert_payment(
            tmp_db, record_id="pay_x", status="pending", created_at=old_ts
        )
        _insert_trigger(
            tmp_db,
            trigger_id="trg_A",
            trigger_type="payment_overdue",
            condition_json=json.dumps({"hours_overdue": 48}),
        )
        # no_show
        ns_iso = _iso(_utc_now() - timedelta(hours=2))
        _insert_appointment(
            tmp_db,
            appt_id="appt_ns2",
            business_id="biz_1",
            start_time=ns_iso,
            status="no_show",
        )
        _insert_trigger(
            tmp_db,
            trigger_id="trg_B",
            trigger_type="no_show_followup",
            condition_json=json.dumps({"hours_back": 24}),
        )
        # rebooking
        old_visit = _iso(_utc_now() - timedelta(days=45))
        _insert_appointment(
            tmp_db,
            appt_id="appt_old2",
            business_id="biz_1",
            client_id="client_lapsed2",
            start_time=old_visit,
            status="completed",
        )
        _insert_trigger(
            tmp_db,
            trigger_id="trg_C",
            trigger_type="rebooking_reminder",
            condition_json=json.dumps({"days_since_last_visit": 30}),
        )
        # review request
        done_iso = _iso(_utc_now() - timedelta(hours=5))
        _insert_appointment(
            tmp_db,
            appt_id="appt_done2",
            business_id="biz_1",
            start_time=done_iso,
            status="completed",
        )
        _insert_trigger(
            tmp_db,
            trigger_id="trg_D",
            trigger_type="review_request",
            condition_json=json.dumps({"hours_after_completion": 2}),
        )

        result = engine.check_triggers("biz_1")
        assert result["ok"] is True
        fired_types = {item["trigger_type"] for item in result["data"]}
        assert fired_types == {
            "payment_overdue",
            "no_show_followup",
            "rebooking_reminder",
            "review_request",
        }

    def test_fired_trigger_updates_last_fired_at(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        old_ts = _iso(_utc_now() - timedelta(hours=60))
        _insert_payment(
            tmp_db, record_id="pay_fired", status="pending", created_at=old_ts
        )
        _insert_trigger(
            tmp_db,
            trigger_id="trg_fired",
            trigger_type="payment_overdue",
            condition_json=json.dumps({"hours_overdue": 48}),
        )
        engine.check_triggers("biz_1")
        conn = sqlite3.connect(tmp_db)
        row = conn.execute(
            "SELECT last_fired_at FROM trigger_monitors WHERE id = ?",
            ("trg_fired",),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] is not None  # last_fired_at was written

    def test_non_firing_trigger_does_not_set_last_fired_at(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        _insert_trigger(
            tmp_db,
            trigger_id="trg_unfired",
            trigger_type="payment_overdue",
        )
        engine.check_triggers("biz_1")
        conn = sqlite3.connect(tmp_db)
        row = conn.execute(
            "SELECT last_fired_at FROM trigger_monitors WHERE id = ?",
            ("trg_unfired",),
        ).fetchone()
        conn.close()
        assert row[0] is None  # should remain NULL

    def test_returns_ok_envelope_structure(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        result = engine.check_triggers("biz_1")
        assert "ok" in result
        assert "data" in result
        assert "receipt" in result
        assert result["receipt"]["action_type"] == "check_triggers"

    def test_malformed_condition_json_does_not_crash(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        """A trigger with invalid condition_json should evaluate with empty condition."""
        _insert_trigger(
            tmp_db,
            trigger_id="trg_bad",
            trigger_type="payment_overdue",
            condition_json="NOT_VALID_JSON",
        )
        result = engine.check_triggers("biz_1")
        # Should not raise — result is still an ok envelope
        assert result["ok"] is True


# ===========================================================================
# 3. weekly_intelligence
# ===========================================================================


class TestWeeklyIntelligence:
    """Tests for ProactiveOpsEngine.weekly_intelligence."""

    def test_returns_ok_envelope(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        result = engine.weekly_intelligence("biz_1")
        assert result["ok"] is True
        assert "data" in result
        assert "receipt" in result

    def test_receipt_fields(self, engine: ProactiveOpsEngine, tmp_db: str) -> None:
        result = engine.weekly_intelligence("biz_1")
        assert result["receipt"]["action_type"] == "weekly_intelligence"
        assert result["receipt"]["outcome"] == "executed"

    def test_empty_data_returns_zeros(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        result = engine.weekly_intelligence("biz_1")
        data = result["data"]
        assert data["appointment_count"] == 0
        assert data["revenue_cents"] == 0
        assert data["new_client_count"] == 0
        assert data["top_services"] == []

    def test_empty_data_retention_rate_none_when_no_appointments_table(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        """When the appointments table is absent, retention_rate is None (no data)."""
        result = engine.weekly_intelligence("biz_1")
        assert result["data"]["client_retention_rate"] is None

    def test_week_start_field_is_7_days_ago(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        result = engine.weekly_intelligence("biz_1")
        expected = (_utc_now() - timedelta(days=7)).strftime("%Y-%m-%d")
        assert result["data"]["week_start"] == expected

    def test_completed_appointments_counted(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        within_window = _iso(_utc_now() - timedelta(days=3))
        _insert_appointment(
            tmp_db,
            appt_id="appt_w1",
            business_id="biz_1",
            start_time=within_window,
            status="completed",
        )
        result = engine.weekly_intelligence("biz_1")
        assert result["data"]["appointment_count"] == 1

    def test_appointments_outside_window_excluded(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        old_iso = _iso(_utc_now() - timedelta(days=10))
        _insert_appointment(
            tmp_db,
            appt_id="appt_old",
            business_id="biz_1",
            start_time=old_iso,
            status="completed",
        )
        result = engine.weekly_intelligence("biz_1")
        assert result["data"]["appointment_count"] == 0

    def test_revenue_from_paid_payments_in_window(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        paid_at = _iso(_utc_now() - timedelta(days=2))
        conn = sqlite3.connect(tmp_db)
        conn.execute(
            """
            INSERT INTO payment_link_records
                (id, client_id, amount_cents, currency, status, created_at, paid_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("pay_paid_1", "client_1", 7500, "usd", "paid", paid_at, paid_at),
        )
        conn.execute(
            """
            INSERT INTO payment_link_records
                (id, client_id, amount_cents, currency, status, created_at, paid_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("pay_paid_2", "client_2", 2500, "usd", "paid", paid_at, paid_at),
        )
        conn.commit()
        conn.close()
        result = engine.weekly_intelligence("biz_1")
        assert result["data"]["revenue_cents"] == 10000

    def test_revenue_outside_window_not_counted(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        old_paid_at = _iso(_utc_now() - timedelta(days=10))
        conn = sqlite3.connect(tmp_db)
        conn.execute(
            """
            INSERT INTO payment_link_records
                (id, client_id, amount_cents, currency, status, created_at, paid_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("pay_old", "client_1", 5000, "usd", "paid", old_paid_at, old_paid_at),
        )
        conn.commit()
        conn.close()
        result = engine.weekly_intelligence("biz_1")
        assert result["data"]["revenue_cents"] == 0

    def test_new_client_count(self, engine: ProactiveOpsEngine, tmp_db: str) -> None:
        """Client whose first appointment is this week → counted as new."""
        within_iso = _iso(_utc_now() - timedelta(days=3))
        _insert_appointment(
            tmp_db,
            appt_id="appt_new",
            business_id="biz_1",
            client_id="brand_new_client",
            start_time=within_iso,
            status="completed",
        )
        result = engine.weekly_intelligence("biz_1")
        assert result["data"]["new_client_count"] == 1

    def test_returning_client_not_counted_as_new(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        """Client who visited before the window is a returning client."""
        old_iso = _iso(_utc_now() - timedelta(days=14))
        within_iso = _iso(_utc_now() - timedelta(days=3))
        _insert_appointment(
            tmp_db,
            appt_id="appt_prev",
            business_id="biz_1",
            client_id="returning_client",
            start_time=old_iso,
            status="completed",
        )
        _insert_appointment(
            tmp_db,
            appt_id="appt_now",
            business_id="biz_1",
            client_id="returning_client",
            start_time=within_iso,
            status="completed",
        )
        result = engine.weekly_intelligence("biz_1")
        assert result["data"]["new_client_count"] == 0

    def test_top_services_aggregated(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        within_iso = _iso(_utc_now() - timedelta(days=2))
        for i in range(3):
            _insert_appointment(
                tmp_db,
                appt_id=f"appt_svc_{i}",
                business_id="biz_1",
                service="Haircut",
                start_time=within_iso,
                status="completed",
            )
        _insert_appointment(
            tmp_db,
            appt_id="appt_svc_other",
            business_id="biz_1",
            service="Massage",
            start_time=within_iso,
            status="completed",
        )
        result = engine.weekly_intelligence("biz_1")
        top = result["data"]["top_services"]
        assert len(top) >= 1
        assert top[0]["service"] == "Haircut"
        assert top[0]["count"] == 3

    def test_retention_rate_computed_correctly(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        """2 clients this week, 1 returning → retention = 0.5."""
        old_iso = _iso(_utc_now() - timedelta(days=14))
        within_iso = _iso(_utc_now() - timedelta(days=2))

        # Returning client
        _insert_appointment(
            tmp_db,
            appt_id="appt_ret_old",
            business_id="biz_1",
            client_id="client_returning",
            start_time=old_iso,
            status="completed",
        )
        _insert_appointment(
            tmp_db,
            appt_id="appt_ret_new",
            business_id="biz_1",
            client_id="client_returning",
            start_time=within_iso,
            status="completed",
        )
        # New client
        _insert_appointment(
            tmp_db,
            appt_id="appt_new_only",
            business_id="biz_1",
            client_id="client_brand_new",
            start_time=within_iso,
            status="completed",
        )

        result = engine.weekly_intelligence("biz_1")
        rate = result["data"]["client_retention_rate"]
        assert rate == 0.5

    def test_report_persisted_to_weekly_intelligence_table(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        engine.weekly_intelligence("biz_1")
        conn = sqlite3.connect(tmp_db)
        rows = conn.execute("SELECT * FROM weekly_intelligence").fetchall()
        conn.close()
        assert len(rows) == 1

    def test_report_upserts_on_same_week_start(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        engine.weekly_intelligence("biz_1")
        engine.weekly_intelligence("biz_1")
        conn = sqlite3.connect(tmp_db)
        rows = conn.execute("SELECT * FROM weekly_intelligence").fetchall()
        conn.close()
        assert len(rows) == 1

    def test_business_id_in_report(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        result = engine.weekly_intelligence("biz_unique_99")
        assert result["data"]["business_id"] == "biz_unique_99"

    def test_no_appointments_table_no_crash(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        """weekly_intelligence works even if the appointments table is absent."""
        result = engine.weekly_intelligence("biz_1")
        assert result["ok"] is True
        assert result["data"]["appointment_count"] == 0


# ===========================================================================
# 4. create_trigger
# ===========================================================================


class TestCreateTrigger:
    """Tests for ProactiveOpsEngine.create_trigger."""

    @pytest.mark.parametrize(
        "trigger_type",
        [
            "no_show_followup",
            "payment_overdue",
            "rebooking_reminder",
            "review_request",
        ],
    )
    def test_valid_trigger_types_succeed(
        self,
        trigger_type: str,
        engine: ProactiveOpsEngine,
        tmp_db: str,
    ) -> None:
        result = engine.create_trigger(trigger_type, '{"key": "value"}')
        assert result["ok"] is True
        assert result["data"]["trigger_type"] == trigger_type

    def test_returns_ok_envelope_structure(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        result = engine.create_trigger("payment_overdue", '{"hours_overdue": 48}')
        assert "ok" in result
        assert "data" in result
        assert "receipt" in result

    def test_receipt_action_type(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        result = engine.create_trigger("payment_overdue", "{}")
        assert result["receipt"]["action_type"] == "create_trigger"
        assert result["receipt"]["outcome"] == "executed"
        assert result["receipt"]["rollback_available"] is True

    def test_trigger_persisted_to_db(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        engine.create_trigger("review_request", '{"hours_after_completion": 2}')
        conn = sqlite3.connect(tmp_db)
        rows = conn.execute(
            "SELECT * FROM trigger_monitors WHERE trigger_type = 'review_request'"
        ).fetchall()
        conn.close()
        assert len(rows) == 1

    def test_trigger_enabled_by_default(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        result = engine.create_trigger("no_show_followup", "{}")
        assert result["data"]["enabled"] == 1

    def test_trigger_last_checked_at_is_none(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        result = engine.create_trigger("rebooking_reminder", "{}")
        assert result["data"]["last_checked_at"] is None

    def test_trigger_last_fired_at_is_none(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        result = engine.create_trigger("rebooking_reminder", "{}")
        assert result["data"]["last_fired_at"] is None

    def test_trigger_id_has_trg_prefix(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        result = engine.create_trigger("payment_overdue", "{}")
        assert result["data"]["id"].startswith("trg_")

    def test_invalid_trigger_type_returns_err(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        result = engine.create_trigger("nonexistent_type", "{}")
        assert result["ok"] is False
        assert "Invalid trigger_type" in result["error"]

    def test_invalid_trigger_type_error_details(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        result = engine.create_trigger("bad_type", "{}")
        assert result["details"]["trigger_type"] == "bad_type"

    def test_invalid_json_condition_returns_err(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        result = engine.create_trigger("payment_overdue", "{not valid json}")
        assert result["ok"] is False
        assert "condition_json is not valid JSON" in result["error"]

    def test_invalid_json_error_details(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        result = engine.create_trigger("payment_overdue", "NOT_JSON")
        assert result["details"]["condition_json"] == "NOT_JSON"

    def test_empty_json_object_is_valid(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        result = engine.create_trigger("no_show_followup", "{}")
        assert result["ok"] is True

    def test_condition_json_stored_as_provided(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        condition = '{"hours_back": 12}'
        result = engine.create_trigger("no_show_followup", condition)
        assert result["data"]["condition_json"] == condition

    def test_multiple_triggers_can_be_created(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        engine.create_trigger("payment_overdue", "{}")
        engine.create_trigger("review_request", "{}")
        engine.create_trigger("no_show_followup", "{}")
        conn = sqlite3.connect(tmp_db)
        count = conn.execute(
            "SELECT COUNT(*) FROM trigger_monitors"
        ).fetchone()[0]
        conn.close()
        assert count == 3

    def test_created_at_is_set(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        result = engine.create_trigger("payment_overdue", "{}")
        assert result["data"]["created_at"] is not None
        assert len(result["data"]["created_at"]) > 0


# ===========================================================================
# 5. undo_last_pulse
# ===========================================================================


class TestUndoLastPulse:
    """Tests for ProactiveOpsEngine.undo_last_pulse."""

    def test_empty_table_returns_err(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        result = engine.undo_last_pulse("biz_1")
        assert result["ok"] is False
        assert "No morning_pulse_log entry found to undo" in result["error"]

    def test_empty_table_error_action_type(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        result = engine.undo_last_pulse("biz_1")
        assert result["receipt"]["action_type"] == "undo_last_pulse"
        assert result["receipt"]["outcome"] == "failed"

    def test_deletes_existing_entry(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        engine.morning_pulse("biz_1")
        result = engine.undo_last_pulse("biz_1")
        assert result["ok"] is True
        # Confirm DB is now empty
        conn = sqlite3.connect(tmp_db)
        rows = conn.execute("SELECT * FROM morning_pulse_log").fetchall()
        conn.close()
        assert len(rows) == 0

    def test_returns_deleted_entry_in_data(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        engine.morning_pulse("biz_1")
        result = engine.undo_last_pulse("biz_1")
        assert result["ok"] is True
        assert "deleted" in result["data"]
        deleted = result["data"]["deleted"]
        assert "id" in deleted
        assert "pulse_date" in deleted
        assert "summary_json" in deleted
        assert "generated_at" in deleted

    def test_receipt_rolled_back(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        engine.morning_pulse("biz_1")
        result = engine.undo_last_pulse("biz_1")
        assert result["receipt"]["outcome"] == "rolled_back"
        assert result["receipt"]["rollback_available"] is False

    def test_receipt_action_type(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        engine.morning_pulse("biz_1")
        result = engine.undo_last_pulse("biz_1")
        assert result["receipt"]["action_type"] == "undo_last_pulse"

    def test_deletes_most_recent_when_multiple_exist(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        """When two rows exist, the one with the latest generated_at is deleted."""
        conn = sqlite3.connect(tmp_db)
        earlier = _iso(_utc_now() - timedelta(hours=2))
        later = _iso(_utc_now() - timedelta(hours=1))
        conn.execute(
            "INSERT INTO morning_pulse_log (id, pulse_date, summary_json, generated_at) VALUES (?, ?, ?, ?)",
            ("pulse_old", "2026-03-13", '{"x":1}', earlier),
        )
        conn.execute(
            "INSERT INTO morning_pulse_log (id, pulse_date, summary_json, generated_at) VALUES (?, ?, ?, ?)",
            ("pulse_new", "2026-03-14", '{"x":2}', later),
        )
        conn.commit()
        conn.close()

        result = engine.undo_last_pulse("biz_1")
        assert result["ok"] is True
        assert result["data"]["deleted"]["id"] == "pulse_new"

        # Older entry still exists
        conn2 = sqlite3.connect(tmp_db)
        remaining = conn2.execute(
            "SELECT id FROM morning_pulse_log"
        ).fetchall()
        conn2.close()
        assert len(remaining) == 1
        assert remaining[0][0] == "pulse_old"

    def test_second_undo_on_empty_table_returns_err(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        engine.morning_pulse("biz_1")
        engine.undo_last_pulse("biz_1")
        result = engine.undo_last_pulse("biz_1")
        assert result["ok"] is False

    def test_triggered_by_in_receipt(
        self, engine: ProactiveOpsEngine, tmp_db: str
    ) -> None:
        engine.morning_pulse("biz_1")
        result = engine.undo_last_pulse("my_biz_99")
        assert result["receipt"]["triggered_by"] == "my_biz_99"
