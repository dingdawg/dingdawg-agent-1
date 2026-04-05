"""Tests for the three newly added Stripe webhook event handlers.

Covers events that were absent from test_stripe_billing.py and
test_stripe_webhooks.py:

  - customer.subscription.created
      → upserts subscription via UsageMeter.create_subscription
      → marks user paid in PaymentGate
      → records audit event
      → idempotent on replay
      → graceful when user_id missing
      → graceful when meter absent

  - customer.subscription.updated
      → updates plan via UsageMeter.update_subscription_plan_by_stripe_id
      → falls back to create_subscription when row missing (race)
      → deactivates subscription when stripe_status = canceled
      → deactivates subscription when stripe_status = unpaid
      → records audit event
      → graceful when meter absent
      → graceful when audit chain absent

  - invoice.payment_succeeded
      → calls reactivate_subscription_by_stripe_id
      → records audit event
      → graceful when no subscription row
      → graceful when meter absent
      → graceful when audit chain absent

All Stripe API calls are mocked — zero network traffic.
Pattern follows test_stripe_billing.py exactly.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from isg_agent.payments.middleware import PaymentGate
from isg_agent.payments.stripe_client import StripeClient
from isg_agent.payments.usage_meter import PRICING_TIERS, UsageMeter


# ===========================================================================
# Shared helpers
# ===========================================================================


def _create_test_app(
    *,
    stripe_client: Any = None,
    usage_meter: Any = None,
    payment_gate: Any = None,
    audit_chain: Any = None,
):
    """Create a minimal FastAPI app with payment routes wired (no JWT required)."""
    from fastapi import FastAPI

    from isg_agent.api.routes.payments import router as payments_router

    app = FastAPI()
    app.include_router(payments_router)

    if stripe_client is not None:
        app.state.stripe_client = stripe_client
    if usage_meter is not None:
        app.state.usage_meter = usage_meter
    if payment_gate is not None:
        app.state.payment_gate = payment_gate
    if audit_chain is not None:
        app.state.audit_chain = audit_chain

    return app


def _make_stripe_client(webhook_secret: str = "whsec_test") -> MagicMock:
    """Return a mock StripeClient."""
    client = MagicMock(spec=StripeClient)
    client.webhook_secret = webhook_secret
    return client


def _webhook_event(event_type: str, data_object: dict, event_id: str = "") -> dict:
    """Build a fake Stripe webhook event dict."""
    eid = event_id or f"evt_{event_type.replace('.', '_')}"
    return {
        "id": eid,
        "type": event_type,
        "data": {"object": data_object},
    }


_WEBHOOK_BYTES = b'{"fake": "payload"}'
_WEBHOOK_HEADERS = {"stripe-signature": "t=1700000000,v1=abc123"}


async def _post_webhook(app, event_dict: dict) -> Any:
    """Helper: POST a webhook event and return the httpx response."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(
            "/api/v1/payments/webhook",
            content=_WEBHOOK_BYTES,
            headers=_WEBHOOK_HEADERS,
        )


# ===========================================================================
# customer.subscription.created
# ===========================================================================


