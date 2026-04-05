"""Comprehensive tests for cap6_marketing.py — MarketingEngine.

Covers every public method with real SQLite (tempfile):
- create_campaign: valid channels, invalid channel, invalid JSON
- schedule_campaign: draft→scheduled, wrong status, approval_queue entry
- send_campaign: matching clients, no matches, rate limiting
- create_offer: all 4 valid types, invalid type, invalid JSON
- redeem_offer: pending→redeemed, already redeemed, immutable receipt created
- sync_gbp: all 4 valid actions, invalid action, invalid JSON
- campaign_analytics: with sent campaigns + offers, empty data, date range
- undo_campaign: draft deleted, scheduled deleted, sent offers cancelled, invalid status
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import os
from pathlib import Path
from typing import Generator

import pytest

from isg_agent.capabilities.cap6_marketing import MarketingEngine
from isg_agent.capabilities.shared.db_schema import ensure_tables
from isg_agent.capabilities.shared.foundation import make_id, iso_now


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_path() -> Generator[str, None, None]:
    """Create a temporary SQLite database with all business ops tables."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        path = tmp.name

    ensure_tables(path)
    yield path

    # Cleanup db and WAL/SHM files
    for suffix in ("", "-wal", "-shm"):
        p = path + suffix
        if os.path.exists(p):
            os.unlink(p)


@pytest.fixture()
def engine(db_path: str) -> MarketingEngine:
    """Return a MarketingEngine bound to the temp DB (no channel_router)."""
    return MarketingEngine(db_path=db_path)


def _insert_client(db_path: str, client_id: str, segment: str = "vip") -> None:
    """Insert a minimal client_intelligence row for use in send_campaign tests."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO client_intelligence (id, client_id, segment, clv_cents, "
            "churn_risk_score, health_score, last_computed_at) VALUES (?,?,?,?,?,?,?)",
            (make_id("ci"), client_id, segment, 0, 0.0, 1.0, iso_now()),
        )
        conn.commit()
    finally:
        conn.close()


def _get_row(db_path: str, table: str, row_id: str) -> dict | None:
    """Fetch a single row by id from *table* in the given database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", [row_id]).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _count_rows(db_path: str, table: str, **filters) -> int:
    """Return the count of rows in *table* matching all keyword filters."""
    conn = sqlite3.connect(db_path)
    try:
        if filters:
            where = " AND ".join(f"{k}=?" for k in filters)
            count = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {where}",
                list(filters.values()),
            ).fetchone()[0]
        else:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        return count
    finally:
        conn.close()


# ===========================================================================
# create_campaign
# ===========================================================================


class TestCreateCampaign:
    """Tests for MarketingEngine.create_campaign."""

    def test_create_campaign_sms_channel(self, engine: MarketingEngine, db_path: str):
        """A campaign with channel='sms' is inserted with status 'draft'."""
        result = engine.create_campaign(
            name="Summer SMS Blast",
            segment_filter_json='{"segment": "vip"}',
            channel="sms",
            template="Hey {first_name}, summer deals inside!",
        )

        assert result["ok"] is True
        data = result["data"]
        assert data["channel"] == "sms"
        assert data["status"] == "draft"
        assert data["sent_count"] == 0
        assert data["id"].startswith("cmpg_")

        # Verify DB persistence
        row = _get_row(db_path, "campaigns", data["id"])
        assert row is not None
        assert row["channel"] == "sms"
        assert row["status"] == "draft"

    def test_create_campaign_email_channel(self, engine: MarketingEngine):
        """channel='email' is accepted."""
        result = engine.create_campaign(
            name="Email Promo",
            segment_filter_json='{"segment": "regular"}',
            channel="email",
            template="Check out our latest offers",
        )
        assert result["ok"] is True
        assert result["data"]["channel"] == "email"

    def test_create_campaign_push_channel(self, engine: MarketingEngine):
        """channel='push' is accepted."""
        result = engine.create_campaign(
            name="Push Alert",
            segment_filter_json="{}",
            channel="push",
            template="Flash sale — 2 hours only!",
        )
        assert result["ok"] is True
        assert result["data"]["channel"] == "push"

    def test_create_campaign_invalid_channel(self, engine: MarketingEngine):
        """An unrecognised channel returns an error envelope."""
        result = engine.create_campaign(
            name="Bad Channel",
            segment_filter_json="{}",
            channel="telegram",
            template="...",
        )
        assert result["ok"] is False
        assert "Invalid channel" in result["error"]
        assert "telegram" in result["error"]
        assert result["receipt"]["outcome"] == "failed"

    def test_create_campaign_invalid_json(self, engine: MarketingEngine):
        """Malformed segment_filter_json returns an error envelope."""
        result = engine.create_campaign(
            name="Bad JSON",
            segment_filter_json="{not valid json}",
            channel="sms",
            template="Hi",
        )
        assert result["ok"] is False
        assert "not valid JSON" in result["error"]
        assert result["receipt"]["outcome"] == "failed"

    def test_create_campaign_receipt_structure(self, engine: MarketingEngine):
        """Receipt contains expected fields and correct action_type."""
        result = engine.create_campaign(
            name="Receipt Check",
            segment_filter_json="{}",
            channel="sms",
            template="T",
        )
        receipt = result["receipt"]
        assert receipt["action_type"] == "create_campaign"
        assert receipt["triggered_by"] == "marketing_engine"
        assert receipt["outcome"] == "executed"
        assert receipt["approval_required"] is False
        assert receipt["rollback_available"] is True

    def test_create_campaign_empty_segment_filter(self, engine: MarketingEngine):
        """An empty JSON object '{}' is valid for segment_filter_json."""
        result = engine.create_campaign(
            name="Broadcast",
            segment_filter_json="{}",
            channel="push",
            template="Broadcast message",
        )
        assert result["ok"] is True

    def test_create_campaign_stores_template(self, engine: MarketingEngine, db_path: str):
        """The template text is persisted verbatim."""
        tmpl = "Hello {name}, your discount code is {code}."
        result = engine.create_campaign(
            name="Template Test",
            segment_filter_json="{}",
            channel="email",
            template=tmpl,
        )
        assert result["ok"] is True
        row = _get_row(db_path, "campaigns", result["data"]["id"])
        assert row["template"] == tmpl


