"""Integration tests for all 24 business-ops API endpoints.

The AGENT1_DB_PATH env var is set to a temp SQLite file at module level,
before the api_routes module is imported, so that the module-level
``ensure_tables`` call and ``_DB_PATH`` binding both use the temp DB.

Each test group (capability) covers:
- A happy-path 200 call with valid JSON body / query params.
- At least one 422 validation-error case for a missing required field.
"""

from __future__ import annotations

import os
import tempfile

# ---- Set DB path BEFORE importing api_routes --------------------------------
_tmp_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db_path: str = _tmp_db_file.name
_tmp_db_file.close()
os.environ["AGENT1_DB_PATH"] = _tmp_db_path
# -----------------------------------------------------------------------------

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from isg_agent.capabilities.api_routes import router

# ---- Create the appointments table (managed by core schema, not ensure_tables,
#      but queried by cap5 StaffOpsEngine.assign_staff) -----------------------
_APPOINTMENTS_DDL = """
CREATE TABLE IF NOT EXISTS appointments (
    id           TEXT PRIMARY KEY,
    staff_id     TEXT,
    start_time   TEXT,
    end_time     TEXT,
    scheduled_at TEXT,
    status       TEXT DEFAULT 'scheduled',
    price_cents  INTEGER DEFAULT 0
)
"""
_conn = sqlite3.connect(_tmp_db_path)
_conn.execute(_APPOINTMENTS_DDL)
_conn.commit()
_conn.close()
del _conn
# -----------------------------------------------------------------------------

app = FastAPI()
app.include_router(router)
client = TestClient(app)


# ===========================================================================
# Capability 1 — Proactive Ops
# ===========================================================================


class TestMorningPulse:
    """POST /api/v1/business-ops/pulse"""

    URL = "/api/v1/business-ops/pulse"

    def test_valid_business_id_returns_200(self) -> None:
        resp = client.post(self.URL, json={"business_id": "biz_001"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))

    def test_missing_business_id_returns_422(self) -> None:
        resp = client.post(self.URL, json={})
        assert resp.status_code == 422


class TestCheckTriggers:
    """POST /api/v1/business-ops/triggers/check"""

    URL = "/api/v1/business-ops/triggers/check"

    def test_valid_business_id_returns_200(self) -> None:
        resp = client.post(self.URL, json={"business_id": "biz_001"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))

    def test_missing_business_id_returns_422(self) -> None:
        resp = client.post(self.URL, json={})
        assert resp.status_code == 422


class TestWeeklyIntelligence:
    """GET /api/v1/business-ops/intelligence/weekly"""

    URL = "/api/v1/business-ops/intelligence/weekly"

    def test_valid_query_param_returns_200(self) -> None:
        resp = client.get(self.URL, params={"business_id": "biz_001"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))

    def test_missing_business_id_returns_422(self) -> None:
        resp = client.get(self.URL)
        assert resp.status_code == 422


class TestCreateTrigger:
    """POST /api/v1/business-ops/triggers"""

    URL = "/api/v1/business-ops/triggers"

    def test_valid_trigger_returns_200(self) -> None:
        resp = client.post(
            self.URL,
            json={
                "trigger_type": "no_show",
                "condition_json": '{"threshold": 3}',
            },
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))

    def test_missing_trigger_type_returns_422(self) -> None:
        resp = client.post(self.URL, json={"condition_json": "{}"})
        assert resp.status_code == 422

    def test_missing_condition_json_returns_422(self) -> None:
        resp = client.post(self.URL, json={"trigger_type": "no_show"})
        assert resp.status_code == 422


# ===========================================================================
# Capability 2 — Payments
# ===========================================================================