class TestSubscriptionCreated:
    """Tests for customer.subscription.created handler."""

    @pytest.mark.asyncio
    async def test_creates_subscription_in_db(self, tmp_path):
        """customer.subscription.created upserts a subscription row in the DB."""
        db_path = str(tmp_path / "sub_created.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        mock_client = _make_stripe_client()
        mock_gate = PaymentGate(stripe_client=None)

        event_data = {
            "id": "sub_created_001",
            "customer": "cus_created_001",
            "status": "active",
            "metadata": {
                "user_id": "user_created_001",
                "agent_id": "agent_created_001",
                "plan": "pro",
            },
            "items": {"data": []},
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "customer.subscription.created", event_data
        )

        app = _create_test_app(
            stripe_client=mock_client,
            usage_meter=meter,
            payment_gate=mock_gate,
        )

        resp = await _post_webhook(app, event_data)
        assert resp.status_code == 200
        assert resp.json()["received"] is True
        assert resp.json()["event_type"] == "customer.subscription.created"

        sub = await meter.get_user_subscription(
            agent_id="agent_created_001", user_id="user_created_001"
        )
        assert sub is not None
        assert sub["plan"] == "pro"
        assert sub["stripe_subscription_id"] == "sub_created_001"
        assert sub["stripe_customer_id"] == "cus_created_001"
        assert sub["is_active"] == 1

    @pytest.mark.asyncio
    async def test_marks_user_paid_in_gate(self, tmp_path):
        """customer.subscription.created marks user paid in PaymentGate."""
        db_path = str(tmp_path / "gate_created.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        mock_client = _make_stripe_client()
        mock_gate = PaymentGate(stripe_client=None)

        event_data = {
            "id": "sub_gate_001",
            "customer": "cus_gate_001",
            "status": "active",
            "metadata": {
                "user_id": "user_gate_created",
                "agent_id": "agent_gate_001",
                "plan": "starter",
            },
            "items": {"data": []},
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "customer.subscription.created", event_data
        )

        app = _create_test_app(
            stripe_client=mock_client,
            usage_meter=meter,
            payment_gate=mock_gate,
        )

        resp = await _post_webhook(app, event_data)
        assert resp.status_code == 200
        assert mock_gate.get_usage("user_gate_created")["is_paid"] is True

    @pytest.mark.asyncio
    async def test_records_audit_event(self, tmp_path):
        """customer.subscription.created records an audit entry."""
        db_path = str(tmp_path / "audit_created.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        mock_client = _make_stripe_client()
        mock_audit = AsyncMock()

        event_data = {
            "id": "sub_audit_001",
            "customer": "cus_audit_001",
            "status": "active",
            "metadata": {
                "user_id": "user_audit_created",
                "agent_id": "agent_audit_001",
                "plan": "enterprise",
            },
            "items": {"data": []},
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "customer.subscription.created", event_data
        )

        app = _create_test_app(
            stripe_client=mock_client,
            usage_meter=meter,
            audit_chain=mock_audit,
        )

        resp = await _post_webhook(app, event_data)
        assert resp.status_code == 200

        mock_audit.record.assert_called_once()
        call_kwargs = mock_audit.record.call_args[1]
        assert call_kwargs["event_type"] == "subscription_created_webhook"
        assert call_kwargs["actor"] == "user_audit_created"
        assert call_kwargs["details"]["stripe_subscription_id"] == "sub_audit_001"
        assert call_kwargs["details"]["plan"] == "enterprise"

    @pytest.mark.asyncio
    async def test_idempotent_on_replay(self, tmp_path):
        """customer.subscription.created processed twice → single DB row."""
        db_path = str(tmp_path / "idem_created.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        mock_client = _make_stripe_client()
        mock_gate = PaymentGate(stripe_client=None)

        event_data = {
            "id": "sub_idem_001",
            "customer": "cus_idem_001",
            "status": "active",
            "metadata": {
                "user_id": "user_idem_created",
                "agent_id": "agent_idem_001",
                "plan": "starter",
            },
            "items": {"data": []},
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "customer.subscription.created", event_data
        )

        app = _create_test_app(
            stripe_client=mock_client,
            usage_meter=meter,
            payment_gate=mock_gate,
        )

        # First delivery
        resp1 = await _post_webhook(app, event_data)
        assert resp1.status_code == 200

        # Second delivery — same event_id → idempotency guard fires
        resp2 = await _post_webhook(app, event_data)
        assert resp2.status_code == 200

        import aiosqlite
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                "SELECT COUNT(*) AS cnt FROM usage_subscriptions "
                "WHERE agent_id='agent_idem_001' AND user_id='user_idem_created'"
            )
        assert rows[0]["cnt"] == 1, "Duplicate subscription row created — idempotency broken"

    @pytest.mark.asyncio
    async def test_graceful_when_user_id_missing(self, tmp_path):
        """customer.subscription.created without user_id → 200, no DB write."""
        db_path = str(tmp_path / "no_user_created.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        mock_client = _make_stripe_client()
        event_data = {
            "id": "sub_no_user_001",
            "customer": "cus_no_user_001",
            "status": "active",
            "metadata": {"agent_id": "agent_no_user", "plan": "pro"},  # user_id missing
            "items": {"data": []},
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "customer.subscription.created", event_data
        )

        app = _create_test_app(stripe_client=mock_client, usage_meter=meter)

        resp = await _post_webhook(app, event_data)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_graceful_when_meter_absent(self):
        """customer.subscription.created with no UsageMeter → 200, no crash."""
        mock_client = _make_stripe_client()
        event_data = {
            "id": "sub_no_meter_001",
            "customer": "cus_no_meter",
            "status": "active",
            "metadata": {"user_id": "user_no_meter", "agent_id": "a", "plan": "starter"},
            "items": {"data": []},
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "customer.subscription.created", event_data
        )

        app = _create_test_app(stripe_client=mock_client)  # No meter

        resp = await _post_webhook(app, event_data)
        assert resp.status_code == 200
        assert resp.json()["event_type"] == "customer.subscription.created"

    @pytest.mark.asyncio
    async def test_plan_resolved_from_items_when_not_in_metadata(self, tmp_path):
        """Plan resolved from items[0].price.metadata.plan when absent from metadata."""
        db_path = str(tmp_path / "items_plan.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        mock_client = _make_stripe_client()
        mock_gate = PaymentGate(stripe_client=None)

        event_data = {
            "id": "sub_items_001",
            "customer": "cus_items_001",
            "status": "active",
            "metadata": {
                "user_id": "user_items_001",
                "agent_id": "agent_items_001",
                # plan NOT set here
            },
            "items": {
                "data": [
                    {
                        "price": {
                            "metadata": {"plan": "enterprise"},
                        }
                    }
                ]
            },
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "customer.subscription.created", event_data
        )

        app = _create_test_app(
            stripe_client=mock_client,
            usage_meter=meter,
            payment_gate=mock_gate,
        )

        resp = await _post_webhook(app, event_data)
        assert resp.status_code == 200

        sub = await meter.get_user_subscription(
            agent_id="agent_items_001", user_id="user_items_001"
        )
        assert sub is not None
        assert sub["plan"] == "enterprise"


# ===========================================================================
# customer.subscription.updated
# ===========================================================================


class TestSubscriptionUpdated:
    """Tests for customer.subscription.updated handler."""

    @pytest.mark.asyncio
    async def test_updates_plan_in_db(self, tmp_path):
        """customer.subscription.updated with active status updates plan tier."""
        db_path = str(tmp_path / "sub_updated.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        # Seed a starter subscription first
        await meter.create_subscription(
            agent_id="agent_upd_001",
            user_id="user_upd_001",
            plan="starter",
            stripe_customer_id="cus_upd_001",
            stripe_subscription_id="sub_upd_001",
        )

        mock_client = _make_stripe_client()
        event_data = {
            "id": "sub_upd_001",
            "customer": "cus_upd_001",
            "status": "active",
            "metadata": {
                "user_id": "user_upd_001",
                "agent_id": "agent_upd_001",
                "plan": "pro",
            },
            "items": {"data": []},
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "customer.subscription.updated", event_data
        )

        app = _create_test_app(stripe_client=mock_client, usage_meter=meter)

        resp = await _post_webhook(app, event_data)
        assert resp.status_code == 200
        assert resp.json()["event_type"] == "customer.subscription.updated"

        sub = await meter.get_user_subscription(
            agent_id="agent_upd_001", user_id="user_upd_001"
        )
        assert sub is not None
        assert sub["plan"] == "pro"
        assert sub["actions_included"] == PRICING_TIERS["pro"]["actions_included"]

    @pytest.mark.asyncio
    async def test_deactivates_on_canceled_status(self, tmp_path):
        """customer.subscription.updated with status=canceled deactivates the sub."""
        db_path = str(tmp_path / "sub_canceled.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        await meter.create_subscription(
            agent_id="agent_cancel_001",
            user_id="user_cancel_001",
            plan="pro",
            stripe_customer_id="cus_cancel_001",
            stripe_subscription_id="sub_cancel_001",
        )

        mock_client = _make_stripe_client()
        event_data = {
            "id": "sub_cancel_001",
            "customer": "cus_cancel_001",
            "status": "canceled",
            "metadata": {"user_id": "user_cancel_001", "agent_id": "agent_cancel_001"},
            "items": {"data": []},
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "customer.subscription.updated", event_data
        )

        app = _create_test_app(stripe_client=mock_client, usage_meter=meter)

        resp = await _post_webhook(app, event_data)
        assert resp.status_code == 200

        sub = await meter.get_user_subscription(
            agent_id="agent_cancel_001", user_id="user_cancel_001"
        )
        # is_active=0 means get_user_subscription returns None (filters active only)
        assert sub is None

    @pytest.mark.asyncio
    async def test_deactivates_on_unpaid_status(self, tmp_path):
        """customer.subscription.updated with status=unpaid deactivates the sub."""
        db_path = str(tmp_path / "sub_unpaid.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        await meter.create_subscription(
            agent_id="agent_unpaid_001",
            user_id="user_unpaid_001",
            plan="starter",
            stripe_customer_id="cus_unpaid_001",
            stripe_subscription_id="sub_unpaid_001",
        )

        mock_client = _make_stripe_client()
        event_data = {
            "id": "sub_unpaid_001",
            "customer": "cus_unpaid_001",
            "status": "unpaid",
            "metadata": {"user_id": "user_unpaid_001", "agent_id": "agent_unpaid_001"},
            "items": {"data": []},
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "customer.subscription.updated", event_data
        )

        app = _create_test_app(stripe_client=mock_client, usage_meter=meter)

        resp = await _post_webhook(app, event_data)
        assert resp.status_code == 200

        sub = await meter.get_user_subscription(
            agent_id="agent_unpaid_001", user_id="user_unpaid_001"
        )
        assert sub is None

    @pytest.mark.asyncio
    async def test_creates_row_when_missing_on_update(self, tmp_path):
        """subscription.updated with no existing row and user_id → upsert via create_subscription."""
        db_path = str(tmp_path / "sub_upsert.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        mock_client = _make_stripe_client()
        event_data = {
            "id": "sub_upsert_001",
            "customer": "cus_upsert_001",
            "status": "active",
            "metadata": {
                "user_id": "user_upsert_001",
                "agent_id": "agent_upsert_001",
                "plan": "enterprise",
            },
            "items": {"data": []},
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "customer.subscription.updated", event_data
        )

        app = _create_test_app(stripe_client=mock_client, usage_meter=meter)

        resp = await _post_webhook(app, event_data)
        assert resp.status_code == 200

        sub = await meter.get_user_subscription(
            agent_id="agent_upsert_001", user_id="user_upsert_001"
        )
        assert sub is not None
        assert sub["plan"] == "enterprise"

    @pytest.mark.asyncio
    async def test_records_audit_event(self, tmp_path):
        """customer.subscription.updated records an audit entry."""
        db_path = str(tmp_path / "audit_upd.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        await meter.create_subscription(
            agent_id="agent_audit_upd",
            user_id="user_audit_upd",
            plan="starter",
            stripe_customer_id="cus_audit_upd",
            stripe_subscription_id="sub_audit_upd",
        )

        mock_client = _make_stripe_client()
        mock_audit = AsyncMock()

        event_data = {
            "id": "sub_audit_upd",
            "customer": "cus_audit_upd",
            "status": "active",
            "metadata": {
                "user_id": "user_audit_upd",
                "agent_id": "agent_audit_upd",
                "plan": "pro",
            },
            "items": {"data": []},
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "customer.subscription.updated", event_data
        )

        app = _create_test_app(
            stripe_client=mock_client,
            usage_meter=meter,
            audit_chain=mock_audit,
        )

        resp = await _post_webhook(app, event_data)
        assert resp.status_code == 200

        mock_audit.record.assert_called_once()
        call_kwargs = mock_audit.record.call_args[1]
        assert call_kwargs["event_type"] == "subscription_updated_webhook"
        assert call_kwargs["details"]["stripe_subscription_id"] == "sub_audit_upd"
        assert call_kwargs["details"]["plan"] == "pro"
        assert call_kwargs["details"]["stripe_status"] == "active"

    @pytest.mark.asyncio
    async def test_graceful_when_meter_absent(self):
        """customer.subscription.updated with no UsageMeter → 200, no crash."""
        mock_client = _make_stripe_client()
        event_data = {
            "id": "sub_no_meter_upd",
            "customer": "cus_no_meter_upd",
            "status": "active",
            "metadata": {"user_id": "u", "agent_id": "a", "plan": "pro"},
            "items": {"data": []},
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "customer.subscription.updated", event_data
        )

        app = _create_test_app(stripe_client=mock_client)  # No meter

        resp = await _post_webhook(app, event_data)
        assert resp.status_code == 200
        assert resp.json()["event_type"] == "customer.subscription.updated"

    @pytest.mark.asyncio
    async def test_graceful_when_audit_chain_absent(self, tmp_path):
        """customer.subscription.updated with no audit chain → 200, no crash."""
        db_path = str(tmp_path / "no_audit_upd.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        mock_client = _make_stripe_client()
        event_data = {
            "id": "sub_no_audit_upd",
            "customer": "cus_no_audit_upd",
            "status": "active",
            "metadata": {"user_id": "u_na_upd", "agent_id": "a_na", "plan": "starter"},
            "items": {"data": []},
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "customer.subscription.updated", event_data
        )

        app = _create_test_app(stripe_client=mock_client, usage_meter=meter)  # No audit

        resp = await _post_webhook(app, event_data)
        assert resp.status_code == 200


# ===========================================================================
# invoice.payment_succeeded
# ===========================================================================


class TestInvoicePaymentSucceeded:
    """Tests for invoice.payment_succeeded handler."""

    @pytest.mark.asyncio
    async def test_reactivates_deactivated_subscription(self, tmp_path):
        """invoice.payment_succeeded calls reactivate_subscription_by_stripe_id."""
        db_path = str(tmp_path / "pay_succ.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        # Create then deactivate a subscription
        await meter.create_subscription(
            agent_id="agent_ps_001",
            user_id="user_ps_001",
            plan="pro",
            stripe_customer_id="cus_ps_001",
            stripe_subscription_id="sub_ps_001",
        )
        await meter.deactivate_subscription_by_stripe_id("sub_ps_001")

        mock_client = _make_stripe_client()
        event_data = {
            "id": "in_ps_001",
            "customer": "cus_ps_001",
            "subscription": "sub_ps_001",
            "amount_paid": 7999,
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "invoice.payment_succeeded", event_data
        )

        app = _create_test_app(stripe_client=mock_client, usage_meter=meter)

        resp = await _post_webhook(app, event_data)
        assert resp.status_code == 200
        assert resp.json()["event_type"] == "invoice.payment_succeeded"

        # Subscription must be active again
        sub = await meter.get_user_subscription(
            agent_id="agent_ps_001", user_id="user_ps_001"
        )
        assert sub is not None
        assert sub["is_active"] == 1

    @pytest.mark.asyncio
    async def test_records_audit_event(self):
        """invoice.payment_succeeded records audit with amount_paid."""
        mock_client = _make_stripe_client()
        mock_audit = AsyncMock()

        event_data = {
            "id": "in_audit_ps",
            "customer": "cus_audit_ps",
            "subscription": "sub_audit_ps",
            "amount_paid": 4999,
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "invoice.payment_succeeded", event_data
        )

        app = _create_test_app(stripe_client=mock_client, audit_chain=mock_audit)

        resp = await _post_webhook(app, event_data)
        assert resp.status_code == 200

        mock_audit.record.assert_called_once()
        call_kwargs = mock_audit.record.call_args[1]
        assert call_kwargs["event_type"] == "invoice_payment_succeeded"
        assert call_kwargs["actor"] == "cus_audit_ps"
        assert call_kwargs["details"]["invoice_id"] == "in_audit_ps"
        assert call_kwargs["details"]["amount_paid"] == 4999
        assert call_kwargs["details"]["stripe_subscription_id"] == "sub_audit_ps"

    @pytest.mark.asyncio
    async def test_graceful_when_no_subscription_row(self, tmp_path):
        """invoice.payment_succeeded with no matching sub row → 200, no crash."""
        db_path = str(tmp_path / "no_row_ps.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        mock_client = _make_stripe_client()
        event_data = {
            "id": "in_no_row_ps",
            "customer": "cus_no_row_ps",
            "subscription": "sub_no_row_ps",
            "amount_paid": 100,
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "invoice.payment_succeeded", event_data
        )

        app = _create_test_app(stripe_client=mock_client, usage_meter=meter)

        resp = await _post_webhook(app, event_data)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_graceful_when_meter_absent(self):
        """invoice.payment_succeeded with no UsageMeter → 200, no crash."""
        mock_client = _make_stripe_client()
        event_data = {
            "id": "in_no_meter_ps",
            "customer": "cus_no_meter_ps",
            "subscription": "sub_no_meter_ps",
            "amount_paid": 100,
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "invoice.payment_succeeded", event_data
        )

        app = _create_test_app(stripe_client=mock_client)  # No meter

        resp = await _post_webhook(app, event_data)
        assert resp.status_code == 200
        assert resp.json()["event_type"] == "invoice.payment_succeeded"

    @pytest.mark.asyncio
    async def test_graceful_when_audit_chain_absent(self, tmp_path):
        """invoice.payment_succeeded with no audit chain → 200, no crash."""
        db_path = str(tmp_path / "no_audit_ps.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        mock_client = _make_stripe_client()
        event_data = {
            "id": "in_no_audit_ps",
            "customer": "cus_no_audit_ps",
            "subscription": "sub_no_audit_ps",
            "amount_paid": 100,
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "invoice.payment_succeeded", event_data
        )

        app = _create_test_app(stripe_client=mock_client, usage_meter=meter)  # No audit

        resp = await _post_webhook(app, event_data)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_idempotent_on_replay(self, tmp_path):
        """invoice.payment_succeeded processed twice → single processed_webhook_events row."""
        db_path = str(tmp_path / "idem_ps.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        mock_client = _make_stripe_client()
        event_data = {
            "id": "in_idem_ps",
            "customer": "cus_idem_ps",
            "subscription": "sub_idem_ps",
            "amount_paid": 100,
        }
        # Use fixed event_id to trigger idempotency guard on second call
        mock_client.verify_webhook.return_value = _webhook_event(
            "invoice.payment_succeeded", event_data, event_id="evt_idem_ps_fixed"
        )

        app = _create_test_app(stripe_client=mock_client, usage_meter=meter)

        resp1 = await _post_webhook(app, event_data)
        assert resp1.status_code == 200

        resp2 = await _post_webhook(app, event_data)
        assert resp2.status_code == 200

        import aiosqlite
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                "SELECT COUNT(*) AS cnt FROM processed_webhook_events "
                "WHERE event_id='evt_idem_ps_fixed'"
            )
        assert rows[0]["cnt"] == 1, "Duplicate webhook event row — idempotency broken"