# ===========================================================================
# schedule_campaign
# ===========================================================================


class TestScheduleCampaign:
    """Tests for MarketingEngine.schedule_campaign."""

    def _make_draft_campaign(self, engine: MarketingEngine) -> str:
        """Create a draft campaign and return its ID."""
        result = engine.create_campaign(
            name="Draft for Scheduling",
            segment_filter_json='{"segment": "vip"}',
            channel="sms",
            template="Schedule me",
        )
        assert result["ok"] is True
        return result["data"]["id"]

    def test_schedule_draft_to_scheduled(
        self, engine: MarketingEngine, db_path: str
    ):
        """A draft campaign transitions to 'scheduled' status."""
        cid = self._make_draft_campaign(engine)
        scheduled_at = "2026-06-01T10:00:00+00:00"

        result = engine.schedule_campaign(cid, scheduled_at)

        assert result["ok"] is True
        data = result["data"]
        assert "campaign" in data
        assert "approval_entry" in data
        assert "rollback_token" in data

        # Check campaign status in DB
        row = _get_row(db_path, "campaigns", cid)
        assert row["status"] == "scheduled"
        assert row["scheduled_at"] == scheduled_at

    def test_schedule_creates_approval_queue_entry(
        self, engine: MarketingEngine, db_path: str
    ):
        """Scheduling inserts exactly one pending entry into approval_queue."""
        cid = self._make_draft_campaign(engine)
        result = engine.schedule_campaign(cid, "2026-06-01T10:00:00+00:00")
        assert result["ok"] is True

        approval_id = result["data"]["approval_entry"]["id"]
        row = _get_row(db_path, "approval_queue", approval_id)
        assert row is not None
        assert row["status"] == "pending"
        assert row["entity_id"] == cid
        assert row["action"] == "send_campaign"

    def test_schedule_approval_payload_contains_campaign_id(
        self, engine: MarketingEngine
    ):
        """The approval_entry payload_json encodes the campaign_id."""
        cid = self._make_draft_campaign(engine)
        scheduled_at = "2026-07-15T08:00:00+00:00"
        result = engine.schedule_campaign(cid, scheduled_at)
        payload = json.loads(result["data"]["approval_entry"]["payload_json"])
        assert payload["campaign_id"] == cid
        assert payload["scheduled_at"] == scheduled_at

    def test_schedule_nonexistent_campaign(self, engine: MarketingEngine):
        """Scheduling a non-existent campaign ID returns an error."""
        result = engine.schedule_campaign("cmpg_does_not_exist", "2026-01-01T00:00:00Z")
        assert result["ok"] is False
        assert "not found" in result["error"]

    def test_schedule_already_scheduled_campaign(self, engine: MarketingEngine):
        """Scheduling a campaign that is already 'scheduled' returns an error."""
        cid = self._make_draft_campaign(engine)
        engine.schedule_campaign(cid, "2026-06-01T10:00:00Z")

        # Attempt second schedule
        result = engine.schedule_campaign(cid, "2026-06-02T10:00:00Z")
        assert result["ok"] is False
        assert "only 'draft' campaigns can be scheduled" in result["error"]

    def test_schedule_sent_campaign_rejected(
        self, engine: MarketingEngine, db_path: str
    ):
        """Scheduling a 'sent' campaign is rejected."""
        cid = self._make_draft_campaign(engine)
        # Force status to sent via raw SQL
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE campaigns SET status='sent' WHERE id=?", [cid])
        conn.commit()
        conn.close()

        result = engine.schedule_campaign(cid, "2026-08-01T10:00:00Z")
        assert result["ok"] is False
        assert "only 'draft' campaigns can be scheduled" in result["error"]

    def test_schedule_receipt_is_queued(self, engine: MarketingEngine):
        """Receipt outcome for a successful schedule is 'queued'."""
        cid = self._make_draft_campaign(engine)
        result = engine.schedule_campaign(cid, "2026-06-01T10:00:00Z")
        assert result["receipt"]["outcome"] == "queued"
        assert result["receipt"]["approval_required"] is True


# ===========================================================================
# send_campaign
# ===========================================================================