class TestCreatePaymentLink:
    """POST /api/v1/business-ops/payments/link"""

    URL = "/api/v1/business-ops/payments/link"

    def test_valid_payload_returns_200(self) -> None:
        resp = client.post(
            self.URL,
            json={
                "client_id": "cli_001",
                "appointment_id": "appt_001",
                "amount_cents": 5000,
            },
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))

    def test_missing_client_id_returns_422(self) -> None:
        resp = client.post(
            self.URL,
            json={"appointment_id": "appt_001", "amount_cents": 5000},
        )
        assert resp.status_code == 422

    def test_missing_amount_cents_returns_422(self) -> None:
        resp = client.post(
            self.URL,
            json={"client_id": "cli_001", "appointment_id": "appt_001"},
        )
        assert resp.status_code == 422


class TestRecordPayment:
    """POST /api/v1/business-ops/payments/record"""

    URL = "/api/v1/business-ops/payments/record"

    def test_valid_payload_returns_200(self) -> None:
        resp = client.post(
            self.URL,
            json={
                "link_id": "link_abc",
                "stripe_event": {"type": "payment_intent.succeeded", "id": "evt_001"},
            },
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))

    def test_missing_link_id_returns_422(self) -> None:
        resp = client.post(
            self.URL,
            json={"stripe_event": {"type": "payment_intent.succeeded"}},
        )
        assert resp.status_code == 422

    def test_missing_stripe_event_returns_422(self) -> None:
        resp = client.post(self.URL, json={"link_id": "link_abc"})
        assert resp.status_code == 422


class TestProcessRefund:
    """POST /api/v1/business-ops/payments/refund"""

    URL = "/api/v1/business-ops/payments/refund"

    def test_valid_payload_returns_200(self) -> None:
        resp = client.post(
            self.URL,
            json={
                "payment_id": "pay_001",
                "amount_cents": 2500,
                "reason": "client_request",
            },
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))

    def test_missing_payment_id_returns_422(self) -> None:
        resp = client.post(
            self.URL,
            json={"amount_cents": 2500, "reason": "client_request"},
        )
        assert resp.status_code == 422

    def test_missing_reason_returns_422(self) -> None:
        resp = client.post(
            self.URL,
            json={"payment_id": "pay_001", "amount_cents": 2500},
        )
        assert resp.status_code == 422


class TestRevenueForecast:
    """GET /api/v1/business-ops/revenue/forecast"""

    URL = "/api/v1/business-ops/revenue/forecast"

    def test_valid_query_param_returns_200(self) -> None:
        resp = client.get(self.URL, params={"business_id": "biz_001"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))

    def test_custom_days_param_returns_200(self) -> None:
        resp = client.get(self.URL, params={"business_id": "biz_001", "days": 14})
        assert resp.status_code == 200

    def test_missing_business_id_returns_422(self) -> None:
        resp = client.get(self.URL)
        assert resp.status_code == 422


# ===========================================================================
# Capability 3 — Conversations
# ===========================================================================


class TestHandleInbound:
    """POST /api/v1/business-ops/conversations/inbound"""

    URL = "/api/v1/business-ops/conversations/inbound"

    def test_valid_payload_returns_200(self) -> None:
        resp = client.post(
            self.URL,
            json={
                "client_id": "cli_001",
                "channel": "sms",
                "content": "Hi, I need to book an appointment.",
            },
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))

    def test_missing_client_id_returns_422(self) -> None:
        resp = client.post(
            self.URL,
            json={"channel": "sms", "content": "Hello"},
        )
        assert resp.status_code == 422

    def test_missing_channel_returns_422(self) -> None:
        resp = client.post(
            self.URL,
            json={"client_id": "cli_001", "content": "Hello"},
        )
        assert resp.status_code == 422


class TestSendReply:
    """POST /api/v1/business-ops/conversations/reply"""

    URL = "/api/v1/business-ops/conversations/reply"

    def test_valid_thread_id_returns_200(self) -> None:
        resp = client.post(
            self.URL,
            json={"thread_id": "thread_001", "content": "Thanks for reaching out!"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))

    def test_missing_thread_id_returns_422(self) -> None:
        resp = client.post(self.URL, json={"content": "Hello"})
        assert resp.status_code == 422

    def test_missing_content_returns_422(self) -> None:
        resp = client.post(self.URL, json={"thread_id": "thread_001"})
        assert resp.status_code == 422


