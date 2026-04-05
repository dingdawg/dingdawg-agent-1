"""Stripe webhook integration tests — focused gap coverage.

test_stripe_billing.py covers the primary happy path for each event type.
This file covers the defensive/edge cases that are NOT in test_stripe_billing.py:

  - ValueError from verify_webhook (no secret configured) → 400 with detail
  - checkout.session.completed with missing user_id in metadata → 200, no crash
  - checkout.session.completed with no UsageMeter on app state → 200, no crash
  - checkout.session.completed with no PaymentGate on app state → 200, no crash
  - invoice.paid with no audit chain → 200, no crash
  - invoice.payment_failed with no audit chain → 200, no crash
  - customer.subscription.deleted extracts stripe_subscription_id from data.object.id
  - customer.subscription.deleted with no user_id in metadata → actor falls back to customer id
  - customer.subscription.deleted with no audit chain → 200, no crash
  - payment_intent.succeeded with no user_id in metadata → 200, gate NOT called
  - payment_intent.succeeded with no PaymentGate on app state → 200, no crash
  - payment_intent.succeeded with no audit chain → 200, no crash
  - Idempotency: checkout.session.completed processed twice → single subscription record
  - All three paid plans (starter, pro, enterprise) via checkout → correct plan in DB
  - Response body always contains received=True and event_type for every handled event
  - invoice.payment_succeeded (alternate spelling, unhandled) → 200, not crash
  - Webhook ValueError path (vs generic exception) → 400 with ValueError message text

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
# Shared helpers (mirrors test_stripe_billing.py — local copies to keep
# tests self-contained and not import across test files)
# ===========================================================================


def _create_test_app(
    *,
    stripe_client: Any = None,
    usage_meter: Any = None,
    payment_gate: Any = None,
    audit_chain: Any = None,
):
    """Create a minimal FastAPI app with payment routes wired.

    No auth override — webhook endpoint does not require JWT.
    """
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
    """Return a mock StripeClient that passes spec checks."""
    client = MagicMock(spec=StripeClient)
    client.webhook_secret = webhook_secret
    return client


def _webhook_event(event_type: str, data_object: dict) -> dict:
    """Build a fake Stripe webhook event dict."""
    return {
        "id": f"evt_{event_type.replace('.', '_')}",
        "type": event_type,
        "data": {"object": data_object},
    }


_WEBHOOK_BYTES = b'{"fake": "payload"}'
_WEBHOOK_SIG = "t=1700000000,v1=abc123"
_WEBHOOK_HEADERS = {"stripe-signature": _WEBHOOK_SIG}


# ===========================================================================
# Signature verification edge cases
# ===========================================================================


class TestWebhookSignatureVerification:
    """Tests for the verify_webhook path — ValueError and generic exception."""

    @pytest.mark.asyncio
    async def test_value_error_from_verify_webhook_returns_400(self):
        """When verify_webhook raises ValueError, returns 400 with generic message (no internal leak)."""
        mock_client = _make_stripe_client()
        # Simulate the "Webhook secret not configured" ValueError
        mock_client.verify_webhook.side_effect = ValueError("Webhook secret not configured")

        app = _create_test_app(stripe_client=mock_client)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/payments/webhook",
                content=_WEBHOOK_BYTES,
                headers=_WEBHOOK_HEADERS,
            )

        assert resp.status_code == 400
        # Internal error details must NOT be forwarded — expect generic message (MEDIUM-02 fix)
        assert resp.json()["detail"] == "Invalid webhook request"

    @pytest.mark.asyncio
    async def test_generic_exception_from_verify_returns_400_with_invalid_message(self):
        """When verify_webhook raises a generic Exception (bad sig), returns 400."""
        mock_client = _make_stripe_client()
        mock_client.verify_webhook.side_effect = RuntimeError("Signature mismatch")

        app = _create_test_app(stripe_client=mock_client)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/payments/webhook",
                content=_WEBHOOK_BYTES,
                headers=_WEBHOOK_HEADERS,
            )

        assert resp.status_code == 400
        assert "Invalid webhook signature" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_empty_signature_header_value_returns_400(self):
        """Empty string Stripe-Signature header (present but blank) returns 400.

        The route checks `if not signature` — an empty header string is falsy.
        """
        mock_client = _make_stripe_client()
        app = _create_test_app(stripe_client=mock_client)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/payments/webhook",
                content=_WEBHOOK_BYTES,
                headers={"stripe-signature": ""},
            )

        assert resp.status_code == 400
        assert "Missing" in resp.json()["detail"]


# ===========================================================================
# checkout.session.completed — defensive / edge cases
# ===========================================================================


class TestCheckoutSessionCompletedEdgeCases:
    """Edge cases for the checkout.session.completed event handler."""

    @pytest.mark.asyncio
    async def test_missing_user_id_in_metadata_no_crash(self, tmp_path):
        """checkout.session.completed with no user_id in metadata → 200, no DB write."""
        db_path = str(tmp_path / "test.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        mock_client = _make_stripe_client()
        mock_gate = PaymentGate(stripe_client=None)

        # No user_id in metadata
        event_data = {
            "id": "cs_no_user",
            "customer": "cus_abc",
            "subscription": "sub_abc",
            "metadata": {
                "agent_id": "agent_abc",
                "plan": "starter",
                # user_id intentionally omitted
            },
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "checkout.session.completed", event_data
        )

        app = _create_test_app(
            stripe_client=mock_client,
            usage_meter=meter,
            payment_gate=mock_gate,
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/payments/webhook",
                content=_WEBHOOK_BYTES,
                headers=_WEBHOOK_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["received"] is True
        # No subscription created because user_id was blank — meter has nothing
        sub = await meter.get_user_subscription(agent_id="agent_abc", user_id="")
        assert sub is None

    @pytest.mark.asyncio
    async def test_no_usage_meter_on_state_no_crash(self):
        """checkout.session.completed with no UsageMeter on app state → 200, no crash."""
        mock_client = _make_stripe_client()
        mock_gate = PaymentGate(stripe_client=None)

        event_data = {
            "id": "cs_no_meter",
            "customer": "cus_nm",
            "subscription": "sub_nm",
            "metadata": {
                "user_id": "user_nm",
                "agent_id": "agent_nm",
                "plan": "pro",
            },
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "checkout.session.completed", event_data
        )

        # No usage_meter passed — meter is None
        app = _create_test_app(
            stripe_client=mock_client,
            payment_gate=mock_gate,
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/payments/webhook",
                content=_WEBHOOK_BYTES,
                headers=_WEBHOOK_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["event_type"] == "checkout.session.completed"
        # User still marked paid in gate (gate path fires independently)
        assert mock_gate.get_usage("user_nm")["is_paid"] is True

    @pytest.mark.asyncio
    async def test_no_payment_gate_on_state_no_crash(self, tmp_path):
        """checkout.session.completed with no PaymentGate on app state → 200, no crash.

        The route calls _get_payment_gate which falls back to a disabled gate.
        """
        db_path = str(tmp_path / "test.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        mock_client = _make_stripe_client()
        mock_audit = AsyncMock()

        event_data = {
            "id": "cs_no_gate",
            "customer": "cus_ng",
            "subscription": "sub_ng",
            "metadata": {
                "user_id": "user_ng",
                "agent_id": "agent_ng",
                "plan": "enterprise",
            },
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "checkout.session.completed", event_data
        )

        # No payment_gate passed
        app = _create_test_app(
            stripe_client=mock_client,
            usage_meter=meter,
            audit_chain=mock_audit,
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/payments/webhook",
                content=_WEBHOOK_BYTES,
                headers=_WEBHOOK_HEADERS,
            )

        assert resp.status_code == 200
        # Subscription should still be created in DB
        sub = await meter.get_user_subscription(agent_id="agent_ng", user_id="user_ng")
        assert sub is not None
        assert sub["plan"] == "enterprise"

    @pytest.mark.asyncio
    async def test_checkout_completed_all_three_paid_plans(self, tmp_path):
        """checkout.session.completed correctly records starter, pro, and enterprise plans."""
        db_path = str(tmp_path / "plans.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        for plan in ("starter", "pro", "enterprise"):
            mock_client = _make_stripe_client()
            mock_gate = PaymentGate(stripe_client=None)

            event_data = {
                "id": f"cs_{plan}",
                "customer": f"cus_{plan}",
                "subscription": f"sub_{plan}",
                "metadata": {
                    "user_id": f"user_{plan}",
                    "agent_id": f"agent_{plan}",
                    "plan": plan,
                },
            }
            # Use a per-plan unique event ID to avoid idempotency deduplication
            # across iterations (all three plans fire the same event type).
            webhook_event = {
                "id": f"evt_checkout_session_completed_{plan}",
                "type": "checkout.session.completed",
                "data": {"object": event_data},
            }
            mock_client.verify_webhook.return_value = webhook_event

            app = _create_test_app(
                stripe_client=mock_client,
                usage_meter=meter,
                payment_gate=mock_gate,
            )

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/payments/webhook",
                    content=_WEBHOOK_BYTES,
                    headers=_WEBHOOK_HEADERS,
                )

            assert resp.status_code == 200, f"Failed for plan={plan}"

            sub = await meter.get_user_subscription(
                agent_id=f"agent_{plan}", user_id=f"user_{plan}"
            )
            assert sub is not None, f"No subscription for plan={plan}"
            assert sub["plan"] == plan, f"Plan mismatch: expected={plan} got={sub['plan']}"
            # Verify actions_included matches pricing tier
            expected_actions = PRICING_TIERS[plan]["actions_included"]
            assert sub["actions_included"] == expected_actions, (
                f"actions_included mismatch for {plan}: "
                f"expected={expected_actions} got={sub['actions_included']}"
            )

    @pytest.mark.asyncio
    async def test_checkout_completed_idempotency_no_duplicate_subscription(self, tmp_path):
        """Same checkout.session.completed processed twice → single subscription record.

        The UsageMeter uses INSERT OR REPLACE (UNIQUE on agent_id, user_id),
        so the second call updates in place — no duplicate row, same plan.
        """
        db_path = str(tmp_path / "idempotent.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        mock_client = _make_stripe_client()
        mock_gate = PaymentGate(stripe_client=None)

        event_data = {
            "id": "cs_idem",
            "customer": "cus_idem",
            "subscription": "sub_idem",
            "metadata": {
                "user_id": "user_idem",
                "agent_id": "agent_idem",
                "plan": "starter",
            },
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "checkout.session.completed", event_data
        )

        app = _create_test_app(
            stripe_client=mock_client,
            usage_meter=meter,
            payment_gate=mock_gate,
        )

        # First call
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp1 = await client.post(
                "/api/v1/payments/webhook",
                content=_WEBHOOK_BYTES,
                headers=_WEBHOOK_HEADERS,
            )
        assert resp1.status_code == 200

        # Second call — same event replayed
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp2 = await client.post(
                "/api/v1/payments/webhook",
                content=_WEBHOOK_BYTES,
                headers=_WEBHOOK_HEADERS,
            )
        assert resp2.status_code == 200

        # Exactly one subscription row for agent_idem / user_idem
        sub = await meter.get_user_subscription(
            agent_id="agent_idem", user_id="user_idem"
        )
        assert sub is not None
        assert sub["plan"] == "starter"

        # Verify uniqueness at DB level
        import aiosqlite
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                "SELECT COUNT(*) AS cnt FROM usage_subscriptions "
                "WHERE agent_id = 'agent_idem' AND user_id = 'user_idem'"
            )
        assert rows[0]["cnt"] == 1, "Duplicate subscription rows created — idempotency broken"


# ===========================================================================
# invoice.paid — edge cases
# ===========================================================================


class TestInvoicePaidEdgeCases:
    """Edge cases for invoice.paid handler."""

    @pytest.mark.asyncio
    async def test_invoice_paid_no_audit_chain_no_crash(self):
        """invoice.paid with no audit_chain on state → 200, no crash."""
        mock_client = _make_stripe_client()
        event_data = {
            "id": "in_noa",
            "customer": "cus_noa",
            "subscription": "sub_noa",
            "amount_paid": 7900,
        }
        mock_client.verify_webhook.return_value = _webhook_event("invoice.paid", event_data)

        # No audit_chain
        app = _create_test_app(stripe_client=mock_client)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/payments/webhook",
                content=_WEBHOOK_BYTES,
                headers=_WEBHOOK_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["received"] is True
        assert resp.json()["event_type"] == "invoice.paid"

    @pytest.mark.asyncio
    async def test_invoice_paid_response_shape(self):
        """invoice.paid response always has received=True and event_type."""
        mock_client = _make_stripe_client()
        mock_audit = AsyncMock()
        event_data = {
            "id": "in_shape",
            "customer": "cus_shape",
            "subscription": "sub_shape",
            "amount_paid": 2900,
        }
        mock_client.verify_webhook.return_value = _webhook_event("invoice.paid", event_data)

        app = _create_test_app(stripe_client=mock_client, audit_chain=mock_audit)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/payments/webhook",
                content=_WEBHOOK_BYTES,
                headers=_WEBHOOK_HEADERS,
            )

        body = resp.json()
        assert body["received"] is True
        assert body["event_type"] == "invoice.paid"


# ===========================================================================
# invoice.payment_failed — edge cases
# ===========================================================================


class TestInvoicePaymentFailedEdgeCases:
    """Edge cases for invoice.payment_failed handler."""

    @pytest.mark.asyncio
    async def test_invoice_payment_failed_no_audit_chain_no_crash(self):
        """invoice.payment_failed with no audit chain → 200, no crash."""
        mock_client = _make_stripe_client()
        event_data = {
            "id": "in_fail_noa",
            "customer": "cus_fnoa",
            "subscription": "sub_fnoa",
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "invoice.payment_failed", event_data
        )

        # No audit_chain
        app = _create_test_app(stripe_client=mock_client)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/payments/webhook",
                content=_WEBHOOK_BYTES,
                headers=_WEBHOOK_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["event_type"] == "invoice.payment_failed"

    @pytest.mark.asyncio
    async def test_invoice_payment_failed_response_shape(self):
        """invoice.payment_failed response always has received=True and event_type."""
        mock_client = _make_stripe_client()
        mock_audit = AsyncMock()
        event_data = {"id": "in_fs", "customer": "cus_fs", "subscription": "sub_fs"}
        mock_client.verify_webhook.return_value = _webhook_event(
            "invoice.payment_failed", event_data
        )

        app = _create_test_app(stripe_client=mock_client, audit_chain=mock_audit)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/payments/webhook",
                content=_WEBHOOK_BYTES,
                headers=_WEBHOOK_HEADERS,
            )

        body = resp.json()
        assert body["received"] is True
        assert body["event_type"] == "invoice.payment_failed"


# ===========================================================================
# customer.subscription.deleted — edge cases
# ===========================================================================


class TestSubscriptionDeletedEdgeCases:
    """Edge cases for customer.subscription.deleted handler."""

    @pytest.mark.asyncio
    async def test_subscription_id_extracted_from_data_object_id(self):
        """The subscription ID is taken from data.object.id, NOT data.object.subscription."""
        mock_client = _make_stripe_client()
        mock_audit = AsyncMock()

        # The route uses: stripe_subscription_id = data_object.get("id", "")
        event_data = {
            "id": "sub_from_id_field",   # This is the subscription ID
            "customer": "cus_del_id",
            "metadata": {"user_id": "user_del_id", "agent_id": "agent_del_id"},
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "customer.subscription.deleted", event_data
        )

        app = _create_test_app(stripe_client=mock_client, audit_chain=mock_audit)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/payments/webhook",
                content=_WEBHOOK_BYTES,
                headers=_WEBHOOK_HEADERS,
            )

        assert resp.status_code == 200
        # Verify audit was called with the correct subscription ID from .id field
        mock_audit.record.assert_called_once()
        call_kwargs = mock_audit.record.call_args[1]
        assert call_kwargs["details"]["stripe_subscription_id"] == "sub_from_id_field"

    @pytest.mark.asyncio
    async def test_subscription_deleted_without_user_id_uses_customer_as_actor(self):
        """When metadata has no user_id, audit actor falls back to stripe_customer_id."""
        mock_client = _make_stripe_client()
        mock_audit = AsyncMock()

        event_data = {
            "id": "sub_no_user",
            "customer": "cus_no_user",
            "metadata": {},  # No user_id, no agent_id
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "customer.subscription.deleted", event_data
        )

        app = _create_test_app(stripe_client=mock_client, audit_chain=mock_audit)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/payments/webhook",
                content=_WEBHOOK_BYTES,
                headers=_WEBHOOK_HEADERS,
            )

        assert resp.status_code == 200
        mock_audit.record.assert_called_once()
        call_kwargs = mock_audit.record.call_args[1]
        # actor should be cus_no_user when user_id is blank
        assert call_kwargs["actor"] == "cus_no_user"

    @pytest.mark.asyncio
    async def test_subscription_deleted_no_audit_chain_no_crash(self):
        """customer.subscription.deleted with no audit chain → 200, no crash."""
        mock_client = _make_stripe_client()
        event_data = {
            "id": "sub_noa_del",
            "customer": "cus_noa_del",
            "metadata": {"user_id": "user_noa_del", "agent_id": "agent_noa_del"},
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "customer.subscription.deleted", event_data
        )

        # No audit_chain
        app = _create_test_app(stripe_client=mock_client)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/payments/webhook",
                content=_WEBHOOK_BYTES,
                headers=_WEBHOOK_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["event_type"] == "customer.subscription.deleted"


# ===========================================================================
# payment_intent.succeeded — edge cases (legacy path)
# ===========================================================================


class TestPaymentIntentSucceededEdgeCases:
    """Edge cases for the legacy payment_intent.succeeded handler."""

    @pytest.mark.asyncio
    async def test_no_user_id_in_metadata_gate_not_called(self):
        """payment_intent.succeeded without user_id → 200, PaymentGate.mark_paid not called."""
        mock_client = _make_stripe_client()
        mock_gate = MagicMock(spec=PaymentGate)

        event_data = {
            "id": "pi_no_user",
            "amount": 100,
            "metadata": {},  # No user_id
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "payment_intent.succeeded", event_data
        )

        app = _create_test_app(stripe_client=mock_client, payment_gate=mock_gate)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/payments/webhook",
                content=_WEBHOOK_BYTES,
                headers=_WEBHOOK_HEADERS,
            )

        assert resp.status_code == 200
        # mark_paid must NOT have been called — no user_id to mark
        mock_gate.mark_paid.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_payment_gate_on_state_no_crash(self):
        """payment_intent.succeeded with no PaymentGate on state → 200, no crash.

        _get_payment_gate returns a disabled fallback gate when state has none.
        """
        mock_client = _make_stripe_client()
        mock_audit = AsyncMock()

        event_data = {
            "id": "pi_no_gate",
            "amount": 100,
            "metadata": {"user_id": "user_ng2"},
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "payment_intent.succeeded", event_data
        )

        # No payment_gate on state
        app = _create_test_app(stripe_client=mock_client, audit_chain=mock_audit)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/payments/webhook",
                content=_WEBHOOK_BYTES,
                headers=_WEBHOOK_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["event_type"] == "payment_intent.succeeded"

    @pytest.mark.asyncio
    async def test_payment_intent_succeeded_no_audit_chain_no_crash(self):
        """payment_intent.succeeded with no audit chain → 200, no crash."""
        mock_client = _make_stripe_client()
        mock_gate = PaymentGate(stripe_client=None)

        event_data = {
            "id": "pi_no_audit",
            "amount": 100,
            "metadata": {"user_id": "user_na"},
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "payment_intent.succeeded", event_data
        )

        # No audit_chain
        app = _create_test_app(stripe_client=mock_client, payment_gate=mock_gate)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/payments/webhook",
                content=_WEBHOOK_BYTES,
                headers=_WEBHOOK_HEADERS,
            )

        assert resp.status_code == 200
        # Gate still marks user paid even without audit chain
        assert mock_gate.get_usage("user_na")["is_paid"] is True

    @pytest.mark.asyncio
    async def test_payment_intent_succeeded_audit_details_include_amount(self):
        """payment_intent.succeeded passes amount and payment_intent_id to audit."""
        mock_client = _make_stripe_client()
        mock_gate = PaymentGate(stripe_client=None)
        mock_audit = AsyncMock()

        event_data = {
            "id": "pi_audit_check",
            "amount": 500,
            "metadata": {"user_id": "user_audit"},
        }
        mock_client.verify_webhook.return_value = _webhook_event(
            "payment_intent.succeeded", event_data
        )

        app = _create_test_app(
            stripe_client=mock_client,
            payment_gate=mock_gate,
            audit_chain=mock_audit,
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/payments/webhook",
                content=_WEBHOOK_BYTES,
                headers=_WEBHOOK_HEADERS,
            )

        assert resp.status_code == 200
        mock_audit.record.assert_called_once()
        call_kwargs = mock_audit.record.call_args[1]
        assert call_kwargs["event_type"] == "payment_succeeded"
        assert call_kwargs["actor"] == "user_audit"
        assert call_kwargs["details"]["payment_intent_id"] == "pi_audit_check"
        assert call_kwargs["details"]["amount"] == 500


# ===========================================================================
# Unknown / unhandled event types
# ===========================================================================


class TestUnhandledEventTypes:
    """Unhandled event types must return 200 (Stripe requirement)."""

    @pytest.mark.asyncio
    async def test_invoice_payment_succeeded_alternate_spelling_is_unknown(self):
        """invoice.payment_succeeded (alternate misspelling) is not handled → 200, no crash.

        The system handles invoice.paid — not invoice.payment_succeeded.
        This confirms the handler is exact-match, not prefix-match.
        """
        mock_client = _make_stripe_client()
        mock_client.verify_webhook.return_value = _webhook_event(
            "invoice.payment_succeeded",  # This is NOT in the handler switch
            {"id": "obj_alt", "customer": "cus_alt"},
        )

        app = _create_test_app(stripe_client=mock_client)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/payments/webhook",
                content=_WEBHOOK_BYTES,
                headers=_WEBHOOK_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["received"] is True
        assert resp.json()["event_type"] == "invoice.payment_succeeded"

    @pytest.mark.asyncio
    async def test_customer_created_event_is_graceful(self):
        """customer.created is not handled → 200, not crash."""
        mock_client = _make_stripe_client()
        mock_client.verify_webhook.return_value = _webhook_event(
            "customer.created",
            {"id": "cus_new_evt", "email": "new@example.com"},
        )

        app = _create_test_app(stripe_client=mock_client)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/payments/webhook",
                content=_WEBHOOK_BYTES,
                headers=_WEBHOOK_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["event_type"] == "customer.created"

    @pytest.mark.asyncio
    async def test_customer_subscription_updated_event_is_graceful(self):
        """customer.subscription.updated is not handled → 200, not crash."""
        mock_client = _make_stripe_client()
        mock_client.verify_webhook.return_value = _webhook_event(
            "customer.subscription.updated",
            {"id": "sub_upd", "customer": "cus_upd", "status": "active"},
        )

        app = _create_test_app(stripe_client=mock_client)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/payments/webhook",
                content=_WEBHOOK_BYTES,
                headers=_WEBHOOK_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["event_type"] == "customer.subscription.updated"

    @pytest.mark.asyncio
    async def test_charge_succeeded_event_is_graceful(self):
        """charge.succeeded is not handled → 200, not crash."""
        mock_client = _make_stripe_client()
        mock_client.verify_webhook.return_value = _webhook_event(
            "charge.succeeded",
            {"id": "ch_ok", "amount": 100, "customer": "cus_charge"},
        )

        app = _create_test_app(stripe_client=mock_client)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/payments/webhook",
                content=_WEBHOOK_BYTES,
                headers=_WEBHOOK_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["event_type"] == "charge.succeeded"


# ===========================================================================
# Response contract validation
# ===========================================================================


class TestWebhookResponseContract:
    """Verify the WebhookResponse shape is consistent across all event types."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "event_type, data_object",
        [
            (
                "checkout.session.completed",
                {
                    "id": "cs_contract",
                    "customer": "cus_ct",
                    "subscription": "sub_ct",
                    "metadata": {"user_id": "u_ct", "agent_id": "a_ct", "plan": "starter"},
                },
            ),
            (
                "invoice.paid",
                {"id": "in_ct", "customer": "cus_ct", "subscription": "sub_ct", "amount_paid": 100},
            ),
            (
                "invoice.payment_failed",
                {"id": "in_fail_ct", "customer": "cus_ct", "subscription": "sub_ct"},
            ),
            (
                "customer.subscription.deleted",
                {"id": "sub_ct", "customer": "cus_ct", "metadata": {}},
            ),
            (
                "payment_intent.succeeded",
                {"id": "pi_ct", "amount": 100, "metadata": {}},
            ),
            (
                "totally.unknown.event",
                {"id": "unk_ct"},
            ),
        ],
    )
    async def test_response_always_has_received_and_event_type(
        self, event_type: str, data_object: dict, tmp_path
    ):
        """Every handled (and unhandled) event must return received=True + event_type."""
        db_path = str(tmp_path / f"contract_{event_type.replace('.', '_')}.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        mock_client = _make_stripe_client()
        mock_gate = PaymentGate(stripe_client=None)
        mock_audit = AsyncMock()

        mock_client.verify_webhook.return_value = _webhook_event(event_type, data_object)

        app = _create_test_app(
            stripe_client=mock_client,
            usage_meter=meter,
            payment_gate=mock_gate,
            audit_chain=mock_audit,
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/payments/webhook",
                content=_WEBHOOK_BYTES,
                headers=_WEBHOOK_HEADERS,
            )

        assert resp.status_code == 200, f"event_type={event_type} returned {resp.status_code}"
        body = resp.json()
        assert body["received"] is True, f"received missing for event_type={event_type}"
        assert body["event_type"] == event_type, (
            f"event_type mismatch: expected={event_type} got={body['event_type']}"
        )