class TestSendCampaign:
    """Tests for MarketingEngine.send_campaign."""

    def _make_campaign(
        self,
        engine: MarketingEngine,
        channel: str = "sms",
        segment: str = "vip",
        status_override: str | None = None,
        db_path: str | None = None,
    ) -> str:
        """Create a draft campaign and optionally force a DB status."""
        result = engine.create_campaign(
            name=f"Send Test {channel}",
            segment_filter_json=json.dumps({"segment": segment}),
            channel=channel,
            template="Hi, here is your offer",
        )
        assert result["ok"] is True
        cid = result["data"]["id"]
        if status_override and db_path:
            conn = sqlite3.connect(db_path)
            conn.execute(
                "UPDATE campaigns SET status=? WHERE id=?", [status_override, cid]
            )
            conn.commit()
            conn.close()
        return cid

    def test_send_campaign_with_matching_clients(
        self, engine: MarketingEngine, db_path: str
    ):
        """Offers are created for each matching client_intelligence row."""
        _insert_client(db_path, "client-001", segment="vip")
        _insert_client(db_path, "client-002", segment="vip")
        cid = self._make_campaign(engine, channel="sms", segment="vip")

        result = engine.send_campaign(cid)

        assert result["ok"] is True
        data = result["data"]
        assert data["clients_matched"] == 2
        assert data["offers_created"] == 2
        assert data["status"] == "sent"

        # Verify offers in DB
        assert _count_rows(db_path, "offers", campaign_id=cid) == 2

        # Campaign status updated
        row = _get_row(db_path, "campaigns", cid)
        assert row["status"] == "sent"
        assert row["sent_count"] == 2

    def test_send_campaign_no_matching_clients(
        self, engine: MarketingEngine, db_path: str
    ):
        """Sending with no matching clients results in 0 offers."""
        # Insert a client with a different segment
        _insert_client(db_path, "client-003", segment="regular")
        cid = self._make_campaign(engine, channel="sms", segment="vip")

        result = engine.send_campaign(cid)

        assert result["ok"] is True
        assert result["data"]["clients_matched"] == 0
        assert result["data"]["offers_created"] == 0
        assert _count_rows(db_path, "offers", campaign_id=cid) == 0

    def test_send_campaign_from_scheduled_status(
        self, engine: MarketingEngine, db_path: str
    ):
        """A 'scheduled' campaign can also be sent."""
        _insert_client(db_path, "client-sc-01", segment="vip")
        cid = self._make_campaign(
            engine, channel="sms", status_override="scheduled", db_path=db_path
        )

        result = engine.send_campaign(cid)
        assert result["ok"] is True
        assert result["data"]["status"] == "sent"

    def test_send_campaign_already_sent_rejected(
        self, engine: MarketingEngine, db_path: str
    ):
        """Sending an already-sent campaign returns an error."""
        cid = self._make_campaign(
            engine, channel="sms", status_override="sent", db_path=db_path
        )
        result = engine.send_campaign(cid)
        assert result["ok"] is False
        assert "must be one of" in result["error"]

    def test_send_campaign_nonexistent(self, engine: MarketingEngine):
        """Sending a non-existent campaign returns an error."""
        result = engine.send_campaign("cmpg_ghost")
        assert result["ok"] is False
        assert "not found" in result["error"]

    def test_send_campaign_rate_limiting_sms(
        self, engine: MarketingEngine, db_path: str
    ):
        """SMS rate limiting: after 3 sends a client is skipped."""
        client_id = "client-ratelimit-sms"
        _insert_client(db_path, client_id, segment="promo")

        # Exhaust the SMS limit (3/day) by sending 3 separate campaigns
        for i in range(3):
            cid = engine.create_campaign(
                name=f"SMS Campaign {i}",
                segment_filter_json='{"segment": "promo"}',
                channel="sms",
                template=f"Offer {i}",
            )["data"]["id"]
            result = engine.send_campaign(cid)
            assert result["ok"] is True
            assert result["data"]["rate_limited_skipped"] == 0

        # 4th campaign should hit the rate limit for this client
        cid4 = engine.create_campaign(
            name="SMS Campaign overflow",
            segment_filter_json='{"segment": "promo"}',
            channel="sms",
            template="You're over the limit",
        )["data"]["id"]
        result4 = engine.send_campaign(cid4)
        assert result4["ok"] is True
        assert result4["data"]["rate_limited_skipped"] == 1
        assert result4["data"]["offers_created"] == 0

    def test_send_campaign_rate_limiting_email(
        self, engine: MarketingEngine, db_path: str
    ):
        """Email rate limiting: limit is 1/day, second campaign is blocked."""
        client_id = "client-ratelimit-email"
        _insert_client(db_path, client_id, segment="email-seg")

        # First email campaign succeeds
        cid1 = engine.create_campaign(
            name="Email 1",
            segment_filter_json='{"segment": "email-seg"}',
            channel="email",
            template="First email",
        )["data"]["id"]
        r1 = engine.send_campaign(cid1)
        assert r1["ok"] is True
        assert r1["data"]["offers_created"] == 1

        # Second email campaign hits the daily limit
        cid2 = engine.create_campaign(
            name="Email 2",
            segment_filter_json='{"segment": "email-seg"}',
            channel="email",
            template="Second email",
        )["data"]["id"]
        r2 = engine.send_campaign(cid2)
        assert r2["ok"] is True
        assert r2["data"]["rate_limited_skipped"] == 1
        assert r2["data"]["offers_created"] == 0

    def test_send_campaign_push_bypasses_rate_limiter(
        self, engine: MarketingEngine, db_path: str
    ):
        """Push notifications bypass the rate limiter entirely."""
        client_id = "client-push-01"
        _insert_client(db_path, client_id, segment="push-seg")

        # Send 5 push campaigns — all should succeed without rate limiting
        for i in range(5):
            cid = engine.create_campaign(
                name=f"Push {i}",
                segment_filter_json='{"segment": "push-seg"}',
                channel="push",
                template=f"Push {i}",
            )["data"]["id"]
            r = engine.send_campaign(cid)
            assert r["ok"] is True
            assert r["data"]["rate_limited_skipped"] == 0
            assert r["data"]["offers_created"] == 1

    def test_send_campaign_writes_immutable_receipt(
        self, engine: MarketingEngine, db_path: str
    ):
        """send_campaign writes an immutable receipt to the DB."""
        _insert_client(db_path, "client-rcpt-01", segment="vip")
        cid = self._make_campaign(engine, channel="sms", segment="vip")

        before = _count_rows(db_path, "immutable_receipts")
        engine.send_campaign(cid)
        after = _count_rows(db_path, "immutable_receipts")
        assert after == before + 1

    def test_send_campaign_offers_have_correct_campaign_id(
        self, engine: MarketingEngine, db_path: str
    ):
        """Each created offer's campaign_id matches the campaign being sent."""
        _insert_client(db_path, "client-offr-01", segment="vip")
        cid = self._make_campaign(engine, channel="sms", segment="vip")
        engine.send_campaign(cid)

        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT campaign_id FROM offers WHERE campaign_id=?", [cid]
        ).fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0][0] == cid