class TestGenerateSmartReply:
    """POST /api/v1/business-ops/conversations/smart-reply"""

    URL = "/api/v1/business-ops/conversations/smart-reply"

    def test_valid_payload_returns_200(self) -> None:
        resp = client.post(
            self.URL,
            json={
                "thread_id": "thread_001",
                "inbound_content": "Can I reschedule my appointment?",
            },
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))

    def test_missing_thread_id_returns_422(self) -> None:
        resp = client.post(
            self.URL,
            json={"inbound_content": "Can I reschedule?"},
        )
        assert resp.status_code == 422

    def test_missing_inbound_content_returns_422(self) -> None:
        resp = client.post(self.URL, json={"thread_id": "thread_001"})
        assert resp.status_code == 422


class TestDetectMissed:
    """GET /api/v1/business-ops/conversations/missed"""

    URL = "/api/v1/business-ops/conversations/missed"

    def test_default_threshold_returns_200(self) -> None:
        resp = client.get(self.URL)
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))

    def test_custom_threshold_returns_200(self) -> None:
        resp = client.get(self.URL, params={"hours_threshold": 48})
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))

    def test_invalid_threshold_type_returns_422(self) -> None:
        resp = client.get(self.URL, params={"hours_threshold": "not_an_int"})
        assert resp.status_code == 422


# ===========================================================================
# Capability 4 — Client Intelligence
# ===========================================================================


class TestGetClientIntelligence:
    """GET /api/v1/business-ops/clients/{client_id}/intelligence"""

    def test_valid_client_id_returns_200(self) -> None:
        resp = client.get("/api/v1/business-ops/clients/cli_001/intelligence")
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))

    def test_different_client_id_returns_200(self) -> None:
        resp = client.get("/api/v1/business-ops/clients/cli_xyz/intelligence")
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))


class TestSegmentClients:
    """POST /api/v1/business-ops/clients/segment"""

    URL = "/api/v1/business-ops/clients/segment"

    def test_valid_business_id_returns_200(self) -> None:
        resp = client.post(self.URL, json={"business_id": "biz_001"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))

    def test_missing_business_id_returns_422(self) -> None:
        resp = client.post(self.URL, json={})
        assert resp.status_code == 422


class TestPredictiveRebook:
    """GET /api/v1/business-ops/clients/{client_id}/rebook"""

    def test_valid_client_id_returns_200(self) -> None:
        resp = client.get("/api/v1/business-ops/clients/cli_001/rebook")
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))

    def test_different_client_id_returns_200(self) -> None:
        resp = client.get("/api/v1/business-ops/clients/cli_xyz/rebook")
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))


class TestClientDashboard:
    """GET /api/v1/business-ops/clients/dashboard"""

    URL = "/api/v1/business-ops/clients/dashboard"

    def test_valid_query_param_returns_200(self) -> None:
        resp = client.get(self.URL, params={"business_id": "biz_001"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))

    def test_missing_business_id_returns_422(self) -> None:
        resp = client.get(self.URL)
        assert resp.status_code == 422


# ===========================================================================
# Capability 5 — Staff Ops
# ===========================================================================


class TestAssignStaff:
    """POST /api/v1/business-ops/staff/assign"""

    URL = "/api/v1/business-ops/staff/assign"

    def test_valid_payload_returns_200(self) -> None:
        resp = client.post(
            self.URL,
            json={"staff_id": "staff_001", "appointment_id": "appt_001"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))

    def test_missing_staff_id_returns_422(self) -> None:
        resp = client.post(self.URL, json={"appointment_id": "appt_001"})
        assert resp.status_code == 422

    def test_missing_appointment_id_returns_422(self) -> None:
        resp = client.post(self.URL, json={"staff_id": "staff_001"})
        assert resp.status_code == 422


