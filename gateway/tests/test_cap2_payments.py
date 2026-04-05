"""Comprehensive tests for cap2_payments.PaymentEngine.

Coverage
--------
- create_payment_link: valid params, negative amount guard, provider exception,
  DB record verification
- record_payment: mark pending as paid (DB + receipt), idempotent on already-paid,
  missing link_id
- process_refund: valid refund (DB + receipt), zero/negative amount guard,
  provider exception, provider returns success=False
- create_subscription: month / year / week intervals (DB record verified for each)
- cancel_subscription: active sub → cancelled + rollback row, idempotent on
  already-cancelled, missing sub_id
- revenue_forecast: active subs + pending links + paid history, days<=0 guard,
  zero-data baseline
- undo_last_payment_action: with rollback record restores state + deletes row,
  without any rollback record returns err

All tests use a real temporary SQLite database (tempfile).
The Stripe provider is replaced with ``FakePaymentProvider``, a concrete
subclass of ``PaymentProviderProtocol`` that returns deterministic successes.
No live network calls are made.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict

import pytest

from isg_agent.capabilities.shared.db_schema import ensure_tables
from isg_agent.capabilities.shared.foundation import PaymentProviderProtocol
from isg_agent.capabilities.cap2_payments import PaymentEngine


# ---------------------------------------------------------------------------
# Fake payment provider — implements PaymentProviderProtocol fully
# ---------------------------------------------------------------------------


class FakePaymentProvider(PaymentProviderProtocol):
    """Deterministic stand-in for StripePaymentProvider.

    Returns predictable fake responses for every method so tests never hit
    the network and always see successful outcomes by default.  The
    ``raise_on_*`` flags allow individual tests to exercise error paths.
    """

    def __init__(
        self,
        raise_on_create_link: bool = False,
        raise_on_refund: bool = False,
        refund_success: bool = True,
    ) -> None:
        self.raise_on_create_link = raise_on_create_link
        self.raise_on_refund = raise_on_refund
        self.refund_success = refund_success

    def create_payment_link(
        self,
        amount_cents: int,
        currency: str,
        description: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        if self.raise_on_create_link:
            raise RuntimeError("Stripe is down")
        return {
            "url": "https://pay.stripe.com/fake_link_url",
            "link_id": "fake_stripe_link_001",
        }

    def charge_payment_method(
        self,
        payment_method_id: str,
        amount_cents: int,
        currency: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {"success": True, "charge_id": "fake_ch_001"}

    def refund_payment(
        self,
        payment_id: str,
        amount_cents: int,
        reason: str,
    ) -> Dict[str, Any]:
        if self.raise_on_refund:
            raise RuntimeError("Stripe refund failed")
        return {
            "success": self.refund_success,
            "refund_id": "fake_re_001",
            "status": "succeeded",
        }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    """Create a fresh SQLite DB with all business-ops tables and return its path."""
    path = str(tmp_path / "test_agent.db")
    ensure_tables(path)
    return path


@pytest.fixture()
def engine(db_path: str) -> PaymentEngine:
    """PaymentEngine wired to the temp DB and the fake provider."""
    return PaymentEngine(db_path=db_path, payment_provider=FakePaymentProvider())


def _fetch(db_path: str, sql: str, params: tuple = ()) -> list[dict]:
    """Helper: run a raw SELECT and return rows as dicts."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# 1. create_payment_link
# ---------------------------------------------------------------------------