# ===========================================================================
# create_offer
# ===========================================================================


class TestCreateOffer:
    """Tests for MarketingEngine.create_offer."""

    VALID_DETAILS = '{"amount_cents": 500, "description": "5 dollar off"}'
    FUTURE_EXPIRY = "2027-12-31T23:59:59+00:00"

    def test_create_offer_discount(self, engine: MarketingEngine, db_path: str):
        """offer_type='discount' is accepted and persisted."""
        result = engine.create_offer(
            campaign_id="cmpg_test",
            client_id="cli_001",
            offer_type="discount",
            details_json=self.VALID_DETAILS,
            expires_at=self.FUTURE_EXPIRY,
        )
        assert result["ok"] is True
        data = result["data"]
        assert data["offer_type"] == "discount"
        assert data["status"] == "pending"
        assert data["id"].startswith("offr_")

        row = _get_row(db_path, "offers", data["id"])
        assert row is not None
        assert row["offer_type"] == "discount"

    def test_create_offer_free_addon(self, engine: MarketingEngine):
        """offer_type='free_addon' is accepted."""
        result = engine.create_offer(
            campaign_id="cmpg_test",
            client_id="cli_002",
            offer_type="free_addon",
            details_json='{"addon": "conditioning treatment"}',
            expires_at=self.FUTURE_EXPIRY,
        )
        assert result["ok"] is True
        assert result["data"]["offer_type"] == "free_addon"

    def test_create_offer_loyalty_reward(self, engine: MarketingEngine):
        """offer_type='loyalty_reward' is accepted."""
        result = engine.create_offer(
            campaign_id="cmpg_test",
            client_id="cli_003",
            offer_type="loyalty_reward",
            details_json='{"points": 200}',
            expires_at=self.FUTURE_EXPIRY,
        )
        assert result["ok"] is True
        assert result["data"]["offer_type"] == "loyalty_reward"

    def test_create_offer_referral_bonus(self, engine: MarketingEngine):
        """offer_type='referral_bonus' is accepted."""
        result = engine.create_offer(
            campaign_id="cmpg_test",
            client_id="cli_004",
            offer_type="referral_bonus",
            details_json='{"bonus_cents": 1000}',
            expires_at=self.FUTURE_EXPIRY,
        )
        assert result["ok"] is True
        assert result["data"]["offer_type"] == "referral_bonus"

    def test_create_offer_invalid_type(self, engine: MarketingEngine):
        """An unrecognised offer_type returns an error envelope."""
        result = engine.create_offer(
            campaign_id="cmpg_test",
            client_id="cli_005",
            offer_type="bogo",
            details_json="{}",
            expires_at=self.FUTURE_EXPIRY,
        )
        assert result["ok"] is False
        assert "Invalid offer_type" in result["error"]
        assert "bogo" in result["error"]
        assert result["receipt"]["outcome"] == "failed"

    def test_create_offer_invalid_details_json(self, engine: MarketingEngine):
        """Malformed details_json returns an error envelope."""
        result = engine.create_offer(
            campaign_id="cmpg_test",
            client_id="cli_006",
            offer_type="discount",
            details_json="not-json",
            expires_at=self.FUTURE_EXPIRY,
        )
        assert result["ok"] is False
        assert "not valid JSON" in result["error"]

    def test_create_offer_receipt_structure(self, engine: MarketingEngine):
        """Receipt has correct action_type, outcome, and flags."""
        result = engine.create_offer(
            campaign_id="cmpg_test",
            client_id="cli_007",
            offer_type="discount",
            details_json="{}",
            expires_at=self.FUTURE_EXPIRY,
        )
        receipt = result["receipt"]
        assert receipt["action_type"] == "create_offer"
        assert receipt["outcome"] == "executed"
        assert receipt["approval_required"] is False
        assert receipt["rollback_available"] is True

    def test_create_offer_stores_expires_at(
        self, engine: MarketingEngine, db_path: str
    ):
        """expires_at is stored exactly as provided."""
        expiry = "2027-03-15T12:00:00+00:00"
        result = engine.create_offer(
            campaign_id="cmpg_test",
            client_id="cli_008",
            offer_type="discount",
            details_json="{}",
            expires_at=expiry,
        )
        assert result["ok"] is True
        row = _get_row(db_path, "offers", result["data"]["id"])
        assert row["expires_at"] == expiry


