"""Tests for the usage-based billing system: UsageMeter, pricing tiers,
skill executor hook, and API endpoints.

All Stripe API calls are mocked -- no real network traffic.
Tests cover: table creation, usage recording, free tier logic, subscription
management, monthly summaries, history, overage billing, blocked status,
Stripe reporting, post-execute hook wiring, and API endpoints.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from isg_agent.payments.usage_meter import PRICING_TIERS, UsageMeter


# ===========================================================================
# Pricing Tiers
# ===========================================================================


class TestPricingTiers:
    """Tests for the pricing tier constants."""

    def test_free_tier_exists(self):
        assert "free" in PRICING_TIERS
        assert PRICING_TIERS["free"]["price_cents_monthly"] == 0
        assert PRICING_TIERS["free"]["actions_included"] == 50
        assert PRICING_TIERS["free"]["overage_blocked"] is True

    def test_starter_tier(self):
        tier = PRICING_TIERS["starter"]
        assert tier["price_cents_monthly"] == 4999  # $49.99/mo
        assert tier["actions_included"] == 500
        assert tier["overage_cents"] == 100  # $1.00/action
        assert tier["overage_blocked"] is False

    def test_pro_tier(self):
        tier = PRICING_TIERS["pro"]
        assert tier["price_cents_monthly"] == 7999  # $79.99/mo
        assert tier["actions_included"] == 2000
        assert tier["overage_cents"] == 100  # $1.00/action
        assert tier["overage_blocked"] is False

    def test_enterprise_tier(self):
        tier = PRICING_TIERS["enterprise"]
        assert tier["price_cents_monthly"] == 49900  # $499/mo
        assert tier["actions_included"] == -1  # Unlimited
        assert tier["overage_cents"] == 100  # $1.00/action
        assert tier["overage_blocked"] is False

    def test_all_tiers_have_required_keys(self):
        required_keys = {
            "name", "price_cents_monthly", "actions_included",
            "overage_cents", "overage_blocked",
        }
        for plan, tier in PRICING_TIERS.items():
            for key in required_keys:
                assert key in tier, f"Missing {key!r} in {plan!r} tier"


# ===========================================================================
# UsageMeter — Table Initialisation
# ===========================================================================


class TestUsageMeterInit:
    """Tests for UsageMeter table creation."""

    @pytest.mark.asyncio
    async def test_init_tables_creates_schema(self, tmp_path):
        db_path = str(tmp_path / "test_usage.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        # Verify tables exist by querying them
        import aiosqlite

        async with aiosqlite.connect(db_path) as db:
            # usage_records
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='usage_records'"
            )
            assert await cursor.fetchone() is not None

            # usage_subscriptions
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='usage_subscriptions'"
            )
            assert await cursor.fetchone() is not None

            # usage_summary
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='usage_summary'"
            )
            assert await cursor.fetchone() is not None

    @pytest.mark.asyncio
    async def test_init_tables_idempotent(self, tmp_path):
        db_path = str(tmp_path / "test_idem.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()
        await meter.init_tables()  # Should not raise

    @pytest.mark.asyncio
    async def test_default_config(self, tmp_path):
        meter = UsageMeter(db_path=str(tmp_path / "t.db"))
        assert meter._price_per_action_cents == 100
        assert meter._free_tier_limit == 50
        assert meter._stripe is None

    @pytest.mark.asyncio
    async def test_custom_config(self, tmp_path):
        mock_stripe = MagicMock()
        meter = UsageMeter(
            db_path=str(tmp_path / "t.db"),
            stripe_client=mock_stripe,
            price_per_action=2.50,
            free_tier_limit=10,
        )
        assert meter._price_per_action_cents == 250
        assert meter._free_tier_limit == 10
        assert meter._stripe is mock_stripe


# ===========================================================================
# UsageMeter — Usage Recording (free tier, no subscription)
# ===========================================================================


class TestUsageRecording:
    """Tests for recording usage and free tier logic."""

    @pytest.mark.asyncio
    async def test_record_usage_within_free_tier(self, tmp_path):
        db_path = str(tmp_path / "test_free.db")
        meter = UsageMeter(db_path=db_path, free_tier_limit=5)
        await meter.init_tables()

        result = await meter.record_usage(
            agent_id="agent_1",
            user_id="user_1",
            skill_name="send_email",
            action="send",
        )

        assert result["status"] == "free_tier"
        assert result["amount_cents"] == 0
        assert result["remaining_free"] == 4
        assert result["plan"] == "free"
        assert "usage_id" in result

    @pytest.mark.asyncio
    async def test_free_tier_countdown(self, tmp_path):
        db_path = str(tmp_path / "test_countdown.db")
        meter = UsageMeter(db_path=db_path, free_tier_limit=3)
        await meter.init_tables()

        # 3 free actions
        for i in range(3):
            result = await meter.record_usage("agent_1", "user_1", "skill", "act")
            assert result["status"] == "free_tier"
            assert result["remaining_free"] == 2 - i

    @pytest.mark.asyncio
    async def test_free_tier_blocked_after_limit(self, tmp_path):
        db_path = str(tmp_path / "test_blocked.db")
        meter = UsageMeter(db_path=db_path, free_tier_limit=2)
        await meter.init_tables()

        # Use up free tier
        await meter.record_usage("agent_1", "user_1", "skill", "act")
        await meter.record_usage("agent_1", "user_1", "skill", "act")

        # Next should be blocked (free plan blocks overage)
        result = await meter.record_usage("agent_1", "user_1", "skill", "act")
        assert result["status"] == "blocked"
        assert result["amount_cents"] == 0
        assert result["remaining_free"] == 0

    @pytest.mark.asyncio
    async def test_different_agents_independent(self, tmp_path):
        db_path = str(tmp_path / "test_agents.db")
        meter = UsageMeter(db_path=db_path, free_tier_limit=2)
        await meter.init_tables()

        # Agent 1 uses up free tier
        await meter.record_usage("agent_1", "user_1", "skill", "act")
        await meter.record_usage("agent_1", "user_1", "skill", "act")
        result_blocked = await meter.record_usage("agent_1", "user_1", "skill", "act")
        assert result_blocked["status"] == "blocked"

        # Agent 2 still has free tier
        result_free = await meter.record_usage("agent_2", "user_1", "skill", "act")
        assert result_free["status"] == "free_tier"
        assert result_free["remaining_free"] == 1


# ===========================================================================
# UsageMeter — Subscriptions
# ===========================================================================


class TestSubscriptions:
    """Tests for subscription creation and usage with subscriptions."""

    @pytest.mark.asyncio
    async def test_create_subscription(self, tmp_path):
        db_path = str(tmp_path / "test_sub.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        sub = await meter.create_subscription(
            agent_id="agent_1",
            user_id="user_1",
            plan="starter",
        )

        assert sub["plan"] == "starter"
        assert sub["actions_included"] == 500
        assert sub["price_cents_monthly"] == 4999  # $49.99/mo
        assert sub["is_active"] is True

    @pytest.mark.asyncio
    async def test_invalid_plan_raises(self, tmp_path):
        db_path = str(tmp_path / "test_invalid.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        with pytest.raises(ValueError, match="Invalid plan"):
            await meter.create_subscription("agent_1", "user_1", "ultra_mega")

    @pytest.mark.asyncio
    async def test_starter_plan_overage(self, tmp_path):
        db_path = str(tmp_path / "test_overage.db")
        meter = UsageMeter(db_path=db_path, free_tier_limit=50)
        await meter.init_tables()

        # Create starter subscription with 500 included
        await meter.create_subscription("agent_1", "user_1", "starter")

        # Use up all 500 included actions
        for _ in range(500):
            result = await meter.record_usage("agent_1", "user_1", "skill", "act")
            assert result["status"] == "free_tier"

        # 501st action should be billed at overage rate ($1.00 = 100 cents)
        result = await meter.record_usage("agent_1", "user_1", "skill", "act")
        assert result["status"] == "recorded"
        assert result["amount_cents"] == 100  # $1.00 overage
        assert result["remaining_free"] == 0

    @pytest.mark.asyncio
    async def test_pro_plan_overage_rate(self, tmp_path):
        db_path = str(tmp_path / "test_pro_overage.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        await meter.create_subscription("agent_1", "user_1", "pro")

        # Burn through 2000 included actions
        for _ in range(2000):
            await meter.record_usage("agent_1", "user_1", "skill", "act")

        # Overage at $1.00
        result = await meter.record_usage("agent_1", "user_1", "skill", "act")
        assert result["status"] == "recorded"
        assert result["amount_cents"] == 100  # $1.00 overage

    @pytest.mark.asyncio
    async def test_enterprise_unlimited(self, tmp_path):
        db_path = str(tmp_path / "test_enterprise.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        await meter.create_subscription("agent_1", "user_1", "enterprise")

        # Even after many actions, still free_tier (unlimited)
        for _ in range(100):
            result = await meter.record_usage("agent_1", "user_1", "skill", "act")
            assert result["status"] == "free_tier"
            assert result["amount_cents"] == 0
            assert result["remaining_free"] == -1

    @pytest.mark.asyncio
    async def test_get_user_subscription(self, tmp_path):
        db_path = str(tmp_path / "test_get_sub.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        # No subscription initially
        sub = await meter.get_user_subscription("agent_1", "user_1")
        assert sub is None

        # Create one
        await meter.create_subscription("agent_1", "user_1", "pro")
        sub = await meter.get_user_subscription("agent_1", "user_1")
        assert sub is not None
        assert sub["plan"] == "pro"

    @pytest.mark.asyncio
    async def test_update_subscription(self, tmp_path):
        db_path = str(tmp_path / "test_update_sub.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        # Create free, then upgrade to pro
        await meter.create_subscription("agent_1", "user_1", "free")
        sub = await meter.get_user_subscription("agent_1", "user_1")
        assert sub["plan"] == "free"

        await meter.create_subscription("agent_1", "user_1", "pro")
        sub = await meter.get_user_subscription("agent_1", "user_1")
        assert sub["plan"] == "pro"


# ===========================================================================
# UsageMeter — Summaries
# ===========================================================================


class TestUsageSummary:
    """Tests for monthly usage summaries."""

    @pytest.mark.asyncio
    async def test_get_empty_summary(self, tmp_path):
        db_path = str(tmp_path / "test_empty_summary.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        summary = await meter.get_usage_summary("agent_1")
        assert summary["total_actions"] == 0
        assert summary["free_actions"] == 0
        assert summary["billed_actions"] == 0
        assert summary["total_amount_cents"] == 0
        assert summary["plan"] == "free"
        assert summary["remaining_free"] == 50

    @pytest.mark.asyncio
    async def test_summary_after_usage(self, tmp_path):
        db_path = str(tmp_path / "test_summary.db")
        meter = UsageMeter(db_path=db_path, free_tier_limit=3)
        await meter.init_tables()

        await meter.record_usage("agent_1", "user_1", "skill_a", "act")
        await meter.record_usage("agent_1", "user_1", "skill_b", "act")

        summary = await meter.get_usage_summary("agent_1")
        assert summary["total_actions"] == 2
        assert summary["free_actions"] == 2
        assert summary["billed_actions"] == 0
        assert summary["remaining_free"] == 1

    @pytest.mark.asyncio
    async def test_summary_with_billing(self, tmp_path):
        db_path = str(tmp_path / "test_billed_summary.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        # Subscribe to starter (500 included, $1.00 overage)
        await meter.create_subscription("agent_1", "user_1", "starter")

        # Use up 500 + 2 overage
        for _ in range(500):
            await meter.record_usage("agent_1", "user_1", "skill", "act")

        await meter.record_usage("agent_1", "user_1", "skill", "act")
        await meter.record_usage("agent_1", "user_1", "skill", "act")

        summary = await meter.get_usage_summary("agent_1")
        assert summary["total_actions"] == 502
        assert summary["free_actions"] == 500
        assert summary["billed_actions"] == 2
        assert summary["total_amount_cents"] == 200  # 2 * 100 cents ($1.00 each)

    @pytest.mark.asyncio
    async def test_usage_history(self, tmp_path):
        db_path = str(tmp_path / "test_history.db")
        meter = UsageMeter(db_path=db_path, free_tier_limit=100)
        await meter.init_tables()

        # Record some usage (all in current month)
        for _ in range(5):
            await meter.record_usage("agent_1", "user_1", "skill", "act")

        history = await meter.get_usage_history("agent_1", months=6)
        assert len(history) == 1
        assert history[0]["total_actions"] == 5

    @pytest.mark.asyncio
    async def test_empty_history(self, tmp_path):
        db_path = str(tmp_path / "test_empty_hist.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        history = await meter.get_usage_history("agent_1")
        assert history == []


# ===========================================================================
# UsageMeter — Stripe Reporting
# ===========================================================================


class TestStripeReporting:
    """Tests for Stripe usage reporting."""

    @pytest.mark.asyncio
    async def test_report_no_stripe(self, tmp_path):
        db_path = str(tmp_path / "test_no_stripe.db")
        meter = UsageMeter(db_path=db_path)
        await meter.init_tables()

        result = await meter.report_to_stripe("usage_123", "cus_123")
        assert result["reported"] is False
        assert result["reason"] == "stripe_not_configured"

    @pytest.mark.asyncio
    async def test_report_stripe_error(self, tmp_path):
        db_path = str(tmp_path / "test_stripe_err.db")
        mock_stripe = MagicMock()
        meter = UsageMeter(db_path=db_path, stripe_client=mock_stripe)
        await meter.init_tables()

        # Record a usage first
        result = await meter.record_usage("agent_1", "user_1", "skill", "act")
        usage_id = result["usage_id"]

        with patch("isg_agent.payments.usage_meter.stripe") as mock_stripe_mod:
            mock_stripe_mod.billing.MeterEvent.create.side_effect = Exception("API error")
            report = await meter.report_to_stripe(usage_id, "cus_123")
            assert report["reported"] is False
            assert "API error" in report["error"]

    @pytest.mark.asyncio
    async def test_report_stripe_success(self, tmp_path):
        db_path = str(tmp_path / "test_stripe_ok.db")
        mock_stripe = MagicMock()
        meter = UsageMeter(db_path=db_path, stripe_client=mock_stripe)
        await meter.init_tables()

        # Record a usage first
        result = await meter.record_usage("agent_1", "user_1", "skill", "act")
        usage_id = result["usage_id"]

        with patch("isg_agent.payments.usage_meter.stripe") as mock_stripe_mod:
            mock_event = MagicMock()
            mock_event.identifier = "mtr_evt_123"
            mock_stripe_mod.billing.MeterEvent.create.return_value = mock_event

            report = await meter.report_to_stripe(usage_id, "cus_123")
            assert report["reported"] is True
            assert report["stripe_record_id"] == "mtr_evt_123"


# ===========================================================================
# SkillExecutor — Post-Execute Hook
# ===========================================================================


class TestPostExecuteHook:
    """Tests for the skill executor post-execute hook."""

    @pytest.mark.asyncio
    async def test_hook_set_and_called(self):
        from isg_agent.skills.executor import SkillExecutor

        executor = SkillExecutor()
        hook = AsyncMock()
        executor.set_post_execute_hook(hook)

        # Register a simple skill
        executor.register_skill("test_skill", lambda params: "ok")

        result = await executor.execute("test_skill", {"agent_id": "a1"})
        assert result.success is True

        # Hook should have been called
        hook.assert_awaited_once()
        call_args = hook.call_args
        assert call_args[0][0] == "test_skill"
        assert call_args[0][1] == {"agent_id": "a1"}
        assert call_args[0][2].success is True

    @pytest.mark.asyncio
    async def test_hook_not_called_on_failure(self):
        from isg_agent.skills.executor import SkillExecutor

        executor = SkillExecutor()
        hook = AsyncMock()
        executor.set_post_execute_hook(hook)

        # Execute a non-existent skill (will fail)
        result = await executor.execute("nonexistent_skill", {})
        assert result.success is False

        # Hook should NOT have been called
        hook.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_hook_exception_does_not_break_execution(self):
        from isg_agent.skills.executor import SkillExecutor

        executor = SkillExecutor()
        hook = AsyncMock(side_effect=Exception("Hook crashed"))
        executor.set_post_execute_hook(hook)

        executor.register_skill("test_skill", lambda params: "result")
        result = await executor.execute("test_skill", {})

        # Execution should still succeed despite hook failure
        assert result.success is True
        assert result.output == "result"

    @pytest.mark.asyncio
    async def test_no_hook_by_default(self):
        from isg_agent.skills.executor import SkillExecutor

        executor = SkillExecutor()
        assert executor._post_execute_hooks == []

        executor.register_skill("test_skill", lambda params: "ok")
        result = await executor.execute("test_skill", {})
        assert result.success is True


# ===========================================================================
# API Route Tests
# ===========================================================================


def _create_test_app(
    *,
    auth_user_id: str = "",
    auth_email: str = "",
):
    """Create a test app with payment routes and usage meter."""
    from fastapi import FastAPI

    from isg_agent.api.deps import CurrentUser, require_auth
    from isg_agent.api.routes.payments import router as payments_router

    app = FastAPI()
    app.include_router(payments_router)

    if auth_user_id:
        user = CurrentUser(user_id=auth_user_id, email=auth_email)

        async def _override_auth() -> CurrentUser:
            return user

        app.dependency_overrides[require_auth] = _override_auth

    return app


class TestUsageApiRoutes:
    """Tests for /api/v1/payments/usage/{agent_id}* endpoints."""

    @pytest.mark.asyncio
    async def test_get_skill_usage_no_meter(self):
        app = _create_test_app(auth_user_id="user1", auth_email="u@test.com")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/payments/usage/agent_1")
            assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_get_skill_usage_success(self, tmp_path):
        app = _create_test_app(auth_user_id="user1", auth_email="u@test.com")
        meter = UsageMeter(db_path=str(tmp_path / "test.db"), free_tier_limit=50)
        await meter.init_tables()
        app.state.usage_meter = meter

        # Record some usage
        await meter.record_usage("agent_1", "user1", "skill_a", "act")
        await meter.record_usage("agent_1", "user1", "skill_b", "act")

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/payments/usage/agent_1")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_actions"] == 2
            assert data["free_actions"] == 2
            assert data["billed_actions"] == 0
            assert data["remaining_free"] == 48
            assert data["plan"] == "free"

    @pytest.mark.asyncio
    async def test_get_skill_usage_requires_auth(self):
        app = _create_test_app()  # No auth
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/payments/usage/agent_1")
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_get_skill_usage_history(self, tmp_path):
        app = _create_test_app(auth_user_id="user1", auth_email="u@test.com")
        meter = UsageMeter(db_path=str(tmp_path / "test.db"), free_tier_limit=100)
        await meter.init_tables()
        app.state.usage_meter = meter

        for _ in range(5):
            await meter.record_usage("agent_1", "user1", "skill", "act")

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/payments/usage/agent_1/history?months=3")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["total_actions"] == 5

    @pytest.mark.asyncio
    async def test_get_empty_history(self, tmp_path):
        app = _create_test_app(auth_user_id="user1", auth_email="u@test.com")
        meter = UsageMeter(db_path=str(tmp_path / "test.db"))
        await meter.init_tables()
        app.state.usage_meter = meter

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/payments/usage/agent_1/history")
            assert resp.status_code == 200
            assert resp.json() == []


class TestSubscribeApiRoute:
    """Tests for POST /api/v1/payments/subscribe endpoint."""

    @pytest.mark.asyncio
    async def test_subscribe_no_meter(self):
        app = _create_test_app(auth_user_id="user1", auth_email="u@test.com")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/payments/subscribe",
                json={"agent_id": "agent_1", "plan": "starter"},
            )
            assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_subscribe_success(self, tmp_path):
        # Free plan succeeds without Stripe configured
        app = _create_test_app(auth_user_id="user1", auth_email="u@test.com")
        meter = UsageMeter(db_path=str(tmp_path / "test.db"))
        await meter.init_tables()
        app.state.usage_meter = meter

        mock_audit = AsyncMock()
        app.state.audit_chain = mock_audit

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/payments/subscribe",
                json={"agent_id": "agent_1", "plan": "free"},
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["plan"] == "free"
            assert data["actions_included"] == 50
            assert data["price_cents_monthly"] == 0
            assert data["is_active"] is True

    @pytest.mark.asyncio
    async def test_subscribe_paid_plan_requires_stripe(self, tmp_path):
        # Paid plans are rejected with 400 when Stripe is not configured
        app = _create_test_app(auth_user_id="user1", auth_email="u@test.com")
        meter = UsageMeter(db_path=str(tmp_path / "test.db"))
        await meter.init_tables()
        app.state.usage_meter = meter

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for paid_plan in ("starter", "pro", "enterprise"):
                resp = await client.post(
                    "/api/v1/payments/subscribe",
                    json={"agent_id": "agent_1", "plan": paid_plan},
                )
                assert resp.status_code == 400
                assert "require Stripe payment" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_subscribe_invalid_plan(self, tmp_path):
        app = _create_test_app(auth_user_id="user1", auth_email="u@test.com")
        meter = UsageMeter(db_path=str(tmp_path / "test.db"))
        await meter.init_tables()
        app.state.usage_meter = meter

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/payments/subscribe",
                json={"agent_id": "agent_1", "plan": "ultra_premium"},
            )
            assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_subscribe_requires_auth(self):
        app = _create_test_app()  # No auth
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/payments/subscribe",
                json={"agent_id": "agent_1", "plan": "starter"},
            )
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_subscribe_all_plans(self, tmp_path):
        """Verify free plan succeeds and paid plans are gated when Stripe is absent."""
        app = _create_test_app(auth_user_id="user1", auth_email="u@test.com")
        meter = UsageMeter(db_path=str(tmp_path / "test.db"))
        await meter.init_tables()
        app.state.usage_meter = meter

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for plan_name in PRICING_TIERS:
                resp = await client.post(
                    "/api/v1/payments/subscribe",
                    json={"agent_id": f"agent_{plan_name}", "plan": plan_name},
                )
                if plan_name == "free":
                    assert resp.status_code == 201
                    assert resp.json()["plan"] == plan_name
                else:
                    # Paid plans require Stripe — expect 400 when not configured
                    assert resp.status_code == 400


# ===========================================================================
# Integration: UsageMeter + SkillExecutor
# ===========================================================================


class TestUsageMeterIntegration:
    """Integration tests wiring UsageMeter into SkillExecutor."""

    @pytest.mark.asyncio
    async def test_skill_execution_records_usage(self, tmp_path):
        from isg_agent.skills.executor import SkillExecutor

        db_path = str(tmp_path / "test_integration.db")
        meter = UsageMeter(db_path=db_path, free_tier_limit=10)
        await meter.init_tables()

        executor = SkillExecutor()
        executor.register_skill("greet", lambda params: "hello")

        async def usage_hook(skill_name, parameters, result):
            agent_id = parameters.get("agent_id", "default")
            user_id = parameters.get("user_id", "system")
            await meter.record_usage(agent_id, user_id, skill_name, "")

        executor.set_post_execute_hook(usage_hook)

        # Execute the skill
        result = await executor.execute(
            "greet",
            {"agent_id": "test_agent", "user_id": "test_user"},
        )
        assert result.success is True

        # Check that usage was recorded
        summary = await meter.get_usage_summary("test_agent")
        assert summary["total_actions"] == 1
        assert summary["free_actions"] == 1

    @pytest.mark.asyncio
    async def test_multiple_skills_accumulate(self, tmp_path):
        from isg_agent.skills.executor import SkillExecutor

        db_path = str(tmp_path / "test_accumulate.db")
        meter = UsageMeter(db_path=db_path, free_tier_limit=100)
        await meter.init_tables()

        executor = SkillExecutor()
        executor.register_skill("skill_a", lambda params: "a")
        executor.register_skill("skill_b", lambda params: "b")

        async def usage_hook(skill_name, parameters, result):
            await meter.record_usage(
                parameters.get("agent_id", "default"),
                parameters.get("user_id", "system"),
                skill_name, "",
            )

        executor.set_post_execute_hook(usage_hook)

        # Execute multiple skills
        for _ in range(5):
            await executor.execute("skill_a", {"agent_id": "ag", "user_id": "u"})
        for _ in range(3):
            await executor.execute("skill_b", {"agent_id": "ag", "user_id": "u"})

        summary = await meter.get_usage_summary("ag")
        assert summary["total_actions"] == 8
        assert summary["free_actions"] == 8
        assert summary["billed_actions"] == 0
