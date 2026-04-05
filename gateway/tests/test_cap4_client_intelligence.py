"""Comprehensive tests for ClientIntelligenceEngine (cap4_client_intelligence.py).

All tests use a real SQLite database created in a temporary directory so
every query path exercises the actual SQL.  No mocking of DB I/O.

Fixtures seed clients, appointments, payment_link_records, subscriptions,
conversation_threads, and conversation_messages before each test group.
"""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

import pytest

from isg_agent.capabilities.cap4_client_intelligence import ClientIntelligenceEngine
from isg_agent.capabilities.shared.db_schema import ensure_tables

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _days_ago(n: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=n)


def _days_from_now(n: int) -> datetime:
    return datetime.now(UTC) + timedelta(days=n)


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _seed_appointments_table(conn: sqlite3.Connection) -> None:
    """Create the appointments table expected by cap4 (not managed by db_schema)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS appointments (
            id           TEXT PRIMARY KEY,
            business_id  TEXT,
            client_id    TEXT,
            service_name TEXT,
            start_time   TEXT,
            end_time     TEXT,
            status       TEXT DEFAULT 'scheduled'
        )
        """
    )
    conn.commit()


# ---------------------------------------------------------------------------
# DB fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path: Path) -> str:
    """Return a path to a fully-initialised SQLite database."""
    db_path = str(tmp_path / "test_agent.db")
    ensure_tables(db_path)
    conn = _connect(db_path)
    try:
        _seed_appointments_table(conn)
    finally:
        conn.close()
    return db_path