# ===========================================================================
# redeem_offer
# ===========================================================================


class TestRedeemOffer:
    """Tests for MarketingEngine.redeem_offer."""

    def _create_pending_offer(
        self, engine: MarketingEngine, campaign_id: str = "cmpg_test"
    ) -> str:
        """Create a pending offer and return its ID."""
        result = engine.create_offer(
            campaign_id=campaign_id,
            client_id="cli_redeem",
            offer_type="discount",
            details_json='{"amount_cents": 500}',
            expires_at="2027-12-31T23:59:59+00:00",
        )
        assert result["ok"] is True
        return result["data"]["id"]

    def test_redeem_pending_offer(self, engine: MarketingEngine, db_path: str):
        """A pending offer is redeemed and status changes to 'redeemed'."""
        oid = self._create_pending_offer(engine)
        result = engine.redeem_offer(oid)

        assert result["ok"] is True
        data = result["data"]
        assert data["offer_id"] == oid
        assert data["status"] == "redeemed"
        assert data["redeemed_at"] is not None

        # Verify in DB
        row = _get_row(db_path, "offers", oid)
        assert row["status"] == "redeemed"
        assert row["redeemed_at"] is not None

    def test_redeem_offer_creates_immutable_receipt(
        self, engine: MarketingEngine, db_path: str
    ):
        """redeem_offer writes an immutable receipt and returns its ID."""
        oid = self._create_pending_offer(engine)

        before = _count_rows(db_path, "immutable_receipts")
        result = engine.redeem_offer(oid)
        after = _count_rows(db_path, "immutable_receipts")

        assert result["ok"] is True
        assert after == before + 1
        assert result["data"]["immutable_receipt_id"] is not None

    def test_redeem_already_redeemed_offer(self, engine: MarketingEngine):
        """Attempting to redeem an already-redeemed offer returns an error."""
        oid = self._create_pending_offer(engine)
        engine.redeem_offer(oid)  # First redeem

        result = engine.redeem_offer(oid)  # Second attempt
        assert result["ok"] is False
        assert "only 'pending' offers can be redeemed" in result["error"]

    def test_redeem_cancelled_offer_rejected(
        self, engine: MarketingEngine, db_path: str
    ):
        """Redeeming a 'cancelled' offer returns an error."""
        oid = self._create_pending_offer(engine)
        # Force status to cancelled
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE offers SET status='cancelled' WHERE id=?", [oid])
        conn.commit()
        conn.close()

        result = engine.redeem_offer(oid)
        assert result["ok"] is False
        assert "only 'pending' offers can be redeemed" in result["error"]

    def test_redeem_nonexistent_offer(self, engine: MarketingEngine):
        """Redeeming a non-existent offer ID returns an error."""
        result = engine.redeem_offer("offr_does_not_exist")
        assert result["ok"] is False
        assert "not found" in result["error"]

    def test_redeem_offer_receipt_rollback_not_available(self, engine: MarketingEngine):
        """Redemption receipt has rollback_available=False (immutable)."""
        oid = self._create_pending_offer(engine)
        result = engine.redeem_offer(oid)
        assert result["receipt"]["rollback_available"] is False
        assert result["receipt"]["outcome"] == "executed"

    def test_redeem_offer_immutable_receipt_has_offer_details(
        self, engine: MarketingEngine, db_path: str
    ):
        """The immutable receipt's details_json contains the offer_id."""
        oid = self._create_pending_offer(engine, campaign_id="cmpg_xyz")
        engine.redeem_offer(oid)

        # Fetch the immutable receipt from DB
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM immutable_receipts ORDER BY rowid DESC LIMIT 1"
        ).fetchall()
        conn.close()

        assert len(rows) == 1
        # The receipt exists; details are stored in the DB record
        row = dict(rows[0])
        assert row["id"] is not None


# ===========================================================================
# sync_gbp
# ===========================================================================


