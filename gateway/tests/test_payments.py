"""Tests for the payment system: StripeClient, PaymentGate, and API routes.

All Stripe API calls are mocked — no real network traffic.
Tests cover: PaymentResult dataclass, StripeClient methods, PaymentGate
free-tier logic, payment routes, audit routes, trust routes, explain routes,
and config routes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from isg_agent.payments.middleware import PaymentGate
from isg_agent.payments.stripe_client import DEFAULT_AMOUNT_CENTS, PaymentResult, StripeClient


# ===========================================================================
# PaymentResult dataclass
# ===========================================================================


class TestPaymentResult:
    """Tests for PaymentResult dataclass."""

    def test_success_result(self):
        result = PaymentResult(success=True, payment_intent_id="pi_123")
        assert result.success is True
        assert result.payment_intent_id == "pi_123"
        assert result.error is None
        assert result.amount_cents == DEFAULT_AMOUNT_CENTS

    def test_failure_result(self):
        result = PaymentResult(
            success=False, error="Card declined", amount_cents=200
        )
        assert result.success is False
        assert result.error == "Card declined"
        assert result.amount_cents == 200

    def test_default_amount(self):
        result = PaymentResult(success=True)
        assert result.amount_cents == 100  # $1.00

    def test_frozen(self):
        result = PaymentResult(success=True)
        with pytest.raises(AttributeError):
            result.success = False  # type: ignore[misc]


# ===========================================================================
# StripeClient (mocked Stripe SDK)
# ===========================================================================


class TestStripeClient:
    """Tests for StripeClient with mocked stripe module."""

    def test_init_sets_api_key(self):
        with patch("isg_agent.payments.stripe_client.stripe") as mock_stripe:
            client = StripeClient(api_key="sk_test_abc", webhook_secret="whsec_xyz")
            assert mock_stripe.api_key == "sk_test_abc"
            assert client.webhook_secret == "whsec_xyz"

    @pytest.mark.asyncio
    async def test_create_payment_intent(self):
        with patch("isg_agent.payments.stripe_client.stripe") as mock_stripe:
            mock_intent = MagicMock()
            mock_intent.id = "pi_test_123"
            mock_intent.client_secret = "pi_test_123_secret_abc"
            mock_stripe.PaymentIntent.create.return_value = mock_intent

            client = StripeClient(api_key="sk_test_abc")
            result = await client.create_payment_intent(
                user_id="user_1", session_id="sess_1", amount_cents=100
            )

            assert result["client_secret"] == "pi_test_123_secret_abc"
            assert result["payment_intent_id"] == "pi_test_123"
            mock_stripe.PaymentIntent.create.assert_called_once_with(
                amount=100,
                currency="usd",
                metadata={
                    "user_id": "user_1",
                    "session_id": "sess_1",
                    "platform": "isg_agent_1",
                },
            )

    @pytest.mark.asyncio
    async def test_create_payment_intent_custom_amount(self):
        with patch("isg_agent.payments.stripe_client.stripe") as mock_stripe:
            mock_intent = MagicMock()
            mock_intent.id = "pi_test_456"
            mock_intent.client_secret = "secret_456"
            mock_stripe.PaymentIntent.create.return_value = mock_intent

            client = StripeClient(api_key="sk_test_abc")
            result = await client.create_payment_intent(
                user_id="u1", session_id="s1", amount_cents=500
            )
            assert result["payment_intent_id"] == "pi_test_456"
            mock_stripe.PaymentIntent.create.assert_called_once()
            call_kwargs = mock_stripe.PaymentIntent.create.call_args
            assert call_kwargs[1]["amount"] == 500

    @pytest.mark.asyncio
    async def test_verify_payment_succeeded(self):
        with patch("isg_agent.payments.stripe_client.stripe") as mock_stripe:
            mock_intent = MagicMock()
            mock_intent.id = "pi_test_789"
            mock_intent.status = "succeeded"
            mock_intent.amount = 100
            mock_stripe.PaymentIntent.retrieve.return_value = mock_intent

            client = StripeClient(api_key="sk_test_abc")
            result = await client.verify_payment("pi_test_789")

            assert result.success is True
            assert result.payment_intent_id == "pi_test_789"
            assert result.amount_cents == 100
            assert result.error is None

    @pytest.mark.asyncio
    async def test_verify_payment_pending(self):
        with patch("isg_agent.payments.stripe_client.stripe") as mock_stripe:
            mock_intent = MagicMock()
            mock_intent.id = "pi_test_pending"
            mock_intent.status = "requires_payment_method"
            mock_intent.amount = 100
            mock_stripe.PaymentIntent.retrieve.return_value = mock_intent

            client = StripeClient(api_key="sk_test_abc")
            result = await client.verify_payment("pi_test_pending")

            assert result.success is False
            assert "requires_payment_method" in result.error

    @pytest.mark.asyncio
    async def test_verify_payment_api_error(self):
        with patch("isg_agent.payments.stripe_client.stripe") as mock_stripe:
            mock_stripe.StripeError = Exception
            mock_stripe.PaymentIntent.retrieve.side_effect = Exception("API down")

            client = StripeClient(api_key="sk_test_abc")
            result = await client.verify_payment("pi_bad")

            assert result.success is False
            assert "API down" in result.error

    def test_verify_webhook_success(self):
        with patch("isg_agent.payments.stripe_client.stripe") as mock_stripe:
            mock_event = {"type": "payment_intent.succeeded", "id": "evt_123"}
            mock_stripe.Webhook.construct_event.return_value = mock_event

            client = StripeClient(api_key="sk_test_abc", webhook_secret="whsec_test")
            event = client.verify_webhook(
                payload=b'{"test": true}', signature="sig_header"
            )

            assert event["type"] == "payment_intent.succeeded"
            mock_stripe.Webhook.construct_event.assert_called_once()

    def test_verify_webhook_no_secret(self):
        with patch("isg_agent.payments.stripe_client.stripe"):
            client = StripeClient(api_key="sk_test_abc", webhook_secret="")

            with pytest.raises(ValueError, match="Webhook secret not configured"):
                client.verify_webhook(payload=b"data", signature="sig")

    @pytest.mark.asyncio
    async def test_create_customer(self):
        with patch("isg_agent.payments.stripe_client.stripe") as mock_stripe:
            mock_customer = MagicMock()
            mock_customer.id = "cus_test_123"
            mock_stripe.Customer.create.return_value = mock_customer

            client = StripeClient(api_key="sk_test_abc")
            customer_id = await client.create_customer(
                email="test@example.com", metadata={"plan": "basic"}
            )

            assert customer_id == "cus_test_123"
            mock_stripe.Customer.create.assert_called_once_with(
                email="test@example.com", metadata={"plan": "basic"}
            )


# ===========================================================================
# PaymentGate
# ===========================================================================


class TestPaymentGate:
    """Tests for PaymentGate free tier logic."""

    def test_disabled_gate_always_allows(self):
        gate = PaymentGate(stripe_client=None)
        assert not gate.is_enabled
        for _ in range(20):
            allowed, remaining = gate.check_access("user_1")
            assert allowed is True
            gate.record_message("user_1")

    def test_enabled_gate_free_tier(self):
        mock_client = MagicMock(spec=StripeClient)
        gate = PaymentGate(stripe_client=mock_client, free_tier_limit=5)
        assert gate.is_enabled

        # 5 free messages allowed
        for i in range(5):
            allowed, remaining = gate.check_access("user_1")
            assert allowed is True
            assert remaining == 5 - i
            gate.record_message("user_1")

        # 6th message blocked
        allowed, remaining = gate.check_access("user_1")
        assert allowed is False
        assert remaining == 0

    def test_paid_user_always_allowed(self):
        mock_client = MagicMock(spec=StripeClient)
        gate = PaymentGate(stripe_client=mock_client, free_tier_limit=3)

        # Use up free tier
        for _ in range(3):
            gate.record_message("user_1")

        # Should be blocked
        allowed, _ = gate.check_access("user_1")
        assert allowed is False

        # Mark as paid
        gate.mark_paid("user_1")

        # Now allowed
        allowed, remaining = gate.check_access("user_1")
        assert allowed is True
        assert remaining == 0  # Paid users show 0 remaining

    def test_get_usage_free_user(self):
        mock_client = MagicMock(spec=StripeClient)
        gate = PaymentGate(stripe_client=mock_client, free_tier_limit=5)

        gate.record_message("user_1")
        gate.record_message("user_1")
        usage = gate.get_usage("user_1")

        assert usage["total_messages"] == 2
        assert usage["free_remaining"] == 3
        assert usage["payment_required"] is False
        assert usage["is_paid"] is False

    def test_get_usage_exhausted(self):
        mock_client = MagicMock(spec=StripeClient)
        gate = PaymentGate(stripe_client=mock_client, free_tier_limit=2)

        gate.record_message("user_1")
        gate.record_message("user_1")
        usage = gate.get_usage("user_1")

        assert usage["total_messages"] == 2
        assert usage["free_remaining"] == 0
        assert usage["payment_required"] is True

    def test_get_usage_paid_user(self):
        mock_client = MagicMock(spec=StripeClient)
        gate = PaymentGate(stripe_client=mock_client, free_tier_limit=5)

        gate.record_message("user_1")
        gate.mark_paid("user_1")
        usage = gate.get_usage("user_1")

        assert usage["total_messages"] == 1
        assert usage["is_paid"] is True
        assert usage["payment_required"] is False

    def test_reset_user(self):
        mock_client = MagicMock(spec=StripeClient)
        gate = PaymentGate(stripe_client=mock_client, free_tier_limit=5)

        gate.record_message("user_1")
        gate.record_message("user_1")
        gate.mark_paid("user_1")

        gate.reset_user("user_1")
        usage = gate.get_usage("user_1")

        assert usage["total_messages"] == 0
        assert usage["is_paid"] is False
        assert usage["free_remaining"] == 5

    def test_custom_free_tier_limit(self):
        mock_client = MagicMock(spec=StripeClient)
        gate = PaymentGate(stripe_client=mock_client, free_tier_limit=10)

        for i in range(10):
            allowed, remaining = gate.check_access("user_1")
            assert allowed is True
            gate.record_message("user_1")

        allowed, _ = gate.check_access("user_1")
        assert allowed is False

    def test_multiple_users_independent(self):
        mock_client = MagicMock(spec=StripeClient)
        gate = PaymentGate(stripe_client=mock_client, free_tier_limit=3)

        # User 1 exhausts free tier
        for _ in range(3):
            gate.record_message("user_1")

        # User 2 still has free messages
        allowed, remaining = gate.check_access("user_2")
        assert allowed is True
        assert remaining == 3

        # User 1 blocked
        allowed, _ = gate.check_access("user_1")
        assert allowed is False


# ===========================================================================
# API Route Tests (using FastAPI TestClient)
# ===========================================================================


def _create_test_app(
    *,
    auth_user_id: str = "",
    auth_email: str = "",
):
    """Create a test app with all dependencies wired.

    When *auth_user_id* is provided, ``require_auth`` is overridden via
    ``app.dependency_overrides`` so that every ``Depends(require_auth)``
    returns a ``CurrentUser`` without a real JWT.
    """
    from fastapi import FastAPI

    from isg_agent.api.deps import CurrentUser, require_auth
    from isg_agent.api.routes.audit import router as audit_router
    from isg_agent.api.routes.config import router as config_router
    from isg_agent.api.routes.explain import router as explain_router
    from isg_agent.api.routes.payments import router as payments_router
    from isg_agent.api.routes.trust import router as trust_router

    app = FastAPI()
    app.include_router(payments_router)
    app.include_router(audit_router)
    app.include_router(trust_router)
    app.include_router(explain_router)
    app.include_router(config_router)

    if auth_user_id:
        user = CurrentUser(user_id=auth_user_id, email=auth_email)

        async def _override_auth() -> CurrentUser:
            return user

        app.dependency_overrides[require_auth] = _override_auth

    return app


# ---------------------------------------------------------------------------
# Payment Route Tests
# ---------------------------------------------------------------------------


class TestPaymentRoutes:
    """Tests for /api/v1/payments/* endpoints."""

    @pytest.mark.asyncio
    async def test_create_intent_no_stripe(self):
        app = _create_test_app(auth_user_id="test_user", auth_email="test@example.com")
        # No stripe_client on state
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/payments/create-intent",
                json={"amount_cents": 100},
            )
            assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_create_intent_success(self):
        app = _create_test_app(auth_user_id="test_user", auth_email="test@example.com")
        mock_stripe_client = AsyncMock(spec=StripeClient)
        mock_stripe_client.create_payment_intent.return_value = {
            "client_secret": "pi_secret_test",
            "payment_intent_id": "pi_test_001",
        }
        app.state.stripe_client = mock_stripe_client
        app.state.payment_gate = PaymentGate(stripe_client=mock_stripe_client)

        # Mock audit chain
        mock_audit = AsyncMock()
        app.state.audit_chain = mock_audit

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/payments/create-intent",
                json={"amount_cents": 100, "session_id": "sess1"},
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["client_secret"] == "pi_secret_test"
            assert data["payment_intent_id"] == "pi_test_001"
            assert data["amount_cents"] == 100

    @pytest.mark.asyncio
    async def test_create_intent_stripe_error(self):
        app = _create_test_app(auth_user_id="test_user", auth_email="test@example.com")
        mock_stripe_client = AsyncMock(spec=StripeClient)
        mock_stripe_client.create_payment_intent.side_effect = Exception("Stripe error")
        app.state.stripe_client = mock_stripe_client

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/payments/create-intent",
                json={"amount_cents": 100},
            )
            assert resp.status_code == 502

    @pytest.mark.asyncio
    async def test_create_intent_requires_auth(self):
        app = _create_test_app()  # No auth override -> 401
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/payments/create-intent",
                json={"amount_cents": 100},
            )
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_usage_endpoint(self):
        app = _create_test_app(auth_user_id="test_user", auth_email="test@example.com")
        gate = PaymentGate(stripe_client=None)
        gate.record_message("test_user")
        gate.record_message("test_user")
        app.state.payment_gate = gate

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/payments/usage")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_messages"] == 2
            assert data["is_paid"] is False

    @pytest.mark.asyncio
    async def test_webhook_no_stripe(self):
        app = _create_test_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/payments/webhook",
                content=b'{"test": true}',
                headers={"stripe-signature": "sig"},
            )
            assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_webhook_missing_signature(self):
        app = _create_test_app()
        mock_client = MagicMock(spec=StripeClient)
        app.state.stripe_client = mock_client

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/payments/webhook",
                content=b'{"test": true}',
            )
            assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_webhook_invalid_signature(self):
        app = _create_test_app()
        mock_client = MagicMock(spec=StripeClient)
        mock_client.verify_webhook.side_effect = Exception("Invalid signature")
        app.state.stripe_client = mock_client

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/payments/webhook",
                content=b'{"test": true}',
                headers={"stripe-signature": "invalid_sig"},
            )
            assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_webhook_payment_succeeded(self):
        app = _create_test_app()
        mock_client = MagicMock(spec=StripeClient)
        mock_client.verify_webhook.return_value = {
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_test_success",
                    "amount": 100,
                    "metadata": {"user_id": "user_paid"},
                }
            },
        }
        app.state.stripe_client = mock_client

        gate = PaymentGate(stripe_client=mock_client)
        app.state.payment_gate = gate

        mock_audit = AsyncMock()
        app.state.audit_chain = mock_audit

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/payments/webhook",
                content=b'{"type": "payment_intent.succeeded"}',
                headers={"stripe-signature": "valid_sig"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["received"] is True
            assert data["event_type"] == "payment_intent.succeeded"

        # Verify user is marked paid
        usage = gate.get_usage("user_paid")
        assert usage["is_paid"] is True


# ---------------------------------------------------------------------------
# Audit Route Tests
# ---------------------------------------------------------------------------


class TestAuditRoutes:
    """Tests for /api/v1/audit/* endpoints."""

    @pytest.mark.asyncio
    async def test_list_entries(self, tmp_path):
        from isg_agent.core.audit import AuditChain

        app = _create_test_app(auth_user_id="test_user", auth_email="test@example.com")
        chain = AuditChain(db_path=str(tmp_path / "test_audit.db"))
        await chain.record(event_type="test_event", actor="agent_1")
        app.state.audit_chain = chain

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/audit")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] >= 2  # GENESIS + 1 event
            assert len(data["entries"]) >= 2

    @pytest.mark.asyncio
    async def test_list_entries_with_filter(self, tmp_path):
        from isg_agent.core.audit import AuditChain

        app = _create_test_app(auth_user_id="test_user", auth_email="test@example.com")
        chain = AuditChain(db_path=str(tmp_path / "test_audit_filter.db"))
        await chain.record(event_type="alpha", actor="agent_1")
        await chain.record(event_type="beta", actor="agent_2")
        app.state.audit_chain = chain

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/audit?event_type=alpha")
            assert resp.status_code == 200
            data = resp.json()
            for entry in data["entries"]:
                assert entry["event_type"] == "alpha"

    @pytest.mark.asyncio
    async def test_verify_chain(self, tmp_path):
        from isg_agent.core.audit import AuditChain

        app = _create_test_app(auth_user_id="test_user", auth_email="test@example.com")
        chain = AuditChain(db_path=str(tmp_path / "test_audit_verify.db"))
        await chain.record(event_type="test", actor="system")
        app.state.audit_chain = chain

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/audit/verify")
            assert resp.status_code == 200
            data = resp.json()
            assert data["valid"] is True
            assert data["length"] >= 2

    @pytest.mark.asyncio
    async def test_audit_requires_auth(self):
        app = _create_test_app()  # No auth override -> 401
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/audit")
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_audit_no_chain(self):
        app = _create_test_app(auth_user_id="test_user", auth_email="test@example.com")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/audit")
            assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Trust Route Tests
# ---------------------------------------------------------------------------


class TestTrustRoutes:
    """Tests for /api/v1/trust/* endpoints."""

    @pytest.mark.asyncio
    async def test_list_trust_scores(self):
        from isg_agent.core.trust_ledger import TrustLedger

        app = _create_test_app(auth_user_id="test_user", auth_email="test@example.com")
        ledger = TrustLedger()
        ledger.record_success("agent_1", weight=1.0, context="test")
        app.state.trust_ledger = ledger

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/trust")
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] >= 1
            assert data["scores"][0]["entity_id"] == "agent_1"

    @pytest.mark.asyncio
    async def test_get_specific_trust_score(self):
        from isg_agent.core.trust_ledger import TrustLedger

        app = _create_test_app(auth_user_id="test_user", auth_email="test@example.com")
        ledger = TrustLedger()
        ledger.record_success("agent_alpha", context="passed test")
        ledger.record_success("agent_alpha", context="passed test 2")
        app.state.trust_ledger = ledger

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/trust/agent_alpha")
            assert resp.status_code == 200
            data = resp.json()
            assert data["entity_id"] == "agent_alpha"
            assert data["total_successes"] == 2
            assert data["score"] > 0.5

    @pytest.mark.asyncio
    async def test_get_unknown_entity_creates_neutral(self):
        from isg_agent.core.trust_ledger import TrustLedger

        app = _create_test_app(auth_user_id="test_user", auth_email="test@example.com")
        ledger = TrustLedger()
        app.state.trust_ledger = ledger

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/trust/new_agent")
            assert resp.status_code == 200
            data = resp.json()
            assert data["entity_id"] == "new_agent"
            assert data["score"] == 0.5

    @pytest.mark.asyncio
    async def test_trust_requires_auth(self):
        app = _create_test_app()  # No auth override -> 401
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/trust")
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_trust_no_ledger(self):
        app = _create_test_app(auth_user_id="test_user", auth_email="test@example.com")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/trust")
            assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Explain Route Tests
# ---------------------------------------------------------------------------


class TestExplainRoutes:
    """Tests for /api/v1/explain/* endpoints."""

    @pytest.mark.asyncio
    async def test_list_traces(self):
        from isg_agent.core.explain import ExplainEngine

        app = _create_test_app(auth_user_id="test_user", auth_email="test@example.com")
        engine = ExplainEngine()
        trace = engine.create_trace(trace_id="trace_001")
        trace.add_step(decision="Allow", reason="Low risk", component="governance")
        trace.finalize(outcome="PROCEED")
        app.state.explain_engine = engine

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/explain")
            assert resp.status_code == 200
            data = resp.json()
            assert "trace_001" in data["trace_ids"]
            assert data["count"] == 1

    @pytest.mark.asyncio
    async def test_get_trace(self):
        from isg_agent.core.explain import ExplainEngine

        app = _create_test_app(auth_user_id="test_user", auth_email="test@example.com")
        engine = ExplainEngine()
        trace = engine.create_trace(trace_id="trace_002")
        trace.add_step(
            decision="Blocked",
            reason="High risk",
            component="security",
            evidence={"risk_level": "HIGH"},
        )
        trace.finalize(outcome="HALT")
        app.state.explain_engine = engine

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/explain/trace_002")
            assert resp.status_code == 200
            data = resp.json()
            assert data["trace_id"] == "trace_002"
            assert data["is_finalized"] is True
            assert data["outcome"] == "HALT"
            assert len(data["steps"]) == 1
            assert data["steps"][0]["decision"] == "Blocked"
            assert "HIGH" in data["steps"][0]["evidence"]["risk_level"]
            assert "trace_002" in data["human_readable"]

    @pytest.mark.asyncio
    async def test_get_trace_not_found(self):
        from isg_agent.core.explain import ExplainEngine

        app = _create_test_app(auth_user_id="test_user", auth_email="test@example.com")
        engine = ExplainEngine()
        app.state.explain_engine = engine

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/explain/nonexistent")
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_explain_requires_auth(self):
        app = _create_test_app()  # No auth override -> 401
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/explain")
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_explain_no_engine(self):
        app = _create_test_app(auth_user_id="test_user", auth_email="test@example.com")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/explain")
            assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Config Route Tests
# ---------------------------------------------------------------------------


class TestConfigRoutes:
    """Tests for /api/v1/config endpoint."""

    @pytest.mark.asyncio
    async def test_get_config(self):
        from isg_agent.config import Settings

        app = _create_test_app(auth_user_id="test_user", auth_email="test@example.com")
        settings = Settings(
            host="0.0.0.0",
            port=8420,
            log_level="INFO",
            max_sessions=10,
            secret_key="test-secret-key-never-exposed",
            openai_api_key="sk-test-openai-key",
        )
        app.state.settings = settings
        app.state.stripe_client = None

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/config")
            assert resp.status_code == 200
            data = resp.json()

            # Non-sensitive values are present
            assert data["port"] == 8420
            assert data["log_level"] == "INFO"
            assert data["max_sessions"] == 10
            assert "openai" in data["providers"]
            assert data["stripe_configured"] is False

            # Secrets must NOT be in the response
            response_text = resp.text
            assert "test-secret-key-never-exposed" not in response_text
            assert "sk-test-openai-key" not in response_text

    @pytest.mark.asyncio
    async def test_config_shows_stripe_configured(self):
        from isg_agent.config import Settings

        app = _create_test_app(auth_user_id="test_user", auth_email="test@example.com")
        mock_stripe = MagicMock(spec=StripeClient)
        app.state.stripe_client = mock_stripe
        app.state.settings = Settings(secret_key="s")

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/config")
            assert resp.status_code == 200
            data = resp.json()
            assert data["stripe_configured"] is True

    @pytest.mark.asyncio
    async def test_config_requires_auth(self):
        app = _create_test_app()  # No auth override -> 401
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/config")
            assert resp.status_code == 401