@pytest.fixture()
def engine(db: str) -> ClientIntelligenceEngine:
    return ClientIntelligenceEngine(db_path=db)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _insert_payment(
    db_path: str,
    *,
    client_id: str,
    amount_cents: int,
    status: str,
    payment_id: str | None = None,
) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO payment_link_records (id, client_id, amount_cents, status, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                payment_id or f"pay_{client_id}_{status}_{amount_cents}",
                client_id,
                amount_cents,
                status,
                _iso(_days_ago(10)),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_subscription(
    db_path: str,
    *,
    client_id: str,
    amount_cents: int,
    interval: str,
    status: str = "active",
    sub_id: str | None = None,
) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO subscriptions (id, client_id, amount_cents, interval, status, started_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                sub_id or f"sub_{client_id}_{interval}",
                client_id,
                amount_cents,
                interval,
                status,
                _iso(_days_ago(60)),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_appointment(
    db_path: str,
    *,
    appt_id: str,
    client_id: str,
    business_id: str,
    start_time: datetime,
    service_name: str = "Haircut",
) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO appointments (id, business_id, client_id, service_name, start_time)"
            " VALUES (?, ?, ?, ?, ?)",
            (appt_id, business_id, client_id, service_name, _iso(start_time)),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_conversation(
    db_path: str,
    *,
    thread_id: str,
    client_id: str,
    message_count: int,
    sent_days_ago: int = 5,
) -> None:
    """Create one thread and *message_count* messages sent *sent_days_ago* days ago."""
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO conversation_threads (id, client_id, channel, started_at)"
            " VALUES (?, ?, 'sms', ?)",
            (thread_id, client_id, _iso(_days_ago(sent_days_ago))),
        )
        for i in range(message_count):
            conn.execute(
                "INSERT INTO conversation_messages (id, thread_id, direction, content, sent_at)"
                " VALUES (?, ?, 'inbound', 'msg', ?)",
                (
                    f"msg_{thread_id}_{i}",
                    thread_id,
                    _iso(_days_ago(sent_days_ago)),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _insert_ci(
    db_path: str,
    *,
    ci_id: str,
    client_id: str,
    clv_cents: int = 0,
    churn_risk_score: float = 0.0,
    segment: str | None = None,
    health_score: float = 0.0,
    last_computed_at: str | None = None,
) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO client_intelligence"
            " (id, client_id, clv_cents, churn_risk_score, segment, health_score, last_computed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                ci_id,
                client_id,
                clv_cents,
                churn_risk_score,
                segment,
                health_score,
                last_computed_at or _iso(_days_ago(1)),
            ),
        )
        conn.commit()
    finally:
        conn.close()


# ===========================================================================
# 1. compute_clv
# ===========================================================================


class TestComputeClv:
    def test_returns_ok_envelope(self, engine: ClientIntelligenceEngine, db: str) -> None:
        result = engine.compute_clv("client_no_data")
        assert result["ok"] is True
        assert "data" in result
        assert "receipt" in result

    def test_no_data_returns_zero(self, engine: ClientIntelligenceEngine, db: str) -> None:
        result = engine.compute_clv("ghost_client")
        assert result["ok"] is True
        data = result["data"]
        assert data["clv_cents"] == 0
        assert data["payments_total_cents"] == 0
        assert data["subscription_annualised_cents"] == 0

    def test_paid_payments_summed(self, engine: ClientIntelligenceEngine, db: str) -> None:
        _insert_payment(db, client_id="c1", amount_cents=5000, status="paid", payment_id="p1")
        _insert_payment(db, client_id="c1", amount_cents=3000, status="paid", payment_id="p2")
        result = engine.compute_clv("c1")
        assert result["ok"] is True
        data = result["data"]
        assert data["payments_total_cents"] == 8000
        assert data["clv_cents"] == 8000

    def test_failed_payments_excluded(self, engine: ClientIntelligenceEngine, db: str) -> None:
        _insert_payment(db, client_id="c2", amount_cents=5000, status="paid", payment_id="p3")
        _insert_payment(db, client_id="c2", amount_cents=2000, status="failed", payment_id="p4")
        _insert_payment(db, client_id="c2", amount_cents=1000, status="expired", payment_id="p5")
        result = engine.compute_clv("c2")
        assert result["ok"] is True
        assert result["data"]["payments_total_cents"] == 5000

    def test_monthly_subscription_annualised(self, engine: ClientIntelligenceEngine, db: str) -> None:
        _insert_subscription(db, client_id="c3", amount_cents=2000, interval="month")
        result = engine.compute_clv("c3")
        assert result["ok"] is True
        data = result["data"]
        # 2000 * 12 = 24000
        assert data["subscription_annualised_cents"] == 24000
        assert data["clv_cents"] == 24000

    def test_yearly_subscription_normalised_to_mrr(self, engine: ClientIntelligenceEngine, db: str) -> None:
        # yearly amount_cents = 24000 → MRR = 2000 → annualised = 2000 * 12 = 24000
        _insert_subscription(db, client_id="c4", amount_cents=24000, interval="year")
        result = engine.compute_clv("c4")
        assert result["ok"] is True
        data = result["data"]
        assert data["subscription_annualised_cents"] == 24000

    def test_inactive_subscription_excluded(self, engine: ClientIntelligenceEngine, db: str) -> None:
        _insert_subscription(
            db,
            client_id="c5",
            amount_cents=5000,
            interval="month",
            status="cancelled",
        )
        result = engine.compute_clv("c5")
        assert result["ok"] is True
        assert result["data"]["subscription_annualised_cents"] == 0

    def test_combined_payments_and_subscription(self, engine: ClientIntelligenceEngine, db: str) -> None:
        _insert_payment(db, client_id="c6", amount_cents=10000, status="paid", payment_id="p6")
        _insert_subscription(db, client_id="c6", amount_cents=1000, interval="month")
        result = engine.compute_clv("c6")
        assert result["ok"] is True
        data = result["data"]
        assert data["payments_total_cents"] == 10000
        assert data["subscription_annualised_cents"] == 12000
        assert data["clv_cents"] == 22000

    def test_result_persisted_in_client_intelligence(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        _insert_payment(db, client_id="c7", amount_cents=7500, status="paid", payment_id="p7")
        engine.compute_clv("c7")
        conn = _connect(db)
        row = conn.execute(
            "SELECT clv_cents FROM client_intelligence WHERE client_id = ?", ("c7",)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["clv_cents"] == 7500

    def test_upsert_updates_existing_record(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        _insert_ci(db, ci_id="ci_c8", client_id="c8", clv_cents=100)
        _insert_payment(db, client_id="c8", amount_cents=9000, status="paid", payment_id="p8")
        engine.compute_clv("c8")
        conn = _connect(db)
        row = conn.execute(
            "SELECT clv_cents FROM client_intelligence WHERE client_id = ?", ("c8",)
        ).fetchone()
        conn.close()
        assert row["clv_cents"] == 9000

    def test_receipt_has_executed_outcome(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        result = engine.compute_clv("c_receipt")
        assert result["receipt"]["outcome"] == "executed"
        assert result["receipt"]["action_type"] == "compute_clv"


# ===========================================================================
# 2. assess_churn_risk
# ===========================================================================


class TestAssessChurnRisk:
    def test_returns_ok_envelope(self, engine: ClientIntelligenceEngine, db: str) -> None:
        result = engine.assess_churn_risk("nobody")
        assert result["ok"] is True
        assert "churn_risk_score" in result["data"]

    def test_active_client_low_risk(self, engine: ClientIntelligenceEngine, db: str) -> None:
        """Client with recent appointment, no failures, many messages → low churn."""
        client_id = "active_client"
        _insert_appointment(
            db,
            appt_id="a_active1",
            client_id=client_id,
            business_id="biz1",
            start_time=_days_ago(5),
        )
        _insert_payment(db, client_id=client_id, amount_cents=5000, status="paid", payment_id="pp1")
        _insert_conversation(db, thread_id="t_active", client_id=client_id, message_count=15, sent_days_ago=3)
        result = engine.assess_churn_risk(client_id)
        assert result["ok"] is True
        score = result["data"]["churn_risk_score"]
        assert score < 0.35, f"Expected low churn but got {score}"

    def test_dormant_client_high_risk(self, engine: ClientIntelligenceEngine, db: str) -> None:
        """Client last seen 200 days ago, 3 payment failures → high churn."""
        client_id = "dormant_client"
        _insert_appointment(
            db,
            appt_id="a_dormant1",
            client_id=client_id,
            business_id="biz1",
            start_time=_days_ago(200),
        )
        _insert_payment(db, client_id=client_id, amount_cents=0, status="failed", payment_id="pf1")
        _insert_payment(db, client_id=client_id, amount_cents=0, status="failed", payment_id="pf2")
        _insert_payment(db, client_id=client_id, amount_cents=0, status="failed", payment_id="pf3")
        result = engine.assess_churn_risk(client_id)
        assert result["ok"] is True
        score = result["data"]["churn_risk_score"]
        assert score >= 0.55, f"Expected high churn but got {score}"

    def test_new_client_moderate_risk(self, engine: ClientIntelligenceEngine, db: str) -> None:
        """Client with no appointment history gets moderate trend risk (0.10)."""
        result = engine.assess_churn_risk("brand_new_client")
        assert result["ok"] is True
        data = result["data"]
        factors = data["risk_factors"]["factor_breakdown"]
        # Not enough bookings → trend_factor = 0.10
        assert factors["booking_trend"] == 0.10

    def test_risk_factors_present(self, engine: ClientIntelligenceEngine, db: str) -> None:
        result = engine.assess_churn_risk("any_client")
        risk_factors = result["data"]["risk_factors"]
        assert "days_since_last_appointment" in risk_factors
        assert "payment_failures" in risk_factors
        assert "messages_last_90_days" in risk_factors
        assert "factor_breakdown" in risk_factors

    def test_factor_breakdown_structure(self, engine: ClientIntelligenceEngine, db: str) -> None:
        result = engine.assess_churn_risk("factor_client")
        breakdown = result["data"]["risk_factors"]["factor_breakdown"]
        expected_keys = {
            "appointment_recency",
            "payment_failures",
            "conversation_activity",
            "booking_trend",
        }
        assert expected_keys == set(breakdown.keys())

    def test_score_capped_at_1(self, engine: ClientIntelligenceEngine, db: str) -> None:
        """Score must never exceed 1.0 regardless of factor magnitudes."""
        client_id = "max_risk_client"
        _insert_appointment(
            db,
            appt_id="a_max1",
            client_id=client_id,
            business_id="biz1",
            start_time=_days_ago(365),
        )
        for i in range(5):
            _insert_payment(
                db,
                client_id=client_id,
                amount_cents=0,
                status="failed",
                payment_id=f"pfmax{i}",
            )
        result = engine.assess_churn_risk(client_id)
        assert result["data"]["churn_risk_score"] <= 1.0

    def test_score_floored_at_0(self, engine: ClientIntelligenceEngine, db: str) -> None:
        result = engine.assess_churn_risk("zero_risk_client")
        assert result["data"]["churn_risk_score"] >= 0.0

    def test_payment_failures_count_capped_at_3(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        """More than 3 failures should not increase payment_factor beyond 0.25."""
        client_id = "many_fails"
        for i in range(10):
            _insert_payment(
                db, client_id=client_id, amount_cents=0, status="failed", payment_id=f"pf_mf{i}"
            )
        result = engine.assess_churn_risk(client_id)
        breakdown = result["data"]["risk_factors"]["factor_breakdown"]
        assert breakdown["payment_failures"] <= 0.25

    def test_ten_plus_messages_zeroes_activity_factor(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        """10+ messages in 90 days → activity_factor = 0.0."""
        client_id = "chatty_client"
        _insert_conversation(
            db, thread_id="t_chatty", client_id=client_id, message_count=15, sent_days_ago=5
        )
        result = engine.assess_churn_risk(client_id)
        breakdown = result["data"]["risk_factors"]["factor_breakdown"]
        assert breakdown["conversation_activity"] == 0.0

    def test_churn_score_persisted(self, engine: ClientIntelligenceEngine, db: str) -> None:
        client_id = "persist_churn"
        engine.assess_churn_risk(client_id)
        conn = _connect(db)
        row = conn.execute(
            "SELECT churn_risk_score FROM client_intelligence WHERE client_id = ?",
            (client_id,),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["churn_risk_score"] is not None

    def test_declining_booking_frequency_increases_trend_factor(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        """Gaps between recent bookings larger than older bookings → trend risk > 0."""
        client_id = "declining_freq"
        # Older appointments: tight gaps (7 days apart)
        for i in range(3):
            _insert_appointment(
                db,
                appt_id=f"old_{i}",
                client_id=client_id,
                business_id="biz1",
                start_time=_days_ago(180 - i * 7),
            )
        # Recent appointments: wide gaps (60 days apart)
        for i in range(3):
            _insert_appointment(
                db,
                appt_id=f"recent_{i}",
                client_id=client_id,
                business_id="biz1",
                start_time=_days_ago(60 - i * 60 // 3),
            )
        result = engine.assess_churn_risk(client_id)
        breakdown = result["data"]["risk_factors"]["factor_breakdown"]
        assert breakdown["booking_trend"] > 0.0


# ===========================================================================
# 3. segment_clients
# ===========================================================================


class TestSegmentClients:
    BIZ = "biz_segment_test"

    def _add_client_with_appt(
        self,
        db: str,
        client_id: str,
        start_time: datetime,
        business_id: str | None = None,
    ) -> None:
        _insert_appointment(
            db,
            appt_id=f"appt_{client_id}",
            client_id=client_id,
            business_id=business_id or self.BIZ,
            start_time=start_time,
        )

    def test_empty_business_returns_zero_counts(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        result = engine.segment_clients("empty_biz")
        assert result["ok"] is True
        data = result["data"]
        assert data["clients_processed"] == 0
        all_zero = all(v == 0 for v in data["segment_counts"].values())
        assert all_zero

    def test_new_client_segment(self, engine: ClientIntelligenceEngine, db: str) -> None:
        """Client whose first appointment was < 30 days ago → New."""
        self._add_client_with_appt(db, "new_c1", _days_ago(5))
        result = engine.segment_clients(self.BIZ)
        assert result["ok"] is True
        assert result["data"]["segment_counts"]["New"] >= 1

    def test_dormant_client_segment(self, engine: ClientIntelligenceEngine, db: str) -> None:
        """Client last seen > 90 days ago → Dormant."""
        client_id = "dormant_seg"
        self._add_client_with_appt(db, client_id, _days_ago(120))
        result = engine.segment_clients(self.BIZ)
        assert result["ok"] is True
        assert result["data"]["segment_counts"]["Dormant"] >= 1

    def test_vip_client_segment(self, engine: ClientIntelligenceEngine, db: str) -> None:
        """Top 10% CLV + recent appointment → VIP."""
        # Seed 10 clients so we have a clear top-10% threshold
        for i in range(9):
            cid = f"regular_vip_{i}"
            self._add_client_with_appt(db, cid, _days_ago(40 + i))
            _insert_ci(db, ci_id=f"ci_rv{i}", client_id=cid, clv_cents=1000 * (i + 1))

        # VIP client: appointment older than 30 days (not "New") but within 90 days
        # (not "Dormant"), and clearly highest CLV (top 10%)
        vip_client = "vip_high_value"
        self._add_client_with_appt(db, vip_client, _days_ago(45))
        _insert_ci(
            db,
            ci_id="ci_vip",
            client_id=vip_client,
            clv_cents=99999,  # clearly highest
        )
        result = engine.segment_clients(self.BIZ)
        assert result["ok"] is True
        assert result["data"]["segment_counts"]["VIP"] >= 1

    def test_at_risk_client_segment(self, engine: ClientIntelligenceEngine, db: str) -> None:
        """Client with churn_risk_score >= 0.6 and not new → At-Risk."""
        client_id = "at_risk_c"
        self._add_client_with_appt(db, client_id, _days_ago(45))
        _insert_ci(db, ci_id="ci_ar", client_id=client_id, churn_risk_score=0.75, clv_cents=0)
        # Add a helper client with high CLV so vip_threshold > 0, preventing
        # the at_risk client (clv=0) from being incorrectly segmented as VIP.
        self._add_client_with_appt(db, "at_risk_helper", _days_ago(50))
        _insert_ci(db, ci_id="ci_ar_helper", client_id="at_risk_helper", clv_cents=99999)
        result = engine.segment_clients(self.BIZ)
        assert result["ok"] is True
        assert result["data"]["segment_counts"]["At-Risk"] >= 1

    def test_regular_client_segment(self, engine: ClientIntelligenceEngine, db: str) -> None:
        """Client not matching any special condition → Regular."""
        client_id = "regular_plain"
        self._add_client_with_appt(db, client_id, _days_ago(45))
        _insert_ci(db, ci_id="ci_reg", client_id=client_id, churn_risk_score=0.10, clv_cents=100)
        # Add a helper client with high CLV so vip_threshold > regular_plain's
        # CLV of 100, preventing it from being incorrectly segmented as VIP.
        self._add_client_with_appt(db, "reg_helper", _days_ago(50))
        _insert_ci(db, ci_id="ci_reg_helper", client_id="reg_helper", clv_cents=99999)
        result = engine.segment_clients(self.BIZ)
        assert result["ok"] is True
        assert result["data"]["segment_counts"]["Regular"] >= 1

    def test_new_takes_priority_over_dormant(self, engine: ClientIntelligenceEngine, db: str) -> None:
        """A client whose FIRST appointment is recent is New even if last appt seems old."""
        client_id = "new_priority"
        # Single appointment 10 days ago — first AND last
        self._add_client_with_appt(db, client_id, _days_ago(10))
        result = engine.segment_clients(self.BIZ)
        assert result["ok"] is True
        assert result["data"]["segment_counts"]["New"] >= 1

    def test_segment_stored_in_client_intelligence(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        client_id = "seg_persist"
        self._add_client_with_appt(db, client_id, _days_ago(50))
        engine.segment_clients(self.BIZ)
        conn = _connect(db)
        row = conn.execute(
            "SELECT segment FROM client_intelligence WHERE client_id = ?", (client_id,)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["segment"] is not None

    def test_clients_processed_count(self, engine: ClientIntelligenceEngine, db: str) -> None:
        biz = "count_biz"
        for i in range(4):
            _insert_appointment(
                db,
                appt_id=f"count_a{i}",
                client_id=f"count_c{i}",
                business_id=biz,
                start_time=_days_ago(50),
            )
        result = engine.segment_clients(biz)
        assert result["data"]["clients_processed"] == 4

    def test_vip_threshold_in_result(self, engine: ClientIntelligenceEngine, db: str) -> None:
        biz = "vip_thresh_biz"
        for i in range(5):
            cid = f"thresh_c{i}"
            _insert_appointment(
                db, appt_id=f"t_a{i}", client_id=cid, business_id=biz, start_time=_days_ago(40)
            )
            _insert_ci(db, ci_id=f"ci_t{i}", client_id=cid, clv_cents=1000 * (i + 1))
        result = engine.segment_clients(biz)
        assert "vip_clv_threshold_cents" in result["data"]

    def test_dormant_takes_priority_over_at_risk(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        """Dormant check runs before At-Risk in priority order."""
        biz = "priority_biz"
        client_id = "dormant_over_atrisk"
        _insert_appointment(
            db,
            appt_id="doa_appt",
            client_id=client_id,
            business_id=biz,
            start_time=_days_ago(150),
        )
        _insert_ci(
            db, ci_id="ci_doa", client_id=client_id, churn_risk_score=0.9
        )
        result = engine.segment_clients(biz)
        # Last appointment was 150 days ago, so dormant takes priority
        counts = result["data"]["segment_counts"]
        assert counts["Dormant"] >= 1
        assert counts["At-Risk"] == 0


# ===========================================================================
# 4. predictive_rebook
# ===========================================================================


class TestPredictiveRebook:
    def test_no_appointments_returns_no_suggestion(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        result = engine.predictive_rebook("no_appts_client")
        assert result["ok"] is True
        data = result["data"]
        assert data["suggestion"] is None
        assert data["confidence"] == 0.0
        assert data["reason"] == "no_appointments"

    def test_single_appointment_confidence_030(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        _insert_appointment(
            db,
            appt_id="single_a1",
            client_id="single_c",
            business_id="biz1",
            start_time=_days_ago(30),
        )
        result = engine.predictive_rebook("single_c")
        assert result["ok"] is True
        assert result["data"]["confidence"] == 0.30

    def test_two_appointments_confidence_050(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        for i, days in enumerate([30, 60]):
            _insert_appointment(
                db,
                appt_id=f"two_a{i}",
                client_id="two_c",
                business_id="biz1",
                start_time=_days_ago(days),
            )
        result = engine.predictive_rebook("two_c")
        assert result["ok"] is True
        assert result["data"]["confidence"] == 0.50

    def test_three_four_appointments_confidence_070(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        for i in range(4):
            _insert_appointment(
                db,
                appt_id=f"four_a{i}",
                client_id="four_c",
                business_id="biz1",
                start_time=_days_ago(30 * (i + 1)),
            )
        result = engine.predictive_rebook("four_c")
        assert result["ok"] is True
        assert result["data"]["confidence"] == 0.70

    def test_five_plus_appointments_confidence_090(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        for i in range(6):
            _insert_appointment(
                db,
                appt_id=f"six_a{i}",
                client_id="six_c",
                business_id="biz1",
                start_time=_days_ago(30 * (i + 1)),
            )
        result = engine.predictive_rebook("six_c")
        assert result["ok"] is True
        assert result["data"]["confidence"] == 0.90

    def test_suggested_date_in_future_of_last_appt(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        last_appt = _days_ago(20)
        _insert_appointment(
            db,
            appt_id="future_a1",
            client_id="future_c",
            business_id="biz1",
            start_time=last_appt,
        )
        result = engine.predictive_rebook("future_c")
        assert result["ok"] is True
        suggested_str = result["data"]["suggested_date"]
        # With avg_gap=30 and last_appt 20 days ago → suggested = last_appt + 30 days
        suggested_dt = datetime.fromisoformat(suggested_str)
        if suggested_dt.tzinfo is None:
            suggested_dt = suggested_dt.replace(tzinfo=UTC)
        assert suggested_dt > last_appt

    def test_most_frequent_service_selected(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        for i in range(3):
            _insert_appointment(
                db,
                appt_id=f"svc_a{i}",
                client_id="svc_c",
                business_id="biz1",
                start_time=_days_ago(30 * (i + 1)),
                service_name="Haircut",
            )
        _insert_appointment(
            db,
            appt_id="svc_a3",
            client_id="svc_c",
            business_id="biz1",
            start_time=_days_ago(120),
            service_name="Color",
        )
        result = engine.predictive_rebook("svc_c")
        assert result["ok"] is True
        assert result["data"]["suggested_service"] == "Haircut"

    def test_rebook_inserted_in_predictive_rebooks_table(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        _insert_appointment(
            db,
            appt_id="prebook_a1",
            client_id="prebook_c",
            business_id="biz1",
            start_time=_days_ago(30),
        )
        result = engine.predictive_rebook("prebook_c")
        assert result["ok"] is True
        rebook_id = result["data"]["rebook_id"]
        conn = _connect(db)
        row = conn.execute(
            "SELECT id, status FROM predictive_rebooks WHERE id = ?", (rebook_id,)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["status"] == "pending"

    def test_average_interval_computed_correctly(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        """Two appointments exactly 30 days apart → avg_interval = 30."""
        # Use a fixed base so both datetimes differ by exactly 30 days,
        # ensuring (dates[0] - dates[1]).days == 30 regardless of execution time.
        base = datetime.now(UTC).replace(microsecond=0)
        appt_recent = base - timedelta(days=30)
        appt_older = base - timedelta(days=60)
        _insert_appointment(
            db, appt_id="avg_a1", client_id="avg_c", business_id="biz1", start_time=appt_recent
        )
        _insert_appointment(
            db, appt_id="avg_a2", client_id="avg_c", business_id="biz1", start_time=appt_older
        )
        result = engine.predictive_rebook("avg_c")
        assert result["ok"] is True
        assert result["data"]["average_interval_days"] == 30.0

    def test_receipt_outcome_executed(self, engine: ClientIntelligenceEngine, db: str) -> None:
        _insert_appointment(
            db, appt_id="rcpt_a1", client_id="rcpt_c", business_id="biz1", start_time=_days_ago(10)
        )
        result = engine.predictive_rebook("rcpt_c")
        assert result["receipt"]["outcome"] == "executed"

    def test_no_appointments_receipt_outcome_skipped(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        result = engine.predictive_rebook("empty_rebook_c")
        assert result["receipt"]["outcome"] == "skipped"


# ===========================================================================
# 5. health_score
# ===========================================================================


class TestHealthScore:
    def test_returns_ok_envelope(self, engine: ClientIntelligenceEngine, db: str) -> None:
        result = engine.health_score("hs_any")
        assert result["ok"] is True
        assert "health_score" in result["data"]
        assert "components" in result["data"]

    def test_score_between_0_and_1(self, engine: ClientIntelligenceEngine, db: str) -> None:
        result = engine.health_score("hs_bounds")
        score = result["data"]["health_score"]
        assert 0.0 <= score <= 1.0

    def test_four_components_present(self, engine: ClientIntelligenceEngine, db: str) -> None:
        result = engine.health_score("hs_components")
        components = result["data"]["components"]
        assert "clv_percentile_contribution" in components
        assert "churn_inverse_contribution" in components
        assert "engagement_contribution" in components
        assert "payment_reliability_contribution" in components

    def test_clv_component_weight_30_pct(self, engine: ClientIntelligenceEngine, db: str) -> None:
        """Single client at 100th percentile → clv_component = 0.30."""
        client_id = "hs_clv_only"
        _insert_ci(db, ci_id="ci_hs_clv", client_id=client_id, clv_cents=50000)
        result = engine.health_score(client_id)
        clv_contrib = result["data"]["components"]["clv_percentile_contribution"]
        # Only one client in CI → percentile fallback: 1.0 * 0.30 = 0.30
        assert clv_contrib == pytest.approx(0.30, abs=0.01)

    def test_churn_inverse_component_weight_30_pct(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        """Zero churn_risk_score → churn_component = 0.30."""
        client_id = "hs_churn_low"
        _insert_ci(db, ci_id="ci_hs_ch", client_id=client_id, churn_risk_score=0.0)
        result = engine.health_score(client_id)
        churn_contrib = result["data"]["components"]["churn_inverse_contribution"]
        assert churn_contrib == pytest.approx(0.30, abs=0.001)

    def test_engagement_component_weight_20_pct(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        """20+ messages in 90 days → engagement_component = 0.20."""
        client_id = "hs_engage"
        _insert_conversation(
            db, thread_id="t_hs_eng", client_id=client_id, message_count=25, sent_days_ago=5
        )
        result = engine.health_score(client_id)
        engage_contrib = result["data"]["components"]["engagement_contribution"]
        assert engage_contrib == pytest.approx(0.20, abs=0.001)

    def test_payment_reliability_component_weight_20_pct_all_paid(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        """All payments paid → reliability = 1.0 → component = 0.20."""
        client_id = "hs_pay_all"
        for i in range(3):
            _insert_payment(
                db,
                client_id=client_id,
                amount_cents=5000,
                status="paid",
                payment_id=f"pay_hsp{i}",
            )
        result = engine.health_score(client_id)
        pay_contrib = result["data"]["components"]["payment_reliability_contribution"]
        assert pay_contrib == pytest.approx(0.20, abs=0.001)

    def test_payment_reliability_no_payments_defaults_50_pct(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        """No payment records → reliability ratio = 0.5 → component = 0.10."""
        client_id = "hs_no_pay"
        result = engine.health_score(client_id)
        pay_contrib = result["data"]["components"]["payment_reliability_contribution"]
        assert pay_contrib == pytest.approx(0.10, abs=0.001)

    def test_high_churn_reduces_score(self, engine: ClientIntelligenceEngine, db: str) -> None:
        """High churn risk reduces churn_inverse_contribution significantly."""
        client_id = "hs_high_churn"
        _insert_ci(db, ci_id="ci_hshc", client_id=client_id, churn_risk_score=0.8)
        result = engine.health_score(client_id)
        churn_contrib = result["data"]["components"]["churn_inverse_contribution"]
        # (1 - 0.8) * 0.30 = 0.06
        assert churn_contrib == pytest.approx(0.06, abs=0.01)

    def test_health_score_persisted(self, engine: ClientIntelligenceEngine, db: str) -> None:
        client_id = "hs_persist"
        engine.health_score(client_id)
        conn = _connect(db)
        row = conn.execute(
            "SELECT health_score FROM client_intelligence WHERE client_id = ?", (client_id,)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["health_score"] is not None

    def test_upsert_updates_existing_health_score(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        client_id = "hs_upsert"
        _insert_ci(db, ci_id="ci_hsu", client_id=client_id, health_score=0.01)
        engine.health_score(client_id)
        conn = _connect(db)
        # Should have exactly one row, not two
        rows = conn.execute(
            "SELECT health_score FROM client_intelligence WHERE client_id = ?", (client_id,)
        ).fetchall()
        conn.close()
        assert len(rows) == 1

    def test_old_messages_not_counted_in_engagement(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        """Messages older than 90 days do not boost engagement component."""
        client_id = "hs_old_msgs"
        _insert_conversation(
            db, thread_id="t_old_msg", client_id=client_id, message_count=20, sent_days_ago=100
        )
        result = engine.health_score(client_id)
        engage_contrib = result["data"]["components"]["engagement_contribution"]
        assert engage_contrib == 0.0

    def test_score_components_sum_correctly(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        client_id = "hs_sum"
        result = engine.health_score(client_id)
        components = result["data"]["components"]
        total = sum(components.values())
        assert result["data"]["health_score"] == pytest.approx(total, abs=0.001)


# ===========================================================================
# 6. get_intelligence
# ===========================================================================


class TestGetIntelligence:
    def test_returns_ok_envelope(self, engine: ClientIntelligenceEngine, db: str) -> None:
        result = engine.get_intelligence("gi_any")
        assert result["ok"] is True
        assert "intelligence" in result["data"]

    def test_fresh_data_not_recomputed(self, engine: ClientIntelligenceEngine, db: str) -> None:
        """Row computed < 24h ago must NOT trigger recompute (recomputed=False)."""
        client_id = "gi_fresh"
        # Insert a fresh CI record (computed 1 hour ago)
        recent_ts = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        _insert_ci(
            db,
            ci_id="ci_gi_fresh",
            client_id=client_id,
            clv_cents=1234,
            last_computed_at=recent_ts,
        )
        result = engine.get_intelligence(client_id)
        assert result["ok"] is True
        assert result["data"]["recomputed"] is False

    def test_stale_data_triggers_recompute(self, engine: ClientIntelligenceEngine, db: str) -> None:
        """Row older than 24h must trigger recompute (recomputed=True)."""
        client_id = "gi_stale"
        stale_ts = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
        _insert_ci(
            db,
            ci_id="ci_gi_stale",
            client_id=client_id,
            clv_cents=999,
            last_computed_at=stale_ts,
        )
        result = engine.get_intelligence(client_id)
        assert result["ok"] is True
        assert result["data"]["recomputed"] is True

    def test_missing_row_triggers_recompute(self, engine: ClientIntelligenceEngine, db: str) -> None:
        """No existing CI row must trigger recompute (recomputed=True)."""
        result = engine.get_intelligence("gi_no_row")
        assert result["ok"] is True
        assert result["data"]["recomputed"] is True

    def test_recomputed_data_includes_updated_fields(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        """After recompute, the returned intelligence row should be non-None."""
        client_id = "gi_updated"
        result = engine.get_intelligence(client_id)
        assert result["ok"] is True
        # After recompute the row should exist (even if all zeros)
        assert result["data"]["intelligence"] is not None

    def test_exact_24h_boundary_treated_as_stale(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        """Row computed exactly 24h ago (plus 1 second) should be stale."""
        client_id = "gi_boundary"
        boundary_ts = (datetime.now(UTC) - timedelta(hours=24, seconds=1)).isoformat()
        _insert_ci(
            db,
            ci_id="ci_gi_boundary",
            client_id=client_id,
            last_computed_at=boundary_ts,
        )
        result = engine.get_intelligence(client_id)
        assert result["data"]["recomputed"] is True

    def test_fresh_row_returned_without_modification(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        """Fresh row CLV must be returned as-is (not overwritten by recompute)."""
        client_id = "gi_untouched"
        recent_ts = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
        _insert_ci(
            db,
            ci_id="ci_gi_unt",
            client_id=client_id,
            clv_cents=77777,
            last_computed_at=recent_ts,
        )
        result = engine.get_intelligence(client_id)
        assert result["ok"] is True
        # No recompute → CLV preserved
        intel = result["data"]["intelligence"]
        assert intel["clv_cents"] == 77777

    def test_receipt_action_type_get_intelligence(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        result = engine.get_intelligence("gi_receipt")
        assert result["receipt"]["action_type"] == "get_intelligence"


# ===========================================================================
# 7. dashboard
# ===========================================================================


class TestDashboard:
    BIZ = "biz_dashboard_test"

    def _seed_full_client(
        self,
        db: str,
        client_id: str,
        *,
        clv_cents: int = 5000,
        churn_risk_score: float = 0.2,
        segment: str = "Regular",
        health_score: float = 0.5,
        days_since_appt: int = 40,
    ) -> None:
        _insert_appointment(
            db,
            appt_id=f"dash_a_{client_id}",
            client_id=client_id,
            business_id=self.BIZ,
            start_time=_days_ago(days_since_appt),
        )
        _insert_ci(
            db,
            ci_id=f"ci_dash_{client_id}",
            client_id=client_id,
            clv_cents=clv_cents,
            churn_risk_score=churn_risk_score,
            segment=segment,
            health_score=health_score,
        )

    def test_empty_business_returns_zeros(self, engine: ClientIntelligenceEngine, db: str) -> None:
        result = engine.dashboard("empty_dash_biz")
        assert result["ok"] is True
        data = result["data"]
        assert data["total_clients"] == 0
        assert data["average_clv_cents"] == 0
        assert data["average_health_score"] == 0.0
        assert data["segment_distribution"] == {}
        assert data["top_5_at_risk"] == []
        assert data["top_5_vip"] == []

    def test_total_clients_count(self, engine: ClientIntelligenceEngine, db: str) -> None:
        for i in range(5):
            self._seed_full_client(db, f"dc_{i}")
        result = engine.dashboard(self.BIZ)
        assert result["data"]["total_clients"] == 5

    def test_average_clv_computed_correctly(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        biz = "avg_clv_biz"
        clvs = [10000, 20000, 30000]
        for i, clv in enumerate(clvs):
            cid = f"avgclv_c{i}"
            _insert_appointment(
                db,
                appt_id=f"avgclv_a{i}",
                client_id=cid,
                business_id=biz,
                start_time=_days_ago(40),
            )
            _insert_ci(db, ci_id=f"ci_avgclv{i}", client_id=cid, clv_cents=clv)
        result = engine.dashboard(biz)
        assert result["ok"] is True
        expected_avg = (10000 + 20000 + 30000) // 3
        assert result["data"]["average_clv_cents"] == expected_avg

    def test_average_health_score_computed_correctly(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        biz = "avg_health_biz"
        scores = [0.4, 0.6, 0.8]
        for i, hs in enumerate(scores):
            cid = f"avghs_c{i}"
            _insert_appointment(
                db,
                appt_id=f"avghs_a{i}",
                client_id=cid,
                business_id=biz,
                start_time=_days_ago(40),
            )
            _insert_ci(db, ci_id=f"ci_avghs{i}", client_id=cid, health_score=hs)
        result = engine.dashboard(biz)
        expected = round(sum(scores) / len(scores), 4)
        assert result["data"]["average_health_score"] == pytest.approx(expected, abs=0.001)

    def test_segment_distribution_counts(self, engine: ClientIntelligenceEngine, db: str) -> None:
        biz = "seg_dist_biz"
        segments = ["Regular", "Regular", "VIP", "At-Risk", "Dormant"]
        for i, seg in enumerate(segments):
            cid = f"segdist_c{i}"
            _insert_appointment(
                db,
                appt_id=f"segdist_a{i}",
                client_id=cid,
                business_id=biz,
                start_time=_days_ago(40),
            )
            _insert_ci(db, ci_id=f"ci_segdist{i}", client_id=cid, segment=seg)
        result = engine.dashboard(biz)
        dist = result["data"]["segment_distribution"]
        assert dist.get("Regular", 0) == 2
        assert dist.get("VIP", 0) == 1
        assert dist.get("At-Risk", 0) == 1
        assert dist.get("Dormant", 0) == 1

    def test_top_5_at_risk_ordered_by_churn(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        biz = "top5ar_biz"
        churn_scores = [0.9, 0.3, 0.7, 0.5, 0.8, 0.1]
        for i, cs in enumerate(churn_scores):
            cid = f"top5ar_c{i}"
            _insert_appointment(
                db, appt_id=f"top5ar_a{i}", client_id=cid, business_id=biz, start_time=_days_ago(40)
            )
            _insert_ci(db, ci_id=f"ci_top5ar{i}", client_id=cid, churn_risk_score=cs)
        result = engine.dashboard(biz)
        top_risk = result["data"]["top_5_at_risk"]
        assert len(top_risk) <= 5
        # First entry should be highest churn
        assert top_risk[0]["churn_risk_score"] == pytest.approx(0.9, abs=0.01)

    def test_top_5_vip_ordered_by_clv(self, engine: ClientIntelligenceEngine, db: str) -> None:
        biz = "top5vip_biz"
        clvs = [5000, 9000, 3000, 7000, 11000, 1000]
        for i, clv in enumerate(clvs):
            cid = f"top5vip_c{i}"
            _insert_appointment(
                db, appt_id=f"top5vip_a{i}", client_id=cid, business_id=biz, start_time=_days_ago(40)
            )
            _insert_ci(db, ci_id=f"ci_top5vip{i}", client_id=cid, clv_cents=clv, segment="VIP")
        result = engine.dashboard(biz)
        top_vip = result["data"]["top_5_vip"]
        assert len(top_vip) <= 5
        assert top_vip[0]["clv_cents"] == 11000

    def test_top_5_vip_only_includes_vip_segment(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        biz = "vip_only_biz"
        for i in range(3):
            cid = f"vip_only_c{i}"
            _insert_appointment(
                db, appt_id=f"vip_only_a{i}", client_id=cid, business_id=biz, start_time=_days_ago(40)
            )
            _insert_ci(db, ci_id=f"ci_vip_only{i}", client_id=cid, segment="Regular", clv_cents=99999)
        result = engine.dashboard(biz)
        # No VIP segment → top_5_vip should be empty
        assert result["data"]["top_5_vip"] == []

    def test_at_risk_summary_fields(self, engine: ClientIntelligenceEngine, db: str) -> None:
        biz = "ar_fields_biz"
        cid = "ar_fields_c"
        _insert_appointment(
            db, appt_id="ar_fields_a", client_id=cid, business_id=biz, start_time=_days_ago(40)
        )
        _insert_ci(db, ci_id="ci_ar_fields", client_id=cid, churn_risk_score=0.7, segment="At-Risk")
        result = engine.dashboard(biz)
        entry = result["data"]["top_5_at_risk"][0]
        assert "client_id" in entry
        assert "churn_risk_score" in entry
        assert "segment" in entry

    def test_vip_summary_fields(self, engine: ClientIntelligenceEngine, db: str) -> None:
        biz = "vip_fields_biz"
        cid = "vip_fields_c"
        _insert_appointment(
            db, appt_id="vip_fields_a", client_id=cid, business_id=biz, start_time=_days_ago(40)
        )
        _insert_ci(
            db,
            ci_id="ci_vip_fields",
            client_id=cid,
            clv_cents=50000,
            segment="VIP",
            health_score=0.85,
        )
        result = engine.dashboard(biz)
        entry = result["data"]["top_5_vip"][0]
        assert "client_id" in entry
        assert "clv_cents" in entry
        assert "health_score" in entry

    def test_clients_without_ci_not_included_in_aggregates(
        self, engine: ClientIntelligenceEngine, db: str
    ) -> None:
        """Clients who appear in appointments but have no CI row are counted in
        total_clients but do not distort CLV / health averages."""
        biz = "no_ci_biz"
        # One client with CI
        _insert_appointment(
            db, appt_id="noci_a1", client_id="noci_c1", business_id=biz, start_time=_days_ago(40)
        )
        _insert_ci(db, ci_id="ci_noci1", client_id="noci_c1", clv_cents=10000, health_score=0.8)
        # One client without CI row (no insert_ci call)
        _insert_appointment(
            db, appt_id="noci_a2", client_id="noci_c2", business_id=biz, start_time=_days_ago(40)
        )
        result = engine.dashboard(biz)
        assert result["data"]["total_clients"] == 2
        # Only noci_c1 contributes to averages (noci_c2 not in CI table)
        assert result["data"]["average_clv_cents"] == 10000

    def test_receipt_action_type_dashboard(self, engine: ClientIntelligenceEngine, db: str) -> None:
        result = engine.dashboard("dash_receipt_biz")
        assert result["receipt"]["action_type"] == "dashboard"
        assert result["receipt"]["outcome"] == "executed"