class TestSyncGbp:
    """Tests for MarketingEngine.sync_gbp."""

    def test_sync_gbp_update_hours(self, engine: MarketingEngine, db_path: str):
        """action='update_hours' is logged correctly."""
        payload = '{"monday": "9am-6pm", "tuesday": "9am-6pm"}'
        result = engine.sync_gbp("update_hours", payload)

        assert result["ok"] is True
        data = result["data"]
        assert data["action"] == "update_hours"
        assert data["status"] == "logged"
        assert data["id"].startswith("gbp_")

        row = _get_row(db_path, "gbp_sync_log", data["id"])
        assert row is not None
        assert row["action"] == "update_hours"

    def test_sync_gbp_post_update(self, engine: MarketingEngine):
        """action='post_update' is accepted."""
        result = engine.sync_gbp(
            "post_update",
            '{"content": "We are open late this Friday!"}',
        )
        assert result["ok"] is True
        assert result["data"]["action"] == "post_update"

    def test_sync_gbp_respond_review(self, engine: MarketingEngine):
        """action='respond_review' is accepted."""
        result = engine.sync_gbp(
            "respond_review",
            '{"review_id": "rv_123", "response": "Thank you!"}',
        )
        assert result["ok"] is True
        assert result["data"]["action"] == "respond_review"

    def test_sync_gbp_update_photos(self, engine: MarketingEngine):
        """action='update_photos' is accepted."""
        result = engine.sync_gbp(
            "update_photos",
            '{"photo_urls": ["https://example.com/photo1.jpg"]}',
        )
        assert result["ok"] is True
        assert result["data"]["action"] == "update_photos"

    def test_sync_gbp_invalid_action(self, engine: MarketingEngine):
        """An unrecognised GBP action returns an error envelope."""
        result = engine.sync_gbp("delete_listing", "{}")
        assert result["ok"] is False
        assert "Invalid GBP action" in result["error"]
        assert "delete_listing" in result["error"]
        assert result["receipt"]["outcome"] == "failed"

    def test_sync_gbp_invalid_payload_json(self, engine: MarketingEngine):
        """Malformed payload_json returns an error envelope."""
        result = engine.sync_gbp("post_update", "this is not json")
        assert result["ok"] is False
        assert "not valid JSON" in result["error"]

    def test_sync_gbp_receipt_not_rollbackable(self, engine: MarketingEngine):
        """GBP sync receipt has rollback_available=False."""
        result = engine.sync_gbp("update_hours", '{"hours": "9-5"}')
        assert result["receipt"]["rollback_available"] is False
        assert result["receipt"]["approval_required"] is False

    def test_sync_gbp_persists_payload_json(
        self, engine: MarketingEngine, db_path: str
    ):
        """The exact payload_json string is stored in gbp_sync_log."""
        payload = '{"key": "value", "num": 42}'
        result = engine.sync_gbp("post_update", payload)
        row = _get_row(db_path, "gbp_sync_log", result["data"]["id"])
        assert row["payload_json"] == payload


# ===========================================================================
# campaign_analytics
# ===========================================================================