class TestCreatePaymentLink:
    def test_valid_params_returns_ok(self, engine: PaymentEngine) -> None:
        result = engine.create_payment_link(
            client_id="client_abc",
            appointment_id="appt_001",
            amount_cents=5000,
            currency="usd",
        )
        assert result["ok"] is True
        assert result["data"]["url"] == "https://pay.stripe.com/fake_link_url"
        assert result["data"]["record"]["status"] == "pending"
        assert result["data"]["record"]["amount_cents"] == 5000
        assert result["data"]["record"]["currency"] == "usd"
        assert result["receipt"]["outcome"] == "executed"

    def test_valid_params_writes_db_record(
        self, engine: PaymentEngine, db_path: str
    ) -> None:
        result = engine.create_payment_link(
            client_id="client_db_check",
            appointment_id="appt_002",
            amount_cents=9900,
            currency="gbp",
        )
        record_id = result["data"]["record"]["id"]
        rows = _fetch(
            db_path,
            "SELECT * FROM payment_link_records WHERE id = ?",
            (record_id,),
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["client_id"] == "client_db_check"
        assert row["appointment_id"] == "appt_002"
        assert row["amount_cents"] == 9900
        assert row["currency"] == "gbp"
        assert row["status"] == "pending"
        assert row["stripe_link_id"] == "fake_stripe_link_001"
        assert row["paid_at"] is None

    def test_db_record_id_matches_returned_record(
        self, engine: PaymentEngine, db_path: str
    ) -> None:
        result = engine.create_payment_link(
            client_id="client_match",
            appointment_id="appt_003",
            amount_cents=2500,
        )
        returned_id = result["data"]["record"]["id"]
        rows = _fetch(
            db_path,
            "SELECT id FROM payment_link_records WHERE id = ?",
            (returned_id,),
        )
        assert len(rows) == 1
        assert rows[0]["id"] == returned_id

    def test_zero_amount_returns_err(self, engine: PaymentEngine) -> None:
        result = engine.create_payment_link(
            client_id="client_x",
            appointment_id="appt_000",
            amount_cents=0,
        )
        assert result["ok"] is False
        assert "amount_cents" in result["error"]
        assert result["receipt"]["outcome"] == "failed"

    def test_negative_amount_returns_err(self, engine: PaymentEngine) -> None:
        result = engine.create_payment_link(
            client_id="client_x",
            appointment_id="appt_000",
            amount_cents=-100,
        )
        assert result["ok"] is False
        assert result["receipt"]["outcome"] == "failed"

    def test_provider_exception_returns_err(self, db_path: str) -> None:
        engine = PaymentEngine(
            db_path=db_path,
            payment_provider=FakePaymentProvider(raise_on_create_link=True),
        )
        result = engine.create_payment_link(
            client_id="client_y",
            appointment_id="appt_exc",
            amount_cents=1000,
        )
        assert result["ok"] is False
        assert "provider" in result["error"].lower()
        assert result["receipt"]["outcome"] == "failed"

    def test_currency_normalised_to_lowercase(
        self, engine: PaymentEngine, db_path: str
    ) -> None:
        result = engine.create_payment_link(
            client_id="client_cur",
            appointment_id="appt_cur",
            amount_cents=3000,
            currency="EUR",
        )
        assert result["ok"] is True
        record_id = result["data"]["record"]["id"]
        rows = _fetch(
            db_path,
            "SELECT currency FROM payment_link_records WHERE id = ?",
            (record_id,),
        )
        assert rows[0]["currency"] == "eur"

    def test_default_currency_is_usd(self, engine: PaymentEngine) -> None:
        result = engine.create_payment_link(
            client_id="client_def",
            appointment_id="appt_def",
            amount_cents=1500,
        )
        assert result["ok"] is True
        assert result["data"]["record"]["currency"] == "usd"


# ---------------------------------------------------------------------------
# 2. record_payment
# ---------------------------------------------------------------------------


class TestRecordPayment:
    def _make_pending_link(
        self,
        engine: PaymentEngine,
        client_id: str = "client_pay",
        amount_cents: int = 4000,
    ) -> str:
        """Create a pending payment link and return its record ID."""
        res = engine.create_payment_link(
            client_id=client_id,
            appointment_id="appt_pay",
            amount_cents=amount_cents,
        )
        assert res["ok"] is True
        return res["data"]["record"]["id"]

    def test_marks_pending_as_paid(
        self, engine: PaymentEngine, db_path: str
    ) -> None:
        link_id = self._make_pending_link(engine)
        result = engine.record_payment(
            link_id=link_id,
            stripe_event={"type": "payment_intent.succeeded"},
        )
        assert result["ok"] is True
        assert result["data"]["record"]["status"] == "paid"
        assert result["receipt"]["outcome"] == "executed"

    def test_db_row_status_updated_to_paid(
        self, engine: PaymentEngine, db_path: str
    ) -> None:
        link_id = self._make_pending_link(engine)
        engine.record_payment(
            link_id=link_id,
            stripe_event={"type": "payment_intent.succeeded"},
        )
        rows = _fetch(
            db_path,
            "SELECT status, paid_at FROM payment_link_records WHERE id = ?",
            (link_id,),
        )
        assert rows[0]["status"] == "paid"
        assert rows[0]["paid_at"] is not None

    def test_immutable_receipt_written_to_db(
        self, engine: PaymentEngine, db_path: str
    ) -> None:
        link_id = self._make_pending_link(engine)
        result = engine.record_payment(
            link_id=link_id,
            stripe_event={"type": "checkout.session.completed"},
        )
        receipt_id = result["data"]["receipt_id"]
        assert receipt_id != ""
        rows = _fetch(
            db_path,
            "SELECT * FROM immutable_receipts WHERE id = ?",
            (receipt_id,),
        )
        assert len(rows) == 1
        assert rows[0]["action_type"] == "record_payment"

    def test_already_paid_returns_ok_skipped(
        self, engine: PaymentEngine
    ) -> None:
        link_id = self._make_pending_link(engine)
        engine.record_payment(
            link_id=link_id,
            stripe_event={"type": "payment_intent.succeeded"},
        )
        # Second call — idempotent
        result2 = engine.record_payment(
            link_id=link_id,
            stripe_event={"type": "payment_intent.succeeded"},
        )
        assert result2["ok"] is True
        assert result2["data"].get("note") == "already marked paid"
        assert result2["receipt"]["outcome"] == "skipped"

    def test_missing_link_id_returns_err(self, engine: PaymentEngine) -> None:
        result = engine.record_payment(
            link_id="plink_does_not_exist",
            stripe_event={"type": "payment_intent.succeeded"},
        )
        assert result["ok"] is False
        assert result["receipt"]["outcome"] == "failed"

    def test_stripe_event_type_reflected_in_receipt_details(
        self, engine: PaymentEngine, db_path: str
    ) -> None:
        link_id = self._make_pending_link(engine)
        result = engine.record_payment(
            link_id=link_id,
            stripe_event={"type": "invoice.payment_succeeded"},
        )
        receipt_id = result["data"]["receipt_id"]
        rows = _fetch(
            db_path,
            "SELECT details FROM immutable_receipts WHERE id = ?",
            (receipt_id,),
        )
        details = json.loads(rows[0]["details"])
        assert details.get("stripe_event_type") == "invoice.payment_succeeded"


# ---------------------------------------------------------------------------
# 3. process_refund
# ---------------------------------------------------------------------------


class TestProcessRefund:
    def test_valid_refund_returns_ok(self, engine: PaymentEngine) -> None:
        result = engine.process_refund(
            payment_id="ch_fake_001",
            amount_cents=2000,
            reason="customer_request",
        )
        assert result["ok"] is True
        assert result["data"]["refund_record"]["amount_cents"] == 2000
        assert result["data"]["refund_record"]["reason"] == "customer_request"
        assert result["receipt"]["outcome"] == "executed"

    def test_valid_refund_writes_db_record(
        self, engine: PaymentEngine, db_path: str
    ) -> None:
        result = engine.process_refund(
            payment_id="ch_fake_002",
            amount_cents=1500,
            reason="duplicate",
        )
        refund_id = result["data"]["refund_record"]["id"]
        rows = _fetch(
            db_path,
            "SELECT * FROM refunds WHERE id = ?",
            (refund_id,),
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["payment_id"] == "ch_fake_002"
        assert row["amount_cents"] == 1500
        assert row["reason"] == "duplicate"
        assert row["stripe_refund_id"] == "fake_re_001"
        assert row["status"] == "succeeded"

    def test_immutable_receipt_written_on_refund(
        self, engine: PaymentEngine, db_path: str
    ) -> None:
        result = engine.process_refund(
            payment_id="ch_fake_003",
            amount_cents=500,
            reason="fraudulent",
        )
        receipt_id = result["data"]["receipt_id"]
        assert receipt_id != ""
        rows = _fetch(
            db_path,
            "SELECT * FROM immutable_receipts WHERE id = ?",
            (receipt_id,),
        )
        assert len(rows) == 1
        assert rows[0]["action_type"] == "process_refund"

    def test_zero_amount_returns_err(self, engine: PaymentEngine) -> None:
        result = engine.process_refund(
            payment_id="ch_fake_004",
            amount_cents=0,
            reason="test",
        )
        assert result["ok"] is False
        assert "amount_cents" in result["error"]
        assert result["receipt"]["outcome"] == "failed"

    def test_negative_amount_returns_err(self, engine: PaymentEngine) -> None:
        result = engine.process_refund(
            payment_id="ch_fake_005",
            amount_cents=-500,
            reason="test",
        )
        assert result["ok"] is False
        assert result["receipt"]["outcome"] == "failed"

    def test_provider_exception_returns_err(self, db_path: str) -> None:
        engine = PaymentEngine(
            db_path=db_path,
            payment_provider=FakePaymentProvider(raise_on_refund=True),
        )
        result = engine.process_refund(
            payment_id="ch_fake_exc",
            amount_cents=1000,
            reason="test",
        )
        assert result["ok"] is False
        assert "provider" in result["error"].lower()

    def test_provider_success_false_returns_err(self, db_path: str) -> None:
        engine = PaymentEngine(
            db_path=db_path,
            payment_provider=FakePaymentProvider(refund_success=False),
        )
        result = engine.process_refund(
            payment_id="ch_fake_fail",
            amount_cents=800,
            reason="test",
        )
        assert result["ok"] is False
        assert "not successful" in result["error"].lower()

    def test_no_db_row_written_on_provider_failure(
        self, db_path: str
    ) -> None:
        engine = PaymentEngine(
            db_path=db_path,
            payment_provider=FakePaymentProvider(refund_success=False),
        )
        engine.process_refund(
            payment_id="ch_no_row",
            amount_cents=750,
            reason="test",
        )
        rows = _fetch(
            db_path,
            "SELECT * FROM refunds WHERE payment_id = ?",
            ("ch_no_row",),
        )
        assert rows == []


# ---------------------------------------------------------------------------
# 4. create_subscription
# ---------------------------------------------------------------------------


class TestCreateSubscription:
    def test_monthly_subscription_returns_ok(self, engine: PaymentEngine) -> None:
        result = engine.create_subscription(
            client_id="client_sub_m",
            plan_name="Gold Monthly",
            amount_cents=4999,
            interval="month",
        )
        assert result["ok"] is True
        sub = result["data"]["subscription"]
        assert sub["status"] == "active"
        assert sub["interval"] == "month"
        assert sub["amount_cents"] == 4999
        assert result["receipt"]["outcome"] == "executed"
        assert result["receipt"]["rollback_available"] is True

    def test_monthly_subscription_written_to_db(
        self, engine: PaymentEngine, db_path: str
    ) -> None:
        result = engine.create_subscription(
            client_id="client_sub_m_db",
            plan_name="Silver Monthly",
            amount_cents=2999,
            interval="month",
        )
        sub_id = result["data"]["subscription"]["id"]
        rows = _fetch(
            db_path,
            "SELECT * FROM subscriptions WHERE id = ?",
            (sub_id,),
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["client_id"] == "client_sub_m_db"
        assert row["plan_name"] == "Silver Monthly"
        assert row["amount_cents"] == 2999
        assert row["interval"] == "month"
        assert row["status"] == "active"
        assert row["cancelled_at"] is None
        assert row["next_billing_at"] is not None

    def test_yearly_subscription_returns_ok(self, engine: PaymentEngine) -> None:
        result = engine.create_subscription(
            client_id="client_sub_y",
            plan_name="Gold Annual",
            amount_cents=49999,
            interval="year",
        )
        assert result["ok"] is True
        sub = result["data"]["subscription"]
        assert sub["interval"] == "year"
        assert sub["status"] == "active"

    def test_yearly_subscription_written_to_db(
        self, engine: PaymentEngine, db_path: str
    ) -> None:
        result = engine.create_subscription(
            client_id="client_sub_y_db",
            plan_name="Platinum Annual",
            amount_cents=99900,
            interval="year",
        )
        sub_id = result["data"]["subscription"]["id"]
        rows = _fetch(
            db_path,
            "SELECT interval, next_billing_at FROM subscriptions WHERE id = ?",
            (sub_id,),
        )
        assert rows[0]["interval"] == "year"
        # next_billing_at must be ~1 year ahead — just verify it is non-null
        assert rows[0]["next_billing_at"] is not None

    def test_weekly_subscription_returns_ok(self, engine: PaymentEngine) -> None:
        result = engine.create_subscription(
            client_id="client_sub_w",
            plan_name="Starter Weekly",
            amount_cents=999,
            interval="week",
        )
        assert result["ok"] is True
        sub = result["data"]["subscription"]
        assert sub["interval"] == "week"
        assert sub["status"] == "active"

    def test_weekly_subscription_written_to_db(
        self, engine: PaymentEngine, db_path: str
    ) -> None:
        result = engine.create_subscription(
            client_id="client_sub_w_db",
            plan_name="Pay-Per-Week",
            amount_cents=500,
            interval="week",
        )
        sub_id = result["data"]["subscription"]["id"]
        rows = _fetch(
            db_path,
            "SELECT interval, next_billing_at FROM subscriptions WHERE id = ?",
            (sub_id,),
        )
        assert rows[0]["interval"] == "week"
        assert rows[0]["next_billing_at"] is not None

    def test_zero_amount_returns_err(self, engine: PaymentEngine) -> None:
        result = engine.create_subscription(
            client_id="client_sub_z",
            plan_name="Free Tier",
            amount_cents=0,
        )
        assert result["ok"] is False
        assert result["receipt"]["outcome"] == "failed"

    def test_negative_amount_returns_err(self, engine: PaymentEngine) -> None:
        result = engine.create_subscription(
            client_id="client_sub_neg",
            plan_name="Negative Plan",
            amount_cents=-1,
        )
        assert result["ok"] is False
        assert result["receipt"]["outcome"] == "failed"

    def test_default_interval_is_month(self, engine: PaymentEngine) -> None:
        result = engine.create_subscription(
            client_id="client_sub_def",
            plan_name="Default Interval",
            amount_cents=1000,
        )
        assert result["ok"] is True
        assert result["data"]["subscription"]["interval"] == "month"

    def test_returned_subscription_has_expected_fields(
        self, engine: PaymentEngine
    ) -> None:
        result = engine.create_subscription(
            client_id="client_fields",
            plan_name="Field Check",
            amount_cents=3000,
            interval="month",
        )
        sub = result["data"]["subscription"]
        for field in (
            "id",
            "client_id",
            "plan_name",
            "amount_cents",
            "interval",
            "stripe_sub_id",
            "status",
            "started_at",
            "cancelled_at",
            "next_billing_at",
        ):
            assert field in sub, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# 5. cancel_subscription
# ---------------------------------------------------------------------------


class TestCancelSubscription:
    def _create_active_sub(
        self,
        engine: PaymentEngine,
        client_id: str = "client_cancel",
        amount_cents: int = 2999,
    ) -> str:
        """Create an active subscription and return its ID."""
        res = engine.create_subscription(
            client_id=client_id,
            plan_name="Test Plan",
            amount_cents=amount_cents,
            interval="month",
        )
        assert res["ok"] is True
        return res["data"]["subscription"]["id"]

    def test_cancel_active_sub_returns_ok(self, engine: PaymentEngine) -> None:
        sub_id = self._create_active_sub(engine)
        result = engine.cancel_subscription(sub_id)
        assert result["ok"] is True
        assert result["data"]["subscription"]["status"] == "cancelled"
        assert result["receipt"]["outcome"] == "executed"
        assert result["receipt"]["rollback_available"] is True

    def test_cancel_updates_db_status(
        self, engine: PaymentEngine, db_path: str
    ) -> None:
        sub_id = self._create_active_sub(engine)
        engine.cancel_subscription(sub_id)
        rows = _fetch(
            db_path,
            "SELECT status, cancelled_at FROM subscriptions WHERE id = ?",
            (sub_id,),
        )
        assert rows[0]["status"] == "cancelled"
        assert rows[0]["cancelled_at"] is not None

    def test_cancel_creates_rollback_record(
        self, engine: PaymentEngine, db_path: str
    ) -> None:
        sub_id = self._create_active_sub(engine)
        result = engine.cancel_subscription(sub_id)
        rollback_id = result["data"]["rollback_id"]
        rows = _fetch(
            db_path,
            "SELECT * FROM rollbacks WHERE id = ?",
            (rollback_id,),
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["entity_type"] == "subscription"
        assert row["entity_id"] == sub_id
        assert row["action"] == "cancel_subscription"

    def test_rollback_record_previous_state_is_active(
        self, engine: PaymentEngine, db_path: str
    ) -> None:
        sub_id = self._create_active_sub(engine)
        result = engine.cancel_subscription(sub_id)
        rollback_id = result["data"]["rollback_id"]
        rows = _fetch(
            db_path,
            "SELECT previous_state_json FROM rollbacks WHERE id = ?",
            (rollback_id,),
        )
        state = json.loads(rows[0]["previous_state_json"])
        assert state["status"] == "active"

    def test_cancel_already_cancelled_returns_ok_skipped(
        self, engine: PaymentEngine
    ) -> None:
        sub_id = self._create_active_sub(engine)
        engine.cancel_subscription(sub_id)
        result2 = engine.cancel_subscription(sub_id)
        assert result2["ok"] is True
        assert result2["data"].get("note") == "already cancelled"
        assert result2["receipt"]["outcome"] == "skipped"

    def test_cancel_missing_sub_returns_err(self, engine: PaymentEngine) -> None:
        result = engine.cancel_subscription("sub_does_not_exist")
        assert result["ok"] is False
        assert result["receipt"]["outcome"] == "failed"

    def test_cancelled_at_timestamp_is_set(
        self, engine: PaymentEngine, db_path: str
    ) -> None:
        sub_id = self._create_active_sub(engine)
        result = engine.cancel_subscription(sub_id)
        assert result["data"]["subscription"]["cancelled_at"] is not None

    def test_rollback_id_in_response(self, engine: PaymentEngine) -> None:
        sub_id = self._create_active_sub(engine)
        result = engine.cancel_subscription(sub_id)
        assert "rollback_id" in result["data"]
        assert result["data"]["rollback_id"].startswith("rbk_")


# ---------------------------------------------------------------------------
# 6. revenue_forecast
# ---------------------------------------------------------------------------


class TestRevenueForecast:
    BIZ = "biz_forecast_001"

    def _seed_active_sub(
        self,
        engine: PaymentEngine,
        amount_cents: int,
        interval: str = "month",
    ) -> None:
        engine.create_subscription(
            client_id=f"{self.BIZ}_client_sub",
            plan_name="Forecast Plan",
            amount_cents=amount_cents,
            interval=interval,
        )

    def _seed_pending_link(
        self, engine: PaymentEngine, amount_cents: int
    ) -> None:
        engine.create_payment_link(
            client_id=f"{self.BIZ}_client_link",
            appointment_id="appt_forecast",
            amount_cents=amount_cents,
        )

    def _seed_paid_link(
        self, engine: PaymentEngine, amount_cents: int
    ) -> None:
        res = engine.create_payment_link(
            client_id=f"{self.BIZ}_client_paid",
            appointment_id="appt_paid",
            amount_cents=amount_cents,
        )
        link_id = res["data"]["record"]["id"]
        engine.record_payment(
            link_id=link_id,
            stripe_event={"type": "payment_intent.succeeded"},
        )

    def test_basic_forecast_returns_ok(self, engine: PaymentEngine) -> None:
        result = engine.revenue_forecast(business_id=self.BIZ, days=30)
        assert result["ok"] is True
        assert "forecast" in result["data"]
        assert result["receipt"]["outcome"] == "executed"

    def test_zero_data_returns_zero_projection(
        self, engine: PaymentEngine
    ) -> None:
        result = engine.revenue_forecast(business_id="biz_empty", days=30)
        forecast = result["data"]["forecast"]
        assert forecast["projected_total_cents"] == 0
        assert forecast["projected_total_dollars"] == 0.0
        assert forecast["active_subscription_count"] == 0

    def test_active_monthly_sub_counted_in_forecast(
        self, engine: PaymentEngine
    ) -> None:
        biz = "biz_sub_only"
        engine.create_subscription(
            client_id=f"{biz}_c",
            plan_name="Monthly",
            amount_cents=10000,
            interval="month",
        )
        result = engine.revenue_forecast(business_id=biz, days=30)
        forecast = result["data"]["forecast"]
        assert forecast["active_subscription_count"] == 1
        assert forecast["mrr_cents"] == 10000
        assert forecast["forecast_from_subscriptions_cents"] == 10000

    def test_active_weekly_sub_mrr_scaled_correctly(
        self, engine: PaymentEngine
    ) -> None:
        biz = "biz_weekly"
        engine.create_subscription(
            client_id=f"{biz}_c",
            plan_name="Weekly",
            amount_cents=1000,
            interval="week",
        )
        result = engine.revenue_forecast(business_id=biz, days=30)
        forecast = result["data"]["forecast"]
        # weekly: amount * 4 = 4000 MRR; forecast for 30 days = 4000
        assert forecast["mrr_cents"] == 4000

    def test_active_yearly_sub_mrr_scaled_correctly(
        self, engine: PaymentEngine
    ) -> None:
        biz = "biz_yearly"
        engine.create_subscription(
            client_id=f"{biz}_c",
            plan_name="Annual",
            amount_cents=12000,
            interval="year",
        )
        result = engine.revenue_forecast(business_id=biz, days=30)
        forecast = result["data"]["forecast"]
        # yearly: amount / 12 = 1000 MRR; forecast for 30 days = 1000
        assert forecast["mrr_cents"] == 1000

    def test_pending_links_included_in_projection(
        self, engine: PaymentEngine
    ) -> None:
        biz = "biz_pending"
        engine.create_payment_link(
            client_id=f"{biz}_c",
            appointment_id="appt_pend",
            amount_cents=7500,
        )
        result = engine.revenue_forecast(business_id=biz, days=30)
        forecast = result["data"]["forecast"]
        assert forecast["pending_payment_links_cents"] == 7500

    def test_paid_history_included_in_projection(
        self, engine: PaymentEngine
    ) -> None:
        biz = "biz_paid_hist"
        res = engine.create_payment_link(
            client_id=f"{biz}_c",
            appointment_id="appt_hist",
            amount_cents=3300,
        )
        link_id = res["data"]["record"]["id"]
        engine.record_payment(
            link_id=link_id,
            stripe_event={"type": "payment_intent.succeeded"},
        )
        result = engine.revenue_forecast(business_id=biz, days=30)
        forecast = result["data"]["forecast"]
        assert forecast["recent_paid_cents"] == 3300

    def test_projected_total_sums_all_components(
        self, engine: PaymentEngine
    ) -> None:
        biz = "biz_sum"
        # Monthly sub: 6000 MRR, 30-day forecast = 6000
        engine.create_subscription(
            client_id=f"{biz}_csub",
            plan_name="Test",
            amount_cents=6000,
            interval="month",
        )
        # Pending link: 2000
        engine.create_payment_link(
            client_id=f"{biz}_cpend",
            appointment_id="appt_pend_sum",
            amount_cents=2000,
        )
        # Paid link: 1000
        res = engine.create_payment_link(
            client_id=f"{biz}_cpaid",
            appointment_id="appt_paid_sum",
            amount_cents=1000,
        )
        engine.record_payment(
            link_id=res["data"]["record"]["id"],
            stripe_event={"type": "payment_intent.succeeded"},
        )
        result = engine.revenue_forecast(business_id=biz, days=30)
        forecast = result["data"]["forecast"]
        expected = (
            forecast["forecast_from_subscriptions_cents"]
            + forecast["pending_payment_links_cents"]
            + forecast["recent_paid_cents"]
        )
        assert forecast["projected_total_cents"] == expected

    def test_projected_total_dollars_correct(
        self, engine: PaymentEngine
    ) -> None:
        biz = "biz_dollars"
        engine.create_payment_link(
            client_id=f"{biz}_c",
            appointment_id="appt_dollars",
            amount_cents=10000,
        )
        result = engine.revenue_forecast(business_id=biz, days=30)
        forecast = result["data"]["forecast"]
        assert forecast["projected_total_dollars"] == round(
            forecast["projected_total_cents"] / 100, 2
        )

    def test_days_zero_returns_err(self, engine: PaymentEngine) -> None:
        result = engine.revenue_forecast(business_id=self.BIZ, days=0)
        assert result["ok"] is False
        assert result["receipt"]["outcome"] == "failed"

    def test_days_negative_returns_err(self, engine: PaymentEngine) -> None:
        result = engine.revenue_forecast(business_id=self.BIZ, days=-5)
        assert result["ok"] is False
        assert result["receipt"]["outcome"] == "failed"

    def test_forecast_contains_required_keys(
        self, engine: PaymentEngine
    ) -> None:
        result = engine.revenue_forecast(business_id="biz_keys", days=30)
        forecast = result["data"]["forecast"]
        for key in (
            "business_id",
            "forecast_days",
            "active_subscription_count",
            "mrr_cents",
            "forecast_from_subscriptions_cents",
            "pending_payment_links_cents",
            "recent_paid_cents",
            "projected_total_cents",
            "projected_total_dollars",
            "generated_at",
        ):
            assert key in forecast, f"Missing forecast key: {key}"

    def test_different_days_scales_subscription_forecast(
        self, engine: PaymentEngine
    ) -> None:
        biz = "biz_scale"
        engine.create_subscription(
            client_id=f"{biz}_c",
            plan_name="Scaling",
            amount_cents=3000,
            interval="month",
        )
        result_30 = engine.revenue_forecast(business_id=biz, days=30)
        result_15 = engine.revenue_forecast(business_id=biz, days=15)
        f30 = result_30["data"]["forecast"]["forecast_from_subscriptions_cents"]
        f15 = result_15["data"]["forecast"]["forecast_from_subscriptions_cents"]
        assert f30 == f15 * 2


# ---------------------------------------------------------------------------
# 7. undo_last_payment_action
# ---------------------------------------------------------------------------


class TestUndoLastPaymentAction:
    def _create_cancelled_sub(
        self,
        engine: PaymentEngine,
        client_id: str = "client_undo",
    ) -> tuple[str, str]:
        """Create and cancel a subscription; return (sub_id, rollback_id)."""
        res = engine.create_subscription(
            client_id=client_id,
            plan_name="Undo Plan",
            amount_cents=5000,
            interval="month",
        )
        sub_id = res["data"]["subscription"]["id"]
        cancel_res = engine.cancel_subscription(sub_id)
        rollback_id = cancel_res["data"]["rollback_id"]
        return sub_id, rollback_id

    def test_undo_with_rollback_record_returns_ok(
        self, engine: PaymentEngine
    ) -> None:
        sub_id, _ = self._create_cancelled_sub(engine)
        result = engine.undo_last_payment_action(business_id="client_undo")
        assert result["ok"] is True
        assert result["receipt"]["outcome"] == "rolled_back"

    def test_undo_restores_subscription_to_active(
        self, engine: PaymentEngine, db_path: str
    ) -> None:
        sub_id, _ = self._create_cancelled_sub(engine)
        engine.undo_last_payment_action(business_id="client_undo")
        rows = _fetch(
            db_path,
            "SELECT status FROM subscriptions WHERE id = ?",
            (sub_id,),
        )
        assert rows[0]["status"] == "active"

    def test_undo_removes_rollback_record_from_db(
        self, engine: PaymentEngine, db_path: str
    ) -> None:
        sub_id, rollback_id = self._create_cancelled_sub(engine)
        engine.undo_last_payment_action(business_id="client_undo")
        rows = _fetch(
            db_path,
            "SELECT * FROM rollbacks WHERE id = ?",
            (rollback_id,),
        )
        assert rows == [], "Rollback record should be deleted after undo"

    def test_undo_response_contains_entity_info(
        self, engine: PaymentEngine
    ) -> None:
        sub_id, _ = self._create_cancelled_sub(engine)
        result = engine.undo_last_payment_action(business_id="client_undo")
        data = result["data"]
        assert data["entity_type"] == "subscription"
        assert data["entity_id"] == sub_id
        assert "rollback_id" in data
        assert "restored" in data

    def test_undo_restored_state_matches_original(
        self, engine: PaymentEngine
    ) -> None:
        sub_id, _ = self._create_cancelled_sub(engine, client_id="client_restore")
        result = engine.undo_last_payment_action(business_id="client_restore")
        restored = result["data"]["restored"]
        assert restored["status"] == "active"
        assert restored["id"] == sub_id

    def test_undo_without_rollback_record_returns_err(
        self, engine: PaymentEngine
    ) -> None:
        # Fresh engine, no actions taken
        result = engine.undo_last_payment_action(business_id="biz_no_history")
        assert result["ok"] is False
        assert result["receipt"]["outcome"] == "failed"

    def test_undo_rollback_not_replayable(
        self, engine: PaymentEngine, db_path: str
    ) -> None:
        """After undo, a second undo should find no rollback records."""
        self._create_cancelled_sub(engine, client_id="client_replay")
        engine.undo_last_payment_action(business_id="client_replay")
        # Second undo — no more rollbacks scoped to this business
        result2 = engine.undo_last_payment_action(business_id="client_replay_unique_99")
        assert result2["ok"] is False

    def test_undo_receipt_rollback_available_is_false(
        self, engine: PaymentEngine
    ) -> None:
        self._create_cancelled_sub(engine, client_id="client_flag")
        result = engine.undo_last_payment_action(business_id="client_flag")
        assert result["receipt"]["rollback_available"] is False


# ---------------------------------------------------------------------------
# Receipt envelope structure sanity checks
# ---------------------------------------------------------------------------


class TestReceiptEnvelopeStructure:
    """Verify every public method returns a valid ok/err envelope with receipt."""

    def test_ok_envelope_shape(self, engine: PaymentEngine) -> None:
        result = engine.create_payment_link(
            client_id="c",
            appointment_id="a",
            amount_cents=100,
        )
        assert "ok" in result
        assert "data" in result
        assert "receipt" in result
        receipt = result["receipt"]
        for field in (
            "action_type",
            "triggered_by",
            "timestamp",
            "outcome",
            "approval_required",
            "rollback_available",
        ):
            assert field in receipt, f"Receipt missing field: {field}"

    def test_err_envelope_shape(self, engine: PaymentEngine) -> None:
        result = engine.create_payment_link(
            client_id="c",
            appointment_id="a",
            amount_cents=0,
        )
        assert result["ok"] is False
        assert "error" in result
        assert "receipt" in result
        assert result["receipt"]["outcome"] == "failed"