class TestSetSchedule:
    """PUT /api/v1/business-ops/staff/{staff_id}/schedule"""

    def test_valid_payload_returns_200(self) -> None:
        resp = client.put(
            "/api/v1/business-ops/staff/staff_001/schedule",
            json={"day_of_week": 1, "start_time": "09:00", "end_time": "17:00"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))

    def test_missing_day_of_week_returns_422(self) -> None:
        resp = client.put(
            "/api/v1/business-ops/staff/staff_001/schedule",
            json={"start_time": "09:00", "end_time": "17:00"},
        )
        assert resp.status_code == 422

    def test_missing_start_time_returns_422(self) -> None:
        resp = client.put(
            "/api/v1/business-ops/staff/staff_001/schedule",
            json={"day_of_week": 1, "end_time": "17:00"},
        )
        assert resp.status_code == 422


class TestGetSchedule:
    """GET /api/v1/business-ops/staff/{staff_id}/schedule"""

    def test_valid_staff_id_returns_200(self) -> None:
        resp = client.get("/api/v1/business-ops/staff/staff_001/schedule")
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))

    def test_different_staff_id_returns_200(self) -> None:
        resp = client.get("/api/v1/business-ops/staff/staff_xyz/schedule")
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))


class TestUtilizationReport:
    """GET /api/v1/business-ops/staff/utilization"""

    URL = "/api/v1/business-ops/staff/utilization"

    def test_valid_query_param_returns_200(self) -> None:
        resp = client.get(self.URL, params={"business_id": "biz_001"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))

    def test_custom_period_days_returns_200(self) -> None:
        resp = client.get(self.URL, params={"business_id": "biz_001", "period_days": 14})
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))

    def test_missing_business_id_returns_422(self) -> None:
        resp = client.get(self.URL)
        assert resp.status_code == 422


# ===========================================================================
# Capability 6 — Marketing
# ===========================================================================


class TestCreateCampaign:
    """POST /api/v1/business-ops/campaigns"""

    URL = "/api/v1/business-ops/campaigns"

    def test_valid_payload_returns_200(self) -> None:
        resp = client.post(
            self.URL,
            json={
                "name": "Spring Promo",
                "segment_filter_json": '{"segment": "vip"}',
                "channel": "email",
                "template": "Hi {{name}}, check out our spring deals!",
            },
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))

    def test_missing_name_returns_422(self) -> None:
        resp = client.post(
            self.URL,
            json={
                "segment_filter_json": "{}",
                "channel": "email",
                "template": "Hello",
            },
        )
        assert resp.status_code == 422

    def test_missing_channel_returns_422(self) -> None:
        resp = client.post(
            self.URL,
            json={
                "name": "Test",
                "segment_filter_json": "{}",
                "template": "Hello",
            },
        )
        assert resp.status_code == 422


class TestSendCampaign:
    """POST /api/v1/business-ops/campaigns/{campaign_id}/send"""

    def test_valid_campaign_id_returns_200(self) -> None:
        resp = client.post("/api/v1/business-ops/campaigns/camp_001/send")
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))

    def test_different_campaign_id_returns_200(self) -> None:
        resp = client.post("/api/v1/business-ops/campaigns/camp_xyz/send")
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))


class TestRedeemOffer:
    """POST /api/v1/business-ops/offers/{offer_id}/redeem"""

    def test_valid_offer_id_returns_200(self) -> None:
        resp = client.post("/api/v1/business-ops/offers/offer_001/redeem")
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))

    def test_different_offer_id_returns_200(self) -> None:
        resp = client.post("/api/v1/business-ops/offers/offer_xyz/redeem")
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))


class TestCampaignAnalytics:
    """GET /api/v1/business-ops/campaigns/analytics"""

    URL = "/api/v1/business-ops/campaigns/analytics"

    def test_valid_query_param_returns_200(self) -> None:
        resp = client.get(self.URL, params={"business_id": "biz_001"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))

    def test_custom_days_returns_200(self) -> None:
        resp = client.get(self.URL, params={"business_id": "biz_001", "days": 7})
        assert resp.status_code == 200
        assert isinstance(resp.json(), (dict, list))

    def test_missing_business_id_returns_422(self) -> None:
        resp = client.get(self.URL)
        assert resp.status_code == 422