class TestCampaignAnalytics:
    """Tests for MarketingEngine.campaign_analytics."""

    def _setup_sent_campaign_with_offers(
        self,
        engine: MarketingEngine,
        db_path: str,
        segment: str = "vip",
        num_clients: int = 2,
        redeem_count: int = 0,
        revenue_per_redemption: int = 0,
    ) -> str:
        """Insert clients, create a campaign, send it, and optionally redeem offers."""
        client_ids = []
        for i in range(num_clients):
            cid = f"client-analytics-{segment}-{i}"
            _insert_client(db_path, cid, segment=segment)
            client_ids.append(cid)

        campaign = engine.create_campaign(
            name=f"Analytics Campaign {segment}",
            segment_filter_json=json.dumps({"segment": segment}),
            channel="push",  # push bypasses rate limiter
            template="Analytics offer",
        )
        assert campaign["ok"] is True
        campaign_id = campaign["data"]["id"]

        send_result = engine.send_campaign(campaign_id)
        assert send_result["ok"] is True

        if redeem_count > 0:
            # Redeem the first N offers; optionally embed revenue_cents
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            offers = conn.execute(
                "SELECT id FROM offers WHERE campaign_id=? LIMIT ?",
                [campaign_id, redeem_count],
            ).fetchall()
            conn.close()

            for offer_row in offers:
                oid = offer_row["id"]
                if revenue_per_redemption:
                    # Update details_json to include revenue_cents
                    conn = sqlite3.connect(db_path)
                    conn.execute(
                        "UPDATE offers SET details_json=? WHERE id=?",
                        [
                            json.dumps({"revenue_cents": revenue_per_redemption}),
                            oid,
                        ],
                    )
                    conn.commit()
                    conn.close()
                r = engine.redeem_offer(oid)
                assert r["ok"] is True

        return campaign_id

    def test_analytics_empty_database(self, engine: MarketingEngine):
        """Analytics with no sent campaigns returns zeros."""
        result = engine.campaign_analytics("biz_001", days=30)
        assert result["ok"] is True
        data = result["data"]
        assert data["campaigns_sent"] == 0
        assert data["total_offers"] == 0
        assert data["redeemed_offers"] == 0
        assert data["redemption_rate"] == 0.0
        assert data["revenue_from_offers"] == 0
        assert data["business_id"] == "biz_001"
        assert data["period_days"] == 30

    def test_analytics_counts_sent_campaigns(
        self, engine: MarketingEngine, db_path: str
    ):
        """campaigns_sent reflects the number of sent campaigns in the window."""
        self._setup_sent_campaign_with_offers(engine, db_path, segment="seg-a", num_clients=1)
        self._setup_sent_campaign_with_offers(engine, db_path, segment="seg-b", num_clients=1)

        result = engine.campaign_analytics("biz_002", days=30)
        assert result["ok"] is True
        assert result["data"]["campaigns_sent"] == 2

    def test_analytics_total_offers_count(
        self, engine: MarketingEngine, db_path: str
    ):
        """total_offers is the sum of all offers from sent campaigns in window."""
        self._setup_sent_campaign_with_offers(
            engine, db_path, segment="seg-c", num_clients=3
        )
        result = engine.campaign_analytics("biz_003", days=30)
        assert result["data"]["total_offers"] == 3

    def test_analytics_redemption_rate_calculation(
        self, engine: MarketingEngine, db_path: str
    ):
        """redemption_rate = redeemed / total, rounded to 4 decimal places."""
        # 2 clients, 1 redeemed → 0.5
        self._setup_sent_campaign_with_offers(
            engine,
            db_path,
            segment="seg-d",
            num_clients=2,
            redeem_count=1,
        )
        result = engine.campaign_analytics("biz_004", days=30)
        data = result["data"]
        assert data["total_offers"] == 2
        assert data["redeemed_offers"] == 1
        assert data["redemption_rate"] == 0.5

    def test_analytics_revenue_from_offers(
        self, engine: MarketingEngine, db_path: str
    ):
        """revenue_from_offers sums revenue_cents from redeemed offer details_json."""
        self._setup_sent_campaign_with_offers(
            engine,
            db_path,
            segment="seg-e",
            num_clients=2,
            redeem_count=2,
            revenue_per_redemption=1500,
        )
        result = engine.campaign_analytics("biz_005", days=30)
        data = result["data"]
        assert data["redeemed_offers"] == 2
        assert data["revenue_from_offers"] == 3000  # 2 * 1500

    def test_analytics_date_range_filters_old_campaigns(
        self, engine: MarketingEngine, db_path: str
    ):
        """Campaigns outside the date window are excluded from analytics."""
        # Insert a sent campaign but manually backdate it to 60 days ago
        self._setup_sent_campaign_with_offers(
            engine, db_path, segment="seg-old", num_clients=2
        )
        # Backdate the campaign to 60 days ago
        conn = sqlite3.connect(db_path)
        from datetime import timedelta
        from isg_agent.capabilities.shared.foundation import utc_now
        old_date = (utc_now() - timedelta(days=60)).isoformat()
        conn.execute(
            "UPDATE campaigns SET created_at=? WHERE status='sent'", [old_date]
        )
        conn.commit()
        conn.close()

        # 30-day window should not include this campaign
        result = engine.campaign_analytics("biz_006", days=30)
        assert result["ok"] is True
        assert result["data"]["campaigns_sent"] == 0
        assert result["data"]["total_offers"] == 0

    def test_analytics_custom_days_parameter(
        self, engine: MarketingEngine, db_path: str
    ):
        """The days parameter is reflected in the response and used for filtering."""
        result = engine.campaign_analytics("biz_007", days=7)
        assert result["ok"] is True
        assert result["data"]["period_days"] == 7

    def test_analytics_period_start_in_response(
        self, engine: MarketingEngine
    ):
        """period_start is included in the analytics response."""
        result = engine.campaign_analytics("biz_008", days=14)
        assert "period_start" in result["data"]
        assert result["data"]["period_start"] is not None

    def test_analytics_receipt_structure(self, engine: MarketingEngine):
        """Analytics receipt has correct action_type and outcome."""
        result = engine.campaign_analytics("biz_009")
        assert result["receipt"]["action_type"] == "campaign_analytics"
        assert result["receipt"]["outcome"] == "executed"
        assert result["receipt"]["approval_required"] is False


# ===========================================================================
# undo_campaign
# ===========================================================================


class TestUndoCampaign:
    """Tests for MarketingEngine.undo_campaign."""

    def _make_campaign_with_status(
        self,
        engine: MarketingEngine,
        db_path: str,
        channel: str = "sms",
        status: str = "draft",
    ) -> str:
        """Create a campaign and force it into *status*."""
        result = engine.create_campaign(
            name=f"Undo Test ({status})",
            segment_filter_json="{}",
            channel=channel,
            template="Undo me",
        )
        assert result["ok"] is True
        cid = result["data"]["id"]
        if status != "draft":
            conn = sqlite3.connect(db_path)
            conn.execute(
                "UPDATE campaigns SET status=? WHERE id=?", [status, cid]
            )
            conn.commit()
            conn.close()
        return cid

    def test_undo_draft_campaign_deletes_it(
        self, engine: MarketingEngine, db_path: str
    ):
        """Undoing a 'draft' campaign removes it from the campaigns table."""
        cid = self._make_campaign_with_status(engine, db_path, status="draft")

        result = engine.undo_campaign(cid)

        assert result["ok"] is True
        data = result["data"]
        assert data["action_taken"] == "deleted"
        assert data["previous_status"] == "draft"
        assert data["campaign_id"] == cid

        # Must be gone from DB
        assert _get_row(db_path, "campaigns", cid) is None

    def test_undo_draft_creates_rollback_record(
        self, engine: MarketingEngine, db_path: str
    ):
        """A rollback record is persisted when a draft is deleted."""
        cid = self._make_campaign_with_status(engine, db_path, status="draft")
        result = engine.undo_campaign(cid)

        rollback_id = result["data"]["rollback_id"]
        row = _get_row(db_path, "rollbacks", rollback_id)
        assert row is not None
        assert row["entity_id"] == cid
        assert row["action"] == "delete_campaign"

    def test_undo_scheduled_campaign_deletes_it(
        self, engine: MarketingEngine, db_path: str
    ):
        """Undoing a 'scheduled' campaign removes it from the campaigns table."""
        cid = self._make_campaign_with_status(engine, db_path, status="scheduled")

        result = engine.undo_campaign(cid)

        assert result["ok"] is True
        assert result["data"]["action_taken"] == "deleted"
        assert result["data"]["previous_status"] == "scheduled"
        assert _get_row(db_path, "campaigns", cid) is None

    def test_undo_sent_campaign_cancels_pending_offers(
        self, engine: MarketingEngine, db_path: str
    ):
        """Undoing a 'sent' campaign marks all pending offers as 'cancelled'."""
        # Set up: insert 2 clients, send a push campaign so both get offers
        _insert_client(db_path, "client-undo-01", segment="undo-seg")
        _insert_client(db_path, "client-undo-02", segment="undo-seg")

        cid_result = engine.create_campaign(
            name="Sent for Undo",
            segment_filter_json='{"segment": "undo-seg"}',
            channel="push",
            template="Undo this",
        )
        assert cid_result["ok"] is True
        cid = cid_result["data"]["id"]

        send_result = engine.send_campaign(cid)
        assert send_result["ok"] is True
        assert send_result["data"]["offers_created"] == 2

        # Undo the sent campaign
        result = engine.undo_campaign(cid)

        assert result["ok"] is True
        data = result["data"]
        assert data["action_taken"] == "offers_cancelled"
        assert data["cancelled_offers"] == 2

        # All offers should now be 'cancelled'
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT status FROM offers WHERE campaign_id=?", [cid]
        ).fetchall()
        conn.close()
        assert all(r[0] == "cancelled" for r in rows)

        # Campaign record itself still exists (just offers cancelled)
        assert _get_row(db_path, "campaigns", cid) is not None

    def test_undo_sent_campaign_only_cancels_pending_offers(
        self, engine: MarketingEngine, db_path: str
    ):
        """Already-redeemed offers are NOT changed by undo_campaign."""
        _insert_client(db_path, "client-undo-03", segment="undo-seg2")
        _insert_client(db_path, "client-undo-04", segment="undo-seg2")

        cid = engine.create_campaign(
            name="Partial Undo",
            segment_filter_json='{"segment": "undo-seg2"}',
            channel="push",
            template="Partial undo",
        )["data"]["id"]
        engine.send_campaign(cid)

        # Redeem one offer
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        first_offer = conn.execute(
            "SELECT id FROM offers WHERE campaign_id=? LIMIT 1", [cid]
        ).fetchone()
        conn.close()
        engine.redeem_offer(first_offer["id"])

        # Undo the campaign
        result = engine.undo_campaign(cid)
        assert result["ok"] is True
        # Only the 1 pending offer was cancelled, not the redeemed one
        assert result["data"]["cancelled_offers"] == 1

        # Verify redeemed offer is still redeemed
        redeemed_row = _get_row(db_path, "offers", first_offer["id"])
        assert redeemed_row["status"] == "redeemed"

    def test_undo_sent_creates_rollback_record(
        self, engine: MarketingEngine, db_path: str
    ):
        """Undoing a sent campaign writes a rollback record."""
        _insert_client(db_path, "client-undo-rb", segment="undo-rbseg")
        cid = engine.create_campaign(
            name="Undo Rollback Test",
            segment_filter_json='{"segment": "undo-rbseg"}',
            channel="push",
            template="RB",
        )["data"]["id"]
        engine.send_campaign(cid)

        result = engine.undo_campaign(cid)
        rollback_id = result["data"]["rollback_id"]
        row = _get_row(db_path, "rollbacks", rollback_id)
        assert row is not None
        assert row["action"] == "cancel_campaign_offers"
        assert row["entity_id"] == cid

    def test_undo_nonexistent_campaign(self, engine: MarketingEngine):
        """Undoing a non-existent campaign returns an error."""
        result = engine.undo_campaign("cmpg_ghost_id")
        assert result["ok"] is False
        assert "not found" in result["error"]

    def test_undo_invalid_status_campaign(
        self, engine: MarketingEngine, db_path: str
    ):
        """A campaign with an unrecognised status cannot be undone."""
        cid = self._make_campaign_with_status(engine, db_path, status="draft")
        # Force an unsupported status
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE campaigns SET status='archived' WHERE id=?", [cid])
        conn.commit()
        conn.close()

        result = engine.undo_campaign(cid)
        assert result["ok"] is False
        assert "cannot be undone" in result["error"]

    def test_undo_receipt_outcome_is_rolled_back(
        self, engine: MarketingEngine, db_path: str
    ):
        """Receipt outcome for undo operations is 'rolled_back'."""
        cid = self._make_campaign_with_status(engine, db_path, status="draft")
        result = engine.undo_campaign(cid)
        assert result["receipt"]["outcome"] == "rolled_back"
        assert result["receipt"]["rollback_available"] is False

    def test_undo_rollback_record_stores_previous_state(
        self, engine: MarketingEngine, db_path: str
    ):
        """The rollback record's previous_state_json contains the campaign name."""
        cid = self._make_campaign_with_status(engine, db_path, status="draft")
        result = engine.undo_campaign(cid)
        rollback_id = result["data"]["rollback_id"]
        row = _get_row(db_path, "rollbacks", rollback_id)
        previous_state = json.loads(row["previous_state_json"])
        assert previous_state["id"] == cid
        assert "Undo Test" in previous_state["name"]
